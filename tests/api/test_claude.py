"""Unit tests for `app.claude.ClaudeChat` / `build_request_kwargs`, isolated
from the FastAPI layer. No real Anthropic API calls."""

from __future__ import annotations

import httpx

import anthropic

import json

from app.claude import (
    MAX_TOKENS_TRUNCATION_MARKER,
    MAX_TOOL_ITERATIONS,
    ClaudeChat,
    build_request_kwargs,
)
from app.config import Settings
from fakes import (
    FakeAnthropicClient,
    make_final_message,
    make_text_block,
    make_tool_use_block,
    make_usage,
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


def test_max_tokens_stop_reason_appends_visible_marker_and_warns(capsys) -> None:
    # Prod 2026-09-10: a "redraft this week" turn hit stop_reason=max_tokens
    # at exactly 16384 output tokens; the PWA showed a truncated answer with
    # NO indication anything was cut off. Never silent: the streamed text
    # must carry a visible marker AND app.claude must emit a WARN log so
    # every hit is a reviewable signal.
    settings = _settings()
    final = make_final_message(
        [make_text_block("Here is the start of the redraft")],
        "max_tokens",
        usage=make_usage(output_tokens=16384),
    )
    client = FakeAnthropicClient([(["Here is the start of the redraft"], final)])
    chat = ClaudeChat(settings, client=client)

    events = list(
        chat.run_streaming(
            [], [{"role": "user", "content": "redraft this week"}], [{"name": "create_week_plan"}], {}
        )
    )

    # The partial text still reaches the client, followed by the visible marker.
    text_events = [json.loads(e[len("data: ") :]) for e in events if '"type": "text"' in e]
    joined = "".join(t["text"] for t in text_events)
    assert "Here is the start of the redraft" in joined
    assert MAX_TOKENS_TRUNCATION_MARKER in joined
    assert "cut off" in MAX_TOKENS_TRUNCATION_MARKER

    # Loop still terminates cleanly with a done event carrying the reason.
    assert any('"type": "done"' in e and "max_tokens" in e for e in events)

    # WARN log from app.claude, with the review-signal fields.
    logged = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{") and "max_tokens" in line
    ]
    warn = next(r for r in logged if r["level"] == "warn" and r["msg"] == "turn hit max_tokens")
    assert warn["output_tokens"] == 16384
    assert warn["iteration"] == 0
    assert "create_week_plan" in warn["tools_available"]


def test_max_tokens_marker_not_emitted_on_normal_end_turn() -> None:
    settings = _settings()
    final = make_final_message([make_text_block("all done, nothing cut")], "end_turn")
    client = FakeAnthropicClient([(["all done, nothing cut"], final)])
    chat = ClaudeChat(settings, client=client)

    events = list(chat.run_streaming([], [{"role": "user", "content": "hi"}], [], {}))
    assert not any(MAX_TOKENS_TRUNCATION_MARKER in e for e in events)


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
    tool_use = make_tool_use_block("t1", "flag_for_coach_review", {"question": "fueling?"})
    turn_1 = make_final_message([text, tool_use], "tool_use")
    turn_2 = make_final_message([make_text_block("done")], "end_turn")
    client = FakeAnthropicClient([([], turn_1), (["done"], turn_2)])
    chat = ClaudeChat(settings, client=client)

    list(chat.run_streaming([], [], [], {"flag_for_coach_review": lambda _in: {"ok": True}}))

    replayed = client.messages.calls[1]["messages"]
    assistant_turn = next(m for m in replayed if m["role"] == "assistant")
    text_blocks = [b for b in assistant_turn["content"] if b["type"] == "text"]
    assert text_blocks, "the assistant's text block must be replayed"
    for block in assistant_turn["content"]:
        assert "parsed_output" not in block
        assert "citations" not in block
