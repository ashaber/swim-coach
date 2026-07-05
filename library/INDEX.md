# Library index

One-line summary per file, plus a topic -> file routing table for `/coach`
and (per ROADMAP.md) Phase 2's chat context assembler: route a question to
2-4 files here, always load `reference_list.md` alongside for citations, and
load `00-conventions.md` once per session to know how to read the tags.

## Files

| File | Summary |
|---|---|
| `00-conventions.md` | The evidence-tag scheme (`[EVIDENCE]` / `[ADAPTED]` + `Confidence:` + `Test:` / `Coach judgment:`) and the rule that `reference_list.md` is the only trustworthy citation source. Read once per session. |
| `03-periodization.md` | Macro block structure (base/build/peak/taper), the taper citation-debt flag, the +8%/week ramp-cap safety rail, and load monitoring (sRPE, monotony, ACWR + its caveats, wellness composite, compliance, the cut/repeat/hold/advance thresholds, and the informational-only 80/20 note). |
| `04-css-intensity-anchors.md` | CSS derivation (Wakayoshi et al. 1992) and the Z1-Z5 zone-offset table; negative-split pacing evidence; dry-land strength frequency. |
| `05-open-water-pace-inference.md` | Why open-water pace needs correcting from pool CSS, and the (all-provisional, athlete-calibration-pending) wetsuit/conditions/cold-water correction constants. |
| `06-long-swim-progression.md` | The Garmin-RunSafe single-session-spike evidence underpinning the long-swim ladder; the `single_day` escalating-ladder format (peak share, step cap, milestone recovery) vs. the `multi_day_stage` back-to-back-weekend format (longest-day cap); pool-placeholder sizing. |
| `reference_list.md` | **The canonical citation source.** Every claim in every file above resolves to an entry here (title + author + year), never a URL/ID — see its own header for why. |
| `sample_pool_workout_traditional.md` | A real logged pool-coach workout sample (traditional/technique-focused notation) — reference material for `/log-workout`'s coach-text parser, not a research citation. |
| `sample_pool_workout_openwater_focus.md` | A real logged pool-coach workout sample (open-water-focused notation) — same purpose as above. |

## Topic -> file routing table

| Athlete/coach question about... | Route to |
|---|---|
| "Why is this week's volume/long-swim what it is?" | `03-periodization.md` (macro block, ramp cap) + `06-long-swim-progression.md` (long-swim ladder specifics) |
| "Why did the plan get cut / repeat / advance this week?" | `03-periodization.md` (load-monitoring thresholds, cut/repeat/advance rules) |
| "What pace should I swim the long set at?" / zone questions | `04-css-intensity-anchors.md` |
| "What pace should I expect in open water / with a wetsuit / in chop?" | `05-open-water-pace-inference.md` |
| "How big should my next long swim be?" / milestone/recovery questions | `06-long-swim-progression.md` |
| "Should I do the single-day swim or the stage option?" | `06-long-swim-progression.md` (format switch section) |
| "Is my training load too high / monotonous?" | `03-periodization.md` (monotony, ACWR + its criticized-methodology caveat) |
| "How am I doing on compliance / consistency?" | `03-periodization.md` (compliance definition + thresholds) |
| Fueling, feeding intervals, carb targets | Not yet authored (`07`-tier "ultra feeding" file per ROADMAP.md's repo-structure sketch) — until it exists, cite `reference_list.md`'s "Swimming — physiology & nutrition" section directly (Martinez-Sanz 2024, Shaw 2014 IJSNEM review, Jeukendrup 2014) and mark any synthesized answer `Coach judgment` / `UNREVIEWED`. |
| Strength/dryland programming detail (beyond the 2x/week frequency) | `04-css-intensity-anchors.md` cites the frequency; full programming detail is not yet authored (`07`-tier "strength" file per ROADMAP.md). |
| Heat/cold acclimation, HRV/recovery interpretation, taper execution, race-day pacing | Not yet authored (`08`-`11`-tier files per ROADMAP.md's repo-structure sketch). Until then: give coach judgment labeled as such, and offer to draft a new `UNREVIEWED` section rather than presenting an unsourced answer as settled. |
| Acute physical distress (chest pain, palpitations, fainting, heat-stroke/hypothermia signs) | **Not a library-routing question.** Stop and use the `/coach` skill's safety-first override — no file in this library should be consulted before that. |

## Known gaps (as of Day 4)

Per ROADMAP.md's repo-structure sketch, topic files `01` (physiology),
`02` (polarized/80-20 training), and `07`-`12` (strength, ultra feeding,
heat/cold, recovery/HRV, taper, race execution) are **not yet authored**.
Day 4 authored only the files that ground existing engine constants (`00`,
`03`-`06`) per this build's scope. `/coach` should say plainly when a
question falls in one of these gaps rather than improvising a citation that
doesn't exist yet.
