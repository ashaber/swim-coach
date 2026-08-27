# Wellness/HRV load integration: confirmation, contradiction, and what should trigger

**UNREVIEWED** — drafted this session from citations verified by direct web
search (see `reference_list.md`'s "Recovery, sleep & HRV" section additions,
not a research-dossier file); pending human review before treated as
grounding truth, per `00-conventions.md`. **Grounds nothing in the engine
yet.** No constant in `engine/swim_coach/adapt.py` or `load.py` currently
cites this file — that is deliberate; see the "Recommendation" section
below for exactly what a future build task would wire up and why it isn't
built tonight.

Andrew's question: `engine/swim_coach/load.py`'s `ctl_atl_tsb_series`
(sRPE-derived CTL/ATL/TSB) and `wellness_baseline_deviation` (RHR/HRV
acute-vs-chronic percent deviation) are intentionally independent signals,
shown side by side but never combined (see both functions' docstrings).
What does the literature actually support doing when they disagree?

## Finding 1 — multi-signal monitoring is well-supported; an algorithmic disagreement rule is not

**[ADAPTED: general-endurance/multi-sport] Confidence: high.** `Bourdon et
al. (2017)`'s multi-discipline consensus statement recommends combining
external load, internal subjective load, and internal objective
(physiological) measures as complementary signals — none a standalone gold
standard. It stops short of a numeric rule for what to do when they
disagree. **Test:** if a future rule is built from this file's
recommendation, check that it never treats `wellness_baseline_deviation`
as a superior override of the athlete's own subjective report — only as an
additional input, matching this consensus statement's framing.

**[ADAPTED: general-endurance/multi-sport] Confidence: medium-high.**
`Rebelo et al. (2026)` — the most current review found this session —
proposes a "Fatigue-Readiness-Adaptation continuum" and 2x2 "Monitoring
Quadrants" (load vs. well-being, load vs. neuromuscular performance,
performance vs. well-being) for *contextual* interpretation, explicitly
stating **no validated algorithmic rule exists in the literature** for
resolving disagreement between subjective and objective signals —
practitioner judgment is the field's actual current answer, not a formula.
It also cautions against proprietary composite scores through its own
"Minimal, Adequate, Accurate" framework — independently converging with
this library's existing exclusion of Oura's Readiness score
(`10-recovery-hrv.md`) from driving plan decisions. **Test:** whatever this
file recommends below should stay a flag/prompt, not an opaque score —
if a future contributor is ever tempted to blend `wellness_baseline_deviation`
into a single composite number with TSB, that's the same mistake this
project already declined to make with Oura's Readiness score.

## Finding 2 — is there a validated deviation-size threshold?

Yes, one specific rule exists, but for a different measurement protocol
than this app currently has real data for. **[ADAPTED: running/cycling]
Confidence: medium.** `Plews et al. (2013)` formalizes a
smallest-worthwhile-change (SWC) rule already in the same lineage as
`10-recovery-hrv.md`'s Kiviniemi/Vesterinen/Javaloyes trio: a 7-day rolling
average of ln(rMSSD), "normal" defined as that week's mean ± 0.5 SD; a day
below the lower bound signals easy/rest rather than hard. This is the most
specific numeric HRV-adjustment rule found this session — but it shares
the exact morning-orthostatic-protocol caveat `10-recovery-hrv.md` already
attaches to Kiviniemi/Vesterinen/Javaloyes (`Nuuttila et al. 2024`): none
of these thresholds have been validated on overnight/ring-style HRV, which
is what this app's `Wellness.hrv` field would actually receive from an
Oura ring. **Test:** once Renee's HRV history accumulates, check whether a
"below mean − 0.5 SD of a 7-day rolling average" rule flags meaningfully
different days than `wellness_baseline_deviation`'s current 28-day-chronic
design — if they diverge often, the SWC's shorter window may transfer
better to her data; if they agree, the added complexity isn't earning its
keep (same bar `10-recovery-hrv.md` already sets for its own HRV section).

A second, harder complication: **[ADAPTED: general-endurance] Confidence:
medium.** `Bellenger et al. (2016)`'s meta-analysis found resting HRV
**largely unaffected by overreaching in aggregate**, and — more
importantly — functional overreaching sometimes produced HRV *increases*
(parasympathetic hyperactivity), not decreases, with effect sizes
overlapping between athletes whose performance later improved (~0.58) and
worsened (~0.26). A single-direction "HRV down = bad" rule is not
consistently supported by this meta-analysis. **Test:** if
`wellness_baseline_deviation`'s current sign convention (negative
`hrv_pct_deviation` = concerning) is ever formalized into a trigger, treat
an unexpected *large positive* HRV deviation as worth a look too, not
automatically "good" — cross-reference against wellness_composite/RHR
before assuming direction.

`Bosquet et al. (2008)` and `Kamandulis et al. (2020)` — both already
cited in `10-recovery-hrv.md` — remain the load-bearing citations for *why*
`wellness_baseline_deviation` reports a trend-relative percentage against
the athlete's own rolling baseline rather than a raw single-day number;
nothing found this session changes that design. No source found this
session gives a validated consecutive-day count specifically for
*deviation magnitude* the way Kamandulis calibrates a volume-response
relationship (3-5 consecutive high-volume days -> ~4.5% HRV reduction) —
that is a real, standing gap, not a settled figure.

## Finding 3 — what does confirmation vs. contradiction actually mean?

**[ADAPTED: general-endurance] Confidence: medium.** `Halson (2014)`'s
"uncoupling" concept — internal/external load measures moving apart from
their usual relationship is itself diagnostic of a fatigue state neither
measure alone would show — is the closest the literature gets to defining
contradiction-as-signal, though it addresses a different pair
(submaximal-exercise HR vs. RPE), not `ctl_atl_tsb_series` (TSB) vs.
`wellness_baseline_deviation` directly. **Test:** if TSB and
`wellness_baseline_deviation` uncouple (TSB flat/rising while RHR/HRV
signal fatigue, or vice versa) more than a handful of times across a full
block, that is itself worth surfacing to the athlete as a pattern — per
Halson's framing — independent of which direction it points.

`Saw, Main & Gastin (2016)` (already cited, `10-recovery-hrv.md`) already
grounds treating subjective self-report as *more* sensitive than objective
measures, not less. Extended to this question: nothing found this session
argues the physiological signal should override a reassuring subjective
read on disagreement — if anything, the literature leans the other way.

Swim-specific data on the *fine-grained meaning* of agreement exists:
`[EVIDENCE: swim]` `Flatt, Esco & Nakamura (2018)` — 17 Division-1 sprint
swimmers — found LnRMSSD significantly tracked sleep/fatigue/stress/mood
in 15 of 17 athletes individually, but **muscle soreness showed no
association with HRV at all**. Practical takeaway: a "contradiction"
between a soreness complaint and normal HRV may not be a contradiction
worth flagging — these two things aren't expected to move together even
in a population where sleep/stress/mood do track HRV well.

`[EVIDENCE: swim]` `Flatt, Hornikel & Esco (2017)` and `Bulte et al.
(2025)` both found HRV tracking overload-vs-taper *phase* transitions in
competitive/elite swimmers (parasympathetic dominance early in taper,
rising sympathetic drive approaching competition) — directionally
consistent corroboration at the multi-week phase level, not a day-level
or week-level contradiction-detection design; neither paper tests a
disagreement-triggers-action rule.

**Practical synthesis for the three disagreement directions Andrew asked
about**, none independently validated as a combined rule (Coach judgment,
built from the findings above, not itself an `[EVIDENCE]`/`[ADAPTED]`
claim):
- **Both agree** (TSB declining and RHR/HRV signal fatigue): the clearest
  case; every source reviewed treats agreement as reinforcing, none
  disputes it.
- **sRPE/TSB fine, physiology fatigued:** the scenario `load.py`'s
  docstring already anticipates. Three explanations have real support —
  under-reporting or an sRPE-invisible stressor (`Saw et al. 2016`,
  `Rebelo et al. 2026`'s "athletes may under-report... fear repercussions"
  finding), a non-training stressor sRPE structurally cannot see
  (illness, life stress — `Halson 2014`, `Bourdon et al. 2017`), or simple
  noise (`Bellenger et al. 2016`'s inconsistent-direction finding, plus
  this library's own Oura data-quality caveats). No study distinguishes
  these three from the numbers alone.
- **sRPE/TSB fatigued, physiology fine:** the least-studied direction.
  `Saw et al. (2016)`'s core finding argues for trusting the subjective
  signal here, not overriding it with a reassuring physiological reading
  — but no source tested this specific direction as its own question.

## Finding 4 — swim-specific evidence, honestly scoped

Real swim-specific HRV literature exists and is cited above and in
`10-recovery-hrv.md` (`Kamandulis et al. 2020`, `Flatt, Esco & Nakamura
2018`, `Flatt, Hornikel & Esco 2017`, `Bulte et al. 2025`, `Collette et al.
2018`) — but none of it tests a "sRPE-TSB vs. HRV/RHR contradiction should
trigger X" rule, in swimming or any other sport. Existing swim-specific
work covers HRV's association with particular subjective sub-domains and
its tracking of macro training phases, not a day- or week-level
cross-check-and-adjust protocol. `Nicolas et al. (2016)` validates a
richer subjective instrument (RESTQ-Sport) in elite swimmers, unrelated to
HRV in that study — flagged here as a separate future angle for a richer
`wellness_composite`, not pursued further in this file.

## What is and isn't well-supported

**Is:** using `wellness_baseline_deviation` as a genuine independent
corroborating input, never a fallback or replacement (Bourdon, Halson, Saw,
Rebelo all converge here — this matches the existing docstring's own
framing already). **Is:** at least one concrete numeric HRV trigger exists
in the literature (Plews et al.'s 0.5-SD-of-7-day-rolling-mean), for a
morning-protocol population this app doesn't yet have. **Is:** proprietary
composite scores stay excluded — two independent, current sources (Doherty
et al. 2025, already cited; Rebelo et al. 2026, new) now agree on this.
**Isn't:** no validated numeric rule exists, anywhere in sport, for what a
*contradiction* specifically should trigger — every multi-signal source
recommends contextual judgment, not an algorithm. **Isn't:** no swim-specific
validation of any day-to-day HRV threshold as an adjustment trigger exists.
**Isn't, and worth stating plainly:** HRV's overreaching signature isn't
even reliably a decrease (Bellenger et al. 2016) — a future rule that
assumes "down is bad, up is fine" is building on a contested premise.

## Recommendation, not yet built

Given the honest state above, the specific, scoped proposal:

1. **Do not** make `wellness_baseline_deviation` change `adapt_week`'s
   `action` (the cut/repeat/hold/advance decision) the way `wellness_red`/
   `load_ratio_red` currently do. No study validates that override, and
   it would repeat the Oura-Readiness mistake this project already
   declined to make — an unvalidated cross-signal number silently
   outranking the athlete's own subjective report or the coach's judgment.

2. **Do** build, as a separate small future task, a purely informational
   flag in `adapt_week`'s existing `rationale["signals"]` dict (not the
   `action`/`rules_fired` decision path): `wellness_baseline_signal`,
   one of `"confirming" | "contradicting" | "insufficient-data"`. Compute
   it by comparing the trailing TSB trend (from `ctl_atl_tsb_series`,
   e.g. its direction over the last 7-14 days) against
   `wellness_baseline_deviation`'s existing fields, reusing the existing
   `WELLNESS_DEVIATION_CONCERNING_PCT = 5` threshold already defined in
   `web/src/plan.js` rather than inventing a new number: "confirming" =
   TSB declining and (RHR elevated ≥5% or HRV suppressed ≤-5%);
   "contradicting" = TSB flat-or-rising while RHR/HRV crosses that same
   ±5% bound (or the reverse); "insufficient-data" whenever either series
   lacks enough history, matching `wellness_baseline_deviation`'s own
   None-when-insufficient behavior.

3. When the contradiction is specifically **sRPE/TSB-fine,
   physiology-fatigued**, sustained ≥3 consecutive days (borrowing
   `Kamandulis et al. (2020)`'s swim-specific 3-5-day window since no
   better swim-specific number exists), surface it as an
   **athlete-facing question, not a plan edit**: ask directly whether
   something outside the training log is going on (illness, life stress,
   sleep debt, under-reported effort) — operationalizing Halson's and
   Rebelo's "investigate, don't auto-adjust" guidance.

4. **Do not** build the mirror-image rule (sRPE/TSB fatigued, physiology
   fine) at all. Per Finding 3, no literature addresses this direction,
   and `Saw et al. (2016)` argues for trusting the subjective signal
   regardless — `adapt.py`'s existing `wellness_red` cut rule already acts
   on that subjective signal at `WELLNESS_RED_THRESHOLD`. Adding a
   physiology-based override here would be built on an actively
   unsupported premise, not just an unproven one.

5. **Falsifiable test before graduating step 2 from "flag" to anything
   that touches `action`:** once `Wellness.hrv`/`resting_hr` accumulate
   real history for this athlete (they don't yet — profile lists an Oura
   ring, no HRV values logged, same gap `10-recovery-hrv.md` already
   documents), check how often the flag fires. Constant firing means the
   ±5%/3-day thresholds are miscalibrated for her; near-never firing means
   the added complexity isn't earning its keep — the same bar
   `10-recovery-hrv.md` already applies to its own HRV section.

The 5%/3-day numbers above are this file's own synthesis of adjacent
findings, not an independently validated combined rule — stated plainly,
per `00-conventions.md`, not dressed up as settled evidence.
