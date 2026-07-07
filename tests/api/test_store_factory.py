"""make_store factory + STORE_BACKEND/DATABASE_URL config.

No network: the `db` path is only exercised up to the point of DSN validation
(DbStore is not constructed against a real DB here -- that's tests/integration).
The default-`file` path and the fail-fast behavior are the load-bearing
guarantees that keep the live backend dormant on FileStore.
"""

from __future__ import annotations

import pytest
from swim_coach.store import FileStore

from app.config import ConfigError, Settings
from app.store_factory import make_store


def _base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("API_TOKEN", "tok")
    monkeypatch.delenv("STORE_BACKEND", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)


def test_default_backend_is_file(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    settings = Settings.from_env()
    assert settings.store_backend == "file"
    assert settings.database_url is None
    assert isinstance(make_store(settings), FileStore)


def test_make_store_file_uses_athletes_dir(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("ATHLETES_DIR", str(tmp_path))
    store = make_store(Settings.from_env())
    assert isinstance(store, FileStore)
    assert store.base_dir == tmp_path


def test_db_backend_without_database_url_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("STORE_BACKEND", "db")
    with pytest.raises(ConfigError, match="DATABASE_URL"):
        Settings.from_env()


def test_invalid_store_backend_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("STORE_BACKEND", "sqlite")
    with pytest.raises(ConfigError, match="STORE_BACKEND"):
        Settings.from_env()


def test_db_backend_with_database_url_selects_dbstore(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("STORE_BACKEND", "db")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@host:6543/postgres")
    settings = Settings.from_env()
    assert settings.store_backend == "db"
    # make_store returns a DbStore instance without opening a connection
    # (psycopg connects lazily per-operation, not in __init__). If psycopg
    # isn't installed in this env, constructing DbStore raises ImportError --
    # skip rather than fail, since the factory wiring is what's under test.
    from swim_coach.store_db import DbStore

    try:
        store = make_store(settings)
    except ImportError:
        pytest.skip("psycopg not installed in this environment")
    assert isinstance(store, DbStore)
