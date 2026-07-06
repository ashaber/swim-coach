# Periodization & load monitoring

Grounds `engine/swim_coach/plan.py`'s macro block structure and
`engine/swim_coach/load.py` / `engine/swim_coach/adapt.py`'s load-monitoring
and adaptation-rule constants. See `00-conventions.md` for the tagging
scheme and `reference_list.md` for full citations.

## Macro block structure (base -> build -> peak -> taper)

`plan.scaffold_macro()` splits the runway to an event into four blocks.
**Coach judgment**, PROVISIONAL, none of the individual block-count/share
constants below are independently cited figures — they're a conventional
base/build/peak/taper *shape* (widely used across endurance coaching in
general) applied with this engine's own specific splits:

- `MIN_MACRO_WEEKS = 8` — refuse to periodize below 8 weeks of runway;
  four blocks each need at least a week or two to mean anything below that.
- `TAPER_RUNWAY_THRESHOLD_WEEKS = 16` — runways of 16+ weeks get the longer
  taper/peak; shorter runways compress both.
- `PEAK_WEEKS_LONG = 3`, `PEAK_WEEKS_SHORT = 2`.
- `BASE_SHARE = 0.6` — of the weeks remaining after taper+peak are carved
  out, base gets `ceil(60%)`, build gets the rest.
- `BASE_END_VOLUME_SHARE_OF_PEAK = 0.85` — base ramps toward ~85% of peak
  weekly volume by its final week; build closes the remaining gap.
- `PEAK_WEEKLY_VOLUME_X_EVENT_DISTANCE = 2.5` — default peak weekly volume,
  as a multiple of event distance, when no explicit peak volume is supplied.

None of these five carry direct citations; they encode a defensible,
conventional shape that this project can revisit once enough athletes/
macrocycles have run through it to compare against outcomes.

## Taper: `TAPER_WEEKS_LONG/SHORT`, `TAPER_WEEKLY_DECAY` — known citation debt

**⚠ Citation debt, actively flagged, not yet resolved as of Day 4.**
`plan.py`'s taper constants (`TAPER_WEEKS_LONG = 4`, `TAPER_WEEKLY_DECAY =
0.25`, i.e. a 4-week taper losing 25% of peak volume per week) were
originally cited to Formosa et al.'s 78-km solo open-water swim case study
as "a 4-week exponential decay model, volume reduced 25% linearly each
week." **`reference_list.md`'s corrections log says this is wrong**: the
actual Formosa et al. paper (real, verified — *International Journal of
Sports Medicine*) reports a **~3-week taper with ~43% total volume
reduction, intensity maintained** — the "4-week/25%-linear" figures were
embellishments introduced during earlier (Gemini-assisted) research and must
not be attributed to Formosa.

This engine's current 4-week/25%-per-week taper is therefore demoted to
**Coach judgment, PROVISIONAL** (not `[EVIDENCE: swim-ultra]`) pending a
follow-up engine pass that either (a) re-derives the taper block from the
corrected ~3-week/~43% figures, or (b) deliberately keeps a different taper
shape as a documented coach-judgment choice. This file and `plan.py`'s
constant comments should be updated together whenever that follow-up
happens — see `plan.py`'s `TAPER_WEEKS_LONG` comment for the same flag in
code.

## Safety rail: `WEEKLY_VOLUME_RAMP_CAP = 0.08`

**Coach judgment / project safety rail** (not itself a physiology citation):
CLAUDE.md's standing rule caps weekly volume increases at +8%/week without
explicit athlete confirmation. `scaffold_macro()` and `generate_week()`
enforce this as a hard mathematical ceiling — peak volume is clamped
(with a `UserWarning`) if a requested/derived target would require
exceeding 8%/week compounding across the ramp weeks available.

Note this project's own reference list *separately* documents that the
common "10% rule" (a different, more permissive number from 1980s running
coaching lore) has been specifically tested and found **not** evidence-based
(`reference_list.md`: Buist et al. 2008 RCT + systematic review, "no
evidence exists for use of the so-called 10% rule"). This engine's 8% figure
is more conservative than that debunked 10% figure, not because 8% is itself
independently proven safer, but as a deliberately cautious choice given the
10% figure's own evidence has been undermined and this athlete's history
includes multiple training interruptions (injury/illness) that argue for
conservatism over precision here.

## Load monitoring (`load.py`)

### sRPE session load

**Coach judgment** (standard training-load bookkeeping method, not itself a
swim-specific evidence claim): `session_load = duration_min * rpe` (the
Foster session-RPE model), sport-agnostic. `DEFAULT_RPE_WHEN_MISSING = 5` is
the 1-10 scale's "somewhat hard" midpoint, used only when a caller opts into
`assume_default_rpe=True` for an RPE-less logged workout (e.g. an ingested
.fit file); the default behavior instead excludes RPE-less workouts from
load totals rather than guessing.

### Monotony

**Coach judgment**: `monotony = mean(daily loads) / stdev(daily loads)`
(the standard Foster monotony bookkeeping formula). High monotony (little
day-to-day load variation) is associated with overtraining risk in the
broader load-monitoring literature even at moderate absolute loads — this
project doesn't have a swim-specific citation for that association in
`reference_list.md`, so it's flagged as a widely used method applied here
as engineering/coaching judgment, not an `[EVIDENCE]` claim.

### Acute:chronic workload ratio (ACWR)

`load.acute_chronic_ratio()` computes a 7-day load sum divided by a 28-day
average load rescaled to weekly units (a "coupled"/simple rolling-average
ACWR), rather than an exponentially-weighted moving average.

**⚠ [ADAPTED: running] Confidence: low.** `reference_list.md`'s "Injury &
training load" section carries the key caveat directly: **Feijen S. et al.
(2021)**, "Prediction of Shoulder Pain in Youth Competitive Swimmers"
(*American Journal of Sports Medicine*) found ACWR associated with shoulder
pain at an odds ratio of ~4.31 — but in **youth** swimmers, with a
confidence interval whose lower bound sits near 1.0 (marginal significance),
and the entry explicitly notes "ACWR methodology is broadly criticized."
Separately, the **Garmin-RunSafe running-health cohort** (5,200+ runners,
>500,000 logged runs, *British Journal of Sports Medicine* 2025/26) found
that week-to-week volume ratio and ACWR were *weak* predictors of injury
risk, while a single session exceeding the prior-30-day longest effort by
more than ~10% was the strongest signal.

**Practical consequence for this engine:** ACWR (`adapt.py`'s
`LOAD_RATIO_RED_THRESHOLD = 1.4`) is used only as a coarse secondary
red-flag signal in the adaptation rule table (a load-ratio spike, alongside
poor wellness, triggers a volume cut) — it is *not* the primary lever for
long-swim injury-risk management. That job belongs to the single-session-
vs-30-day-longest check implemented directly in `adapt.py`'s long-swim
ladder (see `06-long-swim-progression.md`), which has the stronger evidence
behind it per the Garmin-RunSafe finding above.

**Test:** if `adapt.py`'s load-ratio-triggered cuts don't correlate with any
observable wellness decline or injury/soreness signal over a season, that's
consistent with the literature's own skepticism of ACWR and would support
loosening or removing this specific rule in a future pass, rather than
trusting the ratio uncritically.

### Wellness composite

**Coach judgment:** `wellness_composite = mean(sleep_quality, 6-stress,
6-soreness, motivation)`, each term on the `Wellness` model's native 1-5
scale, stress/soreness inverted so higher always means "better recovered."
This specific weighting (equal-weighted mean of four fields) is Andrew's own
scoring convention, not a validated psychometric instrument — flagged
explicitly as engineering judgment. `adapt.py`'s
`WELLNESS_RED_THRESHOLD = 2.0` (a composite at or below 2.0, averaged over
the trailing `WELLNESS_WINDOW_DAYS = 7` days, triggers a mandatory volume
cut) is likewise a coach-judgment threshold, chosen to sit clearly in the
"consistently poor across several fields" zone rather than a single bad
data point.

### Compliance

**Coach judgment:** `compliance = completed swim distance / planned swim
distance * 100`, a bookkeeping definition (not a physiology claim).
`adapt.py`'s thresholds:
- `COMPLIANCE_REPEAT_THRESHOLD = 70.0` — below 70%, repeat the current
  progression step rather than advancing (a big shortfall between plan and
  reality means the plan's assumptions need re-checking, not compounding).
- `COMPLIANCE_ADVANCE_THRESHOLD = 90.0` — at or above 90%, combined with no
  red-flag signals, the engine advances (see `06-long-swim-progression.md`
  for how the long swim specifically advances).

The 70/90 split (with a 70-90% "hold, don't advance or repeat" middle band)
is this engine's own judgment call about how much slack to give real-world
plan/execution mismatch before treating it as either "plan was wrong" (low
compliance -> repeat) or "genuinely earned the next step" (high compliance
-> advance).

### Cut magnitude: `CUT_VOLUME_FRACTION = 0.25`

**Coach judgment.** ROADMAP.md's adaptation rule specifies "cut volume
20-30%" on a red flag; this engine uses the documented range's midpoint
(25%) as a single deterministic value rather than continuously scaling the
cut by how far over threshold the wellness/load signals are. A
severity-scaled cut (e.g. a much-redder wellness score producing a deeper
cut) is a reasonable future refinement, intentionally not implemented in
this pass to keep the rule table simple and auditable.

## Informational-only: 80/20 intensity balance

ROADMAP.md's adaptation rules mention "balance 80/20 intensity across total
swim time" as a rule, but **the canonical 80/20 polarized-training citation
(e.g. Seiler's work) is not present in `reference_list.md`** — this project
has no verified source for that specific split. `adapt.py`'s
`_intensity_balance()` (constants `EASY_RPE_MAX = 5`,
`TARGET_EASY_TIME_SHARE = 0.80`) is therefore implemented as **Coach
judgment, informational only**: it reports the easy/hard swim-time split
over a trailing 28-day window in the adaptation rationale, but does not gate
any cut/repeat/hold/advance decision. The engine cannot enforce an intensity
split at planning time in any case, because pool-coach session content
(most of weekly swim time) is unknown until delivered post-hoc — this is
surfaced for `/adapt`'s human judgment review, not planning-time
enforcement.
