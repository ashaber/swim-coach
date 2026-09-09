-- swim-coach threshold-record durable log -- the missing durable, dated,
-- per-sport threshold history (FTP/LTHR/CSS), built alongside
-- update_athlete_profile (the missing tool that would have let the coach
-- persist Andrew's real 263W working FTP anchor when he prompted it -- see
-- engine/swim_coach/models.py's ThresholdRecord docstring for the full
-- rationale). Before this table existed, `Athlete.css_pace_s_per_100m`/
-- `lthr_bpm`/`ftp_watts` (PR #167) were the ONLY place any threshold value
-- could live -- three ad-hoc, undated, unsourced flat fields with no way
-- for the coach to ever write them, and no memory of where a value came
-- from or how old it is once it's set. A threshold isn't a single mutable
-- fact -- it decays in accuracy over time, and a later reading must never
-- silently erase an earlier one's record.
--
-- Same JSONB-hybrid pattern as `health_status` in
-- 20260901000000_health_status.sql (NOT `feedback`'s all-columns shape):
-- `data` holds the full ThresholdRecord JSON, and `athlete_id`/`sport`/
-- `metric`/`measured_at` are promoted to real columns for the one query
-- shape this table exists to serve fast -- "give me this athlete's
-- threshold history for one sport+metric, most recent first."
--
-- APPEND-ONLY, with NO in-place-mutation path at all (unlike
-- `health_status`'s `resolved` flip) -- this codebase's own safety rail:
-- never delete logs. A threshold reading is never "wrong" the way an open
-- injury status can be closed out; it just ages. The engine NEVER reads
-- this table to auto-pick a "current" value -- see
-- engine/swim_coach/context.py's `_recent_thresholds`/render function and
-- ThresholdRecord's own docstring for why that judgment call stays with
-- the coach. The engine-resolved value zones.py/load.py actually read
-- stays exactly where it already lives -- `athletes.data`'s
-- `ftp_watts`/`lthr_bpm`/`css_pace_s_per_100m` keys, set via
-- `update_athlete_profile` only after a human/coach judges a reading here
-- trustworthy enough to adopt.
--
-- RLS IS INTENTIONALLY NOT ENABLED YET, same as `health_status` and every
-- table in 20260706000000_init.sql -- see that migration's header comment
-- for why.
--
-- MANUAL APPLICATION REQUIRED: per this project's established convention
-- (every migration in supabase/migrations/ is applied by hand via psql, not
-- automatically on merge/deploy -- see this repo's CLAUDE.md/commit
-- history), this file must be applied to the production Supabase instance
-- by Andrew before record_threshold_test/update_athlete_profile work
-- against production. Merging the PR that adds this file does NOT apply
-- it.

create table if not exists threshold_records (
    id             uuid primary key,
    athlete_id     uuid not null references athletes(athlete_id) on delete cascade,
    sport          text not null,
    metric         text not null,
    measured_at    date not null,
    schema_version integer not null default 1,
    data           jsonb not null,
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now()
);
create index if not exists threshold_records_athlete_sport_metric_idx
    on threshold_records(athlete_id, sport, metric, measured_at desc);
