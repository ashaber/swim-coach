"""Direct tests for the tool handlers, independent of the chat/streaming
layer -- exercises the real engine (`swim_coach.adapt`, `swim_coach.load`)
against the isolated per-test athlete tree copy."""

from __future__ import annotations

from fakes import SpyFeedbackStore
from swim_coach.store import FileStore

from app.tools import build_tool_handlers


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
