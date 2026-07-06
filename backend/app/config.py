"""Environment-var configuration. Fails fast if required vars are missing.

Per Andrew's global standard: "All configuration via environment variables
-- no hardcoded values in source" and "Fail fast on startup if required env
vars are missing." `.env.example` at the repo root documents every var
below.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

try:
    # Convenience for local dev (`uvicorn app.main:app` from backend/ with a
    # .env file present). A no-op in production/Cloud Run, where env vars
    # are injected directly and no .env file exists.
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - python-dotenv is a listed dependency
    pass

_REQUIRED_VARS = ("ANTHROPIC_API_KEY", "API_TOKEN")
_VALID_THINKING_MODES = ("adaptive", "disabled")


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid at startup."""


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Settings:
    """Immutable, validated configuration for one running instance.

    Built once via `Settings.from_env()` at app startup (see `main.create_app`)
    and stashed on `app.state.settings` -- never re-read from `os.environ`
    mid-request, so a single request's view of config can't tear.
    """

    anthropic_api_key: str
    api_token_hash: str
    claude_model: str
    claude_thinking: str  # "adaptive" | "disabled"
    allowed_origins: list[str]
    athletes_dir: Path
    library_dir: Path
    research_dir: Path
    port: int
    chat_rate_per_min: int

    @classmethod
    def from_env(cls) -> "Settings":
        missing = [name for name in _REQUIRED_VARS if not os.environ.get(name)]
        if missing:
            raise ConfigError(
                f"missing required environment variable(s): {', '.join(missing)} "
                "-- see .env.example"
            )

        claude_thinking = os.environ.get("CLAUDE_THINKING", "adaptive")
        if claude_thinking not in _VALID_THINKING_MODES:
            raise ConfigError(
                f"CLAUDE_THINKING must be one of {_VALID_THINKING_MODES}, got {claude_thinking!r}"
            )

        athletes_dir = Path(os.environ.get("ATHLETES_DIR", "../athletes"))
        # research/open-questions.jsonl (IDEA 005) lives alongside
        # athletes/ and library/ rather than under either -- derived from
        # ATHLETES_DIR's parent instead of its own env var so there's one
        # fewer knob to configure/document. See context.py's
        # `log_open_question` tool handler.
        research_dir = athletes_dir.parent / "research"

        allowed_origins_raw = os.environ.get("ALLOWED_ORIGINS", "https://ashaber.github.io")
        allowed_origins = [o.strip() for o in allowed_origins_raw.split(",") if o.strip()]

        return cls(
            anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
            api_token_hash=_sha256_hex(os.environ["API_TOKEN"]),
            claude_model=os.environ.get("CLAUDE_MODEL", "claude-opus-4-8"),
            claude_thinking=claude_thinking,
            allowed_origins=allowed_origins,
            athletes_dir=athletes_dir,
            library_dir=Path(os.environ.get("LIBRARY_DIR", "../library")),
            research_dir=research_dir,
            port=int(os.environ.get("PORT", "8000")),
            chat_rate_per_min=int(os.environ.get("CHAT_RATE_PER_MIN", "20")),
        )

    def token_matches(self, provided_token: str) -> bool:
        """Constant-time comparison against the configured API_TOKEN, by
        comparing sha256 hex digests (never the raw token) -- see auth.py."""
        import hmac

        return hmac.compare_digest(_sha256_hex(provided_token), self.api_token_hash)
