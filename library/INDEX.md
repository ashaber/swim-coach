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
| `14-swim-set-structure.md` | Session *composition* (warm-up/main-set/cool-down) for the "additional" pool-independent aerobic swim session, built on top of `04`'s CSS/zone system without changing it: proportions and main-set format menu are Coach judgment/convention; negative-split pacing cross-refs `04`'s existing evidence; a base->build/peak shift toward broken-distance/race-pace-adjacent work is `[EVIDENCE: swim]` (González-Ravé et al. 2021, Pla et al. 2019). Does not touch the Saturday long-swim session (`06`'s territory). **UNREVIEWED**, pending human review. |
| `15-tiered-session-load.md` | The tiered `session_load` fallback (sRPE > HR-based TRIMP > swim pace-IF > duration-only) fixing the confirmed bug where RPE-less workouts (62 of Renee's 63 real logged workouts) were silently excluded from every load total. Banister TRIMP formula/citation, HRmax/HRrest derivation and their honest confidence labels, the swim-specific cubed-IF TSS adaptation, the documented cross-tier scale-mismatch limitation (cross-refs `20-cross-train-load-standardization.md` for the per-modality-fallback question specifically), and the "AU" (arbitrary units) load-number naming convention. Split out of `03-periodization.md` to stay under its word-count cap. **UNREVIEWED**, pending human review. |
| `20-cross-train-load-standardization.md` | Whether tier 4's `DURATION_ONLY_ASSUMED_INTENSITY` duration-only load fallback should be split per activity type (e.g. a different assumed intensity for kayaking vs. walking) for cross-train workouts with neither RPE nor usable HR data. Research-first verdict: no rigorous, peer-reviewed, or widely-adopted standard exists for this specific zero-signal case, across three convergent checks (sRPE/TRIMP validity literature, missing-RPE imputation research in rugby, and real commercial platforms TrainingPeaks/Garmin-Firstbeat). The uniform constant stays a deliberate, documented simplification, not an oversight. **UNREVIEWED**, pending human review. |
| `16-race-week.md` | The final taper week's own, more prescriptive checklist layered on top of `03`'s taper block (never touching its volume math): the 36-72h pre-race carbohydrate-loading window (Burke et al. 2011; Bussau et al. 2002, no depletion phase needed), the 3-5-day-out bodywork/massage window (Weerapong, Hume & Kolt 2005; Dakić et al. 2023 — modest soreness/psychological benefit, practitioner-convention timing), and a generic, event-data-driven athlete logistics checklist (travel/acclimatization, fueling-plan rehearsal, support-crew confirmation). Gated on an active, priority-"A" event matching the macro. **UNREVIEWED**, pending human review. |
| `18-open-water-session-templates.md` | The open-water session-content template library (`ow_session_templates.py`): feed-window practice, negative-split pacing, chop/wind adaptation, sighting, breathing-pattern variation, back-to-back multi-day-stage fatigue simulation, taper activation, race dress rehearsal -- mostly Coach judgment (practitioner-convention session shapes, same category as `14`'s main-set menu), cross-referencing `08-ultra-feeding.md` (feeding rationale) and `06-long-swim-progression.md` (`multi_day_stage` back-to-back premise) rather than re-deriving evidence. Documents the `skill_scalable` vs `endurance_floor` duration-scaling design (Andrew's own applied-coaching insight: technique sessions compress fine under a taper, endurance/fueling sessions have a real minimum effective duration). Deliberately drops the source material's eyes-closed sighting drill as an avoidable safety risk. **REVIEWED**, pending human review. |
| `17-wellness-load-integration.md` | Whether/how the independent RHR/HRV baseline-deviation cross-check (`load.py`'s `wellness_baseline_deviation`) should confirm or trigger an adjustment against the sRPE-derived CTL/ATL/TSB model (`ctl_atl_tsb_series`) — currently shown side by side, never combined. Multi-signal monitoring is well-supported (Bourdon et al. 2017; Rebelo et al. 2026) but no validated algorithmic disagreement rule exists anywhere in the literature, swim-specific or not; one concrete HRV numeric trigger exists (Plews et al. 2013's 0.5-SD-of-7-day-rolling-mean) but for a morning protocol this app doesn't have data for yet, and HRV's overreaching signature isn't even reliably a decrease (Bellenger et al. 2016). Ends with a scoped, not-yet-built recommendation: an informational agreement/contradiction flag, never an `action`-changing override. **UNREVIEWED**, pending human review. |
| `19-srpe-protocol.md` | The Foster CR-10 modified-Borg session-RPE survey protocol (0-10 scale with verbal anchors, single global "how hard was your workout overall" question, ~30-min post-workout ask timing) behind `Workout.rpe`/`WorkoutDraft.rpe` -- the survey *instrument*, distinct from `15-tiered-session-load.md`'s load *formula* that consumes the resulting number. Foster et al. (2001), `[ADAPTED: general-endurance]`, confidence high, verified by direct web search. **REVIEWED**, pending human review. |
| `21-shoulder-health-and-load.md` | Extends `07-strength-dryland.md`'s injury-*prevention* shoulder program with the injury-*recovery* side: the shoulder-load/injury-risk relationship (cross-refs `07`'s existing ACWR citation), a criteria-based three-phase rehab progression (Desmeules et al. 2025 CPG), adjunct-modality evidence for massage and TENS (both genuinely conflicting -- Cochrane placebo-controlled null vs. smaller positive pooled studies), and swim-specific return-to-training criteria (Wilk et al. 2020) plus practitioner-convention volume/stroke/position adaptations. Triggered by a real acute shoulder injury this session; written as general grounding, not a one-athlete note. **REVIEWED**, pending human review. |
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
| "What's the structure of my additional/aerobic swim — warm-up, main set, cool-down?" | `14-swim-set-structure.md` (session composition on top of `04`'s zones; does not cover the Saturday long swim, see `06`) |
| "Is my training load too high / monotonous?" | `03-periodization.md` (monotony, ACWR + its criticized-methodology caveat) |
| "Why is my logged workout's load lower/higher than I expected?" / "why don't I have an RPE on this?" / HR-TRIMP or swim-pace load questions | `15-tiered-session-load.md` (the sRPE/HR-TRIMP/pace-IF/duration-only tiered fallback, and the cross-tier scale-mismatch caveat) |
| "What does the RPE number mean?" / "why does the scale go from 0, not 1?" / when should I answer the how-hard-was-that survey | `19-srpe-protocol.md` (the Foster CR-10 scale, verbal anchors, and ~30-min post-workout ask timing) |
| "Why does my kayak/bike/gym cross-train session get the same estimated load as any other cross-train session, regardless of how hard that specific activity actually is?" | `20-cross-train-load-standardization.md` (the no-RPE/no-HR per-modality-standardization question specifically; `15-tiered-session-load.md` for the tiered fallback itself) |
| "How am I doing on compliance / consistency?" | `03-periodization.md` (compliance definition + thresholds) |
| Fueling, feeding intervals, carb targets, the "wall at X minutes" question | `08-ultra-feeding.md` (in-session carbohydrate dose/gut-training, the 90-minute-wall hypotheses, post-swim rehydration) — cross-refs `13-reds-energy-availability.md` if acute fuelling fixes don't resolve a durability wall. `10-recovery-hrv.md`'s nutrition section still covers the post-exercise recovery-window slice specifically. |
| Hydration, sodium, cramping, "should I drink more?" | `08-ultra-feeding.md` (post-swim rehydration protocol + the exercise-associated-hyponatremia **safety rail** — read that section before ever telling an athlete to drink more). |
| Energy availability, RED-S, under-fueling, bone density, "am I eating enough?", appetite after cold swims | `13-reds-energy-availability.md` (chronic energy availability, the swimming-is-non-osteogenic finding, screening-instrument limits, what this system will and won't diagnose). |
| Strength/dryland programming detail (beyond the 2x/week frequency) | `07-strength-dryland.md` (full programming detail: duration, placement, cut-week/taper handling); `04-css-intensity-anchors.md` cites only the frequency constant. |
| A real shoulder injury, rehab phases, "should I get a massage/use TENS," or "when can I swim again?" | `21-shoulder-health-and-load.md` (rehab-phase structure, massage/TENS evidence, swim-specific return-to-training criteria and volume ramp-back) -- cross-refs `07-strength-dryland.md`'s prevention-focused exercise vocabulary and ACWR/shoulder-load citation. |
| Recovery between two hard efforts a week or so apart / "how do I recover before my next race?" | `10-recovery-hrv.md` (sleep, refeed nutrition, modality tiering, mini-taper evidence + gap) |
| HRV / wellness-composite interpretation, "should I trust my Oura/HRV data or how I feel?" | `10-recovery-hrv.md` (HRV-guided-training section; Saw et al. 2016 grounds the existing subjective `wellness_composite`) |
| "How much should I trust my Oura HRV / readiness score?" | `10-recovery-hrv.md` ("Oura device trust" section — per-signal confidence for RHR/HRV/sleep staging/Readiness; Readiness explicitly should not drive plan changes) |
| Sleep guidance | `10-recovery-hrv.md` (sleep section) |
| Post-race / post-milestone-swim recovery, "how many easy days do I need?" | `06-long-swim-progression.md` (the `RECOVERY_DAYS_AFTER_MILESTONE_MIN/MAX` constant itself) + `10-recovery-hrv.md` (the recovery-science *why*) |
| Cold water immersion, compression, massage — "should I ice bath / wear compression?" | `10-recovery-hrv.md` (modality tier list) |
| Race week: carb-loading timing, pre-race massage/bodywork timing, final-week travel/fueling-rehearsal/support-crew checklist | `16-race-week.md` (layered on `03`'s taper block's own last week; never changes its volume math) |
| "My HRV/RHR looks off but I feel fine (or vice versa) — does that matter?" / whether wellness/HRV should ever trigger a plan change, not just display alongside it | `17-wellness-load-integration.md` (confirmation vs. contradiction between sRPE-derived TSB and RHR/HRV baseline deviation; states plainly this doesn't drive any plan decision today, and what a future rule would need) |
| Heat/cold acclimation, taper execution (full macro taper, not the between-events mini-taper), race-day pacing | Not yet authored (`09`, `12`-tier files per ROADMAP.md's repo-structure sketch — `08` and `11` are no longer gaps, see above). Until then: give coach judgment labeled as such, and offer to draft a new `UNREVIEWED` section rather than presenting an unsourced answer as settled. |
| Acute physical distress (chest pain, palpitations, fainting, heat-stroke/hypothermia signs) | **Not a library-routing question.** Stop and use the `/coach` skill's safety-first override — no file in this library should be consulted before that. |
| Open-water session content — feed-window/fueling practice, negative splits, sighting, chop/wind, breathing-pattern drills, back-to-back stage-fatigue simulation, taper activation, race dress rehearsal; "why is this session just a bare distance number?" | `18-open-water-session-templates.md` (the `ow_session_templates.py` template library + the `skill_scalable`/`endurance_floor` duration-scaling design) |

## Known gaps (as of `13-reds-energy-availability.md`)

Per ROADMAP.md's repo-structure sketch, topic files `01` (physiology),
`02` (polarized/80-20 training), `09` (heat/cold acclimation), and `12`
(race execution / the full macro taper — `10`'s mini-taper section covers
only the between-events case) are **not yet authored**. `07`
(strength/dryland), `10` (recovery/HRV), `11` (workout analytics), `08`
(ultra feeding), `13` (RED-S/energy availability), `14` (swim set
structure), and `15` (tiered session load) have all been authored, each
grounding an existing engine constant or a logged athlete question rather
than speculatively covering ROADMAP's full sketch. `16` (race week) and `17` (wellness/HRV load integration) are
similarly ad hoc additions outside that original numbering sketch — `16`
is not the full `12`-tier "race execution / macro taper" topic, just the
final taper week's own carb-load/bodywork/logistics checklist; `17` is a
research-only answer to a specific developer question (does the RHR/HRV
baseline-deviation cross-check ever confirm or trigger a load adjustment)
and grounds no engine constant yet. `19` documents the Foster CR-10
session-RPE survey instrument itself (scale/anchors/ask-timing), distinct
from `15`'s load-formula focus. `20` (cross-train load standardization)
is similarly ad hoc — a research-only answer to a specific developer
question (should the duration-only load fallback be split per cross-train
activity type) that reached a negative verdict grounding the *absence* of a
new engine constant, not a new one. `21` extends `07`'s injury-prevention
shoulder work with the injury-recovery side (rehab phases, adjunct-modality
evidence, return-to-swim criteria), triggered by a real acute injury this
session but written as general grounding, not a one-athlete note. `10` is
human-reviewed (Oura device-trust pass, 2026-07-11); `07`, `11`, `08`, `13`,
`14`, `15`, `16`, `17`, `19`, `20`, and `21` remain `UNREVIEWED` pending
human review — `/coach` and future readers should treat their claims as
drafts, not settled grounding, until that review happens.
`/coach` should say plainly when a question falls in one of the remaining
gaps rather than improvising a citation that doesn't exist yet.
