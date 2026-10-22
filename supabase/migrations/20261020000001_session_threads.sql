-- swim-coach planned-session chat threads -- the Plan tab's session detail now has the same
-- scoped, persisted conversation a logged workout has (IDEA 016). A workout embeds its
-- messages in its own JSONB; a session lives inside a week plan the coach rewrites, so its
-- messages get their own append-only table keyed by (athlete, session id) instead. See
-- engine/swim_coach/models.py's SessionChatMessage.
--
-- `session_id` is NOT a foreign key: sessions live in `weeks.data` JSONB, not a table.
-- `session_threads` holds per-thread state (currently only whether the AI is muted); a session
-- with no row is unmuted.
--
-- Idempotent: CI applies every migration twice against a throwaway Postgres.
--
-- MANUAL APPLICATION REQUIRED: merging the PR that adds this file does NOT apply it.
-- Apply by hand via psql, THEN deploy the backend.

create table if not exists session_chat_messages (
    id          uuid primary key,
    athlete_id  uuid not null references athletes(athlete_id) on delete cascade,
    session_id  uuid not null,
    sender_role text not null check (sender_role in ('athlete', 'ai_coach', 'coach')),
    body        text not null,
    tool_trace  text,
    created_at  timestamptz not null default now()
);
create index if not exists session_chat_messages_thread_idx
    on session_chat_messages(athlete_id, session_id, created_at, id);

create table if not exists session_threads (
    athlete_id uuid not null references athletes(athlete_id) on delete cascade,
    session_id uuid not null,
    ai_muted   boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (athlete_id, session_id)
);
