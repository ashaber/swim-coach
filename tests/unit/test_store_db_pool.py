"""Process-level connection-pool reuse for DbStore (backend/db-connection-
pooling build).

These tests never touch a live database -- `psycopg_pool.ConnectionPool`
opens its pool lazily via background worker threads and does not raise or
block on construction even against an unreachable DSN (confirmed via a
throwaway probe script during this build: constructing against
`postgresql://nouser:nopass@127.0.0.1:1/nonexistent` returns in a few
milliseconds, with connection attempts/failures handled entirely by
background workers). That's exactly what lets these tests assert the real
pool-SHARING behavior via object identity -- not a mock standing in for it
-- without any DB fixture, matching this repo's "no LLM or network in
tests" rule for `tests/unit`.

`tests/integration/test_store_db_contract.py` (gated behind a real ephemeral
Postgres in CI's `db` job) is what proves the pooled `_connect()` still
behaves correctly end to end (commit/rollback/checkin against a real
backend); these tests are scoped to the pool-reuse mechanism itself.

**Requires the `[db]` extra (psycopg + psycopg_pool) to actually be
installed** -- unlike `test_store_db_mapping.py`'s pure row<->model mappers
or `test_store_psycopg_absent.py` (which SIMULATES absence via
`sys.modules`/`builtins.__import__` blocking, deliberately environment-
independent), these tests construct a real `DbStore(dsn=...)`, which
requires the real imports to succeed. CI's `test` job intentionally installs
ONLY `engine/[dev]` (no `[db]` extra) -- a real, standing "psycopg genuinely
absent" environment, not a stand-in for one -- to prove the engine core
keeps working without psycopg at all (see `store_db.py`'s own module
docstring). `pytest.importorskip` below makes this whole file SKIP cleanly
in that job rather than fail; CI's separate `backend`/`db` jobs (which do
install the `[db]` extra) run it for real."""

from __future__ import annotations

import pytest

pytest.importorskip("psycopg")
pytest.importorskip("psycopg_pool")

from swim_coach import store_db  # noqa: E402 - after the importorskip guard above

# Unreachable-but-syntactically-valid DSNs -- see module docstring above for
# why constructing a pool against these never blocks or raises.
_DSN_A = "postgresql://nouser:nopass@127.0.0.1:1/nonexistent-a"
_DSN_B = "postgresql://nouser:nopass@127.0.0.1:1/nonexistent-b"


@pytest.fixture(autouse=True)
def _reset_pool_registry():
    """Every test gets a clean `_POOLS` registry, and any pool it created is
    closed afterward -- without this, pools (and their background worker
    threads) from one test leak into and pollute the next."""
    store_db._POOLS.clear()
    yield
    store_db.close_all_pools()


def test_dbstore_construction_shares_one_pool_across_instances():
    # The exact scenario `store_factory.make_store()` creates on every
    # single request (see store_db.py's module docstring) -- two separate
    # `DbStore(dsn=...)` constructions for the SAME dsn must share the one
    # underlying pool, not each open their own.
    a = store_db.DbStore(dsn=_DSN_A)
    b = store_db.DbStore(dsn=_DSN_A)
    assert a._pool is b._pool


def test_dbstore_construction_uses_separate_pools_per_dsn():
    a = store_db.DbStore(dsn=_DSN_A)
    b = store_db.DbStore(dsn=_DSN_B)
    assert a._pool is not b._pool


def test_pool_is_registered_in_module_level_pools_dict():
    store = store_db.DbStore(dsn=_DSN_A)
    assert store_db._POOLS[_DSN_A] is store._pool
    assert list(store_db._POOLS.keys()) == [_DSN_A]


def test_pool_connect_kwargs_disable_prepared_statements_and_set_dict_row():
    """`prepare_threshold=None` must apply to every connection the pool ever
    hands out (required against Supabase's transaction-mode pooler -- see
    `_connect`'s docstring) -- applied via the pool's own `kwargs` at
    pool-CREATION time, not per-checkout, so asserting it on the pool object
    itself (not a checked-out connection) is the correct place to catch a
    regression here."""
    store = store_db.DbStore(dsn=_DSN_A)
    assert store._pool.kwargs["prepare_threshold"] is None
    assert store._pool.kwargs["row_factory"] is store._dict_row


def test_close_all_pools_clears_registry_and_a_later_construction_gets_a_fresh_pool():
    first = store_db.DbStore(dsn=_DSN_A)
    first_pool = first._pool

    store_db.close_all_pools()
    assert store_db._POOLS == {}

    second = store_db.DbStore(dsn=_DSN_A)
    assert second._pool is not first_pool


def test_close_all_pools_is_a_safe_noop_when_nothing_was_ever_constructed():
    store_db.close_all_pools()  # must not raise
    assert store_db._POOLS == {}


def test_pool_size_defaults_are_small_and_reasoned():
    """Not pinning a specific number (that's the operational-choice part,
    documented as `Coach judgment:` in `_DEFAULT_POOL_MIN_SIZE`/`_MAX_SIZE`'s
    own comment, not a contract) -- this just guards against psycopg_pool's
    own library default (`min_size=4`) silently coming back if the explicit
    `min_size=`/`max_size=` kwargs are ever dropped from `_get_pool`, for
    this low-traffic, single/few-athlete app."""
    store = store_db.DbStore(dsn=_DSN_A)
    assert 1 <= store._pool.min_size <= 2
    assert store._pool.max_size <= 10


def test_pool_size_honors_env_var_overrides(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SWIM_COACH_DB_POOL_MIN_SIZE", "2")
    monkeypatch.setenv("SWIM_COACH_DB_POOL_MAX_SIZE", "7")
    store = store_db.DbStore(dsn=_DSN_A)
    assert store._pool.min_size == 2
    assert store._pool.max_size == 7


def test_pool_size_env_override_ignores_garbage_and_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("SWIM_COACH_DB_POOL_MIN_SIZE", "not-a-number")
    store = store_db.DbStore(dsn=_DSN_A)
    assert store._pool.min_size == store_db._DEFAULT_POOL_MIN_SIZE


def test_dbstore_still_requires_non_empty_dsn():
    with pytest.raises(ValueError):
        store_db.DbStore(dsn="")
