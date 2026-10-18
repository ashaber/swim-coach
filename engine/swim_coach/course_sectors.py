"""Lap-over-lap course sectors: where on a repeated course the time (and smoothness) went.

For a ride with 2+ laps of similar distance (CX/MTB race laps, a lap-per-circuit pre-ride), each
compared lap is cut into sections that line up across laps. With GPS the sections are course
features (`course_features`: straights vs corner sequences found on the best lap, every lap read
through them by track position, so odometer differences do not matter); without GPS, or when the
track has no usable features, into `SECTOR_COUNT` equal-DISTANCE sectors. Output: per-lap time / power / flow / grit, the fade first -> last lap
(including the flow trend: flow worsening while power holds reads as technique slipping under
fatigue), and a per-sector loss table with the top-3 loss sectors. Loss is measured against the fastest time
through THAT sector on any lap (the motorsport "ideal lap"), so it is never negative.

Constants are Coach judgment, not sourced: SECTOR_COUNT, TRACK_POINTS, START_LINE_RADIUS_M, LAP_DISTANCE_TOLERANCE, MIN_LAP_S, MAX_LAPS.
Flow and grit are Garmin's proprietary device metrics (see `mtb_dynamics`); they are shown beside
the time loss, never thresholded. The data cannot name what a section IS (run-up, sand, off-camber) -- the coach asks the rider.
"""

from __future__ import annotations

from bisect import bisect_left
from typing import Sequence

from swim_coach.course_features import MIN_SECTIONS, Section, align_edges, project_xy, segment_course
from swim_coach.gps_laps import detect_gps_laps
from swim_coach.lap_normalise import START_LINE_RADIUS_M, merge_double_trigger_laps, metres_apart, start_point
from swim_coach.models import (
    CourseSectors, CourseTrack, LapFade, SectorLap, SectorLoss, TrackSector, Workout, WorkoutLap,
)
from swim_coach.mtb_dynamics import (
    GRIT_RECORD_SCALE, has_channel, lap_windows, mean_moving, mean_present, window_indices,
)

SECTOR_COUNT = 8  # Coach judgment: enough resolution to localise a loss, still ~10+ s per sector
LAP_DISTANCE_TOLERANCE = 0.10  # Coach judgment: laps within +-10% of each other are "the same course"
MIN_LAP_S = 120  # Coach judgment: shorter than this is a split, not a lap worth sectoring
MAX_LAPS = 12  # Coach judgment: more than this is auto-lap noise (e.g. every km), not a course
TOP_LOSS_SECTORS = 3
TRACK_POINTS = 200  # Coach judgment: enough to draw a recognisable lap outline, small enough to store


def _starts_together(series: dict, anchor_start: float, start: float) -> bool:
    """Same start line: within START_LINE_RADIUS_M of the anchor's start. Without GPS, assumed."""
    a, b = start_point(series, anchor_start), start_point(series, start)
    return a is None or b is None or metres_apart(a, b) <= START_LINE_RADIUS_M


def _similar_laps(
    windows: list[tuple[WorkoutLap, float, float]], series: dict
) -> list[tuple[int, WorkoutLap, float, float]]:
    """The largest group of laps whose distance is within tolerance of one anchor lap and (with
    GPS) which start at the anchor's start line (earliest anchor wins ties), as
    `(device lap number, lap, start, stop)`."""
    numbered = [
        (n, lap, a, b) for n, (lap, a, b) in enumerate(windows, 1)
        if lap.distance_m and lap.duration_s >= MIN_LAP_S
    ]
    best: list = []
    for _, anchor, anchor_start, _ in numbered:
        group = [
            item for item in numbered
            if abs(item[1].distance_m - anchor.distance_m) <= LAP_DISTANCE_TOLERANCE * anchor.distance_m
            and _starts_together(series, anchor_start, item[2])
        ]
        if len(group) > len(best):
            best = group
    return best


def _gps_windows(series: dict) -> list[tuple[WorkoutLap, float, float]]:
    """Laps found from the GPS start marker (`gps_laps.detect_gps_laps`, boundaries reused as is),
    shaped like the device-lap windows. Distance comes from the `dist_m` channel."""
    dist = series.get("dist_m") or []
    windows = []
    for gps in detect_gps_laps(series):
        a, b = dist[gps.start_idx], dist[gps.end_idx]
        if a is None or b is None:
            continue
        lap = WorkoutLap(index=gps.n, start_offset_s=gps.start_s, duration_s=gps.duration_s, distance_m=b - a)
        windows.append((lap, gps.start_s, gps.end_s))
    return windows


def course_laps(workout: Workout, series: dict, prefer_gps: bool) -> list[tuple[int, WorkoutLap, float, float]]:
    """Native device laps (double-trigger fragments merged into full laps) and GPS-detected laps, each filtered to similar distance from one start
    line; the preferred source wins when it yields 2+ laps, else the other is tried."""
    laps = merge_double_trigger_laps(workout.laps, series)
    native = _similar_laps(lap_windows(laps, series["t_s"][-1] + 1), series)
    gps = _similar_laps(_gps_windows(series), series)
    first, second = (gps, native) if prefer_gps else (native, gps)
    return first if len(first) >= 2 else second


def _t_at(dist: Sequence[float], t: Sequence[float], d: float) -> float:
    i = bisect_left(dist, d)
    if i <= 0:
        return t[0]
    if i >= len(dist):
        return t[-1]
    span = dist[i] - dist[i - 1]
    return t[i] if span <= 0 else t[i - 1] + (t[i] - t[i - 1]) * (d - dist[i - 1]) / span


def _even_edges(series: dict, idx: range) -> list[float] | None:
    """SECTOR_COUNT equal-distance sector edges (times) through one lap, None if the lap has no usable distance."""
    t_s, dist = series["t_s"], series["dist_m"]
    pts = [(t_s[i], dist[i]) for i in idx if dist[i] is not None]
    if len(pts) < SECTOR_COUNT + 1:
        return None
    t = [p[0] for p in pts]
    d = [p[1] for p in pts]
    for i in range(1, len(d)):  # distance never runs backwards inside a lap
        d[i] = max(d[i], d[i - 1])
    total = d[-1] - d[0]
    if total <= 0:
        return None
    return [_t_at(d, t, d[0] + total * k / SECTOR_COUNT) for k in range(SECTOR_COUNT + 1)]


def _speeds_through(speed: Sequence[float | None], sec: range) -> tuple[float | None, float | None, float | None]:
    """`(entry, slowest, exit)` speed over the section's records, None where there are none."""
    vals = [speed[i] for i in sec if speed[i] is not None]
    return (speed[sec[0]], min(vals), speed[sec[-1]]) if vals and speed[sec[0]] is not None and speed[sec[-1]] is not None else (None, None, None)


def _cut(series: dict, idx: range, edges: list[float]) -> dict:
    """One lap cut at `edges` (times): per-section time / flow / grit / speed / power, plus lap totals."""
    t_s = series["t_s"]
    flow, grit, power = series.get("flow") or [], series.get("grit") or [], series.get("power_w") or []
    speed = series.get("speed_mps") or []
    n = len(edges) - 1
    times, flows, grits, speeds, powers, passes = [], [], [], [], [], []
    for k in range(n):
        sec = window_indices(t_s, edges[k], edges[k + 1] if k < n - 1 else edges[-1] + 1e-6)
        sec = range(max(sec.start, idx.start), min(sec.stop, idx.stop))
        times.append(round(edges[k + 1] - edges[k], 2))
        flows.append(mean_moving(flow, speed, sec) if flow else None)
        vals = [grit[i] for i in sec if grit[i] is not None] if grit else []
        grits.append(round(sum(vals) / GRIT_RECORD_SCALE, 3) if vals else None)
        speeds.append(mean_present(speed, sec) if speed and len(sec) else None)
        powers.append(mean_present(power, sec) if power and len(sec) else None)
        passes.append(_speeds_through(speed, sec) if speed and len(sec) else (None, None, None))
    return {"edges": edges, "idx": idx, "time_s": round(edges[-1] - edges[0], 1), "times": times, "flows": flows, "grits": grits,
            "speeds": speeds, "powers": powers, "passes": passes,
            "power": mean_present(power, idx) if power else None,
            "flow": mean_moving(flow, speed, idx) if flow else None,
            "grit": round(sum(v for v in (grit[i] for i in idx) if v is not None) / GRIT_RECORD_SCALE, 2)
            if has_channel(series, "grit") else None}


def _evenly(indices: list[int], limit: int) -> list[int]:
    """At most `limit` of `indices`, evenly spread, always keeping the first and the last."""
    if len(indices) <= limit:
        return indices
    step = (len(indices) - 1) / (limit - 1)
    return [indices[round(i * step)] for i in range(limit)]


def build_track(series: dict, lap: dict, sections: Sequence[Section] | None = None) -> CourseTrack | None:
    """The lap's outline as per-section polylines in local metres (equirectangular projection around
    the lap centroid, north up), ~TRACK_POINTS points in all; None without usable GPS. `sections`
    (course features) name and type each polyline."""
    lat, lng = series.get("lat") or [], series.get("lng") or []
    idx, edges, t_s = lap["idx"], lap["edges"], series["t_s"]
    n = len(edges) - 1
    fixes = [i for i in idx if i < len(lat) and i < len(lng) and lat[i] is not None and lng[i] is not None]
    if len(fixes) < n + 1:
        return None
    lat0 = sum(lat[i] for i in fixes) / len(fixes)
    lng0 = sum(lng[i] for i in fixes) / len(fixes)
    xys = dict(zip(fixes, project_xy(lat, lng, fixes, lat0, lng0)))

    def xy(i: int) -> tuple[float, float]:
        return round(xys[i][0], 1), round(xys[i][1], 1)

    per_sector = max(2, TRACK_POINTS // n)
    track, joined = [], None
    for k in range(n):
        last = k == n - 1
        mine = [i for i in fixes if edges[k] <= t_s[i] and (t_s[i] <= edges[k + 1] if last else t_s[i] < edges[k + 1])]
        if not mine:
            return None
        points = [xy(i) for i in _evenly(mine, per_sector)]
        if joined is not None:  # start where the previous sector ended so the outline is continuous
            points = [joined, *points[1:]] if len(points) > 1 else [joined, points[0]]
        joined = points[-1]
        feature = sections[k] if sections else None
        track.append(TrackSector(sector=k + 1, points=points, label=points[len(points) // 2],
                                 kind=feature.kind if feature else None, name=feature.label if feature else None))
    return CourseTrack(sectors=track)


def _slope(values: list[float]) -> float | None:
    n = len(values)
    if n < 2:
        return None
    mx, my = (n - 1) / 2, sum(values) / n
    den = sum((i - mx) ** 2 for i in range(n))
    return round(sum((i - mx) * (v - my) for i, v in enumerate(values)) / den, 2)


def _pct(new: float | None, old: float | None) -> float | None:
    return round((new - old) / old * 100, 1) if new is not None and old else None


def _mean(vals: list[float]) -> float | None:
    return round(sum(vals) / len(vals), 2) if vals else None


def _fix_indices(series: dict, idx: range) -> list[int]:
    lat, lng = series.get("lat") or [], series.get("lng") or []
    return [i for i in idx if i < len(lat) and i < len(lng) and lat[i] is not None and lng[i] is not None]


def _feature_edges(series: dict, cut: list[tuple[int, dict]], best_i: int) -> tuple[list[Section], list[list[float]]] | None:
    """Course-feature sections found on the best lap and every lap's boundary times through them
    (same first/last edge as the equal-distance cut, so lap times do not change), or None when the
    track has no usable GPS, no features, or some lap does not follow the best lap's line."""
    best = cut[best_i][1]
    fixes = _fix_indices(series, best["idx"])
    if len(fixes) < 2 * MIN_SECTIONS:
        return None
    lat, lng, t_s = series["lat"], series["lng"], series["t_s"]
    lat0 = sum(lat[i] for i in fixes) / len(fixes)
    lng0 = sum(lng[i] for i in fixes) / len(fixes)
    ref_xy = project_xy(lat, lng, fixes, lat0, lng0)
    flow = series.get("flow")
    sections = segment_course(ref_xy, [t_s[i] for i in fixes], [flow[i] for i in fixes] if flow else None)
    if sections is None:
        return None
    bounds = [s.start_i for s in sections] + [sections[-1].end_i]
    all_edges = []
    for k, (_, lap) in enumerate(cut):
        if k == best_i:
            mine = [t_s[fixes[b]] for b in bounds]
        else:
            lap_fixes = _fix_indices(series, lap["idx"])
            mine = align_edges(ref_xy, bounds, project_xy(lat, lng, lap_fixes, lat0, lng0), [t_s[i] for i in lap_fixes])
            if mine is None:
                return None
        mine[0], mine[-1] = lap["edges"][0], lap["edges"][-1]  # the lap's own span, as for the even cut
        all_edges.append([max(e, mine[j - 1]) if j else e for j, e in enumerate(mine)])
    return sections, all_edges


def _section_row(k: int, cut: list[tuple[int, dict]], section: Section | None) -> SectorLoss:
    times = [s["times"][k] for _, s in cut]
    fastest = min(range(len(cut)), key=lambda i: times[i])
    ref = cut[fastest][1]
    losses = [t - times[fastest] for t in times]
    dflow = [s["flows"][k] - ref["flows"][k] for i, (_, s) in enumerate(cut)
             if i != fastest and s["flows"][k] is not None and ref["flows"][k] is not None]
    flow_by_lap = [s["flows"][k] for _, s in cut]
    flows = [f for f in flow_by_lap if f is not None]
    grits = [s["grits"][k] for _, s in cut if s["grits"][k] is not None]
    row = SectorLoss(
        sector=k + 1, best_time_s=times[fastest], mean_loss_s=round(sum(losses) / len(losses), 2),
        total_loss_s=round(sum(losses), 2), spread_s=round(max(times) - times[fastest], 2),
        avg_flow=_mean(flows), flow_vs_best=_mean(dflow), avg_grit=_mean(grits),
    )
    if section is None:
        return row
    passes = [s["passes"][k] for _, s in cut]
    row.kind, row.label, row.length_m = section.kind, section.label, section.length_m
    row.avg_speed_mps = _mean([s["speeds"][k] for _, s in cut if s["speeds"][k] is not None])
    row.avg_power_w = _mean([s["powers"][k] for _, s in cut if s["powers"][k] is not None])
    row.entry_speed_mps, row.min_speed_mps, row.exit_speed_mps = (
        _mean([p[j] for p in passes if p[j] is not None]) for j in range(3))
    row.flow_by_lap = flow_by_lap
    row.flow_slope_per_lap = _slope(flows) if len(flows) == len(cut) else None
    return row


def build_course_sectors(workout: Workout, series: dict | None, prefer_gps: bool = False) -> CourseSectors | None:
    """The section comparison, or None unless 2..MAX_LAPS similar-distance laps can be cut by distance.
    With GPS the best lap is split into straights and corner sequences (`course_features`) and every
    lap is read through those sections by position; otherwise (or if that fails) into SECTOR_COUNT
    equal-distance sectors. `prefer_gps`: use GPS-detected laps before the device's own laps (a race
    whose laps were never pressed)."""
    if not series or not series.get("t_s") or not has_channel(series, "dist_m"):
        return None
    group = course_laps(workout, series, prefer_gps)
    if not 2 <= len(group) <= MAX_LAPS:
        return None
    cut = []
    for n, lap, start, stop in group:
        idx = window_indices(series["t_s"], start, stop)
        edges = _even_edges(series, idx)
        if edges is None:
            return None
        cut.append((n, _cut(series, idx, edges)))
    best_i = min(range(len(cut)), key=lambda i: cut[i][1]["time_s"])
    featured = _feature_edges(series, cut, best_i)
    sections = None
    if featured:
        sections, all_edges = featured
        cut = [(n, _cut(series, lap["idx"], edges)) for (n, lap), edges in zip(cut, all_edges)]
    best = cut[best_i][1]
    laps = [
        SectorLap(lap=n, time_s=s["time_s"], avg_power_w=s["power"], avg_flow=s["flow"], grit=s["grit"],
                  time_vs_best_s=round(s["time_s"] - best["time_s"], 1), sector_times_s=s["times"])
        for n, s in cut
    ]
    count = len(best["times"])
    rows = [_section_row(k, cut, sections[k] if sections else None) for k in range(count)]
    ideal = round(sum(r.best_time_s for r in rows), 1)
    ranked = sorted((r for r in rows if r.total_loss_s > 0), key=lambda r: -r.total_loss_s)
    first, last = cut[0][1], cut[-1][1]
    flow_by_lap = [s["flow"] for _, s in cut if s["flow"] is not None]
    fade = LapFade(
        time_change_pct=_pct(last["time_s"], first["time_s"]) or 0.0,
        power_change_pct=_pct(last["power"], first["power"]),
        flow_change=round(last["flow"] - first["flow"], 2) if last["flow"] is not None and first["flow"] is not None else None,
        flow_slope_per_lap=_slope(flow_by_lap) if len(flow_by_lap) == len(cut) else None,
    )
    return CourseSectors(
        sector_count=count, best_lap=cut[best_i][0], laps=laps, fade=fade, sectors=rows,
        top_loss_sectors=[r.sector for r in ranked[:TOP_LOSS_SECTORS]],
        ideal_lap_s=ideal, ideal_gap_s=round(max(best["time_s"] - ideal, 0.0), 1),
        track=build_track(series, best, sections),
    )
