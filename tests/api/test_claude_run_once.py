"""Unit tests for `ClaudeChat.run_once` -- the non-streaming counterpart to
`run_streaming` used by the direct-to-coach question endpoint
(`POST /api/feedback/questions`), which needs one complete answer string to
persist, not an SSE stream to relay to a browser.

Contract under test (see `run_once`'s docstring in app/claude.py): on a
normal turn (or a turn that runs a tool mid-way and continues), it returns
the concatenated text of every "text" event. On a "refusal" or "error"
terminal event, it raises `RuntimeError` rather than returning a normal
string -- the caller must handle that explicitly, never let it 500 silently.
"""

from __future__ import annotations

from app.claude import ClaudeChat
from app.config import Settings
from fakes import (
    FakeAnthropicClient,
    make_final_message,
    make_text_block,
    make_tool_use_block,
)

import pytest


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


def test_run_once_returns_concatenated_text_on_normal_turn() -> None:
    settings = _settings()
    final = make_final_message(
        [make_text_block("For a 4-hour swim, "), make_text_block("aim for 60-90g carbs/hr.")],
        "end_turn",
    )
    client = FakeAnthropicClient([(["For a 4-hour swim, ", "aim for 60-90g carbs/hr."], final)])
    chat = ClaudeChat(settings, client=client)

    result = chat.run_once([], [], [], {})

    assert result == "For a 4-hour swim, aim for 60-90g carbs/hr."


def test_run_once_executes_tool_call_mid_turn_and_returns_final_text() -> None:
    settings = _settings()
    tool_use = make_tool_use_block("t1", "get_plan_summary", {"weeks": 4})
    turn_1 = make_final_message([tool_use], "tool_use")
    turn_2 = make_final_message([make_text_block("Compliance has been solid.")], "end_turn")
    client = FakeAnthropicClient([([], turn_1), (["Compliance has been solid."], turn_2)])
    chat = ClaudeChat(settings, client=client)

    calls: list[dict] = []
    handlers = {"get_plan_summary": lambda input_data: calls.append(input_data) or {"ok": True}}

    result = chat.run_once([], [], [{"name": "get_plan_summary"}], handlers)

    assert result == "Compliance has been solid."
    assert len(calls) == 1
    assert len(client.messages.calls) == 2


def test_run_once_raises_on_refusal() -> None:
    settings = _settings()
    final = make_final_message([], "refusal")
    client = FakeAnthropicClient([([], final)])
    chat = ClaudeChat(settings, client=client)

    with pytest.raises(RuntimeError):
        chat.run_once([], [], [], {})


def test_run_once_raises_on_api_error() -> None:
    import anthropic
    import httpx

    settings = _settings()

    class BrokenMessagesAPI:
        def stream(self, **kwargs):
            request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
            raise anthropic.APIConnectionError(request=request)

    class BrokenClient:
        def __init__(self):
            self.messages = BrokenMessagesAPI()

    chat = ClaudeChat(settings, client=BrokenClient())

    with pytest.raises(RuntimeError):
        chat.run_once([], [{"role": "user", "content": "hi"}], [], {})


def test_run_once_max_iterations_guard_raises() -> None:
    from app.claude import MAX_TOOL_ITERATIONS

    settings = _settings()
    tool_use = make_tool_use_block("t1", "get_plan_summary", {})
    turns = [([], make_final_message([tool_use], "tool_use")) for _ in range(MAX_TOOL_ITERATIONS)]
    client = FakeAnthropicClient(turns)
    chat = ClaudeChat(settings, client=client)

    handlers = {"get_plan_summary": lambda _input: {"ok": True}}

    with pytest.raises(RuntimeError):
        chat.run_once([], [], [{"name": "get_plan_summary"}], handlers)
