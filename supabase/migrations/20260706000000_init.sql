-- swim-coach Phase 2.5 -- initial schema.
--
-- JSONB-hybrid design: every entity is one row. Query-relevant fields are
-- promoted to real columns (for indexing/filtering); the full pydantic model
-- (models.py, serialized via model_dump(mode="json")) lives in a `data JSONB`
-- column and is the source of truth reconstructed by Model.model_validate(...).
-- Adding a model field therefore usually needs NO migration -- it rides along
-- in `data`; a migration is only needed when a new field must become a
-- queryable column.
--
-- All ids are UUID. Every child table carries athlete_id (FK -> athletes) with
-- ON DELETE CASCADE. Timestamps are TIMESTAMPTZ DEFAULT now(). schema_version
-- mirrors the model's own field so migrations have something to branch on.
--
-- RLS IS INTENTIONALLY NOT ENABLED YET. Phase 2.5 access is service-role only,
-- from the backend (the shared bearer token gates the API, not the DB). Real
-- per-athlete Row-Level Security lands with Supabase Auth in Phase 3, at which
-- point every table below gets `ENABLE ROW LEVEL SECURITY` + policies keyed on
-- auth.uid() -> athlete_id. Do not add RLS piecemeal before then.

create extension if not exists "pgcrypto";  -- gen_random_uuid()

-- --------------------------------------------------------------------------
-- athletes -- the root entity. No athlete_id FK (its own athlete_id IS the key
-- other tables reference). slug is the human handle used by the FileStore tree
-- and every StoreInterface call.
-- --------------------------------------------------------------------------
create table if not exists athletes (
    athlete_id     uuid primary key,
    slug           text unique not null,
    schema_version integer not null default 1,
    data           jsonb not null,
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now()
);

-- --------------------------------------------------------------------------
-- events -- stored as a *set* per athlete. save_events replaces the whole set
-- in a transaction (mirrors FileStore, which rewrites events.yaml wholesale).
-- --------------------------------------------------------------------------
create table if not exists events (
    id             uuid primary key,
    athlete_id     uuid not null references athletes(athlete_id) on delete cascade,
    event_date     date not null,
    schema_version integer not null default 1,
    data           jsonb not null,
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now()
);
create index if not exists events_athlete_idx on events(athlete_id);

-- --------------------------------------------------------------------------
-- macro_plans -- exactly one per athlete (athlete_id is the PK).
-- --------------------------------------------------------------------------
create table if not exists macro_plans (
    athlete_id     uuid primary key references athletes(athlete_id) on delete cascade,
    id             uuid not null,
    event_id       uuid not null,
    schema_version integer not null default 1,
    data           jsonb not null,
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now()
);

-- --------------------------------------------------------------------------
-- week_plans -- one per (athlete, ISO week). Sessions currently live inside the
-- WeekPlan JSON (see the reserved `sessions` stub below); they are NOT split
-- out in this migration.
-- --------------------------------------------------------------------------
create table if not exists week_plans (
    id             uuid primary key,
    athlete_id     uuid not null references athletes(athlete_id) on delete cascade,
    iso_week       text not null,
    schema_version integer not null default 1,
    data           jsonb not null,
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now(),
    unique (athlete_id, iso_week)
);
create index if not exists week_plans_athlete_idx on week_plans(athlete_id);

-- --------------------------------------------------------------------------
-- workouts -- PK is the workout's OWN uuid, so re-saving the same id upserts
-- (matches FileStore's idempotence note); two same-date same-sport workouts
-- with different ids coexist (double pool days).
-- --------------------------------------------------------------------------
create table if not exists workouts (
    id             uuid primary key,
    athlete_id     uuid not null references athletes(athlete_id) on delete cascade,
    date           date not null,
    sport          text not null,
    schema_version integer not null default 1,
    data           jsonb not null,
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now()
);
create index if not exists workouts_athlete_date_idx on workouts(athlete_id, date);

-- --------------------------------------------------------------------------
-- wellness_checkins -- one per (athlete, date).
-- --------------------------------------------------------------------------
create table if not exists wellness_checkins (
    id             uuid primary key,
    athlete_id     uuid not null references athletes(athlete_id) on delete cascade,
    date           date not null,
    schema_version integer not null default 1,
    data           jsonb not null,
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now(),
    unique (athlete_id, date)
);
create index if not exists wellness_athlete_date_idx on wellness_checkins(athlete_id, date);

-- --------------------------------------------------------------------------
-- coach_texts -- verbatim pool-coach text in `body`, saved BEFORE any parsing.
-- One per (athlete, day). save_coach_text raises FileExistsError when a row
-- exists for that day and force=False (enforced by the UNIQUE constraint plus
-- a pre-check in DbStore); force=True overwrites. storage_key holds the
-- db://coach_texts/<slug>/<day> location string returned to callers.
-- --------------------------------------------------------------------------
create table if not exists coach_texts (
    id             uuid primary key,
    athlete_id     uuid not null references athletes(athlete_id) on delete cascade,
    day            date not null,
    body           text not null,
    storage_key    text not null,
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now(),
    unique (athlete_id, day)
);
create index if not exists coach_texts_athlete_day_idx on coach_texts(athlete_id, day);

-- ==========================================================================
-- RESERVED STUBS -- created so the schema is complete, but NOT used by DbStore
-- in Phase 2.5. Do not write to these yet.
-- ==========================================================================

-- sessions: reserved. WeekPlan currently carries its sessions inside its JSON
-- (week_plans.data -> "sessions"); they are NOT split into rows now. When
-- per-session querying is needed, denormalize into this table alongside the
-- JSON (JSON stays the source of truth until then).
create table if not exists sessions (
    id             uuid primary key,
    athlete_id     uuid not null references athletes(athlete_id) on delete cascade,
    week_plan_id   uuid references week_plans(id) on delete cascade,
    date           date,
    sport          text,
    schema_version integer not null default 1,
    data           jsonb not null,
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now()
);

-- uploaded_files: reserved for Phase 2/3 raw .fit/.tcx/.csv uploads (raw bytes
-- go to Supabase Storage; this table holds the metadata row). Not used yet.
create table if not exists uploaded_files (
    id             uuid primary key,
    athlete_id     uuid not null references athletes(athlete_id) on delete cascade,
    storage_key    text not null,
    filename       text,
    content_type   text,
    created_at     timestamptz not null default now()
);

-- api_tokens: reserved (Phase 3). Auth-lite v1 uses one shared bearer token in
-- an env var; this table holds sha256-hashed per-athlete tokens when real auth
-- lands. Not used yet.
create table if not exists api_tokens (
    id             uuid primary key,
    athlete_id     uuid not null references athletes(athlete_id) on delete cascade,
    token_sha256   text unique not null,
    created_at     timestamptz not null default now()
);

-- chat_messages: reserved (Phase 3). Chat history is client-supplied per
-- request in v1 (see backend/app/routes/chat.py); this table persists it
-- server-side when needed. Not used yet.
create table if not exists chat_messages (
    id             uuid primary key,
    athlete_id     uuid not null references athletes(athlete_id) on delete cascade,
    role           text not null,
    content        text not null,
    created_at     timestamptz not null default now()
);
