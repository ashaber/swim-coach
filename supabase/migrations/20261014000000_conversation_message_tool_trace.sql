-- Per-turn tool trace on AI replies in the athlete<->coach conversation: the server's compact
-- record of which tools the coach actually called that turn, replayed into later turns' chat
-- history (see app.save_claims.format_tool_trace). Nullable: NULL = turn predates the column
-- (unknown, not "no tools"). Workout chat messages are embedded JSONB and need no migration.
--
-- Idempotent: CI applies every migration twice against a throwaway Postgres.
--
-- MANUAL APPLICATION REQUIRED: merging the PR that adds this file does NOT apply it.
-- Apply by hand via psql, THEN deploy the backend.

alter table conversation_messages add column if not exists tool_trace text;
