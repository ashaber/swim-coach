"""backend/app/load_helpers.py -- the shared per-workout AU load
computation used by routes/workouts.py, tools.py's get_workouts, and
context.py's render_focused_workout, so all three report the exact same
number instead of the coach chat guessing at one (the real reported bug
this module fixes -- see its own module docstring)."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from app.load_helpers import workout_load_au
from swim_coach.models import Athlete, Workout


def _athlete(**overrides) -> Athlete:
    payload = {
        "id": uuid4(), "slug": "renee", "name": "Renee",
        "css_pace_s_per_100m": 90.0, "sex": None,
    }
    payload.update(overrides)
    return Athlete(**payload)


def _workout(**overrides) -> Workout:
    payload = {
        "id": uuid4(), "athlete_id": uuid4(), "date": date(2026, 8, 1),
        "sport": "cross_train", "source": "fit", "distance_m": 0,
        "duration_min": 60.0, "rpe": None,
    }
    payload.update(overrides)
    return Workout(**payload)


def test_reaches_hr_trimp_tier_when_avg_hr_and_hr_max_are_available():
    # Same fixture numbers as tests/api/test_workouts_route.py's own
    # hr_trimp test: avg_hr=140, hr_max=180, hr_rest falls back to
    # HR_REST_GENERIC_FALLBACK_BPM (60, no wellness history given) --
    # HRR_fraction = (140-60)/(180-60) = 0.6667, TRIMP ~= 98.4 (renee's
    # profile has no `sex` set, so the Banister weighting averages the
    # male/female curves -- see load.py's _trimp_weighting_factor).
    w = _workout(avg_hr=140, duration_min=60)
    load_au, load_tier = workout_load_au(w, athlete=_athlete(), hr_max=180.0, wellness=[])
    assert load_tier == "hr_trimp"
    assert load_au == pytest.approx(98.4, abs=0.1)


def test_falls_through_to_duration_only_when_no_rpe_no_hr_and_hr_max_unknown():
    # No rpe, no avg_hr on the workout itself, AND hr_max unknown (e.g. no
    # workout in this athlete's history has ever logged max_hr) --
    # tier 2 is genuinely unreachable, same honest fallback session_load
    # itself already guarantees (never crashes, never fabricates a tier).
    w = _workout(avg_hr=None, duration_min=45)
    load_au, load_tier = workout_load_au(w, athlete=_athlete(), hr_max=None, wellness=[])
    assert load_tier == "duration"
    assert load_au == pytest.approx(45 * 5, abs=0.01)  # DURATION_ONLY_ASSUMED_INTENSITY = 5


def test_srpe_tier_wins_over_hr_trimp_when_rpe_is_present():
    # rpe present AND avg_hr/hr_max present -- tier 1 (sRPE) still takes
    # priority over tier 2, matching session_load's own documented order.
    w = _workout(rpe=5, avg_hr=140, duration_min=150)
    load_au, load_tier = workout_load_au(w, athlete=_athlete(), hr_max=180.0, wellness=[])
    assert load_tier == "srpe"
    assert load_au == 750.0  # duration_min * rpe
