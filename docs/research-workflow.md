# The research cycle: from a logged gap to a closed feedback row

This document is the end-to-end cycle for turning a coach-logged research
gap into reviewed, deployed library content — and then closing the loop so
the same question doesn't get re-logged forever. See `ROADMAP.md`'s
"PROPOSED — feedback-triggered library research loop" section for the
original design (2026-07-11); this doc describes the manual version of
that loop as it actually exists today. The automated weekly sweep job
described there (step 2 in that section) is **still not built** — every
step below is run by hand, by Andrew or an agent session, when a batch of
open questions is worth a research pass.

## 1. Triage the queue

List the open `research_question` feedback rows (logged by the coach's
`flag_for_coach_review(research_gap=True)` tool call — `backend/app/
tools.py` — whenever the library doesn't cover something an athlete asked):

```
python -m swim_coach.cli research-queue-list --group-by-topic
```

Dedupe as you go: several rows are often the same question logged more than
once across sessions. Two clean-up paths for a row that isn't a real
research gap:

- **`duplicate`** — a repeat of another still-open row. Dismiss the later
  one with `--duplicate-of` pointing at the row it duplicates.
- **`not_research`** — a bug report or feature request mis-logged as
  `research_question` (this happens; the coach tool's judgment isn't
  perfect).
- **`obsolete`** — the question no longer applies (e.g. the athlete/feature
  it was about no longer exists).

```
python -m swim_coach.cli research-queue-dismiss <id> \
  --reason duplicate --duplicate-of <other-id> --note "same question as <other-id>"
```

Always pass `--dry-run` first on anything you're not certain about — it
validates and reports what would happen without writing.

Whatever remains after triage is the real research backlog — the input to
step 2.

## 2. Research pass -> a verified dossier

For each remaining topic (or cluster of related open questions), run a
research pass and produce a **dossier**: every candidate source confirmed
to exist by title+author web search, recorded as title + author + year +
journal — **never a URL or PubMed/PMC/DOI identifier** (a prior
Gemini-assisted pass fabricated exactly those; see `library/00-
conventions.md`'s "one rule that matters most"). Mark each source ✓
(verified), `~` (author real, this specific paper not individually
verified), or `⚠` (a caveat that must be read before citing).

- **Sonnet is the default model for this pass** — thorough, tool-using
  research over many sources. Fable-tier subagents are reserved for
  source-verification specifically, per the standing model-delegation
  policy; they burn the usage limit too fast to run an entire research
  pass.
- The orchestrating session (Andrew, or an Opus-tier session directing the
  build) **spot-verifies at least 3 load-bearing sources per dossier** by
  an independent web search before trusting the dossier's own ✓ markers —
  never trust a research pass's self-reported verification without at
  least a spot check.
- The dossier commits to `library/research-dossiers/` as provenance —
  dated (`YYYY-MM-DD-topic.md`), raw input, and **explicitly not itself
  citable**: it carries the same "not citable" header every existing
  dossier in that directory carries. Cite `library/reference_list.md` and
  the eventual topic file, never the dossier.

## 3. Library build PR

From the dossier:

- **New/changed topic file** (or a new file, if the topic doesn't fit an
  existing one and the existing candidate is already near the 2,500-word
  cap). Every claim carries `[EVIDENCE: swim-ultra|swim|cycling]` or
  `[ADAPTED: cycling|running|tri|general-endurance]` (+ `Confidence:` +
  `Test:`), or is labeled `Coach judgment:`. The changed/new section is
  marked `**UNREVIEWED**` until a human clears it
  (`python -m swim_coach.cli review-accept`).
- **`reference_list.md` entries** — under a new `###` subsection in the
  appropriate existing `##` section. **Token-budget rule, important:**
  `reference_list.md` and `INDEX.md` are loaded into EVERY coach-chat
  turn's system prompt (`backend/app/context.py`'s `build_system_blocks`),
  so new entries must stay compact — one line each, no summary paragraph.
  The full summary lives in the topic file (loaded only when routed) and,
  at more length, in the dossier (never loaded into chat at all).
- **`INDEX.md`** — one row per new file (one sentence, ≤40 words) plus
  routing-table rows for the keywords a question about this topic would
  actually use.
- **`backend/app/context.py` routing** — mirror `INDEX.md`'s new routing
  rows as keyword-bucket entries (`_KEYWORD_ROUTES`,
  `_LIBRARY_FILES_IN_PRIORITY_ORDER`), test-first in
  `tests/api/test_context.py`. If the topic is sport-scoped (bike-only,
  etc.), also add it to `_LIBRARY_FILE_SPORT_SCOPE` — most topics (nutrition,
  general strength, return-from-layoff) are NOT sport-scoped and should be
  left unscoped so every athlete can reach them.
- Run `pytest tests/unit -q` (the library-discipline gate,
  `tests/unit/test_library_discipline.py`, mechanically enforces the tag/
  citation/word-count invariants above) and `pytest tests/api -q` before
  opening the PR.

## 4. Human review + merge

A human with domain judgment (Andrew, or a real coach) reviews the PR and
clears `UNREVIEWED` (`review-accept`) before treating the content as
grounding truth. **Never auto-merge, and never let an AI review stand in
for this** — an AI reviewing an AI's draft pattern-matches agreement, it
doesn't catch a bad inference. The PR is the sign-off record; the human
reviewer is the actual control.

## 5. Backend deploy

Merging to `main` is **not** enough by itself: `library/` ships baked into
the backend's Cloud Run image, so the live chat coach only sees new
content after a manual deploy dispatch —

```
gh workflow run deploy-backend.yml --ref main
```

Repo-side Claude Code skills (`/coach`, etc., run from a checkout) see the
merged file immediately; the deployed coach does not, until this runs.
Confirm the deploy actually went green before step 6 — see the standing
"backend deploy is manual" note; the green "Deploy" PR check is the PWA
frontend, a different, unrelated signal.

## 6. Close the loop — resolve the originating feedback row(s)

**Only after the deploy above**, not before — until then, the athlete-
facing coach can't actually see the answer, so marking the row resolved
would be a lie about what's live.

```
python -m swim_coach.cli research-queue-resolve <id> [<id> ...] \
  --library-file <answering-file.md> [--library-file <another-file.md>] \
  --note "short summary of the answer" \
  --pr <the-PR-number>
```

`resolve` validates that every `--library-file` actually exists under
`library/` before writing anything, and refuses to act on a row that isn't
an open `research_question` (already resolved, already dismissed, or a
different feedback type entirely) — it will not silently no-op or
overwrite a row someone else already closed out. Use `--dry-run` to check
a batch of ids before actually writing.

This is the step that stops the same question getting re-logged: once a
row is `status="resolved"` with `context.resolved_by` pointing at the
library file(s) and PR, the coach has real grounding to answer from next
time, instead of hitting the same gap and logging it again.

## What's still manual, honestly

Every step above is run by hand. The only automated piece is CI's library-
evidence gate (`tests/unit/test_library_discipline.py`), which blocks a PR
from merging with a fabricated-ID-shaped citation, a missing `Confidence:`/
`Test:`, an invalid tag value, a file over the word cap, or an unresolved
citation — it does not draft anything, trigger a research pass, or close
out feedback rows on its own. The weekly automated sweep job described in
`ROADMAP.md`'s "PROPOSED — feedback-triggered library research loop" step 2
— clustering open questions and drafting on a schedule rather than an
ad hoc human/agent decision to run a pass — is still not built.
