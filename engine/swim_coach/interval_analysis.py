"""Deterministic activity-stream interval analyzer.

Answers "did I hit my intervals?" from a synced ride, spending **zero LLM
tokens** on the stream: a standard span-scan detects sustained efforts
within a ride (even mid-3-hour-ride), each effort is assessed against its
prescribed target when one is recoverable, and the athlete's real-world
terrain confounds (a threshold interval up a steepening dirt road reads
like a power fade) are flagged rather than silently mis-called.

Pure functions over the columnar series dict `parse_files._build_series`
produces (`t_s` plus `power_w`/`hr`/`grade`/... channels) -- no I/O, no
network, no LLM. `analytics.compute_analytics` is the only caller that
turns this into a persisted `models.WorkoutIntervals`.

Every named threshold below cites `library/11-workout-analytics.md`'s
"Deterministic activity-stream interval analyzer" section.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from swim_coach.models import (
    IntervalEffort,
    WorkoutIntervals,
    WorkoutStructure,
)

# --- constants (library/11-workout-analytics.md) -------------------------------------

EFFORT_MIN_S = 120.0
# Coach judgment: the shortest above-threshold span counted as a deliberate
# effort. A structured cycling interval session's work bouts are minutes,
# not seconds (Buchheit/Laursen's long-interval family -- `library/24`); a
# 30s surge on a group ride is not what "did I hit my intervals?" is
# asking about. library/11-workout-analytics.md.

EFFORT_MERGE_GAP_S = 25.0
# Coach judgment: a dip below threshold shorter than this (a corner, a
# freewheel over a crest, a rough patch mid-interval) does NOT end the
# effort -- the scan bridges it, mirroring `analytics.stationary_pauses`'s
# single-source span logic one level up. Longer than
# `analytics.GAP_THRESHOLD_S`'s 30s only by coincidence; different
# measurement. library/11-workout-analytics.md.

EFFORT_DYNAMIC_FRAC = 0.62
# Coach judgment: with no supplied target, the detection threshold sits
# this far up from the ride's own 40th-percentile working power toward its
# 85th-percentile working power -- high enough to ignore steady endurance
# riding, low enough to catch a threshold (not just VO2) interval.
# library/11-workout-analytics.md.

COASTING_FLOOR_W = 20.0
# Coach judgment: at or below this the rider is freewheeling, not pedalling
# -- excluded from "working" percentiles, from the tightened-decoupling
# calc, and it's the floor `analyze` passes as `exclude_below_w`.
# library/11-workout-analytics.md.

TARGET_GATE_FRAC = 0.80
# Coach judgment: when a target IS supplied, a sample counts as "in an
# effort" at or above 80% of it -- an athlete aiming for 239W who is
# holding 195W is still visibly *trying* to do the interval, not resting.
# library/11-workout-analytics.md.

IN_BAND_FRAC = 0.05
# [ADAPTED: cycling] Confidence: medium. Time within +/-5% of target power
# is the compliance metric the power-training literature favours for
# judging an interval (explicitly NOT normalized power, a fatigue-cost
# estimate cautioned against for this use). +/-5% is the standard
# practitioner target band (Allen/Coggan lineage). library/11-workout-
# analytics.md.

FADE_FLAG_PCT = 10.0
# [ADAPTED: cycling] Confidence: medium. First-third-vs-last-third mean
# power drop within one effort. `Barsumyan A., Soost C., Burchard R.
# (2025)` measured ~6.5% first-to-last power decline over a 20-min fatigued
# interval in successful amateur road cyclists vs ~12.5% in less successful
# ones -- so a >~10% fade is a meaningful durability/pacing signal, not
# noise. library/11-workout-analytics.md.

HR_HELD_BAND_BPM = 2.0
# Coach judgment: an HR drift between -2 and +2 bpm across an effort is
# "held" -- neither a back-off nor a climb. library/11-workout-analytics.md.

HR_BACKOFF_DROP_BPM = 5.0
# Coach judgment: HR falling more than 5 bpm across an effort, alongside a
# power fade, reads as the athlete easing off, not terrain.
# library/11-workout-analytics.md.

GRADE_DROP_FLAG = 0.03
# Coach judgment: a mid-effort mean-grade decrease of >= 3 percentage
# points (first third vs last third) is "materially more downhill" -- the
# terrain confound this analyzer exists to catch on dirt-road intervals.
# library/11-workout-analytics.md.

TIGHTENED_DECOUPLING_MIN_WORKING_FRAC = 0.5
# Coach judgment: the standard first-half-EF vs second-half-EF decoupling
# calc is documented (TrainingPeaks) as invalid on "variable, stop-start
# or all-out" rides -- so if less than half the moving time was spent
# above `COASTING_FLOOR_W`, `tightened_decoupling` returns `(None,
# reason)` rather than a misleading number. library/11-workout-
# analytics.md.

DURATION_TOLERANCE_FRAC = 0.25
# Coach judgment: a detected effort whose duration is within +/-25% of a
# prescribed rep's duration is "the same rep" for match_efforts_to_
# structure's alignment. library/11-workout-analytics.md.


# --- result types (internal; analyze() returns the pydantic WorkoutIntervals) ------


@dataclass(frozen=True)
class DetectedEffort:
    """One sustained effort located by `detect_efforts` -- index range into
    the series arrays plus its wall-clock span."""

    n: int
    start_idx: int
    end_idx: int  # inclusive
    start_s: float
    end_s: float

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


@dataclass(frozen=True)
class EffortQuality:
    """`assess_effort`'s verdict on one effort -- the raw numbers behind
    the persisted `models.IntervalEffort`."""

    avg_w: float | None
    avg_hr: int | None
    target_w: float | None
    pct_of_target: float | None
    avg_vs_target_w: float | None
    time_in_band_pct: float | None
    fade_pct: float | None
    hr_drift_bpm: float | None
    grade_delta_pct_pts: float | None
    terrain_flag: str | None
    verdict: str


@dataclass(frozen=True)
class MatchResult:
    matched: bool
    prescribed_count: int
    detected_count: int
    # per_rep[i] = (detected_index_or_None, target_w_or_None, duration_ok)
    per_rep: list[tuple[int | None, float | None, bool]]


# --- small helpers -----------------------------------------------------------------


def _mean(values: list) -> float | None:
    clean = [v for v in values if v is not None]
    return statistics.fmean(clean) if clean else None


def _percentile(sorted_vals: list[float], frac: float) -> float:
    if not sorted_vals:
        return 0.0
    if frac <= 0:
        return sorted_vals[0]
    if frac >= 1:
        return sorted_vals[-1]
    pos = frac * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def _thirds(values: list) -> tuple[list, list, list]:
    n = len(values)
    if n < 3:
        return values, [], values
    cut = n // 3
    return values[:cut], values[cut : n * 2 // 3], values[-cut:]


def _detection_channel(series: dict) -> tuple[str, list] | None:
    """`("power", series["power_w"])` when a usable power channel exists,
    else `("hr", series["hr"])`, else `None`."""
    for key, basis in (("power_w", "power"), ("hr", "hr")):
        chan = series.get(key)
        if chan and any(v is not None for v in chan):
            return basis, chan
    return None


# --- effort detection ------------------------------------------------------------------


def detect_efforts(
    series: dict,
    *,
    target_w: float | None = None,
    min_effort_s: float = EFFORT_MIN_S,
    merge_gap_s: float = EFFORT_MERGE_GAP_S,
) -> list[DetectedEffort]:
    """Scan the power stream (HR when there's no power) for sustained
    efforts above a threshold, bridging dips shorter than `merge_gap_s` and
    keeping only spans lasting at least `min_effort_s`.

    Threshold: `target_w * TARGET_GATE_FRAC` when a target is supplied;
    otherwise dynamic -- `EFFORT_DYNAMIC_FRAC` of the way from the ride's
    own 40th-percentile working value to its 85th-percentile working value.
    Deterministic, standard span-scan -- no ML, works on a whole ride
    regardless of length. See `library/11-workout-analytics.md`.
    """
    t_s = series.get("t_s")
    picked = _detection_channel(series)
    if not t_s or picked is None:
        return []
    basis, chan = picked
    n = len(t_s)

    if basis == "power" and target_w:
        threshold = target_w * TARGET_GATE_FRAC
    else:
        floor = COASTING_FLOOR_W if basis == "power" else 0.0
        working = sorted(v for v in chan if v is not None and v > floor)
        if len(working) < 10:
            return []
        lo = _percentile(working, 0.40)
        hi = _percentile(working, 0.85)
        threshold = lo + EFFORT_DYNAMIC_FRAC * (hi - lo)

    efforts: list[DetectedEffort] = []
    span_start_idx: int | None = None
    last_above_idx: int | None = None

    def _close(end_idx: int) -> None:
        nonlocal span_start_idx, last_above_idx
        if span_start_idx is not None:
            start_s, end_s = t_s[span_start_idx], t_s[end_idx]
            if end_s - start_s >= min_effort_s:
                efforts.append(
                    DetectedEffort(
                        n=len(efforts) + 1,
                        start_idx=span_start_idx,
                        end_idx=end_idx,
                        start_s=start_s,
                        end_s=end_s,
                    )
                )
        span_start_idx = None
        last_above_idx = None

    for i in range(n):
        v = chan[i]
        above = v is not None and v >= threshold
        if above:
            if span_start_idx is None:
                span_start_idx = i
            last_above_idx = i
        elif span_start_idx is not None and last_above_idx is not None:
            if t_s[i] - t_s[last_above_idx] > merge_gap_s:
                _close(last_above_idx)
    if span_start_idx is not None and last_above_idx is not None:
        _close(last_above_idx)
    # Renumber (a merge-close can leave gaps if it were ever to reject).
    return [
        DetectedEffort(n=k + 1, start_idx=e.start_idx, end_idx=e.end_idx, start_s=e.start_s, end_s=e.end_s)
        for k, e in enumerate(efforts)
    ]


# --- per-effort quality --------------------------------------------------------------


def assess_effort(
    series: dict,
    effort: DetectedEffort,
    *,
    target_w: float | None = None,
) -> EffortQuality:
    """Assess one detected effort: average power, average-vs-target (W and
    %), time-in-target-band %, within-effort power fade %, HR drift, and a
    terrain-confound flag. See `library/11-workout-analytics.md`.
    """
    a, b = effort.start_idx, effort.end_idx + 1
    power = (series.get("power_w") or [])[a:b]
    hr = (series.get("hr") or [])[a:b]
    grade = (series.get("grade") or [])[a:b]

    avg_w = _mean(power)
    avg_hr_f = _mean(hr)
    avg_hr = round(avg_hr_f) if avg_hr_f is not None else None

    pct_of_target = avg_vs_target_w = time_in_band_pct = None
    if target_w and avg_w is not None:
        pct_of_target = round(avg_w / target_w * 100, 1)
        avg_vs_target_w = round(avg_w - target_w, 1)
        lo, hi = target_w * (1 - IN_BAND_FRAC), target_w * (1 + IN_BAND_FRAC)
        clean = [p for p in power if p is not None]
        if clean:
            time_in_band_pct = round(sum(lo <= p <= hi for p in clean) / len(clean) * 100, 1)

    p1, _p2, p3 = _thirds(power)
    fade_pct = None
    m1, m3 = _mean(p1), _mean(p3)
    if m1 and m1 > 0 and m3 is not None:
        fade_pct = round((m1 - m3) / m1 * 100, 1)

    h1, _h2, h3 = _thirds(hr)
    hr_drift_bpm = None
    hm1, hm3 = _mean(h1), _mean(h3)
    if hm1 is not None and hm3 is not None:
        hr_drift_bpm = round(hm3 - hm1, 1)

    g1, _g2, g3 = _thirds(grade)
    grade_delta_pct_pts = None
    gm1, gm3 = _mean(g1), _mean(g3)
    if gm1 is not None and gm3 is not None:
        grade_delta_pct_pts = round((gm1 - gm3) * 100, 1)

    terrain_flag = _terrain_flag(fade_pct, hr_drift_bpm, grade_delta_pct_pts)
    verdict = _verdict(pct_of_target, time_in_band_pct, fade_pct, terrain_flag, avg_w, target_w)

    return EffortQuality(
        avg_w=round(avg_w, 1) if avg_w is not None else None,
        avg_hr=avg_hr,
        target_w=target_w,
        pct_of_target=pct_of_target,
        avg_vs_target_w=avg_vs_target_w,
        time_in_band_pct=time_in_band_pct,
        fade_pct=fade_pct,
        hr_drift_bpm=hr_drift_bpm,
        grade_delta_pct_pts=grade_delta_pct_pts,
        terrain_flag=terrain_flag,
        verdict=verdict,
    )


def _terrain_flag(
    fade_pct: float | None, hr_drift_bpm: float | None, grade_delta_pct_pts: float | None
) -> str | None:
    if fade_pct is None or fade_pct <= 3.0:
        return None  # no meaningful fade to explain
    hr_held_or_rising = hr_drift_bpm is None or hr_drift_bpm >= -HR_HELD_BAND_BPM
    hr_dropped = hr_drift_bpm is not None and hr_drift_bpm <= -HR_BACKOFF_DROP_BPM
    grade_dropped = grade_delta_pct_pts is not None and grade_delta_pct_pts >= GRADE_DROP_FLAG * 100

    if grade_dropped and hr_held_or_rising:
        return (
            "power fade tracks a downhill grade change "
            f"(~{grade_delta_pct_pts:.0f} pts less climb) while HR held -- "
            "likely terrain, not easing off"
        )
    if hr_dropped:
        return "power and HR both dropped -- backed off"
    if fade_pct >= FADE_FLAG_PCT and hr_held_or_rising:
        return (
            f"power faded {fade_pct:.0f}% with HR held -- genuine fade "
            "(fatigue/durability), not terrain"
        )
    return None


def _verdict(
    pct_of_target: float | None,
    time_in_band_pct: float | None,
    fade_pct: float | None,
    terrain_flag: str | None,
    avg_w: float | None,
    target_w: float | None,
) -> str:
    if target_w and pct_of_target is not None:
        if 97 <= pct_of_target <= 103 and (time_in_band_pct or 0) >= 50:
            head = "on target"
        elif pct_of_target < 92:
            head = f"under target ({pct_of_target:.0f}%)"
        elif pct_of_target > 108:
            head = f"over target ({pct_of_target:.0f}%)"
        else:
            head = f"near target ({pct_of_target:.0f}%)"
    elif avg_w is not None:
        head = f"~{avg_w:.0f}W (no target supplied)"
    else:
        head = "HR-only effort (no power)"

    if terrain_flag:
        return f"{head}; {terrain_flag}"
    if fade_pct is not None and fade_pct >= FADE_FLAG_PCT:
        return f"{head}; faded {fade_pct:.0f}% end-to-end"
    if fade_pct is not None and fade_pct <= -FADE_FLAG_PCT:
        return f"{head}; built through it (+{-fade_pct:.0f}%)"
    return head


# --- match to prescription ---------------------------------------------------------


def _prescribed_reps(structure: WorkoutStructure) -> list[tuple[float | None, float | None]]:
    """Flatten a `WorkoutStructure` to `(duration_s, target_w)` for every
    time-based `role == "interval"` leaf, expanding `WorkoutRepeat` counts.
    `target_w` is read from a `basis == "power_w"` target's `low` (or the
    low/high midpoint); otherwise `None`."""
    out: list[tuple[float | None, float | None]] = []

    def visit(items: list) -> None:
        for item in items:
            if getattr(item, "kind", None) == "repeat":
                count = item.count or 1
                for _ in range(count):
                    visit(item.steps)
            elif getattr(item, "role", None) == "interval":
                dur = item.duration_value if item.duration_kind == "time_s" else None
                tw = None
                tgt = getattr(item, "target", None)
                if tgt is not None and tgt.basis == "power_w":
                    if tgt.low is not None and tgt.high is not None:
                        tw = (tgt.low + tgt.high) / 2
                    else:
                        tw = tgt.low if tgt.low is not None else tgt.high
                out.append((dur, tw))

    visit(structure.items)
    return out


def match_efforts_to_structure(
    detected: list[DetectedEffort], structure: WorkoutStructure | None
) -> MatchResult:
    """Align detected efforts to a prescribed structure's interval reps, in
    order. When `structure` is `None` or carries no interval reps, returns
    `matched=False` and the caller reports the detected efforts raw with a
    caller-supplied target. See `library/11-workout-analytics.md`.
    """
    reps = _prescribed_reps(structure) if structure is not None else []
    if not reps:
        return MatchResult(matched=False, prescribed_count=0, detected_count=len(detected), per_rep=[])

    per_rep: list[tuple[int | None, float | None, bool]] = []
    for i, (dur, tw) in enumerate(reps):
        if i < len(detected):
            det = detected[i]
            dur_ok = (
                dur is None
                or dur <= 0
                or abs(det.duration_s - dur) <= dur * DURATION_TOLERANCE_FRAC
            )
            per_rep.append((det.n, tw, bool(dur_ok)))
        else:
            per_rep.append((None, tw, False))

    matched = len(detected) == len(reps) and all(ok for _, _, ok in per_rep)
    return MatchResult(
        matched=matched,
        prescribed_count=len(reps),
        detected_count=len(detected),
        per_rep=per_rep,
    )


# --- tightened decoupling ----------------------------------------------------------


def tightened_decoupling(
    series: dict, *, exclude_below_w: float = COASTING_FLOOR_W
) -> tuple[float | None, str]:
    """The standard first-half-EF vs second-half-EF aerobic-decoupling
    formula (as `analytics.cardiac_drift` uses), but filtered to genuinely
    *working* samples: power above `exclude_below_w` (speed > 0.5 m/s when
    there's no power). Returns `(None, reason)` when the ride is too
    stop-start for the number to mean anything (less than
    `TIGHTENED_DECOUPLING_MIN_WORKING_FRAC` of moving time was working).
    SUPPLEMENTS `WorkoutAnalytics.cardiac_drift_pct`; never replaces it.
    See `library/11-workout-analytics.md`.
    """
    t_s = series.get("t_s")
    hr = series.get("hr")
    if not t_s or not hr or not any(v is not None for v in hr):
        return None, "no HR data -- decoupling needs heart rate"

    power = series.get("power_w")
    speed = series.get("speed_mps")
    use_power = bool(power) and any(v is not None for v in power)
    effort_chan = power if use_power else speed
    if not effort_chan or not any(v is not None for v in effort_chan):
        return None, "no power or speed channel -- can't isolate working effort"
    floor = exclude_below_w if use_power else 0.5

    moving = [
        (t, h, e)
        for t, h, e in zip(t_s, hr, effort_chan)
        if h is not None and e is not None and e > 0
    ]
    working = [(t, h, e) for t, h, e in moving if e > floor]
    if len(moving) < 8 or not working:
        return None, "not enough moving samples for a decoupling read"

    frac = len(working) / len(moving)
    if frac < TIGHTENED_DECOUPLING_MIN_WORKING_FRAC:
        return None, (
            f"ride too stop-start for a valid decoupling read -- only {frac * 100:.0f}% "
            "of moving time was above the coasting floor"
        )

    mid_t = (working[0][0] + working[-1][0]) / 2
    first = [(h, e) for t, h, e in working if t < mid_t]
    second = [(h, e) for t, h, e in working if t >= mid_t]
    if len(first) < 3 or len(second) < 3:
        return None, "working samples too lopsided in time for a first-half/second-half split"

    def hr_per_effort(pairs: list[tuple[float, float]]) -> float:
        return statistics.fmean(h for h, _ in pairs) / statistics.fmean(e for _, e in pairs)

    r1, r2 = hr_per_effort(first), hr_per_effort(second)
    if r1 == 0:
        return None, "degenerate first-half efficiency (zero)"
    pct = round((r2 / r1 - 1) * 100, 1)
    return pct, (
        f"measured on the {frac * 100:.0f}% of moving time spent working "
        f"(above {floor:g}{'W' if use_power else ' m/s'})"
    )


# --- public entry point ----------------------------------------------------------


def analyze(
    series: dict | None,
    *,
    sport: str | None,
    target_w: float | None = None,
    structure: WorkoutStructure | None = None,
) -> WorkoutIntervals | None:
    """Full deterministic interval analysis for one ride. Returns a
    `models.WorkoutIntervals` for `sport == "bike"` rides that carry a
    usable power or HR series; `None` for every other sport / series-less
    workout (that's what keeps swim/kayak `analytics.intervals` `None`).

    `target_w` is the caller-supplied per-interval power target (e.g. the
    coach passing "2x12 at 91% of 263W"). `structure`, when a
    `WorkoutStructure` is recoverable for the session, aligns detected
    efforts to prescribed reps and takes each rep's own `power_w` target.
    """
    if sport != "bike" or not series:
        return None
    picked = _detection_channel(series)
    if picked is None:
        return None
    basis = picked[0]

    reps = _prescribed_reps(structure) if structure is not None else []
    efforts = detect_efforts(series, target_w=target_w)
    match = match_efforts_to_structure(efforts, structure)

    out_efforts: list[IntervalEffort] = []
    for e in efforts:
        rep_target = None
        if reps and e.n - 1 < len(reps):
            rep_target = reps[e.n - 1][1]
        eff_target = rep_target if rep_target is not None else target_w
        q = assess_effort(series, e, target_w=eff_target)
        out_efforts.append(
            IntervalEffort(
                n=e.n,
                start_s=round(e.start_s, 1),
                duration_s=round(e.duration_s, 1),
                avg_w=q.avg_w,
                avg_hr=q.avg_hr,
                target_w=round(eff_target, 1) if eff_target is not None else None,
                pct_of_target=q.pct_of_target,
                avg_vs_target_w=q.avg_vs_target_w,
                time_in_band_pct=q.time_in_band_pct,
                fade_pct=q.fade_pct,
                hr_drift_bpm=q.hr_drift_bpm,
                grade_delta_pct_pts=q.grade_delta_pct_pts,
                terrain_flag=q.terrain_flag,
                verdict=q.verdict,
            )
        )

    decoupling_pct, decoupling_note = tightened_decoupling(series)

    return WorkoutIntervals(
        efforts_detected=len(efforts),
        detection_basis=basis,
        matched_to_prescription=match.matched,
        prescribed_count=match.prescribed_count or (len(reps) or None),
        efforts=out_efforts,
        decoupling_tightened_pct=decoupling_pct,
        decoupling_note=decoupling_note,
    )
