"""POST /api/chat: request-shape assertions (the exact Claude API usage
this build is supposed to follow) plus the tool loop and SSE streaming
behavior. The Anthropic client is always fake -- see conftest.py.
"""

from __future__ import annotations

import json

from fakes import (
    auth_headers,
    make_final_message,
    make_text_block,
    make_tool_use_block,
    make_usage,
)


def _chat_payload(**overrides) -> dict:
    payload = {"message": "why is this week's volume lower?", "history": [], "athlete": "renee", "expert_mode": False}
    payload.update(overrides)
    return payload


def test_request_shape_no_temperature_top_p_top_k(client, fake_claude_chat_factory) -> None:
    final = make_final_message([make_text_block("because you're in a mini-taper week")], "end_turn")
    chat = fake_claude_chat_factory([(["because you're in a mini-taper week"], final)])

    response = client.post("/api/chat", json=_chat_payload(), headers=auth_headers())
    assert response.status_code == 200

    assert len(chat.client.messages.calls) == 1
    kwargs = chat.client.messages.calls[0]
    assert kwargs["model"] == "claude-opus-4-8"
    assert kwargs["max_tokens"] == 2048
    for forbidden in ("temperature", "top_p", "top_k"):
        assert forbidden not in kwargs
    # adaptive (the default) is passed explicitly -- omission would mean
    # "off" on the Opus line.
    assert kwargs["thinking"] == {"type": "adaptive"}


def test_request_shape_includes_tools(client, fake_claude_chat_factory) -> None:
    final = make_final_message([make_text_block("ok")], "end_turn")
    chat = fake_claude_chat_factory([(["ok"], final)])

    client.post("/api/chat", json=_chat_payload(), headers=auth_headers())

    tools = chat.client.messages.calls[0]["tools"]
    tool_names = {t["name"] for t in tools}
    assert tool_names == {
        "propose_adaptation",
        "get_plan_summary",
        "log_open_question",
        "get_workouts",
    }


def test_request_shape_system_is_two_cacheable_blocks(client, fake_claude_chat_factory) -> None:
    final = make_final_message([make_text_block("ok")], "end_turn")
    chat = fake_claude_chat_factory([(["ok"], final)])

    client.post("/api/chat", json=_chat_payload(), headers=auth_headers())

    system = chat.client.messages.calls[0]["system"]
    assert len(system) == 2
    assert all(block["cache_control"] == {"type": "ephemeral"} for block in system)


def test_system_prefix_is_byte_stable_across_two_different_messages(
    client, fake_claude_chat_factory
) -> None:
    final_1 = make_final_message([make_text_block("a")], "end_turn")
    chat_1 = fake_claude_chat_factory([(["a"], final_1)])
    client.post(
        "/api/chat",
        json=_chat_payload(message="why did this week get cut?"),
        headers=auth_headers(),
    )
    system_1 = chat_1.client.messages.calls[0]["system"]

    final_2 = make_final_message([make_text_block("b")], "end_turn")
    chat_2 = fake_claude_chat_factory([(["b"], final_2)])
    client.post(
        "/api/chat",
        json=_chat_payload(message="why was my plan repeated, not advanced?"),
        headers=auth_headers(),
    )
    system_2 = chat_2.client.messages.calls[0]["system"]

    # Both questions land in the same keyword bucket (03-periodization.md) --
    # the cacheable system prefix must be byte-identical so they share a
    # cache entry.
    assert system_1 == system_2


def test_disabled_thinking_mode_is_passed_explicitly(app_env, monkeypatch) -> None:
    monkeypatch.setenv("CLAUDE_THINKING", "disabled")
    # app_env's app fixture already built an app with the default (adaptive)
    # setting, so build a fresh one here with CLAUDE_THINKING=disabled.
    from app.main import create_app
    from app.claude import ClaudeChat
    from app.routes.chat import get_claude_chat
    from fakes import FakeAnthropicClient
    from fastapi.testclient import TestClient

    app = create_app()
    assert app.state.settings.claude_thinking == "disabled"

    final = make_final_message([make_text_block("ok")], "end_turn")
    fake_client = FakeAnthropicClient([(["ok"], final)])
    app.dependency_overrides[get_claude_chat] = lambda: ClaudeChat(
        app.state.settings, client=fake_client
    )

    with TestClient(app) as local_client:
        local_client.post("/api/chat", json=_chat_payload(), headers=auth_headers())

    kwargs = fake_client.messages.calls[0]
    assert kwargs["thinking"] == {"type": "disabled"}


def test_streaming_text_reaches_the_client(client, fake_claude_chat_factory) -> None:
    final = make_final_message(
        [make_text_block("Your volume is lower this week because of a mini-taper.")], "end_turn"
    )
    fake_claude_chat_factory(
        [(["Your volume is lower ", "this week because of a mini-taper."], final)]
    )

    response = client.post("/api/chat", json=_chat_payload(), headers=auth_headers())
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "Your volume is lower" in response.text
    assert "mini-taper" in response.text
    assert '"type": "done"' in response.text


def test_refusal_stop_reason_is_handled_before_reading_content(
    client, fake_claude_chat_factory
) -> None:
    final = make_final_message([], "refusal", usage=make_usage())
    fake_claude_chat_factory([([], final)])

    response = client.post("/api/chat", json=_chat_payload(), headers=auth_headers())
    assert response.status_code == 200
    assert '"type": "refusal"' in response.text


def test_tool_loop_calls_get_plan_summary_and_continues(client, fake_claude_chat_factory) -> None:
    tool_use = make_tool_use_block("toolu_1", "get_plan_summary", {"weeks": 4})
    turn_1 = make_final_message([tool_use], "tool_use")
    turn_2 = make_final_message(
        [make_text_block("Your compliance has been solid the last 4 weeks.")], "end_turn"
    )
    chat = fake_claude_chat_factory(
        [([], turn_1), (["Your compliance has been solid the last 4 weeks."], turn_2)]
    )

    response = client.post(
        "/api/chat",
        json=_chat_payload(message="how is my compliance / consistency looking?"),
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert '"type": "tool_use"' in response.text
    assert "compliance has been solid" in response.text

    # The second turn's request must include the tool_result appended to messages.
    assert len(chat.client.messages.calls) == 2
    second_call_messages = chat.client.messages.calls[1]["messages"]
    assert second_call_messages[-1]["role"] == "user"
    tool_result_blocks = second_call_messages[-1]["content"]
    assert tool_result_blocks[0]["type"] == "tool_result"
    assert tool_result_blocks[0]["tool_use_id"] == "toolu_1"
    result_payload = json.loads(tool_result_blocks[0]["content"])
    assert "compliance_pct" in result_payload


def test_tool_loop_propose_adaptation_does_not_persist(client, fake_claude_chat_factory, athletes_dir) -> None:
    tool_use = make_tool_use_block("toolu_2", "propose_adaptation", {"iso_week": "2026-W30"})
    turn_1 = make_final_message([tool_use], "tool_use")
    turn_2 = make_final_message([make_text_block("Here's a draft for next week.")], "end_turn")
    fake_claude_chat_factory([([], turn_1), (["Here's a draft for next week."], turn_2)])

    week_file = athletes_dir / "renee" / "plan" / "weeks" / "2026-W30.yaml"
    assert not week_file.exists()

    response = client.post(
        "/api/chat",
        json=_chat_payload(message="can you draft next week for me?"),
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert "Here's a draft" in response.text

    # propose_adaptation must never write to disk.
    assert not week_file.exists()


def test_tool_loop_log_open_question_persists_feedback(
    client, fake_claude_chat_factory, athletes_dir, run_tag
) -> None:
    question = f"does cold-water acclimation change fueling needs? [{run_tag}]"
    tool_use = make_tool_use_block(
        "toolu_3", "log_open_question", {"question": question, "topic": "nutrition"}
    )
    turn_1 = make_final_message([tool_use], "tool_use")
    turn_2 = make_final_message(
        [make_text_block("I don't know -- I've logged that for follow-up.")], "end_turn"
    )
    fake_claude_chat_factory(
        [([], turn_1), (["I don't know -- I've logged that for follow-up."], turn_2)]
    )

    response = client.post(
        "/api/chat",
        json=_chat_payload(message="does cold water change fueling?", expert_mode=True),
        headers=auth_headers(),
    )
    assert response.status_code == 200

    from swim_coach.store import FileStore

    store = FileStore(base_dir=athletes_dir)
    entries = store.list_feedback(athlete="renee")
    matching = [e for e in entries if run_tag in e.body]
    assert len(matching) == 1
    assert matching[0].type == "research_question"
    assert matching[0].source == "coach"
    assert matching[0].context["topic"] == "nutrition"
    assert matching[0].context["expert_mode"] is True
