"""PROMPT_CACHE_TTL: 5m (default, unchanged) or 1h. The big stable block (tools + persona + index
+ reference list, ~170k tokens) is what a 5-minute cache loses whenever the athlete pauses >5 min
between turns; 1h keeps it warm across a planning session. Longer-TTL entries must come BEFORE
shorter ones, so only system block A takes 1h; block B, history and the loop marker stay 5m."""

from __future__ import annotations

import dataclasses

import pytest

from app.config import ConfigError, Settings
from app.context import build_system, build_system_blocks
from fakes import auth_headers, make_final_message, make_text_block

FIVE = {"type": "ephemeral"}
ONE_HOUR = {"type": "ephemeral", "ttl": "1h"}


def test_default_is_byte_identical_to_before(library_dir) -> None:
    assert build_system_blocks(library_dir)[0]["cache_control"] == FIVE
    assert build_system(library_dir, "hi")[0]["cache_control"] == FIVE


def test_one_hour_applies_to_block_a_only(library_dir) -> None:
    system = build_system(library_dir, "how should I fuel?", cache_ttl="1h")
    assert system[0]["cache_control"] == ONE_HOUR   # the long-lived entry comes first
    assert system[1]["cache_control"] == FIVE       # message-routed block stays short


def test_block_text_is_unchanged_by_the_ttl(library_dir) -> None:
    a = build_system(library_dir, "hi")[0]["text"]
    b = build_system(library_dir, "hi", cache_ttl="1h")[0]["text"]
    assert a == b  # the TTL is a billing hint, never a prompt change


def test_setting_defaults_to_5m_and_reads_the_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("API_TOKEN", "t")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id.apps.googleusercontent.com")
    monkeypatch.delenv("PROMPT_CACHE_TTL", raising=False)
    assert Settings.from_env().prompt_cache_ttl == "5m"
    monkeypatch.setenv("PROMPT_CACHE_TTL", "1h")
    assert Settings.from_env().prompt_cache_ttl == "1h"


def test_an_invalid_ttl_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("API_TOKEN", "t")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id.apps.googleusercontent.com")
    monkeypatch.setenv("PROMPT_CACHE_TTL", "2h")
    with pytest.raises(ConfigError, match="PROMPT_CACHE_TTL"):
        Settings.from_env()


def test_the_chat_route_sends_the_configured_ttl(app, client, fake_claude_chat_factory) -> None:
    app.state.settings = dataclasses.replace(app.state.settings, prompt_cache_ttl="1h")
    chat = fake_claude_chat_factory([(["ok"], make_final_message([make_text_block("ok")], "end_turn"))])
    r = client.post("/api/chat", json={"message": "how should I fuel a 4 hour ride?", "history": [],
                                       "athlete": "renee", "expert_mode": False}, headers=auth_headers())
    assert r.status_code == 200
    assert chat.client.messages.calls[0]["system"][0]["cache_control"] == ONE_HOUR
