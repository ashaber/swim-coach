"""Race efficiency: how the same course cost the rider lap after lap.

For a race (or an opener / unstructured ride) with 2+ comparable laps -- the SAME lap selection as
`course_sectors` (double-trigger fragments merged, same distance, same start line; laps that end
before the race start are warm-up and dropped) -- each lap gets time, average power, Normalized
Power (the shared full-window NP, `analytics.normalized_power_w`), average HR, the efficiency
factor EF = NP / avg HR (watts per bpm), speed per 100 W of NP and Garmin flow. The trend reads
first -> last lap and the per-lap slope; decoupling is the EF change from the first half of the
laps to the second half (power:HR decoupling, library/11-workout-analytics.md "Cardiac drift /
aerobic decoupling"), and the verdict is one line the coach leads the debrief with.

Constants: `DECOUPLING_FLAG_PCT` reuses `analytics.CARDIAC_DRIFT_FLAG_PCT` ([ADAPTED:
general-endurance], Confidence: low -- an engineering default, not a validated cutoff);
`FLOW_STEADY_BAND` is Coach judgment (flow is a proprietary device score, so this only picks the
word "smoother"/"rougher" in the verdict, it is never a finding on its own).
"""

from __future__ import annotations

from swim_coach.analytics import CARDIAC_DRIFT_FLAG_PCT, normalized_power_w
from swim_coach.course_sectors import MAX_LAPS, _mean, _pct, _slope, course_laps
from swim_coach.models import RaceEfficiency, RaceEfficiencyLap, RaceEfficiencyTrend, Workout
from swim_coach.mtb_dynamics import has_channel, mean_moving, mean_present, window_indices

DECOUPLING_FLAG_PCT = CARDIAC_DRIFT_FLAG_PCT  # EF this far down (or up) first half -> second half is a real change
FLOW_STEADY_BAND = 0.05  # Coach judgment: a first -> last flow change inside +-0.05 reads as "flow steady"


def _lap_row(series: dict, n: int, start: float, stop: float, distance_m: float) -> RaceEfficiencyLap:
    idx = window_indices(series["t_s"], start, stop)
    t_s, power, hr = series["t_s"], series["power_w"], series.get("hr") or []
    flow, speed = series.get("flow") or [], series.get("speed_mps") or []
    window = {"t_s": [t_s[i] for i in idx], "power_w": [power[i] for i in idx]}
    np_w = normalized_power_w(window) if len(idx) else None
    avg_hr = mean_present(hr, idx) if hr and len(idx) else None
    time_s = round(stop - start, 1)
    return RaceEfficiencyLap(
        lap=n, time_s=time_s,
        avg_power_w=mean_present(power, idx) if len(idx) else None,
        np_w=round(np_w, 1) if np_w else None,
        avg_hr=avg_hr,
        ef=round(np_w / avg_hr, 3) if np_w and avg_hr else None,
        speed_per_100w=round(distance_m / time_s / np_w * 100, 3) if np_w and time_s else None,
        avg_flow=mean_moving(flow, speed or None, idx) if flow and len(idx) else None,
    )


def _half_ef(laps: list[RaceEfficiencyLap]) -> tuple[float | None, float | None]:
    """Mean EF of the first and of the second half of the laps (an odd middle lap is in neither)."""
    h = len(laps) // 2
    return (
        _mean([lap.ef for lap in laps[:h] if lap.ef is not None]),
        _mean([lap.ef for lap in laps[len(laps) - h:] if lap.ef is not None]),
    )


def _decoupled_from(laps: list[RaceEfficiencyLap], baseline: float) -> int | None:
    """First lap from which every later lap's EF stays at least the flag threshold below `baseline`."""
    floor = baseline * (1 - DECOUPLING_FLAG_PCT / 100)
    found = None
    for lap in reversed(laps):
        if lap.ef is None or lap.ef > floor:
            break
        found = lap.lap
    return found


def _trend(laps: list[RaceEfficiencyLap]) -> RaceEfficiencyTrend:
    first, last = laps[0], laps[-1]

    def series(attr: str) -> list[float]:
        vals = [getattr(lap, attr) for lap in laps]
        return vals if all(v is not None for v in vals) else []

    ef_first, ef_second = _half_ef(laps)
    decoupling = _pct(ef_second, ef_first)
    return RaceEfficiencyTrend(
        time_change_pct=_pct(last.time_s, first.time_s),
        power_change_pct=_pct(last.np_w, first.np_w),
        hr_change_bpm=round(last.avg_hr - first.avg_hr, 1) if last.avg_hr and first.avg_hr else None,
        ef_change_pct=_pct(last.ef, first.ef),
        flow_change=round(last.avg_flow - first.avg_flow, 2) if last.avg_flow is not None and first.avg_flow is not None else None,
        time_slope_s_per_lap=_slope(series("time_s")),
        power_slope_w_per_lap=_slope(series("np_w")),
        hr_slope_bpm_per_lap=_slope(series("avg_hr")),
        ef_slope_per_lap=_slope(series("ef")) if series("ef") else None,
        decoupling_pct=decoupling,
        decoupled_from_lap=_decoupled_from(laps, ef_first) if decoupling is not None and decoupling <= -DECOUPLING_FLAG_PCT else None,
    )


def _flow_word(change: float | None) -> str | None:
    if change is None:
        return None
    if abs(change) <= FLOW_STEADY_BAND:
        return "flow steady"
    return "flow smoother" if change > 0 else "flow rougher"


def _verdict(t: RaceEfficiencyTrend) -> str:
    """One line: decoupled (EF down by the flag threshold half over half), improved (up by it), or held."""
    if t.decoupling_pct is None:
        parts = [f"time {t.time_change_pct:+.0f}%" if t.time_change_pct is not None else None,
                 f"power {t.power_change_pct:+.0f}%" if t.power_change_pct is not None else None]
        return "No HR to read efficiency: " + ", ".join(p for p in parts if p) + " first to last lap"
    ef = f"EF {t.ef_change_pct:+.0f}%" if t.ef_change_pct is not None else f"EF {t.decoupling_pct:+.0f}% (second half vs first)"
    flow = _flow_word(t.flow_change)
    if t.decoupling_pct <= -DECOUPLING_FLAG_PCT:
        head = f"Decoupled from lap {t.decoupled_from_lap}" if t.decoupled_from_lap else "Decoupled"
        parts = [ef, f"HR {t.hr_change_bpm:+.0f} bpm" if t.hr_change_bpm is not None else None,
                 f"power {t.power_change_pct:+.0f}%" if t.power_change_pct is not None else None, flow]
        return f"{head}: " + ", ".join(p for p in parts if p)
    head = "Efficiency improved" if t.decoupling_pct >= DECOUPLING_FLAG_PCT else "Efficiency held"
    parts = [f"power {t.power_change_pct:+.0f}%" if t.power_change_pct is not None else None,
             f"HR {t.hr_change_bpm:+.0f} bpm" if t.hr_change_bpm is not None else None, ef, flow]
    return f"{head}: " + ", ".join(p for p in parts if p)


def build_race_efficiency(
    workout: Workout, series: dict | None, prefer_gps: bool = False, race_start_s: float | None = None
) -> RaceEfficiency | None:
    """The lap-to-lap efficiency read, or None unless 2..MAX_LAPS comparable laps (same selection as
    `course_sectors`) end after `race_start_s` and the ride has power and distance channels. HR is
    optional: without it the laps carry power and time but no EF or decoupling."""
    if not series or not series.get("t_s") or not has_channel(series, "power_w") or not has_channel(series, "dist_m"):
        return None
    group = course_laps(workout, series, prefer_gps)
    if race_start_s is not None:
        group = [item for item in group if item[3] > race_start_s]
    if not 2 <= len(group) <= MAX_LAPS:
        return None
    laps = [_lap_row(series, n, start, stop, lap.distance_m) for n, lap, start, stop in group]
    trend = _trend(laps)
    return RaceEfficiency(laps=laps, trend=trend, verdict=_verdict(trend))
