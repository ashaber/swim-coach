"""The athlete<->coach conversation (IDEA 016 Part 2): grant gating on both sides, the AI reply
path (mocked Anthropic client), the user/assistant alternation rule, mute, the polling cursor,
the daily chat cap, and notifications. Routes live in `backend/app/routes/conversation.py`.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from fakes import (
    auth_headers,
    fake_google_verify,
    google_token_for,
    make_final_message,
    make_text_block,
    message_text,
)
from swim_coach.models import ConversationMessage
from swim_coach.store import FileStore

RENEE_EMAIL = "kline.renee@gmail.com"
TIM_EMAIL = "curry.mtb@gmail.com"
ANDREW_EMAIL = "andrewshaber@gmail.com"


@pytest.fixture
def store(app_env: Path) -> FileStore:
    return FileStore(base_dir=app_env)


@pytest.fixture
def allowlist(store: FileStore) -> FileStore:
    store.add_allowed_email(ANDREW_EMAIL, athlete="andrew")
    store.add_allowed_email(RENEE_EMAIL, athlete="renee")
    store.add_allowed_email(TIM_EMAIL, athlete="tim")
    return store


@pytest.fixture
def google(app):
    from app.google_auth import get_google_verifier

    app.dependency_overrides[get_google_verifier] = lambda: fake_google_verify
    yield
    app.dependency_overrides.pop(get_google_verifier, None)


def _headers(client, email: str) -> dict:
    token = client.post("/api/auth/google", json={"id_token": google_token_for(email)}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def granted(store, allowlist):
    """tim coaches renee; returns tim's athlete id (the thread's coach_athlete_id)."""
    store.create_coach_grant(coach_slug="tim", athlete_slug="renee")
    return store.load_athlete("tim").id


@pytest.fixture
def spies(app):
    from app.routes.conversation import get_athlete_side_notifier, get_coach_side_notifier

    to_coach: list = []
    to_athlete: list = []
    app.dependency_overrides[get_athlete_side_notifier] = lambda: (
        lambda store, settings, message, athlete: to_coach.append((message, athlete))
    )
    app.dependency_overrides[get_coach_side_notifier] = lambda: (
        lambda store, settings, message, athlete: to_athlete.append((message, athlete))
    )
    yield {"to_coach": to_coach, "to_athlete": to_athlete}
    app.dependency_overrides.pop(get_athlete_side_notifier, None)
    app.dependency_overrides.pop(get_coach_side_notifier, None)


def _athlete_url(coach_id, suffix: str = "/messages") -> str:
    return f"/api/conversations/{coach_id}{suffix}"


COACH_URL = "/api/coach/athletes/renee/conversation"


def _seed(store, coach_id, role, body, at):
    store.append_conversation_message(
        "renee",
        ConversationMessage(
            id=uuid4(), athlete_id=store.load_athlete("renee").id, coach_athlete_id=coach_id,
            sender_role=role, body=body, created_at=at,
        ),
    )


# --- grant gating ----------------------------------------------------------------------


def test_athlete_routes_require_auth(client, granted) -> None:
    assert client.get(_athlete_url(granted)).status_code == 401
    assert client.post(_athlete_url(granted), json={"message": "hi"}).status_code == 401


def test_athlete_cannot_open_a_thread_with_a_coach_without_an_active_grant(client, allowlist, google, store) -> None:
    headers = _headers(client, RENEE_EMAIL)
    tim_id = store.load_athlete("tim").id
    assert client.get(_athlete_url(tim_id), headers=headers).status_code == 404
    assert client.post(_athlete_url(tim_id), json={"message": "hi"}, headers=headers).status_code == 404
    assert client.get("/api/conversations", headers=headers).json() == []


def test_revoked_grant_closes_the_thread(client, allowlist, google, store, granted) -> None:
    grant = store.list_coach_grants(athlete_slug="renee")[0]
    store.revoke_coach_grant(grant.id)
    assert client.get(_athlete_url(granted), headers=_headers(client, RENEE_EMAIL)).status_code == 404


def test_athlete_lists_a_thread_per_active_coach(client, allowlist, google, granted) -> None:
    body = client.get("/api/conversations", headers=_headers(client, RENEE_EMAIL)).json()
    assert body == [{"coach_athlete_id": str(granted), "ai_muted": False}]


def test_athlete_param_mismatch_is_403(client, allowlist, google, granted) -> None:
    response = client.get(
        _athlete_url(granted) + "?athlete=andrew", headers=_headers(client, RENEE_EMAIL)
    )
    assert response.status_code == 403


def test_coach_routes_403_without_a_grant(client, allowlist, google) -> None:
    headers = _headers(client, TIM_EMAIL)
    assert client.get(COACH_URL, headers=headers).status_code == 403
    assert client.post(COACH_URL + "/messages", json={"body": "hi"}, headers=headers).status_code == 403
    assert client.patch(COACH_URL, json={"ai_muted": True}, headers=headers).status_code == 403


def test_coach_routes_require_auth(client, granted) -> None:
    assert client.get(COACH_URL).status_code == 401


def test_service_credential_has_no_coach_identity(client, granted) -> None:
    assert client.get(COACH_URL, headers=auth_headers()).status_code == 403
    assert client.post(COACH_URL + "/messages", json={"body": "hi"}, headers=auth_headers()).status_code == 403


# --- coach posting -----------------------------------------------------------------------


def test_coach_post_persists_notifies_the_athlete_and_is_visible_to_both(
    client, allowlist, google, store, granted, spies
) -> None:
    coach_headers = _headers(client, TIM_EMAIL)
    response = client.post(COACH_URL + "/messages", json={"body": "  great week  "}, headers=coach_headers)
    assert response.status_code == 200
    posted = response.json()
    assert posted["sender_role"] == "coach"
    assert posted["body"] == "great week"
    assert posted["coach_athlete_id"] == str(granted)

    assert [(m.id, a) for m, a in spies["to_athlete"]] == [(store.list_conversation_messages("renee", granted)[0].id, "renee")]

    seen_by_athlete = client.get(_athlete_url(granted), headers=_headers(client, RENEE_EMAIL)).json()
    assert [m["body"] for m in seen_by_athlete["messages"]] == ["great week"]
    seen_by_coach = client.get(COACH_URL, headers=coach_headers).json()
    assert [m["id"] for m in seen_by_coach["messages"]] == [posted["id"]]


@pytest.mark.parametrize("payload", [{}, {"body": "   "}, {"body": 5}, {"body": "x" * 4001}])
def test_coach_post_rejects_bad_bodies(client, allowlist, google, granted, payload) -> None:
    response = client.post(COACH_URL + "/messages", json=payload, headers=_headers(client, TIM_EMAIL))
    assert response.status_code == 422


def test_coach_post_does_not_call_the_model(client, allowlist, google, granted, fake_claude_chat_factory) -> None:
    chat = fake_claude_chat_factory([])
    client.post(COACH_URL + "/messages", json={"body": "hello"}, headers=_headers(client, TIM_EMAIL))
    assert chat.client.messages.calls == []


# --- athlete posting: AI reply path -----------------------------------------------------------


def test_athlete_post_streams_and_persists_message_then_ai_reply_and_notifies_the_coach(
    client, allowlist, google, store, granted, fake_claude_chat_factory, spies
) -> None:
    final = make_final_message([make_text_block("Rest up, then easy aerobic.")], "end_turn")
    fake_claude_chat_factory([(["Rest up, then easy aerobic."], final)])

    response = client.post(
        _athlete_url(granted), json={"message": "legs are heavy today"}, headers=_headers(client, RENEE_EMAIL)
    )
    assert response.status_code == 200
    assert "Rest up, then easy aerobic." in response.text

    thread = store.list_conversation_messages("renee", granted)
    assert [(m.sender_role, m.body) for m in thread] == [
        ("athlete", "legs are heavy today"),
        ("ai_coach", "Rest up, then easy aerobic."),
    ]
    assert len(spies["to_coach"]) == 1
    message, athlete = spies["to_coach"][0]
    assert (message.body, message.sender_role, athlete) == ("legs are heavy today", "athlete", "renee")


@pytest.mark.parametrize("payload", [{}, {"message": " "}, {"message": "x" * 4001}])
def test_athlete_post_rejects_bad_messages(client, allowlist, google, granted, payload) -> None:
    response = client.post(_athlete_url(granted), json=payload, headers=_headers(client, RENEE_EMAIL))
    assert response.status_code == 422


def test_unanswered_coach_comment_is_folded_onto_the_athletes_next_message(
    client, allowlist, google, store, granted, fake_claude_chat_factory
) -> None:
    """History ends on an unanswered coach comment: the AI must see it, and the request sent to
    Anthropic must never carry two consecutive user turns."""
    t0 = datetime(2026, 9, 29, 8, 0, tzinfo=timezone.utc)
    _seed(store, granted, "athlete", "rough start, faded late", t0)
    _seed(store, granted, "ai_coach", "what happened out there?", t0 + timedelta(seconds=5))
    _seed(store, granted, "coach", "she was fighting a current on the back half.", t0 + timedelta(hours=1))
    final = make_final_message([make_text_block("that explains it.")], "end_turn")
    chat = fake_claude_chat_factory([(["that explains it."], final)])

    response = client.post(
        _athlete_url(granted), json={"message": "anything to change next time?"},
        headers=_headers(client, RENEE_EMAIL),
    )
    assert response.status_code == 200

    sent = chat.client.messages.calls[0]["messages"]
    roles = [m["role"] for m in sent]
    assert all(a != b for a, b in zip(roles, roles[1:]))
    last = message_text(sent[-1]["content"])
    assert "fighting a current" in last
    assert "anything to change next time?" in last

    assert [m.sender_role for m in store.list_conversation_messages("renee", granted)] == [
        "athlete", "ai_coach", "coach", "athlete", "ai_coach",
    ]


def test_consecutive_athlete_and_coach_turns_merge_in_history(
    client, allowlist, google, store, granted, fake_claude_chat_factory
) -> None:
    t0 = datetime(2026, 9, 29, 8, 0, tzinfo=timezone.utc)
    _seed(store, granted, "athlete", "first", t0)
    _seed(store, granted, "ai_coach", "reply", t0 + timedelta(seconds=1))
    _seed(store, granted, "athlete", "second", t0 + timedelta(seconds=2))
    _seed(store, granted, "coach", "third from coach", t0 + timedelta(seconds=3))
    final = make_final_message([make_text_block("ok")], "end_turn")
    chat = fake_claude_chat_factory([(["ok"], final)])
    client.post(_athlete_url(granted), json={"message": "fourth"}, headers=_headers(client, RENEE_EMAIL))
    roles = [m["role"] for m in chat.client.messages.calls[0]["messages"]]
    assert all(a != b for a, b in zip(roles, roles[1:]))


# --- mute ---------------------------------------------------------------------------------------


def test_muted_thread_skips_the_model_still_saves_and_consumes_no_chat_cap(
    client, allowlist, google, store, granted, fake_claude_chat_factory, spies
) -> None:
    chat = fake_claude_chat_factory([])
    renee = _headers(client, RENEE_EMAIL)
    assert client.patch(_athlete_url(granted, ""), json={"ai_muted": True}, headers=renee).json() == {
        "coach_athlete_id": str(granted), "ai_muted": True,
    }

    response = client.post(_athlete_url(granted), json={"message": "for my coach only"}, headers=renee)
    assert response.status_code == 200
    assert "muted" in response.text
    assert chat.client.messages.calls == []
    assert [(m.sender_role, m.body) for m in store.list_conversation_messages("renee", granted)] == [
        ("athlete", "for my coach only"),
    ]
    assert len(spies["to_coach"]) == 1  # the coach is still notified of a muted-thread message


def test_coach_can_mute_and_unmute_and_both_sides_see_it(client, allowlist, google, store, granted) -> None:
    coach = _headers(client, TIM_EMAIL)
    renee = _headers(client, RENEE_EMAIL)
    assert client.patch(COACH_URL, json={"ai_muted": True}, headers=coach).json()["ai_muted"] is True
    assert client.get(_athlete_url(granted), headers=renee).json()["ai_muted"] is True
    assert client.get(COACH_URL, headers=coach).json()["ai_muted"] is True
    client.patch(COACH_URL, json={"ai_muted": False}, headers=coach)
    assert client.get(_athlete_url(granted), headers=renee).json()["ai_muted"] is False


@pytest.mark.parametrize("payload", [{}, {"ai_muted": "yes"}, {"ai_muted": 1}])
def test_mute_requires_a_boolean(client, allowlist, google, granted, payload) -> None:
    assert client.patch(COACH_URL, json=payload, headers=_headers(client, TIM_EMAIL)).status_code == 422
    assert client.patch(_athlete_url(granted, ""), json=payload, headers=_headers(client, RENEE_EMAIL)).status_code == 422


# --- polling cursor --------------------------------------------------------------------------------


def test_since_cursor_returns_only_newer_messages_inclusive(client, allowlist, google, store, granted) -> None:
    t0 = datetime(2026, 9, 29, 8, 0, tzinfo=timezone.utc)
    _seed(store, granted, "athlete", "old", t0)
    _seed(store, granted, "coach", "edge", t0 + timedelta(minutes=5))
    _seed(store, granted, "ai_coach", "new", t0 + timedelta(minutes=9))
    headers = _headers(client, RENEE_EMAIL)
    cursor = (t0 + timedelta(minutes=5)).isoformat()
    body = client.get(_athlete_url(granted), params={"since": cursor}, headers=headers).json()
    assert [m["body"] for m in body["messages"]] == ["edge", "new"]
    assert client.get(COACH_URL, params={"since": cursor}, headers=_headers(client, TIM_EMAIL)).json()[
        "messages"
    ][0]["body"] == "edge"


def test_bad_since_is_422(client, allowlist, google, granted) -> None:
    response = client.get(_athlete_url(granted), params={"since": "yesterday"}, headers=_headers(client, RENEE_EMAIL))
    assert response.status_code == 422


# --- daily cap -----------------------------------------------------------------------------------------


def test_daily_chat_cap_applies_to_unmuted_athlete_posts(allowlist, store, monkeypatch) -> None:
    monkeypatch.setenv("CHAT_DAILY_CAP_PER_ATHLETE", "1")
    monkeypatch.setenv("CHAT_RATE_PER_MIN", "100")
    store.create_coach_grant(coach_slug="tim", athlete_slug="renee")
    coach_id = store.load_athlete("tim").id
    from app.main import create_app

    capped = create_app()
    from app.claude import ClaudeChat
    from app.google_auth import get_google_verifier
    from app.routes.chat import get_claude_chat
    from fakes import FakeAnthropicClient

    capped.dependency_overrides[get_google_verifier] = lambda: fake_google_verify
    final = make_final_message([make_text_block("ok")], "end_turn")
    capped.dependency_overrides[get_claude_chat] = lambda: ClaudeChat(
        capped.state.settings, client=FakeAnthropicClient([(["ok"], final), (["ok"], final)])
    )
    from fastapi.testclient import TestClient

    with TestClient(capped) as c:
        headers = _headers(c, RENEE_EMAIL)
        statuses = [
            c.post(_athlete_url(coach_id), json={"message": "hi"}, headers=headers).status_code
            for _ in range(2)
        ]
        assert statuses == [200, 429]
