# supabase/ — database layer (Phase 2.5)

The Supabase/Postgres schema behind `DbStore` (`engine/swim_coach/store_db.py`).
This whole layer is **dormant** until `STORE_BACKEND=db` is set on the backend —
the live service runs on `FileStore` and is unchanged until Andrew flips the flag.

## Layout

```
supabase/
  migrations/
    20260706000000_init.sql   # initial schema: all tables, indexes, reserved stubs
  README.md         # this file
```

## Schema design (JSONB-hybrid)

Every entity is **one row**: query-relevant fields are promoted to real columns
(for indexing/filtering) and the full pydantic model (`models.py`, serialized via
`model_dump(mode="json")`) lives in a `data JSONB` column, reconstructed by
`Model.model_validate(...)`. Adding a model field usually needs **no migration** —
it rides along in `data`; a migration is only needed to make a new field a
queryable column.

Tables: `athletes`, `events`, `macro_plans`, `week_plans`, `workouts`,
`wellness_checkins`, `coach_texts`, plus reserved-and-unused stubs `sessions`,
`uploaded_files`, `api_tokens`, `chat_messages` (created so the schema is complete;
`DbStore` does not touch them in Phase 2.5). All UUID PKs; every child table has an
`athlete_id` FK `ON DELETE CASCADE`; `created_at`/`updated_at TIMESTAMPTZ DEFAULT now()`;
`schema_version INT` where the model has one.

## RLS is deferred (intentional)

Row-Level Security is **not** enabled yet. Phase 2.5 access is service-role only,
from the backend — the shared bearer token gates the API, not the DB. Real
per-athlete RLS lands with Supabase Auth in **Phase 3**, when every table gets
`ENABLE ROW LEVEL SECURITY` + policies keyed on `auth.uid() -> athlete_id`. This
is noted at the top of `20260706000000_init.sql` too.

## Running the migration

### Option A — `psql` directly (simplest)

```bash
# Against the DIRECT connection (port 5432), not the pooler, for DDL:
psql "postgresql://postgres:<pw>@<host>:5432/postgres" -f supabase/migrations/20260706000000_init.sql
```

### Option B — Supabase CLI (recommended)

Tracks which migrations have been applied (in a `supabase_migrations` table),
so the repo and the DB never silently desync as more migrations land. Prefer
this over Option A once there's more than one migration.

```bash
brew install supabase/tap/supabase   # or: npm i -g supabase
supabase login
supabase link --project-ref <REF>    # prompts for the DB password; writes supabase/config.toml (commit it)
supabase db push                     # applies supabase/migrations/* to the linked project
```

Migration files are named with the CLI's `<YYYYMMDDHHMMSS>_<name>.sql`
convention so `db push` orders and tracks them correctly. Do **not** use the
GitHub auto-deploy integration here — it runs DDL against the live DB on every
merge to `main`, which is exactly the disruption we're avoiding while Renee is
using the system; run `db push` deliberately instead.

Migrations are plain SQL and idempotent-ish (`create table if not exists` /
`create index if not exists`), so re-applying `20260706000000_init.sql` is safe.

## Connection string (`DATABASE_URL`)

`DbStore` connects to the **transaction pooler** (pgbouncer, port **6543**) for
app traffic:

```
postgresql://postgres.<project-ref>:<pw>@<region>.pooler.supabase.com:6543/postgres
```

`DbStore` sets psycopg's `prepare_threshold=None`, which **disables server-side
prepared statements** — required for pgbouncer transaction pooling (a client
connection is not pinned to one backend, so a prepared statement created on one
backend is absent on the next). Use the **direct** connection (port 5432) only for
DDL/migrations, not for the app.

## Migrating existing file data → DB

Once the schema is applied, copy the current `athletes/` tree in:

```bash
# dry run first — reports what WOULD be written, touches nothing, needs no DB:
python scripts/migrate_files_to_db.py --dry-run

# real run (idempotent; NEVER deletes files):
DATABASE_URL="postgresql://...:6543/postgres" python scripts/migrate_files_to_db.py
# or a single athlete:
python scripts/migrate_files_to_db.py --athlete renee --database-url "postgresql://..."
```

The file tree stays the source of truth / archive until the DB is validated and
the backend is cut over. See the root `README.md` "Store backend cutover" section.

## Running the DB contract tests

`tests/integration/test_store_db_contract.py` runs the same StoreInterface
contract suite as the unit tests, but against a **real** DbStore. It is skipped
unless `SWIM_COACH_TEST_DB_URL` points at a **throwaway** schema (the fixture
`TRUNCATE`s every table between tests):

```bash
export SWIM_COACH_TEST_DB_URL="postgresql://postgres:pw@localhost:5432/testdb"
psql "$SWIM_COACH_TEST_DB_URL" -f supabase/migrations/20260706000000_init.sql
pip install -e "engine/[db]"          # psycopg
pytest tests/integration -v
```

A quick local throwaway via Docker:

```bash
docker run -d --rm --name swimpg -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=testdb \
  -p 5432:5432 postgres:16-alpine
```
