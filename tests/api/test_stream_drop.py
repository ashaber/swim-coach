"""A mid-stream transport drop (httpx.RemoteProtocolError, prod 2026-10-15) must
end the turn with a terminal `error` event instead of escaping the generator."""

from __future__ import annotations

from types import SimpleNamespace

import anthropic
import httpx
import pytest

from app.claude import ClaudeChat
from test_claude import _settings


class _DroppingStream:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def __enter__(self) -> "_DroppingStream":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def __iter__(self):
        yield SimpleNamespace(type="text", text="partial ")
        raise self._exc


class _DroppingClient:
    def __init__(self, exc: Exception) -> None:
        self.messages = self
        self._exc = exc

    def stream(self, **_kwargs):
        return _DroppingStream(self._exc)


@pytest.mark.parametrize(
    "exc",
    [
        httpx.RemoteProtocolError("peer closed connection without sending complete message body"),
        anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com")),
    ],
)
def test_midstream_transport_drop_yields_error_event(exc: Exception) -> None:
    chat = ClaudeChat(_settings(), client=_DroppingClient(exc))
    events = list(chat._run_turns([], [{"role": "user", "content": "x"}], [], {}))
    assert events[0] == {"type": "text", "text": "partial "}
    assert events[-1]["type"] == "error"
    assert "dropped" in events[-1]["error"]
    assert not any(e["type"] == "done" for e in events)
