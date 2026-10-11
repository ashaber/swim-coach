"""Session-shape reads for the bike interval analyzer -- pure, no I/O.

Two things the prescription-aware path (`prescription.py`) cannot do alone:

* `technical_read`: on a tight technical course (barrier, remount, corner
  sequence) continuous power is impossible, so a rep's average power is not a
  fair read of effort. Such reps are scored on HR (avg HR, % of LTHR, time at
  >= 90% LTHR) next to average power and NP, never as "under target" / "faded".
* `infer_lap_shape`: with no plan, a repeating work/recovery pattern in the device
  laps is treated as the prescription (open targets), so starts and work reps are
  scored like a planned session.

Every constant is `Coach judgment:` (no source pins the numbers) with a `Test:`
line; see `library/26-activity-stream-interval-analysis.md`
("Technical-course reps", "Lap-shape detection").
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass

from swim_coach.analytics import normalized_power_w
from swim_coach.prescription import Located, PrescribedRep, RepWindow, window_indices

TECH_MIN_REP_S = 120.0
# Only a work rep at least this long is considered for the technical (HR-scored) read; a
# shorter rep is a burst/start and is scored as one. Coach judgment.
# Test: a 3 min race-pace rep on the real 10/10 tight course is read; 30 s starts are not.

TECH_LOW_POWER_FRAC_FTP = 0.5
TECH_LOW_POWER_TIME_PCT = 20.0
# Variability measure: the share of the rep's time spent under 50% of FTP (braking for
# corners, the run-up, the remount, coasting). A rep with >= 20% of its time that low is
# "technical": power there reflects the course, not the effort. Coach judgment (library/26).
# Test: on the real 10/10 reps 2-5 (27-37%) and 9/26 reps (40-44%) it fires; on a smooth
# 3 min rep at 280 W (1%), the 10/06 over/under work blocks (1-9%) it does not.

TECH_LABEL_ASSISTED_TIME_PCT = 10.0
# When the plan text (session purpose/structure) names technical terrain but the step
# label does not, the rep must still show half the variability threshold: a rep ridden on
# a paved path before the course (10/10 rep 1: 1%) stays power-scored. Coach judgment.
# Test: 10/10 rep 1 stays power-scored; reps 2-5 are HR-scored.

TECH_HR_HELD_PCT_LTHR = 85.0
# A technical rep's effort "held" when its average HR is at least this % of LTHR. Coach
# judgment (the real 9/26 and 10/10 reps ran 90-95%). Test: a rep at 80% LTHR reads "HR
# only 80% of LTHR".
TECH_HR_HARD_PCT_LTHR = 90.0
# "Time at >= 90% LTHR" counts seconds at/above this share of LTHR. Coach judgment.

STREAM_MIN_COVERAGE = 0.8
# A rep window with fewer than this share of its seconds in the stream (a recording gap or
# timer pause inside the lap) is reported from the lap summary, not scored. Coach judgment.
# Test: the real 9/26 rep 1 (58 s of 300 s recorded) reads "partial stream".

_TECH_RE = re.compile(r"technical|barrier|remount|dismount|run-?up|corner|tight|twisty", re.I)


def mentions_technical(text: str | None) -> bool:
    return bool(text and _TECH_RE.search(text))


@dataclass(frozen=True)
class RepRead:
    """HR/power numbers for one rep window."""

    coverage: float
    avg_w: float | None
    np_w: float | None
    avg_hr: int | None
    pct_lthr: float | None
    time_ge90_lthr_s: float | None
    low_power_time_pct: float | None


def read_rep(
    series: dict, start_s: float, end_s: float, *, ftp_watts: float | None, lthr_bpm: float | None
) -> RepRead | None:
    t_s = series.get("t_s") or []
    idx = window_indices(t_s, start_s, end_s)
    if idx is None:
        return None
    a, b = idx[0], idx[1] + 1
    power = (series.get("power_w") or [])[a:b]
    hr = (series.get("hr") or [])[a:b]
    span = max(1.0, end_s - start_s)
    coverage = min(1.0, len(t_s[a:b]) / span)
    watts = [float(p) if p is not None else 0.0 for p in power]
    avg_w = statistics.fmean(watts) if watts else None
    low_pct = None
    if ftp_watts and watts:
        low_pct = round(sum(w < TECH_LOW_POWER_FRAC_FTP * ftp_watts for w in watts) / len(watts) * 100, 1)
    np_w = None
    if len(watts) >= 2:
        np_w = normalized_power_w({"t_s": t_s[a:b], "power_w": watts})
    hrs = [float(h) for h in hr if h is not None]
    avg_hr = round(statistics.fmean(hrs)) if hrs else None
    pct_lthr = round(avg_hr / lthr_bpm * 100, 1) if avg_hr is not None and lthr_bpm else None
    t90 = None
    if lthr_bpm and hrs:
        t90 = float(sum(h >= TECH_HR_HARD_PCT_LTHR / 100 * lthr_bpm for h in hrs))
    return RepRead(
        coverage=coverage,
        avg_w=round(avg_w, 1) if avg_w is not None else None,
        np_w=round(np_w, 1) if np_w is not None else None,
        avg_hr=avg_hr,
        pct_lthr=pct_lthr,
        time_ge90_lthr_s=t90,
        low_power_time_pct=low_pct,
    )


def is_technical(read: RepRead, *, label_says: bool, plan_text_says: bool) -> str | None:
    """`"label"` (the step label names technical terrain), `"variability"` (power
    variability alone, or plan text plus half of it), else `None`."""
    low = read.low_power_time_pct
    if label_says:
        return "label"
    if low is None:
        return None
    if low >= TECH_LOW_POWER_TIME_PCT:
        return "variability"
    if plan_text_says and low >= TECH_LABEL_ASSISTED_TIME_PCT:
        return "variability"
    return None


def technical_verdict(read: RepRead) -> str:
    parts = []
    if read.avg_w is not None:
        np_txt = f" / NP {read.np_w:.0f} W" if read.np_w is not None else ""
        parts.append(f"avg {read.avg_w:.0f} W{np_txt}")
    if read.avg_hr is None:
        return "technical rep: " + ", ".join(parts) + " (no HR channel -- effort cannot be read from power on this course)"
    if read.pct_lthr is None:
        return "technical rep: " + ", ".join(parts) + f", HR {read.avg_hr} (no LTHR set for a %LTHR read)"
    hr_txt = f"HR {read.avg_hr} ({read.pct_lthr:.0f}% LTHR)"
    if read.time_ge90_lthr_s is not None:
        hr_txt += f", {read.time_ge90_lthr_s:.0f} s at >=90% LTHR"
    held = (
        "effort held"
        if read.pct_lthr >= TECH_HR_HELD_PCT_LTHR
        else f"HR only {read.pct_lthr:.0f}% of LTHR -- effort not clearly held"
    )
    return f"technical rep: {', '.join(parts)}, {hr_txt} -- {held}"


# --- lap-shape detection ---------------------------------------------------------------

SHAPE_MIN_REPEATS = 3
# A repeating work/recovery lap pattern needs at least this many repeats. Coach judgment.
# Test: the 9/26 ride's two 5 s/55 s pairs are not a pattern; its 4 x 30 s/240 s and
# 4 x 300 s/180 s are.

SHAPE_DURATION_TOL_S = 5.0
SHAPE_DURATION_TOL_FRAC = 0.15
# Lap durations of a repeat must match the first repeat's within max(5 s, 15%) (lap
# presses are by hand). Coach judgment. Test: 9/26 starts (30 s +-1) group; 300/180 group.

SHAPE_WORK_VS_REST_POWER = 1.25
# A work lap >= 60 s must average this much above its recovery lap. Coach judgment.
# Test: 9/26 work laps (186-226 W) vs recoveries (43-74 W) pass.

SHAPE_MIN_PAIR_SHARE = 0.75
# At least this share of a candidate pattern's repeats must pass the work-vs-rest test
# (a start rep whose lap press drifted off the burst may fail). Coach judgment.

SHAPE_SHORT_WORK_S = 60.0
# A work lap shorter than this is a burst; it passes when the stream shows a peak >= the
# caller's burst floor (1.5 x FTP) within `SHAPE_BURST_LOOKAROUND_S` of the lap. Coach judgment.
SHAPE_BURST_LOOKBEFORE_S = 30.0
SHAPE_BURST_LOOKAFTER_S = 60.0
# Same look-around as the starts search (laps are pressed by hand).

SHAPE_MIN_WORK_LAP_S = 10.0
# Work laps shorter than this (5 s openers) are never the work half of a pattern. Coach
# judgment. Test: the 9/26 5 s builds are not counted as starts.


def _tol(first_s: float) -> float:
    return max(SHAPE_DURATION_TOL_S, SHAPE_DURATION_TOL_FRAC * first_s)


def _lap_start(lap, cursor: float) -> float:
    return float(lap.start_offset_s) if lap.start_offset_s is not None else cursor


def _chain(durs: list[float], i: int) -> int:
    """Number of consecutive (work, recovery) lap pairs from lap `i` with durations matching
    the first pair's."""
    w0, r0 = durs[i], durs[i + 1]
    n = 0
    j = i
    while j + 1 < len(durs):
        if abs(durs[j] - w0) > _tol(w0) or abs(durs[j + 1] - r0) > _tol(r0):
            break
        n += 1
        j += 2
    return n


def infer_lap_shape(
    laps: list | None, series: dict | None, *, burst_floor_w: float | None
) -> Located | None:
    """Treat a repeating (work, recovery) lap pattern as the prescription, with open
    targets: `Located(source="lap_shape")`, or `None` when there is none."""
    if not laps or len(laps) < 2 * SHAPE_MIN_REPEATS:
        return None
    t_s = (series or {}).get("t_s") or []
    power = (series or {}).get("power_w") or []
    durs = [float(l.duration_s) for l in laps]
    starts: list[float] = []
    cursor = 0.0
    for l in laps:
        s0 = _lap_start(l, cursor)
        starts.append(s0)
        cursor = s0 + float(l.duration_s)

    def work_passes(k: int) -> bool:
        if durs[k] < SHAPE_SHORT_WORK_S:
            if not t_s or not power or burst_floor_w is None:
                return False
            lo = starts[k] - SHAPE_BURST_LOOKBEFORE_S
            hi = starts[k] + durs[k] + SHAPE_BURST_LOOKAFTER_S
            return any(
                p is not None and p >= burst_floor_w
                for tt, p in zip(t_s, power)
                if lo <= tt < hi
            )
        w, r = laps[k].avg_power_w, laps[k + 1].avg_power_w
        return w is not None and r is not None and w >= SHAPE_WORK_VS_REST_POWER * max(r, 1.0)

    groups: list[list[int]] = []  # work-lap indices per pattern
    i = 0
    while i + 1 < len(laps):
        if durs[i] < SHAPE_MIN_WORK_LAP_S:
            i += 1
            continue
        n = _chain(durs, i)
        if n >= SHAPE_MIN_REPEATS:
            works = [i + 2 * m for m in range(n)]
            ok = sum(work_passes(k) for k in works)
            if ok / n >= SHAPE_MIN_PAIR_SHARE:
                groups.append(works)
                i += 2 * n
                continue
        i += 1
    if not groups:
        return None

    prescribed: list[PrescribedRep] = []
    windows: list[RepWindow] = []
    for g, works in enumerate(groups, start=1):
        for m, k in enumerate(works, start=1):
            rep = PrescribedRep(
                index=len(prescribed) + 1,
                round_n=g,
                rep_in_round=m,
                duration_s=durs[k],
                zone=None,
                low_w=None,
                high_w=None,
                offset_s=starts[k],
                basis="open",
            )
            prescribed.append(rep)
            windows.append(RepWindow(rep, starts[k], starts[k] + durs[k]))
    return Located(windows, "lap_shape", prescribed)
