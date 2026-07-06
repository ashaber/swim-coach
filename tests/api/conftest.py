"""Shared fixtures for the backend API test suite.

Per Andrew's global standard: requests-based harness (see `test_*` files
using `TestClient`, which is `requests`-compatible in interface), unique
per-run `run_tag` UUIDs to isolate any created data, exit-code discipline
(pytest's own). No real Anthropic API calls are ever made -- every test
either injects a fake `ClaudeChat`/client, or exercises code (context
assembly, config, tools against the engine) that never touches the network.

`ATHLETES_DIR` is pointed at a `tmp_path` copy of the real `athletes/renee`
tree (not the repo's own copy) so tests never mutate real athlete data --
this also means propose_adaptation/get_plan_summary exercise the *real*
engine (`swim_coach.adapt`/`swim_coach.load`) against realistic data rather
than a synthetic fixture, while remaining fully isolated per test run.
`LIBRARY_DIR` points at the real repo `library/` directly since it's
read-only content nothing here ever writes to.
"""

from __future__ import annotations

import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest

from fakes import FakeAnthropicClient, TEST_API_TOKEN

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# `app.main` builds a module-level `app = create_app()` at import time (so
# `uvicorn app.main:app` has an ASGI callable to serve) -- Settings.from_env()
# fails fast if ANTHROPIC_API_KEY/API_TOKEN are unset, which would otherwise
# blow up test *collection* itself (pytest imports test modules, and this
# conftest, before any per-test fixture/monkeypatch runs). These placeholder
# values only need to exist long enough for that first import to succeed;
# every test that cares about specific config values sets them explicitly
# via the `app_env` fixture below and builds its own `create_app()`.
import os  # noqa: E402

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-import-placeholder-not-real")
os.environ.setdefault("API_TOKEN", "import-placeholder-token-not-real")


@pytest.fixture
def run_tag() -> str:
    """A per-test-run UUID tag, per Andrew's testing standard. Used to mark
    any data this test run creates (e.g. logged open-questions) so it's
    traceable even though `athletes_dir`'s `tmp_path` root is the actual
    isolation/cleanup mechanism (pytest deletes it automatically)."""
    return uuid.uuid4().hex[:8]


@pytest.fixture
def athletes_dir(tmp_path: Path) -> Path:
    dest = tmp_path / "athletes"
    shutil.copytree(REPO_ROOT / "athletes", dest)
    return dest


@pytest.fixture
def library_dir() -> Path:
    return REPO_ROOT / "library"


@pytest.fixture
def app_env(monkeypatch: pytest.MonkeyPatch, athletes_dir: Path, library_dir: Path) -> Path:
    """Sets every required/optional env var to a test-safe value. Returns
    `athletes_dir` for convenience (tests that need the isolated tree)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-real")
    monkeypatch.setenv("API_TOKEN", TEST_API_TOKEN)
    monkeypatch.setenv("ATHLETES_DIR", str(athletes_dir))
    monkeypatch.setenv("LIBRARY_DIR", str(library_dir))
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://ashaber.github.io,http://localhost:5173")
    monkeypatch.setenv("CHAT_RATE_PER_MIN", "3")
    monkeypatch.delenv("CLAUDE_THINKING", raising=False)
    monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    return athletes_dir


@pytest.fixture
def app(app_env: Path):
    from app.main import create_app

    return create_app()


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


@pytest.fixture
def fake_claude_chat_factory(app):
    """Returns `make(turns)` building a `ClaudeChat` wired to a
    `FakeAnthropicClient` (so no real network/API key is ever used), and
    overrides the app's `get_claude_chat` dependency to return it."""
    from app.claude import ClaudeChat
    from app.routes.chat import get_claude_chat

    def make(turns: list[tuple[list[str], Any]]) -> ClaudeChat:
        fake_client = FakeAnthropicClient(turns)
        chat = ClaudeChat(app.state.settings, client=fake_client)
        app.dependency_overrides[get_claude_chat] = lambda: chat
        return chat

    yield make
    app.dependency_overrides.pop(get_claude_chat, None)
