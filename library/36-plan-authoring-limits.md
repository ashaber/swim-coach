# Plan-authoring limits: the evidence (and honest lack of it) behind `plan_check.py`

See `00-conventions.md` for the tagging scheme and `reference_list.md` for
full citations. Grounds `engine/swim_coach/plan_check.py`'s red-team
constants (engine/plan-check-red-team PR 3, 2026-09-27) — the numbers that
decide what `check_macro`/`check_week` flag in a coach-authored plan.
Source: `library/research-dossiers/2026-09-27-planning-limits.md` (a
Sonnet source-verification pass), corrected by that dossier's own
orchestrator addendum on the swim-taper question (Q4 — see below).

**UNREVIEWED**, pending human review.

Five gaps, in the order `plan_check.py`'s constants need them: masters
ramp/recovery cadence, realistic progression rates, age-related decline,
swim taper length, and time-feasibility margin.

## Masters ramp and recovery-week cadence

**Coach judgment: no ramp-RATE or recovery-cadence evidence exists for
masters athletes specifically.** Searched directly (coaching-blog sources
converge on 2:1 replacing 3:1 past ~40-55) — no study tests 3:1 vs 2:1
cadence, or a masters-specific %-ramp cap, in a real cohort. This is the
same honest gap the prior season-taper dossier already found for the
general-population 3:1 cadence.

What real evidence exists cuts the other way from the popular assumption.
**`[ADAPTED: general-endurance] Confidence: low-medium.`** `Hottenrott et
al. (2022)` (12 younger vs. 12 older well-trained cyclists/triathletes)
found recovery kinetics after HIIT did **not** differ by age group in
already-well-trained masters — a real counter to "masters always need much
more recovery." Set against that, `Reaburn et al. (2019)`
(conference-abstract tier, not full peer-review) found masters athletes
recovered more slowly than training-matched younger athletes after
muscle-damage protocols — the mixed picture likely tracks damage type
(eccentric/muscle-damage vs. steady HIIT-recovery), not a single verdict.
**Test:** if this athlete's own logged HRV/RPE trend doesn't show a real
lag after hard sessions, don't apply an age-alone recovery penalty on top
of the cadence default below — treat any real slowdown as an individual
finding.

**`[ADAPTED: general-endurance] Confidence: medium.`** `Burtscher et al.
(2022)` (reviewed, grounds `35` already) found VO2max decline in masters
tracks **training-volume changes** (>50% of variance) far more than age
itself — the grounds for "don't cut volume just because the athlete is
aging," but it doesn't test ramp-rate tolerance either.

**Working position, Coach judgment, low confidence:** keep the general
`WEEKLY_VOLUME_RAMP_CAP`/`CTL_RAMP_CAP_PER_WEEK` numbers as ceilings, not
targets, and shift recovery-week cadence toward **2:1** for a masters-age
athlete (`RECOVERY_CADENCE_WEEKS_MASTERS_OR_INJURY = 2`) — a defensible
default given Burtscher's volume-matters finding and the mixed
recovery-speed picture above, not itself a ramp-rate trial result.
**Test:** if this athlete's compliance/volume stays consistent across a
recovery-week change, that's a real signal the cadence choice is working
for her specifically, not just a population default.

## Realistic progression rates: diminishing returns, no numeric ceiling

**No numeric W/kg (or CTL/FTP-%) ceiling is evidence-backed for a trained
masters athlete — the qualitative shape is, and that's what
`plan_check.py`'s goal-reality check should actually assert.**

`[ADAPTED: general-endurance] Confidence: high.` `Bacon et al. (2013)`
(VO2max-trainability meta-analysis): large gains are an
**untrained-population** phenomenon; gains shrink sharply as training age
rises, and ~10-20% of individuals show negligible response even under
supervised training. **Test:** if a plan's implied per-block gain looks
closer to an untrained-population figure than the modest range below,
that's the plan overreaching, not this athlete underperforming.
`[EVIDENCE: cycling]` `Cove et al. (2024)` (41 studies, 797 trained
cyclists): training
**duration** (weeks in a block) predicts improvement; weekly/total volume
does not, past a threshold — more hours doesn't buy more adaptation once an
athlete is already trained. Concrete, on-population, high confidence: a
trained masters cyclist should expect **modest (small-to-medium effect,
roughly single-digit-to-low-teens %) gains per structured block**, not
large jumps, and extending block duration beats adding weekly hours.

`[ADAPTED: cycling] Confidence: medium.` `Valenzuela et al. (2022)`'s
professional-cyclist power-duration norms are the only real record-power
dataset available, but they're an **elite population, not masters** — using
them as a ceiling requires the age-decline discount below (never compare a
masters athlete's raw W/kg to this table directly). **Test:** if a plan
projects a raw comparison to this table with no age adjustment applied,
that's a red flag on the plan, not the table.

**Coach judgment:** the popular age-graded W/kg category table (the
Coggan/Allen "power profile," a coaching-book compilation) has no
peer-reviewed backing for its specific age-grading crosswalks — treat it as
informal color, never a hard ceiling. `plan_check.py`'s
`MAX_REALISTIC_ANNUAL_GAIN_FRACTION` stays a Coach-judgment pick inside the
qualitative "modest, single-digit-to-low-teens per block" band above, not a
citation-derived number — false precision would misrepresent the evidence.

## Age-related decline for a training-maintaining masters athlete

`[ADAPTED: general-endurance] Confidence: high.` `Rogers et al. (1990)` —
an 8-year **longitudinal** follow-up (not cross-sectional; the same
athletes tracked as they aged), 15 well-trained masters (mean age 62) vs.
14 sedentary controls: masters VO2max declined **~5.5%/decade**, roughly
**half** the sedentary controls' **~12%/decade**. This is the primary
anchor for `plan_check.py`'s decline-rate constant: real, direct,
same-cohort evidence that staying trained roughly halves the expected
decline.

`Tanaka & Seals (2008)`'s standard review frames the shape: peak endurance
performance holds to ~35, a **modest decline to ~50-60**, then
progressively steeper after — model a masters athlete's ceiling as
flat-to-mildly-declining over a multi-year goal horizon, not flat
indefinitely.

**Honest contradiction, stated plainly, not smoothed over:** `Pimentel et
al. (2003)` — a cross-sectional study of 153 men 20-75 — found
endurance-**trained** men's VO2max declined **faster** with age than
sedentary men's, the opposite of Rogers' framing. This is a real,
unresolved tension in the masters-athletics literature: cross-sectional
designs like Pimentel's can be confounded by different cohorts' peak
historical training volumes, while Rogers' longitudinal design more
directly isolates the training-maintenance effect on the *same* people.
Neither figure is "settled." **Test:** trust this athlete's own
longitudinal CTL/zone trend over either population figure, always.

**Concrete number:** `plan_check.py`'s `MASTERS_ANNUAL_DECLINE_FRACTION`
is set to Rogers' own **~5-6%/decade** anchor (≈0.5-0.6%/year) — the
strongest single figure available, longitudinal, same-cohort, with the
Pimentel contradiction flagged rather than papered over.

## Swim taper length — evidence does NOT pin 3 or 4 weeks

**Best-supported default: `Bosquet et al. (2007)`'s meta-analysis — an
optimal FULL taper is a ~2-week exponential reduction of 41-60% volume,
intensity held.** This is the only genuinely load-bearing, broad-evidence
number in this whole file's taper question, and it's what
`plan_check.py`'s `GENERAL_TAPER_CUT_FRACTION_MIN/MAX` (0.41-0.60) already
encodes.

**State plainly: no evidence supports a fixed 3-week OR 4-week taper for
this athlete's ultra open-water goal.** `Hellard et al. (2013)` studied a
**predefined** 6-week final period (3-week overload + 3-week taper) in
elite pool swimmers and found a good within-window loading pattern — it
did **not** compare taper lengths against each other, so it cannot show
that 3 weeks is optimal, only that a 3-week window, used as designed,
worked. Citing it as "3 weeks is evidence-backed" overstates what it
tested; a predefined window is not a comparison. Formosa's 78-km
solo-swim case (already corrected in `reference_list.md`) is a **single
case** at ~3 weeks/~43% volume cut — real, population-matched
(masters-aged, ultra open water), but n=1, not a rate-tested optimum.
Mujika & Padilla (2003)'s 4-28-day studied range brackets both numbers
without preferring either end.

**`plan_check.py`'s `TAPER_WEEKS_LONG`/`TAPER_WEEKLY_DECAY` (the retired
`plan.py` scaffold constants) are NOT changed on this file's evidence** —
those scaffolds are retired from the coach's tools; taper length is now
the coach's own per-event, per-athlete choice. This file's job is only the
**advisory check band** (`GENERAL_TAPER_CUT_FRACTION_MIN/MAX`,
already Bosquet-aligned) that `check_macro` measures a coach-authored
taper against — not a length the engine picks for the coach. **Test:** if
a real taper at 2-3 weeks/40-45% reads flat or stale for this athlete
across a few real races, that's individual signal to lengthen or deepen it
next time — not grounds to assume either fixed length is the "right" one
for everyone.

## Time-feasibility margin

**Coach judgment, not evidence.** Searched directly: no peer-reviewed
source gives a planned-vs-completed training-**time** (hours) adherence
percentage for adult endurance athletes. The one quantified adherence
figure found (junior netball, session-count not hours) is a poor
population match. `[ADAPTED: general-endurance/multi-sport] Confidence: medium.`
`Inoue et al. (2022)` (27 studies, 725 athletes) found coach-planned vs.
athlete-perceived load agreement was fine overall **except on easy days**,
where athletes perceived meaningfully higher intensity than coaches
planned — a real, distinct caution about easy-day RPE drift, not a
duration/hours finding, and not folded into the same margin.

`plan_check.py`'s `TIME_REALITY_BUFFER_FRACTION = 0.10` stays a
Coach-judgment heuristic ("plans routinely require ~10% more time than
they claim" — matching `ai-coach/.claude/agents/red-team.md`'s own
framing), with an explicit `Test:` rather than a citation: does this
athlete's own logged-vs-planned duration gap over a rolling window match
or exceed 10%? If so, the margin is real for her; if not, it's still a
reasonable ceiling to plan against, not a number a study produced.
