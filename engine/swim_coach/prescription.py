"""Prescription-aware rep location for the interval analyzer.

The free-detection analyzer (`interval_analysis.detect_efforts`) knows nothing
about what was planned: a 3-round 40s/20s VO2 session reads as "3 x 5.6 min
efforts at ~259 W" because its set-clustering collapses each round into one
block. When the planned session's `structured` (a `WorkoutStructure`, nested
repeats allowed) is available, this module instead locates each PRESCRIBED
rep in the ride:

1. `flatten_prescription` walks the tree into an ordered timeline of
   time-based leaves, tags every `role == "interval"` leaf as a
   `PrescribedRep` (round = one iteration of the outermost repeat that holds
   intervals; rep_in_round = its position inside that round) and resolves a
   zone target to watts from FTP via `zones.bike_zone_table`.
2. `locate_from_laps` aligns the timeline to the device laps (a structured
   workout the head unit ran records one lap per step, so this is exact);
   `locate_from_series` is the fallback -- it slides the prescribed timeline
   over the power series to find the offset where the prescribed-hard windows
   are most above the prescribed-easy windows.

Pure functions, no I/O, no LLM. Constants are `Coach judgment:` -- the
prescription itself is the source of truth for what should have happened; the
tolerances below only decide when a recorded lap or window is "the same step".
See library/26-activity-stream-interval-analysis.md.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass

from swim_coach.models import WorkoutRepeat, WorkoutStructure, WorkoutTarget
from swim_coach.zones import bike_zone_table

# Coach judgment: a lap "is" a prescribed rep/short recovery when its duration
# is within max(5 s, 10%) of the step -- covers the second or two of
# lap-button/auto-lap jitter without confusing a 40 s rep with a 20 s one.
LAP_MATCH_TOLERANCE_S = 5.0
LAP_MATCH_TOLERANCE_FRAC = 0.10
# Coach judgment: warm-up / cool-down / long-rest steps are often cut short or
# extended in practice, so they only need to be within max(30 s, 25%).
LAP_LOOSE_TOLERANCE_S = 30.0
LAP_LOOSE_TOLERANCE_FRAC = 0.25
# Coach judgment: a step counts as a "short" (tightly matched) one up to 5 min.
LAP_TIGHT_MAX_STEP_S = 300.0
# Coach judgment: the series fallback searches +/-3 min of start offset.
SERIES_SHIFT_RANGE_S = 180
SERIES_SHIFT_STEP_S = 1
# Coach judgment: the series fallback only trusts a placement where the
# prescribed-hard windows average at least 15% above the prescribed-easy ones.
SERIES_MIN_CONTRAST_FRAC = 0.15
# Coach judgment: a rep whose average power is below 75% of the band's floor
# was not really attempted (a stopped / bailed rep), so it is not "completed".
REP_COMPLETED_MIN_FRAC_OF_LOW = 0.75
# Coach judgment: a target with a single power number (no band) gets +/-5%.
SINGLE_TARGET_BAND_FRAC = 0.05


@dataclass(frozen=True)
class PrescribedRep:
    index: int  # 1-based, in prescription order
    round_n: int
    rep_in_round: int
    duration_s: float
    zone: str | None
    low_w: float | None
    high_w: float | None  # None for an unbounded top zone or an unresolved band
    offset_s: float


@dataclass(frozen=True)
class PrescribedLeaf:
    role: str
    duration_s: float
    offset_s: float
    rep: PrescribedRep | None = None


@dataclass(frozen=True)
class RepWindow:
    rep: PrescribedRep
    start_s: float
    end_s: float


@dataclass(frozen=True)
class Located:
    windows: list[RepWindow]
    source: str  # "laps" | "series"
    prescribed: list[PrescribedRep]  # every prescribed rep, located or not


def resolve_step_band_w(
    target: WorkoutTarget | None, ftp_watts: float | None
) -> tuple[float | None, float | None]:
    """Resolve a bike step target to a `(low_w, high_w)` band. `power_w`
    targets are already watts; a zone target needs FTP (else `(None, None)`)."""
    if target is None:
        return None, None
    if target.basis == "power_w":
        low, high = target.low, target.high
        if low is not None and high is None:
            return low * (1 - SINGLE_TARGET_BAND_FRAC), low * (1 + SINGLE_TARGET_BAND_FRAC)
        if high is not None and low is None:
            return high * (1 - SINGLE_TARGET_BAND_FRAC), high * (1 + SINGLE_TARGET_BAND_FRAC)
        return low, high
    if target.basis == "zone" and target.zone and ftp_watts:
        entry = bike_zone_table(ftp_watts).get(target.zone)
        if entry is None:
            return None, None
        return float(entry["watts_lo"]), (
            float(entry["watts_hi"]) if entry["watts_hi"] is not None else None
        )
    return None, None


def _holds_intervals(items: list) -> bool:
    for item in items:
        if getattr(item, "kind", None) == "repeat":
            if _holds_intervals(item.steps):
                return True
        elif getattr(item, "role", None) == "interval":
            return True
    return False


def flatten_prescription(
    structure: WorkoutStructure, *, ftp_watts: float | None
) -> list[PrescribedLeaf]:
    """Ordered timeline of every time-based leaf. Returns `[]` when the tree
    has no interval leaf or any leaf is not time-based (distance/reps/open
    steps have no timeline this module can align)."""
    if not _holds_intervals(structure.items):
        return []
    leaves: list[PrescribedLeaf] = []
    state = {"offset": 0.0, "round": 0, "rep": 0, "index": 0, "ok": True}

    def emit(step, round_n: int) -> None:
        if step.duration_kind != "time_s" or not step.duration_value:
            state["ok"] = False
            return
        dur = float(step.duration_value)
        rep = None
        if step.role == "interval":
            low, high = resolve_step_band_w(step.target, ftp_watts)
            state["index"] += 1
            state["rep"] += 1
            zone = step.target.zone if step.target is not None else None
            rep = PrescribedRep(
                index=state["index"], round_n=round_n, rep_in_round=state["rep"],
                duration_s=dur, zone=zone, low_w=low, high_w=high, offset_s=state["offset"],
            )
        leaves.append(PrescribedLeaf(step.role, dur, state["offset"], rep))
        state["offset"] += dur

    def visit(items: list, round_n: int | None) -> None:
        for item in items:
            if isinstance(item, WorkoutRepeat) or getattr(item, "kind", None) == "repeat":
                if item.repeat_mode != "count":
                    state["ok"] = False
                    continue
                for _ in range(item.count or 1):
                    if round_n is None and _holds_intervals(item.steps):
                        state["round"] += 1
                        state["rep"] = 0
                        visit(item.steps, state["round"])
                    else:
                        visit(item.steps, round_n)
            elif item.role == "interval" and round_n is None:
                state["round"] += 1
                state["rep"] = 0
                emit(item, state["round"])
            else:
                emit(item, round_n or 0)

    visit(structure.items, None)
    return leaves if state["ok"] else []


def _lap_starts(laps: list) -> list[float]:
    starts: list[float] = []
    cursor = 0.0
    for lap in laps:
        start = lap.start_offset_s if lap.start_offset_s is not None else cursor
        starts.append(float(start))
        cursor = float(start) + float(lap.duration_s)
    return starts


def _lap_matches(leaf: PrescribedLeaf, lap_duration_s: float) -> bool:
    tight = leaf.rep is not None or leaf.duration_s <= LAP_TIGHT_MAX_STEP_S
    if tight:
        tol = max(LAP_MATCH_TOLERANCE_S, LAP_MATCH_TOLERANCE_FRAC * leaf.duration_s)
    else:
        tol = max(LAP_LOOSE_TOLERANCE_S, LAP_LOOSE_TOLERANCE_FRAC * leaf.duration_s)
    if leaf.rep is None and leaf.role in ("warmup", "cooldown"):
        tol = max(LAP_LOOSE_TOLERANCE_S, LAP_LOOSE_TOLERANCE_FRAC * leaf.duration_s)
    return abs(lap_duration_s - leaf.duration_s) <= tol


def locate_from_laps(leaves: list[PrescribedLeaf], laps: list | None) -> Located | None:
    """Align the timeline to the device laps, one lap per prescribed step. Up
    to two leading extra laps are tolerated; the ride may end early (the reps
    reached so far are returned) but any mid-timeline mismatch fails the
    alignment so the caller falls back to the series."""
    if not laps or not leaves:
        return None
    starts = _lap_starts(laps)
    for first in range(min(3, len(laps))):
        windows: list[RepWindow] = []
        j = first
        ok = True
        for leaf in leaves:
            if j >= len(laps):
                break
            if not _lap_matches(leaf, float(laps[j].duration_s)):
                ok = False
                break
            if leaf.rep is not None:
                windows.append(
                    RepWindow(leaf.rep, starts[j], starts[j] + float(laps[j].duration_s))
                )
            j += 1
        if ok and windows:
            return Located(windows, "laps", [l.rep for l in leaves if l.rep is not None])
    return None


def _window_mean(t_s: list[float], power: list, prefix: list[float], a: float, b: float) -> float | None:
    lo, hi = bisect_left(t_s, a), bisect_left(t_s, b)
    if hi - lo < max(1, int((b - a) * 0.5)):
        return None
    return (prefix[hi] - prefix[lo]) / (hi - lo)


def locate_from_series(leaves: list[PrescribedLeaf], series: dict | None) -> Located | None:
    """Slide the prescribed timeline over the power series and keep the
    offset where prescribed-hard windows most exceed prescribed-easy ones."""
    if not series or not leaves:
        return None
    t_s, power = series.get("t_s") or [], series.get("power_w") or []
    if len(t_s) < 10 or len(t_s) != len(power):
        return None
    prefix = [0.0]
    for p in power:
        prefix.append(prefix[-1] + (p or 0.0))
    reps = [leaf for leaf in leaves if leaf.rep is not None]
    first_rep, last_rep = reps[0].offset_s, reps[-1].offset_s + reps[-1].duration_s
    easy = [
        leaf for leaf in leaves
        if leaf.rep is None and leaf.offset_s >= first_rep and leaf.offset_s + leaf.duration_s <= last_rep
    ]
    best: tuple[float, int] | None = None
    for shift in range(-SERIES_SHIFT_RANGE_S, SERIES_SHIFT_RANGE_S + 1, SERIES_SHIFT_STEP_S):
        hard_means = [
            m for leaf in reps
            if (m := _window_mean(t_s, power, prefix, leaf.offset_s + shift, leaf.offset_s + leaf.duration_s + shift)) is not None
        ]
        if not hard_means:
            continue
        easy_means = [
            m for leaf in easy
            if (m := _window_mean(t_s, power, prefix, leaf.offset_s + shift, leaf.offset_s + leaf.duration_s + shift)) is not None
        ]
        hard = sum(hard_means) / len(hard_means)
        easy_mean = sum(easy_means) / len(easy_means) if easy_means else 0.0
        score = hard - easy_mean
        if best is None or score > best[0]:
            best = (score, shift)
    if best is None:
        return None
    score, shift = best
    windows = [
        RepWindow(leaf.rep, leaf.offset_s + shift, leaf.offset_s + leaf.duration_s + shift)
        for leaf in reps
        if _window_mean(t_s, power, prefix, leaf.offset_s + shift, leaf.offset_s + leaf.duration_s + shift) is not None
    ]
    if not windows:
        return None
    hard_all = [
        _window_mean(t_s, power, prefix, w.start_s, w.end_s) for w in windows
    ]
    hard_avg = sum(hard_all) / len(hard_all)
    if easy and hard_avg > 0 and score < SERIES_MIN_CONTRAST_FRAC * hard_avg:
        return None
    return Located(windows, "series", [l.rep for l in leaves if l.rep is not None])


def locate_prescribed_reps(
    structure: WorkoutStructure,
    *,
    series: dict | None,
    laps: list | None,
    ftp_watts: float | None,
) -> Located | None:
    """Laps first, series fallback; `None` when the prescription has no
    alignable interval reps or neither source places them."""
    leaves = flatten_prescription(structure, ftp_watts=ftp_watts)
    if not any(leaf.rep is not None for leaf in leaves):
        return None
    return locate_from_laps(leaves, laps) or locate_from_series(leaves, series)


def window_indices(t_s: list[float], start_s: float, end_s: float) -> tuple[int, int] | None:
    """Inclusive `(start_idx, end_idx)` of the samples in `[start_s, end_s)`."""
    lo, hi = bisect_left(t_s, start_s), bisect_left(t_s, end_s)
    if hi <= lo:
        return None
    return lo, hi - 1
