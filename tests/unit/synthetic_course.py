"""Synthetic closed course for the section tests: straights joined by arcs, driven at constant speed.

Coordinates are made up (a local frame around (47.0, 8.0)) -- never real GPS. `loop_xy` lays the
course out in metres; `ride` samples N laps of it at 1 Hz into a `series` dict.
"""

from __future__ import annotations

import math

LAT0, LNG0 = 47.0, 8.0
M_PER_DEG = 111_320.0

# (kind, length_m, turn_deg): a rectangle with rounded corners and an S-bend on the long top side.
# Heading starts east; positive turn = left (counter-clockwise).
RECT_WITH_S_BEND = [
    ("line", 150.0, 0.0),
    ("arc", 12.0, 90.0),    # corner 1
    ("line", 100.0, 0.0),
    ("arc", 12.0, 90.0),    # corner 2
    ("line", 138.3, 0.0),
    ("arc", 10.0, -80.0),   # S-bend, right...
    ("line", 15.0, 0.0),    # a short link between the two bends (still one corner sequence)
    ("arc", 10.0, 80.0),    # ...then left, back to the old heading
    ("line", 141.0, 0.0),
    ("arc", 12.0, 90.0),    # corner 3
    ("line", 130.8, 0.0),
    ("arc", 12.0, 90.0),    # corner 4
    ("line", 150.0, 0.0),   # back to the line: the lap starts and ends mid-straight
]


def loop_xy(spec: list[tuple[str, float, float]], step_m: float = 1.0) -> list[tuple[float, float]]:
    """Dense polyline (every `step_m`) of the course described by `spec`; a "line" is (len, _), an
    "arc" is (radius, turn degrees). The loop is closed by a final straight back to the origin."""
    x = y = 0.0
    heading = 0.0
    pts = [(x, y)]
    for kind, size, turn in spec:
        if kind == "line":
            for _ in range(int(size / step_m)):
                x, y = x + step_m * math.cos(heading), y + step_m * math.sin(heading)
                pts.append((x, y))
        else:
            arc_len = abs(math.radians(turn)) * size
            dtheta = math.radians(turn) / max(1, int(arc_len / step_m))
            for _ in range(max(1, int(arc_len / step_m))):
                heading += dtheta
                x, y = x + step_m * math.cos(heading), y + step_m * math.sin(heading)
                pts.append((x, y))
    return pts


def _along(pts: list[tuple[float, float]], s: float) -> tuple[float, float]:
    """Point `s` metres along a dense polyline that is treated as a loop."""
    seg = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    seg.append(math.dist(pts[-1], pts[0]))
    total = sum(seg)
    s %= total
    for i, d in enumerate(seg):
        if s <= d:
            a, b = pts[i], pts[(i + 1) % len(pts)]
            f = s / d if d else 0.0
            return a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
        s -= d
    return pts[0]


def loop_length(pts: list[tuple[float, float]]) -> float:
    return sum(math.dist(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts)))


def ride(pts: list[tuple[float, float]], lap_speeds: list[float], slow: dict[int, tuple[float, float, float]] | None = None,
         length_scale: float = 1.0) -> dict:
    """1 Hz series for `len(lap_speeds)` laps at constant per-lap speed (m/s). `slow[lap] = (from_m, to_m,
    speed)` rides that stretch of that lap slower. `length_scale` stretches the ridden distance (the
    odometer reads long/short) without changing the route."""
    total = loop_length(pts)
    t = 0.0
    s = 0.0
    lap = 0
    lap_start_s = 0.0
    out: dict = {"t_s": [], "lat": [], "lng": [], "dist_m": [], "speed_mps": []}
    odo = 0.0
    while lap < len(lap_speeds):
        v = lap_speeds[lap]
        if slow and lap in slow:
            a, b, sv = slow[lap]
            if a <= s - lap_start_s <= b:
                v = sv
        x, y = _along(pts, s)
        out["t_s"].append(t)
        out["lat"].append(LAT0 + y / M_PER_DEG)
        out["lng"].append(LNG0 + x / (M_PER_DEG * math.cos(math.radians(LAT0))))
        out["dist_m"].append(odo)
        out["speed_mps"].append(v)
        t += 1.0
        s += v
        odo += v * length_scale
        if s - lap_start_s >= total:
            lap += 1
            lap_start_s = s
    return out
