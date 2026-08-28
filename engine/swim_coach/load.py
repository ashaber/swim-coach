"""Training-load math: tiered session load, weekly volume, monotony, ACWR,
wellness composite, and plan compliance.

Pure functions over ``list[Workout]`` / ``list[Wellness]`` / ``list[Session]``
-- no I/O, no LLM calls. `cli.py`'s ``summarize`` command is the only caller
that turns these into a printed rollup; `adapt.py` calls straight into this
module for its rule table.

Every named constant below cites its source file per CLAUDE.md's "every
engine constant must cite its library/ file" rule. Two citation classes
appear, same convention as `plan.py` and `zones.py`:
  * `library/reference_list.md` entries that are already curated and
    verified (cited by author/year).
  * PROVISIONAL citations to `library/03-periodization.md` (load-monitoring
    conventions), authored alongside this module on Day 4.

**Design principle (added when the tiered session-load fallback was built,
see `library/03-periodization.md`'s "Load monitoring" section for the full
writeup): a workout's real training load does not depend on whether the
athlete bothered to survey it.** RPE adds fidelity on top of a real,
objective load number -- it does not gate whether a load number exists at
all. Confirmed against Renee's real logged history: 63 workouts synced from
her watch via intervals.icu, but only 1 carries an RPE (the other 62 are
pure device telemetry -- HR, pace -- with no subjective survey attached). The
old behavior (`session_load` returning ``None`` for a missing RPE, and
`daily_loads` excluding that ``None`` from the day's total) made 62 of her 63
real workouts invisible to every load-monitoring signal built on
`daily_loads` (CTL/ATL/TSB, ACWR, monotony). `session_load` now falls
through four tiers of decreasing fidelity -- sRPE, HR-based TRIMP, swim
pace-based intensity, duration-only -- and only reaches the last tier (which
still returns a real number, never ``None``) when literally none of RPE, HR,
or (for a swim with a known CSS) pace are available. We never fabricate a
survey answer the athlete didn't give (the old `assume_default_rpe`/
`DEFAULT_RPE_WHEN_MISSING` escape hatch did exactly that, and has been
removed as dead code now that a real physiologically-grounded fallback
exists at every tier below sRPE).

**Known limitation, flagged honestly rather than silently smoothed over:**
the four tiers are NOT on a common numeric scale. sRPE (`duration_min *
rpe`, RPE on a 1-10 scale) and HR-based TRIMP (Banister's exponential
weighting, see below) are both real, cited training-load formulas, but they
were never designed to be summed interchangeably within the same athlete's
history -- a training session scored by TRIMP typically comes out to
roughly a third to a half of what the *same* effort would score via sRPE
(see the worked examples in `tests/unit/test_load.py`). `daily_loads` sums
whatever tier each individual workout resolves to, because that is still
strictly better than the old behavior (a real, lower-fidelity number beats
a silently-excluded workout), but a day mixing an sRPE-scored strength
session with a TRIMP-scored swim will under-represent the swim's relative
contribution compared to two sRPE-scored sessions. This is a real,
documented gap, not a solved problem -- a future pass could calibrate
TRIMP/pace-IF against this athlete's own historical sRPE-vs-HR data once
enough dual-logged sessions exist to fit a personal scaling factor, but
inventing an uncited scaling constant now would trade one silent
distortion for another. Revisit once Renee logs more RPE alongside her
watch data.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from swim_coach.models import Athlete, Session, Wellness, Workout

_SWIM_SPORTS = {"swim_pool", "swim_ow"}

# --- tiered session load --------------------------------------------------------

LoadTier = Literal["srpe", "hr_trimp", "pace_if", "duration"]


@dataclass(frozen=True)
class SessionLoad:
    """One workout's training-load estimate plus which tier produced it --
    callers that only need the number can read ``.value``; callers/debugging
    that need to know the estimate's fidelity (e.g. "is this day's total
    real sRPE or a lower-fidelity fallback?") read ``.tier``. Never silently
    dropped the way a bare ``None`` return used to be -- see module
    docstring.
    """

    value: float
    tier: LoadTier


# Tier 2: HR-based TRIMP (Banister heart-rate-reserve training impulse) ----------

TRIMP_MALE_COEFFICIENT = 0.64
TRIMP_MALE_EXPONENT = 1.92
TRIMP_FEMALE_COEFFICIENT = 0.86
TRIMP_FEMALE_EXPONENT = 1.67
# ✓ Verified by direct web search this session (title/authors/publisher/
# pages confirmed). Primary source: **Banister EW (1991)**, "Modeling Elite
# Athletic Performance," in *Physiological Testing of Elite Athletes* (Green
# HJ, McDougall JD, Wenger HA, eds), Human Kinetics, Champaign IL, pp.
# 403-424 -- the original TRIMP exponential heart-rate-reserve weighting,
# derived separately for men and women from each group's own blood-lactate
# profile as exercise intensity rises. Corroborated by **Morton RH,
# Fitz-Clarke JR, Banister EW (1990)**, "Modeling human performance in
# running," *Journal of Applied Physiology*, 69(3):1171-1177 -- same
# TRIMP family, running application, same author. `[ADAPTED:
# general-endurance]` -- not swim-specific, but this predates sRPE as the
# field's own original training-load method, applied here as the physio-
# logically-grounded fallback when sRPE isn't available. See
# `library/reference_list.md`'s "Injury & training load" section for the
# full citation entry and `library/15-tiered-session-load.md` for the
# full tiered-load writeup.
# ⚠ **Get this right**: several popular training-log/calculator sites
# reproduce this with the MALE 0.64 coefficient applied to both sexes and
# only the exponent swapped for women (i.e. "0.64 * e^(1.67*x)" for women).
# That does **not** match the primary source -- the coefficient AND the
# exponent both differ by sex. Confirmed via this session's own search
# before hardcoding either number.
#
# TRIMP = duration_min * HRR_fraction * weight(HRR_fraction), where
# HRR_fraction = (avg_hr - HRrest) / (HRmax - HRrest) and weight(x) =
# TRIMP_MALE_COEFFICIENT * e^(TRIMP_MALE_EXPONENT * x) for men,
# TRIMP_FEMALE_COEFFICIENT * e^(TRIMP_FEMALE_EXPONENT * x) for women.

# `estimate_hr_max` below has no dedicated constant -- HRmax is estimated
# as the highest `Workout.max_hr` ever logged in this athlete's own
# history, a Coach judgment / practitioner convention, NOT itself a
# peer-reviewed formula (there is no lab-tested HRmax on file, no fixed
# HRmax field on `Athlete`). The closest corroborating citation found this
# session is **~ Ausland Å., Kelemen B., Seiler S. (2026)**, "An
# Exploratory Study of Maximal Heart Rate Determination in Endurance
# Athletes: Laboratory Testing Versus Field Based," *Frontiers in Sports
# and Active Living*, 8:1806303 -- found real athlete-reported field-effort
# HRmax exceeded standard age-based formulas (Fox 220-age, Tanaka
# 208-0.7*age) by ~5-6 bpm on average, supporting field-observed data over
# generic formulas. Not an exact match for this convention (that paper
# compares self-reported *maximal-effort* HR against lab tests/formulas,
# not "highest incidentally observed HR across ordinary training
# sessions" -- this athlete's logged workouts are training, not
# standardized max-effort tests, so this proxy is a floor that can only
# rise as more history accumulates, never a confirmed ceiling). Flagged
# honestly as PROVISIONAL, not `[EVIDENCE]`.

HR_REST_LOOKBACK_READINGS = 5
# Coach judgment / PROVISIONAL: a short rolling average of the athlete's
# own most-recently-logged `Wellness.resting_hr` readings (most-recent-N,
# not a calendar-day window) -- recent enough to reflect a genuine change
# in resting fitness quickly, less noisy than a single reading. No
# swim-specific or general-endurance citation for this specific choice of
# N=5; library/03-periodization.md.

HR_REST_GENERIC_FALLBACK_BPM = 60.0
# Coach judgment / PROVISIONAL, not swim-specific: the commonly-cited
# normal adult resting-heart-rate range is ~60-100 bpm (American Heart
# Association patient-education material, "All About Heart Rate"), with
# trained endurance athletes often running at or below the bottom of that
# range. 60.0 is used ONLY when the athlete has never logged a single
# `resting_hr` wellness check-in -- deliberately the top of the commonly-
# cited "normal" range rather than a lower elite-athlete-typical value,
# because a HIGHER assumed HRrest *understates* the HRR fraction and
# therefore *understates* TRIMP -- the safer direction to be wrong in for
# an assumed number feeding a training-load estimate.
#
# Explicitly considered and rejected: deriving HRrest from the athlete's
# own lowest-ever *in-workout* avg_hr instead of a population default.
# Even an easy recovery swim's average HR sits well above true resting HR
# (measured supine/seated, not mid-exercise) -- that proxy would
# systematically UNDERSTATE HRrest, inflate the HRR fraction, and
# overestimate load, which is worse (both less accurate AND wrong in the
# less-safe direction) than the population fallback above.

# Tier 3: swim pace-based intensity (TSS-family formula) -------------------------

SWIM_TSS_INTENSITY_EXPONENT = 3.0
# ✓ Verified by direct web search this session. The general TSS-family
# shape (Coggan/TrainingPeaks cycling "Training Stress Score": `TSS =
# duration_hours * IF^2 * 100`, IF = Normalized Power / FTP -- a 1-hour
# ride exactly at FTP scores 100) comes from **Allen H., Coggan A. (2010)**,
# *Training and Racing with a Power Meter* (2nd ed.), VeloPress -- the
# originating practitioner text for TSS/IF, not a peer-reviewed journal
# source, same footing as this project's other TrainingPeaks-convention
# citations (see `CTL_TIME_CONSTANT_DAYS` below). TrainingPeaks' own
# swim-specific documentation ("Calculating Swimming TSS Score," confirmed
# by direct fetch this session) explicitly CUBES the intensity factor
# instead of squaring it: "because water presents more resistance than
# air, the physiological stress of swimming increases with increasing swim
# speed faster than ... running" -- i.e. this is a deliberate, documented
# swim-specific adaptation of the generic cycling formula, not an
# unexamined carry-over. `[ADAPTED: cycling]`, Confidence: medium (a
# widely-used practitioner convention with a stated physical rationale,
# not an independently validated exponent). Test: if this tier's swim
# loads consistently feel out of proportion to sRPE-scored swims of
# similar perceived effort once more dual-logged data exists, revisit the
# exponent before the HR-TRIMP tier's scale (see module docstring).
#
# IF = css_pace_s_per_100m / avg_pace_s_per_100m -- inverted from the
# power-based IF above because pace is a TIME value (lower = faster), so a
# faster (lower) avg_pace_s_per_100m must produce a HIGHER IF, not lower.
# swim_tss = duration_hours * IF^SWIM_TSS_INTENSITY_EXPONENT * 100.

# Tier 4: duration-only fallback --------------------------------------------------

DURATION_ONLY_ASSUMED_INTENSITY = 5
# Coach judgment, last resort only: the 1-10 RPE scale's "somewhat hard"
# midpoint, applied as `duration_min * DURATION_ONLY_ASSUMED_INTENSITY` ONLY
# when a workout has no RPE, no HR (or no usable HRmax/HRrest context), and
# is either not a swim or has no pace/CSS data -- i.e. every richer signal
# this module knows how to use has already been checked and failed.
# Deliberately kept on the same numeric scale as tier 1 (duration * a
# 1-10 value) purely so a duration-only fallback day doesn't create an
# even bigger scale discontinuity in the mixed-tier daily sum than tiers
# 2/3 already do (see module docstring's "known limitation" -- this is a
# scale-compatibility choice, not a claim about this specific workout's
# actual effort). This is NOT the old `assume_default_rpe` escape hatch --
# that let a caller *opt into* faking an RPE for exclusion purposes; this
# fires unconditionally as the guaranteed final tier so a workout is never
# simply absent from a load total for lack of one specific signal.
# library/03-periodization.md.


def estimate_hr_max(workouts: list[Workout]) -> float | None:
    """Working HRmax estimate: the highest `Workout.max_hr` ever logged
    across this athlete's own workout history (see the comment above this
    function for the practitioner-convention citation and its honest
    limits).

    Returns ``None`` if no workout in `workouts` has `max_hr` logged at all
    -- callers must treat that as "tier 2 (HR-based TRIMP) unavailable,"
    not as a 0 bpm HRmax.

    Deliberately computed from the FULL workout history every time, not
    truncated to "as of" some earlier date: a higher HR observed later
    still reflects the athlete's real physiological ceiling, and the
    estimate is meant to keep improving as more history accumulates, the
    same way a coach's own working estimate of an athlete's max would.
    """
    values = [w.max_hr for w in workouts if w.max_hr is not None]
    return float(max(values)) if values else None


def estimate_hr_rest(
    wellness: list[Wellness], as_of: date, *, lookback_readings: int = HR_REST_LOOKBACK_READINGS
) -> float:
    """Working HRrest estimate as of `as_of`: the mean of the athlete's most
    recent (up to `lookback_readings`) logged `Wellness.resting_hr` values
    dated on or before `as_of` -- see `HR_REST_LOOKBACK_READINGS` above.

    Always returns a real float, never ``None`` -- falls back to
    `HR_REST_GENERIC_FALLBACK_BPM` when the athlete has no `resting_hr`
    reading on or before `as_of` at all (including "never logged one").
    Readings *after* `as_of` are never used, so scoring an older workout
    doesn't borrow from resting-HR data that didn't exist yet at the time.
    """
    values = _daily_field_values(wellness, "resting_hr")
    recent_dates = sorted((d for d in values if d <= as_of), reverse=True)[:lookback_readings]
    if not recent_dates:
        return HR_REST_GENERIC_FALLBACK_BPM
    return statistics.mean(values[d] for d in recent_dates)


def _trimp_weighting_factor(hrr_fraction: float, sex: Literal["male", "female", "other"] | None) -> float:
    """Banister exponential weighting factor for one HRR fraction -- see
    the `TRIMP_*` constants' citation above. `sex` selects the coefficient
    pair; when unknown (`None`, e.g. this athlete's profile has no `sex`
    field set, or `"other"`, which the underlying research does not
    itself distinguish a curve for), this averages the male and female
    weighting curves rather than silently defaulting to one -- a deliberate
    neutral choice, not a resolved citation. Documented here, not just in
    a comment on the constants, because this is the one place the choice
    actually gets made.
    """
    male_weight = TRIMP_MALE_COEFFICIENT * math.exp(TRIMP_MALE_EXPONENT * hrr_fraction)
    if sex == "male":
        return male_weight
    female_weight = TRIMP_FEMALE_COEFFICIENT * math.exp(TRIMP_FEMALE_EXPONENT * hrr_fraction)
    if sex == "female":
        return female_weight
    return (male_weight + female_weight) / 2


def session_load(
    workout: Workout,
    *,
    hr_max: float | None = None,
    hr_rest: float | None = None,
    sex: Literal["male", "female", "other"] | None = None,
    css_pace_s_per_100m: float | None = None,
) -> SessionLoad:
    """One workout's training-load estimate, falling through four tiers of
    decreasing fidelity until one applies -- see module docstring for the
    design principle this replaces (missing RPE used to mean "excluded,"
    not "estimated from the next-best signal"). Always returns a real
    `SessionLoad`, never ``None`` -- tier 4 is unconditional.

    1. **sRPE** (`duration_min * rpe`) when `workout.rpe` is set --
       unchanged from the original Foster session-RPE model, highest
       fidelity because it's athlete-reported.
    2. **HR-based TRIMP** when `workout.avg_hr`, `hr_max`, and `hr_rest`
       are all available (`hr_max > hr_rest`, so a real HRR range exists).
       HRR_fraction is clamped to `[0.0, 1.0]`: a value below 0 would mean
       `avg_hr` sits below the assumed resting baseline (only possible if
       `hr_rest`'s estimate is itself too high) and a value above 1 would
       mean the athlete exceeded the current `hr_max` estimate (expected
       to happen occasionally -- `estimate_hr_max` is a floor, not a
       confirmed ceiling) -- letting either case go unclamped would feed
       an out-of-domain input into the exponential weighting and produce
       a nonsensical (negative or runaway) load.
    3. **Swim pace-based intensity** (a TSS-family formula) when tier 2
       isn't available, the workout is a swim (`swim_pool`/`swim_ow`), and
       both `workout.avg_pace_s_per_100m` and `css_pace_s_per_100m` are
       known and positive.
    4. **Duration-only** fallback (`DURATION_ONLY_ASSUMED_INTENSITY`) --
       unconditional, so a workout is never simply absent from a load
       total for lack of one specific signal.
    """
    if workout.rpe is not None:
        return SessionLoad(value=workout.duration_min * workout.rpe, tier="srpe")

    if (
        workout.avg_hr is not None
        and hr_max is not None
        and hr_rest is not None
        and hr_max > hr_rest
    ):
        hrr_fraction = (workout.avg_hr - hr_rest) / (hr_max - hr_rest)
        hrr_fraction = max(0.0, min(1.0, hrr_fraction))
        weight = _trimp_weighting_factor(hrr_fraction, sex)
        trimp = workout.duration_min * hrr_fraction * weight
        return SessionLoad(value=trimp, tier="hr_trimp")

    if (
        workout.sport in _SWIM_SPORTS
        and workout.avg_pace_s_per_100m is not None
        and workout.avg_pace_s_per_100m > 0
        and css_pace_s_per_100m is not None
        and css_pace_s_per_100m > 0
    ):
        intensity_factor = css_pace_s_per_100m / workout.avg_pace_s_per_100m
        duration_hours = workout.duration_min / 60.0
        swim_tss = duration_hours * (intensity_factor**SWIM_TSS_INTENSITY_EXPONENT) * 100.0
        return SessionLoad(value=swim_tss, tier="pace_if")

    return SessionLoad(
        value=workout.duration_min * DURATION_ONLY_ASSUMED_INTENSITY, tier="duration"
    )


# --- volume & daily load series -----------------------------------------------


def _in_week(d: date, week_start: date) -> bool:
    return week_start <= d < week_start + timedelta(days=7)


def weekly_volume_m(workouts: list[Workout], week_start: date) -> int:
    """Total logged swim distance (meters) in the 7-day window starting
    ``week_start`` (inclusive) through ``week_start + 6 days``.

    Only swim sports (`swim_pool`, `swim_ow`) count toward volume --
    strength/recovery sessions have no `distance_m`. This is the "completed"
    counterpart to `WeekPlan.target_volume_m`.
    """
    return sum(
        w.distance_m
        for w in workouts
        if w.sport in _SWIM_SPORTS and _in_week(w.date, week_start)
    )


def daily_loads(
    workouts: list[Workout],
    *,
    athlete: Athlete | None = None,
    wellness: list[Wellness] | None = None,
) -> dict[date, float]:
    """Total tiered training load per calendar date, across *all* sports.

    Unlike ``weekly_volume_m``, every sport counts here -- training load is
    sport-agnostic total stress (a strength or recovery session still costs
    something), not swim-specific volume.

    Every workout now contributes a real number -- `session_load`'s tier-4
    fallback is unconditional, so (unlike the pre-tiered-fallback behavior)
    a day is never silently absent from the returned dict just because none
    of its workouts had a logged RPE; a day only stays out of the dict if it
    has no workouts logged at all (equivalent to zero for lookup purposes
    via ``.get(day, 0.0)``, same convention as before).

    `athlete` (for `sex`/`css_pace_s_per_100m`) and `wellness` (for
    `resting_hr` history) feed tiers 2/3's context -- both optional so
    existing callers that only have workouts on hand still get tier-1
    (sRPE) and tier-4 (duration-only) behavior unchanged; passing them in
    is what unlocks tiers 2/3 for RPE-less workouts. `estimate_hr_max` is
    computed once from the full `workouts` list (not per-workout) since
    it's a single working ceiling for the whole history, not a per-day
    figure -- see that function's docstring. `estimate_hr_rest` IS
    evaluated per-workout, anchored to each workout's own date, so scoring
    an old workout never borrows from resting-HR data logged after it.
    """
    wellness = wellness if wellness is not None else []
    hr_max = estimate_hr_max(workouts)
    sex = athlete.sex if athlete is not None else None
    css_pace_s_per_100m = athlete.css_pace_s_per_100m if athlete is not None else None

    totals: dict[date, float] = {}
    for workout in workouts:
        load = session_load(
            workout,
            hr_max=hr_max,
            hr_rest=estimate_hr_rest(wellness, workout.date),
            sex=sex,
            css_pace_s_per_100m=css_pace_s_per_100m,
        ).value
        totals[workout.date] = totals.get(workout.date, 0.0) + load
    return totals


# --- monotony ------------------------------------------------------------------


def monotony(daily_load_values: dict[date, float]) -> float | None:
    """Foster daily-load monotony = mean(daily loads) / stdev(daily loads).

    Coach-judgment application of the standard monotony bookkeeping method
    (not itself an [EVIDENCE: swim-ultra] claim) -- library/03-periodization.md.
    High monotony (little day-to-day variation) is associated with
    overtraining risk in the broader load-monitoring literature even at
    moderate absolute loads.

    Guards the degenerate cases -- fewer than 2 days of data, or zero
    variation (stdev == 0, e.g. every day identical or only one non-zero
    day) -- by returning ``None`` rather than raising ZeroDivisionError or
    reporting a misleading monotony of 0.
    """
    values = list(daily_load_values.values())
    if len(values) < 2:
        return None
    stdev = statistics.stdev(values)
    if stdev == 0:
        return None
    return statistics.mean(values) / stdev


# --- acute:chronic workload ratio (ACWR) --------------------------------------

ACWR_ACUTE_WINDOW_DAYS = 7
ACWR_CHRONIC_WINDOW_DAYS = 28
# Simple/"coupled" rolling-average ACWR (7-day load sum vs. a 28-day average
# rescaled to weekly units), chosen over an exponentially-weighted moving
# average for transparency and because this project's most actionable
# injury-risk signal for long-swim progression -- "don't exceed the prior
# 30-day longest single swim by >10%" (Garmin-RunSafe cohort,
# library/reference_list.md) -- is implemented directly in `adapt.py`'s
# long-swim ladder, not through ACWR. library/03-periodization.md.
#
# ACWR caveat (library/reference_list.md, Feijen S. et al. 2021): elevated
# ACWR was associated with shoulder pain in *youth* swimmers, but the odds-
# ratio confidence interval's lower bound sits near 1.0 (marginal), and
# "ACWR methodology is broadly criticized" -- the Garmin-RunSafe cohort
# separately found week-to-week ratio/ACWR to be weak predictors compared to
# the single-session-vs-30-day-longest check. Confidence: low. Treat this
# ratio as a coarse secondary signal (used only for the wellness/volume
# "cut volume" rule in adapt.py), not a precise injury forecast.


def acute_chronic_ratio(
    workouts: list[Workout],
    as_of: date,
    *,
    athlete: Athlete | None = None,
    wellness: list[Wellness] | None = None,
) -> float | None:
    """7-day load sum divided by a 28-day average load, rescaled to weekly
    units so both sides are directly comparable (a ratio of ~1.0 means
    "training like a normal week"; see module-level ACWR caveat above).

    ``as_of`` is the last day included in both windows (inclusive). Returns
    ``None`` if the 28-day chronic window has zero total load (nothing to
    compare the acute window against). `athlete`/`wellness` are forwarded
    straight to `daily_loads` -- see that function's docstring for what
    they unlock.
    """
    loads = daily_loads(workouts, athlete=athlete, wellness=wellness)
    acute = sum(
        loads.get(as_of - timedelta(days=i), 0.0) for i in range(ACWR_ACUTE_WINDOW_DAYS)
    )
    chronic_sum = sum(
        loads.get(as_of - timedelta(days=i), 0.0) for i in range(ACWR_CHRONIC_WINDOW_DAYS)
    )
    chronic_weekly_avg = chronic_sum / (ACWR_CHRONIC_WINDOW_DAYS / ACWR_ACUTE_WINDOW_DAYS)
    if chronic_weekly_avg == 0:
        return None
    return acute / chronic_weekly_avg


# --- CTL / ATL / TSB (Banister impulse-response) --------------------------------

CTL_TIME_CONSTANT_DAYS = 42
ATL_TIME_CONSTANT_DAYS = 7
# PROVISIONAL -- library/03-periodization.md (load-monitoring conventions).
# These are the standard cycling/TrainingPeaks Banister-model time constants
# (42-day "Chronic Training Load"/fitness, 7-day "Acute Training Load"/
# fatigue), NOT yet verified for swimming specifically -- they're carried
# over from endurance-cycling load-monitoring practice as Coach judgment,
# the same way `acute_chronic_ratio`'s windows above are `[ADAPTED: running]`.
#
# Specific, flagged citation debt: Thomas, Mujika & Busso (2008), "A model
# study of optimal training reduction during pre-event taper in elite
# swimmers" -- *Journal of Sports Sciences*, 26(6):643-652 -- is real and
# verified by direct web search this session (title/authors/journal/volume/
# pages confirmed), and comes from the same body of taper/fatigue-modeling
# research this constant should eventually be checked against. Elite
# swimmers training 45-50 km/week have reportedly shown a measured fatigue
# time constant around **19 days**, not the 7-day cycling convention used
# here -- but that specific number is sourced only from a secondary summary
# of the paper found this session, not from reading the paper's own primary
# text (it's paywalled; not yet accessible). The citation itself is trusted;
# the number attached to it is not yet independently confirmed the way this
# project's evidence discipline requires -- see `reference_list.md`'s entry
# for the same caveat.
#
# Practical consequence: using ATL_TIME_CONSTANT_DAYS = 7 here may
# materially misjudge how fast this athlete's fatigue actually clears --
# a true ~19-day time constant would make ATL rise and fall much more
# slowly than this module currently models, softening apparent TSB swings
# considerably. Revisit both this constant and the citation above once
# direct access to Thomas, Mujika & Busso (2008)'s primary text is
# available to confirm (or correct) the 19-day figure.


def ctl_atl_tsb_series(
    daily_load_values: dict[date, float],
    *,
    ctl_tau_days: float = CTL_TIME_CONSTANT_DAYS,
    atl_tau_days: float = ATL_TIME_CONSTANT_DAYS,
) -> list[tuple[date, float, float, float]]:
    """CTL ("fitness"), ATL ("fatigue"), and TSB ("form" = CTL - ATL) as
    exponentially-weighted moving averages of daily sRPE load -- the
    standard Banister impulse-response model, in contrast to
    ``acute_chronic_ratio``'s rolling-window ACWR above.

    Walks every calendar day from the earliest to the latest date present
    in ``daily_load_values`` (inclusive), same "day with no logged load
    counts as zero" convention ``daily_loads``/``monotony`` already use --
    a day missing from the dict is treated as a zero-load day, not skipped.
    Seeded at ``CTL = ATL = 0`` immediately before the first day in range,
    then for each day: ``CTL_t = CTL_{t-1} + (load_t - CTL_{t-1}) /
    ctl_tau_days``, ``ATL_t = ATL_{t-1} + (load_t - ATL_{t-1}) /
    atl_tau_days``, ``TSB_t = CTL_t - ATL_t``.

    Returns one ``(date, ctl, atl, tsb)`` tuple per calendar day in range,
    sorted ascending -- same "full series, not a single point-in-time
    number" philosophy as ``wellness_trend`` above, since a trend is what's
    actually useful for spotting a slide.

    Read-only/informational: this feeds athlete-facing context and
    ``get_plan_summary``, not ``plan.py``'s periodization or taper math.

    **Known limitation -- cold start:** seeding both series at 0 means
    early values in a short history aren't meaningful CTL/ATL estimates yet
    -- they're still climbing from zero, not reflecting genuine fitness/
    fatigue. Treat the series as warmed up only after roughly a few
    multiples of the longer time constant (``ctl_tau_days``) worth of days
    have accumulated; don't read early-series values as real fitness/
    fatigue levels.
    """
    if not daily_load_values:
        return []
    start = min(daily_load_values)
    end = max(daily_load_values)
    ctl = 0.0
    atl = 0.0
    series: list[tuple[date, float, float, float]] = []
    day = start
    while day <= end:
        load = daily_load_values.get(day, 0.0)
        ctl = ctl + (load - ctl) / ctl_tau_days
        atl = atl + (load - atl) / atl_tau_days
        series.append((day, ctl, atl, ctl - atl))
        day += timedelta(days=1)
    return series


# --- wellness composite ---------------------------------------------------------


def wellness_composite(entry: Wellness) -> float | None:
    """Daily wellness composite, scaled 1-5 (higher = better recovered).

    mean(sleep_quality, 6-stress, 6-soreness, motivation) -- each term is
    already on the `Wellness` model's native 1-5 scale; stress and soreness
    are inverted (6-x) so every term points the same direction (higher =
    better) before averaging. Coach judgment: this specific weighting/
    composite is Andrew's own scoring of standard wellness-questionnaire
    fields, not an [EVIDENCE] claim -- library/03-periodization.md.

    Returns `None` if any of the four subjective fields is missing (e.g. a
    sync-only row populated by backend/app/sync.py from intervals.icu, which
    only ever carries resting_hr/hrv) -- never derive a fabricated composite
    from a partial subjective set or from objective data alone, same "honest
    None over fabricated number" convention as `monotony()`/
    `wellness_baseline_deviation()` above.
    """
    fields = (entry.sleep_quality, entry.stress, entry.soreness, entry.motivation)
    if any(f is None for f in fields):
        return None
    sleep_quality, stress, soreness, motivation = fields
    return (sleep_quality + (6 - stress) + (6 - soreness) + motivation) / 4


def wellness_trend(entries: list[Wellness]) -> list[tuple[date, float]]:
    """Date-sorted (date, wellness_composite) series, one point per entry
    that has a usable composite.

    Convenience wrapper for the CLI's ``summarize`` command ("wellness
    trend") and for `/adapt`'s judgment review -- a raw series is more
    useful for spotting a slide than a single averaged number.

    Entries with no usable composite (e.g. sync-only rows -- see
    `wellness_composite`) are silently excluded, same "day with nothing to
    report doesn't appear" convention `daily_loads` already uses, rather than
    emitting a `None`-valued point.
    """
    return sorted(
        (entry.date, composite)
        for entry in entries
        if (composite := wellness_composite(entry)) is not None
    )


# --- wellness baseline deviation (RHR / HRV fatigue cross-check) --------------

WELLNESS_BASELINE_ACUTE_WINDOW_DAYS = 7
WELLNESS_BASELINE_CHRONIC_WINDOW_DAYS = 28
# PROVISIONAL -- library/03-periodization.md (load-monitoring conventions).
# Reuses acute_chronic_ratio's 7-day/28-day *coupled* window shape (the
# chronic window includes the acute window, same as ACWR above) purely for
# consistency across this module's rolling-baseline signals -- not because
# 7/28 has been independently validated for daily wellness metrics the way
# it's carried for training load.
#
# The closest swim-specific data point found this session --
# **Kamandulis et al. (2020)**, 22 national-level adolescent swimmers over
# 11 weeks -- found day-to-day HRV alone had *limited* value for estimating
# an athlete's load/tolerance balance, but a consistent ~4.5% HRV
# *reduction* emerged after 3-5 **consecutive** high-volume (>6 km/day)
# days, and HRV correlated inversely (r=-0.35, p<0.05) with large
# (>7 km/day) week-to-week training-load shifts. That's evidence for a
# shorter acute window (~3-5 days) arguably mattering more than a 7-day
# one for HRV specifically -- but "3-5 consecutive high-volume days" is a
# different measurement than "mean of the last N calendar days" (this
# function's shape), so it isn't a direct swap-in citation for
# WELLNESS_BASELINE_ACUTE_WINDOW_DAYS. Treat 7/28 as a defensible,
# consistency-driven default, not a resolved citation the way
# `reference_list.md`'s verification legend expects for an `[EVIDENCE]`
# claim -- same citation-debt posture as `CTL_TIME_CONSTANT_DAYS`/
# `ATL_TIME_CONSTANT_DAYS` above.


def _daily_field_values(entries: list[Wellness], field: str) -> dict[date, float]:
    """Date -> value map for one optional `Wellness` field, skipping entries
    where it's `None` -- both `resting_hr` and `hrv` are optional fields an
    athlete may not log every day (or at all)."""
    values: dict[date, float] = {}
    for entry in entries:
        value = getattr(entry, field)
        if value is None:
            continue
        values[entry.date] = float(value)
    return values


def _window_mean(values: dict[date, float], as_of: date, window_days: int) -> float | None:
    """Mean of whatever values fall in the ``window_days`` ending at
    ``as_of`` (inclusive) -- unlike ``daily_loads``' "missing day counts as
    zero" convention, a day with no logged wellness entry is *skipped*
    here, not treated as zero (a missing resting_hr reading is not a
    resting_hr of zero). Returns ``None`` if the window contains no values
    at all.
    """
    present = [values[d] for i in range(window_days) if (d := as_of - timedelta(days=i)) in values]
    if not present:
        return None
    return statistics.mean(present)


def _pct_deviation(
    values: dict[date, float], as_of: date, acute_window_days: int, chronic_window_days: int
) -> float | None:
    acute_mean = _window_mean(values, as_of, acute_window_days)
    chronic_mean = _window_mean(values, as_of, chronic_window_days)
    if acute_mean is None or chronic_mean is None or chronic_mean == 0:
        return None
    return (acute_mean - chronic_mean) / chronic_mean * 100.0


def wellness_baseline_deviation(
    entries: list[Wellness],
    as_of: date,
    *,
    acute_window_days: int = WELLNESS_BASELINE_ACUTE_WINDOW_DAYS,
    chronic_window_days: int = WELLNESS_BASELINE_CHRONIC_WINDOW_DAYS,
) -> dict[str, float | None]:
    """Percent deviation of the recent (acute-window) average from the
    athlete's own longer-term (chronic-window) average, computed
    independently for `resting_hr` and `hrv` -- the same acute-vs-chronic
    rolling-window shape as `acute_chronic_ratio` above (coupled: the
    chronic window includes the acute window), applied to two wellness
    fields instead of training load.

    Returns ``{"resting_hr_pct_deviation": ..., "hrv_pct_deviation": ...}``,
    each ``float | None``. A field is ``None`` whenever there isn't enough
    data to trust the number -- no logged values for that field at all, or
    (critically) no logged value inside the *acute* window even if older
    chronic-window history exists, since a deviation computed only from
    stale history would misrepresent "right now" as "computed as of
    now". `_window_mean`'s missing-day-is-skipped (not zero) convention
    keeps a single missed check-in from distorting either average.

    **Why this exists, and why it's a separate field from
    `ctl_atl_tsb_series` rather than folded into it:** `ctl_atl_tsb_series`
    is built entirely from sRPE training load, whose *validity* as a
    training-load signal is well-supported (`Wallace, Slattery & Coutts
    2009` -- swim-specific `[EVIDENCE: swim]` support for session-RPE as a
    training-load measure) but whose *reliability* (consistency of the
    same effort producing the same reported RPE) is more mixed:
    `Haddad et al. (2017)`'s review of the session-RPE literature reports
    ICC values for session-RPE ranging from ~0.55 (Scott et al. 2013,
    Australian football, "fair"/borderline-"good") to ~0.95 (excellent) in
    other sports/protocols -- no swim-specific *reliability* number was
    found (only the swim-specific *validity* study above), consistent with
    this project's existing citation-debt pattern of "validity is better
    evidenced than reliability" for this method. `resting_hr`/`hrv` are
    physiologically measured, not self-reported, so they corroborate (or
    fail to corroborate) the sRPE-derived TSB trend from an independent
    measurement channel -- `Bosquet et al. (2008)`'s systematic review
    found resting-HR elevation during overreach real but small-to-moderate
    in magnitude (may fall within day-to-day variability read as a single
    number, hence this function reports a *trend-relative* percentage
    rather than a raw value), and `Kamandulis et al. (2020)` (above) is
    the swim-specific citation that HRV suppression under sustained load is
    real but easy to miss without comparing against the athlete's own
    rolling baseline, exactly what this function does. Per this project's
    "multiple independent signals, not one master number" convention
    (ACWR/monotony/wellness-composite/CTL-ATL-TSB already coexist rather
    than merge), this stays its own clearly-labeled field -- a
    corroborating cross-check for `ctl_atl_tsb_series`'s TSB, not a
    replacement or a blend into it. See `library/10-recovery-hrv.md`'s
    "Oura device trust" section for the separate question of *how much to
    trust the underlying device reading itself* (not addressed here).

    Sign convention (deliberately asymmetric, since "worse" points opposite
    ways for these two fields): a positive `resting_hr_pct_deviation` means
    recent RHR sits *above* baseline (elevated = a fatigue signal); a
    negative `hrv_pct_deviation` means recent HRV sits *below* baseline
    (suppressed = a fatigue signal). Neither field is inverted/rescaled to
    force "higher = worse" onto both -- read each field's own sign in light
    of its own direction.
    """
    rhr_values = _daily_field_values(entries, "resting_hr")
    hrv_values = _daily_field_values(entries, "hrv")
    return {
        "resting_hr_pct_deviation": _pct_deviation(
            rhr_values, as_of, acute_window_days, chronic_window_days
        ),
        "hrv_pct_deviation": _pct_deviation(
            hrv_values, as_of, acute_window_days, chronic_window_days
        ),
    }


# --- compliance ------------------------------------------------------------------


def compliance(planned_sessions: list[Session], workouts: list[Workout]) -> float:
    """Percentage of planned swim volume actually completed.

    planned_m = sum of `distance_m` across `planned_sessions` with sport in
    {swim_pool, swim_ow} (strength/recovery sessions have no `distance_m`
    and aren't volume-comparable, so they're excluded rather than coerced to
    zero). completed_m = sum of `distance_m` across `workouts` with sport in
    {swim_pool, swim_ow}, over whatever period the caller already filtered
    both lists to (e.g. one week).

    Returns ``completed_m / planned_m * 100``. Can exceed 100 (over-
    delivered). Returns 0.0 if nothing swim-related was planned (can't be
    "non-compliant" with an empty plan).
    """
    planned_m = sum(
        s.distance_m or 0 for s in planned_sessions if s.sport in _SWIM_SPORTS
    )
    if planned_m == 0:
        return 0.0
    completed_m = sum(w.distance_m for w in workouts if w.sport in _SWIM_SPORTS)
    return completed_m / planned_m * 100
