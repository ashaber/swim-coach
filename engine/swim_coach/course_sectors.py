"""Lap-over-lap course sectors: where on a repeated course the time (and smoothness) went.

For a ride with 2+ laps of similar distance (CX/MTB race laps, a lap-per-circuit pre-ride), each
compared lap is cut into `SECTOR_COUNT` equal-DISTANCE sectors, so sector k lines up across laps
without GPS matching. Output: per-lap time / power / flow / grit, the fade first -> last lap
(including the flow trend: flow worsening while power holds reads as technique slipping under
fatigue), and a per-sector loss table vs the fastest lap with the top-3 loss sectors.

Constants are Coach judgment, not sourced: SECTOR_COUNT, TRACK_POINTS, START_LINE_RADIUS_M, LAP_DISTANCE_TOLERANCE, MIN_LAP_S, MAX_LAPS.
Flow and grit are Garmin's proprietary device metrics (see `mtb_dynamics`); they are shown beside
the time loss, never thresholded. The data cannot name course features -- the coach asks the rider.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from statistics import median
from typing import Sequence

from swim_coach.gps_laps import detect_gps_laps
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
START_LINE_RADIUS_M = 30.0  # Coach judgment: a lap starting farther than this from the reference lap's start is not the same lap
TRACK_POINTS = 200  # Coach judgment: enough to draw a recognisable lap outline, small enough to store
EARTH_M_PER_DEG = 111_320.0  # metres per degree of latitude (spherical earth, plenty for a 30 m test)


def _start_point(series: dict, start_s: float) -> tuple[float, float] | None:
    """The (lat, lng) at the first record at/after `start_s`, or None without GPS there."""
    lat, lng = series.get("lat") or [], series.get("lng") or []
    i = next((i for i, t in enumerate(series["t_s"]) if t >= start_s), None)
    if i is None or i >= len(lat) or i >= len(lng) or lat[i] is None or lng[i] is None:
        return None
    return lat[i], lng[i]


def _metres_apart(a: tuple[float, float], b: tuple[float, float]) -> float:
    dy = (a[0] - b[0]) * EARTH_M_PER_DEG
    dx = (a[1] - b[1]) * EARTH_M_PER_DEG * math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot(dx, dy)


def _starts_together(series: dict, anchor_start: float, start: float) -> bool:
    """Same start line: within START_LINE_RADIUS_M of the anchor's start. Without GPS, assumed."""
    a, b = _start_point(series, anchor_start), _start_point(series, start)
    return a is None or b is None or _metres_apart(a, b) <= START_LINE_RADIUS_M


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


def _course_laps(workout: Workout, series: dict, prefer_gps: bool) -> list[tuple[int, WorkoutLap, float, float]]:
    """Native device laps and GPS-detected laps, each filtered to similar distance from one start
    line; the preferred source wins when it yields 2+ laps, else the other is tried."""
    native = _similar_laps(lap_windows(workout.laps, series["t_s"][-1] + 1), series)
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


def _lap_sectors(series: dict, idx: range) -> dict | None:
    t_s, dist = series["t_s"], series["dist_m"]
    pts = [(t_s[i], dist[i], i) for i in idx if dist[i] is not None]
    if len(pts) < SECTOR_COUNT + 1:
        return None
    t = [p[0] for p in pts]
    d = [p[1] for p in pts]
    for i in range(1, len(d)):  # distance never runs backwards inside a lap
        d[i] = max(d[i], d[i - 1])
    total = d[-1] - d[0]
    if total <= 0:
        return None
    edges = [_t_at(d, t, d[0] + total * k / SECTOR_COUNT) for k in range(SECTOR_COUNT + 1)]
    flow, grit, power = series.get("flow") or [], series.get("grit") or [], series.get("power_w") or []
    speed = series.get("speed_mps") or []
    times, flows, grits = [], [], []
    for k in range(SECTOR_COUNT):
        sec = window_indices(t_s, edges[k], edges[k + 1] if k < SECTOR_COUNT - 1 else edges[-1] + 1e-6)
        sec = range(max(sec.start, idx.start), min(sec.stop, idx.stop))
        times.append(round(edges[k + 1] - edges[k], 2))
        flows.append(mean_moving(flow, speed, sec) if flow else None)
        vals = [grit[i] for i in sec if grit[i] is not None] if grit else []
        grits.append(round(sum(vals) / GRIT_RECORD_SCALE, 3) if vals else None)
    return {"edges": edges, "idx": idx, "time_s": round(edges[-1] - edges[0], 1), "times": times, "flows": flows, "grits": grits,
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


def build_track(series: dict, lap: dict) -> CourseTrack | None:
    """The lap's outline as per-sector polylines in local metres (equirectangular projection around
    the lap centroid, north up), ~TRACK_POINTS points in all; None without usable GPS."""
    lat, lng = series.get("lat") or [], series.get("lng") or []
    idx, edges, t_s = lap["idx"], lap["edges"], series["t_s"]
    fixes = [i for i in idx if i < len(lat) and i < len(lng) and lat[i] is not None and lng[i] is not None]
    if len(fixes) < SECTOR_COUNT + 1:
        return None
    lat0 = sum(lat[i] for i in fixes) / len(fixes)
    lng0 = sum(lng[i] for i in fixes) / len(fixes)
    kx = EARTH_M_PER_DEG * math.cos(math.radians(lat0))

    def xy(i: int) -> tuple[float, float]:
        return round((lng[i] - lng0) * kx, 1), round((lat[i] - lat0) * EARTH_M_PER_DEG, 1)

    per_sector = max(2, TRACK_POINTS // SECTOR_COUNT)
    sectors, joined = [], None
    for k in range(SECTOR_COUNT):
        last = k == SECTOR_COUNT - 1
        mine = [i for i in fixes if edges[k] <= t_s[i] and (t_s[i] <= edges[k + 1] if last else t_s[i] < edges[k + 1])]
        if not mine:
            return None
        points = [xy(i) for i in _evenly(mine, per_sector)]
        if joined is not None:  # start where the previous sector ended so the outline is continuous
            points = [joined, *points[1:]] if len(points) > 1 else [joined, points[0]]
        joined = points[-1]
        sectors.append(TrackSector(sector=k + 1, points=points, label=points[len(points) // 2]))
    return CourseTrack(sectors=sectors)


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


def build_course_sectors(workout: Workout, series: dict | None, prefer_gps: bool = False) -> CourseSectors | None:
    """The sector comparison, or None unless 2..MAX_LAPS similar-distance laps can be cut by distance.
    `prefer_gps`: use GPS-detected laps before the device's own laps (a race whose laps were never pressed)."""
    if not series or not series.get("t_s") or not has_channel(series, "dist_m"):
        return None
    group = _course_laps(workout, series, prefer_gps)
    if not 2 <= len(group) <= MAX_LAPS:
        return None
    cut = []
    for n, lap, start, stop in group:
        s = _lap_sectors(series, window_indices(series["t_s"], start, stop))
        if s is None:
            return None
        cut.append((n, s))
    best_i = min(range(len(cut)), key=lambda i: cut[i][1]["time_s"])
    best = cut[best_i][1]
    laps = [
        SectorLap(lap=n, time_s=s["time_s"], avg_power_w=s["power"], avg_flow=s["flow"], grit=s["grit"],
                  time_vs_best_s=round(s["time_s"] - best["time_s"], 1), sector_times_s=s["times"])
        for n, s in cut
    ]
    others = [s for i, (_, s) in enumerate(cut) if i != best_i]
    sectors = []
    for k in range(SECTOR_COUNT):
        losses = [s["times"][k] - best["times"][k] for s in others]
        dflow = [s["flows"][k] - best["flows"][k] for s in others
                 if s["flows"][k] is not None and best["flows"][k] is not None]
        flows = [s["flows"][k] for _, s in cut if s["flows"][k] is not None]
        grits = [s["grits"][k] for _, s in cut if s["grits"][k] is not None]
        sectors.append(SectorLoss(
            sector=k + 1, best_time_s=best["times"][k], mean_loss_s=round(sum(losses) / len(losses), 2),
            total_loss_s=round(sum(losses), 2), avg_flow=_mean(flows), flow_vs_best=_mean(dflow),
            avg_grit=_mean(grits),
        ))
    ranked = sorted((s for s in sectors if s.total_loss_s > 0), key=lambda s: -s.total_loss_s)
    first, last = cut[0][1], cut[-1][1]
    flow_by_lap = [s["flow"] for _, s in cut if s["flow"] is not None]
    fade = LapFade(
        time_change_pct=_pct(last["time_s"], first["time_s"]) or 0.0,
        power_change_pct=_pct(last["power"], first["power"]),
        flow_change=round(last["flow"] - first["flow"], 2) if last["flow"] is not None and first["flow"] is not None else None,
        flow_slope_per_lap=_slope(flow_by_lap) if len(flow_by_lap) == len(cut) else None,
    )
    return CourseSectors(
        sector_count=SECTOR_COUNT, best_lap=cut[best_i][0], laps=laps, fade=fade, sectors=sectors,
        top_loss_sectors=[s.sector for s in ranked[:TOP_LOSS_SECTORS]],
        track=build_track(series, best),
    )
