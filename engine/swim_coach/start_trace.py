"""Per-start 1 Hz trace and phase read: launch, shift dips, sustain, stop vs the planned end,
restart. Pure functions over the power stream; `interval_analysis` attaches the result to each
`StartBurst`. Every constant is Coach judgment (library/38-race-week-sharpener-and-openers.md,
"Reading a start trace"), each with a Test: line."""

from __future__ import annotations

from dataclasses import dataclass, field

from swim_coach.models import StartDip, StartRestart

TRACE_PRE_S = 3
TRACE_POST_S = 3
TRACE_MAX_SAMPLES = 45
# Trace window: 3 s before the burst to 3 s after the effort (or its intended end) finishes,
# capped at 45 samples so a stored start stays small. Coach judgment (library/38).
# Test: the real 10/10 starts (30 s steps) fit in 36 samples and include the restart.

LAUNCH_RISE_FRAC_FTP = 0.5
# The launch starts at the last sample at/below this fraction of FTP before power first reaches
# 1.0x FTP (a standing start from rest), and runs to the peak. Coach judgment (library/38).
# Test: real 10/10 start 4 reads ~5 s (athlete's read of the graph: ~6 s).

DIP_MIN_DROP_FRAC_PEAK = 0.2
DIP_MAX_DROP_S = 2
DIP_FLOOR_FRAC_PEAK = 0.4
DIP_RECOVER_W = 100
DIP_RECOVER_S = 3
# A "likely shift/bobble": power falls >= 20% of the start's peak within 2 s, stays above 40% of
# the peak (below that it is a brake or a stop, not a shift) and recovers >= 100 W within 3 s.
# Coach judgment (library/38). Test: real 10/10 start 4 dips 1100 -> 721 W and recovers to 925 W.

SUSTAIN_FRAC_FTP = 2.0
# Seconds at/above 2x FTP count as "sustained" -- an all-out 30 s start should hold well above
# that for most of its length. Coach judgment (library/38). Test: real 10/10 starts read 13-26 s.

STOP_FRAC_FTP = 1.0
STOP_MIN_S = 2
# The effort has stopped when power falls below 1.0x FTP and stays there >= 2 s. Coach judgment
# (library/38). Test: real 10/10 start 4 stops at ~21 s of a 30 s step.

STOPPED_EARLY_MIN_S = 2.0
# Only call it "stopped early" when the stop is at least this many seconds before the intended
# end (single-second timing noise is not a verdict). Coach judgment (library/38).

RESTART_WEAK_FRAC_PEAK = 0.6
# A restart whose peak is under 60% of the start's peak reads as "weak". Coach judgment
# (library/38). Test: real 10/10 start 4 restarts at ~550 W after a 1100 W launch.


@dataclass(frozen=True)
class StartTrace:
    trace_w: list[int]
    trace_cadence: list[int | None] | None
    trace_t0: int
    launch_s: float | None
    launch_rate_w_per_s: float | None
    dips: list[StartDip] = field(default_factory=list)
    sustained_s: float | None = None
    sustain_floor_w: int | None = None
    stopped_at_s: float | None = None
    stopped_early_s: float | None = None
    restart: StartRestart | None = None
    peak_w: int = 0
    start_w: int = 0


def _grid(t_s: list[float], values: list, first: int, n: int) -> list[float | None]:
    """`values` on the whole-second grid first..first+n-1 (None where the stream has no sample)."""
    by_sec: dict[int, float | None] = {}
    for t, v in zip(t_s, values):
        by_sec.setdefault(int(round(t)), None if v is None else float(v))
    return [by_sec.get(first + i) for i in range(n)]


def _find_stop(tr: list[float], ftp: float, begin: int) -> int | None:
    """First index >= `begin` where power is below the stop floor and stays there for
    `STOP_MIN_S` samples (a trace that ends right after counts as staying)."""
    floor = STOP_FRAC_FTP * ftp
    for i in range(begin, len(tr)):
        if tr[i] < floor and all(x < floor for x in tr[i + 1 : i + STOP_MIN_S]):
            return i
    return None


def _find_dips(tr: list[float], t0: int, end: int, peak: float) -> list[StartDip]:
    out: list[StartDip] = []
    for i in range(t0 + 1, end):
        prior = max(tr[max(t0, i - DIP_MAX_DROP_S) : i], default=0.0)
        low = tr[i]
        if prior - low < DIP_MIN_DROP_FRAC_PEAK * peak or low < DIP_FLOOR_FRAC_PEAK * peak:
            continue
        if low > tr[i - 1] or (i + 1 < len(tr) and low > tr[i + 1]):
            continue  # not a local minimum
        rec = max(tr[i + 1 : i + 1 + DIP_RECOVER_S], default=0.0)
        if rec - low >= DIP_RECOVER_W:
            out.append(StartDip(at_s=float(i - t0), from_w=int(round(prior)), to_w=int(round(low)),
                                recovered_to_w=int(round(rec))))
    return out


def _find_restart(tr: list[float], stop: int, ftp: float) -> StartRestart | None:
    floor = STOP_FRAC_FTP * ftp
    j = next((i for i in range(stop, len(tr)) if tr[i] >= floor), None)
    if j is None:
        return None
    k = j
    while k + 1 < len(tr) and tr[k + 1] >= floor:
        k += 1
    run = tr[j : k + 1]
    return StartRestart(
        after_gap_s=float(j - stop), duration_s=float(len(run)),
        avg_w=int(round(sum(run) / len(run))), peak_w=int(round(max(run))),
    )


def read_start_trace(
    series: dict,
    *,
    burst_start_s: float,
    first_end_s: float,
    last_start_s: float,
    effort_end_s: float,
    intended_s: float,
    ftp_watts: float | None,
) -> StartTrace | None:
    """Trace and phase read of one start. `first_end_s` ends burst 1 (the launch is read
    inside it), `last_start_s` begins the last burst (the stop is searched from there, so a
    prescribed brake between two bursts is not a stop), `effort_end_s` ends the last burst."""
    t_s = series.get("t_s") or []
    power = series.get("power_w") or []
    if not t_s or not power:
        return None
    first = int(round(burst_start_s)) - TRACE_PRE_S
    last = max(int(round(effort_end_s)), int(round(burst_start_s + intended_s))) + TRACE_POST_S
    n = min(last - first + 1, TRACE_MAX_SAMPLES)
    grid = _grid(t_s, power, first, n)
    if not any(x for x in grid):
        return None
    tr = [x or 0.0 for x in grid]
    cad_raw = series.get("cadence_rpm") or []
    cadence: list[int | None] | None = None
    if len(cad_raw) == len(t_s):
        cg = _grid(t_s, cad_raw, first, n)
        if any(c is not None for c in cg):
            cadence = [None if c is None else int(round(c)) for c in cg]

    lo = max(0, int(round(burst_start_s)) - first)
    hi = min(n, int(round(first_end_s)) - first + 1)
    ip = max(range(lo, max(hi, lo + 1)), key=lambda i: tr[i])
    peak = tr[ip]
    ftp = ftp_watts or 0.3 * peak
    cross = next((i for i in range(0, ip + 1) if tr[i] >= ftp), ip)
    t0 = next((i for i in range(cross - 1, -1, -1) if tr[i] <= LAUNCH_RISE_FRAC_FTP * ftp), 0)
    launch_s = float(ip - t0) if ip > t0 else None
    rate = round((peak - tr[t0]) / launch_s, 1) if launch_s else None

    s0 = max(ip + 1, int(round(last_start_s)) - first)
    stop = _find_stop(tr, ftp, s0)
    effort_to = stop if stop is not None else n
    floor = SUSTAIN_FRAC_FTP * ftp
    sustained = float(sum(1 for x in tr[t0:effort_to] if x >= floor))
    stopped_at = float(stop - t0) if stop is not None else None
    early = None
    if stopped_at is not None and intended_s - stopped_at >= STOPPED_EARLY_MIN_S:
        early = round(intended_s - stopped_at, 1)
    return StartTrace(
        trace_w=[int(round(x)) for x in tr],
        trace_cadence=cadence,
        trace_t0=t0,
        launch_s=launch_s,
        launch_rate_w_per_s=rate,
        dips=_find_dips(tr, t0, effort_to, peak),
        sustained_s=sustained,
        sustain_floor_w=int(round(floor)),
        stopped_at_s=stopped_at,
        stopped_early_s=early,
        restart=_find_restart(tr, stop, ftp) if stop is not None else None,
        peak_w=int(round(peak)),
        start_w=int(round(tr[t0])),
    )


def trace_clauses(tr: StartTrace | None, *, intended_s: float) -> str:
    """Coach-style phrases for the verdict (joined with '; '), '' when there is no trace."""
    if tr is None:
        return ""
    parts: list[str] = []
    if tr.launch_s:
        parts.append(f"launch {tr.start_w}->{tr.peak_w} W in {tr.launch_s:.0f} s")
    for d in tr.dips:
        parts.append(f"dip to {d.to_w} W at {d.at_s:.0f} s (likely shift/bobble)")
    if tr.sustained_s is not None and tr.sustain_floor_w:
        parts.append(f"sustained >={tr.sustain_floor_w} W for {tr.sustained_s:.0f} s")
    if tr.stopped_early_s is not None and tr.stopped_at_s is not None:
        parts.append(
            f"stopped at {tr.stopped_at_s:.0f} s, {tr.stopped_early_s:.0f} s before the "
            f"{intended_s:.0f} s mark"
        )
    r = tr.restart
    if r is not None:
        weak = "weak " if r.peak_w < RESTART_WEAK_FRAC_PEAK * tr.peak_w else ""
        parts.append(
            f"{weak}restart ~{r.avg_w} W for {r.duration_s:.0f} s after a {r.after_gap_s:.0f} s gap"
        )
    return "; ".join(parts)
