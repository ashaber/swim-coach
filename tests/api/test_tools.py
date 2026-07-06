"""Direct tests for the tool handlers, independent of the chat/streaming
layer -- exercises the real engine (`swim_coach.adapt`, `swim_coach.load`)
against the isolated per-test athlete tree copy."""

from __future__ import annotations

import json

from swim_coach.store import FileStore

from app.tools import build_tool_handlers


def test_propose_adaptation_returns_draft_without_persisting(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(
        store, slug="renee", research_dir=athletes_dir.parent / "research", expert_mode=False
    )

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
    handlers = build_tool_handlers(
        store, slug="renee", research_dir=athletes_dir.parent / "research", expert_mode=False
    )

    # 2026-W50 has no week plan for W49 to adapt from.
    result = handlers["propose_adaptation"]({"iso_week": "2026-W50"})
    assert "error" in result


def test_propose_adaptation_invalid_iso_week_is_an_error(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(
        store, slug="renee", research_dir=athletes_dir.parent / "research", expert_mode=False
    )
    result = handlers["propose_adaptation"]({"iso_week": "not-a-week"})
    assert "error" in result


def test_get_plan_summary_matches_engine_summarize_shape(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(
        store, slug="renee", research_dir=athletes_dir.parent / "research", expert_mode=False
    )
    result = handlers["get_plan_summary"]({"weeks": 4})
    assert result["athlete"] == "renee"
    assert result["weeks"] == 4
    assert "volume_m" in result
    assert "compliance_pct" in result


def test_log_open_question_appends_jsonl_entry(athletes_dir, run_tag) -> None:
    research_dir = athletes_dir.parent / "research"
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(
        store, slug="renee", research_dir=research_dir, expert_mode=True
    )

    question = f"is there swim-specific taper research beyond the swim-adapted cycling data? [{run_tag}]"
    result = handlers["log_open_question"]({"question": question, "topic": "taper"})

    assert result["logged"] is True
    path = research_dir / "open-questions.jsonl"
    assert path.exists()
    entries = [json.loads(line) for line in path.read_text().splitlines()]
    matching = [e for e in entries if run_tag in e["question"]]
    assert len(matching) == 1
    assert matching[0]["expert_mode"] is True
    assert matching[0]["topic"] == "taper"


def test_log_open_question_requires_question_and_topic(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(
        store, slug="renee", research_dir=athletes_dir.parent / "research", expert_mode=False
    )
    result = handlers["log_open_question"]({"question": "", "topic": ""})
    assert "error" in result
