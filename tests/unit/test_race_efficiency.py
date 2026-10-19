"""Race efficiency: lap-to-lap NP / HR efficiency factor, decoupling and a one-line verdict.

Synthetic, GPS-free fixtures only: N laps of LAP_S seconds and LAP_M metres at 1 Hz, with per-lap
power / HR / flow levels, optionally preceded by a different-length warm-up lap.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from swim_coach.analysis import BIKE_FIELDS, AnalysisContext, analytics_for_coach
from swim_coach.bike_coach_view import RACE_EFFICIENCY_COACH_NOTE
from swim_coach.models import Session, Workout, WorkoutLap, WorkoutStep, WorkoutStructure
from swim_coach.canonical_laps import build_canonical_laps
from swim_coach.race_efficiency import DECOUPLING_FLAG_PCT, build_race_efficiency as _build

LAP_S = 300
LAP_M = 1000.0


def _series(power: list[float], hr: list[float], flow: list[float] | None = None, warmup_s: int = 0) -> dict:
    t_s, dist, speed, pw, hrs, fl = [], [], [], [], [], []
    d, t = 0.0, 0
    for _ in range(warmup_s):  # a different-distance warm-up lap
        d += 3.0
        t_s.append(float(t))
        dist.append(d)
        speed.append(3.0)
        pw.append(120.0)
        hrs.append(110.0)
        fl.append(0.0)
        t += 1
    for k in range(len(power)):
        for _ in range(LAP_S):
            d += LAP_M / LAP_S
            t_s.append(float(t))
            dist.append(round(d, 2))
            speed.append(LAP_M / LAP_S)
            pw.append(power[k])
            hrs.append(hr[k])
            fl.append(flow[k] if flow else 0.0)
            t += 1
    out = {"t_s": t_s, "dist_m": dist, "speed_mps": speed, "power_w": pw, "hr": hrs}
    if flow:
        out["flow"] = fl
    return out


def _workout(n: int, warmup_s: int = 0) -> Workout:
    laps = [WorkoutLap(index=0, start_offset_s=0.0, duration_s=float(warmup_s), distance_m=3.0 * warmup_s)] if warmup_s else []
    laps += [
        WorkoutLap(index=len(laps) + k, start_offset_s=float(warmup_s + k * LAP_S), duration_s=float(LAP_S), distance_m=LAP_M)
        for k in range(n)
    ]
    return Workout(id=uuid.uuid4(), athlete_id=uuid.uuid4(), date=date(2026, 10, 17), sport="bike", source="fit",
                   distance_m=n * LAP_M, duration_min=n * LAP_S / 60, laps=laps)


def build_race_efficiency(workout: Workout, series: dict | None, race_start_s: float | None = None):
    return _build(build_canonical_laps(workout.laps, series, race_start_s=race_start_s), series)


def test_held_efficiency_has_per_lap_numbers_and_a_held_verdict():
    n = 4
    series = _series([250.0] * n, [170.0] * n, [4.0, 4.1, 4.2, 4.3])
    re = build_race_efficiency(_workout(n), series)
    assert [lap.lap for lap in re.laps] == [1, 2, 3, 4]
    lap = re.laps[0]
    assert lap.time_s == pytest.approx(300.0, abs=2)
    assert lap.avg_power_w == pytest.approx(250.0, abs=1)
    assert lap.np_w == pytest.approx(250.0, abs=1)
    assert lap.avg_hr == pytest.approx(170.0, abs=0.5)
    assert lap.ef == pytest.approx(250.0 / 170.0, abs=0.01)
    assert lap.speed_per_100w == pytest.approx((LAP_M / LAP_S) / 250.0 * 100, abs=0.01)
    assert re.trend.decoupling_pct == pytest.approx(0.0, abs=0.5)
    assert re.trend.decoupled_from_lap is None
    assert re.verdict.startswith("Efficiency held")
    assert "flow smoother" in re.verdict


def test_rising_hr_at_constant_power_is_decoupled_from_the_lap_it_started():
    n = 6
    hr = [165.0, 165.0, 166.0, 180.0, 182.0, 184.0]
    re = build_race_efficiency(_workout(n), _series([250.0] * n, hr))
    assert re.trend.decoupling_pct <= -DECOUPLING_FLAG_PCT
    assert re.trend.decoupled_from_lap == 4
    assert re.verdict.startswith("Decoupled from lap 4")
    assert "EF" in re.verdict
    assert re.trend.ef_change_pct < 0
    assert re.trend.hr_change_bpm == pytest.approx(19.0, abs=1)


def test_slopes_per_lap():
    n = 4
    re = build_race_efficiency(_workout(n), _series([250, 246, 242, 238], [170, 171, 172, 173]))
    assert re.trend.time_slope_s_per_lap == pytest.approx(0.0, abs=0.5)
    assert re.trend.power_slope_w_per_lap == pytest.approx(-4.0, abs=0.2)
    assert re.trend.hr_slope_bpm_per_lap == pytest.approx(1.0, abs=0.1)
    assert re.trend.power_change_pct == pytest.approx(-4.8, abs=0.2)


def test_warmup_lap_of_different_distance_is_left_out():
    n = 3
    re = build_race_efficiency(_workout(n, warmup_s=200), _series([250.0] * n, [170.0] * n, warmup_s=200))
    assert [lap.lap for lap in re.laps] == [2, 3, 4]


def test_laps_before_race_start_are_trimmed_and_the_start_lap_stays_out_of_the_trend():
    n = 4
    re = build_race_efficiency(_workout(n), _series([250.0, 300.0, 200.0, 200.0], [170.0] * n), race_start_s=LAP_S + 10.0)
    assert [lap.lap for lap in re.laps] == [1, 2, 3]  # lap 1 = the start lap, cut at the gun
    assert re.laps[0].start_lap and re.laps[0].time_s == pytest.approx(LAP_S - 10.0, abs=2)
    assert not any(lap.start_lap for lap in re.laps[1:])
    assert re.trend.power_change_pct == pytest.approx(0.0, abs=0.5)  # laps 2 -> 3, not 1 -> 3


def test_none_without_two_laps_or_power():
    assert build_race_efficiency(_workout(1), _series([250.0], [170.0])) is None
    series = _series([250.0] * 3, [170.0] * 3)
    series.pop("power_w")
    assert build_race_efficiency(_workout(3), series) is None
    assert build_race_efficiency(_workout(3), None) is None


def test_no_hr_still_reads_power_and_time_without_ef():
    n = 3
    series = _series([250.0, 245.0, 240.0], [170.0] * n)
    series.pop("hr")
    re = build_race_efficiency(_workout(n), series)
    assert all(lap.ef is None for lap in re.laps)
    assert re.trend.decoupling_pct is None
    assert "power" in re.verdict


def test_analyzer_attaches_it_for_a_race_and_the_coach_view_leads_with_it():
    assert "race_efficiency" in BIKE_FIELDS
    n = 4
    wo = _workout(n)
    series = _series([250.0] * n, [170.0] * n, [4.0] * n)
    wo.analytics = wo.analyze(AnalysisContext(kind="race", series=series))
    assert wo.analytics.race_efficiency is not None
    view = analytics_for_coach(wo.analytics, "bike")
    assert next(iter(view)) == "race_efficiency"
    block = view["race_efficiency"]
    assert block["coach_note"] == RACE_EFFICIENCY_COACH_NOTE
    assert block["verdict"].startswith("Efficiency held")
    assert len(block["laps"]) == n and "EF" in block["laps"][0]


def test_structured_workout_gets_no_race_efficiency():
    n = 3
    wo = _workout(n)
    session = Session(
        id=uuid.uuid4(), athlete_id=wo.athlete_id, date=wo.date, sport="bike", source="ai_coach", duration_min=15,
        intensity={}, purpose="intervals",
        structured=WorkoutStructure(items=[WorkoutStep(label="work", role="interval", duration_kind="time_s", duration_s=300)]),
    )
    ctx = AnalysisContext(kind="workout", session=session, series=_series([250.0] * n, [170.0] * n))
    assert wo.analyze(ctx).race_efficiency is None
