"""A planned session's own chat thread: POST /api/chat with `session_id` persists the exchange under
that session (not the Coach tab), replays ONLY that thread as history (tool_trace included), honours
the mute switch, imports old single-turn feedback Q&A as read-only earlier messages, and carries the
messages onto the completed workout once the session is matched to one."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from fakes import (
    auth_headers,
    make_final_message,
    make_session,
    make_text_block,
    make_tool_use_block,
    make_workout,
    message_text,
)
from swim_coach.models import Feedback, SessionChatMessage, WeekPlan
from swim_coach.store import FileStore

from app import enrich
from app.context import iso_week_str


def _seed_session(athletes_dir, **overrides):
    store = FileStore(base_dir=athletes_dir)
    profile = store.load_athlete("renee")
    today = date.today()
    session = make_session(
        athlete_id=profile.id, date=today, sport="strength", source="ai_coach",
        purpose="lower-body strength", structure="3x8 goblet squat", **overrides,
    )
    store.save_week("renee", WeekPlan(
        id=uuid.uuid4(), athlete_id=profile.id, iso_week=iso_week_str(today), meso_block="base",
        focus="strength", target_volume_m=0, sessions=[session],
    ))
    return store, profile, session


def _payload(session, message="how heavy?", **extra) -> dict:
    return {"message": message, "history": [], "athlete": "renee", "expert_mode": False,
            "session_id": str(session.id), **extra}


def _msg(profile, session, role, body, at, **kw):
    return SessionChatMessage(
        id=uuid.uuid4(), athlete_id=profile.id, session_id=session.id, sender_role=role, body=body,
        created_at=at, **kw,
    )


def test_session_chat_persists_both_messages_under_the_session(client, fake_claude_chat_factory, athletes_dir) -> None:
    store, _profile, session = _seed_session(athletes_dir)
    final = make_final_message([make_text_block("Start light.")], "end_turn")
    fake_claude_chat_factory([(["Start light."], final)])

    response = client.post("/api/chat", json=_payload(session), headers=auth_headers())
    assert response.status_code == 200

    thread = store.list_session_messages("renee", session.id)
    assert [(m.sender_role, m.body) for m in thread] == [("athlete", "how heavy?"), ("ai_coach", "Start light.")]


def test_session_chat_context_carries_the_focused_session(client, fake_claude_chat_factory, athletes_dir) -> None:
    _store, _profile, session = _seed_session(athletes_dir)
    final = make_final_message([make_text_block("ok")], "end_turn")
    chat = fake_claude_chat_factory([(["ok"], final)])

    client.post("/api/chat", json=_payload(session), headers=auth_headers())

    system_text = "\n".join(b["text"] for b in chat.client.messages.calls[0]["system"])
    assert "specific planned session the athlete is asking about" in system_text
    assert str(session.id) in system_text


def test_second_turn_replays_the_session_thread_with_tool_trace_not_client_history(
    client, fake_claude_chat_factory, athletes_dir
) -> None:
    store, profile, session = _seed_session(athletes_dir)
    t0 = datetime.now(timezone.utc) - timedelta(minutes=5)
    store.append_session_message("renee", _msg(profile, session, "athlete", "first question", t0))
    store.append_session_message(
        "renee", _msg(profile, session, "ai_coach", "first answer", t0 + timedelta(seconds=5), tool_trace="none")
    )
    final = make_final_message([make_text_block("second answer")], "end_turn")
    chat = fake_claude_chat_factory([(["second answer"], final)])

    # The Coach tab's own history must be ignored for a session-scoped turn.
    payload = _payload(session, message="second question")
    payload["history"] = [{"role": "user", "content": "unrelated coach-tab chatter"},
                          {"role": "assistant", "content": "unrelated reply"}]
    client.post("/api/chat", json=payload, headers=auth_headers())

    sent = chat.client.messages.calls[0]["messages"]
    texts = [message_text(m["content"]) for m in sent]
    joined = "\n".join(texts)
    assert "first question" in joined and "first answer" in joined
    assert "[tools this turn: none]" in joined
    assert "unrelated coach-tab chatter" not in joined
    roles = [m["role"] for m in sent]
    assert all(a != b for a, b in zip(roles, roles[1:]))


def test_muted_session_thread_skips_the_model_but_saves_the_athlete_message(
    client, fake_claude_chat_factory, athletes_dir
) -> None:
    store, _profile, session = _seed_session(athletes_dir)
    store.set_session_thread_muted("renee", session.id, True)
    chat = fake_claude_chat_factory([])

    response = client.post("/api/chat", json=_payload(session, message="note to self"), headers=auth_headers())

    assert response.status_code == 200
    assert chat.client.messages.calls == []
    assert [m.body for m in store.list_session_messages("renee", session.id)] == ["note to self"]


def test_unknown_session_id_is_a_404(client, fake_claude_chat_factory, athletes_dir) -> None:
    _seed_session(athletes_dir)
    fake_claude_chat_factory([])
    response = client.post(
        "/api/chat",
        json={"message": "hi", "athlete": "renee", "session_id": str(uuid.uuid4())},
        headers=auth_headers(),
    )
    assert response.status_code == 404


def test_workout_id_and_session_id_together_is_a_422(client, fake_claude_chat_factory, athletes_dir) -> None:
    _store, _profile, session = _seed_session(athletes_dir)
    fake_claude_chat_factory([])
    response = client.post(
        "/api/chat",
        json={"message": "hi", "athlete": "renee", "session_id": str(session.id), "workout_id": "abcd1234"},
        headers=auth_headers(),
    )
    assert response.status_code == 422


def test_draft_claim_guard_still_runs_in_a_session_thread(client, fake_claude_chat_factory, athletes_dir) -> None:
    _store, _profile, session = _seed_session(athletes_dir)
    claim = "I've drafted the new week plan for you -- take a look and confirm it."
    final = make_final_message([make_text_block(claim)], "end_turn")
    fake_claude_chat_factory([([claim], final)])

    response = client.post("/api/chat", json=_payload(session, message="redo this week"), headers=auth_headers())

    assert response.status_code == 200
    assert "no draft was made" in response.text


def test_tool_trace_is_stored_on_the_ai_reply(client, fake_claude_chat_factory, athletes_dir) -> None:
    store, _profile, session = _seed_session(athletes_dir)
    tool_turn = make_final_message(
        [make_tool_use_block("tu_1", "get_plan_summary", {})], "tool_use"
    )
    final = make_final_message([make_text_block("Here is the plan.")], "end_turn")
    fake_claude_chat_factory([([], tool_turn), (["Here is the plan."], final)])

    client.post("/api/chat", json=_payload(session), headers=auth_headers())

    reply = store.list_session_messages("renee", session.id)[-1]
    assert reply.sender_role == "ai_coach"
    assert reply.tool_trace and "get_plan_summary" in reply.tool_trace


# --- thread route ---------------------------------------------------------------------------


def test_get_thread_returns_messages_and_mute_state(client, athletes_dir) -> None:
    store, profile, session = _seed_session(athletes_dir)
    store.append_session_message("renee", _msg(profile, session, "athlete", "hello", datetime.now(timezone.utc)))

    body = client.get(f"/api/sessions/{session.id}/thread?athlete=renee", headers=auth_headers()).json()

    assert body["ai_muted"] is False
    assert [m["body"] for m in body["messages"]] == ["hello"]


def test_get_thread_unknown_session_is_404(client, athletes_dir) -> None:
    _seed_session(athletes_dir)
    response = client.get(f"/api/sessions/{uuid.uuid4()}/thread?athlete=renee", headers=auth_headers())
    assert response.status_code == 404


def test_patch_thread_mutes_and_unmutes(client, athletes_dir) -> None:
    store, _profile, session = _seed_session(athletes_dir)
    url = f"/api/sessions/{session.id}/thread?athlete=renee"

    assert client.patch(url, json={"ai_muted": True}, headers=auth_headers()).json()["ai_muted"] is True
    assert store.get_session_thread("renee", session.id).ai_muted is True
    assert client.patch(url, json={"ai_muted": False}, headers=auth_headers()).json()["ai_muted"] is False
    assert client.patch(url, json={"ai_muted": "yes"}, headers=auth_headers()).status_code == 422


def test_old_feedback_questions_appear_as_earlier_messages_without_being_lost(client, athletes_dir) -> None:
    store, profile, session = _seed_session(athletes_dir)
    asked = datetime.now(timezone.utc) - timedelta(days=1)
    by_id = Feedback(
        id=uuid.uuid4(), athlete_id=profile.id, type="question", source="athlete", body="old question",
        created_at=asked, session_id=session.id, session_date=session.date, session_sport=session.sport,
        ai_provisional_answer="old answer",
    )
    legacy_no_id = Feedback(
        id=uuid.uuid4(), athlete_id=profile.id, type="question", source="athlete", body="oldest question",
        created_at=asked - timedelta(hours=1), session_date=session.date, session_sport=session.sport,
        coach_reply="human reply", coach_reply_at=asked,
    )
    other_session = Feedback(
        id=uuid.uuid4(), athlete_id=profile.id, type="question", source="athlete", body="elsewhere",
        created_at=asked, session_id=uuid.uuid4(), session_date=session.date, session_sport=session.sport,
    )
    for f in (by_id, legacy_no_id, other_session):
        store.save_feedback(f)
    store.append_session_message("renee", _msg(profile, session, "athlete", "new question", datetime.now(timezone.utc)))

    body = client.get(f"/api/sessions/{session.id}/thread?athlete=renee", headers=auth_headers()).json()

    assert [(m["sender_role"], m["body"]) for m in body["messages"]] == [
        ("athlete", "oldest question"), ("coach", "human reply"),
        ("athlete", "old question"), ("ai_coach", "old answer"),
        ("athlete", "new question"),
    ]
    # Importing is a read: the feedback rows are untouched and nothing was written to the thread.
    assert len(store.list_feedback(athlete="renee")) == 3
    assert len(store.list_session_messages("renee", session.id)) == 1
    # And the imported Q&A is stable across reads (same ids), so the client can de-duplicate.
    again = client.get(f"/api/sessions/{session.id}/thread?athlete=renee", headers=auth_headers()).json()
    assert [m["id"] for m in again["messages"]] == [m["id"] for m in body["messages"]]


def test_imported_feedback_reaches_the_model_as_history(client, fake_claude_chat_factory, athletes_dir) -> None:
    store, profile, session = _seed_session(athletes_dir)
    store.save_feedback(Feedback(
        id=uuid.uuid4(), athlete_id=profile.id, type="question", source="athlete", body="what about tempo",
        created_at=datetime.now(timezone.utc) - timedelta(days=1), session_id=session.id,
        session_date=session.date, session_sport=session.sport, ai_provisional_answer="keep it easy",
    ))
    final = make_final_message([make_text_block("ok")], "end_turn")
    chat = fake_claude_chat_factory([(["ok"], final)])

    client.post("/api/chat", json=_payload(session), headers=auth_headers())

    joined = "\n".join(message_text(m["content"]) for m in chat.client.messages.calls[0]["messages"])
    assert "what about tempo" in joined and "keep it easy" in joined


# --- carry-over -----------------------------------------------------------------------------


def test_matching_a_workout_to_the_session_copies_the_thread_onto_it(athletes_dir, monkeypatch) -> None:
    store, profile, session = _seed_session(athletes_dir)
    t0 = datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc)
    asked = _msg(profile, session, "athlete", "how heavy?", t0)
    answered = _msg(profile, session, "ai_coach", "Start light.", t0 + timedelta(seconds=4), tool_trace="none")
    store.append_session_message("renee", asked)
    store.append_session_message("renee", answered)
    monkeypatch.setattr(enrich, "find_planned_session", lambda *_a, **_k: session)
    workout = make_workout(athlete_id=profile.id, sport="strength", date=session.date)

    linked = enrich.attach_planned_session(workout, store=store, slug="renee", series=None)

    assert linked.planned_session_id == session.id
    assert [(m.id, m.sender_role, m.body, m.tool_trace) for m in linked.chat_messages] == [
        (asked.id, "athlete", "how heavy?", None), (answered.id, "ai_coach", "Start light.", "none"),
    ]
    # Re-running (a re-analyse) never duplicates, and picks up messages added since.
    later = _msg(profile, session, "athlete", "and the tempo?", t0 + timedelta(minutes=1))
    store.append_session_message("renee", later)
    again = enrich.attach_planned_session(linked, store=store, slug="renee", series=None)
    assert [m.body for m in again.chat_messages] == ["how heavy?", "Start light.", "and the tempo?"]


def test_carry_over_keeps_the_workouts_own_messages_in_time_order(athletes_dir, monkeypatch) -> None:
    from swim_coach.models import WorkoutChatMessage

    store, profile, session = _seed_session(athletes_dir)
    t0 = datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc)
    store.append_session_message("renee", _msg(profile, session, "athlete", "before", t0))
    monkeypatch.setattr(enrich, "find_planned_session", lambda *_a, **_k: session)
    workout = make_workout(athlete_id=profile.id, sport="strength", date=session.date)
    workout.chat_messages.append(WorkoutChatMessage(
        id=uuid.uuid4(), sender_role="athlete", body="after", created_at=t0 + timedelta(hours=2),
    ))

    linked = enrich.attach_planned_session(workout, store=store, slug="renee", series=None)

    assert [m.body for m in linked.chat_messages] == ["before", "after"]


def test_no_session_thread_leaves_the_workout_untouched(athletes_dir, monkeypatch) -> None:
    store, profile, session = _seed_session(athletes_dir)
    monkeypatch.setattr(enrich, "find_planned_session", lambda *_a, **_k: session)
    workout = make_workout(athlete_id=profile.id, sport="strength", date=session.date)

    linked = enrich.attach_planned_session(workout, store=store, slug="renee", series=None)

    assert linked.chat_messages == []
