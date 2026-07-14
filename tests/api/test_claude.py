"""Unit tests for `app.claude.ClaudeChat` / `build_request_kwargs`, isolated
from the FastAPI layer. No real Anthropic API calls."""

from __future__ import annotations

import httpx

import anthropic

from app.claude import MAX_TOOL_ITERATIONS, ClaudeChat, build_request_kwargs
from app.config import Settings
from fakes import (
    FakeAnthropicClient,
    make_final_message,
    make_text_block,
    make_tool_use_block,
)


def _settings(**overrides) -> Settings:
    base = dict(
        anthropic_api_key="sk-ant-test",
        api_token_hash="x" * 64,
        claude_model="claude-sonnet-5",
        claude_thinking="adaptive",
        allowed_origins=["https://ashaber.github.io"],
        athletes_dir=None,
        library_dir=None,
        research_dir=None,
        port=8000,
        chat_rate_per_min=20,
        store_backend="file",
        database_url=None,
        google_client_id="test-client-id.apps.googleusercontent.com",
        session_ttl_days=30,
        chat_daily_cap_per_athlete=50,
    )
    base.update(overrides)
    return Settings(**base)


def test_build_request_kwargs_adaptive_thinking_is_explicit() -> None:
    settings = _settings(claude_thinking="adaptive")
    kwargs = build_request_kwargs(settings, system=[], messages=[])
    # Explicit, not omitted -- omission means "off" on the Opus line.
    assert kwargs["thinking"] == {"type": "adaptive"}
    assert "budget_tokens" not in kwargs["thinking"]
    assert "temperature" not in kwargs
    assert "top_p" not in kwargs
    assert "top_k" not in kwargs


def test_build_request_kwargs_disabled_thinking() -> None:
    settings = _settings(claude_thinking="disabled")
    kwargs = build_request_kwargs(settings, system=[], messages=[])
    assert kwargs["thinking"] == {"type": "disabled"}
    assert "budget_tokens" not in kwargs["thinking"]


def test_build_request_kwargs_omits_tools_when_empty() -> None:
    settings = _settings()
    kwargs = build_request_kwargs(settings, system=[], messages=[], tools=[])
    assert "tools" not in kwargs


def test_run_streaming_max_iterations_guard() -> None:
    settings = _settings()
    tool_use = make_tool_use_block("t1", "get_plan_summary", {})
    # Every turn returns tool_use -- would loop forever without the guard.
    turns = [([], make_final_message([tool_use], "tool_use")) for _ in range(MAX_TOOL_ITERATIONS)]
    client = FakeAnthropicClient(turns)
    chat = ClaudeChat(settings, client=client)

    handlers = {"get_plan_summary": lambda _input: {"ok": True}}
    events = list(chat.run_streaming([], [], [{"name": "get_plan_summary"}], handlers))

    assert any('"type": "error"' in e for e in events)
    assert len(client.messages.calls) == MAX_TOOL_ITERATIONS


def test_run_streaming_handles_anthropic_api_error() -> None:
    settings = _settings()

    class BrokenMessagesAPI:
        def stream(self, **kwargs):
            request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
            raise anthropic.APIConnectionError(request=request)

    class BrokenClient:
        def __init__(self):
            self.messages = BrokenMessagesAPI()

    chat = ClaudeChat(settings, client=BrokenClient())
    events = list(chat.run_streaming([], [{"role": "user", "content": "hi"}], [], {}))

    assert len(events) == 1
    assert '"type": "error"' in events[0]


def test_run_streaming_unknown_tool_reports_error_result() -> None:
    settings = _settings()
    tool_use = make_tool_use_block("t1", "not_a_real_tool", {})
    turn_1 = make_final_message([tool_use], "tool_use")
    turn_2 = make_final_message([make_text_block("done")], "end_turn")
    client = FakeAnthropicClient([([], turn_1), (["done"], turn_2)])
    chat = ClaudeChat(settings, client=client)

    list(chat.run_streaming([], [], [], {}))  # no handlers registered at all

    second_call_messages = client.messages.calls[1]["messages"]
    tool_result = second_call_messages[-1]["content"][0]
    assert "unknown tool" in tool_result["content"]


def test_replayed_assistant_content_drops_sdk_only_null_fields() -> None:
    # D1: a text block emitted alongside a tool_use carries SDK-only null
    # fields (parsed_output/citations). When the assistant turn is replayed on
    # the follow-up request, those must not be sent back or the API 400s with
    # "text.parsed_output: Extra inputs are not permitted".
    settings = _settings()
    text = make_text_block("logging a question for research...")
    tool_use = make_tool_use_block("t1", "log_open_question", {"question": "fueling?"})
    turn_1 = make_final_message([text, tool_use], "tool_use")
    turn_2 = make_final_message([make_text_block("done")], "end_turn")
    client = FakeAnthropicClient([([], turn_1), (["done"], turn_2)])
    chat = ClaudeChat(settings, client=client)

    list(chat.run_streaming([], [], [], {"log_open_question": lambda _in: {"ok": True}}))

    replayed = client.messages.calls[1]["messages"]
    assistant_turn = next(m for m in replayed if m["role"] == "assistant")
    text_blocks = [b for b in assistant_turn["content"] if b["type"] == "text"]
    assert text_blocks, "the assistant's text block must be replayed"
    for block in assistant_turn["content"]:
        assert "parsed_output" not in block
        assert "citations" not in block
