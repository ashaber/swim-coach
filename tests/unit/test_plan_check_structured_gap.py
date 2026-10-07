"""Advisory: a Garmin-pushable session with prose `structure` but no `structured` workout."""

from __future__ import annotations

import uuid
from datetime import date

from swim_coach.models import Athlete, Session, WeekPlan
from swim_coach.plan_check import check_week

PROSE = "Warm-up: 10min easy. Main set: 3 x 9min over/under. Cool-down: 10min"


def _athlete() -> Athlete:
    return Athlete(id=uuid.uuid4(), slug="t", name="T", css_pace_s_per_100m=None, constraints={}, pool_schedule=[])


def _session(athlete: Athlete, sport: str, day: date, structure: str | None = PROSE) -> Session:
    return Session(
        id=uuid.uuid4(), athlete_id=athlete.id, date=day, sport=sport, source="ai_coach",
        duration_min=60.0, intensity={"zone": "Z4"}, purpose="threshold", structure=structure,
    )


def _week(athlete: Athlete, sessions: list[Session]) -> WeekPlan:
    return WeekPlan(
        id=uuid.uuid4(), athlete_id=athlete.id, iso_week="2026-W41", meso_block="build",
        focus="build", target_volume_m=0, sessions=sessions,
    )


def test_flags_prose_only_bike_session_as_advisory() -> None:
    athlete = _athlete()
    bike = _session(athlete, "bike", date(2026, 10, 6))
    report = check_week(_week(athlete, [bike]), None, athlete, recent_weeks=[])
    finding = next(f for f in report.findings if f.id == "no-structured-workout")
    assert "2026-10-06" in finding.evidence
    assert "structured" in finding.fix
    assert not finding.id.startswith("confirm-")


def test_skips_sessions_that_cannot_or_need_not_be_structured() -> None:
    athlete = _athlete()
    sessions = [
        _session(athlete, "swim_pool", date(2026, 10, 5)),  # swim is not Garmin-pushable
        _session(athlete, "recovery", date(2026, 10, 6)),
        _session(athlete, "bike", date(2026, 10, 7), structure=None),
        _session(athlete, "bike", date(2026, 10, 8), structure="  "),
    ]
    report = check_week(_week(athlete, sessions), None, athlete, recent_weeks=[])
    assert not [f for f in report.findings if f.id.startswith("no-structured-workout")]
