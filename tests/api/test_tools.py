"""Direct tests for the tool handlers, independent of the chat/streaming
layer -- exercises the real engine (`swim_coach.adapt`, `swim_coach.load`)
against the isolated per-test athlete tree copy."""

from __future__ import annotations

import base64
import json
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest
from fakes import SpyFeedbackStore, make_workout
from swim_coach.models import WorkoutAnalytics, WorkoutLap, WorkoutPause
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
