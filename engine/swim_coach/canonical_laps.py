"""The one canonical lap derivation: every lap-based calculation and view reads these laps.

A device's own laps are unreliable for a race: the lap that contains the race start also holds the
warm-up and the wait on the line, a hairpin by the lap mark makes the auto-lap fire twice, and a
missed press leaves one lap spanning two. `build_canonical_laps` turns the raw device laps
(`Workout.laps`, kept untouched for the raw analysis view) plus the recording into ONE lap set,
computed once per analysis and stored (`WorkoutAnalytics.laps`):

1. Merge double-trigger fragments into the preceding lap (`lap_normalise.merge_double_trigger_laps`).
2. For a race, trim to the race start: laps that end before it are warm-up and dropped, and the lap
   that contains it is split so lap 1 begins AT the start (no line-wait in its time, power or coasting).
3. Find the lap MARK: for a race the start of the first full device lap after the start (for a ride
   the anchor of the largest group of similar laps; with no device lap to read it from, the track
   position at the race start / the first fix).
4. Fill missed laps: a lap well over one typical lap long that contains a GPS crossing of the mark
   (`gps_laps.mark_crossings`) is cut there. With no usable device laps, the crossings alone make the laps.
5. Flag each lap: `start_lap` (begins at the race start away from the mark) and `comparable` (starts
   at the mark and covers a similar distance to the other such laps). Lap-to-lap comparisons (course
   sectors, race efficiency trends, lap consistency) use comparable laps only.

Times are on the activity clock; a lap runs to the next lap's start (paused time stays inside it). Constants are Coach judgment, not sourced.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Sequence

from swim_coach.gps_laps import GPS_LAP_MIN_DURATION_S, detect_gps_laps, mark_crossings
from swim_coach.lap_normalise import START_LINE_RADIUS_M, merge_double_trigger_laps, metres_apart, start_point
from swim_coach.models import CanonicalLap, CanonicalLapSource, WorkoutLap
from swim_coach.mtb_dynamics import mean_present, window_indices

LAP_DISTANCE_TOLERANCE = 0.10  # Coach judgment: laps within +-10% of each other are "the same course"
MIN_LAP_S = 120  # Coach judgment: shorter than this is a split, not a lap worth comparing
START_SNAP_S = 2.0  # Coach judgment: a device lap pressed within 2 s of the race start was pressed at the gun
FILL_MIN_LONG_FACTOR = 1.5  # Coach judgment: only a lap this many times a typical lap is a missed press worth cutting at the mark


@dataclass
class _Span:
    start_s: float
    end_s: float
    source: CanonicalLapSource
    device: WorkoutLap | None = None  # supplies distance / power / HR when the span is a (merged) device lap
    trimmed: bool = False  # begins at the race start


def _device_spans(laps: Sequence[WorkoutLap], series: dict, merge: bool) -> list[_Span]:
    """Device laps (fragments merged when asked) as spans, each running to the next lap's start."""
    merged = merge_double_trigger_laps(laps, series) if merge else list(laps)
    timed = sorted((l for l in merged if l.start_offset_s is not None), key=lambda l: l.start_offset_s)
    original = {(float(l.start_offset_s), round(l.duration_s, 1)) for l in laps if l.start_offset_s is not None}
    end = series["t_s"][-1] + 1
    spans = []
    for i, lap in enumerate(timed):
        stop = float(timed[i + 1].start_offset_s) if i + 1 < len(timed) else end
        source = "device" if (float(lap.start_offset_s), round(lap.duration_s, 1)) in original else "merged"
        spans.append(_Span(float(lap.start_offset_s), stop, source, lap))
    return spans


def _trim_to_start(spans: list[_Span], race_start_s: float, end_s: float) -> list[_Span]:
    """Laps from the race start on: warm-up laps dropped, the lap containing the start cut at it."""
    kept = [s for s in spans if s.end_s > race_start_s]
    if not kept:
        return [_Span(race_start_s, end_s, "split_at_start", None, trimmed=True)]
    first = kept[0]
    if first.start_s < race_start_s - START_SNAP_S:
        return [_Span(race_start_s, first.end_s, "split_at_start", None, trimmed=True), *kept[1:]]
    if first.start_s > race_start_s + START_SNAP_S:
        return [_Span(race_start_s, first.start_s, "split_at_start", None, trimmed=True), *kept]
    first.trimmed = True
    return kept


def _dist_between(series: dict, start_s: float, end_s: float) -> float | None:
    dist = series.get("dist_m") or []
    t_s = series["t_s"]
    if not dist:
        return None
    lo = window_indices(t_s, start_s, end_s)
    inside = [dist[i] for i in lo if dist[i] is not None]
    if not inside:
        return None
    after = next((dist[i] for i in range(lo.stop, len(t_s)) if dist[i] is not None), None)
    return round((after if after is not None else inside[-1]) - inside[0], 2)


def _lap(n: int, span: _Span, series: dict) -> CanonicalLap:
    """One canonical lap: a device lap's own distance / power / HR, else the recording's over the span."""
    if span.device is not None:
        dist, power, hr = span.device.distance_m, span.device.avg_power_w, span.device.avg_hr
    else:
        idx = window_indices(series["t_s"], span.start_s, span.end_s)
        dist = _dist_between(series, span.start_s, span.end_s)
        power = mean_present(series["power_w"], idx) if series.get("power_w") and len(idx) else None
        mean_hr = mean_present(series["hr"], idx) if series.get("hr") and len(idx) else None
        hr = round(mean_hr) if mean_hr is not None else None
    return CanonicalLap(
        n=n, start_s=span.start_s, end_s=span.end_s, duration_s=round(span.end_s - span.start_s, 3),
        distance_m=dist, avg_power_w=power, avg_hr=hr, source=span.source, start_lap=span.trimmed,
    )


def _near(series: dict, ref: tuple[float, float] | None, at_s: float) -> bool:
    """Within the start-line radius of `ref`; assumed when either position is unknown (no GPS)."""
    here = start_point(series, at_s)
    return ref is None or here is None or metres_apart(ref, here) <= START_LINE_RADIUS_M


def _best_group(laps: Sequence[CanonicalLap], series: dict, mark: tuple[float, float] | None) -> list[CanonicalLap]:
    """The largest group of full laps (not the start lap) within the size tolerance of one anchor
    lap that start at the mark (with no mark: at the anchor's own start); the earliest anchor wins
    ties. Size is distance, or duration when the laps carry no distance (no distance channel)."""
    pool = [l for l in laps if not l.start_lap and l.duration_s >= MIN_LAP_S]
    size = (lambda l: l.distance_m) if pool and all(l.distance_m for l in pool) else (lambda l: l.duration_s)
    best: list[CanonicalLap] = []
    for anchor in pool:
        ref = mark if mark is not None else start_point(series, anchor.start_s)
        group = [
            l for l in pool
            if abs(size(l) - size(anchor)) <= LAP_DISTANCE_TOLERANCE * size(anchor) and _near(series, ref, l.start_s)
        ]
        if len(group) > len(best):
            best = group
    return best


def _find_mark(laps: Sequence[CanonicalLap], series: dict, race_start_s: float | None) -> tuple[float, float] | None:
    """The lap mark's position. Race: where the first full device lap after the start begins; ride:
    where the largest group of similar laps begins. Without a device lap to read it from, the track
    position at the race start (or the first fix)."""
    if race_start_s is not None:
        full = next((l for l in laps if not l.start_lap and l.source in ("device", "merged") and l.duration_s >= MIN_LAP_S), None)
        return start_point(series, full.start_s if full else race_start_s)
    group = _best_group(laps, series, None)
    anchor = group[0] if group else next((l for l in laps if l.duration_s >= MIN_LAP_S), None)
    return start_point(series, anchor.start_s if anchor else series["t_s"][0])


def _fill_missed_laps(spans: list[_Span], series: dict, mark: tuple[float, float], typical_s: float | None) -> list[_Span]:
    """Cut each lap that is a missed press (or a GPS-only span) at the crossings of the mark inside it."""
    crossings = mark_crossings(series, mark)
    out: list[_Span] = []
    for span in spans:
        long_enough = span.source == "gps" or (typical_s is not None and span.end_s - span.start_s >= FILL_MIN_LONG_FACTOR * typical_s)
        cuts = [c for c in crossings if span.start_s + GPS_LAP_MIN_DURATION_S <= c <= span.end_s - GPS_LAP_MIN_DURATION_S]
        if not (long_enough and cuts):
            out.append(span)
            continue
        edges = [span.start_s, *cuts, span.end_s]
        piece = "gps" if span.source == "gps" else "gps_filled"
        out.extend(
            _Span(a, b, "split_at_start" if k == 0 and span.source == "split_at_start" else piece, None, trimmed=span.trimmed and k == 0)
            for k, (a, b) in enumerate(zip(edges, edges[1:]))
        )
    return out


def _gps_spans(series: dict, race_start_s: float | None) -> list[_Span]:
    """Laps from GPS crossings of the mark alone: the track position at the race start, else the first fix."""
    ref = start_point(series, race_start_s) if race_start_s is not None else None
    found = detect_gps_laps(series, reference=ref, from_s=race_start_s)
    return [_Span(g.start_s, g.end_s, "gps") for g in found]


def _typical_s(laps: Sequence[CanonicalLap], series: dict, mark: tuple[float, float] | None) -> float | None:
    group = [l for l in _best_group(laps, series, mark) if l.source in ("device", "merged")]
    return median(l.duration_s for l in group) if group else None


def _finish(spans: list[_Span], series: dict, mark: tuple[float, float] | None) -> list[CanonicalLap]:
    """Number the spans and set `start_lap` / `comparable`."""
    laps = [_lap(n, s, series) for n, s in enumerate(spans, 1)]
    flagged = [
        l.model_copy(update={"start_lap": l.start_lap and not _near_known(series, mark, l.start_s)}) for l in laps
    ]
    group = {l.n for l in _best_group(flagged, series, mark)}
    return [l.model_copy(update={"comparable": l.n in group}) for l in flagged]


def _near_known(series: dict, mark: tuple[float, float] | None, at_s: float) -> bool:
    """Positively at the mark (unlike `_near`, unknown is not at the mark)."""
    here = start_point(series, at_s)
    return mark is not None and here is not None and metres_apart(mark, here) <= START_LINE_RADIUS_M


def _comparable_pair(laps: Sequence[CanonicalLap]) -> bool:
    return sum(l.comparable for l in laps) >= 2


def build_canonical_laps(
    device_laps: Sequence[WorkoutLap],
    series: dict | None,
    *,
    race_start_s: float | None = None,
    course: bool = True,
) -> list[CanonicalLap]:
    """The canonical laps (see the module docstring). `race_start_s`: the race start on the activity
    clock (None for a ride, or a race whose start is unknown). `course=False` is for a structured
    workout whose device laps are its reps: they pass through as they are, never comparable.
    `[]` without a series."""
    if not series or not series.get("t_s"):
        return []
    spans = _device_spans(device_laps, series, merge=course)
    if not course:
        return [_lap(n, s, series) for n, s in enumerate(spans, 1)]
    if race_start_s is not None:
        spans = _trim_to_start(spans, race_start_s, series["t_s"][-1] + 1)
    laps = [_lap(n, s, series) for n, s in enumerate(spans, 1)]
    mark = _find_mark(laps, series, race_start_s)
    if mark is not None and spans:
        spans = _fill_missed_laps(spans, series, mark, _typical_s(laps, series, mark))
    result = _finish(spans, series, mark)
    if not _comparable_pair(result):
        alt_mark = start_point(series, race_start_s) if race_start_s is not None else None
        alt = _finish(_gps_spans(series, race_start_s), series, alt_mark)
        if _comparable_pair(alt):
            return alt
    return result
