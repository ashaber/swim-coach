"""A synthetic CX-style race recording for the canonical-lap tests (no real GPS).

Timeline at 1 Hz, 3 m/s (one sample = 3 m):
  0-200 s    warm-up, riding east along a line 450 m south of the lap mark
  200-480 s  waiting on the start grid (stationary, 0 W) at (0, -450)
  480 s      the gun (RACE_START_S); the grid is 450 m (150 s) south of the mark
  630 s      first crossing of the mark (0, 0): the first full device lap starts here
  4 square loops of 600 m (200 s) from the mark, crossings at 630/830/1030/1230/1430 s
  1430-1490  a 60 s finish remainder past the mark

Device laps (the raw, messy list the watch recorded):
  - one long lap from 0 s to the first crossing (warm-up + wait + the start run-in)
  - a double-trigger hairpin fragment: each long lap ends 17 s early and the 17 s tail is its own lap
  - the auto-lap at the 1030 s crossing was missed: one lap covers 830 s -> 1230 s
  - the 60 s finish remainder
"""

from __future__ import annotations

import math
import uuid
from datetime import date

from swim_coach.models import Workout, WorkoutLap

LAT0, LNG0 = 45.0, -122.0
M_PER_DEG = 111_320.0
SPEED = 3.0
RACE_START_S = 480.0
CROSSINGS = [630.0, 830.0, 1030.0, 1230.0, 1430.0]
END_S = 1490.0
FRAGMENT_S = 17.0


def _ll(x: float, y: float) -> tuple[float, float]:
    return LAT0 + y / M_PER_DEG, LNG0 + x / (M_PER_DEG * math.cos(math.radians(LAT0)))


def _position(t: int) -> tuple[float, float]:
    if t < 200:
        return -600.0 + SPEED * t, -450.0
    if t < 480:
        return 0.0, -450.0
    if t < 630:
        return 0.0, -450.0 + SPEED * (t - 480)
    d = SPEED * ((t - 630) % 200)  # distance along the 150 m square, anticlockwise from the mark
    if t >= 1430:
        return min(d, 150.0), 0.0
    if d < 150:
        return d, 0.0
    if d < 300:
        return 150.0, d - 150
    if d < 450:
        return 150.0 - (d - 300), 150.0
    return 0.0, 150.0 - (d - 450)


def race_series() -> dict:
    t_s, lat, lng, dist, power, hr, flow, speed = [], [], [], [], [], [], [], []
    total = 0.0
    prev = None
    for t in range(int(END_S)):
        x, y = _position(t)
        if prev is not None:
            total += math.hypot(x - prev[0], y - prev[1])
        prev = (x, y)
        la, lo = _ll(x, y)
        waiting = 200 <= t < 480
        t_s.append(float(t))
        lat.append(la)
        lng.append(lo)
        dist.append(round(total, 2))
        power.append(0.0 if waiting else (150.0 if t < 200 else 250.0))
        hr.append(110.0 if t < 480 else 170.0)
        flow.append(0.0 if waiting else 3.0)
        speed.append(0.0 if waiting else SPEED)
    return {"t_s": t_s, "lat": lat, "lng": lng, "dist_m": dist, "power_w": power, "hr": hr, "flow": flow, "speed_mps": speed}


def _lap(index: int, start: float, end: float, series: dict, avg_hr: int) -> WorkoutLap:
    i, j = int(start), min(int(end), len(series["t_s"]) - 1)
    return WorkoutLap(
        index=index, start_offset_s=start, duration_s=end - start,
        distance_m=round(series["dist_m"][j] - series["dist_m"][i], 2),
        avg_power_w=round(sum(series["power_w"][i:j]) / max(j - i, 1), 1), avg_hr=avg_hr,
    )


def race_device_laps(series: dict) -> list[WorkoutLap]:
    c = CROSSINGS
    spans = [(0.0, c[0])]
    spans += [(c[0], c[1] - FRAGMENT_S), (c[1] - FRAGMENT_S, c[1])]
    spans += [(c[1], c[3] - FRAGMENT_S), (c[3] - FRAGMENT_S, c[3])]  # the auto-lap at c[2] was missed
    spans += [(c[3], c[4] - FRAGMENT_S), (c[4] - FRAGMENT_S, c[4])]
    spans += [(c[4], END_S)]
    return [_lap(i, a, b, series, 110 if a < RACE_START_S else 170) for i, (a, b) in enumerate(spans)]


def race_workout(series: dict | None = None) -> Workout:
    series = series or race_series()
    return Workout(
        id=uuid.uuid4(), athlete_id=uuid.uuid4(), date=date(2026, 10, 17), sport="bike", source="fit",
        distance_m=series["dist_m"][-1], duration_min=END_S / 60, laps=race_device_laps(series),
    )
