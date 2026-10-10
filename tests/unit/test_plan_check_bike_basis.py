"""Advisory: a bike session whose structured steps use a swim-pace target basis.

Real incident, prod 2026-10-10: the coach wrote watts (278-286) under
`target.basis="absolute"` (= swim pace in s/100m); garmin_export would push a
pace target and the analyzer's prescription only resolves `power_w`."""

from __future__ import annotations

import uuid
from datetime import date

from swim_coach.models import Athlete, Session, WeekPlan, WorkoutStep, WorkoutStructure, WorkoutTarget
from swim_coach.plan_check import bike_swim_basis_steps, check_week


def _athlete() -> Athlete:
    return Athlete(id=uuid.uuid4(), slug="t", name="T", css_pace_s_per_100m=None, constraints={}, pool_schedule=[])


def _structured(basis: str, low: float, high: float) -> WorkoutStructure:
    step = WorkoutStep(
        label="Main", role="interval", modality="bike", duration_kind="time_s", duration_value=600,
        target=WorkoutTarget(basis=basis, low=low, high=high),
    )
    return WorkoutStructure(items=[step])


def _session(a: Athlete, sport: str, structured: WorkoutStructure) -> Session:
    return Session(
        id=uuid.uuid4(), athlete_id=a.id, date=date(2026, 10, 6), sport=sport, source="ai_coach",
        duration_min=60.0, intensity={"zone": "Z4"}, purpose="threshold", structure="x", structured=structured,
    )


def _week(a: Athlete, sessions: list[Session]) -> WeekPlan:
    return WeekPlan(id=uuid.uuid4(), athlete_id=a.id, iso_week="2026-W41", meso_block="build", focus="b",
                    target_volume_m=0, sessions=sessions)


def test_helper_flags_absolute_and_percent_css_on_bike_only() -> None:
    a = _athlete()
    assert bike_swim_basis_steps(_session(a, "bike", _structured("absolute", 278, 286)))
    assert bike_swim_basis_steps(_session(a, "bike", _structured("percent_css", 90, 95)))
    assert not bike_swim_basis_steps(_session(a, "bike", _structured("power_w", 278, 286)))
    assert not bike_swim_basis_steps(_session(a, "bike", _structured("zone", 0, 0)))
    assert not bike_swim_basis_steps(_session(a, "swim_pool", _structured("absolute", 90, 95)))


def test_check_week_surfaces_stored_bad_bike_session() -> None:
    a = _athlete()
    report = check_week(_week(a, [_session(a, "bike", _structured("absolute", 278, 286))]), None, a, recent_weeks=[])
    f = next(f for f in report.findings if f.id == "bike-swim-pace-basis")
    assert "2026-10-06" in f.evidence and "power_w" in f.fix
    assert not f.id.startswith("confirm-")


def test_check_week_quiet_for_power_w() -> None:
    a = _athlete()
    report = check_week(_week(a, [_session(a, "bike", _structured("power_w", 278, 286))]), None, a, recent_weeks=[])
    assert all(f.id != "bike-swim-pace-basis" for f in report.findings)
