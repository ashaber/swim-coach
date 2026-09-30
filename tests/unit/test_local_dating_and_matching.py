"""Local-time workout dating and the +-1 day planned-session match.

Regression for 2026-09-29: an evening ride was stored as 2026-09-30 (UTC date)
because the athlete had no timezone, so the planned 09-29 session never matched.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from pathlib import Path

from swim_coach.athlete_time import resolve_workout_date
from swim_coach.models import Session, Workout
from swim_coach.quality import match_workout_to_session

ATHLETE_ID = uuid.uuid4()
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "ride_2026_09_29_vo2_40_20.json"


def make_session(**overrides) -> Session:
    data = dict(
        id=uuid.uuid4(), athlete_id=ATHLETE_ID, date=date(2026, 9, 29), sport="bike",
        source="ai_coach", duration_min=60.0, distance_m=0, intensity={"zone": "Z5"}, purpose="test",
    )
    data.update(overrides)
    return Session(**data)


def make_workout(**overrides) -> Workout:
    data = dict(
        id=uuid.uuid4(), athlete_id=ATHLETE_ID, date=date(2026, 9, 30), sport="bike",
        source="fit", distance_m=1000, duration_min=55.0,
    )
    data.update(overrides)
    return Workout(**data)


# --- resolve_workout_date ---------------------------------------------------------


def test_prefers_provider_local_start():
    # 2026-09-29 20:15 local == 2026-09-30 02:15 UTC; the UTC date is a day late.
    got = resolve_workout_date(
        utc_date=date(2026, 9, 30), started_at=datetime(2026, 9, 30, 2, 15),
        provider_local="2026-09-29T20:15:00", timezone=None,
    )
    assert got == date(2026, 9, 29)


def test_falls_back_to_athlete_timezone():
    got = resolve_workout_date(
        utc_date=date(2026, 9, 30), started_at=datetime(2026, 9, 30, 2, 15),  # naive UTC (fitparse)
        provider_local=None, timezone="America/Denver",
    )
    assert got == date(2026, 9, 29)


def test_falls_back_to_utc_date():
    assert resolve_workout_date(
        utc_date=date(2026, 9, 30), started_at=None, provider_local=None, timezone="America/Denver"
    ) == date(2026, 9, 30)
    assert resolve_workout_date(
        utc_date=date(2026, 9, 30), started_at=datetime(2026, 9, 30, 2, 15), provider_local=None, timezone=None
    ) == date(2026, 9, 30)


def test_ignores_malformed_provider_value():
    assert resolve_workout_date(
        utc_date=date(2026, 9, 30), started_at=None, provider_local="not-a-date", timezone=None
    ) == date(2026, 9, 30)


# --- match_workout_to_session: +-1 day window --------------------------------------


def test_adjacent_day_matches_when_exactly_one_unmatched_session_fits():
    session = make_session()
    assert match_workout_to_session(make_workout(), [session]) is session


def test_adjacent_day_is_ambiguous_with_two_candidates():
    before, after = make_session(date=date(2026, 9, 29)), make_session(date=date(2026, 10, 1))
    assert match_workout_to_session(make_workout(), [before, after]) is None


def test_adjacent_day_needs_same_sport_and_at_most_one_day():
    swim = make_session(sport="swim_pool")
    far = make_session(date=date(2026, 9, 27))
    assert match_workout_to_session(make_workout(), [swim, far]) is None


def test_adjacent_day_skips_session_claimed_by_another_workout():
    session = make_session()
    claimed = make_workout(date=date(2026, 9, 29), planned_session_id=session.id)
    assert match_workout_to_session(make_workout(), [session], other_workouts=[claimed]) is None


def test_adjacent_day_skips_session_whose_own_day_already_has_a_workout():
    session = make_session()
    same_day = make_workout(date=date(2026, 9, 29))
    assert match_workout_to_session(make_workout(), [session], other_workouts=[same_day]) is None


def test_exact_date_still_beats_adjacent_day():
    exact = make_session(date=date(2026, 9, 30))
    adjacent = make_session(date=date(2026, 9, 29))
    assert match_workout_to_session(make_workout(), [adjacent, exact]) is exact


def test_workout_with_dangling_planned_id_still_does_not_fall_back():
    assert match_workout_to_session(make_workout(planned_session_id=uuid.uuid4()), [make_session()]) is None


def test_real_ride_fixture_matches_its_session_dated_locally_or_in_utc():
    fx = json.loads(FIXTURE.read_text())
    session = Session.model_validate(fx["planned_session"])
    for day in ("2026-09-29", "2026-09-30"):
        workout = Workout.model_validate({**fx["workout"], "date": day})
        assert match_workout_to_session(workout, [session]) is session
