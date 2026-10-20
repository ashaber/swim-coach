-- Haiku coach router, shadow mode: a reviewed sample of what Haiku WOULD have replied next to what
-- Sonnet actually replied, for the athletes named in COACH_ROUTER_CAPTURE_ATHLETES (default none).
-- Append-only. Holds athlete message text, so it is written only for opted-in athletes and the text
-- is never logged. Its own table (not a column on chat messages) because the general Coach tab chat
-- is not persisted server-side at all -- only workout and conversation threads are.
--
-- Safe to leave unapplied: the backend swallows and logs a failed capture write
-- ("router capture failed"); nothing user-facing depends on this table.
--
-- Idempotent: CI applies every migration twice against a throwaway Postgres.
--
-- RLS IS INTENTIONALLY NOT ENABLED YET, same as every table in 20260706000000_init.sql.
--
-- MANUAL APPLICATION REQUIRED: merging the PR that adds this file does NOT apply it.
-- Apply by hand via psql, THEN (or before) deploying the backend.

create table if not exists router_shadow_captures (
    id          uuid primary key,
    athlete_id  uuid not null references athletes(athlete_id) on delete cascade,
    request_id  text not null,
    question    text not null,
    haiku_reply text,
    sonnet_reply text,
    decision    jsonb not null default '{}'::jsonb,
    created_at  timestamptz not null default now()
);

create index if not exists router_shadow_captures_athlete_created_idx
    on router_shadow_captures (athlete_id, created_at desc);
