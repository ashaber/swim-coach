"""Direct tests for the tool handlers, independent of the chat/streaming
layer -- exercises the real engine (`swim_coach.adapt`, `swim_coach.load`)
against the isolated per-test athlete tree copy."""

from __future__ import annotations

import base64
import json
import uuid
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest
from fakes import SpyFeedbackStore, make_workout
from swim_coach.models import (
    MacroBlock,
    MacroPlan,
    Session,
    WorkoutAnalytics,
    WorkoutLap,
    WorkoutPause,
)
from swim_coach.store import FileStore

from app.tools import GET_WORKOUTS_CAP, SYNC_WORKOUTS_WINDOW_DAYS, build_tool_handlers

# Fixed IDs/names from the real athletes/renee/ test tree (copied into
# athletes_dir by conftest.py) -- see events.yaml/plan/macro.yaml.
GREECE_EVENT_NAME = "UltraSwim 33.3 Greece (Skopelos) — single-day 33.3 km continuous"

REPO_ROOT = Path(__file__).resolve().parents[2]
FIT_FIXTURE = REPO_ROOT / "tests" / "unit" / "fixtures" / "fit" / "real_swim.fit"
_no_fit_fixture = pytest.mark.skipif(
    not FIT_FIXTURE.exists(), reason="no real .fit fixture at tests/unit/fixtures/fit/real_swim.fit"
)


def test_propose_adaptation_returns_draft_without_persisting(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    result = handlers["propose_adaptation"]({"iso_week": "2026-W30"})

    assert "error" not in result
    assert result["iso_week"] == "2026-W30"
    assert result["draft"] is True
    assert result["persisted"] is False
    assert result["target_volume_m"] > 0
    assert result["rationale"] is not None

    week_file = athletes_dir / "renee" / "plan" / "weeks" / "2026-W30.yaml"
    assert not week_file.exists()


def test_propose_adaptation_missing_current_week_is_an_error(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    # 2026-W50 has no week plan for W49 to adapt from.
    result = handlers["propose_adaptation"]({"iso_week": "2026-W50"})
    assert "error" in result


def test_propose_adaptation_invalid_iso_week_is_an_error(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    result = handlers["propose_adaptation"]({"iso_week": "not-a-week"})
    assert "error" in result


def test_propose_adaptation_prior_week_predating_macro_is_a_calm_error(athletes_dir) -> None:
    # Regression test for tonight's real bug: after replace_macro_plan moves
    # the macro to a new event with a later start date, an OLD week plan
    # from before that start date can still be sitting on disk. Simulate
    # that here -- a week file at 2026-W27 (the real macro's base block
    # starts 2026-07-06, i.e. W28) standing in for a stale/pre-replacement
    # week -- and confirm propose_adaptation refuses with the new,
    # non-alarming, action-directing message rather than silently adapting
    # from it.
    store = FileStore(base_dir=athletes_dir)
    stale_week = store.load_week("renee", "2026-W28")
    stale_week = stale_week.model_copy(update={"iso_week": "2026-W27"})
    store.save_week("renee", stale_week)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    result = handlers["propose_adaptation"]({"iso_week": "2026-W28"})

    assert "error" in result
    assert "predates the current macro" in result["error"]
    assert "2026-07-06" in result["error"]  # macro's actual start date
    assert "create_week_plan" in result["error"]
    assert "2026-W28" in result["error"]


def test_propose_adaptation_prior_week_after_macro_end_points_at_a_new_macro(athletes_dir) -> None:
    # Distinct from the predates-start case above: here the prior week (and
    # therefore the target iso_week too, since it's only 7 days later) falls
    # AFTER the current macro's own end date -- e.g. the athlete already
    # raced and is asking about a week beyond the whole plan. Found during
    # review: the original single-branch check reused the "predates" message
    # verbatim for this case too, wrongly claiming the macro "starts
    # 2026-07-06" and directing to create_week_plan -- which would itself
    # refuse for the exact same range reason, trading one dead end for
    # another. Confirm the message here is accurate (says the macro *ends*,
    # not "predates"/"starts") and points at building a new macro instead.
    store = FileStore(base_dir=athletes_dir)
    macro = store.load_macro("renee")
    macro_end = macro.blocks[-1].end_date
    assert macro_end.isoformat() == "2026-09-13"

    stale_week = store.load_week("renee", "2026-W28")
    stale_week = stale_week.model_copy(update={"iso_week": "2026-W39"})
    store.save_week("renee", stale_week)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    result = handlers["propose_adaptation"]({"iso_week": "2026-W40"})

    assert "error" in result
    assert "falls after" in result["error"]
    assert "predates" not in result["error"]
    assert "2026-09-13" in result["error"]  # macro's actual end date
    assert "draft_macro_plan" in result["error"] or "replace_macro_plan" in result["error"]
    assert "2026-W40" in result["error"]


def test_propose_adaptation_in_range_prior_week_is_unaffected_by_the_new_check(athletes_dir) -> None:
    # Regression check: the new out-of-range guard must not disturb the
    # ordinary, already-correct in-range case -- 2026-W29 (the real prior
    # week on file) falls inside the macro's base block, same as before
    # Part 1's fix.
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    result = handlers["propose_adaptation"]({"iso_week": "2026-W30"})

    assert "error" not in result
    assert result["iso_week"] == "2026-W30"
    assert result["persisted"] is False


def test_get_plan_summary_matches_engine_summarize_shape(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    result = handlers["get_plan_summary"]({"weeks": 4})
    assert result["athlete"] == "renee"
    assert result["weeks"] == 4
    assert "volume_m" in result
    assert "compliance_pct" in result


def test_log_open_question_calls_save_feedback_with_research_question_shape(
    athletes_dir, run_tag
) -> None:
    spy = SpyFeedbackStore(FileStore(base_dir=athletes_dir))
    handlers = build_tool_handlers(spy, slug="renee", expert_mode=True)

    question = f"is there swim-specific taper research beyond the swim-adapted cycling data? [{run_tag}]"
    result = handlers["log_open_question"]({"question": question, "topic": "taper"})

    assert result["logged"] is True
    assert len(spy.saved) == 1
    entry = spy.saved[0]
    assert entry.type == "research_question"
    assert entry.source == "coach"
    assert entry.body == question
    assert entry.context == {"topic": "taper", "expert_mode": True}
    assert entry.athlete_id == spy.load_athlete("renee").id


def test_log_open_question_requires_question_and_topic(athletes_dir) -> None:
    spy = SpyFeedbackStore(FileStore(base_dir=athletes_dir))
    handlers = build_tool_handlers(spy, slug="renee", expert_mode=False)
    result = handlers["log_open_question"]({"question": "", "topic": ""})
    assert "error" in result
    assert spy.saved == []


def _save(store: FileStore, **overrides) -> None:
    store.save_workout("renee", make_workout(**overrides))


def test_get_workouts_filters_by_date_range_inclusive_boundaries(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    _save(store, date=date(2026, 1, 4), distance_m=1000)
    _save(store, date=date(2026, 1, 5), distance_m=2000)
    _save(store, date=date(2026, 1, 10), distance_m=3000)
    _save(store, date=date(2026, 1, 11), distance_m=4000)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    result = handlers["get_workouts"]({"start_date": "2026-01-05", "end_date": "2026-01-10"})

    assert "error" not in result
    dates = [w["date"] for w in result["workouts"]]
    assert dates == ["2026-01-05", "2026-01-10"]
    assert result["count"] == 2
    assert result["truncated"] is False


def test_get_workouts_single_day_defaults_end_date_to_start_date(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    _save(store, date=date(2026, 1, 20), distance_m=1500)
    _save(store, date=date(2026, 1, 21), distance_m=1600)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    result = handlers["get_workouts"]({"start_date": "2026-01-20"})

    assert result["count"] == 1
    assert result["workouts"][0]["date"] == "2026-01-20"


def test_get_workouts_caps_results_and_sets_truncated(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    for day in range(1, 26):
        _save(store, date=date(2026, 2, day), distance_m=1000 + day)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    result = handlers["get_workouts"]({"start_date": "2026-02-01", "end_date": "2026-02-25"})

    assert result["count"] == GET_WORKOUTS_CAP
    assert len(result["workouts"]) == GET_WORKOUTS_CAP
    assert result["truncated"] is True
    assert result["workouts"][0]["date"] == "2026-02-01"


def test_get_workouts_derived_counts_present_and_arrays_absent(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    _save(
        store,
        date=date(2026, 3, 1),
        laps=[WorkoutLap(index=0, duration_s=60.0, distance_m=100.0)],
        pauses=[WorkoutPause(start_offset_s=10.0, duration_s=5.0, source="gap")],
    )
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    result = handlers["get_workouts"]({"start_date": "2026-03-01"})

    workout = result["workouts"][0]
    assert workout["lap_count"] == 1
    assert workout["length_count"] == 0
    assert workout["pause_count"] == 1
    assert "laps" not in workout
    assert "lengths" not in workout
    assert "pauses" not in workout


def test_get_workouts_analytics_passed_through(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    _save(
        store,
        date=date(2026, 3, 5),
        avg_hr=120,
        max_hr=150,
        analytics=WorkoutAnalytics(cardiac_drift_pct=6.2, split_label="positive"),
    )
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    result = handlers["get_workouts"]({"start_date": "2026-03-05"})

    workout = result["workouts"][0]
    assert workout["avg_hr"] == 120
    assert workout["max_hr"] == 150
    assert workout["analytics"]["cardiac_drift_pct"] == 6.2
    assert workout["analytics"]["split_label"] == "positive"


def test_get_workouts_no_analytics_is_none(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    _save(store, date=date(2026, 3, 10))
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    result = handlers["get_workouts"]({"start_date": "2026-03-10"})

    assert result["workouts"][0]["analytics"] is None


def test_get_workouts_invalid_start_date_is_an_error(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    result = handlers["get_workouts"]({"start_date": "not-a-date"})
    assert "error" in result


def test_get_workouts_invalid_end_date_is_an_error(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    result = handlers["get_workouts"]({"start_date": "2026-01-01", "end_date": "not-a-date"})
    assert "error" in result


def test_get_workouts_missing_start_date_is_an_error(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    result = handlers["get_workouts"]({})
    assert "error" in result


def test_get_workouts_end_before_start_is_an_error(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    result = handlers["get_workouts"]({"start_date": "2026-01-10", "end_date": "2026-01-01"})
    assert "error" in result


def test_get_workouts_empty_range_is_not_an_error(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    result = handlers["get_workouts"]({"start_date": "2019-01-01", "end_date": "2019-01-31"})
    assert "error" not in result
    assert result == {"workouts": [], "count": 0, "truncated": False}


def test_get_workouts_unknown_athlete_behaves_like_other_handlers(athletes_dir) -> None:
    # Consistent with get_plan_summary/propose_adaptation's engine-level
    # handlers: list_workouts on a nonexistent athlete tree returns [] rather
    # than raising, so this returns an empty (not error) result.
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="no-such-athlete", expert_mode=False)
    result = handlers["get_workouts"]({"start_date": "2026-01-01", "end_date": "2026-01-31"})
    assert "error" not in result
    assert result["count"] == 0


# --- sync_workouts -----------------------------------------------------------


def _sync_activity(activity_id: str, **overrides) -> dict:
    data = {
        "id": activity_id,
        "start_date_local": "2026-03-14T06:00:00",
        "type": "Swim",
        "source": "GARMIN_CONNECT",
        "distance": 1623,
        "pool_length": 25,
    }
    data.update(overrides)
    return data


def _force_mock_transport(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    """`sync_workouts` builds its own `IntervalsClient` (the `client=None`
    path -- production has no injected client for the tool to use, see
    `app.tools._handle_sync_workouts`), so unlike test_sync.py's tests this
    can't just pass `transport=` directly into a constructor the test calls
    itself. Instead, force every `httpx.Client` app.sync constructs onto an
    `httpx.MockTransport`, matching the same no-network-in-tests standard
    `IntervalsClient(transport=...)` normally satisfies for direct callers."""
    real_client_cls = httpx.Client

    def fake_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client_cls(*args, **kwargs)

    monkeypatch.setattr("app.sync.httpx.Client", fake_client)


@_no_fit_fixture
def test_sync_workouts_scopes_to_bound_athlete_only(athletes_dir, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "INTERVALS_SYNC_CONFIG",
        json.dumps(
            [
                {"slug": "andrew", "intervals_athlete_id": "i-andrew", "api_key": "andrew-key"},
                {"slug": "renee", "intervals_athlete_id": "i-renee", "api_key": "renee-key"},
            ]
        ),
    )
    requested_paths: list[str] = []
    auth_headers: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        auth_headers.append(request.headers.get("authorization", ""))
        if request.url.path.endswith("/activities"):
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={"error": "not found"})

    _force_mock_transport(monkeypatch, handler)
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    result = handlers["sync_workouts"]({})

    assert "error" not in result
    assert requested_paths == ["/api/v1/athlete/i-renee/activities"]
    expected_auth = "Basic " + base64.b64encode(b"API_KEY:renee-key").decode()
    assert auth_headers == [expected_auth]


def test_sync_workouts_uses_a_two_day_window(athletes_dir, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "INTERVALS_SYNC_CONFIG",
        json.dumps([{"slug": "renee", "intervals_athlete_id": "i-renee", "api_key": "renee-key"}]),
    )
    captured_params: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/activities"):
            captured_params.update(dict(request.url.params))
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={"error": "not found"})

    _force_mock_transport(monkeypatch, handler)
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    handlers["sync_workouts"]({})

    oldest = date.fromisoformat(captured_params["oldest"])
    newest = date.fromisoformat(captured_params["newest"])
    # Asserted as a relative delta (not against date.today() directly) so
    # this stays robust to whenever the suite happens to run -- test_sync.py
    # never freezes time for its own window assertions either.
    assert (newest - oldest).days == SYNC_WORKOUTS_WINDOW_DAYS
    assert newest == oldest + timedelta(days=SYNC_WORKOUTS_WINDOW_DAYS)


def test_sync_workouts_missing_config_is_a_friendly_error(
    athletes_dir, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("INTERVALS_SYNC_CONFIG", raising=False)
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    result = handlers["sync_workouts"]({})

    assert result == {"error": "sync not configured for this athlete"}


def test_sync_workouts_athlete_not_in_config_is_a_friendly_error(
    athletes_dir, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The env var itself is fine (andrew is configured) -- just not for the
    # athlete bound to this request.
    monkeypatch.setenv(
        "INTERVALS_SYNC_CONFIG",
        json.dumps([{"slug": "andrew", "intervals_athlete_id": "i-andrew", "api_key": "andrew-key"}]),
    )
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    result = handlers["sync_workouts"]({})

    assert result == {"error": "sync not configured for this athlete"}


@_no_fit_fixture
def test_sync_workouts_successful_sync_returns_counts(
    athletes_dir, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "INTERVALS_SYNC_CONFIG",
        json.dumps([{"slug": "renee", "intervals_athlete_id": "i-renee", "api_key": "renee-key"}]),
    )
    fit_bytes = FIT_FIXTURE.read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/activities"):
            return httpx.Response(200, json=[_sync_activity("i123")])
        if request.url.path == "/api/v1/activity/i123/file":
            return httpx.Response(200, content=fit_bytes)
        return httpx.Response(404, json={"error": "not found"})

    _force_mock_transport(monkeypatch, handler)
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    result = handlers["sync_workouts"]({})

    assert result == {"listed": 1, "new": 1, "saved": 1, "failed": 0}


# --- create_event -------------------------------------------------------------


def test_create_event_persists_and_returns_created_shape(athletes_dir, run_tag) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    name = f"Test New Event [{run_tag}]"

    result = handlers["create_event"](
        {
            "name": name,
            "event_date": "2027-06-01",
            "distance_m": 15000,
            "priority": "B",
            "water_temp_c": 22.5,
            "wetsuit": True,
            "event_format": "multi_day_stage",
        }
    )

    assert "error" not in result
    assert result["created"] is True
    assert result["name"] == name
    assert result["event_date"] == "2027-06-01"
    assert result["distance_m"] == 15000
    assert result["priority"] == "B"
    assert result["water_temp_c"] == 22.5
    assert result["wetsuit"] is True
    assert result["event_format"] == "multi_day_stage"

    reloaded = FileStore(base_dir=athletes_dir).load_events("renee")
    matching = [e for e in reloaded if e.name == name]
    assert len(matching) == 1
    assert str(matching[0].id) == result["id"]
    assert matching[0].athlete_id == store.load_athlete("renee").id


def test_create_event_defaults_and_optional_fields(athletes_dir, run_tag) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    name = f"Test Minimal Event [{run_tag}]"

    result = handlers["create_event"](
        {"name": name, "event_date": "2027-03-01", "distance_m": 5000, "priority": "A"}
    )

    assert "error" not in result
    assert result["event_format"] == "single_day"
    assert result["wetsuit"] is False
    assert result["water_temp_c"] is None


def test_create_event_appends_without_disturbing_existing_events(athletes_dir, run_tag) -> None:
    store = FileStore(base_dir=athletes_dir)
    before = store.load_events("renee")
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    handlers["create_event"](
        {
            "name": f"Test Appended Event [{run_tag}]",
            "event_date": "2027-04-01",
            "distance_m": 8000,
            "priority": "B",
        }
    )

    after = FileStore(base_dir=athletes_dir).load_events("renee")
    assert len(after) == len(before) + 1
    before_ids = {e.id for e in before}
    assert before_ids <= {e.id for e in after}


@pytest.mark.parametrize(
    "overrides,missing_field",
    [
        ({"name": ""}, "name"),
        ({"event_date": ""}, "event_date"),
        ({"distance_m": None}, "distance_m"),
        ({"priority": ""}, "priority"),
    ],
)
def test_create_event_missing_required_field_is_an_error(
    athletes_dir, overrides: dict, missing_field: str
) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    payload = {
        "name": "Test Event",
        "event_date": "2027-01-01",
        "distance_m": 5000,
        "priority": "A",
    }
    payload.update(overrides)

    result = handlers["create_event"](payload)

    assert "error" in result


def test_create_event_invalid_event_date_is_an_error(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    result = handlers["create_event"](
        {"name": "Test Event", "event_date": "not-a-date", "distance_m": 5000, "priority": "A"}
    )
    assert "error" in result


def test_create_event_non_positive_distance_is_an_error(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    result = handlers["create_event"](
        {"name": "Test Event", "event_date": "2027-01-01", "distance_m": 0, "priority": "A"}
    )
    assert "error" in result


def test_create_event_invalid_event_format_is_an_error(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    result = handlers["create_event"](
        {
            "name": "Test Event",
            "event_date": "2027-01-01",
            "distance_m": 5000,
            "priority": "A",
            "event_format": "weekend_only",
        }
    )
    assert "error" in result


# --- draft_macro_plan -----------------------------------------------------------


def test_draft_macro_plan_persists_new_macro_for_a_brand_new_event(athletes_dir, run_tag) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    name = f"Test Macro Event [{run_tag}]"
    handlers["create_event"](
        {"name": name, "event_date": "2027-06-01", "distance_m": 20000, "priority": "B"}
    )

    result = handlers["draft_macro_plan"](
        {
            "event_name": name,
            "current_weekly_volume_m": 15000,
            "start_date": "2027-01-01",
        }
    )

    assert "error" not in result
    assert result["created"] is True
    assert result["event_name"] == name
    assert len(result["blocks"]) == 4
    block_names = [b["name"] for b in result["blocks"]]
    assert block_names == ["base", "build", "peak", "taper"]
    for block in result["blocks"]:
        assert block["weekly_volume_target_m"] >= 0

    reloaded_macro = FileStore(base_dir=athletes_dir).load_macro("renee")
    assert reloaded_macro is not None
    events = FileStore(base_dir=athletes_dir).load_events("renee")
    new_event = next(e for e in events if e.name == name)
    assert reloaded_macro.event_id == new_event.id


def test_draft_macro_plan_refuses_when_macro_already_exists_for_event(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    result = handlers["draft_macro_plan"](
        {"event_name": GREECE_EVENT_NAME, "current_weekly_volume_m": 15000}
    )

    assert "error" in result
    assert "already exists" in result["error"]

    # Untouched -- still the original macro tied to Greece.
    macro = FileStore(base_dir=athletes_dir).load_macro("renee")
    events = FileStore(base_dir=athletes_dir).load_events("renee")
    greece = next(e for e in events if e.name == GREECE_EVENT_NAME)
    assert macro.event_id == greece.id


def test_draft_macro_plan_unknown_event_name_names_existing_events(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    result = handlers["draft_macro_plan"](
        {"event_name": "No Such Event At All", "current_weekly_volume_m": 15000}
    )

    assert "error" in result
    assert GREECE_EVENT_NAME in result["error"]
    assert "Bear Lake Monster 10K (Garden City UT, point-to-point)" in result["error"]


def test_draft_macro_plan_insufficient_runway_is_an_error(athletes_dir, run_tag) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    name = f"Test Sprint Event [{run_tag}]"
    handlers["create_event"](
        {"name": name, "event_date": "2027-01-15", "distance_m": 5000, "priority": "B"}
    )

    result = handlers["draft_macro_plan"](
        {
            "event_name": name,
            "current_weekly_volume_m": 10000,
            "start_date": "2027-01-01",
        }
    )

    assert "error" in result
    # No macro should have been persisted by a failed scaffold attempt.
    assert FileStore(base_dir=athletes_dir).load_macro("renee") is not None


def test_draft_macro_plan_missing_current_weekly_volume_is_an_error(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    result = handlers["draft_macro_plan"]({"event_name": GREECE_EVENT_NAME})
    assert "error" in result


def test_draft_macro_plan_missing_event_name_is_an_error(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    result = handlers["draft_macro_plan"]({"current_weekly_volume_m": 15000})
    assert "error" in result


# --- replace_macro_plan ----------------------------------------------------------


def test_replace_macro_plan_draft_mode_does_not_persist(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    original_macro = FileStore(base_dir=athletes_dir).load_macro("renee")

    result = handlers["replace_macro_plan"](
        {"event_name": GREECE_EVENT_NAME, "current_weekly_volume_m": 18000, "start_date": "2026-01-05"}
    )

    assert "error" not in result
    assert result["persisted"] is False
    assert len(result["blocks"]) == 4
    assert [b["name"] for b in result["blocks"]] == ["base", "build", "peak", "taper"]

    # Untouched -- draft mode never calls save_macro.
    reloaded = FileStore(base_dir=athletes_dir).load_macro("renee")
    assert reloaded == original_macro


def test_replace_macro_plan_draft_mode_confirm_explicitly_false_also_does_not_persist(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    original_macro = FileStore(base_dir=athletes_dir).load_macro("renee")

    result = handlers["replace_macro_plan"](
        {
            "event_name": GREECE_EVENT_NAME,
            "current_weekly_volume_m": 18000,
            "start_date": "2026-01-05",
            "confirm": False,
        }
    )

    assert result["persisted"] is False
    assert FileStore(base_dir=athletes_dir).load_macro("renee") == original_macro


def test_replace_macro_plan_draft_includes_comparison_against_current_macro(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    result = handlers["replace_macro_plan"](
        {"event_name": GREECE_EVENT_NAME, "current_weekly_volume_m": 18000, "start_date": "2026-01-05"}
    )

    assert "error" not in result
    comparison = result["comparison"]
    assert comparison is not None
    assert comparison["old_event_name"] == GREECE_EVENT_NAME
    assert comparison["new_event_name"] == GREECE_EVENT_NAME
    assert comparison["old_peak_weekly_volume_m"] == 26659  # athletes/renee/plan/macro.yaml
    new_peak = next(b["weekly_volume_target_m"] for b in result["blocks"] if b["name"] == "peak")
    assert comparison["new_peak_weekly_volume_m"] == new_peak


def test_replace_macro_plan_confirm_true_persists_and_is_retrievable(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    original_macro = FileStore(base_dir=athletes_dir).load_macro("renee")

    result = handlers["replace_macro_plan"](
        {
            "event_name": GREECE_EVENT_NAME,
            "current_weekly_volume_m": 18000,
            "start_date": "2026-01-05",
            "confirm": True,
        }
    )

    assert "error" not in result
    assert result["persisted"] is True

    reloaded = FileStore(base_dir=athletes_dir).load_macro("renee")
    assert reloaded is not None
    assert reloaded.id != original_macro.id
    assert [b.weekly_volume_target_m for b in reloaded.blocks] == [
        b["weekly_volume_target_m"] for b in result["blocks"]
    ]


def test_replace_macro_plan_works_with_no_prior_macro(athletes_dir) -> None:
    (athletes_dir / "renee" / "plan" / "macro.yaml").unlink()
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    assert FileStore(base_dir=athletes_dir).load_macro("renee") is None

    draft = handlers["replace_macro_plan"](
        {"event_name": GREECE_EVENT_NAME, "current_weekly_volume_m": 18000, "start_date": "2026-01-05"}
    )
    assert "error" not in draft
    assert draft["persisted"] is False
    assert draft["comparison"] is None  # nothing to compare against
    assert FileStore(base_dir=athletes_dir).load_macro("renee") is None

    confirmed = handlers["replace_macro_plan"](
        {
            "event_name": GREECE_EVENT_NAME,
            "current_weekly_volume_m": 18000,
            "start_date": "2026-01-05",
            "confirm": True,
        }
    )
    assert confirmed["persisted"] is True
    reloaded = FileStore(base_dir=athletes_dir).load_macro("renee")
    assert reloaded is not None
    events = FileStore(base_dir=athletes_dir).load_events("renee")
    greece = next(e for e in events if e.name == GREECE_EVENT_NAME)
    assert reloaded.event_id == greece.id


def test_replace_macro_plan_fixes_a_broken_zero_volume_macro_end_to_end(athletes_dir, run_tag) -> None:
    # End-to-end regression test for the reported bug + gap: before Part 1's
    # fix, draft_macro_plan with current_weekly_volume_m=0 silently persisted
    # an all-zero macro, and there was previously no way to fix it afterward
    # (draft_macro_plan refuses once any macro exists). Since scaffold_macro
    # itself can no longer produce that degenerate macro (that's the Part 1
    # fix working), this test constructs a broken all-zero macro directly --
    # standing in for one created by the pre-fix engine, e.g. Andrew's own
    # already-broken Halloween Spook Swim macro -- and confirms
    # replace_macro_plan is the self-service fix.
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    name = f"Test Broken Macro Event [{run_tag}]"
    create_result = handlers["create_event"](
        {"name": name, "event_date": "2027-06-01", "distance_m": 20000, "priority": "B"}
    )
    event_id = uuid.UUID(create_result["id"])
    athlete_id = store.load_athlete("renee").id

    broken_macro = MacroPlan(
        id=uuid.uuid4(),
        athlete_id=athlete_id,
        event_id=event_id,
        blocks=[
            MacroBlock(
                name="base", start_date=date(2027, 1, 4), end_date=date(2027, 3, 1),
                weekly_volume_target_m=0, focus="aerobic base",
            ),
            MacroBlock(
                name="build", start_date=date(2027, 3, 2), end_date=date(2027, 3, 29),
                weekly_volume_target_m=0, focus="race-specific build",
            ),
            MacroBlock(
                name="peak", start_date=date(2027, 3, 30), end_date=date(2027, 4, 19),
                weekly_volume_target_m=0, focus="peak volume",
            ),
            MacroBlock(
                name="taper", start_date=date(2027, 4, 20), end_date=date(2027, 5, 31),
                weekly_volume_target_m=0, focus="taper",
            ),
        ],
    )
    store.save_macro("renee", broken_macro)
    assert all(b.weekly_volume_target_m == 0 for b in broken_macro.blocks)  # confirmed broken

    # draft_macro_plan can't touch it -- confirm the refusal points here.
    refused = handlers["draft_macro_plan"](
        {"event_name": name, "current_weekly_volume_m": 12000, "start_date": "2027-01-01"}
    )
    assert "error" in refused
    assert "replace_macro_plan" in refused["error"]

    # replace_macro_plan is the fix: draft first...
    draft = handlers["replace_macro_plan"](
        {"event_name": name, "current_weekly_volume_m": 12000, "start_date": "2027-01-01"}
    )
    assert "error" not in draft
    assert draft["persisted"] is False
    assert any(b["weekly_volume_target_m"] > 0 for b in draft["blocks"])
    # Still broken on disk -- draft mode didn't touch it.
    assert FileStore(base_dir=athletes_dir).load_macro("renee").blocks == broken_macro.blocks

    # ...then confirm.
    fixed = handlers["replace_macro_plan"](
        {"event_name": name, "current_weekly_volume_m": 12000, "start_date": "2027-01-01", "confirm": True}
    )
    assert fixed["persisted"] is True
    fixed_macro = FileStore(base_dir=athletes_dir).load_macro("renee")
    assert fixed_macro is not None
    assert any(b.weekly_volume_target_m > 0 for b in fixed_macro.blocks)
    assert fixed_macro.event_id == event_id


def test_replace_macro_plan_unknown_event_name_names_existing_events(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    result = handlers["replace_macro_plan"](
        {"event_name": "No Such Event At All", "current_weekly_volume_m": 15000}
    )

    assert "error" in result
    assert GREECE_EVENT_NAME in result["error"]


def test_replace_macro_plan_insufficient_runway_is_an_error(athletes_dir, run_tag) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    name = f"Test Sprint Event Replace [{run_tag}]"
    handlers["create_event"](
        {"name": name, "event_date": "2027-01-15", "distance_m": 5000, "priority": "B"}
    )

    result = handlers["replace_macro_plan"](
        {"event_name": name, "current_weekly_volume_m": 10000, "start_date": "2027-01-01"}
    )

    assert "error" in result


def test_replace_macro_plan_missing_current_weekly_volume_is_an_error(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    result = handlers["replace_macro_plan"]({"event_name": GREECE_EVENT_NAME})
    assert "error" in result


def test_replace_macro_plan_missing_event_name_is_an_error(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    result = handlers["replace_macro_plan"]({"current_weekly_volume_m": 15000})
    assert "error" in result


# --- set_pool_coach_status -------------------------------------------------------


def test_set_pool_coach_status_persists_false(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    assert store.load_athlete("renee").has_pool_coach is True  # default

    result = handlers["set_pool_coach_status"]({"has_pool_coach": False})

    assert result == {"updated": True, "has_pool_coach": False}
    reloaded = FileStore(base_dir=athletes_dir).load_athlete("renee")
    assert reloaded.has_pool_coach is False


def test_set_pool_coach_status_persists_true(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    handlers["set_pool_coach_status"]({"has_pool_coach": False})

    result = handlers["set_pool_coach_status"]({"has_pool_coach": True})

    assert result == {"updated": True, "has_pool_coach": True}
    reloaded = FileStore(base_dir=athletes_dir).load_athlete("renee")
    assert reloaded.has_pool_coach is True


def test_set_pool_coach_status_missing_field_is_an_error(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    result = handlers["set_pool_coach_status"]({})
    assert "error" in result


def test_set_pool_coach_status_non_boolean_is_an_error(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    result = handlers["set_pool_coach_status"]({"has_pool_coach": "yes"})
    assert "error" in result


# --- create_week_plan -----------------------------------------------------------


def test_create_week_plan_persists_a_new_week_from_the_macro(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    # 2026-W30 falls inside the base block (2026-07-06 -> 2026-08-02) and has
    # no existing week file (only W28/W29 exist in the test tree).
    result = handlers["create_week_plan"]({"iso_week": "2026-W30"})

    assert "error" not in result
    assert result["created"] is True
    assert result["iso_week"] == "2026-W30"
    assert result["meso_block"] == "base"
    assert result["target_volume_m"] > 0
    assert len(result["sessions"]) > 0

    reloaded = FileStore(base_dir=athletes_dir).load_week("renee", "2026-W30")
    assert reloaded is not None
    assert reloaded.draft is False
    assert reloaded.target_volume_m == result["target_volume_m"]


def test_create_week_plan_refuses_when_week_already_exists(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    result = handlers["create_week_plan"]({"iso_week": "2026-W28"})

    assert "error" in result
    assert "propose_adaptation" in result["error"]


def test_create_week_plan_no_macro_is_an_error(athletes_dir) -> None:
    (athletes_dir / "renee" / "plan" / "macro.yaml").unlink()
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    result = handlers["create_week_plan"]({"iso_week": "2026-W30"})

    assert "error" in result
    assert "draft_macro_plan" in result["error"]


def test_create_week_plan_invalid_iso_week_is_an_error(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    result = handlers["create_week_plan"]({"iso_week": "not-a-week"})
    assert "error" in result


def test_create_week_plan_missing_iso_week_is_an_error(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    result = handlers["create_week_plan"]({})
    assert "error" in result


def test_create_week_plan_missing_macro_event_is_an_error(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    events = store.load_events("renee")
    remaining = [e for e in events if e.name != GREECE_EVENT_NAME]
    store.save_events("renee", remaining)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    result = handlers["create_week_plan"]({"iso_week": "2026-W30"})

    assert "error" in result
    assert "not found in events.yaml" in result["error"]


def test_create_week_plan_week_outside_macro_range_is_an_error(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    # Well past the macro's taper block (ends 2026-09-13).
    result = handlers["create_week_plan"]({"iso_week": "2027-W01"})

    assert "error" in result


# --- reschedule_session -------------------------------------------------------
# 2026-W28 (2026-07-06 .. 2026-07-12, real test-tree fixture) sessions by
# date: 07-06 swim_pool, 07-07 strength, 07-08 swim_pool, 07-09 swim_ow,
# 07-10 swim_pool, 07-11 recovery, 07-12 recovery.


def test_reschedule_session_moves_date_and_leaves_rest_of_week_untouched(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    original = store.load_week("renee", "2026-W28")
    original_by_id = {s.id: s for s in original.sessions}
    moved_id = next(s.id for s in original.sessions if s.sport == "strength")

    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    result = handlers["reschedule_session"](
        {
            "iso_week": "2026-W28",
            "current_date": "2026-07-07",
            "sport": "strength",
            "new_date": "2026-07-12",
        }
    )

    assert result == {
        "rescheduled": True,
        "iso_week": "2026-W28",
        "sport": "strength",
        "previous_date": "2026-07-07",
        "new_date": "2026-07-12",
    }

    reloaded = FileStore(base_dir=athletes_dir).load_week("renee", "2026-W28")
    assert len(reloaded.sessions) == len(original.sessions)

    moved = next(s for s in reloaded.sessions if s.id == moved_id)
    assert moved.date == date(2026, 7, 12)
    # everything else about the moved session is untouched
    original_moved = original_by_id[moved_id]
    assert moved.sport == original_moved.sport
    assert moved.distance_m == original_moved.distance_m
    assert moved.duration_min == original_moved.duration_min
    assert moved.purpose == original_moved.purpose
    assert moved.structure == original_moved.structure

    # every other session in the week is completely untouched
    for session in reloaded.sessions:
        if session.id == moved_id:
            continue
        original_session = original_by_id[session.id]
        assert session.date == original_session.date
        assert session.sport == original_session.sport
        assert session.distance_m == original_session.distance_m
        assert session.duration_min == original_session.duration_min
        assert session.purpose == original_session.purpose


def test_reschedule_session_ambiguous_match_lists_same_day_sessions(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    week = store.load_week("renee", "2026-W28")
    athlete_id = store.load_athlete("renee").id
    # Construct a genuine ambiguity: two "strength" sessions both dated
    # 2026-07-07 (the fixture only ever has one session per sport per day,
    # so this has to be built by hand).
    duplicate = Session(
        id=uuid.uuid4(),
        athlete_id=athlete_id,
        date=date(2026, 7, 7),
        sport="strength",
        source="ai_coach",
        duration_min=45.0,
        distance_m=None,
        intensity={"anchor": "rpe"},
        purpose="duplicate strength session for ambiguity test",
        structure=None,
        status="planned",
    )
    week.sessions.append(duplicate)
    store.save_week("renee", week)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    result = handlers["reschedule_session"](
        {
            "iso_week": "2026-W28",
            "current_date": "2026-07-07",
            "sport": "strength",
            "new_date": "2026-07-08",
        }
    )

    assert "error" in result
    assert "found 2" in result["error"]
    assert "2026-07-07" in result["error"]

    # untouched -- an ambiguous match must not silently pick one.
    reloaded = FileStore(base_dir=athletes_dir).load_week("renee", "2026-W28")
    assert sum(1 for s in reloaded.sessions if s.sport == "strength") == 2
    assert all(s.date == date(2026, 7, 7) for s in reloaded.sessions if s.sport == "strength")


def test_reschedule_session_no_match_lists_what_is_on_file_that_day(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    # 2026-07-07 is on file, but as "strength" not "swim_ow".
    result = handlers["reschedule_session"](
        {
            "iso_week": "2026-W28",
            "current_date": "2026-07-07",
            "sport": "swim_ow",
            "new_date": "2026-07-08",
        }
    )

    assert "error" in result
    assert "found 0" in result["error"]
    assert "strength" in result["error"]


def test_reschedule_session_cross_week_new_date_refuses(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    # 2026-07-15 falls in 2026-W29, not 2026-W28 -- a different-week move,
    # out of scope for this tool.
    result = handlers["reschedule_session"](
        {
            "iso_week": "2026-W28",
            "current_date": "2026-07-07",
            "sport": "strength",
            "new_date": "2026-07-15",
        }
    )

    assert "error" in result
    assert "propose_adaptation" in result["error"]

    # untouched
    reloaded = FileStore(base_dir=athletes_dir).load_week("renee", "2026-W28")
    strength = next(s for s in reloaded.sessions if s.sport == "strength")
    assert strength.date == date(2026, 7, 7)


def test_reschedule_session_week_does_not_exist_is_an_error(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    # 2026-W40 has no week file at all in the test tree; both dates fall
    # within that same ISO week's own span (2026-09-28 .. 2026-10-04) so the
    # cross-week guard doesn't mask the missing-week error.
    result = handlers["reschedule_session"](
        {
            "iso_week": "2026-W40",
            "current_date": "2026-09-28",
            "sport": "swim_pool",
            "new_date": "2026-09-29",
        }
    )

    assert "error" in result
    assert "2026-W40" in result["error"]


def test_reschedule_session_invalid_iso_week_is_an_error(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    result = handlers["reschedule_session"](
        {"iso_week": "not-a-week", "current_date": "2026-07-07", "sport": "strength", "new_date": "2026-07-08"}
    )
    assert "error" in result


def test_reschedule_session_invalid_current_date_is_an_error(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    result = handlers["reschedule_session"](
        {"iso_week": "2026-W28", "current_date": "not-a-date", "sport": "strength", "new_date": "2026-07-08"}
    )
    assert "error" in result


def test_reschedule_session_invalid_new_date_is_an_error(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    result = handlers["reschedule_session"](
        {"iso_week": "2026-W28", "current_date": "2026-07-07", "sport": "strength", "new_date": "not-a-date"}
    )
    assert "error" in result


@pytest.mark.parametrize(
    "overrides,missing_field",
    [
        ({"iso_week": ""}, "iso_week"),
        ({"current_date": ""}, "current_date"),
        ({"sport": ""}, "sport"),
        ({"new_date": ""}, "new_date"),
    ],
)
def test_reschedule_session_missing_required_field_is_an_error(
    athletes_dir, overrides: dict, missing_field: str
) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    payload = {
        "iso_week": "2026-W28",
        "current_date": "2026-07-07",
        "sport": "strength",
        "new_date": "2026-07-08",
    }
    payload.update(overrides)

    result = handlers["reschedule_session"](payload)

    assert "error" in result


# --- replace_week_plan ---------------------------------------------------------
# 2026-W28/W29 already have real week files in the test tree (base block,
# 2026-07-06 .. 2026-08-02); 2026-W30 has none yet (same gap create_week_plan's
# own tests use).


def test_replace_week_plan_draft_mode_does_not_persist(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    original_week = FileStore(base_dir=athletes_dir).load_week("renee", "2026-W28")

    result = handlers["replace_week_plan"]({"iso_week": "2026-W28"})

    assert "error" not in result
    assert result["persisted"] is False
    assert result["iso_week"] == "2026-W28"
    assert result["target_volume_m"] > 0
    assert len(result["sessions"]) > 0

    # Untouched -- draft mode never calls save_week.
    reloaded = FileStore(base_dir=athletes_dir).load_week("renee", "2026-W28")
    assert reloaded == original_week


def test_replace_week_plan_draft_mode_confirm_explicitly_false_also_does_not_persist(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    original_week = FileStore(base_dir=athletes_dir).load_week("renee", "2026-W28")

    result = handlers["replace_week_plan"]({"iso_week": "2026-W28", "confirm": False})

    assert result["persisted"] is False
    assert FileStore(base_dir=athletes_dir).load_week("renee", "2026-W28") == original_week


def test_replace_week_plan_draft_includes_comparison_against_current_week(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    original_week = FileStore(base_dir=athletes_dir).load_week("renee", "2026-W28")

    result = handlers["replace_week_plan"]({"iso_week": "2026-W28"})

    assert "error" not in result
    comparison = result["comparison"]
    assert comparison is not None
    assert comparison["old_target_volume_m"] == original_week.target_volume_m
    assert comparison["old_session_count"] == len(original_week.sessions)
    assert comparison["new_target_volume_m"] == result["target_volume_m"]
    assert comparison["new_session_count"] == len(result["sessions"])


def test_replace_week_plan_confirm_true_persists_and_overwrites_existing_week(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    original_week = FileStore(base_dir=athletes_dir).load_week("renee", "2026-W28")

    result = handlers["replace_week_plan"]({"iso_week": "2026-W28", "confirm": True})

    assert "error" not in result
    assert result["persisted"] is True

    reloaded = FileStore(base_dir=athletes_dir).load_week("renee", "2026-W28")
    assert reloaded is not None
    # Overwritten -- a freshly generated week, not the original object on disk.
    assert reloaded.id != original_week.id
    assert reloaded.target_volume_m == result["target_volume_m"]
    assert len(reloaded.sessions) == len(result["sessions"])


def test_replace_week_plan_works_when_no_week_exists_yet(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    assert FileStore(base_dir=athletes_dir).load_week("renee", "2026-W30") is None

    draft = handlers["replace_week_plan"]({"iso_week": "2026-W30"})
    assert "error" not in draft
    assert draft["persisted"] is False
    assert draft["comparison"] is None  # nothing to compare against
    assert FileStore(base_dir=athletes_dir).load_week("renee", "2026-W30") is None

    confirmed = handlers["replace_week_plan"]({"iso_week": "2026-W30", "confirm": True})
    assert confirmed["persisted"] is True
    reloaded = FileStore(base_dir=athletes_dir).load_week("renee", "2026-W30")
    assert reloaded is not None
    assert reloaded.iso_week == "2026-W30"


def test_replace_week_plan_week_outside_macro_range_is_a_clean_error(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    # Well past the macro's taper block (ends 2026-09-13) -- must return a
    # calm {"error": ...}, never raise.
    result = handlers["replace_week_plan"]({"iso_week": "2027-W01"})

    assert "error" in result
    # Nothing persisted for a week that was never on file.
    assert FileStore(base_dir=athletes_dir).load_week("renee", "2027-W01") is None


def test_replace_week_plan_no_macro_is_an_error(athletes_dir) -> None:
    (athletes_dir / "renee" / "plan" / "macro.yaml").unlink()
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    result = handlers["replace_week_plan"]({"iso_week": "2026-W28"})

    assert "error" in result
    assert "draft_macro_plan" in result["error"]


def test_replace_week_plan_invalid_iso_week_is_an_error(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    result = handlers["replace_week_plan"]({"iso_week": "not-a-week"})
    assert "error" in result


def test_replace_week_plan_missing_iso_week_is_an_error(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    result = handlers["replace_week_plan"]({})
    assert "error" in result


# --- replace_week_plan session_overrides ----------------------------------------
# Real bug, real athlete: a first-swim-back-after-a-break session computed a
# technically ramp-safe but unwanted distance, and there was no tool that could
# just set a specific session's number -- create_week_plan refuses (week
# exists), propose_adaptation refuses (no prior week), and replace_week_plan on
# its own just recomputes the identical deterministic number again. This is the
# fix: an explicit override applied on top of the otherwise-normal draft.


def test_replace_week_plan_session_override_sets_distance_and_reestimates_duration(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    baseline = handlers["replace_week_plan"]({"iso_week": "2026-W28"})
    assert "error" not in baseline
    target = baseline["sessions"][0]
    original_duration = target["duration_min"]
    new_distance = (target["distance_m"] or 1000) / 2  # deliberately different from computed

    result = handlers["replace_week_plan"]({
        "iso_week": "2026-W28",
        "session_overrides": [{"date": target["date"], "sport": target["sport"], "distance_m": new_distance}],
    })

    assert "error" not in result
    overridden = next(s for s in result["sessions"] if s["date"] == target["date"] and s["sport"] == target["sport"])
    assert overridden["distance_m"] == new_distance
    # Duration was re-estimated from the new distance, not left stale.
    assert overridden["duration_min"] != original_duration

    # Every other session is untouched.
    others_before = [s for s in baseline["sessions"] if s["date"] != target["date"] or s["sport"] != target["sport"]]
    others_after = [s for s in result["sessions"] if s["date"] != target["date"] or s["sport"] != target["sport"]]
    assert others_before == others_after


def test_replace_week_plan_session_override_explicit_duration_is_not_reestimated(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    baseline = handlers["replace_week_plan"]({"iso_week": "2026-W28"})
    target = baseline["sessions"][0]

    result = handlers["replace_week_plan"]({
        "iso_week": "2026-W28",
        "session_overrides": [{
            "date": target["date"], "sport": target["sport"], "distance_m": 500, "duration_min": 12.5,
        }],
    })

    assert "error" not in result
    overridden = next(s for s in result["sessions"] if s["date"] == target["date"] and s["sport"] == target["sport"])
    assert overridden["distance_m"] == 500
    assert overridden["duration_min"] == 12.5


def test_replace_week_plan_session_override_persists_only_on_confirm(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    baseline = handlers["replace_week_plan"]({"iso_week": "2026-W28"})
    target = baseline["sessions"][0]
    override = [{"date": target["date"], "sport": target["sport"], "distance_m": 750}]

    draft = handlers["replace_week_plan"]({"iso_week": "2026-W28", "session_overrides": override})
    assert draft["persisted"] is False
    on_disk = FileStore(base_dir=athletes_dir).load_week("renee", "2026-W28")
    assert not any(s.date.isoformat() == target["date"] and s.distance_m == 750 for s in on_disk.sessions)

    confirmed = handlers["replace_week_plan"]({
        "iso_week": "2026-W28", "session_overrides": override, "confirm": True,
    })
    assert confirmed["persisted"] is True
    on_disk = FileStore(base_dir=athletes_dir).load_week("renee", "2026-W28")
    assert any(s.date.isoformat() == target["date"] and s.distance_m == 750 for s in on_disk.sessions)


def test_replace_week_plan_session_override_no_matching_session_is_a_clean_error(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    result = handlers["replace_week_plan"]({
        "iso_week": "2026-W28",
        "session_overrides": [{"date": "2099-01-01", "distance_m": 1000}],
    })

    assert "error" in result
    assert "2099-01-01" in result["error"]


def test_replace_week_plan_session_override_ambiguous_date_without_sport_is_a_clean_error(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    baseline = handlers["replace_week_plan"]({"iso_week": "2026-W28"})

    date_counts = Counter(s["date"] for s in baseline["sessions"])
    multi_session_date = next((d for d, count in date_counts.items() if count > 1), None)
    if multi_session_date is None:
        pytest.skip("this fixture week has no day with more than one session to test ambiguity against")

    result = handlers["replace_week_plan"]({
        "iso_week": "2026-W28",
        "session_overrides": [{"date": multi_session_date, "distance_m": 1000}],
    })

    assert "error" in result
    assert "disambiguate" in result["error"]


def test_replace_week_plan_session_override_missing_both_fields_is_a_clean_error(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    baseline = handlers["replace_week_plan"]({"iso_week": "2026-W28"})
    target = baseline["sessions"][0]

    result = handlers["replace_week_plan"]({
        "iso_week": "2026-W28",
        "session_overrides": [{"date": target["date"], "sport": target["sport"]}],
    })

    assert "error" in result


def test_replace_week_plan_end_to_end_pool_coach_status_change_regression(athletes_dir) -> None:
    # This morning's real bug, end to end: 2026-W28's real fixture sessions
    # are pool_coach-source placeholders (has_pool_coach defaults True).
    # After the athlete says they no longer have a pool coach
    # (set_pool_coach_status(False)), 2026-W28 is stuck with stale
    # pool_coach placeholder content and no tool could regenerate it --
    # create_week_plan refuses (week exists), propose_adaptation refuses (no
    # valid prior week -- W27 doesn't exist). replace_week_plan is the fix:
    # confirming it should produce ai_coach-authored real pool-session
    # structure instead.
    store = FileStore(base_dir=athletes_dir)
    original_week = store.load_week("renee", "2026-W28")
    original_pool_sessions = [s for s in original_week.sessions if s.sport == "swim_pool"]
    assert original_pool_sessions, "fixture must have pool sessions to make this regression real"
    assert all(s.source == "pool_coach" for s in original_pool_sessions)
    assert all(s.structure is None for s in original_pool_sessions)

    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    status_result = handlers["set_pool_coach_status"]({"has_pool_coach": False})
    assert status_result == {"updated": True, "has_pool_coach": False}

    confirmed = handlers["replace_week_plan"]({"iso_week": "2026-W28", "confirm": True})
    assert "error" not in confirmed
    assert confirmed["persisted"] is True

    reloaded = FileStore(base_dir=athletes_dir).load_week("renee", "2026-W28")
    new_pool_sessions = [s for s in reloaded.sessions if s.sport == "swim_pool"]
    assert new_pool_sessions
    for s in new_pool_sessions:
        assert s.source == "ai_coach"
        assert s.structure is not None
        assert s.structure.strip() != ""


# --- template_preference (create_week_plan / replace_week_plan) --------------
# 2026-W32 (2026-08-03 .. 2026-08-09) is the build block's FIRST week
# (week_index_in_block == 0 -- the macro's real block boundaries in
# athletes/renee/plan/macro.yaml have "build" starting exactly 2026-08-03, a
# Monday) and has no week file in the fixture (only W28/W29 exist). With no
# preference, selector == 0 deterministically picks "build-0-descend" (the
# alphabetically-first of 16 build/peak/taper candidates -- see
# tests/unit/test_workout_templates.py's own rotation tests). Requesting
# `template_preference={"purpose": "sprint_power"}` narrows the pool to the
# 4 sprint_power templates, whose alphabetically-first member
# ("build-f-straight-repeat-sprints", a fins-assisted sprint set) is
# genuinely different prose from the default -- proving the preference
# actually changes which template gets selected rather than being accepted
# and silently ignored.


def _additional_swim_session(week):
    return next(s for s in week.sessions if s.purpose == "additional pool-independent aerobic volume")


def test_create_week_plan_default_rotation_picks_build_0_descend(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    result = handlers["create_week_plan"]({"iso_week": "2026-W32"})
    assert "error" not in result

    week = FileStore(base_dir=athletes_dir).load_week("renee", "2026-W32")
    session = _additional_swim_session(week)
    assert "descend" in session.structure.lower()
    assert "fins-assisted" not in session.structure


def test_create_week_plan_with_template_preference_changes_selected_template(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    result = handlers["create_week_plan"](
        {"iso_week": "2026-W32", "template_preference": {"purpose": "sprint_power"}}
    )
    assert "error" not in result

    week = FileStore(base_dir=athletes_dir).load_week("renee", "2026-W32")
    session = _additional_swim_session(week)
    assert "fins-assisted" in session.structure


def test_create_week_plan_invalid_template_preference_purpose_is_a_clean_error(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    result = handlers["create_week_plan"](
        {"iso_week": "2026-W32", "template_preference": {"purpose": "not_a_real_purpose"}}
    )
    assert "error" in result
    assert "template_preference" in result["error"]
    assert FileStore(base_dir=athletes_dir).load_week("renee", "2026-W32") is None


def test_create_week_plan_template_preference_matching_nothing_is_a_clean_error(athletes_dir) -> None:
    # 2026-W30 falls in the base block, which has no sprint_power template
    # (only "aerobic_base" purpose templates apply to "base").
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    result = handlers["create_week_plan"](
        {"iso_week": "2026-W30", "template_preference": {"purpose": "sprint_power"}}
    )
    assert "error" in result
    assert "no workout templates match" in result["error"]
    assert FileStore(base_dir=athletes_dir).load_week("renee", "2026-W30") is None


def test_replace_week_plan_with_template_preference_changes_selected_template_on_confirm(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    # Establish the default-rotation baseline first.
    handlers["create_week_plan"]({"iso_week": "2026-W32"})
    baseline_week = FileStore(base_dir=athletes_dir).load_week("renee", "2026-W32")
    baseline_session = _additional_swim_session(baseline_week)
    assert "fins-assisted" not in baseline_session.structure

    result = handlers["replace_week_plan"](
        {
            "iso_week": "2026-W32",
            "confirm": True,
            "template_preference": {"purpose": "sprint_power"},
        }
    )
    assert "error" not in result
    assert result["persisted"] is True

    reloaded_week = FileStore(base_dir=athletes_dir).load_week("renee", "2026-W32")
    reloaded_session = _additional_swim_session(reloaded_week)
    assert "fins-assisted" in reloaded_session.structure


def test_replace_week_plan_template_preference_draft_mode_does_not_persist(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    handlers["create_week_plan"]({"iso_week": "2026-W32"})

    result = handlers["replace_week_plan"](
        {"iso_week": "2026-W32", "template_preference": {"purpose": "sprint_power"}}
    )
    assert "error" not in result
    assert result["persisted"] is False

    # Still the unconstrained default on disk -- draft mode never persisted.
    week = FileStore(base_dir=athletes_dir).load_week("renee", "2026-W32")
    session = _additional_swim_session(week)
    assert "fins-assisted" not in session.structure


def test_replace_week_plan_invalid_template_preference_interval_style_is_a_clean_error(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    result = handlers["replace_week_plan"](
        {"iso_week": "2026-W28", "template_preference": {"interval_style": "not_a_real_style"}}
    )
    assert "error" in result
    assert "template_preference" in result["error"]


# --- set_event_active_status ---------------------------------------------------


def test_set_event_active_status_deactivate_then_reactivate_round_trips(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    original = next(e for e in store.load_events("renee") if e.name == GREECE_EVENT_NAME)
    assert original.active is True  # default

    deactivated = handlers["set_event_active_status"](
        {"event_name": GREECE_EVENT_NAME, "active": False}
    )
    assert deactivated == {"updated": True, "event_name": GREECE_EVENT_NAME, "active": False}

    reloaded_store = FileStore(base_dir=athletes_dir)
    after_deactivate = next(e for e in reloaded_store.load_events("renee") if e.name == GREECE_EVENT_NAME)
    assert after_deactivate.active is False
    # Every other field on the event is untouched.
    assert after_deactivate.id == original.id
    assert after_deactivate.event_date == original.event_date
    assert after_deactivate.distance_m == original.distance_m

    reactivated = handlers["set_event_active_status"](
        {"event_name": GREECE_EVENT_NAME, "active": True}
    )
    assert reactivated == {"updated": True, "event_name": GREECE_EVENT_NAME, "active": True}

    final_store = FileStore(base_dir=athletes_dir)
    after_reactivate = next(e for e in final_store.load_events("renee") if e.name == GREECE_EVENT_NAME)
    assert after_reactivate.active is True


def test_set_event_active_status_no_match_names_existing_events(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    result = handlers["set_event_active_status"](
        {"event_name": "No Such Event At All", "active": False}
    )

    assert "error" in result
    assert "found 0" in result["error"]
    assert GREECE_EVENT_NAME in result["error"]


def test_set_event_active_status_ambiguous_match_is_an_error(athletes_dir, run_tag) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    dup_name = f"Test Duplicate Event [{run_tag}]"
    handlers["create_event"](
        {"name": dup_name, "event_date": "2027-05-01", "distance_m": 5000, "priority": "B"}
    )
    handlers["create_event"](
        {"name": dup_name, "event_date": "2027-06-01", "distance_m": 6000, "priority": "B"}
    )

    result = handlers["set_event_active_status"]({"event_name": dup_name, "active": False})

    assert "error" in result
    assert "found 2" in result["error"]


def test_set_event_active_status_missing_fields_are_errors(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    assert "error" in handlers["set_event_active_status"]({"active": False})
    assert "error" in handlers["set_event_active_status"]({"event_name": GREECE_EVENT_NAME})


def test_set_event_active_status_non_boolean_active_is_an_error(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    result = handlers["set_event_active_status"](
        {"event_name": GREECE_EVENT_NAME, "active": "yes"}
    )
    assert "error" in result


def test_draft_macro_plan_can_resolve_and_build_toward_a_deactivated_event(athletes_dir, run_tag) -> None:
    # Confirms no accidental active-filtering broke draft_macro_plan's own
    # event-by-name lookup: a deactivated event must still resolve, since the
    # athlete might reactivate it and (re)build a macro toward it, or an old
    # macro might still reference it historically.
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    name = f"Test Deactivated Macro Event [{run_tag}]"
    handlers["create_event"](
        {"name": name, "event_date": "2027-06-01", "distance_m": 20000, "priority": "B"}
    )
    handlers["set_event_active_status"]({"event_name": name, "active": False})
    event = next(e for e in store.load_events("renee") if e.name == name)
    assert event.active is False

    result = handlers["draft_macro_plan"](
        {"event_name": name, "current_weekly_volume_m": 15000, "start_date": "2027-01-01"}
    )

    assert "error" not in result
    assert result["created"] is True
    reloaded_macro = FileStore(base_dir=athletes_dir).load_macro("renee")
    assert reloaded_macro.event_id == event.id


def test_replace_macro_plan_can_resolve_and_build_toward_a_deactivated_event(athletes_dir) -> None:
    # Same confirmation as above, for replace_macro_plan's event lookup.
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    handlers["set_event_active_status"]({"event_name": GREECE_EVENT_NAME, "active": False})
    event = next(e for e in store.load_events("renee") if e.name == GREECE_EVENT_NAME)
    assert event.active is False

    result = handlers["replace_macro_plan"](
        {
            "event_name": GREECE_EVENT_NAME,
            "current_weekly_volume_m": 18000,
            "start_date": "2026-01-05",
            "confirm": True,
        }
    )

    assert "error" not in result
    assert result["persisted"] is True
    reloaded_macro = FileStore(base_dir=athletes_dir).load_macro("renee")
    assert reloaded_macro.event_id == event.id
