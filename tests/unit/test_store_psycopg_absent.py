"""Prove the engine core imports and runs WITHOUT psycopg installed.

The design contract (task brief item 3): `import swim_coach.store` (FileStore)
and the CLI must work with psycopg NOT installed. psycopg is only needed to
*construct* a DbStore. These tests simulate psycopg's absence by blocking its
import via sys.modules, then assert:

  - swim_coach.store / swim_coach.cli / swim_coach.store_db all import fine
  - the pure mapping functions work
  - constructing DbStore raises a clear ImportError pointing at the [db] extra
"""

from __future__ import annotations

import builtins
import importlib
import sys
import uuid

import pytest


def test_store_and_cli_import_without_psycopg():
    # store.py and cli.py must never import psycopg at module load.
    store = importlib.import_module("swim_coach.store")
    cli = importlib.import_module("swim_coach.cli")
    assert hasattr(store, "FileStore")
    assert hasattr(cli, "main")


def test_store_db_module_imports_and_maps_without_psycopg(monkeypatch):
    """store_db imports (lazy psycopg) and its pure mappers work even when
    psycopg cannot be imported at all."""
    _block_psycopg(monkeypatch)
    store_db = importlib.reload(importlib.import_module("swim_coach.store_db"))
    from swim_coach.models import Athlete

    a = Athlete(id=uuid.uuid4(), slug="renee", name="R")
    row = store_db.athlete_to_row(a)
    assert store_db.row_to_athlete(row) == a


def test_constructing_dbstore_without_psycopg_raises_helpful_error(monkeypatch):
    _block_psycopg(monkeypatch)
    store_db = importlib.reload(importlib.import_module("swim_coach.store_db"))
    with pytest.raises(ImportError, match=r"\[db\]|psycopg"):
        store_db.DbStore(dsn="postgresql://unused")


def test_constructing_dbstore_without_psycopg_pool_raises_helpful_error(monkeypatch):
    """`psycopg_pool` (backend/db-connection-pooling build) is imported
    lazily alongside psycopg itself, same discipline, same [db] extra --
    its absence (psycopg present, psycopg_pool missing) must raise the same
    kind of clear, actionable ImportError, not an opaque `ModuleNotFoundError`
    surfacing from deep inside `__init__`."""
    _block_psycopg_pool(monkeypatch)
    store_db = importlib.reload(importlib.import_module("swim_coach.store_db"))
    with pytest.raises(ImportError, match=r"\[db\]|psycopg"):
        store_db.DbStore(dsn="postgresql://unused")


def _block_psycopg(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make `import psycopg` (and submodules) fail, as if not installed."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "psycopg" or name.startswith("psycopg."):
            raise ImportError(f"blocked for test: {name}")
        return real_import(name, *args, **kwargs)

    for mod in list(sys.modules):
        if mod == "psycopg" or mod.startswith("psycopg."):
            monkeypatch.delitem(sys.modules, mod, raising=False)
    monkeypatch.setattr(builtins, "__import__", fake_import)


def _block_psycopg_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make `import psycopg_pool` (and submodules) fail, as if not
    installed -- psycopg itself stays importable."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "psycopg_pool" or name.startswith("psycopg_pool."):
            raise ImportError(f"blocked for test: {name}")
        return real_import(name, *args, **kwargs)

    for mod in list(sys.modules):
        if mod == "psycopg_pool" or mod.startswith("psycopg_pool."):
            monkeypatch.delitem(sys.modules, mod, raising=False)
    monkeypatch.setattr(builtins, "__import__", fake_import)
