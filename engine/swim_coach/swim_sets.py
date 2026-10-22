"""Swim moving/elapsed pace, pool-unit inference and set segmentation: pure functions.

Works on a stored workout's `lengths` + `pauses` alone (prod rows carry no raw .fit). A *rep* is a
run of consecutive active lengths ended by recorded rest; a *set* is consecutive reps of the same
distance and stroke category. Rest the device never recorded (a pause at the wall without pressing
lap/rest) is invisible, so an unbroken run stays ONE rep -- nothing is invented from length-duration
outliers (possible follow-up).

Constants are "Coach judgment:" (no library file backs set segmentation; they are display heuristics
that never feed load or plan checks).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, replace
from typing import Literal, Sequence

from swim_coach.models import SwimRep, SwimSet, WorkoutLength, WorkoutPause

PoolUnit = Literal["yd", "m"]

M_PER_YD = 0.9144

# Coach judgment: a gap between consecutive active lengths this long is a rest (a wall pause the
# device logged as an idle length / timer stop); shorter is turn noise.
REST_MIN_S = 5.0
# Coach judgment: when the lap changes, even a short real gap ends the rep (the swimmer pressed lap).
LAP_GAP_MIN_S = 2.0
# Coach judgment: reconstructing a timeline, a pause belongs between two lengths when it starts
# within this many seconds of the running cursor.
TIMELINE_TOL_S = 5.0
# Coach judgment: send-off and rest are shown to the nearest 5 s, like a pace clock.
SEND_OFF_ROUND_S = 5
# Coach judgment: a rep/set gets a stroke label only when one stroke covers at least this share of
# its lengths (the watch's stroke tags are unreliable, e.g. freestyle on backstroke flip turns);
# otherwise the stroke is omitted. Stroke never splits sets.
STROKE_LABEL_SHARE = 0.8
# Coach judgment: wall rest the device did not record is folded into the NEXT length's time. A
# length is a "detected rest" when it runs this many seconds over the median of its neighbours
# (same stroke when >= DETECT_MIN_SAME_STROKE of them share it, else all) ...
DETECT_EXCESS_S = 8.0
DETECT_MIN_SAME_STROKE = 5
# ... judged against the lengths this many positions either side.
DETECT_WINDOW = 6
# ... and its stroke count is no more than the median plus this margin (more strokes = genuinely
# slow swimming, not rest).
DETECT_STROKE_MARGIN = 3
# Coach judgment: a pace faster than this per 100 m (elite sprint territory) means the pool length
# or turn count is wrong; paces and sets are withheld rather than published as fact.
MIN_PLAUSIBLE_PACE_S_PER_100M = 50.0
# Coach judgment: warn that rest may be unrecorded when one rep is >= 80% of elapsed time, or is
# >= 20 min and >= half of it (a long unbroken block with only a couple of recorded rests).
NOTE_SHARE_STRICT = 0.8
NOTE_SHARE_LONG = 0.5
NOTE_LONG_REP_S = 20 * 60
# Coach judgment: pool lengths recognised from distance per length, within this relative tolerance.
POOL_TOL = 0.03
_POOLS: tuple[tuple[float, PoolUnit], ...] = (
    (25 * M_PER_YD, "yd"),
    (25.0, "m"),
    (50 * M_PER_YD, "yd"),
    (50.0, "m"),
)

_STROKE_SHORT = {
    "freestyle": "free",
    "backstroke": "back",
    "breaststroke": "breast",
    "butterfly": "fly",
    "drill": "drill",
    "mixed": "mixed",
    "im": "IM",
}


def fmt_mmss(seconds: float) -> str:
    total = int(round(seconds))
    return f"{total // 60}:{total % 60:02d}"


def infer_pool(distance_m: float, n_active_lengths: int) -> tuple[float | None, PoolUnit]:
    """Pool length and unit from distance per length; unrecognised -> (None, "m")."""
    if n_active_lengths <= 0 or distance_m <= 0:
        return None, "m"
    per_length = distance_m / n_active_lengths
    for length_m, unit in _POOLS:
        if abs(per_length - length_m) <= length_m * POOL_TOL:
            return round(length_m, 2), unit
    return None, "m"


def _per_100(seconds: float, distance_m: float, unit: PoolUnit) -> float:
    unit_m = M_PER_YD if unit == "yd" else 1.0
    return seconds / (distance_m / unit_m / 100)


def swim_pace_block(*, moving_s: float, elapsed_s: float, distance_m: float, pool_unit: PoolUnit | None) -> dict:
    """Moving (rest excluded) and elapsed pace per 100 m and per 100 of the pool unit."""
    if distance_m <= 0 or moving_s <= 0 or elapsed_s <= 0:
        return {}
    out: dict = {
        "moving_pace_s_per_100m": _per_100(moving_s, distance_m, "m"),
        "elapsed_pace_s_per_100m": _per_100(elapsed_s, distance_m, "m"),
        "rest_total_s": max(0.0, elapsed_s - moving_s),
    }
    if pool_unit is not None:
        out["moving_pace_s_per_100_unit"] = _per_100(moving_s, distance_m, pool_unit)
        out["elapsed_pace_s_per_100_unit"] = _per_100(elapsed_s, distance_m, pool_unit)
    return out


@dataclass(frozen=True)
class _Placed:
    start: float
    end: float
    length: WorkoutLength
    # Seconds of unrecorded wall rest folded into this length (0 = none); the swim portion is
    # `swim_s`, and the swimming itself starts at `swim_start`.
    extra: float = 0.0

    @property
    def swim_s(self) -> float:
        return self.length.duration_s - self.extra

    @property
    def swim_start(self) -> float:
        return self.start + self.extra


def _timeline(lengths: Sequence[WorkoutLength], pauses: Sequence[WorkoutPause]) -> list[_Placed]:
    """Each length with a start/end second: the recorded `start_offset_s` when every length has
    one, else cumulative durations with each pause inserted where it starts."""
    if lengths and all(length.start_offset_s is not None for length in lengths):
        return [_Placed(l.start_offset_s, l.start_offset_s + l.duration_s, l) for l in lengths]  # type: ignore[operator]
    queue = sorted(pauses, key=lambda p: p.start_offset_s)
    placed: list[_Placed] = []
    t = 0.0
    qi = 0
    for length in lengths:
        while qi < len(queue) and queue[qi].start_offset_s <= t + TIMELINE_TOL_S:
            t = max(t, queue[qi].start_offset_s) + queue[qi].duration_s
            qi += 1
        placed.append(_Placed(t, t + length.duration_s, length))
        t += length.duration_s
    return placed


def _local_median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _with_detected_rest(placed: list[_Placed]) -> list[_Placed]:
    """Mark lengths that absorbed unrecorded wall rest (see DETECT_EXCESS_S), judged against the
    median of the neighbouring lengths so an easy warm-up or cool-down (slower throughout) is not
    mistaken for rest. The first length of the swim is never marked (nothing precedes it)."""
    if len(placed) < DETECT_WINDOW:
        return placed
    out: list[_Placed] = [placed[0]]
    for i in range(1, len(placed)):
        p = placed[i]
        near = [q.length for q in (placed[max(0, i - DETECT_WINDOW) : i + DETECT_WINDOW + 1]) if q is not p]
        same = [l for l in near if l.stroke == p.length.stroke]
        group = same if len(same) >= DETECT_MIN_SAME_STROKE else near
        med_dur = _local_median([l.duration_s for l in group])
        med_strokes = _local_median([l.strokes for l in group if l.strokes])
        strokes = p.length.strokes
        few_strokes = strokes is None or med_strokes is None or strokes <= med_strokes + DETECT_STROKE_MARGIN
        excess = p.length.duration_s - med_dur if med_dur is not None else 0.0
        out.append(replace(p, extra=excess) if excess > DETECT_EXCESS_S and few_strokes else p)
    return out


def _is_boundary(prev: _Placed, nxt: _Placed) -> bool:
    gap = nxt.start - prev.end
    lap_changed = prev.length.lap_index != nxt.length.lap_index
    return gap >= REST_MIN_S or (lap_changed and gap >= LAP_GAP_MIN_S) or nxt.extra > 0


def _stroke_label(group: Sequence[_Placed]) -> str | None:
    """The dominant stroke's short name when it covers STROKE_LABEL_SHARE of the lengths; else None."""
    strokes = [str(p.length.stroke).lower() for p in group if p.length.stroke]
    if not strokes:
        return None
    top = max(set(strokes), key=strokes.count)
    if strokes.count(top) / len(group) < STROKE_LABEL_SHARE or top == "mixed":
        return None
    return _STROKE_SHORT.get(top, top)


def _unit_length(pool_length_m: float, unit: PoolUnit) -> float:
    return pool_length_m / M_PER_YD if unit == "yd" else pool_length_m


def _reps(placed: list[_Placed], pool_length_m: float, unit: PoolUnit) -> list[SwimRep]:
    groups: list[list[_Placed]] = []
    for p in placed:
        if groups and not _is_boundary(groups[-1][-1], p):
            groups[-1].append(p)
        else:
            groups.append([p])
    step = _unit_length(pool_length_m, unit)
    reps: list[SwimRep] = []
    for i, g in enumerate(groups):
        time_s = sum(p.swim_s for p in g)
        distance = round(len(g) * step)
        rest = source = None
        if i + 1 < len(groups):
            nxt = groups[i + 1][0]
            recorded = max(0.0, nxt.start - g[-1].end)
            rest = recorded + nxt.extra
            source = "recorded" if recorded >= LAP_GAP_MIN_S else "detected"
        reps.append(
            SwimRep(
                start_offset_s=round(g[0].swim_start, 1),
                distance=distance,
                swim_time_s=round(time_s, 1),
                pace_s_per_100=time_s / distance * 100,
                stroke=_stroke_label(g),
                rest_after_s=round(rest, 1) if rest is not None else None,
                rest_source=source,
            )
        )
    return reps


def _round5(x: float) -> int:
    return int(round(x / SEND_OFF_ROUND_S) * SEND_OFF_ROUND_S)


def _describe(
    count: int, dist: int, stroke: str | None, send_off: int | None, pace: float, rest: float | None, source: str | None
) -> str:
    head = f"{count}×{dist}" if count > 1 else f"{dist}"
    if stroke:
        head += f" {stroke}"
    if send_off is not None:
        head += f" on {fmt_mmss(send_off)}"
    out = f"{head} @ {fmt_mmss(pace)}/100"
    if count > 1 and rest:
        out += f" (rest ~{fmt_mmss(_round5(rest))}{', detected' if source == 'detected' else ''})"
    return out


def _make_set(reps: list[SwimRep]) -> SwimSet:
    first = reps[0]
    count = len(reps)
    total_time = sum(r.swim_time_s for r in reps)
    total_dist = sum(r.distance for r in reps)
    pace = total_time / total_dist * 100
    strokes = {r.stroke for r in reps}
    stroke = first.stroke if len(strokes) == 1 else None
    send_off = rest = source = None
    if count >= 2:
        send_off = _round5(statistics.median(b.start_offset_s - a.start_offset_s for a, b in zip(reps, reps[1:])))
        inner = [r for r in reps[:-1] if r.rest_after_s is not None]
        rest = statistics.mean(r.rest_after_s for r in inner) if inner else None
        detected = sum(1 for r in inner if r.rest_source == "detected")
        source = None if not inner else ("detected" if detected * 2 > len(inner) else "recorded")
    return SwimSet(
        count=count,
        rep_distance=first.distance,
        stroke=stroke,
        send_off_s=send_off,
        avg_pace_s_per_100=pace,
        avg_rest_s=rest,
        rest_source=source,
        total_distance=total_dist,
        description=_describe(count, first.distance, stroke, send_off, pace, rest, source),
        reps=reps,
    )


def _note(reps: list[SwimRep], elapsed_s: float) -> str | None:
    """Only when neither recorded nor detected rests split a long run."""
    if not reps or elapsed_s <= 0:
        return None
    longest = max(r.swim_time_s for r in reps)
    share = longest / elapsed_s
    if share >= NOTE_SHARE_STRICT or (longest >= NOTE_LONG_REP_S and share >= NOTE_SHARE_LONG):
        n = len(reps) - 1
        recorded = f"Only {n} rest{'s were' if n != 1 else ' was'} recorded" if n else "No rest was recorded"
        return f"{recorded}; rest at the wall without pressing lap/rest isn't visible."
    return None


def pace_is_implausible(pace_s_per_100: float, unit: PoolUnit) -> bool:
    per_100m = pace_s_per_100 / (M_PER_YD if unit == "yd" else 1.0)
    return per_100m < MIN_PLAUSIBLE_PACE_S_PER_100M


def segment_swim(
    lengths: Sequence[WorkoutLength],
    pauses: Sequence[WorkoutPause],
    *,
    pool_length_m: float,
    pool_unit: PoolUnit,
    elapsed_s: float | None,
) -> tuple[list[SwimSet], str | None]:
    """Sets (and an honesty note when rest looks under-recorded) for a pool swim's lengths.
    Reps end at recorded rest or at a detected rest (an inflated length); sets group consecutive
    reps of the same distance, whatever the stroke."""
    if not lengths or pool_length_m <= 0:
        return [], None
    placed = _with_detected_rest(_timeline(lengths, pauses))
    reps = _reps(placed, pool_length_m, pool_unit)
    span = elapsed_s if elapsed_s else placed[-1].end - placed[0].start
    sets: list[SwimSet] = []
    run: list[SwimRep] = []
    for rep in reps:
        if run and rep.distance != run[0].distance:
            sets.append(_make_set(run))
            run = []
        run.append(rep)
    sets.append(_make_set(run))
    return sets, _note(reps, span)
