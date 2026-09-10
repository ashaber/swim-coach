-- swim-coach workout time-series store -- the durable home for a workout's
-- columnar per-record telemetry (`t_s` plus whichever of
-- `hr`/`speed_mps`/`dist_m`/`power_w`/`cadence_rpm`/`altitude_m`/`grade`
-- channels the `.fit` file carried -- see
-- engine/swim_coach/parse_files.py's `_build_series`). Before this table
-- existed, `FileStore.save_series` wrote a JSON sidecar on local disk and
-- `DbStore` had NO series handling at all: on a `db`-backed deploy
-- (`STORE_BACKEND=db`, i.e. production) the parsed activity stream was
-- discarded entirely, so nothing could ever recompute a synced ride's
-- interval analytics after the fact. This table is what lets the
-- `reanalyze_workout` coach tool (and the `analyze` CLI) reload a ride's
-- power/grade stream and re-run the deterministic interval analyzer once
-- the athlete supplies a target the file itself never carried.
--
-- Same JSONB-hybrid pattern as `threshold_records` in
-- 20260907000000_threshold_records.sql (NOT `feedback`'s all-columns
-- shape): `data` holds the whole columnar payload as one JSONB object, and
-- `athlete_id`/`date`/`sport` are promoted to real columns for the one
-- query shape this table serves -- "this athlete's series for one
-- workout" (by PK) and "... over a date range".
--
-- Keyed by `workout_id` (PK). Re-saving the same id OVERWRITES -- callers
-- always re-derive the payload from a freshly parsed `.fit`, so there is no
-- "don't clobber prior data" concern (unlike `coach_texts`). The FK is to
-- `athletes` only, deliberately NOT to `workouts(id)`: the backend's
-- enrich path (backend/app/enrich.py) can persist a series before the
-- confirmed `Workout` row exists, exactly as it always has for the
-- FileStore sidecar. `on delete cascade` on the athlete FK keeps this in
-- step with every other per-athlete table.
--
-- RLS IS INTENTIONALLY NOT ENABLED YET, same as every table in
-- 20260706000000_init.sql -- see that migration's header comment for why.
--
-- MANUAL APPLICATION REQUIRED: per this project's established convention
-- (every migration in supabase/migrations/ is applied by hand via psql,
-- not automatically on merge/deploy -- see this repo's CLAUDE.md/commit
-- history and MEMORY.md's "DB migrations are manual" note), this file must
-- be applied to the production Supabase instance by Andrew before
-- `reanalyze_workout` / series persistence work against production.
-- Merging the PR that adds this file does NOT apply it. CI's `db` job
-- applies it twice against a throwaway Postgres to prove it is idempotent.

create table if not exists workout_series (
    workout_id     uuid primary key,
    athlete_id     uuid not null references athletes(athlete_id) on delete cascade,
    date           date not null,
    sport          text not null,
    schema_version integer not null default 1,
    data           jsonb not null,
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now()
);
create index if not exists workout_series_athlete_date_idx
    on workout_series(athlete_id, date desc);
