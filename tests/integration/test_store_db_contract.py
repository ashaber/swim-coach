"""The shared StoreInterface contract suite, run against a REAL DbStore.

GATED: skipped entirely unless `SWIM_COACH_TEST_DB_URL` points at a throwaway
Postgres/Supabase schema you don't mind having wiped between tests. This is
where the real row<->model round-trip through psycopg is verified. It is NOT
part of the default `pytest tests/unit -v` run (different directory) and, even
if collected, skips cleanly (never errors) when the env var is absent.

To run:
    export SWIM_COACH_TEST_DB_URL=postgresql://user:pw@host:5432/testdb
    # apply the schema once:
    psql "$SWIM_COACH_TEST_DB_URL" -f supabase/migrations/0001_init.sql
    pytest tests/integration -v

Each test starts from an empty set of tables (the `store` fixture truncates
every table before yielding), so tests are order-independent and isolated.
"""

from __future__ import annotations

import os
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from store_contract import StoreContractTests  # noqa: E402

TEST_DB_URL = os.environ.get("SWIM_COACH_TEST_DB_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DB_URL,
    reason="set SWIM_COACH_TEST_DB_URL to a throwaway Postgres schema to run DB contract tests",
)

_TABLES = [
    "chat_messages",
    "api_tokens",
    "uploaded_files",
    "sessions",
    "coach_texts",
    "wellness_checkins",
    "workouts",
    "week_plans",
    "macro_plans",
    "events",
    "athletes",
]


class TestDbStoreContract(StoreContractTests):
    @pytest.fixture
    def store(self):
        from swim_coach.store_db import DbStore

        s = DbStore(dsn=TEST_DB_URL)
        # Start empty: truncate every table (CASCADE handles FKs).
        with s._connect() as conn, conn.cursor() as cur:
            cur.execute(f"truncate {', '.join(_TABLES)} cascade")
        return s
