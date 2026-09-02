-- swim-coach health-status durable record -- the missing durable trace of
-- injury/illness/medical status, built after a real incident (an athlete's
-- undetected medical/stress episode) exposed that this system had NO durable
-- record of health status anywhere: Wellness.soreness is a daily 1-5
-- self-rating with no memory beyond "today," backend/app/routes/chat.py
-- persists nothing server-side (chat history is client-supplied per
-- request), and there was no model of this shape at all. CLAUDE.md's own
-- standing safety rail -- "any pain report -> stop-and-assess" -- was
-- enforced ONLY as prompt-level guidance with zero durable backing before
-- this table existed. See engine/swim_coach/models.py's HealthStatus
-- docstring for the full model rationale.
--
-- Same JSONB-hybrid pattern as `wellness_checkins` in
-- 20260706000000_init.sql (NOT `feedback`'s all-columns shape): `data` holds
-- the full HealthStatus JSON, and `athlete_id`/`reported_at`/`resolved` are
-- promoted to real columns for the one query shape this table exists to
-- serve fast -- "give me this athlete's current active status," i.e. the
-- most recent row for this athlete with resolved = false.
--
-- Unlike `wellness_checkins` (one row per athlete+date, upserted), this is
-- an APPEND-ONLY log: every entry is its own row, never overwritten by a
-- later one (this codebase's own safety rail: never delete logs, and never
-- silently overwrite health-status history either -- see the model
-- docstring). The ONE mutation this table allows is flipping an existing
-- row's `resolved` (see engine/swim_coach/store_db.py's
-- `update_health_status`), which also re-syncs `data` so the promoted
-- column and the JSON blob never drift apart.
--
-- RLS IS INTENTIONALLY NOT ENABLED YET, same as every table in
-- 20260706000000_init.sql -- see that migration's header comment for why.
--
-- MANUAL APPLICATION REQUIRED: per this project's established convention
-- (every migration in supabase/migrations/ is applied by hand via psql, not
-- automatically on merge/deploy -- see this repo's CLAUDE.md/commit
-- history), this file must be applied to the production Supabase instance
-- by Andrew before the health-status feature works against production.
-- Merging the PR that adds this file does NOT apply it.

create table if not exists health_status (
    id             uuid primary key,
    athlete_id     uuid not null references athletes(athlete_id) on delete cascade,
    reported_at    timestamptz not null,
    resolved       boolean not null default false,
    schema_version integer not null default 1,
    data           jsonb not null,
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now()
);
create index if not exists health_status_athlete_active_idx
    on health_status(athlete_id, resolved, reported_at desc);
