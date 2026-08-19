# Defects — swim-coach

Tracked defects to address opportunistically. Format: `D<n> — title (where found)`.

## Open

**D2** — No plan weeks exist past 2026-W29 for any athlete (reported 2026-08-18: "the Plan tab only shows July").
  - **Root cause:** a *data* gap, not a rendering one. `andrew` has a single week on file (`2026-W29`, Jul 13–19), `renee` has `2026-W28`/`2026-W29`, `tim` has none. Nothing was generated for W30 onward while the wall clock reached W34. The deployed backend serves from Supabase (`STORE_BACKEND=db`), not this repo's `athletes/` tree, so the live gap is in the DB — backfilling the repo tree would not change what the athlete sees.
  - **Masking bug (FIXED, see below):** `pickCurrentAndNextWeek` used to fall back to the last two weeks when every week had elapsed, so the stale W29 rendered under a "This week" heading and hid the gap entirely.
  - **Remaining work (needs Andrew / the athlete):** regenerate the current weeks against the prod DB — `/adapt` in the app, or `cli plan-week --database-url …`. Naive macro-derived regeneration is *not* safe to apply unreviewed: after the five-week gap it produces `andrew` 8,990 → 12,682 m (+41%) and `renee` 17,500 → 26,659 m (+52%) week-over-week, both far past the standing "+≤8% weekly volume without explicit athlete confirmation" rail. Run `/adapt` against the real synced logs instead of `plan-week` off the macro scaffold.

## Fixed

**D2a** — The Plan tab labelled an already-elapsed week "This week" (found while diagnosing D2 above).
  - **Root cause:** `web/src/plan.js`'s `pickCurrentAndNextWeek` fell back to `Math.max(0, sorted.length - 2)` when no week's Sunday was still in the future — silently presenting the newest stale week as the current one, so a five-week-old prescription looked live.
  - **Fix:** returns `{ current: null, next: null, stale: true }` instead; `renderWeeksSection` words the two empty states differently ("no plan generated for this week yet" vs "no weeks planned yet"), and a collapsed all-weeks `<details>` accordion makes the whole plan browsable rather than only current+next. Branch `phase4/plan-week-display`.

**D1** — Chat backend 400 when the research-logging path fires mid-conversation: `messages.N.content.1.text.parsed_output: Extra inputs are not permitted`.
  - Instance 1 (2026-07-06): `messages.5…` — after a fueling-during-swim follow-up ("fueled during swim but not sure how much…").
  - Instance 2 (2026-07-07): `messages.8…` — after "Did you note the headwind on return? Is there data for effects of headwind in open water swimming?" during a fueling/nutrition discussion. Different index, same shape.
  - **Root cause:** the tool-use loop (`backend/app/claude.py`) replayed the assistant turn via `block.model_dump()`, which serialized the SDK's null `parsed_output`/`citations` fields on text blocks; the API rejects those as *input* on the follow-up request. Only fires when the turn contains a tool call (e.g. `log_open_question`), so the turn has to be replayed — hence "whenever research-logging triggers," at whatever message index the tool call lands.
  - **Fix:** `model_dump(exclude_none=True)` drops the null SDK-only fields while preserving text/tool_use/thinking blocks. Regression test `test_replayed_assistant_content_drops_sdk_only_null_fields`; the API fakes now carry `parsed_output` like the real SDK so the fix is actually exercised. Branch `phase2.5/d1-parsed-output-toolloop`.
