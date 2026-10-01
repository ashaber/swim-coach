"""notify.py's conversation emails (IDEA 016 Part 2): coach -> athlete and athlete -> coach,
gated on the recipient's own toggle, no-op without a Resend key, and throttled so a chat does
not become one email per message. No real HTTP: `httpx.MockTransport`, same convention as
test_notify.py (whose helpers this reuses).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from swim_coach.models import ConversationMessage

from test_notify import _grant_coach, _seeded_store, _settings

from app.notify import notify_athlete_of_conversation_message, notify_coach_of_conversation_message


def _client(captured: list[dict]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "email_1"})

    return httpx.Client(transport=httpx.MockTransport(handler))


def _msg(athlete, coach, role: str, body: str, at: datetime) -> ConversationMessage:
    return ConversationMessage(
        id=uuid.uuid4(), athlete_id=athlete.id, coach_athlete_id=coach.id,
        sender_role=role, body=body, created_at=at,
    )


def _setup(tmp_path, **coach_kwargs):
    store, athlete = _seeded_store(tmp_path)
    store.add_allowed_email("renee@example.com", athlete=athlete.slug)
    coach = _grant_coach(
        store, athlete, slug="tim", name="Tim Coach", email="tim@example.com", **coach_kwargs
    )
    return store, athlete, coach


def test_coach_message_emails_the_athlete(tmp_path) -> None:
    store, athlete, coach = _setup(tmp_path)
    message = _msg(athlete, coach, "coach", "nice work this week", datetime.now(timezone.utc))
    store.append_conversation_message(athlete.slug, message)
    sent: list[dict] = []
    notify_athlete_of_conversation_message(store, _settings(), message, athlete.slug, client=_client(sent))
    assert len(sent) == 1
    assert sent[0]["to"] == ["renee@example.com"]
    assert "nice work this week" in sent[0]["text"]


def test_athlete_message_emails_the_thread_coach_only(tmp_path) -> None:
    store, athlete, coach = _setup(tmp_path)
    message = _msg(athlete, coach, "athlete", "shoulder feels tight", datetime.now(timezone.utc))
    store.append_conversation_message(athlete.slug, message)
    sent: list[dict] = []
    notify_coach_of_conversation_message(store, _settings(), message, athlete.slug, client=_client(sent))
    assert [s["to"] for s in sent] == [["tim@example.com"]]
    assert "shoulder feels tight" in sent[0]["text"]


def test_recipient_opt_out_and_missing_key_send_nothing(tmp_path) -> None:
    store, athlete, coach = _setup(tmp_path, email_notifications_enabled=False)
    message = _msg(athlete, coach, "athlete", "hi", datetime.now(timezone.utc))
    store.append_conversation_message(athlete.slug, message)
    sent: list[dict] = []
    notify_coach_of_conversation_message(store, _settings(), message, athlete.slug, client=_client(sent))
    notify_coach_of_conversation_message(
        store, _settings(resend_api_key=None), message, athlete.slug, client=_client(sent)
    )
    assert sent == []


def test_rapid_follow_up_from_the_same_sender_is_throttled(tmp_path) -> None:
    store, athlete, coach = _setup(tmp_path)
    now = datetime.now(timezone.utc)
    first = _msg(athlete, coach, "athlete", "one", now - timedelta(minutes=2))
    second = _msg(athlete, coach, "athlete", "two", now)
    store.append_conversation_message(athlete.slug, first)
    store.append_conversation_message(athlete.slug, second)
    sent: list[dict] = []
    notify_coach_of_conversation_message(store, _settings(), second, athlete.slug, client=_client(sent))
    assert sent == []  # `first` already went out within the throttle window

    long_ago = _msg(athlete, coach, "athlete", "three", now + timedelta(minutes=30))
    store.append_conversation_message(athlete.slug, long_ago)
    notify_coach_of_conversation_message(store, _settings(), long_ago, athlete.slug, client=_client(sent))
    assert len(sent) == 1
