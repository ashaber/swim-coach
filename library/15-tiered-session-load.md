# Tiered session load: sRPE > HR-based TRIMP > swim pace-IF > duration-only

Grounds `engine/swim_coach/load.py`'s `session_load`/`daily_loads` tiered
fallback (moved out of `03-periodization.md`'s "Load monitoring" section).
See `00-conventions.md` for the tagging scheme and `reference_list.md` for
full citations.

## The problem this fixes

Confirmed against Renee's real deployed data: she has 63 real logged
workouts (synced from her watch via intervals.icu), but only 1 carries an
RPE -- the other 62 are pure device telemetry (HR, pace, no subjective
survey). The original `session_load` returned `None` for a missing RPE,
and `daily_loads` *excluded* that workout entirely -- 62 of her 63 real
workouts were invisible to every downstream load signal (CTL/ATL/TSB,
ACWR, monotony).

**Design principle:** a workout's real training load does not depend on
whether the athlete bothered to survey it. RPE adds fidelity on top of a
real, objective load number -- it does not gate whether one exists at all.
`session_load` falls through four tiers of decreasing fidelity; the last
is unconditional (never `None`).

## The four tiers

### Tier 1: sRPE

`duration_min * rpe`, the standard Foster session-RPE model, sport-agnostic.
**Coach judgment**, not itself a swim-specific evidence claim, though its
swim-specific *validity* IS separately evidenced (see `03-periodization.md`'s
"RHR/HRV baseline deviation" section: **✓ Wallace, Slattery & Coutts 2009**,
`[EVIDENCE: swim]`).

**Refinement -- putting sRPE on tier 2's own normalized scale, when there's
enough HR context to (confirmed against real data, Aug 2026):** sRPE's raw
`duration_min * rpe` is never rescaled, while tier 2 gets LTHR-normalized
onto a "100 = one hour at threshold" scale once `lthr_bpm` is set -- so
which tier a workout landed on (purely whether RPE was logged that day)
drove its scale, not how hard the workout actually was. Confirmed against
two of Andrew's own consecutive rides: **2026-08-30** (MTB, `rpe=5`,
`duration_min=158.5`) scored raw sRPE **792.5 AU** vs. TrainingPeaks' own
TSS of **155**; **2026-08-29** (no RPE) scored **78.6 AU** after
LTHR-normalization vs. TrainingPeaks' TSS of **85** -- ~1.8x apart on
TrainingPeaks, but **~10x apart** in this engine.

**The fix:** when `workout.rpe` is set AND tier 2's own four preconditions
are also met (`hr_max`, `hr_rest` with `hr_max > hr_rest`, `lthr_bpm`), the
RPE converts to an estimated %HRR fraction (`rpe / 10.0` -- CR-10's own
endpoints: 0 = "Rest / Nothing at all" ~0% HRR, 10 = "Maximal / Exhausting"
~100% HRR, per `19-srpe-protocol.md`) and runs through the *exact same*
Banister weighting + LTHR-normalization pipeline tier 2 already uses -- no
new formula. **Tier priority is unchanged**: sRPE still wins over measured
HR whenever logged; only the output value changes. Missing any one
precondition (most profiles have no `lthr_bpm` yet) falls back to
byte-identical `duration_min * rpe`.

**Coach judgment / PROVISIONAL** -- `rpe / 10.0` is not a fitted
regression. **✓ Verified by direct fetch this session** (full primary text
obtained): **Arney et al. (2019)**, "Comparison of Rating of Perceived
Exertion Scales During Incremental and Interval Exercise," *Kinesiology*,
51(2):150-157 (full author list in `reference_list.md`) -- corroborates a
strong, roughly-linear CR-10-vs-%HRR relationship ("very large"
correlations: r=.87 incremental, r=.84 interval), with a real (CR-10,
%HRR) table: (3.1, 63.8%), (6.5, 90.0%), (8.9, 97.4%). No full-range
regression equation is published (its own quadratic equations interconvert
BORG-RPE 6-20 and BORG-CR10 against each other, not either scale against
%HRR) -- a least-squares line through those three points extrapolates to a
nonsensical ~47% %HRR at CR-10=0 (they only span moderate-to-hard
efforts), confirming `rpe / 10.0`'s honest simplicity over fabricating
precision the source doesn't support. **[ADAPTED: general-endurance]
Confidence: low-medium.** **Test:** once this athlete has enough
dual-logged (RPE + real HR) workouts, fit a personal RPE-to-%HRR
relationship instead.

Recomputing 2026-08-30 through this refined path (`hr_max=190`,
`hr_rest=52`, `lthr_bpm=172`) gives **~78.5 AU** -- close to 8/29's 78.6 AU
(a coincidental convergence, not a general claim). Recomputing that same
ride through tier 2 instead (real `avg_hr=138`) gives **~121.9 AU** -- a
~1.55x spread, the same order of magnitude as TrainingPeaks' own 1.8x, not
the old ~10x gap; some divergence between an RPE estimate and a
measured-HR figure is expected, real signal, not a bug. See
`tests/unit/test_load.py`'s sRPE-via-HRR-normalization tests for exact
figures.

### Tier 2: HR-based TRIMP (Banister heart-rate-reserve training impulse)

Used when `avg_hr`, `hr_max`, and `hr_rest` are all available:

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
blood-lactate profile. Corroborated by **Morton RH, Fitz-Clarke JR,
Banister EW (1990)**, "Modeling human performance in running," *Journal of
Applied Physiology*, 69(3):1171-1177 -- same TRIMP family, running
application, same lead author. `[ADAPTED: general-endurance]`. **Confidence:
medium** (primary formula verified and real; not swim-specific).
**Test:** if TRIMP-tier loads read as systematically too low/high once
Renee logs enough dual RPE+HR sessions, revisit.

**⚠ Get this right:** several popular training-log sites reproduce this
with the MALE 0.64 coefficient applied to both sexes and only the exponent
swapped for women -- that does **not** match the primary source. This
engine's `TRIMP_MALE_COEFFICIENT`/`TRIMP_FEMALE_COEFFICIENT` (0.64 vs.
0.86) and exponents (1.92 vs. 1.67) are both kept distinct per sex.

**`hr_max` derivation:** no lab-tested HRmax is on file. Estimated as the
highest `Workout.max_hr` ever logged -- a common practical convention when
no lab test exists, not itself a peer-reviewed formula. **~ Ausland Å.,
Kelemen B., Seiler S. (2026)**, "An Exploratory
Study of Maximal Heart Rate Determination in Endurance Athletes: Laboratory
Testing Versus Field Based," *Frontiers in Sports and Active Living*,
8:1806303 -- found real field-effort HRmax exceeded age-based formulas
(Fox 220-age, Tanaka 208-0.7*age) by ~5-6 bpm, supporting field-observed
data over generic formulas. Not an exact match (self-reported
*maximal-effort* HR, not "highest incidentally observed HR in training" --
this proxy is a floor that can only rise, never a confirmed ceiling).
PROVISIONAL, not `[EVIDENCE]`.

**`hr_rest` derivation:** `Wellness.resting_hr` is optional and sparse.
Estimated as a short rolling average (`HR_REST_LOOKBACK_READINGS = 5`) of
the most recent logged readings on or before the workout's date; falls
back to `HR_REST_GENERIC_FALLBACK_BPM = 60.0` (the top of the commonly-cited
~60-100 bpm normal adult resting-HR range -- American Heart Association
patient-education material) only when never logged. Deliberately the top
of that range: a HIGHER assumed `hr_rest` *understates* HRR and therefore
*understates* TRIMP -- the safer direction to be wrong in.

Considered and rejected: deriving `hr_rest` from the athlete's own
lowest-ever *in-workout* `avg_hr` -- even an easy recovery swim sits well
above true resting HR, so that proxy would inflate the HRR fraction and
overestimate load, worse in both accuracy and safety than the fallback.

**Sex selection:** `Athlete.sex` selects the coefficient pair. When unset
(as Renee's currently is) or `"other"`, the engine averages the male and
female weighting curves rather than silently assuming one -- a deliberate
neutral default, not a resolved citation.

**Optional refinement -- normalizing to a threshold-hour (`Athlete.lthr_bpm`):**
raised directly by Andrew (Aug 2026): a raw HR/power number means little
without knowing the athlete's own zones -- "my 200w is endurance, my MTB
[ride] it would be Z6 neuromuscular" -- so he asked for the engine to use
his known lactate-threshold heart rate (LTHR = 172 bpm) the same way it
already uses CSS pace for swimming, citing intervals.icu's "HRSS"
heart-rate load-model option as the reference behavior he wanted (small
load for an easy 60-minute walk, meaningful load for a multi-hour one).

**✓ Verified by direct fetch this session.** TrainingPeaks' own help
documentation ("Training with TSS vs. hrTSS: What's the Difference?")
confirms hrTSS is "based on time in heart rate training zones derived from
an athlete's lactate threshold heart rate," normalized against "an
estimate of the amount of accumulated TSS in an hour" at threshold effort
-- the same "100 = one hour at threshold" convention Tier 3 uses for FTP
(below). Separately, intervals.icu's own creator ("david," intervals.icu
forum thread "HRSS (normalized TRIMP) training load," confirmed by direct
fetch this session) describes their "HRSS" heart-rate option as literally
Banister TRIMP -- **the exact formula this tier already implements** --
"normalized in a similar way to TSS (100 = 1h max effort)."

Both sources converge: no new exponential-weighting formula is needed.
`_normalize_trimp_to_lthr_hour` implements exactly this -- when
`Athlete.lthr_bpm` is set, tier-2's TRIMP output is linearly rescaled so
one hour at `lthr_bpm` reads as `HR_LOAD_NORMALIZED_SCALE` (100) AU, using
the existing `hr_max`/`hr_rest` estimates purely to place `lthr_bpm` on the
same %HRR fraction the tier already computes on. `[ADAPTED: cycling]`
(TSS's "100=1hr@FTP" convention, borrowed for HR). **Confidence: medium**
(both sources confirm the rescaling technique; neither publishes the exact
method a tool like intervals.icu uses to derive HRmax from LTHR, so this
keeps using the project's own already-cited `estimate_hr_max` rather than
an unverified ratio). **Test:** if a real lab-/field-tested HRmax ever
becomes known, compare it against `estimate_hr_max`'s floor and revisit if
they diverge materially.

Worked check (`lthr_bpm=172`, `hr_max=190`, `hr_rest=60` generic fallback):
a 60-minute walk at `avg_hr=85` scores ~7 AU (matching Andrew's own "5-10
points" expectation for a low-HR walk under HRSS); a 3-hour walk at
`avg_hr=95` scores ~33 AU -- small for the short easy walk, not collapsed
to near-zero for the long one. See `tests/unit/test_load.py`'s LTHR
normalization tests for exact figures.

A no-op (unchanged raw TRIMP) for any athlete who hasn't set `lthr_bpm` --
most profiles haven't, and tier 2's pre-existing behavior stays unchanged
for them.

**Lap-based TRIMP summation (fixes a confirmed real-data bug, Aug 2026):**
whole-session-average TRIMP under-counts interval/variable-effort
workouts. **Coach judgment / directly verifiable math, not a new external
research claim** -- the Banister weighting `weight(x) = coefficient *
e^(exponent*x)` above is convex, and so is `x * weight(x)`; by Jensen's
inequality, `avg(f(x_i)) >= f(avg(x_i))` for a convex `f`, so summing the
weighting per smaller time-slice always meets or exceeds weighting one
whole-session average, strictly exceeding it whenever HR varies within the
session -- a property of the already-cited Banister formula's own math,
needing no separate citation.

Confirmed against a real over/under bike ride logged 2026-08-29 (99
minutes, 46 laps alternating ~60-second hard reps ~160-170bpm with
recovery ~110-140bpm): 121.67 raw TRIMP from the whole-session `avg_hr`,
vs. 139.52 summing the identical formula per lap -- ~15% higher for the
same ride, matching the athlete's sense that the app under-scored it next
to intervals.icu's own (differently-scaled) reported Load of 87.

`_trimp_from_laps` implements the summed version, used only when
`workout.laps` is non-empty, every lap has `avg_hr` set, and the laps'
total duration is within `TRIMP_LAP_COVERAGE_TOLERANCE` (10%, **Coach
judgment**, not research-backed) of the workout's own duration -- falls
back to the pre-existing whole-session computation, unchanged, otherwise
(the overwhelming majority of this athlete's logged history: zero or one
lap).

### Tier 3: swim pace-based intensity (a TSS-family formula)

Used when tier 2 isn't available, the session is a swim, and both
`avg_pace_s_per_100m` and `css_pace_s_per_100m` are known:

```
IF = css_pace_s_per_100m / avg_pace_s_per_100m
swim_tss = duration_hours * IF^3 * 100
```

IF is inverted relative to power-based intensity factor because pace is a
*time* value -- a *lower* `avg_pace_s_per_100m` is *faster*, so it must
produce a *higher* IF (`tests/unit/test_load.py` has a direct
faster-swim-scores-higher-load regression test).

**✓ Verified by direct web search/fetch this session.** The general
TSS-family shape (`TSS = duration_hours * IF^2 * 100`, IF = Normalized
Power / FTP; one hour exactly at FTP scores 100) originates from
**Allen H., Coggan A. (2010)**, *Training and Racing with a Power Meter*
(2nd ed.), VeloPress -- the originating practitioner text for TSS/IF, same
footing as this project's other TrainingPeaks-convention citations (see
`03-periodization.md`'s CTL/ATL section). TrainingPeaks' own swim-specific
documentation ("Calculating Swimming TSS Score," confirmed by direct fetch
this session) explicitly **cubes** the intensity factor instead of
squaring it: "because water presents more resistance than air, the
physiological stress of swimming increases with increasing swim speed
faster than ... running" -- a deliberate, documented swim-specific
adaptation, not an unexamined carry-over. `[ADAPTED: cycling]`.
**Confidence: medium** (a widely-used practitioner convention with a
stated physical rationale, not an independently validated exponent).
**Test:** if this tier's swim loads feel out of proportion to sRPE-scored
swims of similar effort once more dual-logged data exists, revisit the
exponent.

### Tier 4: duration-only fallback

`duration_min * DURATION_ONLY_ASSUMED_INTENSITY`
(`DURATION_ONLY_ASSUMED_INTENSITY = 5`, the same 1-10-scale "somewhat hard"
midpoint the old `DEFAULT_RPE_WHEN_MISSING` constant used). **Coach
judgment**, last resort only, unconditional so a workout is never absent
from a load total for lack of one specific signal. Replaces the old
`assume_default_rpe`/`DEFAULT_RPE_WHEN_MISSING` opt-in escape hatch
(removed as dead code): that let a caller *choose* to fake an RPE for
coverage; this fires automatically, only after every richer signal above
has already failed.

## Known limitation: the tiers are not on one numeric scale

sRPE and HR-based TRIMP were never designed to be summed interchangeably
within one athlete's history -- a session scored by TRIMP typically comes
out to roughly a third to a half of what the *same* effort would score via
sRPE (see `tests/unit/test_load.py`'s worked examples: a 60-minute session
at HRR_fraction≈0.71 scores ~108-121 TRIMP depending on sex, versus 300-480
for the same duration at a plausible sRPE of 5-8). `daily_loads` sums
whatever tier each workout resolves to anyway (a real lower-fidelity
number beats a silently excluded workout), but a day mixing an
sRPE-scored session with a TRIMP-scored one under-represents the
TRIMP-scored session's relative contribution.

This is a real, documented gap for an athlete without `lthr_bpm` set, not
a fully solved problem. A future pass could calibrate TRIMP/pace-IF against
this athlete's own historical sRPE-vs-HR/pace data once enough dual-logged
sessions exist to fit a personal scaling factor -- but inventing an uncited
scaling constant now would trade one silent distortion for another.

**Partial fix, for whichever athlete has `lthr_bpm` set:** the LTHR-
normalization (tier 2) and the sRPE-via-HRR-normalization refinement
(tier 1, above) together close this gap for that athlete specifically --
both tiers now land on the same "100 = one hour at threshold" scale. An
athlete without `lthr_bpm` still gets the unreconciled scales described
above.

**Also investigated and found unsupported:** whether tier 4's
`DURATION_ONLY_ASSUMED_INTENSITY` should be split per activity type instead
of one flat constant for every cross-train workout with neither RPE nor
usable HR data. `20-cross-train-load-standardization.md` covers this in
full: no industry standard exists for a per-activity assumed intensity in
the zero-signal case, and the closest analog (missing-RPE imputation
research in rugby) found fixed-value substitution the *least* accurate
method tested, with individualized historical-data models winning instead
(not available for a brand-new modality with zero prior signal). The
uniform constant stays a deliberate simplification, not an unexamined gap.

## Unit: "AU" (arbitrary units)

All four tiers produce a value in **AU** -- a nominal, project-internal
scale, not a physical unit with external meaning (unlike, say, kilojoules).
**Coach judgment** naming choice, not a citation: it changes no formula or
existing load number, and doesn't itself resolve the "tiers are not on one
numeric scale" limitation above -- an sRPE-tier AU value and a TRIMP-tier
AU value are both honestly labeled AU, and (outside the refinements above)
still not directly comparable to each other.
