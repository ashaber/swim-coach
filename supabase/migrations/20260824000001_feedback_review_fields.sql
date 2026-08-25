-- swim-coach coach-mode Chunk A -- feedback gains human-coach-review fields.
--
-- Extends `feedback` (20260707000000_feedback.sql) so a durable Q&A/comment
-- row can be linked to a workout, flagged for a human coach's attention, and
-- carry that coach's reply -- without a second table. See
-- engine/swim_coach/models.py's Feedback docstring: `type` and
-- `needs_human_review` are orthogonal (a 'research_question' row can ALSO be
-- `needs_human_review=true` when it's both under-evidenced AND urgent, one
-- row, not a fork into a second entry).
--
-- `type` is widened to add 'question' (athlete-initiated, expects an answer)
-- and 'coach_review' (AI-flagged needs_human_review with no research gap --
-- pain/safety escalations, an explicit "talk to my coach" request, or any
-- other high-stakes judgment call the AI declines to make alone).
--
-- The original migration left the `type` check constraint unnamed, so
-- Postgres auto-named it `feedback_type_check` (Postgres's standard
-- <table>_<column>_check convention for an inline, unnamed column
-- constraint). `drop constraint if exists` + `add constraint` (with that same
-- name, explicit this time) is idempotent under CI's twice-in-a-row apply:
-- the first run drops nothing then adds; the second run drops the
-- just-added constraint then re-adds the identical one.

alter table feedback add column if not exists workout_id uuid references workouts(id) on delete set null;
alter table feedback add column if not exists needs_human_review boolean not null default false;
alter table feedback add column if not exists ai_provisional_answer text;
alter table feedback add column if not exists coach_athlete_id uuid references athletes(athlete_id) on delete set null;
alter table feedback add column if not exists coach_reply text;
alter table feedback add column if not exists coach_reply_at timestamptz;

create index if not exists feedback_workout_idx on feedback(workout_id);
create index if not exists feedback_coach_athlete_idx on feedback(coach_athlete_id);
create index if not exists feedback_needs_human_review_idx on feedback(needs_human_review) where needs_human_review;

alter table feedback drop constraint if exists feedback_type_check;
alter table feedback add constraint feedback_type_check
    check (type in ('research_question', 'feature_request', 'comment', 'bug', 'question', 'coach_review'));
