"""Session kind in the plan: the generator tags race / warm-up sessions, the ramp rail counts
neither, and the coach's session overrides can set it."""

from __future__ import annotations

import uuid
from datetime import date

from swim_coach.models import Athlete, Session
from swim_coach.plan import (
    BIKE_WEEKLY_VOLUME_RAMP_CAP_FRACTION,
    _bike_prerace_primer_session,
    _bike_race_session,
    counts_toward_bike_ramp,
    evaluate_week_realism,
)

from app.tools import _apply_session_overrides

DAY = date(2026, 9, 19)
ATHLETE = Athlete(id=uuid.uuid4(), slug="t", name="T", ftp_watts=250.0)


def _bike(day: date, minutes: float, *, kind=None, purpose="endurance", zone="Z2") -> Session:
    return Session(
        id=uuid.uuid4(), athlete_id=ATHLETE.id, date=day, sport="bike", source="ai_coach",
        duration_min=minutes, intensity={"zone": zone}, purpose=purpose, kind=kind,
    )


def test_generator_tags_the_race_session_and_keeps_its_display_label():
    race = _bike_race_session(ATHLETE, DAY, None, 250.0)
    assert race.kind == "race" and race.purpose.startswith("RACE — ")


def test_generator_tags_the_pre_race_primer_as_a_warmup():
    assert _bike_prerace_primer_session(ATHLETE, DAY, 250.0).kind == "warmup"


def test_ramp_rail_counts_neither_race_nor_warmup_minutes():
    assert counts_toward_bike_ramp(_bike(DAY, 60, kind="workout"))
    assert counts_toward_bike_ramp(_bike(DAY, 60, kind="free_ride"))
    assert not counts_toward_bike_ramp(_bike(DAY, 60, kind="race"))
    assert not counts_toward_bike_ramp(_bike(DAY, 60, kind="warmup"))


def test_realism_ramp_rail_ignores_race_and_warmup_minutes():
    prev = 300.0
    cap = prev * (1 + BIKE_WEEKLY_VOLUME_RAMP_CAP_FRACTION)
    training = _bike(date(2026, 9, 14), cap - 1)  # just under the cap on its own
    extras = [
        _bike(date(2026, 9, 18), 30, kind="warmup", purpose="primer"),
        _bike(date(2026, 9, 19), 90, kind="race", purpose="RACE — x"),
    ]
    warnings = evaluate_week_realism([training, *extras], prev_week_bike_volume_min=prev)
    assert not any("safety" in w for w in warnings)
    over = evaluate_week_realism([_bike(date(2026, 9, 14), cap + 5)], prev_week_bike_volume_min=prev)
    assert any("safety" in w for w in over)


class _Week:
    def __init__(self, sessions):
        self.sessions = sessions


def _override(week, **entry):
    return _apply_session_overrides(week, [{"date": DAY.isoformat(), **entry}], ATHLETE)


def test_override_can_set_kind_on_an_existing_session():
    week = _Week([_bike(DAY, 60, purpose="Race: club crit")])
    assert week.sessions[0].kind == "workout"  # legacy backfill: no RACE — prefix
    error, _ = _override(week, sport="bike", kind="race")
    assert error is None and week.sessions[0].kind == "race"


def test_override_add_mode_accepts_kind_and_rejects_unknown_kinds():
    week = _Week([])
    error, _ = _override(week, sport="bike", add=True, duration_min=20, purpose="openers", kind="warmup")
    assert error is None and week.sessions[0].kind == "warmup"
    error, _ = _override(_Week([_bike(DAY, 60)]), sport="bike", kind="tempo")
    assert error is not None and "invalid session kind" in error
