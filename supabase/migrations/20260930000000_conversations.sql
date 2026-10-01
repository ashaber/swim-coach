-- swim-coach athlete<->coach conversation (IDEA 016 "Part 2") -- the general, not
-- workout-scoped, three-party thread (athlete, AI coach, human coach) shown to the
-- athlete as "My coach" inside the Coach tab and to the coach on the roster's
-- Conversations sub-tab. Part 1 (per-workout thread) embeds its messages on the
-- workout; this thread is unbounded for the life of the relationship, so it gets its
-- own append-only table. See engine/swim_coach/models.py's ConversationMessage.
--
-- One thread per (athlete, coach) pair -- the thread is keyed on the two athlete rows,
-- NOT on a coach_grants row, so it survives a revoked-and-re-created grant. Access is
-- always gated in the API by an ACTIVE grant; this schema does not encode it.
--
-- `conversation_messages` is append-only and has no `data` JSONB blob (every field is
-- its own column, like `feedback`/`coach_grants`). `conversations` holds per-thread
-- state (currently only whether the AI is muted); a thread with no row is unmuted.
--
-- Idempotent: CI applies every migration twice against a throwaway Postgres.
--
-- RLS IS INTENTIONALLY NOT ENABLED YET, same as every table in
-- 20260706000000_init.sql -- see that migration's header comment for why.
--
-- MANUAL APPLICATION REQUIRED: merging the PR that adds this file does NOT apply it.
-- Apply by hand via psql (README, "Cutover" section), THEN deploy the backend.

create table if not exists conversations (
    athlete_id       uuid not null references athletes(athlete_id) on delete cascade,
    coach_athlete_id uuid not null references athletes(athlete_id) on delete cascade,
    ai_muted         boolean not null default false,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now(),
    primary key (athlete_id, coach_athlete_id)
);

create table if not exists conversation_messages (
    id               uuid primary key,
    athlete_id       uuid not null references athletes(athlete_id) on delete cascade,
    coach_athlete_id uuid not null references athletes(athlete_id) on delete cascade,
    sender_role      text not null check (sender_role in ('athlete', 'ai_coach', 'coach')),
    body             text not null,
    created_at       timestamptz not null default now()
);
create index if not exists conversation_messages_thread_idx
    on conversation_messages(athlete_id, coach_athlete_id, created_at, id);
