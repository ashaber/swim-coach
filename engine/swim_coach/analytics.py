"""Derived workout analytics: cardiac drift, splits, pause accounting, SWOLF.

Pure functions over `WorkoutLap`/`WorkoutLength`/`WorkoutPause` (and an
optional in-memory series dict -- see `parse_files.parse_fit`'s
`WorkoutDraft.series`) -- no I/O, no LLM calls. `cli.py`'s `ingest` and
`analyze` commands are the only callers that turn these into a persisted
`WorkoutAnalytics` (via `compute_analytics`).

Every named constant below cites `library/11-workout-analytics.md`, which is
explicitly marked provisional pending a full research pass -- see that
file's header and "What's still a gap" section.
"""

from __future__ import annotations

import statistics
from typing import Literal

from swim_coach.models import WorkoutLap, WorkoutLength, WorkoutPause

# --- constants (library/11-workout-analytics.md) --------------------------------------

SPLIT_EVEN_BAND_PCT = 2.0
# Coach judgment: a first-half/second-half pace difference within +/-2% is
# labeled "even" rather than "negative"/"positive". library/11-workout-
# analytics.md ("Pause-gap threshold and even-split band").

GAP_THRESHOLD_S = 30.0
# Coach judgment: a record-frame timestamp gap longer than this is treated
# as a real pause, not GPS/sensor smart-recording variance (observed real
# gaps up to ~19s on a real kayak .fit export). library/11-workout-
# analytics.md ("Pause-gap threshold and even-split band").

CARDIAC_DRIFT_FLAG_PCT = 5.0
# [ADAPTED: general-endurance] Confidence: low -- an engineering default,
# not a validated cutoff; no swim-specific citation exists yet.
# library/11-workout-analytics.md ("Cardiac drift / aerobic decoupling").

SWOLF_MIN_LENGTHS = 8
# Coach judgment: minimum active-length count before computing a SWOLF
# first-quartile-vs-last-quartile trend, a floor against noisy small-sample
# quartiles. library/11-workout-analytics.md ("SWOLF as a stroke-efficiency
# proxy").

SWOLF_OUTLIER_DURATION_X = 3.0
# Coach judgment: an "active" length whose duration exceeds this multiple of
# the median active-length duration is a device auto-length-detection miss
# (e.g. a 1136s length among ~30s lengths in a real pool export), not a swum
# length -- excluded from the SWOLF trend. library/11-workout-analytics.md
# ("SWOLF as a stroke-efficiency proxy").


# --- cardiac drift ----------------------------------------------------------------


def _series_halves_hr_per_speed(
    series: dict, pauses: list[WorkoutPause] | None
) -> tuple[float, float] | None:
    """Mean HR / mean speed for each half of the series' moving time,
    excluding samples that fall inside a pause span. Returns None if there's
    no usable HR or speed data."""
    t_s = series.get("t_s")
    hr = series.get("hr")
    speed = series.get("speed_mps")
    if not t_s or not hr or not speed:
        return None

    pauses = pauses or []

    def in_pause(t: float) -> bool:
        return any(p.start_offset_s <= t < p.start_offset_s + p.duration_s for p in pauses)

    samples = [
        (t, h, s)
        for t, h, s in zip(t_s, hr, speed)
        if h is not None and s is not None and s > 0 and not in_pause(t)
    ]
    if len(samples) < 4:
        return None

    mid_t = (samples[0][0] + samples[-1][0]) / 2
    first_half = [(h, s) for t, h, s in samples if t < mid_t]
    second_half = [(h, s) for t, h, s in samples if t >= mid_t]
    if not first_half or not second_half:
        return None

    def hr_per_speed(pairs: list[tuple[float, float]]) -> float:
        mean_hr = statistics.mean(h for h, _ in pairs)
        mean_speed = statistics.mean(s for _, s in pairs)
        return mean_hr / mean_speed

    return hr_per_speed(first_half), hr_per_speed(second_half)


def _lap_pace_s_per_100m(lap: WorkoutLap) -> float | None:
    """`avg_pace_s_per_100m` when set, else derived from duration_s/distance_m."""
    if lap.avg_pace_s_per_100m is not None:
        return lap.avg_pace_s_per_100m
    if lap.distance_m:
        return lap.duration_s / (lap.distance_m / 100)
    return None


def _laps_halves_hr_per_pace(laps: list[WorkoutLap]) -> tuple[float, float] | None:
    """Mean HR / mean pace(s/100m) for each half of a lap list, only using
    laps that carry both avg_hr and a derivable pace. Returns None if fewer
    than 2 usable laps."""
    usable = [
        (lap.avg_hr, _lap_pace_s_per_100m(lap))
        for lap in laps
        if lap.avg_hr is not None and _lap_pace_s_per_100m(lap) is not None
    ]
    if len(usable) < 2:
        return None
    mid = len(usable) // 2
    first_half, second_half = usable[:mid] or usable[:1], usable[mid:]
    if not first_half or not second_half:
        return None

    def hr_per_pace(subset: list[tuple[int, float]]) -> float:
        mean_hr = statistics.mean(hr for hr, _ in subset)
        mean_pace = statistics.mean(pace for _, pace in subset)
        # Slower pace (higher s/100m) = lower speed, so use pace directly as
        # the "effort cost" denominator's inverse: HR * pace (not HR / pace)
        # keeps the ratio rising when HR rises OR pace gets slower (both bad).
        return mean_hr * mean_pace

    return hr_per_pace(first_half), hr_per_pace(second_half)


def cardiac_drift(
    series: dict | None,
    *,
    laps: list[WorkoutLap],
    pauses: list[WorkoutPause] | None = None,
) -> float | None:
    """Pa:HR aerobic decoupling between the first and second half of moving
    time. Prefers the time-series (HR vs. speed, pause spans excluded) when
    available; falls back to per-lap avg_hr + avg_pace when at least 2 laps
    carry both. Returns None when no HR data exists at all.

    See library/11-workout-analytics.md ("Cardiac drift / aerobic
    decoupling") -- CARDIAC_DRIFT_FLAG_PCT is the suggested flag threshold,
    not applied inside this function.
    """
    if series:
        halves = _series_halves_hr_per_speed(series, pauses)
        if halves is not None:
            first, second = halves
            if first == 0:
                return None
            return (second / first - 1) * 100

    halves = _laps_halves_hr_per_pace(laps)
    if halves is None:
        return None
    first, second = halves
    if first == 0:
        return None
    return (second / first - 1) * 100


# --- splits -------------------------------------------------------------------------


def split_analysis(
    laps: list[WorkoutLap],
) -> tuple[Literal["negative", "even", "positive"] | None, float | None, float | None]:
    """Distance-weighted first-half/second-half pace (s/100m) and a
    negative/even/positive label, from a list of laps in chronological
    order. Restates `Saavedra J.M., Einarsson, et al. (2018)`'s open-water
    negative-split finding operationally (library/11-workout-analytics.md);
    the +/-SPLIT_EVEN_BAND_PCT even-split band itself is coach judgment, not
    from that paper.

    Returns (None, None, None) if fewer than 2 laps carry distance_m.
    """
    usable = [lap for lap in laps if lap.distance_m]
    if len(usable) < 2:
        return None, None, None

    total_distance = sum(lap.distance_m for lap in usable)
    half_distance = total_distance / 2

    first_distance = 0.0
    first_time = 0.0
    second_distance = 0.0
    second_time = 0.0
    for lap in usable:
        if first_distance < half_distance:
            first_distance += lap.distance_m
            first_time += lap.duration_s
        else:
            second_distance += lap.distance_m
            second_time += lap.duration_s

    if first_distance == 0 or second_distance == 0:
        return None, None, None

    first_pace = first_time / (first_distance / 100)
    second_pace = second_time / (second_distance / 100)

    diff_pct = (second_pace - first_pace) / first_pace * 100
    if abs(diff_pct) <= SPLIT_EVEN_BAND_PCT:
        label: Literal["negative", "even", "positive"] = "even"
    elif diff_pct < 0:
        label = "negative"  # second half faster
    else:
        label = "positive"  # second half slower

    return label, first_pace, second_pace


# --- pauses ---------------------------------------------------------------------------


def pause_summary(
    pauses: list[WorkoutPause], *, elapsed_min: float | None, moving_min: float | None
) -> dict:
    """Totals/count for a pause list, plus the elapsed/moving minutes passed
    through unchanged (convenience for building WorkoutAnalytics)."""
    pause_total_min = sum(p.duration_s for p in pauses) / 60.0
    return {
        "pause_count": len(pauses),
        "pause_total_min": pause_total_min,
        "elapsed_min": elapsed_min,
        "moving_min": moving_min,
    }


def projected_stop_time_min(feed_every_min: float, feed_len_min: float, total_hours: float) -> float:
    """Total minutes of planned feed stops over `total_hours`, feeding every
    `feed_every_min` minutes for `feed_len_min` minutes each time.

    E.g. projected_stop_time_min(30, 2, 10) == 40.0 (2 min every 30 min over
    10h = 20 feeds x 2 min).
    """
    if feed_every_min <= 0 or total_hours <= 0:
        return 0.0
    total_min = total_hours * 60
    num_feeds = total_min / feed_every_min
    return num_feeds * feed_len_min


# --- SWOLF trend ------------------------------------------------------------------------


def swolf_trend(lengths: list[WorkoutLength]) -> tuple[float, float, float] | None:
    """Mean SWOLF of the first vs. last quartile of active lengths (in
    logged order) plus the percent degradation from first to last quartile.
    Active lengths whose duration exceeds SWOLF_OUTLIER_DURATION_X times the
    median duration are excluded first (device auto-length-detection misses).
    Returns None if fewer than SWOLF_MIN_LENGTHS lengths remain
    (library/11-workout-analytics.md's SWOLF_MIN_LENGTHS floor).
    """
    with_swolf = [length for length in lengths if length.swolf is not None]
    if len(with_swolf) >= 2:
        median_duration = statistics.median(length.duration_s for length in with_swolf)
        with_swolf = [
            length
            for length in with_swolf
            if length.duration_s <= median_duration * SWOLF_OUTLIER_DURATION_X
        ]
    usable = [length.swolf for length in with_swolf]
    if len(usable) < SWOLF_MIN_LENGTHS:
        return None

    quartile = max(1, len(usable) // 4)
    first_quartile = usable[:quartile]
    last_quartile = usable[-quartile:]

    first_mean = statistics.mean(first_quartile)
    last_mean = statistics.mean(last_quartile)
    degradation_pct = (last_mean / first_mean - 1) * 100 if first_mean else 0.0

    return first_mean, last_mean, degradation_pct


# --- orchestrator -----------------------------------------------------------------------


def compute_analytics(
    *,
    laps: list[WorkoutLap],
    lengths: list[WorkoutLength],
    pauses: list[WorkoutPause],
    series: dict | None,
    elapsed_min: float | None,
    moving_min: float | None,
):
    """Build a swim_coach.models.WorkoutAnalytics from parsed workout parts.

    Imports WorkoutAnalytics lazily (function-local) to avoid a circular
    import at module load time (models.py does not import analytics.py, but
    keeping the import local here keeps the dependency direction obvious:
    analytics depends on models, not the reverse).
    """
    from swim_coach.models import WorkoutAnalytics

    drift = cardiac_drift(series, laps=laps, pauses=pauses)
    split_label, first_pace, second_pace = split_analysis(laps)
    pauses_summary = pause_summary(pauses, elapsed_min=elapsed_min, moving_min=moving_min)
    swolf = swolf_trend(lengths)

    return WorkoutAnalytics(
        cardiac_drift_pct=drift,
        split_label=split_label,
        first_half_pace_s_per_100m=first_pace,
        second_half_pace_s_per_100m=second_pace,
        elapsed_min=elapsed_min,
        moving_min=moving_min,
        pause_total_min=pauses_summary["pause_total_min"],
        pause_count=pauses_summary["pause_count"],
        swolf_first_quarter=swolf[0] if swolf else None,
        swolf_last_quarter=swolf[1] if swolf else None,
        swolf_degradation_pct=swolf[2] if swolf else None,
    )
