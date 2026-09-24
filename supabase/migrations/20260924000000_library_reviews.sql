-- swim-coach web/resources-tab-library-review build -- library review cards.
--
-- One admin decision (accept/flag) on a research-library review card
-- (`library/review-cards/<stem>.yaml`, one card per `##` section of a
-- `library/*.md` topic file). See engine/swim_coach/models.py's
-- LibraryReview docstring and docs/library-review.md for the full
-- authoring/review workflow.
--
-- `file`/`section` name a card (the topic file's own filename + its section
-- slug) -- there is deliberately no foreign key onto a `library_cards`
-- table, since cards are authored/versioned as YAML in the repo, never a DB
-- row of their own. `content_hash` is the card's hash AT REVIEW TIME, so
-- `library-review-apply` (engine/swim_coach/cli.py) can tell an accepted
-- decision whose section text has since changed (stale, must be re-
-- reviewed) from one that's still current.
--
-- Append-only, same convention as `feedback`/`health_status`: a re-review of
-- the same (file, section) is a NEW row, never an UPDATE, so decision
-- history is never lost.
--
-- Like `feedback`/`coach_grants`, this does NOT use the JSONB-hybrid
-- data-blob pattern -- every LibraryReview field maps onto its own column.
--
-- RLS IS INTENTIONALLY NOT ENABLED YET, same as every table in
-- 20260706000000_init.sql -- see that migration's header comment for why.

create table if not exists library_reviews (
    id             uuid primary key,
    file           text not null,
    section        text not null,
    content_hash   text not null,
    decision       text not null check (decision in ('accepted', 'flagged')),
    note           text,
    reviewed_by    uuid not null references athletes(athlete_id) on delete cascade,
    created_at     timestamptz not null default now()
);
create index if not exists library_reviews_file_section_idx on library_reviews(file, section);
create index if not exists library_reviews_created_at_idx on library_reviews(created_at desc);
