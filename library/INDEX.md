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
| `08-ultra-feeding.md` | The 90-minute "my body is done" wall (why it isn't a plausible muscle-glycogen wall, the liver-glycogen/blood-glucose and habituated-pacing-ceiling alternatives, and why "carbs fixed it" doesn't prove glycogen — the mouth-rinse confound); in-session carbohydrate dose/gut-training; post-swim rehydration; a **safety rail on exercise-associated hyponatremia (EAH)** covering the athlete's reported low-urine-output pattern. Cross-refs `13-reds-energy-availability.md` (chronic under-fuelling as a false-dichotomy resolver for the wall) and `06-long-swim-progression.md` (duration progression). **UNREVIEWED**, pending human review. |
| `10-recovery-hrv.md` | Recovery-science support for `adapt.py`'s post-milestone recovery window and the `wellness_composite` subjective-primary-signal design; sleep as the highest-leverage lever; refeed-window carbohydrate/protein; CWI/compression comfort-vs-performance tiering; HRV-guided load-adjustment evidence, now amended for the morning-vs-overnight HRV protocol mismatch (Nuuttila et al. 2024); an Oura device-trust section rating per-signal confidence (RHR high, nightly rMSSD trend medium-high, sleep staging medium/low-medium, Readiness score low and excluded from driving plan changes); swim-specific sRPE-over-ACWR recovery monitoring (cross-refs `03`); a between-events mini-taper evidence base with the "no direct evidence for two ultra swims ~9 days apart" gap stated plainly. Human-reviewed. |
| `11-workout-analytics.md` | Provisional (Slice-1 stub) thresholds behind `analytics.py`'s cardiac-drift, split-evenness, pause/gap, and SWOLF constants; general-endurance-adapted, low-to-medium confidence throughout, pending a full research pass. |
| `13-reds-energy-availability.md` | Chronic energy availability / RED-S: why the "30 kcal/kg FFM" threshold isn't a settled clinical number, why chronic low energy availability (LEA) is a plausible upstream cause of `08`'s 90-minute wall that acute fuelling alone won't fix, why swimming is non-osteogenic (the one clear swim-specific, actionable finding, cross-refs `07-strength-dryland.md`), why no validated LEA screening exists for a post-menopausal athlete, and an HRV/RHR interpretation confound cross-refed into `10-recovery-hrv.md`. States plainly that diagnosis/treatment/bone density are physician/dietitian territory. **UNREVIEWED**, pending human review. |
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
| Fueling, feeding intervals, carb targets, the "wall at X minutes" question | `08-ultra-feeding.md` (in-session carbohydrate dose/gut-training, the 90-minute-wall hypotheses, post-swim rehydration) — cross-refs `13-reds-energy-availability.md` if acute fuelling fixes don't resolve a durability wall. `10-recovery-hrv.md`'s nutrition section still covers the post-exercise recovery-window slice specifically. |
| Hydration, sodium, cramping, "should I drink more?" | `08-ultra-feeding.md` (post-swim rehydration protocol + the exercise-associated-hyponatremia **safety rail** — read that section before ever telling an athlete to drink more). |
| Energy availability, RED-S, under-fueling, bone density, "am I eating enough?", appetite after cold swims | `13-reds-energy-availability.md` (chronic energy availability, the swimming-is-non-osteogenic finding, screening-instrument limits, what this system will and won't diagnose). |
| Strength/dryland programming detail (beyond the 2x/week frequency) | `07-strength-dryland.md` (full programming detail: duration, placement, cut-week/taper handling); `04-css-intensity-anchors.md` cites only the frequency constant. |
| Recovery between two hard efforts a week or so apart / "how do I recover before my next race?" | `10-recovery-hrv.md` (sleep, refeed nutrition, modality tiering, mini-taper evidence + gap) |
| HRV / wellness-composite interpretation, "should I trust my Oura/HRV data or how I feel?" | `10-recovery-hrv.md` (HRV-guided-training section; Saw et al. 2016 grounds the existing subjective `wellness_composite`) |
| "How much should I trust my Oura HRV / readiness score?" | `10-recovery-hrv.md` ("Oura device trust" section — per-signal confidence for RHR/HRV/sleep staging/Readiness; Readiness explicitly should not drive plan changes) |
| Sleep guidance | `10-recovery-hrv.md` (sleep section) |
| Post-race / post-milestone-swim recovery, "how many easy days do I need?" | `06-long-swim-progression.md` (the `RECOVERY_DAYS_AFTER_MILESTONE_MIN/MAX` constant itself) + `10-recovery-hrv.md` (the recovery-science *why*) |
| Cold water immersion, compression, massage — "should I ice bath / wear compression?" | `10-recovery-hrv.md` (modality tier list) |
| Heat/cold acclimation, taper execution (full macro taper, not the between-events mini-taper), race-day pacing | Not yet authored (`09`, `12`-tier files per ROADMAP.md's repo-structure sketch — `08` and `11` are no longer gaps, see above). Until then: give coach judgment labeled as such, and offer to draft a new `UNREVIEWED` section rather than presenting an unsourced answer as settled. |
| Acute physical distress (chest pain, palpitations, fainting, heat-stroke/hypothermia signs) | **Not a library-routing question.** Stop and use the `/coach` skill's safety-first override — no file in this library should be consulted before that. |

## Known gaps (as of `13-reds-energy-availability.md`)

Per ROADMAP.md's repo-structure sketch, topic files `01` (physiology),
`02` (polarized/80-20 training), `09` (heat/cold acclimation), and `12`
(race execution / the full macro taper — `10`'s mini-taper section covers
only the between-events case) are **not yet authored**. `07`
(strength/dryland), `10` (recovery/HRV), `11` (workout analytics), `08`
(ultra feeding) and `13` (RED-S/energy availability) have all been
authored, each grounding an existing engine constant or a logged athlete
question rather than speculatively covering ROADMAP's full sketch. `10` is
human-reviewed (Oura device-trust pass, 2026-07-11); `07`, `11`, `08` and
`13` remain `UNREVIEWED` pending human review — `/coach` and future readers
should treat their claims as drafts, not settled grounding, until that
review happens.
`/coach` should say plainly when a question falls in one of the remaining
gaps rather than improvising a citation that doesn't exist yet.
