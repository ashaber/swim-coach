# Adversarial review — cycling-training dossier and draft library file

> **This is a critique/review artifact, not additional research.** It
> reviews `library/research-dossiers/2026-09-07-cycling-training.md` (the
> verified-sources dossier) and `library/23-cycling-training.md` (the
> drafted, UNREVIEWED library file), plus the accompanying
> `reference_list.md`/`INDEX.md` additions, produced earlier this session
> on `engine/cycling-coach`. Written in the adversarial "red team" posture
> requested: assume the plan is wrong somewhere and find where, without
> manufacturing objections. No engine code or library content was changed
> to produce this review. `tests/unit/test_library_discipline.py`'s
> CI-gate checks were run against the new file and confirmed passing
> mechanically (word count, tag values, `Confidence`/`Test` completeness,
> citation resolution) — the objections below are about content and
> judgment, not mechanical gate violations.

VERDICT: sound with reservations

1. [medium] Clarsen et al. (2010)'s road-cyclist overuse-injury cohort is graded `Confidence: high` for an athlete who is primarily MTB + cyclocross, with no discipline-mismatch discount — even though this same file's own §"Discipline variants" establishes road and MTB as physiologically distinct populations and states injury *mechanism* differs by discipline (acute/upper-limb crash pattern vs. overuse/lower-limb pattern).
   Evidence: `library/23-cycling-training.md:151-162` ("Injury: patellofemoral pain and knee loading" — Clarsen et al., "elite, direct, cycling-specific cohort... **Confidence: high.**") vs. the same file's `:178-213` section arguing road ≠ MTB physiologically and citing Fallon et al.'s finding that acute vs. overuse injury are "genuinely different problems, not the same risk measured two ways." The file never states that Clarsen's overuse-mechanism findings (109 of 116 *professional road racers*, high sustained-cadence/low-impact loading) are a road-specific proxy for an MTB/CX rider's very different (intermittent, technical, impact-loaded per Protzen et al.) knee-loading pattern. Compare `03-periodization.md`'s own precedent of discounting confidence for exactly this kind of population mismatch (the Feijen et al. ACWR citation is explicitly downgraded because it's a youth, not adult, cohort).
   Consequence: a build/coach stage could present road-cyclist-derived knee-overuse framing to this athlete at the same confidence as directly-applicable evidence, when the actual applicability to MTB/CX loading patterns is unverified. The Bini/Priego-Quesada saddle-height mechanics (not discipline-specific) are less affected — the risk is specifically Clarsen's overuse-*mechanism* framing being read as MTB/CX-transferable.
   Suggested fix: add one caveat sentence noting Clarsen's cohort is road-specific and that MTB/cyclocross overuse-knee epidemiology wasn't found this pass (an honest gap, consistent with how §7 already handles the cyclocross injury gap) — discount to `medium-high` rather than `high` for this athlete's actual disciplines.

2. [medium-high] The `[ADAPTED: cycling]` tag-scheme workaround is honestly flagged in the file's own header, but nothing yet stops `/coach`'s existing convention from producing confusing output once this file is wired into live answers: `00-conventions.md` instructs `/coach` to phrase `[ADAPTED]` claims as "this is adapted from cycling... worth testing against your own data" — which reads as nonsensical when told to a cyclist about their own zones.
   Evidence: `library/23-cycling-training.md:9-24` (header caveat) and `library/00-conventions.md:94-96` ("this is adapted from cycling, medium confidence, worth testing against your own data" — the exact phrasing `/coach` is instructed to use for any `[ADAPTED]` tag, with no exception carved out for a claim that is mechanically-but-not-epistemically ADAPTED).
   Consequence: the first real cycling coaching answer this system gives Andrew risks sounding self-contradictory or eroding trust in the tagging discipline generally, exactly the failure mode `00-conventions.md` exists to prevent.
   Suggested fix: take a position rather than deferring further — before the BUILD stage wires this file into any live `/coach` answer for a cycling-configured athlete, extend `00-conventions.md`'s scheme with a real native-evidence value per discipline (e.g. `[EVIDENCE: cycling]`, matching IDEA 008's already-recorded direction), even if only a minimal version scoped to this file. Continuing to defer past a research-only pass is defensible; deferring past the point where `/coach` actually speaks this content to a user is not — the mismatch is no longer cosmetic once it reaches dialogue.

3. [medium] `INDEX.md` asserts a "hard requirement" that `23-cycling-training.md` must never ground answers for a swim-only athlete, but nothing enforces it: there is no `Athlete`-level configured-sport(s) field (checked `engine/swim_coach/models.py` — `Athlete` has no `sport`/`sports` field, only per-`Session`/`Workout` sport tags), and the constraint isn't even restated in `23-cycling-training.md`'s own header, only in `INDEX.md`'s routing-table row.
   Evidence: `library/INDEX.md`'s diff-added row ("**Guidance-scoping constraint (IDEA 008, hard requirement):** this file must only ground answers for an athlete whose own configured sport(s) include cycling — never surface cycling content to a swim-only athlete (Renee)") has no corresponding code, test, or model field; `library/23-cycling-training.md` itself never mentions this constraint.
   Consequence: a future context assembler that routes by keyword/topic match alone (rather than re-reading `INDEX.md`'s prose) has no structural signal to gate on — the trust problem IDEA 008 explicitly names could recur silently.
   Suggested fix: no obvious fix within a research-only pass's scope — but the BUILD stage should not treat this constraint as satisfied by documentation alone; it needs an `Athlete.sports`-shaped field and a routing check before it's real.

4. [low-medium] The Coggan %FTP zone boundaries have an unspecified gap at whole-number transitions: Z1 is `<55%`, Z2 is `56–75%` — leaving 55.0–55.99%FTP formally unclassified.
   Evidence: `library/23-cycling-training.md:31-33` ("Z1 Active Recovery <55%, Z2 Endurance 56–75%, Z3 Tempo 76–90%, Z4 Lactate Threshold 91–105%...") — same pattern repeats at every zone boundary (75/76, 90/91, 105/106, 120/121, 150).
   Consequence: a builder writing `zones.py`'s boundary logic (the next stage's stated purpose for this file) has to silently guess how to close the gap, which is exactly the class of off-by-one ambiguity this project has been bitten by before (cf. `06-long-swim-progression.md`'s documented pool-session-floor edge case, found via real dogfooding).
   Suggested fix: one line specifying the intended boundary convention (e.g. "boundaries are inclusive on the upper end: Z1 ≤55%, Z2 56–75%") — the underlying source table's own ambiguity, so this doesn't need new research, just an explicit engineering decision recorded here rather than left to the build stage to invent unreviewed.

5. [low] Structural inconsistency against this project's established topic-file pattern: `23-cycling-training.md`'s header doesn't include the standard "See `00-conventions.md` for the tagging scheme and `reference_list.md` for full citations" line every other reviewed topic file opens with (`03-periodization.md:5-6`, `06-long-swim-progression.md:6-7`, `07-strength-dryland.md:6-7`).
   Evidence: `library/23-cycling-training.md:1-24`'s header covers the tagging-mechanism caveat at length but never names `00-conventions.md` or `reference_list.md` directly in the boilerplate way peer files do.
   Consequence: purely cosmetic — no functional gap, since the tag mechanism itself is explained in more detail than usual — but it's a tell that this file was drafted somewhat outside the normal template, worth tightening before human review sign-off.
   Suggested fix: add the one-line boilerplate cross-reference alongside the existing (good, more thorough) tagging-mechanism caveat.

FRAGILE: the two places this will break first if not caught now: (1) objection 1 — the moment this athlete reports real knee/overuse discomfort on the MTB or in cyclocross and the coach reaches for Clarsen's road-cohort framing at "high" confidence, since that's the first place research-population mismatch turns into a concrete wrong-feeling answer rather than an abstract tagging gap; (2) objection 2 — the first time `/coach` actually answers a cycling question aloud using this file's `[ADAPTED: cycling]` claims verbatim per `00-conventions.md`'s own phrasing instruction, which will visibly sound wrong to a cyclist being told his own sport's evidence is "adapted from cycling."

---

## What held up well (for balance, not padding the objection count)

- **Citation-to-claim fidelity is clean.** Every `[ADAPTED: cycling]`-tagged
  number checked against the dossier (Coggan zone percentages, the NP/IF/TSS
  formula steps, the Galán-Rioja h/week ranges, the Clarsen 45%/23% injury
  split, the Bini 5%/35%/16% figures, the Fallon per-365-day incidence
  numbers) reproduces the dossier's numbers exactly — no drift, no
  overclaim beyond what the dossier itself supports.
- **The two adjacent-field-caution sources are handled correctly.** Marchal
  et al. (2025) is explicitly labeled "**not a cycling population**... general
  model-class caution, not direct cycling counter-evidence" and tagged
  `[ADAPTED: general-endurance]` at `Confidence: low-medium` — it is not
  silently presented as cycling-native evidence. Vermeire et al. (2022) is
  likewise kept at `[ADAPTED: general-endurance]`, cited only for
  methodological caution about the fitness-fatigue model class, not as a
  cycling-specific finding.
- **The cyclocross injury paper's preliminary status is honestly carried
  through.** `23-cycling-training.md` calls Fallon, Fischer & Heron (2025)
  "Self-described 'preliminary,' single event, not yet replicated" and grades
  it `Confidence: low-medium` — the confidence language matches the
  source's own hedging rather than rounding it up.
- **The rejected predatory-venue source (Carmichael et al. 2017) is handled
  exactly per this project's existing precedent** (the Smith & Thomas/
  Hilaris demotion) — flagged, not cited, recorded so a future pass doesn't
  re-discover and re-verify it blind.
- **The honest no-citable-source outcome (cycling-specific volume-progression
  rate) is a real negative result, not papered over** — consistent with this
  project's stated norm that an honest gap is acceptable output.
- **The CI gate mechanically passes** (`pytest tests/unit/test_library_discipline.py -k "23-cycling"`,
  6/6 green): word count, allowed tag/confidence values, `Confidence`+`Test`
  completeness on every `[ADAPTED]` block, and citation resolution to
  `reference_list.md` all hold.
