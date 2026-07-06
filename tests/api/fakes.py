"""Test doubles for the Anthropic client + small auth helpers, shared by
`tests/api`'s test modules and `conftest.py`.

Deliberately not named `conftest.py` and not re-exported through it: pytest
runs `tests/unit` and `tests/api` side by side without package `__init__.py`
files in either, so two same-named top-level modules (e.g. two
`conftest.py`s, or two `test_plan.py`s) collide in `sys.modules` the moment
either is imported by name rather than discovered by pytest itself. Fixture
*discovery* is fine (pytest loads each `conftest.py` by path, not by a
colliding module name) but a plain `from conftest import ...` in a test
module is a real Python import and hits the collision -- hence a uniquely
named module for anything test files import directly.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

TEST_API_TOKEN = "test-token-please-ignore"  # noqa: S105 - test fixture, not a real secret


def auth_headers(token: str = TEST_API_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def make_text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text, model_dump=lambda: {"type": "text", "text": text})


def make_tool_use_block(block_id: str, name: str, tool_input: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        type="tool_use",
        id=block_id,
        name=name,
        input=tool_input,
        model_dump=lambda: {"type": "tool_use", "id": block_id, "name": name, "input": tool_input},
    )


def make_usage(
    input_tokens: int = 100,
    output_tokens: int = 20,
    cache_read_input_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read_input_tokens,
        cache_creation_input_tokens=cache_creation_input_tokens,
    )


def make_final_message(content: list[Any], stop_reason: str, usage: SimpleNamespace | None = None):
    return SimpleNamespace(content=content, stop_reason=stop_reason, usage=usage or make_usage())


class FakeStreamContext:
    """Mimics `anthropic.MessageStream`: a context manager exposing
    `.text_stream` (an iterator of text deltas) and `.get_final_message()`."""

    def __init__(self, chunks: list[str], final_message: Any) -> None:
        self._chunks = chunks
        self._final_message = final_message

    def __enter__(self) -> "FakeStreamContext":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    @property
    def text_stream(self):
        yield from self._chunks

    def get_final_message(self) -> Any:
        return self._final_message


class FakeMessagesAPI:
    """Fake of `client.messages`: `.stream(**kwargs)` pops the next
    preconfigured `(chunks, final_message)` pair and records every call's
    kwargs in `.calls` for request-shape assertions."""

    def __init__(self, turns: list[tuple[list[str], Any]]) -> None:
        self._turns = list(turns)
        self.calls: list[dict[str, Any]] = []

    def stream(self, **kwargs: Any) -> FakeStreamContext:
        self.calls.append(kwargs)
        if not self._turns:
            raise AssertionError("FakeMessagesAPI.stream called more times than turns configured")
        chunks, final_message = self._turns.pop(0)
        return FakeStreamContext(chunks, final_message)


class FakeAnthropicClient:
    def __init__(self, turns: list[tuple[list[str], Any]]) -> None:
        self.messages = FakeMessagesAPI(turns)
