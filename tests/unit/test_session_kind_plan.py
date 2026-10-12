"""Session kind in the plan: the generator tags race / warm-up sessions, the ramp rail counts
neither. The coach-override side lives in tests/api/test_session_kind_overrides.py."""

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
