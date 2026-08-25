"""Tests for swim_coach.compliance: per-workout planned-vs-actual matching
and interpretation.

No LLM calls, no network access -- pure arithmetic + model validation, same
discipline as test_load.py.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from swim_coach.analytics import CARDIAC_DRIFT_FLAG_PCT
from swim_coach.compliance import match_workout_to_session, workout_compliance
from swim_coach.models import Session, Workout, WorkoutAnalytics

ATHLETE_ID = uuid.uuid4()


def make_session(**overrides):
    data = dict(
        id=uuid.uuid4(),
        athlete_id=ATHLETE_ID,
        date=date(2026, 7, 6),
        sport="swim_pool",
        source="pool_coach",
        duration_min=60.0,
        distance_m=3000,
        intensity={"anchor": "rpe"},
        purpose="test",
    )
    data.update(overrides)
    return Session(**data)


def make_workout(**overrides):
    data = dict(
        id=uuid.uuid4(),
        athlete_id=ATHLETE_ID,
        date=date(2026, 7, 6),
        sport="swim_pool",
        source="manual",
        distance_m=3000,
        duration_min=60.0,
        rpe=6,
    )
    data.update(overrides)
    return Workout(**data)


# --- match_workout_to_session -----------------------------------------------------


def test_match_exact_planned_session_id_wins():
    target = make_session(date=date(2026, 7, 6), sport="swim_pool")
    # A decoy that would "coincidentally" match on date+sport too -- the id
    # match must win over it, not the other way around.
    decoy = make_session(date=date(2026, 7, 6), sport="swim_pool")
    workout = make_workout(
        date=date(2026, 7, 6), sport="swim_pool", planned_session_id=target.id
    )
    result = match_workout_to_session(workout, [decoy, target])
    assert result is target


def test_match_falls_back_to_date_and_sport_when_no_planned_id():
    session = make_session(date=date(2026, 7, 8), sport="swim_ow")
    workout = make_workout(date=date(2026, 7, 8), sport="swim_ow", planned_session_id=None)
    result = match_workout_to_session(workout, [session])
    assert result is session


def test_match_returns_none_when_neither_condition_holds():
    session = make_session(date=date(2026, 7, 8), sport="swim_ow")
    workout = make_workout(date=date(2026, 7, 9), sport="swim_pool", planned_session_id=None)
    result = match_workout_to_session(workout, [session])
    assert result is None


def test_match_dangling_planned_session_id_does_not_fall_back():
    # The workout claims a planned_session_id, but no session in the list
    # carries that id -- e.g. the plan week was regenerated and the old
    # session no longer exists. Documented behavior: this does NOT fall
    # through to the date+sport fallback (mirrors the JS original, whose
    # fallback branch is gated on the WORKOUT having no planned_session_id
    # at all) even though a same-date/same-sport session is present and
    # would otherwise match.
    other_session = make_session(date=date(2026, 7, 6), sport="swim_pool")
    workout = make_workout(
        date=date(2026, 7, 6), sport="swim_pool", planned_session_id=uuid.uuid4()
    )
    result = match_workout_to_session(workout, [other_session])
    assert result is None


# --- workout_compliance -------------------------------------------------------------


def test_workout_compliance_no_session_gives_unmatched_and_all_none():
    workout = make_workout(
        analytics=WorkoutAnalytics(cardiac_drift_pct=12.0),
    )
    result = workout_compliance(workout, None)
    assert result.matched is False
    assert result.distance_delta_pct is None
    assert result.duration_delta_pct is None
    assert result.intensity_match == "unknown"
    assert result.quality_summary is None


def test_workout_compliance_over_delivered_distance_is_positive():
    session = make_session(distance_m=3000, duration_min=60.0)
    workout = make_workout(distance_m=3300, duration_min=60.0)
    result = workout_compliance(workout, session)
    assert result.matched is True
    assert result.distance_delta_pct == 10.0


def test_workout_compliance_under_delivered_distance_is_negative():
    session = make_session(distance_m=3000, duration_min=60.0)
    workout = make_workout(distance_m=2700, duration_min=60.0)
    result = workout_compliance(workout, session)
    assert result.distance_delta_pct == -10.0


def test_workout_compliance_duration_delta_rounds_to_one_decimal():
    session = make_session(distance_m=3000, duration_min=60.0)
    workout = make_workout(distance_m=3000, duration_min=65.0)
    result = workout_compliance(workout, session)
    assert result.duration_delta_pct == pytest.approx(8.3)


def test_workout_compliance_session_without_distance_gives_none_distance_delta():
    # Recovery/strength session shape -- distance_m is None, not comparable.
    session = make_session(sport="strength", distance_m=None, duration_min=45.0)
    workout = make_workout(sport="strength", distance_m=0, duration_min=45.0)
    result = workout_compliance(workout, session)
    assert result.distance_delta_pct is None
    # duration_min is always set on Session, so this still computes.
    assert result.duration_delta_pct == 0.0


def test_workout_compliance_intensity_match_is_unknown_phase1():
    # Phase-1 gap: no zone-classification-from-pace/HR function exists yet
    # in zones.py, so intensity_match can never be "match"/"mismatch" today
    # regardless of whether session.intensity carries a zone.
    session = make_session(intensity={"zone": "Z2", "anchor": "css_pace"})
    workout = make_workout()
    result = workout_compliance(workout, session)
    assert result.intensity_match == "unknown"


def test_workout_compliance_intensity_match_unknown_when_no_zone_on_session():
    session = make_session(intensity={"anchor": "rpe"})
    workout = make_workout()
    result = workout_compliance(workout, session)
    assert result.intensity_match == "unknown"


def test_workout_compliance_quality_summary_none_without_analytics():
    session = make_session()
    workout = make_workout(analytics=None)
    result = workout_compliance(workout, session)
    assert result.quality_summary is None


def test_workout_compliance_quality_summary_flags_notable_cardiac_drift():
    session = make_session()
    workout = make_workout(
        analytics=WorkoutAnalytics(cardiac_drift_pct=CARDIAC_DRIFT_FLAG_PCT + 3.0)
    )
    result = workout_compliance(workout, session)
    assert result.quality_summary is not None
    assert "drift" in result.quality_summary.lower()


def test_workout_compliance_quality_summary_is_calm_without_notable_flags():
    session = make_session()
    workout = make_workout(analytics=WorkoutAnalytics(cardiac_drift_pct=0.5))
    result = workout_compliance(workout, session)
    assert result.quality_summary is not None
    assert "no notable" in result.quality_summary.lower()
