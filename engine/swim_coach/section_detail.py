"""Drill-down data for one course section: every lap's pass as a 1 Hz trace, cut into pieces.

Computed on request from the stored series and the stored `course_sectors` (the traces are never
persisted: they would swell the workout list payload). Each pass is cut into equal-DISTANCE pieces
(about PIECE_TARGET_S long); a piece says what that stretch cost against the other laps:

  free    faster than the other laps' median by more than the timing noise, on no more than PIECE_POWER_W more watts
  bought  faster than the median, on more than PIECE_POWER_W more watts
  saved   slower than the median, on more than PIECE_POWER_W fewer watts
  lost    slower than the median on the same or more watts
  par     within the timing noise of the median

Timing noise (`section_noise`): a piece's time is the difference of two edge crossings, so its sigma is
edge sigma * sqrt(2); a piece's loss is within noise when it is under the loss that noise alone produces.
The frame is the one of `course_sectors.track` (metres east/north of the best lap's centroid).

Constants are Coach judgment.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from statistics import median
from typing import Sequence

from swim_coach.course_features import project_xy
from swim_coach.course_sectors import _evenly, _fix_indices, _t_at
from swim_coach.models import CanonicalLap, CourseSectors
from swim_coach.mtb_dynamics import mean_present, window_indices
from swim_coach.section_noise import FALLBACK_EDGE_NOISE_S, loss_noise_floor

OUTLINE_MAX_POINTS = 400  # Coach judgment: a smooth outline on a phone, small on the wire
PIECE_TARGET_S = 10.0  # Coach judgment: a piece shorter than this is timing noise (a 2 s piece has ~0.4 s of it)
PIECE_MAX = 8  # Coach judgment: more pieces than this is unreadable on a section strip
PIECE_POWER_W = 15.0  # Coach judgment: a power difference under 15 W is within pass-to-pass variation of a piece average
TRACE_PAD_S = 1.0  # the points run one second beyond each edge so the line meets its neighbours


def piece_count(mean_duration_s: float) -> int:
    return min(max(round(mean_duration_s / PIECE_TARGET_S), 1), PIECE_MAX)


def classify_piece(time_s: float, power_w: float, others: Sequence[tuple[float, float]], sigma_s: float) -> str:
    """'free' | 'bought' | 'saved' | 'lost' | 'par' against the median of the other laps' `(time, power)`."""
    if not others:
        return "par"
    faster_by = median(t for t, _ in others) - time_s
    extra_w = power_w - median(p for _, p in others)
    if faster_by >= sigma_s:
        return "bought" if extra_w > PIECE_POWER_W else "free"
    if faster_by <= -sigma_s:
        return "saved" if extra_w < -PIECE_POWER_W else "lost"
    return "par"


def _edges(lap: CanonicalLap, times: Sequence[float]) -> list[float]:
    out = [lap.start_s]
    for t in times:
        out.append(out[-1] + t)
    return out


def _piece_times(series: dict, t0: float, t1: float, n: int) -> list[float]:
    """The n+1 times that cut [t0, t1] into n equal-distance pieces on the lap's own odometer."""
    t_s, dist = series["t_s"], series.get("dist_m") or []
    idx = window_indices(t_s, t0 - TRACE_PAD_S, t1 + TRACE_PAD_S + 1e-9)
    pts = [(t_s[i], dist[i]) for i in idx if dist and dist[i] is not None]
    if len(pts) < 2 or n == 1:
        return [t0 + (t1 - t0) * j / n for j in range(n + 1)]
    ts = [t for t, _ in pts]
    run = [pts[0][1]]
    for _, d in pts[1:]:
        run.append(max(d, run[-1]))
    da, db = _t_dist(ts, run, t0), _t_dist(ts, run, t1)
    return [t0, *(min(max(_t_at(run, ts, da + (db - da) * j / n), t0), t1) for j in range(1, n)), t1]


def _t_dist(ts: Sequence[float], run: Sequence[float], t: float) -> float:
    i = bisect_left(ts, t)
    if i <= 0:
        return run[0]
    if i >= len(ts):
        return run[-1]
    span = ts[i] - ts[i - 1]
    return run[i] if span <= 0 else run[i - 1] + (run[i] - run[i - 1]) * (t - ts[i - 1]) / span


def _nearest(times: Sequence[float], t: float) -> int:
    i = bisect_left(times, t)
    if i <= 0:
        return 0
    if i >= len(times):
        return len(times) - 1
    return i if times[i] - t < t - times[i - 1] else i - 1


def build_section_detail(series: dict | None, laps: Sequence[CanonicalLap], cs: CourseSectors) -> dict | None:
    """`{outline, sections}` for the drill-down map, or None without GPS."""
    if not series or not series.get("t_s") or not (series.get("lat") and series.get("lng")):
        return None
    by_n = {lap.n: lap for lap in laps}
    best = by_n.get(cs.best_lap)
    if best is None:
        return None
    t_s, power, flow = series["t_s"], series.get("power_w") or [], series.get("flow") or []
    best_idx = window_indices(t_s, best.start_s, best.end_s)
    fixes = _fix_indices(series, best_idx)
    if len(fixes) < 2:
        return None
    lat0 = sum(series["lat"][i] for i in fixes) / len(fixes)
    lng0 = sum(series["lng"][i] for i in fixes) / len(fixes)
    xy_of = dict(zip(range(len(t_s)), project_xy(series["lat"], series["lng"], range(len(t_s)), lat0, lng0)))
    outline = [[round(xy_of[i][0], 1), round(xy_of[i][1], 1)] for i in _evenly(fixes, OUTLINE_MAX_POINTS)]
    edge_s = cs.edge_noise_s if cs.edge_noise_s is not None else FALLBACK_EDGE_NOISE_S
    piece_sigma = edge_s * math.sqrt(2)
    lap_edges = {sl.lap: _edges(by_n[sl.lap], sl.sector_times_s) for sl in cs.laps if sl.lap in by_n}
    sections: dict[str, dict] = {}
    for k, row in enumerate(cs.sectors):
        label = row.label or str(row.sector)
        n_pieces = piece_count(sum(e[k + 1] - e[k] for e in lap_edges.values()) / len(lap_edges))
        passes: dict[int, dict] = {}
        for lap_n, e in lap_edges.items():
            t0, t1 = e[k], e[k + 1]
            idx = [i for i in window_indices(t_s, t0 - TRACE_PAD_S, t1 + TRACE_PAD_S + 1e-9) if xy_of[i] is not None]
            points = [[round(xy_of[i][0], 1), round(xy_of[i][1], 1), round(power[i]) if power and power[i] is not None else 0,
                       round(flow[i], 1) if flow and flow[i] is not None else 0] for i in idx]
            cuts = _piece_times(series, t0, t1, n_pieces)
            times = [t_s[i] for i in idx]
            pieces = []
            for a, b in zip(cuts, cuts[1:]):
                w = window_indices(t_s, a, b)
                p = mean_present(power, w) if power and len(w) else None
                pieces.append({"from_i": _nearest(times, a), "to_i": _nearest(times, b), "time_s": round(b - a, 2), "power_w": round(p) if p is not None else 0})
            passes[lap_n] = {"points": points, "pieces": pieces}
        _grade_pieces(passes, piece_sigma)
        everything = [p for v in passes.values() for p in v["points"]]
        sections[label] = {
            "bbox": [min(p[0] for p in everything), min(p[1] for p in everything), max(p[0] for p in everything), max(p[1] for p in everything)] if everything else [0, 0, 0, 0],
            "laps": {str(n): v for n, v in passes.items()},
        }
    return {"outline": outline, "edge_noise_s": cs.edge_noise_s, "sections": sections}


def _grade_pieces(passes: dict[int, dict], sigma_s: float) -> None:
    """Fill `loss_s`, `eff` and `within_noise` on every piece, comparing the same piece across laps."""
    n_laps = len(passes)
    floor = loss_noise_floor(sigma_s, n_laps)
    for i in range(len(next(iter(passes.values()))["pieces"])):
        fastest = min(v["pieces"][i]["time_s"] for v in passes.values())
        for lap_n, v in passes.items():
            piece = v["pieces"][i]
            others = [(o["pieces"][i]["time_s"], o["pieces"][i]["power_w"]) for n, o in passes.items() if n != lap_n]
            piece["loss_s"] = round(piece["time_s"] - fastest, 2)
            piece["within_noise"] = piece["loss_s"] <= floor
            piece["eff"] = classify_piece(piece["time_s"], piece["power_w"], others, sigma_s)
