"""Coach-only "Ask AI coach" in a workout thread.

`POST /api/coach/athletes/{slug}/chat` with a `workout_id` runs the AI as the coach on that
workout; the question and the reply persist onto `Workout.chat_messages` as
`visibility="coach_only"` and must be invisible to the athlete on every read path.
"""

from __future__ import annotations

import pytest

from fakes import auth_headers, make_final_message, make_text_block, message_text
from test_coach_route import (  # noqa: F401  (fixtures re-used from the sibling module)
    ANDREW_EMAIL,
    _bearer,
    _renee_headers,
    _seed_workout,
    _sign_in,
    _tim_headers,
    _workout_chat_url,
    allowlist,
    google,
    store,
)

PRIVATE_Q = "reanalyze this workout please"
PRIVATE_A = "Re-ran the analysis; the last 400m was the fade."


def _ask_ai(client, headers, workout_id, message: str = PRIVATE_Q):
    return client.post(
        "/api/coach/athletes/renee/chat",
        json={"message": message, "history": [], "workout_id": str(workout_id)},
        headers=headers,
    )


def _chat_with_reply(fake_claude_chat_factory, text: str = PRIVATE_A):
    final = make_final_message([make_text_block(text)], "end_turn")
    return fake_claude_chat_factory([([text], final)])


def _sent_text(chat) -> str:
    return " ".join(message_text(m["content"]) for m in chat.client.messages.calls[0]["messages"])


def test_coach_ask_ai_persists_coach_only_messages(
    client, allowlist, store, google, fake_claude_chat_factory
) -> None:
    store.create_coach_grant(coach_slug="tim", athlete_slug="renee")
    workout = _seed_workout(store, "renee")
    _chat_with_reply(fake_claude_chat_factory)
    headers = _tim_headers(client, allowlist, google)

    assert _ask_ai(client, headers, workout.id).status_code == 200

    tim_id = store.load_athlete("tim").id
    messages = store.get_workout("renee", workout.id).chat_messages
    assert [(m.sender_role, m.body, m.visibility, m.coach_athlete_id) for m in messages] == [
        ("coach", PRIVATE_Q, "coach_only", tim_id),
        ("ai_coach", PRIVATE_A, "coach_only", tim_id),
    ]


def test_coach_ask_ai_runs_even_when_athlete_thread_is_muted(
    client, allowlist, store, google, fake_claude_chat_factory
) -> None:
    store.create_coach_grant(coach_slug="tim", athlete_slug="renee")
    workout = _seed_workout(store, "renee", chat_ai_muted=True)
    chat = _chat_with_reply(fake_claude_chat_factory)
    headers = _tim_headers(client, allowlist, google)

    assert _ask_ai(client, headers, workout.id).status_code == 200
    assert len(chat.client.messages.calls) == 1


def test_coach_ask_ai_403_without_grant_and_persists_nothing(client, allowlist, store, google) -> None:
    workout = _seed_workout(store, "renee")
    headers = _tim_headers(client, allowlist, google)

    assert _ask_ai(client, headers, workout.id).status_code == 403
    assert store.get_workout("renee", workout.id).chat_messages == []


def test_coach_ask_ai_service_principal_is_403(client, allowlist, store) -> None:
    workout = _seed_workout(store, "renee")
    assert _ask_ai(client, auth_headers(), workout.id).status_code == 403


def test_coach_ask_ai_unknown_workout_is_404(client, allowlist, store, google) -> None:
    store.create_coach_grant(coach_slug="tim", athlete_slug="renee")
    headers = _tim_headers(client, allowlist, google)
    assert _ask_ai(client, headers, "00000000-0000-0000-0000-000000000000").status_code == 404


@pytest.fixture
def private_thread(client, allowlist, store, google, fake_claude_chat_factory):
    """A renee workout with one public coach note then one private Ask-AI exchange by tim."""
    store.create_coach_grant(coach_slug="tim", athlete_slug="renee")
    workout = _seed_workout(store, "renee")
    tim = _tim_headers(client, allowlist, google)
    client.post(_workout_chat_url("renee", workout.id), json={"body": "public note to renee"}, headers=tim)
    _chat_with_reply(fake_claude_chat_factory)
    assert _ask_ai(client, tim, workout.id).status_code == 200
    return workout, tim


def test_athlete_workout_list_excludes_coach_only_messages(client, allowlist, google, private_thread) -> None:
    workout, _ = private_thread
    rows = client.get("/api/workouts", headers=_renee_headers(client, allowlist, google)).json()
    row = next(r for r in rows if r["id"] == str(workout.id))
    assert [m["body"] for m in row["chat_messages"]] == ["public note to renee"]


def test_athlete_patch_response_excludes_coach_only_but_keeps_them_stored(
    client, allowlist, store, google, private_thread
) -> None:
    workout, _ = private_thread
    renee = _renee_headers(client, allowlist, google)

    response = client.patch(f"/api/workouts/{workout.id}", json={"rpe": 7}, headers=renee)
    assert response.status_code == 200
    assert [m["body"] for m in response.json()["chat_messages"]] == ["public note to renee"]
    assert len(store.get_workout("renee", workout.id).chat_messages) == 3


def test_athlete_ai_turn_history_excludes_coach_only_messages(
    client, allowlist, store, google, fake_claude_chat_factory, private_thread
) -> None:
    workout, _ = private_thread
    renee = _renee_headers(client, allowlist, google)
    chat = _chat_with_reply(fake_claude_chat_factory, "athlete-side answer")

    response = client.post(
        "/api/chat",
        json={"message": "how did it go?", "history": [], "workout_id": str(workout.id), "athlete": "renee"},
        headers=renee,
    )
    assert response.status_code == 200
    sent = _sent_text(chat)
    assert "public note to renee" in sent
    assert PRIVATE_Q not in sent and PRIVATE_A not in sent
    bodies = [m.body for m in store.get_workout("renee", workout.id).chat_messages]
    assert bodies[-2:] == ["how did it go?", "athlete-side answer"]


def test_coach_view_shows_only_own_coach_only_messages(
    client, allowlist, store, google, private_thread
) -> None:
    workout, tim = private_thread
    store.create_coach_grant(coach_slug="andrew", athlete_slug="renee")

    def thread(headers):
        rows = client.get("/api/coach/athletes/renee/workouts?days=365", headers=headers).json()
        return [m["body"] for r in rows if r["id"] == str(workout.id) for m in r["chat_messages"]]

    assert thread(tim) == ["public note to renee", PRIVATE_Q, PRIVATE_A]
    andrew = _bearer(_sign_in(client, ANDREW_EMAIL).json()["token"])
    assert thread(andrew) == ["public note to renee"]


def test_second_private_turn_sees_prior_private_history(
    client, fake_claude_chat_factory, private_thread
) -> None:
    workout, tim = private_thread
    chat = _chat_with_reply(fake_claude_chat_factory, "second answer")
    assert _ask_ai(client, tim, workout.id, "and the second half?").status_code == 200
    sent = _sent_text(chat)
    assert PRIVATE_Q in sent and PRIVATE_A in sent
