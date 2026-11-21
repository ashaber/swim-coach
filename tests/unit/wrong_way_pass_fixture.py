"""A synthetic CX-style race whose course runs back past the lap mark the OPPOSITE way (no real GPS).

The mark is the origin; the course leaves it heading north. The return leg runs south 12 m east of
the mark (a wrong-way pass, ~80 s before the real pass), loops round and arrives at the mark heading
north again. Loop = 409 s at 3 m/s. 1 Hz.

  gun at 335 s (5 s / 15 m before the first mark pass, a rolling start grid)
  mark passes (north) at 340 + 409 k, k = 0..6   -> 340, 749, 1158, 1567, 1976, 2385, 2794
  wrong-way passes at 260 + 409 k                -> 260, 669, 1078, 1487, 1896, 2305, 2714
  recording ends 51 s after the last mark pass (cool-down)

Device laps: the athlete pressed nothing until the third mark pass, so one long lap from 0 s to 1158;
from then on the watch split at the mark AND at the wrong-way pass; a 51 s lap after the last pass.
"""

from __future__ import annotations

import math

from swim_coach.models import WorkoutLap

LAT0, LNG0 = 45.0, -122.0
M_PER_DEG = 111_320.0
SPEED = 3.0
LOOP_S = 409
GUN_S = 335.0
FIRST_PASS_S = 340
MARK_PASSES = [float(FIRST_PASS_S + LOOP_S * k) for k in range(7)]
WRONG_WAY_PASSES = [p - 80.0 for p in MARK_PASSES]
END_S = MARK_PASSES[-1] + 51.0
WAYPOINTS = [(0, 0), (0, 300), (200, 300), (200, 100), (12, 100), (12, -113.5), (0, -113.5), (0, 0)]


def ll(x: float, y: float) -> tuple[float, float]:
    return LAT0 + y / M_PER_DEG, LNG0 + x / (M_PER_DEG * math.cos(math.radians(LAT0)))


def _loop_xy(u: float) -> tuple[float, float]:
    d = SPEED * u
    for (x0, y0), (x1, y1) in zip(WAYPOINTS, WAYPOINTS[1:]):
        seg = math.hypot(x1 - x0, y1 - y0)
        if d <= seg:
            f = d / seg
            return x0 + f * (x1 - x0), y0 + f * (y1 - y0)
        d -= seg
    return WAYPOINTS[-1]


def wrong_way_series(*, gps: bool = True) -> dict:
    n = int(END_S)
    xy = [_loop_xy((t - FIRST_PASS_S) % LOOP_S) for t in range(n)]
    dist, total = [], 0.0
    for t in range(n):
        if t:
            total += math.hypot(xy[t][0] - xy[t - 1][0], xy[t][1] - xy[t - 1][1])
        dist.append(round(total, 2))
    series = {
        "t_s": [float(t) for t in range(n)], "dist_m": dist, "power_w": [200.0] * n, "hr": [160.0] * n,
        "speed_mps": [SPEED] * n,
    }
    if gps:
        series["lat"] = [ll(*p)[0] for p in xy]
        series["lng"] = [ll(*p)[1] for p in xy]
    return series


def _lap(index: int, start: float, end: float, series: dict) -> WorkoutLap:
    i, j = int(start), min(int(end), len(series["t_s"]) - 1)
    return WorkoutLap(
        index=index, start_offset_s=start, duration_s=end - start,
        distance_m=round(series["dist_m"][j] - series["dist_m"][i], 2), avg_power_w=200.0, avg_hr=160,
    )


def wrong_way_device_laps(series: dict) -> list[WorkoutLap]:
    """One long lap to the third mark pass, then a split at each wrong-way pass and each mark pass."""
    cuts = [0.0, MARK_PASSES[2]]
    for k in range(3, 7):
        cuts += [WRONG_WAY_PASSES[k], MARK_PASSES[k]]
    cuts.append(END_S)
    return [_lap(i, a, b, series) for i, (a, b) in enumerate(zip(cuts, cuts[1:]))]
