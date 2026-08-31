-- swim-coach coach-mode Q&A build -- feedback gains a PLANNED-session
-- linkage alongside its existing workout_id one.
--
-- `session_date`/`session_sport` link a question to a planned Session by
-- (date, sport) rather than a raw session id -- Session.id does NOT survive
-- `replace_week_plan` (every session in a regenerated week gets a fresh
-- uuid4(), see plan.py/tools.py), so a question linked by raw id would
-- silently orphan the moment its week is regenerated. (date, sport) is the
-- same stability fallback `quality.match_workout_to_session` already trusts
-- for matching a completed workout to its planned session. See
-- engine/swim_coach/models.py's Feedback docstring.
--
-- Mutually exclusive with `workout_id` at the application layer
-- (backend/app/routes/feedback.py) -- not enforced here as a DB constraint,
-- same as every other cross-field invariant in this schema (e.g.
-- needs_human_review/research_gap in the 20260824000001 migration).

alter table feedback add column if not exists session_date date;
alter table feedback add column if not exists session_sport text;

create index if not exists feedback_session_date_sport_idx on feedback(session_date, session_sport);
