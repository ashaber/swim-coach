"""`log_app_feedback`: the coach's channel for app defects / ideas / comments -- developer-facing,
never the human-coach queue."""

from __future__ import annotations

from swim_coach.store import FileStore

from app.tools import TOOLS_SCHEMA, build_tool_handlers
from test_tools import SpyFeedbackStore


def test_writes_a_coach_sourced_row_without_notifying(athletes_dir, run_tag, monkeypatch) -> None:
    import app.notify as notify_module

    def _boom(*_a, **_k):
        raise AssertionError("log_app_feedback must never notify coaches")

    monkeypatch.setattr(notify_module, "notify_coaches_of_feedback", _boom)
    spy = SpyFeedbackStore(FileStore(base_dir=athletes_dir))
    handlers = build_tool_handlers(spy, slug="renee", expert_mode=False)

    result = handlers["log_app_feedback"](
        {"type": "comment", "summary": f"great bike patch flow [{run_tag}]", "sentiment": "positive",
         "topic": "patch", "what_happened": "confirmed in one turn"}
    )

    assert result["logged"] is True and result["type"] == "comment"
    entry = spy.saved[0]
    assert entry.type == "comment" and entry.source == "coach"
    assert entry.needs_human_review is False
    assert entry.context["sentiment"] == "positive" and entry.context["topic"] == "patch"
    assert entry.context["what_happened"] == "confirmed in one turn"


def test_rejects_bad_type_and_missing_summary(athletes_dir) -> None:
    spy = SpyFeedbackStore(FileStore(base_dir=athletes_dir))
    handlers = build_tool_handlers(spy, slug="renee", expert_mode=False)
    assert "error" in handlers["log_app_feedback"]({"type": "coach_review", "summary": "x"})
    assert "error" in handlers["log_app_feedback"]({"type": "bug", "summary": "  "})
    assert "error" in handlers["log_app_feedback"]({"type": "bug", "summary": "x", "sentiment": "meh"})
    assert spy.saved == []


def test_registered_and_flag_description_points_app_defects_away() -> None:
    schemas = {t["name"]: t for t in TOOLS_SCHEMA}
    assert schemas["log_app_feedback"]["input_schema"]["properties"]["type"]["enum"] == [
        "bug", "feature_request", "comment"]
    assert "log_app_feedback" in schemas["flag_for_coach_review"]["description"]
