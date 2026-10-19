"""Garmin MTB dynamics (Grit / Flow / jumps) as analytics: ride totals plus per-lap splits.

Grit = ride difficulty from elevation, gradient and rapid direction changes; Flow = how
consistently speed/smoothness is held through turns (lower = smoother) -- Garmin Edge manual
definitions. The algorithms are proprietary, so these are read-only device metrics: this module
only sums and averages what the device recorded, and invents no thresholds.

Units (verified on a real 2026-10-04 MTB FIT): the per-record `grit` channel is an increment
scaled x1000 (the records sum to ~92053 for a session `total_grit` of 92.05 kGrit), so a lap's
grit is the sum of its records / `GRIT_RECORD_SCALE`. Per-record `flow` is 0 while stopped, and the
session `avg_flow` excludes those samples. A lap's (and sector's) flow is the mean of the record
flow over MOVING records (`speed_mps > MOVING_SPEED_MPS`), which tracks the session `avg_flow` far
more closely than the non-zero mean (verified on 3 real FIT files: 3.89 vs 4.40, 3.29 vs 3.50,
3.87 vs 3.96; the non-zero mean ran ~2x high). Garmin's formula is unpublished, so this is
approximately on its scale, not exact.

Data presence drives everything: the block exists when the ride carries a grit/flow channel or
device totals, whatever the sport label says.
"""

from __future__ import annotations

from typing import Sequence

from swim_coach.models import CanonicalLap, JumpsSummary, MtbDynamics, MtbLap, Workout

GRIT_RECORD_SCALE = 1000.0
"""Per-record grit increments sum to the session total_grit x 1000 (device definition, verified
against a real FIT; see module docstring)."""


MOVING_SPEED_MPS = 1.0
"""Coach judgment: records faster than this count as moving for the flow mean (Garmin's formula is unpublished)."""


def has_channel(series: dict | None, name: str) -> bool:
    return bool(series) and any(v is not None for v in series.get(name) or [])


def window_indices(t_s: Sequence[float], start_s: float, stop_s: float) -> range:
    lo = next((i for i, t in enumerate(t_s) if t >= start_s), len(t_s))
    hi = next((i for i, t in enumerate(t_s) if t >= stop_s), len(t_s))
    return range(lo, hi)


def sum_grit(grit: Sequence[float | None], idx: range) -> float | None:
    vals = [grit[i] for i in idx if grit[i] is not None]
    return round(sum(vals) / GRIT_RECORD_SCALE, 2) if vals else None


def mean_nonzero(values: Sequence[float | None], idx: range) -> float | None:
    vals = [values[i] for i in idx if values[i]]
    return round(sum(vals) / len(vals), 2) if vals else None


def mean_moving(values: Sequence[float | None], speed: Sequence[float | None] | None, idx: range) -> float | None:
    """Mean of `values` over the records moving faster than MOVING_SPEED_MPS; without a speed
    channel, the mean of the non-zero samples."""
    if not speed:
        return mean_nonzero(values, idx)
    vals = [values[i] for i in idx if values[i] is not None and speed[i] is not None and speed[i] > MOVING_SPEED_MPS]
    return round(sum(vals) / len(vals), 2) if vals else None


def mean_present(values: Sequence[float | None], idx: range) -> float | None:
    vals = [values[i] for i in idx if values[i] is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def _summarise_jumps(workout: Workout) -> JumpsSummary | None:
    dev = workout.device_dynamics
    if dev is None or not dev.jumps:
        return None

    def top(values: list[float | None]) -> float | None:
        present = [v for v in values if v is not None]
        return max(present) if present else None

    return JumpsSummary(
        count=dev.jump_count if dev.jump_count is not None else len(dev.jumps),
        max_height_m=top([j.height_m for j in dev.jumps]),
        max_hang_time_s=top([j.hang_time_s for j in dev.jumps]),
        max_distance_m=top([j.distance_m for j in dev.jumps]),
        best_score=top([j.score for j in dev.jumps]),
    )


def _lap_rows(workout: Workout, series: dict | None, laps: Sequence[CanonicalLap]) -> list[MtbLap]:
    if not series or not (has_channel(series, "grit") or has_channel(series, "flow")):
        return []
    t_s = series.get("t_s") or []
    if not t_s:
        return []
    grit, flow, power = series.get("grit") or [], series.get("flow") or [], series.get("power_w") or []
    speed = series.get("speed_mps") or []
    jumps = workout.device_dynamics.jumps if workout.device_dynamics else []
    rows = []
    for lap in laps:
        start, stop = lap.start_s, lap.end_s
        idx = window_indices(t_s, start, stop)
        in_lap = [j for j in jumps if j.offset_s is not None and start <= j.offset_s < stop]
        rows.append(
            MtbLap(
                lap=lap.n,
                start_offset_s=lap.start_s,
                duration_s=lap.duration_s,
                distance_m=lap.distance_m,
                avg_power_w=lap.avg_power_w if lap.avg_power_w is not None else (mean_present(power, idx) if power else None),
                grit=sum_grit(grit, idx) if grit else None,
                avg_flow=mean_moving(flow, speed, idx) if flow else None,
                jumps=len(in_lap) if jumps else None,
            )
        )
    return rows


def build_mtb_dynamics(workout: Workout, series: dict | None, laps: Sequence[CanonicalLap] = ()) -> MtbDynamics | None:
    """The ride's Grit / Flow / jump block, or None when the ride carries none of them. `laps`: the
    canonical laps (`canonical_laps.build_canonical_laps`) the per-lap splits are cut at."""
    dev = workout.device_dynamics
    has_series = has_channel(series, "grit") or has_channel(series, "flow")
    if dev is None and not has_series:
        return None
    t_s = (series or {}).get("t_s") or []
    everything = range(len(t_s))
    total_grit = dev.total_grit if dev and dev.total_grit is not None else (
        sum_grit(series["grit"], everything) if has_channel(series, "grit") else None
    )
    avg_flow = dev.avg_flow if dev and dev.avg_flow is not None else (
        mean_nonzero(series["flow"], everything) if has_channel(series, "flow") else None
    )
    jump_count = dev.jump_count if dev and dev.jump_count is not None else (len(dev.jumps) if dev and dev.jumps else None)
    return MtbDynamics(
        total_grit=total_grit,
        avg_flow=avg_flow,
        jump_count=jump_count,
        laps=_lap_rows(workout, series, laps),
        jumps=_summarise_jumps(workout),
    )
