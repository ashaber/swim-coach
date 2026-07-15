"""Config fail-fast behavior: missing required env vars must raise before
the app can be built, never fail silently or serve with a blank secret."""

from __future__ import annotations

import pytest

from app.config import ConfigError, Settings


def test_missing_anthropic_api_key_fails_fast(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("API_TOKEN", "some-token")
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        Settings.from_env()


def test_missing_api_token_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.delenv("API_TOKEN", raising=False)
    with pytest.raises(ConfigError, match="API_TOKEN"):
        Settings.from_env()


def test_missing_google_client_id_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("API_TOKEN", "some-token")
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    with pytest.raises(ConfigError, match="GOOGLE_CLIENT_ID"):
        Settings.from_env()


def test_invalid_claude_thinking_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("API_TOKEN", "some-token")
    monkeypatch.setenv("CLAUDE_THINKING", "turbo")
    with pytest.raises(ConfigError, match="CLAUDE_THINKING"):
        Settings.from_env()


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("API_TOKEN", "some-token")
    monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    monkeypatch.delenv("CLAUDE_THINKING", raising=False)
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("CHAT_RATE_PER_MIN", raising=False)

    settings = Settings.from_env()

    assert settings.claude_model == "claude-sonnet-5"
    assert settings.claude_thinking == "adaptive"
    assert settings.allowed_origins == ["https://ashaber.github.io"]
    assert settings.port == 8000
    assert settings.chat_rate_per_min == 20
    # research_dir is derived from athletes_dir's parent, not its own env var.
    assert settings.research_dir == settings.athletes_dir.parent / "research"


def test_token_matches_is_hash_based_and_correct(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("API_TOKEN", "correct-token")
    settings = Settings.from_env()

    assert settings.token_matches("correct-token") is True
    assert settings.token_matches("wrong-token") is False
    # the raw token is never stored -- only its sha256 hex digest.
    assert settings.api_token_hash != "correct-token"
    assert len(settings.api_token_hash) == 64


def test_secret_env_vars_are_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    # Secret managers / printf|echo pipelines often leave a trailing newline;
    # a stray newline in the key breaks the x-api-key header, in DATABASE_URL
    # breaks psycopg's URI parse, in API_TOKEN changes its hash. from_env must
    # strip all three.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test\n")
    monkeypatch.setenv("API_TOKEN", "  correct-token\n")
    monkeypatch.setenv("STORE_BACKEND", "db")
    monkeypatch.setenv("DATABASE_URL", "\npostgresql://u:p@h:6543/db\n")
    settings = Settings.from_env()

    assert settings.anthropic_api_key == "sk-ant-test"
    assert settings.database_url == "postgresql://u:p@h:6543/db"
    # the stripped token hashes to the stripped value, so a clean token matches
    assert settings.token_matches("correct-token") is True
