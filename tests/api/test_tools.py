"""Direct tests for the tool handlers, independent of the chat/streaming
layer -- exercises the real engine (`swim_coach.adapt`, `swim_coach.load`)
against the isolated per-test athlete tree copy."""

from __future__ import annotations

from datetime import date

from fakes import SpyFeedbackStore, make_workout
from swim_coach.models import WorkoutAnalytics, WorkoutLap, WorkoutPause
from swim_coach.store import FileStore

from app.tools import GET_WORKOUTS_CAP, build_tool_handlers


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
