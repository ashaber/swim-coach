"""What a coach reads from a ride with no prescribed structure -- pure, no I/O.

`read_free_ride` is the computation behind `BikeAnalyzer`'s free-ride behaviour
(`analysis.py`): a ride with no structure to score, even if it was on the calendar (a
scheduled group ride). It answers "where did the time go, what was the best of it, what did
it cost, and did it fit the week" -- see `library/41-free-ride-analysis.md` for the reasoning
and each constant's tag. Everything here is a read, never a score: a verdict (tempo creep)
exists only against a STATED intent (the matched session's structured intensity zone), never
against the athlete's purpose text.

All per-second reads run on the power curve's own 1 Hz riding timeline
(`power_curve.riding_samples`), so a notable effort's window is exactly the curve's best window.
"""

from __future__ import annotations

import statistics
from bisect import bisect_left
from dataclasses import dataclass
from datetime import date
from itertools import accumulate
from typing import Sequence

from swim_coach.analytics import cardiac_drift
from swim_coach.interval_analysis import COASTING_FLOOR_W
from swim_coach.load import session_load
from swim_coach.models import (
    FreeRideCost,
    FreeRideDrift,
    FreeRideEffort,
    FreeRideMatch,
    FreeRideMatches,
    FreeRideNeighbor,
    FreeRideRead,
    FreeRideZoneTime,
    Session,
    Workout,
    WorkoutAnalytics,
)
from swim_coach.power_curve import riding_samples
from swim_coach.zones import bike_zone_for_pct

# --- constants (library/41-free-ride-analysis.md; power zones are library/23 via zones.py) ---

# Coach judgment: heart-rate zone upper bounds as % of LTHR (inclusive), the usual five-band
# bike split; the library has no HR-zone table of its own (library/41).
HR_ZONE_UPPER_PCT_LTHR: tuple[tuple[str, float | None], ...] = (
    ("Z1", 81.0), ("Z2", 89.0), ("Z3", 93.0), ("Z4", 99.0), ("Z5", None),
)

# A stated intent counts as "easy" when the session's structured intensity zone is one of these.
EASY_INTENT_ZONES: frozenset[str] = frozenset({"Z1", "Z2"})
# Seiler (2010), library/24 "Framework grounding": ~80% low / ~20% high with little moderate
# time. Easy intent + more than this share of pedalling time at Z3+ reads as tempo creep.
TEMPO_CREEP_Z3_PLUS_PCT = 20.0
# Coach judgment: and at least this much absolute Z3+ time, so a short ride cannot trip it.
TEMPO_CREEP_MIN_S = 15 * 60

# Notable efforts: the curve's 20 / 5 / 1 min windows (threshold / VO2 / anaerobic anchors).
NOTABLE_WINDOWS_S: tuple[int, ...] = (1200, 300, 60)
ZONE_EFFORT_NAMES = {"Z3": "tempo", "Z4": "threshold", "Z5": "VO2max", "Z6": "anaerobic", "Z7": "sprint"}
# Coach judgment: a window is a "climb" at >= this average grade and >= this net gain.
CLIMB_MIN_GRADE_PCT = 3.0
CLIMB_MIN_GAIN_M = 50.0
ALTITUDE_END_SMOOTH_S = 5  # window ends are 5 s altitude means (the channel is noisy)

# Matches burned: 30 s centred power above FTP for >= 10 s, gaps < 10 s merged. Coach judgment;
# no W' model yet (library/29 lists CP/W' fitting as future work).
MATCH_SMOOTH_S = 30
MATCH_MIN_S = 10
MATCH_MERGE_GAP_S = 10
MATCH_PEAK_S = 5
MATCH_KEEP = 10  # efforts stored (totals always cover all of them)

# Steady stretches for drift: 60 s blocks, >= 90% pedalling, block-mean CV <= 12%, >= 20 min.
STEADY_BLOCK_S = 60
STEADY_MIN_PEDAL_FRAC = 0.9
STEADY_MAX_CV = 0.12
STEADY_MIN_S = 20 * 60
STEADY_MAX_SEGMENTS = 2

# Data quality (Coach judgment): outdoor rides here coast ~30%; at 50% zero/null power the
# power-based reads are not trustworthy. An altitude range under 30 m cannot support a climb call.
POWER_MISSING_PCT = 50.0
FLAT_ALTITUDE_RANGE_M = 30.0

KEY_ZONES: frozenset[str] = frozenset({"Z4", "Z5"})  # a planned workout this hard is "key"

POWER_MISSING_NOTE = (
    "Power is zero or missing for {pct:.0f}% of moving time (outdoor coasting is typically about 30%), "
    "so power reads are limited: no tempo verdict, no effort labels, no steady-stretch drift."
)


def is_key_session(session: Session) -> bool:
    """A race, or a planned workout that is structured or sits in Z4/Z5 (Coach judgment)."""
    if session.effective_kind == "race":
        return True
    if session.effective_kind != "workout":
        return False
    zone = (session.intensity or {}).get("zone")
    return session.structured is not None or zone in KEY_ZONES


@dataclass(frozen=True)
class _Timeline:
    """The ride on the 1 Hz riding timeline: index == riding second."""

    clock: list[float]  # original t_s of each riding second
    power: list[float]  # null -> 0 W
    power_null: list[bool]
    hr: list[float | None]
    alt: list[float | None]
    dist: list[float | None]


def _carry(vals: Sequence, src: list[int | None]) -> list:
    """`vals` on the riding timeline, a filled dropout repeating the last real sample."""
    out: list = []
    last = None
    for i in src:
        if i is not None and i < len(vals):
            last = vals[i]
        out.append(last)
    return out


def _timeline(series: dict) -> _Timeline | None:
    t_s, power = series.get("t_s") or [], series.get("power_w") or []
    if not t_s or not power or all(p is None for p in power):
        return None
    clock, src = riding_samples(t_s)
    if not clock:
        return None
    raw = [None if i is None or i >= len(power) else power[i] for i in src]
    return _Timeline(
        clock=clock,
        power=[0.0 if p is None else float(p) for p in raw],
        power_null=[p is None for p in raw],
        hr=_carry(series.get("hr") or [], src),
        alt=_carry(series.get("altitude_m") or [], src),
        dist=_carry(series.get("dist_m") or [], src),
    )


def _pct(part: float, whole: float) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


def _zone_times(counts: dict[str, int], order: Sequence[str]) -> list[FreeRideZoneTime]:
    total = sum(counts.values())
    return [FreeRideZoneTime(zone=z, seconds=counts.get(z, 0), pct=_pct(counts.get(z, 0), total)) for z in order]


def _power_zones(tl: _Timeline, ftp: float) -> list[FreeRideZoneTime]:
    counts: dict[str, int] = {}
    for p in tl.power:
        if p > COASTING_FLOOR_W:
            z = bike_zone_for_pct(100.0 * p / ftp)
            counts[z] = counts.get(z, 0) + 1
    return _zone_times(counts, [f"Z{i}" for i in range(1, 8)])


def _hr_zone(hr: float, lthr: float) -> str:
    pct = 100.0 * hr / lthr
    for name, hi in HR_ZONE_UPPER_PCT_LTHR:
        if hi is None or pct <= hi:
            return name
    return HR_ZONE_UPPER_PCT_LTHR[-1][0]


def _hr_zones(tl: _Timeline, lthr: float | None) -> list[FreeRideZoneTime]:
    if not lthr:
        return []
    counts: dict[str, int] = {}
    for h in tl.hr:
        if h is not None and h > 0:
            z = _hr_zone(h, lthr)
            counts[z] = counts.get(z, 0) + 1
    return _zone_times(counts, [z for z, _ in HR_ZONE_UPPER_PCT_LTHR]) if counts else []


def _mean(vals: Sequence[float | None]) -> float | None:
    real = [v for v in vals if v is not None]
    return statistics.fmean(real) if real else None


def _window_climb(tl: _Timeline, i: int, d: int) -> tuple[float | None, float | None]:
    """(net altitude gain m, average grade %) over riding seconds [i, i+d)."""
    k = ALTITUDE_END_SMOOTH_S
    start, end = _mean(tl.alt[i : i + k]), _mean(tl.alt[i + d - k : i + d])
    if start is None or end is None:
        return None, None
    gain = end - start
    d0, d1 = tl.dist[i], tl.dist[min(i + d, len(tl.dist)) - 1]
    run = d1 - d0 if d0 is not None and d1 is not None else 0.0
    return round(gain, 1), round(100.0 * gain / run, 1) if run > 0 else None


def _effort_label(pct_ftp: float, gain: float | None, grade: float | None, *, climbs_ok: bool) -> str | None:
    name = ZONE_EFFORT_NAMES.get(bike_zone_for_pct(pct_ftp))
    if name is None:
        return None
    is_climb = (
        climbs_ok and gain is not None and grade is not None
        and gain >= CLIMB_MIN_GAIN_M and grade >= CLIMB_MIN_GRADE_PCT
    )
    return f"{name} {'climb' if is_climb else 'effort'}"


def _notable_efforts(
    tl: _Timeline, analytics: WorkoutAnalytics, ftp: float, *, label_ok: bool, climbs_ok: bool
) -> list[FreeRideEffort]:
    t0 = tl.clock[0]
    curve = {p.duration_s: p for p in analytics.power_curve or []}
    out: list[FreeRideEffort] = []
    for d in NOTABLE_WINDOWS_S:
        point = curve.get(d)
        if point is None:
            continue
        i = bisect_left(tl.clock, point.start_s)
        gain, grade = _window_climb(tl, i, d)
        avg_hr = _mean(tl.hr[i : i + d])
        pct_ftp = round(100.0 * point.watts / ftp, 1)
        out.append(
            FreeRideEffort(
                duration_s=d,
                start_offset_s=round(point.start_s - t0, 1),
                avg_w=point.watts,
                pct_ftp=pct_ftp,
                avg_hr=round(avg_hr) if avg_hr is not None else None,
                altitude_gain_m=gain,
                avg_grade_pct=grade,
                label=_effort_label(pct_ftp, gain, grade, climbs_ok=climbs_ok) if label_ok else None,
                new_best_42d=point.is_best_42d,
                new_best_90d=point.is_best_90d,
            )
        )
    return out


def _centred_mean(vals: list[float], window: int) -> list[float]:
    n = len(vals)
    cum = [0.0, *accumulate(vals)]
    half = window // 2
    out = []
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        out.append((cum[hi] - cum[lo]) / (hi - lo))
    return out


def _above_runs(mask: list[bool]) -> list[tuple[int, int]]:
    """[start, end] (inclusive) of True runs, gaps shorter than MATCH_MERGE_GAP_S merged."""
    runs: list[list[int]] = []
    for i, m in enumerate(mask):
        if not m:
            continue
        if runs and i - runs[-1][1] - 1 < MATCH_MERGE_GAP_S:
            runs[-1][1] = i
        else:
            runs.append([i, i])
    return [(a, b) for a, b in runs]


def _best_mean(vals: list[float], window: int) -> float:
    if len(vals) <= window:
        return statistics.fmean(vals)
    cum = [0.0, *accumulate(vals)]
    return max(cum[i + window] - cum[i] for i in range(len(vals) - window + 1)) / window


def _matches(tl: _Timeline, ftp: float) -> FreeRideMatches:
    rolling = _centred_mean(tl.power, MATCH_SMOOTH_S)
    found: list[FreeRideMatch] = []
    for a, b in _above_runs([r > ftp for r in rolling]):
        dur = b - a + 1
        if dur < MATCH_MIN_S:
            continue
        seg = tl.power[a : b + 1]
        found.append(
            FreeRideMatch(
                start_offset_s=round(tl.clock[a] - tl.clock[0], 1),
                duration_s=dur,
                avg_w=round(statistics.fmean(seg)),
                peak_w=round(_best_mean(seg, MATCH_PEAK_S)),
                kj_above_ftp=round(sum(max(0.0, p - ftp) for p in seg) / 1000.0, 1),
            )
        )
    top = sorted(found, key=lambda m: m.kj_above_ftp, reverse=True)[:MATCH_KEEP]
    return FreeRideMatches(
        count=len(found),
        time_above_ftp_s=sum(m.duration_s for m in found),
        kj_above_ftp=round(sum(m.kj_above_ftp for m in found), 1),
        efforts=top,
    )


def _cv(vals: list[float]) -> float:
    mean = statistics.fmean(vals)
    return statistics.pstdev(vals) / mean if mean > 0 else float("inf")


def _steady_segments(tl: _Timeline) -> list[tuple[int, int]]:
    """Riding-second spans [a, b) of >= STEADY_MIN_S with low block-to-block power variation
    and few stops, longest first."""
    segs: list[tuple[int, int]] = []
    cur: list[float] = []
    cur_start = 0

    def close(end: int) -> None:
        if len(cur) * STEADY_BLOCK_S >= STEADY_MIN_S:
            segs.append((cur_start, end))

    n_blocks = len(tl.power) // STEADY_BLOCK_S
    for k in range(n_blocks):
        a = k * STEADY_BLOCK_S
        block = tl.power[a : a + STEADY_BLOCK_S]
        pedalling = sum(p > COASTING_FLOOR_W for p in block) / STEADY_BLOCK_S
        mean = statistics.fmean(block)
        if pedalling >= STEADY_MIN_PEDAL_FRAC and (not cur or _cv([*cur, mean]) <= STEADY_MAX_CV):
            if not cur:
                cur_start = a
            cur.append(mean)
            continue
        close(a)
        cur = []
        if pedalling >= STEADY_MIN_PEDAL_FRAC:
            cur_start, cur = a, [mean]
    close(n_blocks * STEADY_BLOCK_S)
    return sorted(segs, key=lambda s: s[1] - s[0], reverse=True)[:STEADY_MAX_SEGMENTS]


def _steady_drift(tl: _Timeline) -> list[FreeRideDrift]:
    out: list[FreeRideDrift] = []
    for a, b in _steady_segments(tl):
        sub = {"t_s": tl.clock[a:b], "hr": tl.hr[a:b], "power_w": tl.power[a:b]}
        drift = cardiac_drift(sub, laps=[])
        if drift is None:
            continue
        blocks = [statistics.fmean(tl.power[i : i + STEADY_BLOCK_S]) for i in range(a, b - STEADY_BLOCK_S + 1, STEADY_BLOCK_S)]
        out.append(
            FreeRideDrift(
                start_offset_s=round(tl.clock[a] - tl.clock[0], 1),
                duration_min=round((b - a) / 60.0, 1),
                avg_w=round(statistics.fmean(tl.power[a:b])),
                power_cv_pct=round(100.0 * _cv(blocks), 1),
                drift_pct=round(drift, 1),
            )
        )
    return sorted(out, key=lambda d: d.start_offset_s)


_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _neighbors(ride_date: date, sessions: Sequence[Session]) -> list[FreeRideNeighbor]:
    out: list[FreeRideNeighbor] = []
    for s in sorted(sessions, key=lambda s: s.date):
        delta = (s.date - ride_date).days
        if delta in (-1, 1) and is_key_session(s):
            out.append(
                FreeRideNeighbor(
                    relation="after" if delta == 1 else "before",
                    date=s.date,
                    title=s.title or s.purpose[:40],
                    kind=s.effective_kind,
                )
            )
    return out


def _cost(
    workout: Workout, analytics: WorkoutAnalytics, ftp: float, neighbors: Sequence[Session]
) -> FreeRideCost:
    """TSS from `load.session_load` (the same power-TSS the load model uses) and IF = NP / FTP."""
    rated = workout.model_copy(update={"analytics": analytics})
    load = session_load(rated, ftp_watts=ftp)
    np_w = analytics.normalized_power_w
    if load.tier != "power_tss" or np_w is None:
        return FreeRideCost()
    tss, intensity_factor = round(load.value, 0), round(np_w / ftp, 2)
    adjacent = _neighbors(workout.date, neighbors)
    note = f"TSS {tss:.0f}, IF {intensity_factor:.2f}"
    for n in adjacent:
        where = "the day before" if n.relation == "after" else "the day after"
        note += f"; {where} {_WEEKDAYS[n.date.weekday()]}'s key session ({n.title})"
    return FreeRideCost(tss=tss, intensity_factor=intensity_factor, adjacent_key_sessions=adjacent, note=note)


def _altitude_range(tl: _Timeline) -> float | None:
    alts = [a for a in tl.alt if a is not None]
    return round(max(alts) - min(alts), 1) if alts else None


def _creep(zones: list[FreeRideZoneTime], intent: str | None, power_ok: bool) -> tuple[float | None, bool | None, str | None]:
    """(Z3+ share of pedalling time, tempo_creep verdict, note). Verdict only against a stated
    easy intent and readable power."""
    z3_plus_s = sum(z.seconds for z in zones if z.zone not in ("Z1", "Z2"))
    total = sum(z.seconds for z in zones)
    share = _pct(z3_plus_s, total) if total else None
    if intent not in EASY_INTENT_ZONES or not power_ok or share is None:
        return share, None, None
    creep = share > TEMPO_CREEP_Z3_PLUS_PCT and z3_plus_s >= TEMPO_CREEP_MIN_S
    note = (
        f"Planned {intent} but {share:.0f}% of pedalling time ({z3_plus_s // 60} min) was Z3 or harder "
        f"(above the ~{TEMPO_CREEP_Z3_PLUS_PCT:.0f}% an easy day allows)."
        if creep
        else f"Planned {intent}; {share:.0f}% of pedalling time was Z3 or harder -- intensity fit the intent."
    )
    return share, creep, note


def read_free_ride(
    *,
    workout: Workout,
    analytics: WorkoutAnalytics,
    series: dict | None,
    ftp_watts: float | None,
    lthr_bpm: float | None,
    intent_zone: str | None = None,
    neighbors: Sequence[Session] = (),
) -> FreeRideRead | None:
    """The free-ride read, or `None` without a power channel or an FTP to anchor zones to.
    `analytics` is the ride's finished analytics (power curve with its bests, NP)."""
    if not series or not ftp_watts or ftp_watts <= 0:
        return None
    tl = _timeline(series)
    if tl is None:
        return None
    moving = len(tl.power)
    pedalling = sum(p > COASTING_FLOOR_W for p in tl.power)
    zero_null_pct = _pct(sum(p <= 0 or n for p, n in zip(tl.power, tl.power_null)), moving)
    alt_range = _altitude_range(tl)
    power_ok = zero_null_pct < POWER_MISSING_PCT
    climbs_ok = alt_range is not None and alt_range >= FLAT_ALTITUDE_RANGE_M
    notes: list[str] = []
    if not power_ok:
        notes.append(POWER_MISSING_NOTE.format(pct=zero_null_pct))
    if not climbs_ok:
        notes.append(
            "No altitude channel; climb calls skipped."
            if alt_range is None
            else f"Altitude range is only {alt_range:.0f} m (flat or unreliable altitude): climb calls skipped."
        )
    zones = _power_zones(tl, ftp_watts)
    z3_plus, creep, creep_note = _creep(zones, intent_zone, power_ok)
    drift = _steady_drift(tl) if power_ok else []
    return FreeRideRead(
        moving_s=moving,
        coasting_s=moving - pedalling,
        coasting_pct=_pct(moving - pedalling, moving),
        zero_or_null_power_pct=zero_null_pct,
        power_zones=zones,
        hr_zones=_hr_zones(tl, lthr_bpm),
        intent_zone=intent_zone,
        z3_plus_pct=z3_plus,
        tempo_creep=creep,
        tempo_creep_note=creep_note,
        notable_efforts=_notable_efforts(tl, analytics, ftp_watts, label_ok=power_ok, climbs_ok=climbs_ok),
        matches=_matches(tl, ftp_watts),
        cost=_cost(workout, analytics, ftp_watts, neighbors),
        steady_drift=drift,
        steady_note=(
            None
            if drift or not power_ok
            else f"No steady stretch of {STEADY_MIN_S // 60} min or more (power varied or stops); no drift read."
        ),
        altitude_range_m=alt_range,
        data_quality_notes=notes,
    )
