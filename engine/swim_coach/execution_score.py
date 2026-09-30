"""Deterministic execution scores (0-100) with a transparent breakdown.

Pure functions, no I/O, no LLM:

- `workout_execution_score` scores a bike workout against the session it was
  planned as, from the prescription-aware interval analyzer
  (`interval_analysis.analyze` -> `WorkoutIntervals`).
- `race_execution_score` scores a race ride from the deterministic race
  outputs that already exist (`race_phases.split_race_phases` and
  `gps_laps.analyze_gps_laps`): pacing evenness, late-race fade, start
  control, lap-to-lap consistency.

Every weight and scale below is `Coach judgment:` -- no study supports a
specific formula for combining these (see `library/11-workout-analytics.md`,
"Execution scores"). The only evidence-backed number reused is the 5%
within-athlete variation floor (`race_phases.DEFAULT_SIGNIFICANCE_THRESHOLD_PCT`,
Mateo-March et al. 2025): differences under it are not scored as errors.

A component the workout has no data for is dropped and the remaining weights
are renormalized, so the breakdown always sums to the reported score.
"""

from __future__ import annotations

import statistics

from swim_coach.gps_laps import GpsLapMetrics
from swim_coach.models import ExecutionComponent, ExecutionScore, Session, Workout, WorkoutIntervals
from swim_coach.race_phases import DEFAULT_SIGNIFICANCE_THRESHOLD_PCT, RacePhase

# Coach judgment: intensity (did the reps land in the prescribed band) is the
# point of a structured session; completion and consistency support it.
WORKOUT_WEIGHTS: dict[str, float] = {"intensity": 0.50, "completion": 0.30, "consistency": 0.20}
# Coach judgment: fade at or under the 5% within-athlete variation floor costs
# nothing; the consistency score reaches 0 at 20% fade.
FADE_FREE_PCT = DEFAULT_SIGNIFICANCE_THRESHOLD_PCT
FADE_ZERO_PCT = 20.0
# Coach judgment: reps in band at or above this share of completed reps is a
# "match" for `WorkoutQuality.intensity_match`.
INTENSITY_MATCH_MIN_IN_BAND_PCT = 70.0

# Coach judgment: race weights. Pacing evenness and late fade are the two
# reads a coach leans on; start control and lap consistency refine them.
RACE_WEIGHTS: dict[str, float] = {
    "pacing_evenness": 0.35,
    "late_fade": 0.30,
    "start_control": 0.15,
    "lap_consistency": 0.20,
}
# Coach judgment: spread of NP across the post-start phases scores 100 within
# the variation floor, 0 at a 25% spread.
EVENNESS_FREE_PCT = DEFAULT_SIGNIFICANCE_THRESHOLD_PCT
EVENNESS_ZERO_PCT = 25.0
# Coach judgment: NP drop from phase 1 to the last phase, same free/zero shape.
LATE_FADE_FREE_PCT = DEFAULT_SIGNIFICANCE_THRESHOLD_PCT
LATE_FADE_ZERO_PCT = 25.0
# Coach judgment: the start phase legitimately runs hot (positioning sprint);
# only NP more than 20% above phase 1 starts costing, reaching 0 at +60%.
# A start BELOW phase 1 is not penalised (a wait at the line is 0 W).
START_OVERSHOOT_FREE_PCT = 20.0
START_OVERSHOOT_ZERO_PCT = 60.0
# Coach judgment: coefficient of variation of lap NP; needs >= 3 laps.
LAP_CV_FREE_PCT = 3.0
LAP_CV_ZERO_PCT = 15.0
LAP_MIN_COUNT = 3


def _linear(value: float, free: float, zero: float) -> float:
    """100 at or below `free`, 0 at or above `zero`, linear between."""
    if value <= free:
        return 100.0
    if value >= zero:
        return 0.0
    return round(100.0 * (zero - value) / (zero - free), 1)


def _assemble(
    kind: str, weights: dict[str, float], parts: dict[str, tuple[float | None, str]]
) -> ExecutionScore:
    """Renormalize weights over the components that have a score, then sum."""
    scored = {k: v for k, v in parts.items() if v[0] is not None}
    total_w = sum(weights[k] for k in scored)
    components: list[ExecutionComponent] = []
    for name, (score, detail) in parts.items():
        eff = round(weights[name] / total_w, 3) if score is not None and total_w else 0.0
        components.append(ExecutionComponent(name=name, score=score, weight=eff, detail=detail))
    if not scored:
        return ExecutionScore(
            kind=kind, score=None, reason="no component had data to score", components=components
        )
    total = sum(weights[k] * scored[k][0] for k in scored) / total_w
    return ExecutionScore(kind=kind, score=round(total, 1), components=components)


def _unscored(kind: str, reason: str) -> ExecutionScore:
    return ExecutionScore(kind=kind, score=None, reason=reason)


def workout_execution_score(
    intervals: WorkoutIntervals | None, workout: Workout, session: Session | None
) -> ExecutionScore:
    if session is None:
        return _unscored("workout", "not scored: this workout is not matched to a planned session")
    if intervals is None:
        return _unscored("workout", "not scored: no interval analysis (bike power/HR series needed)")
    if not intervals.matched_to_prescription:
        return _unscored(
            "workout",
            "not scored: the planned session's structure could not be located in the ride, so there "
            "is no prescription to score against",
        )

    parts: dict[str, tuple[float | None, str]] = {}

    if intervals.reps_in_band_pct is not None:
        band = (
            f" {intervals.target_band_w[0]:g}-{intervals.target_band_w[1]:g} W"
            if intervals.target_band_w
            else ""
        )
        parts["intensity"] = (
            round(intervals.reps_in_band_pct, 1),
            f"{intervals.reps_in_band_pct:g}% of completed reps averaged inside the target band{band}",
        )
    else:
        parts["intensity"] = (None, "no resolvable watts band (set FTP to score intensity)")

    ratios: list[float] = []
    notes: list[str] = []
    if intervals.prescribed_count and intervals.reps_completed is not None:
        ratios.append(min(intervals.reps_completed / intervals.prescribed_count, 1.0))
        notes.append(f"{intervals.reps_completed}/{intervals.prescribed_count} reps completed")
    if session.duration_min:
        ratios.append(min(workout.duration_min / session.duration_min, 1.0))
        notes.append(f"{workout.duration_min:g}/{session.duration_min:g} min of the planned duration")
    parts["completion"] = (
        round(100.0 * statistics.fmean(ratios), 1) if ratios else None,
        "; ".join(notes) or "no prescribed reps or duration to compare",
    )

    fades = [
        f for f in (intervals.fade_across_reps_pct, intervals.fade_across_rounds_pct) if f is not None
    ]
    if fades:
        worst = max(fades)
        parts["consistency"] = (
            _linear(worst, FADE_FREE_PCT, FADE_ZERO_PCT),
            f"worst power fade {worst:g}% (across reps {intervals.fade_across_reps_pct}, "
            f"across rounds {intervals.fade_across_rounds_pct}); up to {FADE_FREE_PCT:g}% is free",
        )
    else:
        parts["consistency"] = (None, "too few reps to measure fade")

    return _assemble("workout", WORKOUT_WEIGHTS, parts)


def intensity_match(intervals: WorkoutIntervals | None) -> str:
    """"match"/"mismatch" from the analyzer's in-band share when a prescription
    was located and a band resolved; "unknown" otherwise."""
    if intervals is None or not intervals.matched_to_prescription or intervals.reps_in_band_pct is None:
        return "unknown"
    return "match" if intervals.reps_in_band_pct >= INTENSITY_MATCH_MIN_IN_BAND_PCT else "mismatch"


def race_execution_score(phases: list[RacePhase], laps: list[GpsLapMetrics]) -> ExecutionScore:
    main = [p for p in phases if p.name.startswith("phase_") and p.normalized_power_w]
    start = next((p for p in phases if p.name == "start"), None)
    if len(main) < 2:
        return _unscored(
            "race", "not scored: the ride is too short or has no power data for race phases"
        )

    parts: dict[str, tuple[float | None, str]] = {}
    nps = [p.normalized_power_w for p in main]
    spread = (max(nps) - min(nps)) / statistics.fmean(nps) * 100
    parts["pacing_evenness"] = (
        _linear(spread, EVENNESS_FREE_PCT, EVENNESS_ZERO_PCT),
        f"NP varied {spread:.1f}% across the {len(main)} post-start phases "
        f"({EVENNESS_FREE_PCT:g}% is normal variation)",
    )

    drop = (nps[0] - nps[-1]) / nps[0] * 100
    parts["late_fade"] = (
        _linear(drop, LATE_FADE_FREE_PCT, LATE_FADE_ZERO_PCT),
        f"final phase NP {-drop:+.1f}% vs phase 1 (negative = faded)",
    )

    if start is not None and start.normalized_power_w:
        over = (start.normalized_power_w - nps[0]) / nps[0] * 100
        parts["start_control"] = (
            _linear(over, START_OVERSHOOT_FREE_PCT, START_OVERSHOOT_ZERO_PCT),
            f"start-phase NP {over:+.1f}% vs phase 1 ({START_OVERSHOOT_FREE_PCT:g}% over is expected)",
        )
    else:
        parts["start_control"] = (None, "no usable start-phase power")

    lap_nps = [m.normalized_power_w for m in laps if m.normalized_power_w]
    if len(lap_nps) >= LAP_MIN_COUNT:
        cv = statistics.pstdev(lap_nps) / statistics.fmean(lap_nps) * 100
        parts["lap_consistency"] = (
            _linear(cv, LAP_CV_FREE_PCT, LAP_CV_ZERO_PCT),
            f"lap NP varied {cv:.1f}% (CV) over {len(lap_nps)} laps",
        )
    else:
        parts["lap_consistency"] = (None, f"fewer than {LAP_MIN_COUNT} detected laps")

    return _assemble("race", RACE_WEIGHTS, parts)
