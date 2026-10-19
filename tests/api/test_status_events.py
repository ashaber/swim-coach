"""Status events while the model writes tool input (prod 2026-10-18: 4.5 min of silence)."""

from __future__ import annotations

from types import SimpleNamespace

import app.claude as claude_module
from app.claude import ClaudeChat
from fakes import FakeAnthropicClient, make_final_message, make_text_block, make_tool_use_block
from test_claude import _settings


def _start(name: str):
    return SimpleNamespace(type="content_block_start", content_block=SimpleNamespace(type="tool_use", name=name))


def _json():
    return SimpleNamespace(type="input_json", partial_json='{"a"', snapshot={})


def test_tool_use_start_emits_friendly_status(monkeypatch) -> None:
    monkeypatch.setattr(claude_module, "_monotonic", lambda: 0.0)
    final = make_final_message([make_text_block("ok")], "end_turn")
    chat = ClaudeChat(_settings(), client=FakeAnthropicClient([([_start("author_week_plan"), "hi"], final)]))
    events = list(chat._run_turns([], [{"role": "user", "content": "x"}], [], {}))
    assert events[0] == {"type": "status", "text": "Writing your week plan…"}
    assert {"type": "text", "text": "hi"} in events


def _first_status(monkeypatch, tool: str) -> str:
    monkeypatch.setattr(claude_module, "_monotonic", lambda: 0.0)
    final = make_final_message([make_text_block("ok")], "end_turn")
    chat = ClaudeChat(_settings(), client=FakeAnthropicClient([([_start(tool)], final)]))
    events = list(chat._run_turns([], [{"role": "user", "content": "x"}], [], {}))
    return events[0]["text"]


def test_unknown_tool_gets_default_label(monkeypatch) -> None:
    assert _first_status(monkeypatch, "get_week_plan") == "Working…"


def test_patch_label(monkeypatch) -> None:
    assert _first_status(monkeypatch, "patch_week_plan") == "Updating your plan…"


class _TimedStream:
    """Stream whose events arrive at fake-clock times."""

    def __init__(self, now: list[float], times: list[float], final) -> None:
        self._now, self._times, self._final = now, times, final

    def __enter__(self) -> "_TimedStream":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def __iter__(self):
        self._now[0] = 0.0
        yield _start("author_week_plan")
        for t in self._times:
            self._now[0] = t
            yield _json()

    def get_final_message(self):
        return self._final


class _TimedClient:
    def __init__(self, stream: _TimedStream) -> None:
        self.messages = self
        self._stream = stream

    def stream(self, **_kwargs):
        return self._stream


def test_input_json_heartbeat_is_throttled_to_ten_seconds(monkeypatch) -> None:
    now = [0.0]
    monkeypatch.setattr(claude_module, "_monotonic", lambda: now[0])
    final = make_final_message([make_text_block("ok")], "end_turn")
    stream = _TimedStream(now, [1, 4, 9, 11, 15, 21.5, 22], final)
    chat = ClaudeChat(_settings(), client=_TimedClient(stream))
    events = list(chat._run_turns([], [{"role": "user", "content": "x"}], [], {}))
    statuses = [e["text"] for e in events if e["type"] == "status"]
    assert statuses == ["Writing your week plan…", "Writing your week plan… (11s)", "Writing your week plan… (21s)"]


def test_status_event_is_sse_framed_and_ignored_by_run_once(monkeypatch) -> None:
    monkeypatch.setattr(claude_module, "_monotonic", lambda: 0.0)
    final = make_final_message([make_text_block("answer")], "end_turn")
    chat = ClaudeChat(_settings(), client=FakeAnthropicClient([([_start("author_week_plan"), "answer"], final)]))
    lines = list(chat.run_streaming([], [{"role": "user", "content": "x"}], [], {}))
    assert 'data: {"type": "status"' in lines[0]
    chat2 = ClaudeChat(_settings(), client=FakeAnthropicClient([([_start("author_week_plan"), "answer"], final)]))
    assert chat2.run_once([], [{"role": "user", "content": "x"}], [], {}) == "answer"


def test_tool_loop_still_runs_after_status(monkeypatch) -> None:
    monkeypatch.setattr(claude_module, "_monotonic", lambda: 0.0)
    block = make_tool_use_block("t1", "echo", {"v": 1})
    turn1 = ([_start("echo")], make_final_message([block], "tool_use"))
    turn2 = (["done"], make_final_message([make_text_block("done")], "end_turn"))
    chat = ClaudeChat(_settings(), client=FakeAnthropicClient([turn1, turn2]))
    events = list(chat._run_turns([], [{"role": "user", "content": "x"}], [], {"echo": lambda i: {"ok": True}}))
    types = [e["type"] for e in events]
    assert types[0] == "status" and "done" in types
