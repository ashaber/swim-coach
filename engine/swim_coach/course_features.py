"""Course features: split a repeated lap into straights and corner sequences, and line laps up by position.

Pure geometry, no I/O. `segment_course` works on the reference (best) lap's projected track: it flags
cornering samples (turn rate, or Garmin's per-second flow where the device records it), merges corners
that sit close together into one corner sequence, absorbs slivers of straight, and caps the section
count. `align_edges` then maps another lap's samples onto the reference track (forward windowed
nearest point, so close parallel sections are never confused) and reads off when that lap crossed each
section boundary -- independent of how far the odometer thinks the lap was.

Constants are Coach judgment, tuned on the 2026-10-17 CX race file (per-second flow ~0 on straights,
~4.5 at 10-30 deg/s, ~13 at 30-60 deg/s, ~20 above 60 deg/s; see `bike_coach_view.COURSE_SECTORS_COACH_NOTE`).
"""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass, replace
from typing import Sequence

from swim_coach.lap_normalise import EARTH_M_PER_DEG

XY = tuple[float, float]

TURN_RATE_DEG_S = 20.0  # Coach judgment: a turn this fast at race speed is a corner, not a gentle bend
FLOW_CORNER = 3.0  # Coach judgment: Garmin flow at/above this is cornering (straights read ~0)
SMOOTH_SAMPLES = 3  # Coach judgment: moving-average width of the turn rate (1 Hz GPS is noisy)
STATIONARY_STEP_M = 0.5  # Coach judgment: a smaller step than this carries no heading
CORNER_JOIN_M = 25.0  # Coach judgment: corners closer together than this ride as one corner sequence
MIN_STRAIGHT_M = 30.0  # Coach judgment: a start/finish straight shorter than this is absorbed into its corner
TURN_EXTEND_DEG_S = 8.0  # Coach judgment: a corner reaches out to neighbouring samples still turning this fast (1 Hz smears an arc)
MIN_CORNER_TURN_DEG = 35.0  # Coach judgment: a bend that turns less than this in total is a kink in a straight, not a corner
MIN_SPLIT_PARTS = 2  # Coach judgment: a split into one part is no split
MAX_SPLIT_PARTS = 4  # Coach judgment: more parts than this are shorter than the timing noise of a 1 Hz edge
MIN_SECTIONS = 4  # Coach judgment: fewer than this is no more informative than equal-distance sectors
MAX_SECTIONS = 24  # Coach judgment: more than this is too fine to read in a phone grid
ALIGN_WINDOW_FRAC = 0.125  # Coach judgment: the match may move at most this share of the reference lap ahead per sample
ALIGN_WINDOW_MIN = 15  # Coach judgment: ...but never less than this many reference samples
_RELAX_STEPS = (1.0, 1.5, 2.0, 3.0, 4.0)  # thresholds are scaled up until the section cap is met


@dataclass(frozen=True)
class Section:
    """One course section on the reference lap, as samples `start_i..end_i` of its track (adjacent
    sections share the boundary sample)."""

    index: int  # 1-based
    kind: str  # "straight" | "corners"
    label: str  # "S1" / "C2": numbered within its kind, in lap order
    start_i: float  # fractional only for the parts of a split section
    end_i: float
    start_m: float
    end_m: float
    split_of: str | None = None  # the label of the section this part was split from

    @property
    def length_m(self) -> float:
        return round(self.end_m - self.start_m, 1)


def project_xy(lat: Sequence[float | None], lng: Sequence[float | None], idx: Sequence[int], lat0: float, lng0: float) -> list[XY | None]:
    """Equirectangular projection (metres east / north of `lat0, lng0`) of the fixes at `idx`; None
    where a fix is missing."""
    kx = EARTH_M_PER_DEG * math.cos(math.radians(lat0))
    out: list[XY | None] = []
    for i in idx:
        if i < len(lat) and i < len(lng) and lat[i] is not None and lng[i] is not None:
            out.append(((lng[i] - lng0) * kx, (lat[i] - lat0) * EARTH_M_PER_DEG))
        else:
            out.append(None)
    return out


def _wrap_deg(d: float) -> float:
    return (d + 180.0) % 360.0 - 180.0


def turn_rates(xy: Sequence[XY], t: Sequence[float]) -> list[float]:
    """Absolute heading change per second (deg/s) at every sample, moving-averaged over SMOOTH_SAMPLES."""
    n = len(xy)
    heading: list[float | None] = []
    for i in range(n - 1):
        dx, dy = xy[i + 1][0] - xy[i][0], xy[i + 1][1] - xy[i][1]
        heading.append(math.degrees(math.atan2(dy, dx)) if math.hypot(dx, dy) >= STATIONARY_STEP_M else None)
    raw = [0.0] * n
    for i in range(1, n - 1):
        a, b = heading[i - 1], heading[i]
        dt = t[i + 1] - t[i - 1]
        if a is not None and b is not None and dt > 0:
            raw[i] = abs(_wrap_deg(b - a)) / (dt / 2)
    half = SMOOTH_SAMPLES // 2
    return [sum(raw[max(0, i - half): i + half + 1]) / len(raw[max(0, i - half): i + half + 1]) for i in range(n)]


def cumulative_m(xy: Sequence[XY]) -> list[float]:
    cum = [0.0]
    for i in range(1, len(xy)):
        cum.append(cum[-1] + math.dist(xy[i - 1], xy[i]))
    return cum


def _runs(flags: Sequence[bool]) -> list[list]:
    """`[is_corner, first, last]` per maximal run of equal flags."""
    runs: list[list] = []
    for i, f in enumerate(flags):
        if runs and runs[-1][0] == f:
            runs[-1][2] = i
        else:
            runs.append([f, i, i])
    return runs


def _coalesce(runs: list[list]) -> list[list]:
    out: list[list] = []
    for r in runs:
        if out and out[-1][0] == r[0]:
            out[-1][2] = r[2]
        else:
            out.append(list(r))
    return out


def _extend(corner: list[bool], rate: Sequence[float]) -> list[bool]:
    """Grow every corner run over neighbouring samples that are still turning (TURN_EXTEND_DEG_S)."""
    out = list(corner)
    for order in (range(len(corner)), range(len(corner) - 1, -1, -1)):
        for i in order:
            for j in (i - 1, i + 1):
                if 0 <= j < len(corner) and out[j] and not out[i] and rate[i] >= TURN_EXTEND_DEG_S:
                    out[i] = True
    return out


def _running_turn(rate: Sequence[float], t: Sequence[float]) -> list[float]:
    total, out = 0.0, []
    for i, r in enumerate(rate):
        total += r * ((t[i + 1] - t[i - 1]) / 2 if 0 < i < len(rate) - 1 else 0.0)
        out.append(total)
    return out


def _span(cum: Sequence[float], first: int, last: int) -> float:
    return cum[last] - cum[first]


def _merge(runs: list[list], cum: Sequence[float], turn: Sequence[float], scale: float) -> list[list]:
    """Drop kinks, join corners that are close together, absorb start/finish slivers. `turn` is the
    running total of heading change (degrees) per sample."""
    runs = [[c and turn[b] - (turn[a - 1] if a else 0.0) >= MIN_CORNER_TURN_DEG * scale, a, b] for c, a, b in runs]
    runs = _coalesce(runs)
    runs = [[True if (not c and 0 < k < len(runs) - 1 and _span(cum, a, b) < CORNER_JOIN_M * scale) else c, a, b]
            for k, (c, a, b) in enumerate(runs)]
    runs = _coalesce(runs)
    if len(runs) > 1 and not runs[0][0] and _span(cum, runs[0][1], runs[0][2]) < MIN_STRAIGHT_M * scale:
        runs[0][0] = True
    if len(runs) > 1 and not runs[-1][0] and _span(cum, runs[-1][1], runs[-1][2]) < MIN_STRAIGHT_M * scale:
        runs[-1][0] = True
    return _coalesce(runs)


def _label(kind: str, counts: dict[str, int]) -> str:
    counts[kind] = counts.get(kind, 0) + 1
    return f"{'C' if kind == 'corners' else 'S'}{counts[kind]}"


def segment_course(xy: Sequence[XY], t: Sequence[float], flow: Sequence[float | None] | None) -> list[Section] | None:
    """The reference lap's sections in lap order, or None when the track has fewer than MIN_SECTIONS
    (a featureless loop) or cannot be brought under MAX_SECTIONS."""
    n = len(xy)
    if n < 2 * MIN_SECTIONS:
        return None
    rate = turn_rates(xy, t)
    corner = [rate[i] >= TURN_RATE_DEG_S or (flow is not None and (flow[i] or 0.0) >= FLOW_CORNER) for i in range(n)]
    corner = _extend(corner, rate)
    cum = cumulative_m(xy)
    turn = _running_turn(rate, t)
    raw = _runs(corner)
    for scale in _RELAX_STEPS:
        runs = _merge(raw, cum, turn, scale)
        if len(runs) <= MAX_SECTIONS:
            break
    else:
        return None
    if len(runs) < MIN_SECTIONS:
        return None
    counts: dict[str, int] = {}
    sections = []
    for k, (is_corner, first, _) in enumerate(runs):
        end_i = runs[k + 1][1] if k + 1 < len(runs) else n - 1
        kind = "corners" if is_corner else "straight"
        sections.append(Section(index=k + 1, kind=kind, label=_label(kind, counts), start_i=first, end_i=end_i,
                                start_m=round(cum[first], 1), end_m=round(cum[end_i], 1)))
    return sections


def _along_segment(p: XY, a: XY, b: XY) -> tuple[float, float]:
    """`(distance, u)`: how far `p` is from segment a-b and where along it (0..1) the nearest point sits."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    seg2 = dx * dx + dy * dy
    u = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / seg2))
    return math.hypot(p[0] - (a[0] + u * dx), p[1] - (a[1] + u * dy)), u


def track_positions(ref_xy: Sequence[XY], lap_xy: Sequence[XY | None]) -> list[float | None]:
    """Fractional reference-sample index of every lap sample: the nearest point on the reference track
    searched forward only, within a window of the previous match; never decreasing. None for samples
    without a fix."""
    n = len(ref_xy)
    window = max(ALIGN_WINDOW_MIN, int(n * ALIGN_WINDOW_FRAC))
    prev = 0.0
    out: list[float | None] = []
    for p in lap_xy:
        if p is None:
            out.append(None)
            continue
        best_d, best_pos = math.inf, prev
        for m in range(int(prev), min(n - 1, int(prev) + window + 1)):
            d, u = _along_segment(p, ref_xy[m], ref_xy[m + 1])
            if d < best_d and m + u >= prev - 1e-9:
                best_d, best_pos = d, m + u
        prev = max(prev, best_pos)
        out.append(prev)
    return out


def align_edges(ref_xy: Sequence[XY], bounds: Sequence[int], lap_xy: Sequence[XY | None], lap_t: Sequence[float]) -> list[float] | None:
    """When this lap crossed every section boundary (`bounds`: reference sample indices, first to
    last), as times in `lap_t`'s clock: the first edge is the lap's first fix, the last its last fix.
    None when the lap never gets to some boundary (it does not follow the reference course)."""
    pos = track_positions(ref_xy, lap_xy)
    fixed = [(p, t) for p, t in zip(pos, lap_t) if p is not None]
    if len(fixed) < 2:
        return None
    edges = [fixed[0][1]]
    for b in bounds[1:-1]:
        k = next((k for k, (p, _) in enumerate(fixed) if p >= b), None)
        if k is None:
            return None
        if k == 0:
            edges.append(fixed[0][1])
            continue
        (p0, t0), (p1, t1) = fixed[k - 1], fixed[k]
        edges.append(t0 + (t1 - t0) * ((b - p0) / (p1 - p0) if p1 > p0 else 0.0))
    edges.append(fixed[-1][1])
    return [max(e, edges[i - 1]) if i else e for i, e in enumerate(edges)]


def _index_at(cum: Sequence[float], d: float) -> float:
    """Fractional sample index at distance `d` along the track."""
    k = min(max(bisect_right(cum, d) - 1, 0), len(cum) - 2)
    span = cum[k + 1] - cum[k]
    return k + (0.0 if span <= 0 else (d - cum[k]) / span)


def split_sections(sections: Sequence[Section], cum: Sequence[float], splits: dict[str, int]) -> list[Section]:
    """`sections` with each section named in `splits` cut into that many equal-DISTANCE parts, labelled
    `<label>a`, `<label>b`, ...; a count outside MIN..MAX_SPLIT_PARTS or an unknown label is ignored."""
    out: list[Section] = []
    for sec in sections:
        n = splits.get(sec.label, 0)
        if not MIN_SPLIT_PARTS <= n <= MAX_SPLIT_PARTS:
            out.append(replace(sec, index=len(out) + 1))
            continue
        d0, d1 = cum[int(sec.start_i)], cum[int(sec.end_i)]
        cuts = [sec.start_i, *(_index_at(cum, d0 + (d1 - d0) * j / n) for j in range(1, n)), sec.end_i]
        for j in range(n):
            out.append(Section(index=len(out) + 1, kind=sec.kind, label=f"{sec.label}{chr(97 + j)}", start_i=cuts[j], end_i=cuts[j + 1],
                               start_m=round(d0 + (d1 - d0) * j / n, 1), end_m=round(d0 + (d1 - d0) * (j + 1) / n, 1), split_of=sec.label))
    return out
