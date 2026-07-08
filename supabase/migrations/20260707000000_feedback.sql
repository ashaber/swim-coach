-- swim-coach Phase 2.5 -- durable feedback log.
--
-- Replaces the ephemeral research/open-questions.jsonl file (IDEA 005): on
-- Cloud Run that file lived on an EPHEMERAL disk, wiped on scale-to-zero, so
-- every coach-logged research gap was silently lost. Generalizes it into a
-- durable feedback log that also holds athlete-submitted feature requests,
-- comments, and bug reports (see the app's Feedback tab / POST /api/feedback).
--
-- Unlike 20260706000000_init.sql's tables, `feedback` does NOT use the
-- JSONB-hybrid data-blob pattern -- every Feedback field (engine/swim_coach/
-- models.py) maps onto its own column; `context` is the one free-form JSONB
-- field, for type-specific extras a coach research_question or an athlete
-- bug report might carry. schema_version is not persisted as a column (it is
-- not in this table's spec); DbStore's row_to_feedback always reconstructs
-- it as the model's default (1).
--
-- RLS IS INTENTIONALLY NOT ENABLED YET, same as every table in
-- 20260706000000_init.sql -- see that migration's header comment for why.

create table if not exists feedback (
    id             uuid primary key,
    athlete_id     uuid references athletes(athlete_id) on delete set null,
    type           text not null check (type in ('research_question', 'feature_request', 'comment', 'bug')),
    source         text not null check (source in ('coach', 'athlete')),
    body           text not null,
    context        jsonb,
    status         text not null default 'open',
    created_at     timestamptz not null default now()
);
create index if not exists feedback_athlete_idx on feedback(athlete_id);
create index if not exists feedback_created_at_idx on feedback(created_at desc);
