-- swim-coach Slice 1 of self-service in-app onboarding -- nullable athlete_id.
--
-- Design: docs/design-self-service-onboarding.md, PR #63. Backs the
-- "onboarding-scoped session" auth foundation: an email can now be invited
-- BEFORE an athlete exists for it, and that person's first Google sign-in
-- mints a session with NO athlete bound -- see backend/app/routes/auth.py's
-- new onboarding branch and backend/app/auth.py's `Principal(kind=
-- "onboarding", ...)`.
--
-- THE BLOCKER this migration removes: both `allowed_emails.athlete_id` and
-- `auth_sessions.athlete_id` were `NOT NULL` (20260714000000_identity.sql),
-- so every existing write path required an athlete to already exist. This
-- migration makes both columns nullable and treats `athlete_id IS NULL` as
-- the pending/onboarding state -- a non-null value must still reference a
-- real athlete (the FK itself is UNCHANGED, only its NOT NULL constraint is
-- dropped).
--
-- IDEMPOTENT: `DROP NOT NULL` on an already-nullable column is a no-op, not
-- an error -- safe to re-run (matches this repo's CI, which applies every
-- migrations/*.sql file twice in a row as an idempotency check).
--
-- RLS is still intentionally not enabled -- same rationale as
-- 20260706000000_init.sql and 20260714000000_identity.sql.

alter table allowed_emails alter column athlete_id drop not null;
alter table auth_sessions alter column athlete_id drop not null;
