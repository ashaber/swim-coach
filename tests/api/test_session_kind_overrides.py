"""Session kind via the coach's session overrides (backend `_apply_session_overrides`)."""

from __future__ import annotations

import uuid
from datetime import date

from swim_coach.models import Athlete, Session

from app.tools import _apply_session_overrides

DAY = date(2026, 9, 19)
ATHLETE = Athlete(id=uuid.uuid4(), slug="t", name="T", ftp_watts=250.0)


def _bike(day: date, minutes: float, *, kind=None, purpose="endurance", zone="Z2") -> Session:
    return Session(
        id=uuid.uuid4(), athlete_id=ATHLETE.id, date=day, sport="bike", source="ai_coach",
        duration_min=minutes, intensity={"zone": zone}, purpose=purpose, kind=kind,
    )


class _Week:
    def __init__(self, sessions):
        self.sessions = sessions


def _override(week, **entry):
    return _apply_session_overrides(week, [{"date": DAY.isoformat(), **entry}], ATHLETE)


def test_override_can_set_kind_on_an_existing_session():
    week = _Week([_bike(DAY, 60, purpose="Race: club crit")])
    assert week.sessions[0].kind is None and week.sessions[0].effective_kind == "workout"
    error, _ = _override(week, sport="bike", kind="race")
    assert error is None and week.sessions[0].kind == "race"


def test_override_add_mode_accepts_kind_and_rejects_unknown_kinds():
    week = _Week([])
    error, _ = _override(week, sport="bike", add=True, duration_min=20, purpose="openers", kind="warmup")
    assert error is None and week.sessions[0].kind == "warmup"
    error, _ = _override(_Week([_bike(DAY, 60)]), sport="bike", kind="tempo")
    assert error is not None and "invalid session kind" in error
