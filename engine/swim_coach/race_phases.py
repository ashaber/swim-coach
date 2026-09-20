"""Race-phase pacing analysis: splits a race's power/speed series into an
isolated START phase plus N roughly-equal remaining phases, and compares
Normalized Power across them against a real, evidence-grounded
significance floor.

Motivating gap (2026-09-19 race-power-file-review discussion, Andrew):
the existing structured-workout analyzer (`interval_analysis.py`) checks
completed workouts against a PRESCRIBED template -- a race has no
prescribed target, and the existing whole-race decoupling number
(`analytics`) collapses an entire race's pacing into one figure, losing
exactly the early-vs-late distinction a real coach would ask about.

Deliberately time-based (elapsed seconds from the activity's first valid
sample), NOT lap-based -- works on any race series with no GPS channel
required, and is independent of `gps_laps.py` (a separate, unmerged
build that finds real per-course-lap boundaries from GPS position; this
module's "phase" concept doesn't need or assume laps exist). A future
caller with real lap boundaries (from `gps_laps.py`, or native FIT laps)
could plausibly want phases keyed to lap boundaries instead of raw
elapsed time -- deliberately out of scope here; see this module's own
`split_race_phases` docstring for the elapsed-time-thirds fallback this
implements instead, matching Næss (2021)/Hays (2018)'s own lap-by-lap
precedent generalized to a lap-agnostic split.

## Real research grounding (verified by direct fetch, 2026-09-19 research
pass against Andrew's own race-analysis question -- condensed here, full
citation list/confidence grading in the research pass' own report)

- **Næss S., Sollie O., Gløersen Ø.N., Losnegard T. (2021)** --
  "Exercise Intensity and Pacing Pattern During a Cross-Country Olympic
  Mountain Bike Race", Frontiers in Physiology 12:702415, DOI
  10.3389/fphys.2021.702415. XCO race, lap-by-lap: magnitude of
  individual supra-critical-power efforts fell 25 +/- 8% first-to-last
  lap while effort COUNT/duration held steady -- what degrades is effort
  QUALITY, not attempt rate. `[EVIDENCE: cycling]`.
- **Hays A., Devys S., Bertin D., Marquet L., Brisswalter J. (2018)** --
  "Understanding the Physiological Requirements of the Mountain Bike
  Cross-Country Olympic Race Format", Frontiers in Physiology 9:1062,
  DOI 10.3389/fphys.2018.01062. XCO, lap 1 -> lap 3: time above VT2 fell
  48.8% -> 34.7% -> 27.4%. `[EVIDENCE: cycling]`.
- **Protzen G.V., El Moussaoui El Azhari Y., García-López J., Boullosa
  D.A. (2026)** -- "Re-Examining Pacing Profiles in Elite Cross-Country
  Olympic Mountain Biking: The Influence of the Start Loop and
  Performance Level", IJSPP, DOI 10.1123/ijspp.2026-0139. 934 elite
  finishers, 10 major 2024 events: including the start loop in
  lap-speed-variability analysis raised median CV from ~1.1% to 8.5%
  (men) / 10.9% (women) -- roughly a 7x inflation. The start phase MUST
  be isolated, not folded into "early race" -- this is the direct
  motivation for `split_race_phases` always carving out a distinct
  `"start"` phase rather than treating the race as N uniform slices.
  `[EVIDENCE: cycling]`. The same research pass also confirmed (via a
  systematic review, Protzen et al., Sports Medicine - Open, DOI
  10.1186/s40798-026-00976-4) that a fast start is frequently a course-
  design artifact, not a pacing error -- so this module reports the start
  phase's own numbers without grading them as good/bad.
- **Mateo-March M., Barranco-Gil D., Hernández-Belmonte A., Javaloyes A.,
  Muriel X., Pallarés J.G., Lucia A., Valenzuela P.L. (2025)** --
  "Reliability of the durability concept in professional cyclists: a
  field-based study", Int J Sports Med, DOI 10.1055/a-2555-8961. Real
  within-athlete SEM for repeated power efforts: ~5% in general, ~2-3%
  for efforts >=1min. A phase-to-phase NP difference below this is not
  reliably distinguishable from normal day-to-day variation --
  `DEFAULT_SIGNIFICANCE_THRESHOLD_PCT` below uses the more conservative
  (wider) 5% figure, since a whole race phase is typically many minutes,
  not the tightly-controlled single-effort-length protocol the 2-3%
  figure was measured against. `[EVIDENCE: cycling]`.

`[ADAPTED: general-endurance]` note, applying to every citation above:
none of these papers studied cyclocross specifically -- the 2026-09-19
research pass ran a full literature sweep and found no peer-reviewed
cyclocross power/pacing study at all. Every finding here is adapted from
XCO (Olympic cross-country) mountain biking, the closest studied
discipline (same mass-start format, similar lap/loop structure).
Confidence: medium. **Test:** compare this module's read of a real CX
race file against the athlete's own memory of how the race actually felt
phase-by-phase, same as any other `[ADAPTED]` claim in this codebase.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from swim_coach import analytics

# Protzen et al. (2026) establishes THAT the start must be isolated; no
# paper in the 2026-09-19 research pass reports a real, citable start-
# phase DURATION for cyclocross or XCO. The one concrete number found
# (Wolfe/TrainingPeaks, a single practitioner's blog post analyzing one
# rider's file) was an ~15s opening sprint -- too thin (n=1, no peer
# review) to build a constant on. 90s is Coach judgment: deliberately
# generous relative to that anecdote, meant to capture the whole
# positioning scramble (Protzen's "start loop" concept), not just the
# opening effort -- override with a real detected lap-1 boundary
# (`gps_laps.detect_gps_laps`, a separate build) or a course-specific
# value when one is actually known for a given race/course.
DEFAULT_START_PHASE_S = 90.0

# Mateo-March et al. (2025): real within-athlete SEM ~2-3% for efforts
# >=1min, ~5% general/mixed-duration. The wider 5% is the default here
# since a race PHASE (many minutes) isn't the tightly-controlled
# single-effort-length protocol the tighter 2-3% figure was measured
# against -- callers with a narrower use case can pass a tighter
# `threshold_pct` explicitly.
DEFAULT_SIGNIFICANCE_THRESHOLD_PCT = 5.0

DEFAULT_NUM_REMAINING_PHASES = 3


@dataclass(frozen=True)
class RacePhase:
    """One phase of a race: `"start"` (the first `start_phase_s` seconds,
    always isolated per Protzen et al. 2026 -- see module docstring) or
    `"phase_N"` (1-indexed, one of `num_remaining_phases` roughly-equal
    slices covering the rest of the race). `normalized_power_w`/
    `avg_speed_mps` are `None` when that phase had no usable power/speed
    data -- never a crash, same posture `gps_laps.py`'s per-lap metrics
    already establish for this codebase."""

    name: str
    start_s: float
    end_s: float
    duration_s: float
    normalized_power_w: float | None
    avg_speed_mps: float | None


def _slice_by_time(series: dict, start_s: float, end_s: float) -> dict:
    """Every list-valued channel in `series`, restricted to samples with
    `start_s <= t_s <= end_s` -- TIME-based, not index-based (this module
    splits a race by elapsed time, not by any lap/index boundary)."""
    t_s = series.get("t_s")
    if not t_s:
        return {}
    lo: int | None = None
    hi: int | None = None
    for i, t in enumerate(t_s):
        if t is None:
            continue
        if t >= start_s and lo is None:
            lo = i
        if t <= end_s:
            hi = i
    if lo is None or hi is None or hi < lo:
        return {}
    return {k: v[lo:hi + 1] for k, v in series.items() if isinstance(v, list)}


def _avg_speed_mps(sliced: dict) -> float | None:
    """Mean of `speed_mps` over the slice, ignoring `None`s; falls back to
    distance-covered/duration via `dist_m` when `speed_mps` is absent or
    entirely `None` within the slice. Deliberately duplicated (not
    imported) from `gps_laps.py`'s identically-behaved helper -- that
    module is a separate, unrelated, unmerged build; this module has no
    dependency on it."""
    speed = sliced.get("speed_mps")
    if speed:
        clean = [s for s in speed if s is not None]
        if clean:
            return statistics.fmean(clean)
    dist = sliced.get("dist_m")
    t_s = sliced.get("t_s")
    if dist and t_s:
        usable = [(t, d) for t, d in zip(t_s, dist) if d is not None]
        if len(usable) >= 2:
            (t0, d0), (t1, d1) = usable[0], usable[-1]
            duration = t1 - t0
            if duration > 0:
                return (d1 - d0) / duration
    return None


def _phase(series: dict, name: str, start_s: float, end_s: float) -> RacePhase:
    sliced = _slice_by_time(series, start_s, end_s)
    np_w = analytics.normalized_power_w(sliced) if sliced else None
    speed = _avg_speed_mps(sliced) if sliced else None
    return RacePhase(
        name=name, start_s=start_s, end_s=end_s, duration_s=end_s - start_s,
        normalized_power_w=np_w, avg_speed_mps=speed,
    )


def split_race_phases(
    series: dict | None,
    *,
    start_phase_s: float = DEFAULT_START_PHASE_S,
    num_remaining_phases: int = DEFAULT_NUM_REMAINING_PHASES,
) -> list[RacePhase]:
    """Splits a race's `series` (the columnar dict `parse_files.
    _build_series` produces / `store.load_series` returns -- same shape
    `analytics.normalized_power_w` already consumes) into a real, isolated
    START phase (the first `start_phase_s` seconds -- see
    `DEFAULT_START_PHASE_S`'s own docstring for why this is isolated, not
    folded into "early race") followed by `num_remaining_phases`
    roughly-equal phases covering the rest of the race.

    Returns `[]` (never raises) for: a `None`/empty `series`; a series
    with no usable `t_s` channel; a race too short to even contain the
    start phase; or `num_remaining_phases < 1`. A `RacePhase` with
    `normalized_power_w`/`avg_speed_mps` of `None` means that specific
    phase had no usable power/speed data -- distinct from the whole call
    returning `[]`.
    """
    if not series:
        return []
    t_s = series.get("t_s")
    if not t_s:
        return []
    valid_t = [t for t in t_s if t is not None]
    if not valid_t:
        return []
    total_s = max(valid_t) - min(valid_t)
    if total_s <= start_phase_s or num_remaining_phases < 1:
        return []

    t0 = min(valid_t)
    phases = [_phase(series, "start", t0, t0 + start_phase_s)]
    remaining_s = total_s - start_phase_s
    phase_len = remaining_s / num_remaining_phases
    for i in range(num_remaining_phases):
        p_start = t0 + start_phase_s + i * phase_len
        p_end = t0 + start_phase_s + (i + 1) * phase_len
        phases.append(_phase(series, f"phase_{i + 1}", p_start, p_end))
    return phases


def phase_difference_is_significant(
    np_a: float | None,
    np_b: float | None,
    *,
    threshold_pct: float = DEFAULT_SIGNIFICANCE_THRESHOLD_PCT,
) -> bool | None:
    """Whether two phases' Normalized Power values differ by more than
    normal within-athlete variation -- see `DEFAULT_SIGNIFICANCE_
    THRESHOLD_PCT`'s own docstring (Mateo-March et al. 2025) for the real
    evidence behind the default floor. A caller comparing `RacePhase`
    values across a race should use this rather than eyeballing raw
    percent differences, so a routine ~2% wobble doesn't get reported as
    a real pacing/fatigue signal.

    Returns `None` (a genuinely unknown answer, distinct from `False`)
    when either input is `None` or `np_a` is `0` (an undefined percent
    difference) -- never raises, never silently reads missing data as
    "not significant", which would be a different, false claim.
    """
    if np_a is None or np_b is None or np_a == 0:
        return None
    pct_diff = abs(np_b - np_a) / np_a * 100
    return pct_diff >= threshold_pct
