"""Training-load math: sRPE session load, weekly volume, monotony, ACWR,
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
"""

from __future__ import annotations

import statistics
from datetime import date, timedelta

from swim_coach.models import Session, Wellness, Workout

# --- sRPE session load --------------------------------------------------------

DEFAULT_RPE_WHEN_MISSING = 5
# Coach judgment: the 1-10 RPE scale's "somewhat hard" midpoint, used only
# when a workout has no logged RPE *and* the caller opts in via
# assume_default_rpe=True. library/03-periodization.md (load-monitoring
# conventions, to be authored). This is a deliberate approximation, not an
# [EVIDENCE] claim -- see `session_load` docstring for when it applies.

_SWIM_SPORTS = {"swim_pool", "swim_ow"}


def session_load(workout: Workout, *, assume_default_rpe: bool = False) -> float | None:
    """Session RPE (sRPE) training load for one workout = duration_min * rpe.

    Standard Foster session-RPE training-load model (duration x
    session-RPE); this specific formula is not itself an
    [EVIDENCE: swim-ultra] claim in `library/reference_list.md` -- it's a
    widely used, sport-agnostic training-load bookkeeping method, applied
    here as Coach judgment.

    Missing-RPE fallback: if ``workout.rpe`` is ``None`` (e.g. an ingested
    .fit/.tcx file with no subjective RPE attached), the default behavior is
    to return ``None`` -- callers (``daily_loads`` etc.) then *exclude* this
    session from load totals rather than silently guessing at its intensity.
    Pass ``assume_default_rpe=True`` to instead fall back to
    ``DEFAULT_RPE_WHEN_MISSING``, trading precision for coverage (useful when
    a rollup needs every logged session represented, e.g. weekly volume
    context alongside load).
    """
    if workout.rpe is None:
        if not assume_default_rpe:
            return None
        return workout.duration_min * DEFAULT_RPE_WHEN_MISSING
    return workout.duration_min * workout.rpe


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
    workouts: list[Workout], *, assume_default_rpe: bool = False
) -> dict[date, float]:
    """Total sRPE load per calendar date, across *all* sports.

    Unlike ``weekly_volume_m``, every sport counts here -- sRPE training
    load is sport-agnostic total stress (a strength or recovery session
    still costs something), not swim-specific volume. Workouts whose
    ``session_load`` is ``None`` (missing RPE, ``assume_default_rpe=False``)
    are excluded from their date's total rather than treated as zero load;
    a day with only such workouts simply doesn't appear in the returned
    dict (equivalent to zero for lookup purposes via ``.get(day, 0.0)``).
    """
    totals: dict[date, float] = {}
    for workout in workouts:
        load = session_load(workout, assume_default_rpe=assume_default_rpe)
        if load is None:
            continue
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
    workouts: list[Workout], as_of: date, *, assume_default_rpe: bool = False
) -> float | None:
    """7-day load sum divided by a 28-day average load, rescaled to weekly
    units so both sides are directly comparable (a ratio of ~1.0 means
    "training like a normal week"; see module-level ACWR caveat above).

    ``as_of`` is the last day included in both windows (inclusive). Returns
    ``None`` if the 28-day chronic window has zero total load (nothing to
    compare the acute window against).
    """
    loads = daily_loads(workouts, assume_default_rpe=assume_default_rpe)
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


def wellness_composite(entry: Wellness) -> float:
    """Daily wellness composite, scaled 1-5 (higher = better recovered).

    mean(sleep_quality, 6-stress, 6-soreness, motivation) -- each term is
    already on the `Wellness` model's native 1-5 scale; stress and soreness
    are inverted (6-x) so every term points the same direction (higher =
    better) before averaging. Coach judgment: this specific weighting/
    composite is Andrew's own scoring of standard wellness-questionnaire
    fields, not an [EVIDENCE] claim -- library/03-periodization.md.
    """
    return (entry.sleep_quality + (6 - entry.stress) + (6 - entry.soreness) + entry.motivation) / 4


def wellness_trend(entries: list[Wellness]) -> list[tuple[date, float]]:
    """Date-sorted (date, wellness_composite) series, one point per entry.

    Convenience wrapper for the CLI's ``summarize`` command ("wellness
    trend") and for `/adapt`'s judgment review -- a raw series is more
    useful for spotting a slide than a single averaged number.
    """
    return sorted((entry.date, wellness_composite(entry)) for entry in entries)


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
