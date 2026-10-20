"""Race-view numbers for a bike race: the race window, the first 40 s, and a sprint to the line.

Pure functions over the 1 Hz recording and the canonical laps; no I/O. The race window runs from the
race start to the finish line. The finish line is the lap mark again, so it is the end of the last
COMPARABLE canonical lap: a short fragment after it is the roll-out, not racing.

Constants are Coach judgment (no source pins them), tuned on the 2026-10-17/18 CX races.
"""

from __future__ import annotations

from bisect import bisect_left
from typing import Sequence

from swim_coach.analytics import normalized_power_w
from swim_coach.canonical_laps import _dist_between
from swim_coach.models import (
    CanonicalLap,
    FinishSprint,
    PreviousRaceStart,
    RaceOverview,
    RaceStartTrace,
    StartDip,
    Workout,
)
from swim_coach.mtb_dynamics import has_channel, mean_nonzero, mean_present, sum_grit, window_indices

START_TRACE_S = 40  # Coach judgment: a standing start is decided in the first 40 s; the PWA draws exactly this many seconds
DIP_FROM_S, DIP_TO_S = 2, 15  # Coach judgment: a dip inside the launch (after the first pedal strokes, within the 15 s mean) is a shift or a bobble
DIP_FRAC_OF_MEAN = 0.5  # Coach judgment: below half the 15 s mean is a gap in the effort, not variation
SPRINT_LOOKBACK_S = 60  # Coach judgment: the last minute is the run-in (it also locates the last second below race NP before the surge)
SPRINT_END_WITHIN_S = 10  # Coach judgment: a sprint to the line ends at the line; a 5 s effort that ended 10+ s before it (a corner exit) is not one
SPRINT_PEAK_S = 5  # Coach judgment: a 5 s mean is the shortest window that is a sprint and not a single spike
SPRINT_MIN_NP_MULT = 2.0  # Coach judgment: a sprint is at least twice race NP (10/17: 3.4x race NP in its best 5 s; 10/18 had no effort over 1.5x in its last 10 s)
SPRINT_TRACE_S = 15  # Coach judgment: the last 15 s cover the run-in and the sprint
KMH = 3.6


def finish_s(laps: Sequence[CanonicalLap]) -> float | None:
    """The finish line on the activity clock: the end of the last comparable lap, else None."""
    comparable = [l for l in laps if l.comparable]
    return comparable[-1].end_s if comparable else None


def _col(series: dict, key: str) -> list:
    return series.get(key) or []


def build_race_overview(series: dict, start_s: float, end_s: float) -> RaceOverview | None:
    """The race window's numbers; a channel the recording lacks is None."""
    t_s = series.get("t_s")
    if not t_s or end_s <= start_s:
        return None
    idx = window_indices(t_s, start_s, end_s)
    if not len(idx):
        return None
    duration = end_s - start_s
    power, hr, speed, cad = (_col(series, k) for k in ("power_w", "hr", "speed_mps", "cadence_rpm"))
    avg_p = mean_present(power, idx) if power else None
    window = {"t_s": [t_s[i] for i in idx], "power_w": [power[i] for i in idx]} if power else None
    np_w = normalized_power_w(window)
    dist = _dist_between(series, start_s, end_s) if has_channel(series, "dist_m") else None
    hrs = [hr[i] for i in idx if hr and hr[i] is not None]
    pw = [power[i] for i in idx if power and power[i] is not None]
    sp = [speed[i] for i in idx if speed and speed[i] is not None]
    cadence = mean_nonzero(cad, idx) if cad else None
    return RaceOverview(
        start_s=start_s, end_s=end_s, duration_s=round(duration, 1),
        distance_m=round(dist) if dist is not None else None,
        avg_hr=round(sum(hrs) / len(hrs)) if hrs else None, max_hr=round(max(hrs)) if hrs else None,
        avg_power_w=round(avg_p) if avg_p is not None else None, max_power_w=round(max(pw)) if pw else None,
        np_w=round(np_w) if np_w is not None else None,
        work_kj=round(avg_p * duration / 1000) if avg_p is not None else None,
        avg_speed_kmh=round(sum(sp) / len(sp) * KMH, 1) if sp else None,
        max_speed_kmh=round(max(sp) * KMH, 1) if sp else None,
        avg_cadence_rpm=round(cadence) if cadence is not None else None,
        total_grit=sum_grit(_col(series, "grit"), idx) if _col(series, "grit") else None,
    )


def _per_second(series: dict, key: str, start_s: float, seconds: int, scale: float = 1.0) -> list[float]:
    """The channel at start_s + 0 .. seconds-1 (the sample of that second; 0 where there is none)."""
    t_s, vals = series["t_s"], _col(series, key)
    out = []
    for k in range(seconds):
        i = bisect_left(t_s, start_s + k - 0.5)
        near = i < len(t_s) and abs(t_s[i] - (start_s + k)) < 0.5 and vals and vals[i] is not None
        out.append(vals[i] * scale if near else 0.0)
    return out


def build_race_start_trace(series: dict, start_s: float, previous: PreviousRaceStart | None = None) -> RaceStartTrace | None:
    """The first START_TRACE_S seconds from the gun, 1 Hz, with the start's headline numbers."""
    if not series.get("t_s") or not _col(series, "power_w"):
        return None
    power = [round(p) for p in _per_second(series, "power_w", start_s, START_TRACE_S)]
    speed = [round(v, 1) for v in _per_second(series, "speed_mps", start_s, START_TRACE_S, KMH)]
    mean_5, mean_15 = round(sum(power[:5]) / 5), round(sum(power[:15]) / 15)
    peak = max(power)
    top = max(speed)
    dip_at = min(range(DIP_FROM_S, DIP_TO_S + 1), key=lambda k: power[k])
    dip = StartDip(at_s=dip_at, power_w=power[dip_at]) if power[dip_at] < DIP_FRAC_OF_MEAN * mean_15 else None
    return RaceStartTrace(
        power_w=power, speed_kmh=speed, peak_w=peak, peak_at_s=power.index(peak), mean_5s_w=mean_5, mean_15s_w=mean_15,
        top_speed_kmh=top, top_speed_at_s=speed.index(top), dip=dip, previous=previous,
    )


def _best_window(p: Sequence[float], n: int, first_from: int) -> tuple[float, int]:
    """`(mean, first index)` of the best n-second window starting at index `first_from` or later."""
    starts = range(first_from, len(p) - n + 1)
    best = max(starts, key=lambda i: sum(p[i:i + n]))
    return sum(p[best:best + n]) / n, best


def build_finish_sprint(series: dict, finish: float, race_np_w: float | None) -> FinishSprint | None:
    """A sprint to the line, or None unless the best SPRINT_PEAK_S mean in the last minute is at least
    SPRINT_MIN_NP_MULT x race NP. The sprint is the contiguous seconds at/above that same bar around the
    peak; the arrays are the last SPRINT_TRACE_S seconds, the final sample being the second that ends at the line."""
    if not race_np_w or not series.get("t_s") or not _col(series, "power_w"):
        return None
    look = _per_second(series, "power_w", finish - SPRINT_LOOKBACK_S, SPRINT_LOOKBACK_S)
    mean_peak, first = _best_window(look, SPRINT_PEAK_S, len(look) - SPRINT_END_WITHIN_S - SPRINT_PEAK_S + 1)
    bar = SPRINT_MIN_NP_MULT * race_np_w
    if mean_peak < bar:
        return None
    speed = _per_second(series, "speed_mps", finish - SPRINT_LOOKBACK_S, SPRINT_LOOKBACK_S, KMH)
    centre = max(range(first, first + SPRINT_PEAK_S), key=lambda i: look[i])
    lo = hi = centre
    while lo > 0 and look[lo - 1] >= bar:
        lo -= 1
    while hi < len(look) - 1 and look[hi + 1] >= bar:
        hi += 1
    ramp = next((i for i in range(lo - 1, -1, -1) if look[i] < race_np_w), lo)  # the last second below race NP before the surge
    span = look[lo:hi + 1]
    tail = slice(len(look) - SPRINT_TRACE_S, len(look))
    return FinishSprint(
        duration_s=len(span), avg_w=round(sum(span) / len(span)), peak_w=round(max(span)),
        entry_speed_kmh=round(speed[ramp], 1), exit_speed_kmh=round(max(speed[lo:hi + 1]), 1),
        power_w=[round(x) for x in look[tail]], speed_kmh=[round(x, 1) for x in speed[tail]],
    )


def _when(w: Workout) -> tuple:
    return (w.date, w.started_at.timestamp() if w.started_at else 0.0)


def pick_previous_race_start(workouts: Sequence[Workout], current: Workout) -> PreviousRaceStart | None:
    """The athlete's most recent EARLIER race of the same kind (`sport_detail`) that has a race-start
    trace, as the side-by-side comparison. `workouts` is whatever the store holds (the caller's lookup)."""
    earlier = [
        w for w in workouts
        if w.id != current.id and w.effective_kind == "race" and w.sport_detail == current.sport_detail
        and _when(w) < _when(current) and w.analytics is not None and w.analytics.race_start is not None
    ]
    if not earlier:
        return None
    prev = max(earlier, key=_when)
    trace = prev.analytics.race_start
    return PreviousRaceStart(workout_id=str(prev.id), date=prev.date, power_w=trace.power_w,
                             mean_15s_w=trace.mean_15s_w, top_speed_kmh=trace.top_speed_kmh)
