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
| `07-strength-dryland.md` | Dry-land shoulder-strengthening RCT evidence behind the 2x/week strength frequency (fuller home; `04` grounds only the frequency number); session duration, placement rule (pool-free weekdays, never weekend), the low-confidence run/bike strength-transfer adaptation, total-load caution when ramping strength alongside swim volume, the cut-week strength->recovery trade-off, and taper's (currently absent) strength handling. **UNREVIEWED**, pending human review. |
| `10-recovery-hrv.md` | Recovery-science support for `adapt.py`'s post-milestone recovery window and the `wellness_composite` subjective-primary-signal design; sleep as the highest-leverage lever; refeed-window carbohydrate/protein; CWI/compression comfort-vs-performance tiering; HRV-guided load-adjustment evidence, now amended for the morning-vs-overnight HRV protocol mismatch (Nuuttila et al. 2024); an Oura device-trust section rating per-signal confidence (RHR high, nightly rMSSD trend medium-high, sleep staging medium/low-medium, Readiness score low and excluded from driving plan changes); swim-specific sRPE-over-ACWR recovery monitoring (cross-refs `03`); a between-events mini-taper evidence base with the "no direct evidence for two ultra swims ~9 days apart" gap stated plainly. Human-reviewed. |
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
| Fueling, feeding intervals, carb targets | Not yet authored (`08`-tier "ultra feeding" file per ROADMAP.md's repo-structure sketch) — until it exists, cite `reference_list.md`'s "Swimming — physiology & nutrition" section directly (Martinez-Sanz 2024, Shaw 2014 IJSNEM review, Jeukendrup 2014, plus the newer Ivy 1988 / Burke 2011 / Koopman 2004 recovery-refeed entries) and mark any synthesized answer `Coach judgment` / `UNREVIEWED`. `10-recovery-hrv.md`'s nutrition section covers the recovery-window slice of this topic in the meantime. |
| Strength/dryland programming detail (beyond the 2x/week frequency) | `07-strength-dryland.md` (full programming detail: duration, placement, cut-week/taper handling); `04-css-intensity-anchors.md` cites only the frequency constant. |
| Recovery between two hard efforts a week or so apart / "how do I recover before my next race?" | `10-recovery-hrv.md` (sleep, refeed nutrition, modality tiering, mini-taper evidence + gap) |
| HRV / wellness-composite interpretation, "should I trust my Oura/HRV data or how I feel?" | `10-recovery-hrv.md` (HRV-guided-training section; Saw et al. 2016 grounds the existing subjective `wellness_composite`) |
| "How much should I trust my Oura HRV / readiness score?" | `10-recovery-hrv.md` ("Oura device trust" section — per-signal confidence for RHR/HRV/sleep staging/Readiness; Readiness explicitly should not drive plan changes) |
| Sleep guidance | `10-recovery-hrv.md` (sleep section) |
| Post-race / post-milestone-swim recovery, "how many easy days do I need?" | `06-long-swim-progression.md` (the `RECOVERY_DAYS_AFTER_MILESTONE_MIN/MAX` constant itself) + `10-recovery-hrv.md` (the recovery-science *why*) |
| Cold water immersion, compression, massage — "should I ice bath / wear compression?" | `10-recovery-hrv.md` (modality tier list) |
| Heat/cold acclimation, taper execution (full macro taper, not the between-events mini-taper), race-day pacing | Not yet authored (`08`, `09`, `11`, `12`-tier files per ROADMAP.md's repo-structure sketch). Until then: give coach judgment labeled as such, and offer to draft a new `UNREVIEWED` section rather than presenting an unsourced answer as settled. |
| Acute physical distress (chest pain, palpitations, fainting, heat-stroke/hypothermia signs) | **Not a library-routing question.** Stop and use the `/coach` skill's safety-first override — no file in this library should be consulted before that. |

## Known gaps (as of `10-recovery-hrv.md`)

Per ROADMAP.md's repo-structure sketch, topic files `01` (physiology),
`02` (polarized/80-20 training), `08` (ultra feeding), `09` (heat/cold
acclimation), `11` (taper — the full macro taper; `10`'s mini-taper section
covers only the between-events case), and `12` (race execution) are **not
yet authored**. `07` (strength/dryland) and `10` (recovery/HRV) were both
authored after Day 4; `07` remains `UNREVIEWED` pending human review, `10`
has now been human-reviewed (Oura device-trust pass, 2026-07-11). Day 4
authored only the files that ground existing engine constants (`00`,
`03`-`06`) per this build's scope; `07` and `10` each extend that to
constants/signals Day 4 didn't cover (strength frequency; the post-
milestone recovery window and `wellness_composite`, respectively).
`/coach` should say plainly when a question falls in one of the remaining
gaps rather than improvising a citation that doesn't exist yet.
