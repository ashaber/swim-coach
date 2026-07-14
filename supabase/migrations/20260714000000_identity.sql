-- swim-coach Slice 1 -- server-side verified identity.
--
-- Backs POST /api/auth/google + GET /api/me (backend/app/routes/auth.py) and
-- require_auth's new athlete-session path (backend/app/auth.py). PURELY
-- ADDITIVE: the legacy shared API_TOKEN path (backend/app/config.py's
-- Settings.token_matches) is completely untouched, and neither table here is
-- read by any existing route/job until an athlete actually signs in via
-- Google -- the live PWA, CLI, scripts/, and the intervals.icu sync job
-- keep working exactly as they do today after this migration runs.
--
-- Table naming note: the session table below is named `auth_sessions`, NOT
-- `sessions` -- `sessions` is already a RESERVED stub table in
-- 20260706000000_init.sql for WeekPlan's per-session rows (a completely
-- different concept: a planned/logged swim session vs. a signed-in identity
-- session). Reusing that name here would collide with that reservation.
--
-- RLS IS INTENTIONALLY NOT ENABLED YET, same rationale as every table in
-- 20260706000000_init.sql -- service-role only from the backend for now;
-- real per-athlete RLS is a later Phase 3 step, not this slice.

-- --------------------------------------------------------------------------
-- allowed_emails -- the beta allowlist. A signed-in Google email that isn't
-- here gets 403 {"error": "request access"} from POST /api/auth/google, with
-- no session and no athlete created. Adding/removing a beta user is a data
-- change to this table (swim_coach.cli's invite/list-invites/revoke-invite),
-- never a code deploy.
-- --------------------------------------------------------------------------
create table if not exists allowed_emails (
    email          text primary key,
    athlete_id     uuid not null references athletes(athlete_id) on delete cascade,
    note           text,
    created_at     timestamptz not null default now()
);
create index if not exists allowed_emails_athlete_idx on allowed_emails(athlete_id);

-- --------------------------------------------------------------------------
-- auth_sessions -- opaque server-minted session tokens. `token_hash` is the
-- sha256 hex digest of the raw token returned once by POST /api/auth/google
-- (the raw token is never persisted, same discipline as Settings.
-- api_token_hash for the legacy shared token). `revoked_at` is set by
-- explicit revocation; `expires_at` bounds the session's lifetime
-- regardless (~30 days by default, see backend/app/config.py's
-- SESSION_TTL_DAYS). Both are evaluated by require_auth at request time,
-- never at the DB layer (no stored procedure enforces them) -- see
-- StoreInterface.get_session's docstring.
-- --------------------------------------------------------------------------
create table if not exists auth_sessions (
    token_hash     text primary key,
    athlete_id     uuid not null references athletes(athlete_id) on delete cascade,
    created_at     timestamptz not null default now(),
    expires_at     timestamptz not null,
    revoked_at     timestamptz
);
create index if not exists auth_sessions_athlete_idx on auth_sessions(athlete_id);
create index if not exists auth_sessions_expires_idx on auth_sessions(expires_at);

-- --------------------------------------------------------------------------
-- Seed the three existing beta users so the step-2 frontend switch (a later
-- PR) is a no-op for them -- mirrors web/src/identity.js's
-- EMAIL_IDENTITY_MAP today (deleted in that later PR once the backend is
-- the source of truth for identity).
--
-- Resolved via slug rather than a hardcoded athlete_id: athlete_id is
-- environment-specific (dev/staging/prod each have their own row for the
-- same slug), so `select athlete_id from athletes where slug = ...` is the
-- portable way to seed this across environments. If a given environment's
-- athletes table doesn't have that slug yet, the SELECT returns no rows and
-- the INSERT is a silent no-op for that one row -- not an error.
-- --------------------------------------------------------------------------
insert into allowed_emails (email, athlete_id, note)
select 'andrewshaber@gmail.com', athlete_id, 'seeded: step-1 rollout (repo owner)'
from athletes where slug = 'andrew'
on conflict (email) do nothing;

insert into allowed_emails (email, athlete_id, note)
select 'kline.renee@gmail.com', athlete_id, 'seeded: step-1 rollout'
from athletes where slug = 'renee'
on conflict (email) do nothing;

insert into allowed_emails (email, athlete_id, note)
select 'curry.mtb@gmail.com', athlete_id, 'seeded: step-1 rollout'
from athletes where slug = 'tim'
on conflict (email) do nothing;
