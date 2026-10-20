"""Every cache_control on the coach path carries the configured TTL, TTLs never increase along
the prompt (tools -> system -> messages), and the sonnet-5-5 thinking guard."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.claude import build_request_kwargs, with_loop_breakpoint
from app.config import ConfigError, Settings
from app.context import build_context_block, build_messages, build_system
from swim_coach.store import FileStore


def _breakpoints(kwargs: dict[str, Any]) -> list[tuple[str, dict[str, str]]]:
    found: list[tuple[str, dict[str, str]]] = []
    for i, b in enumerate(kwargs["system"]):
        if "cache_control" in b:
            found.append((f"system[{i}]", b["cache_control"]))
    for mi, m in enumerate(kwargs["messages"]):
        if isinstance(m["content"], list):
            for b in m["content"]:
                if "cache_control" in b:
                    found.append((f"messages[{mi}]", b["cache_control"]))
    return found


def _ttl_seconds(cc: dict[str, str]) -> int:
    return 3600 if cc.get("ttl") == "1h" else 300


def _cc(ttl: str) -> dict[str, str]:
    return {"type": "ephemeral"} if ttl == "5m" else {"type": "ephemeral", "ttl": ttl}


def _request(app_env: Path, library_dir: Path, *, a_ttl: str, ctx_ttl: str, in_message: bool) -> dict[str, Any]:
    store = FileStore(base_dir=app_env)
    context_block = build_context_block(store, "renee", expert_mode=False, cache_ttl=ctx_ttl)
    system = build_system(
        library_dir,
        "how should I fuel a long swim?",
        include_routed=not in_message,
        cache_ttl=a_ttl,
        context_block=context_block,
        context_cache_ttl=ctx_ttl,
    )
    history = [
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
    ]
    messages = build_messages(
        message="q2", history=history, library_text="lib" if in_message else None, cache_ttl=ctx_ttl
    )
    settings = _settings()
    return build_request_kwargs(
        settings, system, with_loop_breakpoint(system, messages, None, cache_ttl=ctx_ttl), None
    )


def _settings() -> Settings:
    return SimpleNamespace(  # type: ignore[return-value]
        claude_model="claude-sonnet-5-5", claude_max_tokens=1000, claude_thinking="adaptive"
    )


@pytest.mark.parametrize("in_message", [False, True])
@pytest.mark.parametrize("a_ttl,ctx_ttl", [("1h", "1h"), ("1h", "5m"), ("5m", "5m")])
def test_every_breakpoint_uses_configured_ttl_and_ttls_never_increase(
    app_env: Path, library_dir: Path, a_ttl: str, ctx_ttl: str, in_message: bool
) -> None:
    kwargs = _request(app_env, library_dir, a_ttl=a_ttl, ctx_ttl=ctx_ttl, in_message=in_message)
    bps = _breakpoints(kwargs)
    assert len(bps) >= 3
    assert bps[0] == ("system[0]", _cc(a_ttl))
    assert all(cc == _cc(ctx_ttl) for _, cc in bps[1:])
    secs = [_ttl_seconds(cc) for _, cc in bps]
    assert secs == sorted(secs, reverse=True)


def test_with_loop_breakpoint_uses_ttl_when_below_cap() -> None:
    out = with_loop_breakpoint([], [{"role": "user", "content": "hi"}], None, cache_ttl="1h")
    assert out[-1]["content"][-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def _env(monkeypatch: pytest.MonkeyPatch, **extra: str) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("API_TOKEN", "some-token")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "x.apps.googleusercontent.com")
    for k in ("CLAUDE_MODEL", "CLAUDE_THINKING", "PROMPT_CACHE_TTL", "PROMPT_CACHE_TTL_CONTEXT"):
        monkeypatch.delenv(k, raising=False)
    for k, v in extra.items():
        monkeypatch.setenv(k, v)


def test_config_rejects_block_a_ttl_shorter_than_context_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, PROMPT_CACHE_TTL="5m", PROMPT_CACHE_TTL_CONTEXT="1h")
    with pytest.raises(ConfigError, match="PROMPT_CACHE_TTL"):
        Settings.from_env()


def test_config_accepts_longer_block_a_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, PROMPT_CACHE_TTL="1h", PROMPT_CACHE_TTL_CONTEXT="5m")
    assert Settings.from_env().prompt_cache_ttl_context == "5m"


def test_config_rejects_disabled_thinking_on_sonnet_5_5(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, CLAUDE_MODEL="claude-sonnet-5-5", CLAUDE_THINKING="disabled")
    with pytest.raises(ConfigError, match="disabled"):
        Settings.from_env()


def test_config_allows_disabled_thinking_on_sonnet_5(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, CLAUDE_MODEL="claude-sonnet-5", CLAUDE_THINKING="disabled")
    assert Settings.from_env().claude_thinking == "disabled"


def test_default_model_is_sonnet_5_5_with_adaptive_thinking(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch)
    s = Settings.from_env()
    assert s.claude_model == "claude-sonnet-5-5" and s.claude_thinking == "adaptive"
