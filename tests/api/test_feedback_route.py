"""POST/GET /api/feedback -- the durable feedback log (IDEA 005 generalized:
coach research questions plus athlete feature requests/comments/bugs).

Same conventions as test_workouts_route.py / test_wellness_route.py -- the
real FileStore (via the `client`/`athletes_dir` fixtures) is exercised here,
not a fake.
"""

from __future__ import annotations

import uuid

import pytest
from fakes import (
    auth_headers,
    make_final_message,
    make_text_block,
    make_workout,
)

from app.routes.feedback import get_notifier


def _valid_payload(**overrides) -> dict:
    payload = {"type": "feature_request", "body": "Please add a pace calculator."}
    payload.update(overrides)
    return payload


def test_create_feedback_requires_auth(client) -> None:
    response = client.post("/api/feedback?athlete=renee", json=_valid_payload())
    assert response.status_code == 401


def test_list_feedback_requires_auth(client) -> None:
    response = client.get("/api/feedback?athlete=renee")
    assert response.status_code == 401


def test_create_feedback_persists_and_returns_created_object(client) -> None:
    response = client.post(
        "/api/feedback?athlete=renee", json=_valid_payload(), headers=auth_headers()
    )
    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "feature_request"
    assert body["source"] == "athlete"
    assert body["body"] == "Please add a pace calculator."
    assert body["status"] == "open"
    assert body["schema_version"] == 1
    assert body["id"]
    assert body["athlete_id"]
    assert body["created_at"]


def test_create_feedback_accepts_comment_and_bug(client) -> None:
    for feedback_type in ("comment", "bug"):
        response = client.post(
            "/api/feedback?athlete=renee",
            json=_valid_payload(type=feedback_type, body=f"a {feedback_type}"),
            headers=auth_headers(),
        )
        assert response.status_code == 200
        assert response.json()["type"] == feedback_type


def test_create_feedback_accepts_question_type(client) -> None:
    response = client.post(
        "/api/feedback?athlete=renee",
        json=_valid_payload(type="question", body="how should I fuel a 4hr swim?"),
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert response.json()["type"] == "question"


def test_create_feedback_rejects_research_question(client) -> None:
    response = client.post(
        "/api/feedback?athlete=renee",
        json=_valid_payload(type="research_question", body="is taper research swim-specific?"),
        headers=auth_headers(),
    )
    assert response.status_code == 422
    assert "error" in response.json()


def test_create_feedback_rejects_missing_body(client) -> None:
    payload = _valid_payload()
    del payload["body"]
    response = client.post(
        "/api/feedback?athlete=renee", json=payload, headers=auth_headers()
    )
    assert response.status_code == 422
    assert "error" in response.json()


def test_create_feedback_rejects_invalid_type(client) -> None:
    response = client.post(
        "/api/feedback?athlete=renee",
        json=_valid_payload(type="not-a-real-type"),
        headers=auth_headers(),
    )
    assert response.status_code == 422
    assert "error" in response.json()


def test_create_feedback_unknown_athlete_is_404(client) -> None:
    response = client.post(
        "/api/feedback?athlete=nobody", json=_valid_payload(), headers=auth_headers()
    )
    assert response.status_code == 404
    assert "error" in response.json()


def test_create_feedback_ignores_client_supplied_server_fields(client) -> None:
    response = client.post(
        "/api/feedback?athlete=renee",
        json=_valid_payload(
            id="00000000-0000-0000-0000-000000000000",
            athlete_id="00000000-0000-0000-0000-000000000000",
            source="coach",
            status="resolved",
        ),
        headers=auth_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] != "00000000-0000-0000-0000-000000000000"
    assert body["athlete_id"] != "00000000-0000-0000-0000-000000000000"
    assert body["source"] == "athlete"
    assert body["status"] == "open"


def test_list_feedback_returns_what_was_saved_most_recent_first(client) -> None:
    created = []
    for body in ("first one", "second one"):
        response = client.post(
            "/api/feedback?athlete=renee",
            json=_valid_payload(body=body),
            headers=auth_headers(),
        )
        assert response.status_code == 200
        created.append(response.json())

    response = client.get("/api/feedback?athlete=renee", headers=auth_headers())
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    created_ids = {f["id"] for f in created}
    returned_ids = {f["id"] for f in body}
    assert created_ids.issubset(returned_ids)


def test_list_feedback_unknown_athlete_is_404(client) -> None:
    response = client.get("/api/feedback?athlete=nobody", headers=auth_headers())
    assert response.status_code == 404
    assert "error" in response.json()


def _create(client, **overrides) -> dict:
    response = client.post(
        "/api/feedback?athlete=renee",
        json=_valid_payload(**overrides),
        headers=auth_headers(),
    )
    assert response.status_code == 200
    return response.json()


def test_patch_feedback_requires_auth(client) -> None:
    created = _create(client)
    response = client.patch(f"/api/feedback/{created['id']}", json={"status": "resolved"})
    assert response.status_code == 401


def test_patch_feedback_updates_status(client) -> None:
    created = _create(client)
    response = client.patch(
        f"/api/feedback/{created['id']}",
        json={"status": "resolved"},
        headers=auth_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == created["id"]
    assert body["status"] == "resolved"


def test_patch_feedback_merges_context_without_clobbering(client) -> None:
    created = _create(
        client,
        type="comment",
        body="taper research question",
        context={"topic": "taper", "n": 1},
    )
    response = client.patch(
        f"/api/feedback/{created['id']}",
        json={"status": "resolved", "context": {"n": 2, "resolution": "see 03-periodization.md"}},
        headers=auth_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "resolved"
    assert body["context"] == {
        "topic": "taper",
        "n": 2,
        "resolution": "see 03-periodization.md",
    }


def test_patch_feedback_unknown_id_is_404(client) -> None:
    response = client.patch(
        "/api/feedback/00000000-0000-0000-0000-000000000000",
        json={"status": "resolved"},
        headers=auth_headers(),
    )
    assert response.status_code == 404
    assert "error" in response.json()


def test_patch_feedback_invalid_status_type_is_422(client) -> None:
    created = _create(client)
    response = client.patch(
        f"/api/feedback/{created['id']}",
        json={"status": 12345},
        headers=auth_headers(),
    )
    assert response.status_code == 422
    assert "error" in response.json()


def test_patch_feedback_accepts_needs_human_review(client) -> None:
    created = _create(client)
    response = client.patch(
        f"/api/feedback/{created['id']}",
        json={"needs_human_review": True},
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert response.json()["needs_human_review"] is True


def test_patch_feedback_invalid_needs_human_review_type_is_422(client) -> None:
    created = _create(client)
    response = client.patch(
        f"/api/feedback/{created['id']}",
        json={"needs_human_review": "yes"},
        headers=auth_headers(),
    )
    assert response.status_code == 422
    assert "error" in response.json()


def test_patch_feedback_does_not_disturb_other_entries(client) -> None:
    keep = _create(client, body="leave me alone")
    target = _create(client, body="patch me")
    response = client.patch(
        f"/api/feedback/{target['id']}",
        json={"status": "resolved"},
        headers=auth_headers(),
    )
    assert response.status_code == 200

    listing = client.get("/api/feedback?athlete=renee", headers=auth_headers())
    by_id = {f["id"]: f for f in listing.json()}
    assert by_id[keep["id"]]["status"] == "open"
    assert by_id[target["id"]]["status"] == "resolved"


# --- POST /api/feedback/questions -------------------------------------------
#
# The direct-to-coach question endpoint: a one-shot, non-streaming call
# through ClaudeChat.run_once (app/claude.py), persisted as a Feedback row
# with type="question". Same fake-ClaudeChat convention as test_chat.py --
# `fake_claude_chat_factory` overrides get_claude_chat with a ClaudeChat
# wired to a fake Anthropic client, so run_once never touches the network.


def _question_payload(**overrides) -> dict:
    payload = {"body": "how should I fuel a 4hr swim?"}
    payload.update(overrides)
    return payload


def test_ask_question_requires_auth(client) -> None:
    response = client.post("/api/feedback/questions?athlete=renee", json=_question_payload())
    assert response.status_code == 401


def test_ask_question_happy_path_persists_provisional_answer(
    client, fake_claude_chat_factory
) -> None:
    final = make_final_message(
        [make_text_block("Aim for 60-90g carbs/hr, starting within the first 30 minutes.")],
        "end_turn",
    )
    fake_claude_chat_factory(
        [(["Aim for 60-90g carbs/hr, starting within the first 30 minutes."], final)]
    )

    response = client.post(
        "/api/feedback/questions?athlete=renee",
        json=_question_payload(),
        headers=auth_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "question"
    assert body["source"] == "athlete"
    assert body["body"] == "how should I fuel a 4hr swim?"
    assert body["ai_provisional_answer"] == (
        "Aim for 60-90g carbs/hr, starting within the first 30 minutes."
    )
    assert body["needs_human_review"] is False
    assert body["workout_id"] is None


def test_ask_question_direct_to_coach_sets_needs_human_review(
    client, fake_claude_chat_factory
) -> None:
    final = make_final_message([make_text_block("Provisional answer.")], "end_turn")
    fake_claude_chat_factory([(["Provisional answer."], final)])

    response = client.post(
        "/api/feedback/questions?athlete=renee",
        json=_question_payload(direct_to_coach=True),
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert response.json()["needs_human_review"] is True


def test_ask_question_workout_id_linkage(
    client, fake_claude_chat_factory, athletes_dir
) -> None:
    from swim_coach.store import FileStore

    store = FileStore(base_dir=athletes_dir)
    profile = store.load_athlete("renee")
    workout = make_workout(athlete_id=profile.id)
    store.save_workout("renee", workout)

    final = make_final_message([make_text_block("Nice swim.")], "end_turn")
    fake_claude_chat_factory([(["Nice swim."], final)])

    response = client.post(
        "/api/feedback/questions?athlete=renee",
        json=_question_payload(workout_id=str(workout.id)),
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert response.json()["workout_id"] == str(workout.id)


def test_ask_question_unknown_workout_id_is_404(client, fake_claude_chat_factory) -> None:
    chat = fake_claude_chat_factory([])

    response = client.post(
        "/api/feedback/questions?athlete=renee",
        json=_question_payload(workout_id="ffffffff-0000-0000-0000-000000000000"),
        headers=auth_headers(),
    )
    assert response.status_code == 404
    assert "error" in response.json()
    assert chat.client.messages.calls == []


def test_ask_question_missing_body_is_422(client, fake_claude_chat_factory) -> None:
    fake_claude_chat_factory([])
    response = client.post(
        "/api/feedback/questions?athlete=renee", json={}, headers=auth_headers()
    )
    assert response.status_code == 422
    assert "error" in response.json()


def test_ask_question_rate_limit_enforced(client, fake_claude_chat_factory) -> None:
    # app_env sets CHAT_RATE_PER_MIN=3 -- shares the same per-token limiter
    # /api/chat uses, so the 4th call in a minute for the same (service)
    # token is a 429.
    def _one_call():
        final = make_final_message([make_text_block("ok")], "end_turn")
        fake_claude_chat_factory([(["ok"], final)])
        return client.post(
            "/api/feedback/questions?athlete=renee",
            json=_question_payload(),
            headers=auth_headers(),
        )

    statuses = [_one_call().status_code for _ in range(4)]
    assert statuses[:3] == [200, 200, 200]
    assert statuses[3] == 429


def test_ask_question_run_once_error_is_502_not_a_crash(client, fake_claude_chat_factory) -> None:
    final = make_final_message([], "refusal")
    fake_claude_chat_factory([([], final)])

    response = client.post(
        "/api/feedback/questions?athlete=renee",
        json=_question_payload(),
        headers=auth_headers(),
    )
    assert response.status_code == 502
    assert "error" in response.json()


# --- Coach-notification wiring (BackgroundTasks -> app/notify.py) ----------
#
# `get_notifier` (routes/feedback.py) is the dependency-injection seam, the
# SAME pattern as `get_claude_chat` above -- tests override it with a spy so
# the assertion is "was the notifier scheduled with the right args", never an
# attempt to peek inside Starlette's BackgroundTasks internals or reach a
# real Resend API. TestClient runs BackgroundTasks synchronously (as part of
# the same ASGI call) before `client.post(...)` returns, so the spy's calls
# are already populated by the time each test asserts on them.


@pytest.fixture
def spy_notifier(app):
    calls = []

    def fake_notifier(store, settings, feedback, athlete):
        calls.append({"feedback": feedback, "athlete": athlete})

    app.dependency_overrides[get_notifier] = lambda: fake_notifier
    yield calls
    app.dependency_overrides.pop(get_notifier, None)


def test_create_feedback_schedules_notification(client, spy_notifier) -> None:
    response = client.post(
        "/api/feedback?athlete=renee", json=_valid_payload(), headers=auth_headers()
    )
    assert response.status_code == 200
    assert len(spy_notifier) == 1
    assert spy_notifier[0]["athlete"] == "renee"
    assert spy_notifier[0]["feedback"].id == uuid.UUID(response.json()["id"])


def test_ask_question_schedules_notification(
    client, fake_claude_chat_factory, spy_notifier
) -> None:
    final = make_final_message([make_text_block("Provisional answer.")], "end_turn")
    fake_claude_chat_factory([(["Provisional answer."], final)])

    response = client.post(
        "/api/feedback/questions?athlete=renee",
        json=_question_payload(),
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert len(spy_notifier) == 1
    assert spy_notifier[0]["athlete"] == "renee"
    assert spy_notifier[0]["feedback"].id == uuid.UUID(response.json()["id"])


def test_create_feedback_notification_failure_does_not_break_response(client) -> None:
    """A real integration-shaped check: even with the REAL notifier (not the
    spy above) wired in and no RESEND_API_KEY configured (the test env's
    default -- see app_env, which never sets it), the feedback save and HTTP
    response are completely unaffected. This is the behavior the whole
    BackgroundTasks/never-raises design exists to guarantee."""
    response = client.post(
        "/api/feedback?athlete=renee", json=_valid_payload(), headers=auth_headers()
    )
    assert response.status_code == 200
    assert response.json()["body"] == "Please add a pace calculator."
