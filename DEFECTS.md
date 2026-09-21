# Defects — swim-coach

Tracked defects to address opportunistically. Format: `D<n> — title (where found)`.

## Open

**D2** — No plan weeks exist past 2026-W29 for any athlete (reported 2026-08-18: "the Plan tab only shows July").
  - **Root cause:** a *data* gap, not a rendering one. `andrew` has a single week on file (`2026-W29`, Jul 13–19), `renee` has `2026-W28`/`2026-W29`, `tim` has none. Nothing was generated for W30 onward while the wall clock reached W34. The deployed backend serves from Supabase (`STORE_BACKEND=db`), not this repo's `athletes/` tree, so the live gap is in the DB — backfilling the repo tree would not change what the athlete sees.
  - **Masking bug (FIXED, see below):** `pickCurrentAndNextWeek` used to fall back to the last two weeks when every week had elapsed, so the stale W29 rendered under a "This week" heading and hid the gap entirely.
  - **Remaining work (needs Andrew / the athlete):** regenerate the current weeks against the prod DB — `/adapt` in the app, or `cli plan-week --database-url …`. Naive macro-derived regeneration is *not* safe to apply unreviewed: after the five-week gap it produces `andrew` 8,990 → 12,682 m (+41%) and `renee` 17,500 → 26,659 m (+52%) week-over-week, both far past the standing "+≤8% weekly volume without explicit athlete confirmation" rail. Run `/adapt` against the real synced logs instead of `plan-week` off the macro scaffold.

**D3** — The week generator emits exactly ONE hard bike session per week, so a plan with two interval days cannot be generated (reported 2026-09-20; Andrew's real next-week plan).
  - **Evidence:** asked for Mon skills+yoga / Tue intervals+strength / Wed group ride / Thu off / Fri yoga / Sat intervals+strength / Sun group ride, the generator (with the closest expressible `training_days`) produced 7 of 9 sessions, and **Saturday came out as a Z2 endurance ride**. Root cause: `plan._bike_week_sessions` marks only `i == 0` as hard (`is_hard = n > 1 and i == 0`). The realism guardrail is NOT the blocker (`BIKE_MAX_HARD_DAYS_PER_WEEK = 3`); this is a structural generator limit, so every second interval day, or any session outside the fixed 3-bike + 2-strength shape, has to be hand-authored via `session_overrides` -- the source of the multi-iteration failures catalogued in IDEA 024.
  - **Impact:** Andrew was forced to build the plan in Tim's tool.

**D4** — No yoga / mobility session type; `Session.sport` is only `swim_pool | swim_ow | strength | recovery | cross_train | bike` (2026-09-20).
  - Yoga sessions can only be hand-authored as `recovery`/`cross_train` overrides, with no generator support and no library backing. Adding yoga to a week through `replace_week_plan` dropped four sessions including a race day (IDEA 024 #1).

**D5** — `set_schedule_preferences` (PR #218) re-implemented the single-hard-day limit instead of removing it (2026-09-20).
  - The tool rejects `"give only one hard day"`, so Andrew's Tue + Sat interval days could not even be STATED, let alone honored. The engine cannot generate them either (D3), so the tool was honest but useless for this plan. Pattern to stop repeating: a structural limit is not a safety rail -- see IDEA 023 v3 (weekly template) for the fix; safety rails (ramp cap) must warn and require explicit confirmation, never silently block or silently cap the structure.

**D6** — `confirm` REGENERATED the plan instead of writing the agreed one (found 2026-09-21; Andrew: "what is causing it to corrupt?... plan creates plan; let the coach write it once agreed").
  - **Root cause:** no draft was ever stored. `replace_week_plan` re-ran `generate_week` on the confirm call and saved that result; `patch_week_plan` re-applied whatever overrides arrived with the confirm to whatever was live at that moment. The plan the athlete agreed to and the plan written were two independent computations, so any change in between (a template edit, different/re-typed overrides, a shifted interval rotation) silently changed the saved week -- the "reverts to a prior iteration" symptom.
  - **Fix:** PR #222 -- drafts are held under a hidden key and `confirm` + `draft_id` writes exactly that draft (risk flagged, never blocking). `merge_week_plan`, `propose_adaptation`, `propose_session_adjustment` still have their own re-computing confirm paths (open).

**D7** — A modify-mode session override could not set the zone/intensity, so relabelling a session as intervals left the zone tag at Z2 and fooled the realism guardrail (coach-reported defect #4, silent partial-apply; reproduced 2026-09-21). Fixed in #220: modify mode accepts `intensity`, and a purpose that says hard work over an unchanged Z1/Z2 tag is flagged.

**D8** — `structure` without `distance_m` was a hard ERROR (coach-reported defect #3). Now applied and flagged for swim sessions (where distance is a real stat), no requirement for others (#220). Still open from that report: nested repeat-inside-repeat is rejected; setting `structure` without `structured` clears the structured data.

**D9** — Macro coverage undiscoverable before a week call fails (coach-reported #6). `get_plan_summary` now returns `macro_coverage` and the out-of-range error names the covered range and how to extend it (#220).

## Fixed

**D2a** — The Plan tab labelled an already-elapsed week "This week" (found while diagnosing D2 above).
  - **Root cause:** `web/src/plan.js`'s `pickCurrentAndNextWeek` fell back to `Math.max(0, sorted.length - 2)` when no week's Sunday was still in the future — silently presenting the newest stale week as the current one, so a five-week-old prescription looked live.
  - **Fix:** returns `{ current: null, next: null, stale: true }` instead; `renderWeeksSection` words the two empty states differently ("no plan generated for this week yet" vs "no weeks planned yet"), and a collapsed all-weeks `<details>` accordion makes the whole plan browsable rather than only current+next. Branch `phase4/plan-week-display`.

**D1** — Chat backend 400 when the research-logging path fires mid-conversation: `messages.N.content.1.text.parsed_output: Extra inputs are not permitted`.
  - Instance 1 (2026-07-06): `messages.5…` — after a fueling-during-swim follow-up ("fueled during swim but not sure how much…").
  - Instance 2 (2026-07-07): `messages.8…` — after "Did you note the headwind on return? Is there data for effects of headwind in open water swimming?" during a fueling/nutrition discussion. Different index, same shape.
  - **Root cause:** the tool-use loop (`backend/app/claude.py`) replayed the assistant turn via `block.model_dump()`, which serialized the SDK's null `parsed_output`/`citations` fields on text blocks; the API rejects those as *input* on the follow-up request. Only fires when the turn contains a tool call (e.g. `log_open_question`), so the turn has to be replayed — hence "whenever research-logging triggers," at whatever message index the tool call lands.
  - **Fix:** `model_dump(exclude_none=True)` drops the null SDK-only fields while preserving text/tool_use/thinking blocks. Regression test `test_replayed_assistant_content_drops_sdk_only_null_fields`; the API fakes now carry `parsed_output` like the real SDK so the fix is actually exercised. Branch `phase2.5/d1-parsed-output-toolloop`.
