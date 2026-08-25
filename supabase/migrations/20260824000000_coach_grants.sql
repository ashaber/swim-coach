-- swim-coach coach-mode Chunk A -- coach grants.
--
-- One athlete (the "coach") gets access to another athlete's data. Coaches in
-- this system are themselves athlete accounts -- e.g. Tim, a consulting
-- physiologist with no training data of his own, still has an `athletes/tim/`
-- profile purely to hold a session identity -- so a grant just references the
-- athletes table twice (coach_athlete_id, athlete_id) rather than needing a
-- separate Coach identity model. See engine/swim_coach/models.py's CoachGrant
-- docstring.
--
-- `chat_visibility` controls whether the granted coach can see the athlete's
-- full AI-chat history or only messages the athlete explicitly shares -- the
-- column exists now but is NOT YET ENFORCED anywhere (chat isn't durably
-- persisted at all yet); defaults to the more private 'shared_only' so an
-- athlete who never touches the setting doesn't over-share by default once
-- enforcement lands.
--
-- Like `feedback` (20260707000000_feedback.sql), this does NOT use the
-- JSONB-hybrid data-blob pattern -- every CoachGrant field maps onto its own
-- column.
--
-- RLS IS INTENTIONALLY NOT ENABLED YET, same as every table in
-- 20260706000000_init.sql -- see that migration's header comment for why.

create table if not exists coach_grants (
    id                 uuid primary key,
    coach_athlete_id   uuid not null references athletes(athlete_id) on delete cascade,
    athlete_id         uuid not null references athletes(athlete_id) on delete cascade,
    status             text not null default 'active' check (status in ('active', 'revoked')),
    chat_visibility    text not null default 'shared_only' check (chat_visibility in ('full', 'shared_only')),
    granted_at         timestamptz not null default now(),
    revoked_at         timestamptz,
    check (coach_athlete_id != athlete_id)
);
create index if not exists coach_grants_coach_idx on coach_grants(coach_athlete_id);
create index if not exists coach_grants_athlete_idx on coach_grants(athlete_id);
