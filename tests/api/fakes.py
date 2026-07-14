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

import uuid
from datetime import date
from types import SimpleNamespace
from typing import Any

from swim_coach.models import Event, Feedback, Workout

TEST_API_TOKEN = "test-token-please-ignore"  # noqa: S105 - test fixture, not a real secret
TEST_GOOGLE_CLIENT_ID = "test-client-id.apps.googleusercontent.com"


def auth_headers(token: str = TEST_API_TOKEN) -> dict[str, str]:
    """Bearer header for the legacy shared API_TOKEN (a SERVICE principal --
    unchanged behavior, may pass any ?athlete=)."""
    return {"Authorization": f"Bearer {token}"}


def make_workout(**overrides: Any) -> Workout:
    """A completed-workout fixture, `swim_pool` by default. Used by
    test_context.py to prove the per-request context surfaces each logged
    session's exact `sport` (the production bug this build fixes: the coach
    calling a logged `swim_ow` session a "pool" session because it could
    only see an aggregate rollup, never the workout itself)."""
    data: dict[str, Any] = dict(
        id=uuid.uuid4(),
        athlete_id=uuid.uuid4(),
        date=date(2026, 7, 1),
        sport="swim_pool",
        source="manual",
        distance_m=3000,
        duration_min=60.0,
        rpe=6,
        avg_pace_s_per_100m=98.0,
    )
    data.update(overrides)
    return Workout(**data)


def make_event(**overrides: Any) -> Event:
    """A target-event fixture. Used by test_context.py to prove the
    per-request context surfaces race dates (`event_date`/`days_until`),
    fixing the coach not knowing when the athlete's races are."""
    data: dict[str, Any] = dict(
        id=uuid.uuid4(),
        athlete_id=uuid.uuid4(),
        name="Test Ultra Swim",
        event_date=date(2026, 9, 1),
        distance_m=10000,
        water_temp_c=20.0,
        wetsuit=False,
        priority="A",
        event_format="single_day",
    )
    data.update(overrides)
    return Event(**data)


class SpyFeedbackStore:
    """Wraps a real StoreInterface, delegating every call to it (so real
    engine tests -- propose_adaptation/get_plan_summary -- work unchanged)
    but also recording every `save_feedback` call in `.saved`, so
    test_tools.py can assert what `_handle_log_open_question` persisted
    without depending on jsonl-file mechanics."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.saved: list[Feedback] = []

    def save_feedback(self, entry: Feedback) -> None:
        self.saved.append(entry)
        self._inner.save_feedback(entry)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def make_text_block(text: str) -> SimpleNamespace:
    # Mirrors the real SDK TextBlock: model_dump() carries SDK-only fields
    # (parsed_output, citations) that are None in ordinary chat. exclude_none
    # must drop them, or replaying the block back to the API 400s
    # ("text.parsed_output: Extra inputs are not permitted") -- see D1.
    def _dump(exclude_none: bool = False) -> dict[str, Any]:
        d = {"type": "text", "text": text, "citations": None, "parsed_output": None}
        return {k: v for k, v in d.items() if not (exclude_none and v is None)}

    return SimpleNamespace(type="text", text=text, model_dump=_dump)


def make_tool_use_block(block_id: str, name: str, tool_input: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        type="tool_use",
        id=block_id,
        name=name,
        input=tool_input,
        model_dump=lambda exclude_none=False: {
            "type": "tool_use",
            "id": block_id,
            "name": name,
            "input": tool_input,
        },
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


def fake_google_verify(raw_token: str) -> dict:
    """Stand-in for app.google_auth's real verify (which makes an HTTPS call
    to Google's JWKS -- forbidden in tests). Convention: a raw_token shaped
    `valid:<email>` verifies to that email's claims; ANYTHING else raises
    ValueError, exactly as google-auth's verify_oauth2_token does for a
    tampered/wrong-audience/expired/wrong-issuer token. Tests inject this via
    `app.dependency_overrides[get_google_verifier] = lambda: fake_google_verify`.
    """
    if not raw_token.startswith("valid:"):
        raise ValueError("fake verifier: token did not verify")
    email = raw_token[len("valid:") :]
    return {"email": email, "email_verified": True, "sub": "fake-google-sub"}


def google_token_for(email: str) -> str:
    """The id_token string the fake verifier above accepts for `email`."""
    return f"valid:{email}"
