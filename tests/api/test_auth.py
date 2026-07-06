"""Bearer-token auth and per-token chat rate limiting.

`/api/chat` is used (rather than /health) because auth applies to it; the
Claude client is always faked here (`fake_claude_chat_factory`) so these
tests never come close to a real network call even on a 200.
"""

from __future__ import annotations

from fakes import auth_headers, make_final_message, make_text_block


def _chat_payload(message: str = "hello") -> dict:
    return {"message": message, "history": [], "athlete": "renee", "expert_mode": False}


def test_chat_without_authorization_header_is_401(client) -> None:
    response = client.post("/api/chat", json=_chat_payload())
    assert response.status_code == 401
    assert "error" in response.json()


def test_chat_with_malformed_authorization_header_is_401(client) -> None:
    response = client.post(
        "/api/chat", json=_chat_payload(), headers={"Authorization": "NotBearer xyz"}
    )
    assert response.status_code == 401


def test_chat_with_wrong_token_is_401(client) -> None:
    response = client.post(
        "/api/chat", json=_chat_payload(), headers=auth_headers("wrong-token")
    )
    assert response.status_code == 401


def test_chat_with_correct_token_succeeds(client, fake_claude_chat_factory) -> None:
    final = make_final_message([make_text_block("hi there")], stop_reason="end_turn")
    fake_claude_chat_factory([(["hi there"], final)])

    response = client.post("/api/chat", json=_chat_payload(), headers=auth_headers())
    assert response.status_code == 200
    assert "hi there" in response.text


def test_chat_rate_limit_triggers(client, fake_claude_chat_factory) -> None:
    # app_env sets CHAT_RATE_PER_MIN=3.
    def make_turn():
        final = make_final_message([make_text_block("ok")], stop_reason="end_turn")
        return [(["ok"], final)]

    responses = []
    for _ in range(4):
        fake_claude_chat_factory(make_turn())
        responses.append(client.post("/api/chat", json=_chat_payload(), headers=auth_headers()))

    statuses = [r.status_code for r in responses]
    assert statuses[:3] == [200, 200, 200]
    assert statuses[3] == 429
    assert "error" in responses[3].json()
