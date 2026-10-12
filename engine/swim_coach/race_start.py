"""Race-start read for a bike race -- pure, no I/O.

Finds the first major burst of the race (the start), reports its peak and best
5/15/30 s, how long it lasted and how long the athlete took to settle to race
pace, and compares the opening five minutes to the whole race. Constants are
`Coach judgment:` (no source pins the numbers); see
`library/38-race-week-sharpener-and-openers.md` ("Race start").
"""

from __future__ import annotations

import statistics

from swim_coach.analytics import normalized_power_w
from swim_coach.models import RaceStart
from swim_coach.power_curve import _riding_timeline

RACE_BURST_MIN_FRAC_FTP = 1.5
# The race start is the first sample at/above this multiple of FTP (same 1.5 x FTP floor
# as the training-start burst search) that is followed by racing, not an opener. Coach
# judgment. Test: on the real 9/19 cyclocross race it lands at 253 s, not at the 0 W staging.

RACE_FOLLOW_WINDOW_S = 300
RACE_FOLLOW_MIN_FRAC_FTP = 0.6
# "Followed by racing": the 5 min after the candidate burst average at least 0.6 x FTP.
# A warm-up opener is followed by easy spinning and fails this. Coach judgment.
# Test: a 600 W blip followed by 5 min at 100 W is skipped.

RACE_BURST_SEARCH_S = 20
# The burst's peak is the highest sample within this many seconds of its first sample.
# Coach judgment.

RACE_BURST_EDGE_FRAC = 0.4
RACE_BURST_MAX_GAP_S = 2
# Burst length uses the same edge rule as the training-start burst (power >= 40% of the
# peak, <= 2 s dropouts). Coach judgment (library/38).

RACE_SETTLE_WINDOW_S = 30
RACE_SETTLE_BAND_FRAC = 0.10
# Time to settle: seconds from the burst start until the trailing 30 s mean power is within
# +-10% of the average of the following 5 min of racing. Coach judgment.
# Test: a flat 250 W race after an 800 W 10 s burst settles within ~40 s.


def _best_mean(w: list[float], n: int) -> int | None:
    if len(w) < n or n <= 0:
        return None
    cum = [0.0]
    for x in w:
        cum.append(cum[-1] + x)
    return int(round(max(cum[i + n] - cum[i] for i in range(len(w) - n + 1)) / n))


def _first_race_burst(w: list[float], ftp_watts: float) -> int | None:
    floor = RACE_BURST_MIN_FRAC_FTP * ftp_watts
    for i, x in enumerate(w):
        if x < floor:
            continue
        after = w[i : i + RACE_FOLLOW_WINDOW_S]
        if len(after) >= RACE_FOLLOW_WINDOW_S // 2 and statistics.fmean(after) >= RACE_FOLLOW_MIN_FRAC_FTP * ftp_watts:
            return i
    return None


def _burst_end(w: list[float], i0: int, ip: int) -> int:
    edge = RACE_BURST_EDGE_FRAC * w[ip]
    b, gap = ip, 0
    for i in range(ip + 1, len(w)):
        if w[i] >= edge:
            b, gap = i, 0
        else:
            gap += 1
            if gap > RACE_BURST_MAX_GAP_S:
                break
    return b


def analyze_race_start(series: dict | None, *, ftp_watts: float | None) -> RaceStart | None:
    """The race-start block, or `None` without a power channel / FTP or without a
    qualifying burst."""
    if not series or not ftp_watts:
        return None
    t_s = series.get("t_s") or []
    power = series.get("power_w") or []
    if not t_s or not power or all(p is None for p in power):
        return None
    w, clock = _riding_timeline(t_s, power)
    i0 = _first_race_burst(w, ftp_watts)
    if i0 is None:
        return None
    ip = max(range(i0, min(len(w), i0 + RACE_BURST_SEARCH_S + 1)), key=lambda k: w[k])
    end = _burst_end(w, i0, ip)
    rest = w[i0:]
    ref_win = w[end + 1 : end + 1 + RACE_FOLLOW_WINDOW_S]
    ref = statistics.fmean(ref_win) if len(ref_win) >= RACE_FOLLOW_WINDOW_S // 2 else None

    settle = None
    if ref:
        win = RACE_SETTLE_WINDOW_S
        for k in range(i0 + win, min(len(w), end + 1 + RACE_FOLLOW_WINDOW_S) + 1):
            m = statistics.fmean(w[k - win : k])
            if abs(m - ref) <= RACE_SETTLE_BAND_FRAC * ref:
                settle = float(k - i0)
                break

    first5 = w[i0 : i0 + RACE_FOLLOW_WINDOW_S]
    clock5 = clock[i0 : i0 + RACE_FOLLOW_WINDOW_S]
    np5 = normalized_power_w({"t_s": clock5, "power_w": first5}) if len(first5) >= 2 else None
    np_race = normalized_power_w({"t_s": clock[i0:], "power_w": rest}) if len(rest) >= 2 else None
    pct = round(np5 / np_race * 100, 1) if np5 and np_race else None
    peak = int(round(w[ip]))
    b5 = _best_mean(rest[:90], 5) or peak
    note = f"race start at {clock[i0]:.0f} s: peak {peak} W, best 5 s {b5} W, burst {clock[end] - clock[i0] + 1:.0f} s"
    note += f", settled to race pace in {settle:.0f} s" if settle is not None else ", no clear settle to race pace"
    if pct is not None:
        note += f"; first 5 min NP {np5:.0f} W = {pct:.0f}% of race NP {np_race:.0f} W"
    return RaceStart(
        start_s=round(clock[i0], 1),
        peak_w=peak,
        best_5s_w=b5,
        best_15s_w=_best_mean(rest[:90], 15),
        best_30s_w=_best_mean(rest[:90], 30),
        burst_s=round(clock[end] - clock[i0] + 1.0, 1),
        time_to_settle_s=settle,
        first_5min_avg_w=int(round(statistics.fmean(first5))) if first5 else None,
        first_5min_np_w=int(round(np5)) if np5 else None,
        race_np_w=int(round(np_race)) if np_race else None,
        first_5min_vs_race_np_pct=pct,
        note=note,
    )
