"""app/garmin_push.py -- pushing a planned session's Garmin `.FIT` workout to
the athlete's intervals.icu calendar (see that module's docstring for the
full mechanism: intervals.icu's own Garmin Connect integration is what
actually forwards the pushed event to the watch).

No real HTTP: every intervals.icu call is served by an `httpx.MockTransport`
handler, same convention as tests/api/test_sync.py and
tests/api/test_workouts_sync_route.py's `_force_mock_transport` (used here
for `push_on_demand`/`push_session_to_intervals` calls that build their own
`IntervalsClient` with no injected transport).

Uses the real `FileStore` (via the `athletes_dir` fixture) the same way
test_garmin_route.py does, appending real `Session`/`WeekPlan` objects to an
existing week on file rather than mocking the store.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import date
from pathlib import Path

import httpx
import pytest
from swim_coach.garmin_export import to_garmin_fit_workout
from swim_coach.models import Session, WorkoutStep, WorkoutStructure, WorkoutTarget
from swim_coach.store import FileStore

from app.garmin_push import (
    _SESSION_SPORT_TO_INTERVALS_TYPE,
    build_workout_event,
    push_on_demand,
    push_session_to_intervals,
)
from app.sync import IntervalsAthleteConfig, IntervalsClient, SYNC_NOT_CONFIGURED_ERROR

ISO_WEEK = "2026-W28"

STRUCTURED = WorkoutStructure(
    items=[
        WorkoutStep(
            label="4x200 @ Z3",
            role="interval",
            duration_kind="distance_m",
            duration_value=800,
            target=WorkoutTarget(basis="absolute", low=90.0, high=95.0),
            modality="swim",
        ),
    ]
)


def _session(athlete_id, *, sport="swim_pool", structured=STRUCTURED, day=8, purpose="garmin push test"):
    return Session(
        id=uuid.uuid4(),
        athlete_id=athlete_id,
        date=date(2026, 7, day),
        sport=sport,
        source="ai_coach",
        duration_min=30.0,
        distance_m=1000 if structured is not None else None,
        intensity={"anchor": "css_pace", "zone": "Z3"} if sport != "recovery" else {"anchor": "rpe"},
        purpose=purpose,
        structure="Main set: 4x200 @ Z3" if structured is not None else None,
        structured=structured,
        status="planned",
    )


def _add_session(athletes_dir: Path, session: Session) -> None:
    store = FileStore(base_dir=athletes_dir)
    week = store.load_week("renee", ISO_WEEK)
    week.sessions.append(session)
    store.save_week("renee", week)


def _force_mock_transport(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    """See test_workouts_sync_route.py's identically-named helper --
    `push_on_demand`/`push_session_to_intervals` (like `sync_on_demand`)
    build their own `IntervalsClient` with no injected transport when the
    caller doesn't hand one in, so every `httpx.Client` app.sync constructs
    must be forced onto an `httpx.MockTransport`."""
    real_client_cls = httpx.Client

    def fake_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client_cls(*args, **kwargs)

    monkeypatch.setattr("app.sync.httpx.Client", fake_client)


def _bulk_ok_handler(captured_events: list):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/events/bulk"):
            body = json.loads(request.content)
            captured_events.extend(body)
            return httpx.Response(200, json=[{"id": i} for i in range(len(body))])
        return httpx.Response(404, json={"error": "not found"})

    return handler


# --- build_workout_event ----------------------------------------------------


def test_build_workout_event_swim_pool_maps_to_swim_type(athletes_dir: Path) -> None:
    store = FileStore(base_dir=athletes_dir)
    athlete_id = store.load_athlete("renee").id
    session = _session(athlete_id, sport="swim_pool")

    event = build_workout_event(session)

    assert event["category"] == "WORKOUT"
    assert event["type"] == "Swim"
    assert event["external_id"] == str(session.id)
    assert event["name"] == session.purpose
    assert event["start_date_local"] == f"{session.date.isoformat()}T00:00:00"
    assert event["filename"] == f"session-{session.id}.fit"

    expected_bytes = to_garmin_fit_workout(session.structured, sport="swim", name=session.purpose)
    assert base64.b64decode(event["file_contents_base64"]) == expected_bytes


def test_build_workout_event_swim_ow_also_maps_to_swim_type(athletes_dir: Path) -> None:
    store = FileStore(base_dir=athletes_dir)
    athlete_id = store.load_athlete("renee").id
    session = _session(athlete_id, sport="swim_ow")

    event = build_workout_event(session)
    assert event["type"] == "Swim"


def test_build_workout_event_strength_maps_to_weighttraining_type(athletes_dir: Path) -> None:
    store = FileStore(base_dir=athletes_dir)
    athlete_id = store.load_athlete("renee").id
    session = _session(athlete_id, sport="strength")

    event = build_workout_event(session)

    assert event["type"] == "WeightTraining"
    expected_bytes = to_garmin_fit_workout(session.structured, sport="strength", name=session.purpose)
    assert base64.b64decode(event["file_contents_base64"]) == expected_bytes


def test_sport_to_intervals_type_mapping_is_exactly_the_documented_three() -> None:
    # Locks in the brief's exact mapping so a future edit can't silently
    # drop/rename one of the three supported sports.
    assert _SESSION_SPORT_TO_INTERVALS_TYPE == {
        "swim_pool": "Swim",
        "swim_ow": "Swim",
        "strength": "WeightTraining",
    }


def test_build_workout_event_raises_for_no_structured_data(athletes_dir: Path) -> None:
    store = FileStore(base_dir=athletes_dir)
    athlete_id = store.load_athlete("renee").id
    session = _session(athlete_id, sport="swim_pool", structured=None)

    with pytest.raises(ValueError, match="structured"):
        build_workout_event(session)


def test_build_workout_event_raises_for_unsupported_sport(athletes_dir: Path) -> None:
    store = FileStore(base_dir=athletes_dir)
    athlete_id = store.load_athlete("renee").id
    session = _session(athlete_id, sport="recovery")

    with pytest.raises(ValueError, match="recovery"):
        build_workout_event(session)


# --- push_session_to_intervals -----------------------------------------------


def test_push_session_to_intervals_pushes_and_summarizes(athletes_dir: Path) -> None:
    store = FileStore(base_dir=athletes_dir)
    athlete_id = store.load_athlete("renee").id
    session = _session(athlete_id, sport="swim_pool")
    cfg = IntervalsAthleteConfig(slug="renee", intervals_athlete_id="i999", api_key="test-key")

    captured: list = []
    client = IntervalsClient("i999", "test-key", transport=httpx.MockTransport(_bulk_ok_handler(captured)))

    result = push_session_to_intervals(session, cfg=cfg, client=client)

    assert result == {
        "pushed": True,
        "session_id": str(session.id),
        "date": session.date.isoformat(),
        "type": "Swim",
    }
    assert len(captured) == 1
    assert captured[0]["external_id"] == str(session.id)


# --- push_on_demand ------------------------------------------------------------


def test_push_on_demand_missing_config_is_not_configured_error(
    athletes_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("INTERVALS_SYNC_CONFIG", raising=False)
    store = FileStore(base_dir=athletes_dir)

    result = push_on_demand(store, "renee", iso_week=ISO_WEEK)

    assert result == {"error": SYNC_NOT_CONFIGURED_ERROR}


def test_push_on_demand_athlete_not_in_config_is_not_configured_error(
    athletes_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "INTERVALS_SYNC_CONFIG",
        json.dumps([{"slug": "andrew", "intervals_athlete_id": "i-andrew", "api_key": "k"}]),
    )
    store = FileStore(base_dir=athletes_dir)

    result = push_on_demand(store, "renee", iso_week=ISO_WEEK)

    assert result == {"error": SYNC_NOT_CONFIGURED_ERROR}


def test_push_on_demand_single_session_id_pushes_it(
    athletes_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "INTERVALS_SYNC_CONFIG",
        json.dumps([{"slug": "renee", "intervals_athlete_id": "i999", "api_key": "k"}]),
    )
    store = FileStore(base_dir=athletes_dir)
    athlete_id = store.load_athlete("renee").id
    session = _session(athlete_id, sport="swim_pool")
    _add_session(athletes_dir, session)

    captured: list = []
    _force_mock_transport(monkeypatch, _bulk_ok_handler(captured))

    result = push_on_demand(store, "renee", session_id=str(session.id))

    assert result["pushed"] == 1
    assert result["skipped"] == 0
    assert result["failed"] == 0
    assert result["results"] == [
        {"pushed": True, "session_id": str(session.id), "date": session.date.isoformat(), "type": "Swim"}
    ]
    assert len(captured) == 1


def test_push_on_demand_unknown_session_id_is_a_clean_error(
    athletes_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "INTERVALS_SYNC_CONFIG",
        json.dumps([{"slug": "renee", "intervals_athlete_id": "i999", "api_key": "k"}]),
    )
    store = FileStore(base_dir=athletes_dir)

    result = push_on_demand(store, "renee", session_id=str(uuid.uuid4()))

    assert "error" in result
    assert "no such session" in result["error"]


def test_push_on_demand_neither_session_id_nor_iso_week_is_a_clean_error(
    athletes_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "INTERVALS_SYNC_CONFIG",
        json.dumps([{"slug": "renee", "intervals_athlete_id": "i999", "api_key": "k"}]),
    )
    store = FileStore(base_dir=athletes_dir)

    result = push_on_demand(store, "renee")

    assert "error" in result


def test_push_on_demand_iso_week_skips_unpushable_sessions_not_fatal(
    athletes_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "INTERVALS_SYNC_CONFIG",
        json.dumps([{"slug": "renee", "intervals_athlete_id": "i999", "api_key": "k"}]),
    )
    store = FileStore(base_dir=athletes_dir)
    athlete_id = store.load_athlete("renee").id

    pushable = _session(athlete_id, sport="swim_pool", day=8, purpose="pushable session")
    no_structure = _session(athlete_id, sport="swim_pool", structured=None, day=9, purpose="no structure")
    unsupported_sport = _session(athlete_id, sport="recovery", day=10, purpose="unsupported sport")

    for s in (pushable, no_structure, unsupported_sport):
        _add_session(athletes_dir, s)

    captured: list = []
    _force_mock_transport(monkeypatch, _bulk_ok_handler(captured))

    result = push_on_demand(store, "renee", iso_week=ISO_WEEK)

    # The fixture week (athletes/renee's committed 2026-W28) already has its
    # own sessions predating `structured` (all structured=None, same as
    # test_garmin_route.py's unstructured_session) -- assert on the three
    # sessions this test itself added, not absolute totals, so this doesn't
    # depend on what else happens to be committed in that week.
    assert result["failed"] == 0
    only_pushed_ids = {e["external_id"] for e in captured}
    assert only_pushed_ids == {str(pushable.id)}  # only the one pushable session hit the network

    result_ids = {r["session_id"]: r for r in result["results"]}
    assert result_ids[str(pushable.id)]["pushed"] is True
    assert result_ids[str(no_structure.id)]["pushed"] is False
    assert result_ids[str(no_structure.id)]["reason"] == "no structured workout data"
    assert result_ids[str(unsupported_sport.id)]["pushed"] is False
    assert result_ids[str(unsupported_sport.id)]["reason"] == "unsupported sport 'recovery'"


def test_push_on_demand_unknown_iso_week_is_a_clean_error(
    athletes_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "INTERVALS_SYNC_CONFIG",
        json.dumps([{"slug": "renee", "intervals_athlete_id": "i999", "api_key": "k"}]),
    )
    store = FileStore(base_dir=athletes_dir)

    result = push_on_demand(store, "renee", iso_week="2099-W01")

    assert "error" in result
    assert "no such week" in result["error"]


def test_push_on_demand_upstream_failure_is_counted_failed_not_fatal(
    athletes_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "INTERVALS_SYNC_CONFIG",
        json.dumps([{"slug": "renee", "intervals_athlete_id": "i999", "api_key": "k"}]),
    )
    store = FileStore(base_dir=athletes_dir)
    athlete_id = store.load_athlete("renee").id
    session = _session(athlete_id, sport="swim_pool")
    _add_session(athletes_dir, session)

    def failing_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "intervals.icu is down"})

    _force_mock_transport(monkeypatch, failing_handler)

    result = push_on_demand(store, "renee", session_id=str(session.id))

    assert result["pushed"] == 0
    assert result["failed"] == 1
    assert result["skipped"] == 0
