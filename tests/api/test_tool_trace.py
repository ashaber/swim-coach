"""Per-turn tool trace: the server's record of which tools a coach turn really called, emitted
as a `tool_trace` SSE event, stored with the AI reply, and replayed into later turns' history
so the model can't mistake its own narration for evidence a tool ran (prod 2026-10-15)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from app.context import PERSONA_AND_RULES
from app.routes.chat import _history_from_workout_chat, _persisting_thread_stream
from app.save_claims import format_tool_trace
from fakes import make_tool_use_block
from swim_coach.models import ConversationMessage, WorkoutChatMessage
from test_save_claim_guard import _run

DRAFT_ID = "d41f9c2e-1111-2222-3333-444455556666"


def _trace(events) -> list[dict]:
    return [e for e in events if e["type"] == "tool_trace"]


def test_trace_lists_tools_and_marks_a_draft_not_saved() -> None:
    get = make_tool_use_block("t1", "get_week_plan", {})
    patch = make_tool_use_block("t2", "patch_week_plan", {})
    _, events = _run(
        [(get, None), (patch, None), (None, "Here is the draft.")],
        {
            "get_week_plan": lambda _i: {"sessions": []},
            "patch_week_plan": lambda _i: {"persisted": False, "draft_id": DRAFT_ID},
        },
    )
    assert _trace(events) == [
        {"type": "tool_trace", "trace": "get_week_plan; patch_week_plan → draft d41f9c2e NOT saved"}
    ]
    assert events[-1]["type"] == "done" and events[-2]["type"] == "tool_trace"


def test_trace_marks_a_persisted_write() -> None:
    tu = make_tool_use_block("t1", "patch_week_plan", {"confirm": True, "draft_id": DRAFT_ID})
    _, events = _run(
        [(tu, None), (None, "Saved.")],
        {"patch_week_plan": lambda _i: {"persisted": True}},
    )
    assert _trace(events)[0]["trace"] == "patch_week_plan → draft d41f9c2e SAVED"


def test_trace_with_no_tools_is_none() -> None:
    _, events = _run([(None, "Draft is clean, no planning warnings.")], {})
    assert _trace(events)[0]["trace"] == "none"


def test_trace_records_a_tool_error_briefly() -> None:
    tu = make_tool_use_block("t1", "patch_week_plan", {})
    _, events = _run(
        [(tu, None), (None, "That failed.")],
        {"patch_week_plan": lambda _i: {"error": "x" * 500}},
    )
    trace = _trace(events)[0]["trace"]
    assert trace.startswith("patch_week_plan → error: xxx")
    assert len(trace) < 120


def test_trace_is_deterministic_and_collapses_repeats() -> None:
    calls = [("get_week_plan", {}, {"sessions": []})] * 3
    assert format_tool_trace(calls) == format_tool_trace(calls) == "get_week_plan ×3"


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def test_persisting_stream_stores_trace_with_reply_but_not_in_body() -> None:
    saved: list[tuple] = []

    def append(role, body, tool_trace=None):
        saved.append((role, body, tool_trace))

    inner = iter([
        _sse({"type": "text", "text": "Hello"}),
        _sse({"type": "tool_trace", "trace": "get_week_plan"}),
        _sse({"type": "done", "stop_reason": "end_turn"}),
    ])
    out = list(_persisting_thread_stream(append, "hi", inner))
    assert len(out) == 3  # forwarded unchanged
    assert saved == [("athlete", "hi", None), ("ai_coach", "Hello", "get_week_plan")]


def _msg(cls, role, body, trace=None, **extra):
    return cls(
        id=uuid4(), sender_role=role, body=body, tool_trace=trace,
        created_at=datetime.now(timezone.utc), **extra,
    )


def test_history_replay_appends_trace_line_and_omits_it_for_legacy_turns() -> None:
    msgs = [
        _msg(WorkoutChatMessage, "athlete", "plan next week"),
        _msg(WorkoutChatMessage, "ai_coach", "Draft is clean. Confirm and I'll persist.", "none"),
        _msg(WorkoutChatMessage, "athlete", "ok"),
        _msg(WorkoutChatMessage, "ai_coach", "Old reply", None),
        _msg(WorkoutChatMessage, "athlete", "again"),
        _msg(WorkoutChatMessage, "ai_coach", "Done", "patch_week_plan → draft d41f9c2e SAVED"),
    ]
    turns, pending = _history_from_workout_chat(msgs)
    assert pending is None
    assert turns[1]["content"] == (
        "Draft is clean. Confirm and I'll persist.\n\n[tools this turn: none]"
    )
    assert turns[3]["content"] == "Old reply"
    assert turns[5]["content"].endswith("[tools this turn: patch_week_plan → draft d41f9c2e SAVED]")
    again, _ = _history_from_workout_chat(msgs)
    assert again == turns  # byte-stable


def test_conversation_messages_replay_trace_too() -> None:
    cid = uuid4()
    msgs = [
        _msg(ConversationMessage, "athlete", "hi", athlete_id=uuid4(), coach_athlete_id=cid),
        _msg(ConversationMessage, "ai_coach", "Hi", "none", athlete_id=uuid4(), coach_athlete_id=cid),
    ]
    turns, _ = _history_from_workout_chat(msgs)
    assert turns[1]["content"] == "Hi\n\n[tools this turn: none]"


def test_persona_explains_the_tool_record() -> None:
    assert "[tools this turn:" in PERSONA_AND_RULES


def test_workout_chat_route_persists_trace_with_the_ai_reply(
    client, fake_claude_chat_factory, athletes_dir
) -> None:
    from fakes import auth_headers, make_final_message, make_text_block
    from swim_coach.store import FileStore
    from test_chat import _chat_payload, _save_rich_workout

    workout = _save_rich_workout(athletes_dir)
    final = make_final_message([make_text_block("Draft is clean.")], "end_turn")
    fake_claude_chat_factory([(["Draft is clean."], final)])
    response = client.post(
        "/api/chat",
        json=_chat_payload(message="plan it", workout_id=str(workout.id)),
        headers=auth_headers(),
    )
    assert response.status_code == 200
    reloaded = FileStore(base_dir=athletes_dir).get_workout("renee", workout.id)
    ai = [m for m in reloaded.chat_messages if m.sender_role == "ai_coach"][0]
    assert ai.tool_trace == "none"
    assert "tools this turn" not in ai.body
