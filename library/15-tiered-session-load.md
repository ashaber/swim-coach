# Tiered session load: sRPE > HR-based TRIMP > swim pace-IF > duration-only

Grounds `engine/swim_coach/load.py`'s `session_load`/`daily_loads` tiered
fallback (moved out of `03-periodization.md`'s "Load monitoring" section to
stay under that file's word-count cap; the summary there still points
here). See `00-conventions.md` for the tagging scheme and
`reference_list.md` for full citations.

## The problem this fixes

Confirmed against Renee's real deployed data: she has 63 real logged
workouts (synced from her watch via intervals.icu), but only 1 carries an
RPE -- the other 62 are pure device telemetry (HR, pace, no subjective
survey). The original `session_load` returned `None` for a missing RPE,
and `daily_loads` *excluded* that workout from its date's total entirely --
meaning 62 of her 63 real workouts were invisible to every downstream load
signal built on `daily_loads` (CTL/ATL/TSB, ACWR, monotony).

**Design principle:** a workout's real training load does not depend on
whether the athlete bothered to survey it. RPE adds fidelity on top of a
real, objective load number -- it does not gate whether a load number
exists at all. `session_load` now falls through four tiers of decreasing
fidelity, and the last tier is unconditional (never `None`).

## The four tiers

### Tier 1: sRPE

`duration_min * rpe`, unchanged from before -- the standard Foster
session-RPE model, sport-agnostic. **Coach judgment**, not itself a
swim-specific evidence claim, though its swim-specific *validity* IS
separately evidenced (see `03-periodization.md`'s "RHR/HRV baseline
deviation" section: **✓ Wallace, Slattery & Coutts 2009**, `[EVIDENCE:
swim]`).

### Tier 2: HR-based TRIMP (Banister heart-rate-reserve training impulse)

Used when `avg_hr`, a derivable `hr_max`, and a derivable `hr_rest` are all
available:

```
HRR_fraction = (avg_hr - hr_rest) / (hr_max - hr_rest)
TRIMP = duration_min * HRR_fraction * weight(HRR_fraction)
weight(x) = 0.64 * e^(1.92*x)   for men
weight(x) = 0.86 * e^(1.67*x)   for women
```

**✓ Verified by direct web search this session** (title/authors/publisher/
pages confirmed): **Banister EW (1991)**, "Modeling Elite Athletic
Performance," in *Physiological Testing of Elite Athletes* (Green HJ,
McDougall JD, Wenger HA, eds), Human Kinetics, Champaign IL, pp. 403-424 --
the field's own original heart-rate-based training-load method, predating
sRPE, derived separately for men and women from each group's own
blood-lactate profile as exercise intensity rises. Corroborated by
**Morton RH, Fitz-Clarke JR, Banister EW (1990)**, "Modeling human
performance in running," *Journal of Applied Physiology*, 69(3):1171-1177
-- same TRIMP family, running application, same lead author. `[ADAPTED:
general-endurance]` -- not swim-specific. **Confidence: medium** (the
primary formula is verified and real; it just isn't a swim-specific
citation). **Test:** if TRIMP-tier loads read as systematically too
low/high once Renee logs enough dual RPE+HR sessions to eyeball the two
against each other, revisit.

**⚠ Get this right:** several popular training-log/calculator sites
reproduce this with the MALE 0.64 coefficient applied to both sexes and
only the exponent swapped for women -- that does **not** match the primary
source. This engine's `TRIMP_MALE_COEFFICIENT`/`TRIMP_FEMALE_COEFFICIENT`
(0.64 vs. 0.86) and `TRIMP_MALE_EXPONENT`/`TRIMP_FEMALE_EXPONENT` (1.92 vs.
1.67) are both kept distinct per sex.

**`hr_max` derivation:** no lab-tested HRmax is on file for this athlete
(no fixed HRmax field on `Athlete`). Estimated as the highest
`Workout.max_hr` ever logged in the athlete's own history -- a common
practical convention when no lab test exists, not itself a peer-reviewed
formula. **~ Ausland Å., Kelemen B., Seiler S. (2026)**, "An Exploratory
Study of Maximal Heart Rate Determination in Endurance Athletes: Laboratory
Testing Versus Field Based," *Frontiers in Sports and Active Living*,
8:1806303 -- found real athlete-reported field-effort HRmax exceeded
standard age-based formulas (Fox 220-age, Tanaka 208-0.7*age) by ~5-6 bpm
on average, supporting field-observed HR data over generic formulas. Not an
exact match for this specific convention (that study compares self-reported
*maximal-effort* HR against lab tests/formulas, not "highest incidentally
observed HR across ordinary training sessions" -- this athlete's logged
workouts are training, not standardized max-effort tests, so the proxy is a
floor that can only rise as more history accumulates, never a confirmed
ceiling). PROVISIONAL, not `[EVIDENCE]`.

**`hr_rest` derivation:** `Wellness.resting_hr` is optional and sparse (a
per-day check-in field). Estimated as a short rolling average
(`HR_REST_LOOKBACK_READINGS = 5`) of the most recent logged readings on or
before the workout's own date; falls back to
`HR_REST_GENERIC_FALLBACK_BPM = 60.0` (the top of the commonly-cited
~60-100 bpm normal adult resting-HR range -- American Heart Association
patient-education material, "All About Heart Rate") only when the athlete
has never logged a `resting_hr` at all. Deliberately the top of that range,
not a lower elite-athlete-typical value: a HIGHER assumed `hr_rest`
*understates* the HRR fraction and therefore *understates* TRIMP -- the
safer direction to be wrong in for an assumed number feeding a
training-load estimate.

Explicitly considered and rejected: deriving `hr_rest` from the athlete's
own lowest-ever *in-workout* `avg_hr` instead of a population default. Even
an easy recovery swim's average HR sits well above true resting HR
(measured supine/seated, not mid-exercise) -- that proxy would
systematically understate `hr_rest`, inflate the HRR fraction, and
overestimate load, worse in both accuracy and safety direction than the
population fallback above.

**Sex selection:** the athlete's `sex` field (`Athlete.sex`) selects the
coefficient pair. When unset (as Renee's currently is) or `"other"`, the
engine averages the male and female weighting curves rather than silently
assuming one -- a deliberate neutral default, not a resolved citation.

**Optional refinement -- normalizing to a threshold-hour (`Athlete.lthr_bpm`):**
raised directly by Andrew (Aug 2026 coach-chat session): his own recent
cycling workout came back with a coach explanation that assumed a default
sRPE=1 recovery-ride fallback the engine doesn't even have, for a workout
that in fact had real HR data and should have reached tier 2. Separately,
he pointed out that a raw HR/power number means little without knowing the
athlete's own zones -- "my 200w is endurance, my MTB [ride] it would be Z6
neuromuscular" -- and asked for the engine to use his known lactate-
threshold heart rate (LTHR = 172 bpm) the same way it already uses CSS pace
for swimming, citing intervals.icu's "HRSS" heart-rate load-model option as
the reference behavior he wanted (small load for an easy 60-minute walk,
meaningful load for a multi-hour one).

**✓ Verified by direct fetch this session.** TrainingPeaks' own help
documentation ("Training with TSS vs. hrTSS: What's the Difference?")
confirms hrTSS is "based on time in heart rate training zones derived from
an athlete's lactate threshold heart rate," normalized against "an
estimate of the amount of accumulated TSS in an hour" at threshold effort
-- the same "100 = one hour at threshold" convention this module's Tier 3
already uses for FTP (below). Separately, intervals.icu's own creator
("david," intervals.icu forum thread "HRSS (normalized TRIMP) training
load," confirmed by direct fetch this session) describes intervals.icu's
own "HRSS" heart-rate option as literally Banister TRIMP -- **the exact
formula this tier already implements**, not a different curve -- requiring
only a resting HR and a threshold HR as inputs, "normalized in a similar
way to TSS (100 = 1h max effort)."

Both sources converge on the same conclusion: no new exponential-weighting
formula is needed. `engine/swim_coach/load.py`'s
`_normalize_trimp_to_lthr_hour` implements exactly this -- when
`Athlete.lthr_bpm` is set, the existing tier-2 TRIMP output is linearly
rescaled so that one hour spent at `lthr_bpm` reads as
`HR_LOAD_NORMALIZED_SCALE` (100) AU, using the athlete's own existing
`hr_max`/`hr_rest` estimates (unchanged, see above) purely to place
`lthr_bpm` on the same %HRR fraction the rest of the tier already computes
on. `[ADAPTED: cycling]` (TSS's "100=1hr@FTP" convention, borrowed for
HR). **Confidence: medium** (both practitioner sources independently
confirm the threshold-hour=100 rescaling technique; neither publishes the
exact internal method a commercial tool like intervals.icu uses to derive
a working HRmax from LTHR when no lab-tested max is on file, so this
implementation deliberately keeps using this project's own already-cited
`estimate_hr_max` -- "highest ever observed" -- rather than inventing an
unverified LTHR-to-HRmax ratio). **Test:** if Andrew's real lab- or
field-tested HRmax ever becomes known, compare it against
`estimate_hr_max`'s floor estimate and revisit if they diverge materially.

Worked check against Andrew's own stated numbers (`lthr_bpm=172`,
`hr_max=190` observed, `hr_rest=60` generic fallback): a 60-minute walk at
`avg_hr=85` scores ~7 AU (matching his own quoted expectation of "5-10
points" for a low-HR walk under HRSS), while a 3-hour walk at `avg_hr=95`
scores ~33 AU -- small for the short easy walk, but not collapsed to
near-zero for the long one, addressing his explicit concern that "a 2 to 5
hour walk needs to be counted." See `tests/unit/test_load.py`'s LTHR
normalization tests for the exact figures.

This is deliberately a no-op (unchanged raw TRIMP) for any athlete who
hasn't set `lthr_bpm` -- most profiles haven't, and tier 2's pre-existing
behavior remains correct and unchanged for them.

**Lap-based TRIMP summation (fixes a confirmed real-data bug, Aug 2026):**
whole-session-average TRIMP under-counts interval/variable-effort
workouts. **Coach judgment / directly verifiable math, not a new external
research claim** -- the Banister weighting `weight(x) = coefficient *
e^(exponent*x)` above is convex, and so is `x * weight(x)`; by Jensen's
inequality, `avg(f(x_i)) >= f(avg(x_i))` for a convex `f`, so summing the
weighting over each smaller time-slice's own HRR fraction always meets or
exceeds weighting one whole-session average, strictly exceeding it
whenever HR varies within the session. This is a property of the
already-cited Banister formula's own math, not a new source, so no
separate citation is needed -- stated explicitly rather than left for the
reader to wonder.

Confirmed against a real over/under bike ride logged 2026-08-29 (99
minutes, 46 device-captured laps alternating ~60-second hard reps around
160-170bpm with slower recovery segments around 110-140bpm): 121.67 raw
TRIMP from the workout's single whole-session `avg_hr`, vs. 139.52 raw
TRIMP summing the identical formula over its 46 real laps -- ~15% higher
for the same ride, matching the athlete's own sense that the app
under-scored it next to intervals.icu's own (differently-scaled) reported
Load of 87.

`_trimp_from_laps` implements the summed version, used only when
`workout.laps` is non-empty, every lap has `avg_hr` set, and the laps'
total duration is within `TRIMP_LAP_COVERAGE_TOLERANCE` (10%, **Coach
judgment**, not research-backed) of the workout's own duration -- falls
back to the pre-existing whole-session computation, unchanged, otherwise
(the overwhelming majority of this athlete's logged history: zero or one
lap).

### Tier 3: swim pace-based intensity (a TSS-family formula)

Used when tier 2 isn't available, the session is a swim (`swim_pool`/
`swim_ow`), and both the workout's `avg_pace_s_per_100m` and the athlete's
`css_pace_s_per_100m` are known:

```
IF = css_pace_s_per_100m / avg_pace_s_per_100m
swim_tss = duration_hours * IF^3 * 100
```

IF is inverted relative to power-based intensity factor because pace is a
*time* value -- a *lower* `avg_pace_s_per_100m` is *faster*, so it must
produce a *higher* IF, not lower (`tests/unit/test_load.py` has a direct
faster-swim-scores-higher-load regression test for this).

**✓ Verified by direct web search/fetch this session.** The general
TSS-family shape (`TSS = duration_hours * IF^2 * 100`, IF = Normalized
Power / FTP; one hour exactly at FTP scores 100) originates from
**Allen H., Coggan A. (2010)**, *Training and Racing with a Power Meter*
(2nd ed.), VeloPress -- the originating practitioner text for TSS/IF, not a
peer-reviewed journal source, same footing as this project's other
TrainingPeaks-convention citations (see `03-periodization.md`'s CTL/ATL
section). TrainingPeaks' own swim-specific documentation ("Calculating
Swimming TSS Score," confirmed by direct fetch this session) explicitly
**cubes** the intensity factor instead of squaring it: "because water
presents more resistance than air, the physiological stress of swimming
increases with increasing swim speed faster than ... running" -- a
deliberate, documented swim-specific adaptation of the generic cycling
formula, not an unexamined carry-over. `[ADAPTED: cycling]`. **Confidence:
medium** (a widely-used practitioner convention with a stated physical
rationale, not an independently validated exponent). **Test:** if this
tier's swim loads consistently feel out of proportion to sRPE-scored swims
of similar perceived effort once more dual-logged data exists, revisit the
exponent.

### Tier 4: duration-only fallback

`duration_min * DURATION_ONLY_ASSUMED_INTENSITY`
(`DURATION_ONLY_ASSUMED_INTENSITY = 5`, the same 1-10-scale "somewhat hard"
midpoint the old `DEFAULT_RPE_WHEN_MISSING` constant used). **Coach
judgment**, last resort only, unconditional so a workout is never simply
absent from a load total for lack of one specific signal. This replaces
the old `assume_default_rpe`/`DEFAULT_RPE_WHEN_MISSING` opt-in escape hatch
(removed as dead code): that mechanism let a caller *choose* to fake an
RPE for coverage; this fires automatically as the guaranteed final tier,
only after every richer signal above has already been checked and failed.

## Known limitation: the tiers are not on one numeric scale

sRPE and HR-based TRIMP were never designed to be summed interchangeably
within one athlete's history -- a session scored by TRIMP typically comes
out to roughly a third to a half of what the *same* effort would score via
sRPE (see `tests/unit/test_load.py`'s worked examples: a 60-minute session
at HRR_fraction≈0.71 scores ~108-121 TRIMP depending on sex, versus 300-480
for the same duration at a plausible sRPE of 5-8). `daily_loads` sums
whatever tier each individual workout resolves to anyway, because a real
lower-fidelity number still beats a silently excluded workout, but a day
mixing an sRPE-scored session with a TRIMP-scored one will under-represent
the TRIMP-scored session's relative contribution to that day's total.

This is a real, documented gap, not a solved problem. A future pass could
calibrate TRIMP/pace-IF against this athlete's own historical
sRPE-vs-HR/pace data once enough dual-logged sessions exist to fit a
personal scaling factor -- but inventing an uncited scaling constant now
would trade one silent distortion for another. Revisit once Renee logs
more RPE alongside her watch data.

**Partial fix, for whichever athlete has one:** the LTHR-normalization
above narrows this for tier 2 specifically -- rescaling TRIMP onto TSS's
own "100 = one hour at threshold" convention -- but only for an athlete
who has actually set `Athlete.lthr_bpm`, and it doesn't reconcile TSS's
own scale with sRPE's either (those remain two different, never-reconciled
conventions in the broader field, not something this project has solved).

**Also investigated and found unsupported:** whether tier 4's
`DURATION_ONLY_ASSUMED_INTENSITY` should be split per activity type (e.g. a
different assumed intensity for kayaking vs. walking vs. a generic gym
session) instead of one flat constant for every cross-train workout with
neither RPE nor usable HR data. `20-cross-train-load-standardization.md`
covers this specific question in full: no rigorous, peer-reviewed, or
widely-adopted industry standard exists for a per-activity-type assumed
intensity in the zero-signal case, and the closest real analog (missing-RPE
imputation research in rugby) found that fixed-value substitution -- the
closest real-world approach to a per-modality constant -- was the *least*
accurate method tested, with individualized historical-data models winning
instead (a route this project can't use for a brand-new modality with zero
prior signal). The uniform `DURATION_ONLY_ASSUMED_INTENSITY` constant
therefore stays a deliberate, documented simplification, not an unexamined
gap.

## Unit: "AU" (arbitrary units)

All four tiers above produce a **Training Load (AU) = duration (minutes) x
CR-10 RPE score** for tier 1, generalized loosely to the other three tiers'
own formulas (HR-based TRIMP, swim pace-IF, duration-only) -- "AU" names the
result honestly as a nominal, project-internal scale, not a physical unit
with external meaning (unlike, say, kilojoules). This label is a
**Coach judgment** naming choice, not a citation -- it doesn't change any
formula, constant, or existing load number, and it doesn't resolve the
"tiers are not on one numeric scale" limitation documented above: an
sRPE-tier AU value and a TRIMP-tier AU value are both honestly labeled AU,
and still not directly comparable to each other for the reasons given above.
