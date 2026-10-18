"""Lap normalisation: merge auto-lap "double trigger" fragments back into full laps.

A device that auto-laps by position can fire twice per lap when the course passes the lap mark,
loops round a short hairpin and crosses back over the mark. The raw laps then alternate
`long, short, long, short ...` (e.g. 325 s / 1851 m, 17 s / 104 m). Treating the long piece as
"the lap" drops the hairpin plus whatever follows the mark -- often a sprint into the finish.

`merge_double_trigger_laps` folds each such fragment into the PRECEDING lap, so every full lap
starts at the same mark. Pure: no I/O, the input laps are never mutated (the raw device laps stay
as stored for the raw laps table).

A fragment is a lap that is short (at most `FRAGMENT_FRAC_OF_LONG` of the median long lap), follows
a long lap, and is followed by a long lap, nothing, or the final lap of the activity (the finish
remainder). With GPS at the fragment's start, its end and the preceding lap's start, it is merged
only when its end is within `START_LINE_RADIUS_M` of the lap mark (the preceding lap's start) and
its start within `FRAGMENT_START_RADIUS_M` (the first trigger fires on the approach). Without GPS the duration pattern alone is trusted, and only when it repeats
(`MIN_PATTERN_REPEATS`), so one genuine short lap is never swallowed.

Constants are Coach judgment, not sourced.
"""

from __future__ import annotations

import math
from statistics import median
from typing import Sequence

from swim_coach.models import WorkoutLap

FRAGMENT_FRAC_OF_LONG = 0.15  # Coach judgment: a hairpin re-trigger is a sliver of a lap (17 s of 320 s ~ 5%)
MIN_LONG_LAP_S = 120  # Coach judgment: shorter than this is a split, never a full lap (matches course_sectors.MIN_LAP_S)
MIN_PATTERN_REPEATS = 3  # Coach judgment: without GPS only a repeating long/short pattern is a double trigger
START_LINE_RADIUS_M = 30.0  # Coach judgment: a lap starting farther than this from the reference lap's start is not the same lap
FRAGMENT_START_RADIUS_M = 2 * START_LINE_RADIUS_M  # Coach judgment: the first trigger fires on the approach, 26-31 m short of the mark on the 2026-10-17 race
EARTH_M_PER_DEG = 111_320.0  # metres per degree of latitude (spherical earth, plenty for a 30 m test)


def start_point(series: dict | None, start_s: float) -> tuple[float, float] | None:
    """The (lat, lng) at the first record at/after `start_s`, or None without GPS there."""
    if not series:
        return None
    lat, lng = series.get("lat") or [], series.get("lng") or []
    i = next((i for i, t in enumerate(series["t_s"]) if t >= start_s), None)
    if i is None or i >= len(lat) or i >= len(lng) or lat[i] is None or lng[i] is None:
        return None
    return lat[i], lng[i]


def metres_apart(a: tuple[float, float], b: tuple[float, float]) -> float:
    dy = (a[0] - b[0]) * EARTH_M_PER_DEG
    dx = (a[1] - b[1]) * EARTH_M_PER_DEG * math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot(dx, dy)


def _is_fragment(laps: Sequence[WorkoutLap], i: int, long_ref_s: float) -> bool:
    """Short, after a long lap, and before a long lap, nothing, or the final lap."""
    if i == 0 or laps[i].duration_s > FRAGMENT_FRAC_OF_LONG * long_ref_s:
        return False
    if laps[i - 1].duration_s < MIN_LONG_LAP_S:
        return False
    nxt = i + 1
    return nxt >= len(laps) or laps[nxt].duration_s >= MIN_LONG_LAP_S or nxt == len(laps) - 1


def _at_the_mark(laps: Sequence[WorkoutLap], i: int, series: dict | None) -> bool | None:
    """GPS verdict: does fragment `i` start and end within the start-line radius of the lap mark
    (the preceding lap's start)? None when any of the three fixes is missing."""
    frag = laps[i]
    end_s = laps[i + 1].start_offset_s if i + 1 < len(laps) else frag.start_offset_s + frag.duration_s
    mark = start_point(series, laps[i - 1].start_offset_s)
    begin, end = start_point(series, frag.start_offset_s), start_point(series, end_s)
    if mark is None or begin is None or end is None:
        return None
    return metres_apart(mark, begin) <= FRAGMENT_START_RADIUS_M and metres_apart(mark, end) <= START_LINE_RADIUS_M


def _combine(a: WorkoutLap, b: WorkoutLap) -> WorkoutLap:
    """`b` folded into `a` (the preceding lap): summed time/distance, duration-weighted averages."""
    total = a.duration_s + b.duration_s

    def weighted(x: float | None, y: float | None) -> float | None:
        if x is None or y is None:
            return x if y is None else y
        return (x * a.duration_s + y * b.duration_s) / total

    hr = weighted(a.avg_hr, b.avg_hr)
    maxes = [v for v in (a.max_hr, b.max_hr) if v is not None]
    dist = None if a.distance_m is None and b.distance_m is None else (a.distance_m or 0.0) + (b.distance_m or 0.0)
    return a.model_copy(update={
        "duration_s": total,
        "distance_m": dist,
        "avg_hr": round(hr) if hr is not None else None,
        "max_hr": max(maxes) if maxes else None,
        "avg_power_w": weighted(a.avg_power_w, b.avg_power_w),
    })


def merge_double_trigger_laps(laps: Sequence[WorkoutLap], series: dict | None = None) -> list[WorkoutLap]:
    """`laps` with double-trigger fragments merged into the preceding lap; unchanged when none
    qualify. Laps without a start offset cannot be placed and are returned as is."""
    timed = sorted((l for l in laps if l.start_offset_s is not None), key=lambda l: l.start_offset_s)
    untimed = [l for l in laps if l.start_offset_s is None]
    longs = [l.duration_s for l in timed if l.duration_s >= MIN_LONG_LAP_S]
    if not longs:
        return list(laps)
    long_ref_s = median(longs)
    verdicts = {i: _at_the_mark(timed, i, series) for i in range(len(timed)) if _is_fragment(timed, i, long_ref_s)}
    pattern_ok = sum(v is not False for v in verdicts.values()) >= MIN_PATTERN_REPEATS
    merge = {i for i, v in verdicts.items() if v is True or (v is None and pattern_ok)}
    if not merge:
        return list(laps)
    out: list[WorkoutLap] = []
    for i, lap in enumerate(timed):
        if i in merge:
            out[-1] = _combine(out[-1], lap)
        else:
            out.append(lap)
    return out + untimed
