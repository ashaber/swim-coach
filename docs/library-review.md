# Library review: cards, the Resources tab, and applying decisions

How `library/*.md` research-library content gets human-reviewed, end to
end. Replaces the old flow (trace a topic file's markdown for the
`UNREVIEWED` marker, hand-edit it, re-upload) with a small reviewer built
into the PWA's Resources tab.

## The pieces

- **Topic files** (`library/*.md`) are the actual research content: claims
  tagged `[EVIDENCE: ...]`/`[ADAPTED: ...]` + `Confidence:` + `Test:`, or
  `Coach judgment:` for unsourced engineering defaults. See
  `library/00-conventions.md` for the tagging scheme and
  `engine/swim_coach/library_review.py`'s module docstring for how an
  `UNREVIEWED` marker's scope (file- or section-level) governs which claims
  are still pending.
- **Review cards** (`library/review-cards/<topic-stem>.yaml`) are a
  sidecar, NOT inside the topic file — topic files are routed into the
  chat model's context (`backend/app/context.py`), and every word added
  there costs tokens on every relevant request. One card per `##`
  (level-2) section: `section` (a slug), `heading` (verbatim), `summary`
  (≤35 words, what the section says), `recommendation` (≤35 words, what
  the coach will actually tell/do an athlete because of it — `"none --
  background only"` is valid), and `content_hash` (a hash of the section's
  own text at card-authoring time). Schema: `engine/swim_coach/
  library_cards.py`.
- **Everything else a reviewer sees is DERIVED, never hand-typed onto a
  card**: confidence (lowest among the section's tagged claims), evidence
  tags, source count + weak/caveated (~/⚠) count, whether an `UNREVIEWED`
  marker still covers the section, whether the section needs judgment
  (any `EVIDENCE`/`ADAPTED` claim) vs. is purely mechanical
  (`Coach judgment` only), and `stale` (has the section's live text
  drifted from the card's `content_hash`). Computed by
  `library_review.section_evidence` and `library_cards.is_stale` at
  request time — see `backend/app/routes/library.py`.
- **Review decisions** (`LibraryReview`, `engine/swim_coach/models.py`) are
  an append-only log: every accept/flag is a new row, never an edit of a
  previous one. Persisted via the usual store seam (`StoreInterface` →
  `FileStore`/`DbStore`, `supabase/migrations/
  20260924000000_library_reviews.sql`).

## Authoring cards for a new/changed section

Whenever a research build adds a `##` section to a topic file (or
materially changes an existing one), add/update its card in the matching
`library/review-cards/<stem>.yaml`:

1. Read the section's actual text. Write `summary` (what it says) and
   `recommendation` (the athlete-facing takeaway, or `"none -- background
   only"`) — both ≤35 words, faithful to the text, no invented claims or
   numbers.
2. Compute `content_hash` = `library_cards.content_hash(section_text)` —
   `section_text(topic_file_text, section)` gives the exact stripped body
   text to hash; `section` slugs come from `topic_sections(text)`. In
   practice: run the assembly the same way this build's card-authoring
   pass did (read the file, get its sections, hash each one) rather than
   hand-computing a sha256 digest.
3. `pytest tests/unit/test_library_cards.py` pins three things against the
   REAL repo content: every in-scope section has a card, every card stays
   within the word limits, and every card's `content_hash` matches its
   section's current text. A stale hash here means the card text needs
   updating to match what actually changed — it's the safety net that
   catches "I edited the library file but forgot the card."

Files excluded from card coverage (`library_cards.EXCLUDED_FROM_CARDS`):
`00-conventions.md`/`INDEX.md`/`reference_list.md` (meta, no claims of
their own) and the `sample_*`/`researched-*` files (raw reference
material, not periodization/physiology claims).

## The Resources tab (PWA)

**Research library** (everyone): cards grouped by file, filter chips All /
Needs review / Flagged. Each card shows its heading, file, confidence
badge (lowest across its claims), status badge (reviewed/unreviewed),
stale badge, summary, recommendation, and source count. "Read full
section" opens the topic file (`GET /api/library/files/{name}`) rendered
via `markdown.js`, scrolled to the section's anchor.

**Approvals** (only when `is_library_admin`): unreviewed + stale cards,
needs-judgment ones first, each with Accept and Flag (a note is required
to flag) buttons — optimistic UI, error state on failure. Calls
`POST /api/library/reviews`. Offline: the last-fetched cards and files are
cached in `localStorage` and shown read-only; Approvals actions are
disabled with a message while offline (there's nothing to optimistically
apply against).

## Applying an accepted decision back into the repo

A `POST /api/library/reviews` call only ever RECORDS a decision — it never
edits `library/*.md`. Andrew runs the CLI to actually strip a marker:

```
python -m swim_coach.cli library-review-apply [--dry-run]
```

For every card whose CURRENT decision (most recent by `created_at`) is
`"accepted"`:

- if the section's live `content_hash` no longer matches what was
  reviewed, it's skipped (`stale-hash`) — the text changed since the
  review; it needs re-review, never a silent apply.
- if the section carries its own section-scoped `UNREVIEWED` marker
  (e.g. `04-css-intensity-anchors.md`'s "Open questions" section), that
  marker is stripped directly.
- if the section is covered by its file's file-level marker instead (the
  common case for a freshly-drafted topic file), nothing is stripped for
  it alone — the file-level marker is the same atomic unit
  `review-accept` already treats it as, so it's only stripped once EVERY
  section in that file has a current accepted decision with a matching
  hash. A file with any section not yet accepted reports
  `partial-file` with the sections still blocking it. Clearing it also
  flips `INDEX.md`'s row to "Human-reviewed.", same as `review-accept`.

`--dry-run` reports every action it would take without writing anything.
Andrew reviews the resulting `git diff`, and commits it via PR (per this
repo's standing rule: library changes go through a feature branch + PR,
never straight to main) — this command never commits on its own.

## Marker hygiene (why this matters)

`library_review.py`'s `MARKER_RE` only recognizes a bold span containing
the literal word `UNREVIEWED`. A file whose true review status doesn't
match its marker form — "REVIEWED" typed by hand instead of the marker
being stripped, or a file authored with no marker at all despite genuinely
needing review — silently falls out of (or never enters) the queue. This
happened to 12 real files before the `web/resources-tab-library-review`
build audited and fixed every one (see that PR/commit history and
`tests/unit/test_library_review.py`'s
`test_every_file_index_calls_pending_is_actually_detected`, which pins
`INDEX.md`'s own row text against what the scanner actually finds). When
authoring or reviewing a topic file by hand, always use the exact
`**UNREVIEWED**` form (or run it through `review-accept`/
`library-review-apply` to remove it) — never hand-type a status word the
scanner doesn't recognize.
