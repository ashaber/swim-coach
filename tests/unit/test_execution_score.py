"""Execution scores: the 9/29 real ride, edge cases, and the race score."""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path

import pytest

from swim_coach.execution_score import (
    WORKOUT_WEIGHTS,
    intensity_match,
    race_execution_score,
    workout_execution_score,
)
from swim_coach.gps_laps import GpsLapMetrics
from swim_coach.interval_analysis import analyze
from swim_coach.models import Athlete, Session, Workout, WorkoutLap
from swim_coach.quality import workout_quality
from swim_coach.race_phases import RacePhase

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "ride_2026_09_29_vo2_40_20.json"
FTP = 276.0


@pytest.fixture(scope="module")
def ride() -> dict:
    return json.loads(FIXTURE.read_text())


@pytest.fixture()
def session(ride) -> Session:
    return Session.model_validate(ride["planned_session"])


@pytest.fixture()
def workout(ride) -> Workout:
    w = dict(ride["workout"])
    w["analytics"] = None
    return Workout.model_validate(w)


@pytest.fixture()
def intervals(ride, session):
    laps = [WorkoutLap.model_validate(x) for x in ride["workout"]["laps"]]
    return analyze(
        copy.deepcopy(ride["series"]), sport="bike", structure=session.structured, laps=laps,
        ftp_watts=FTP, home_elevation_m=823.0,
    )


def test_weights_sum_to_one():
    assert sum(WORKOUT_WEIGHTS.values()) == pytest.approx(1.0)


def test_real_ride_scores_high_with_breakdown(intervals, workout, session):
    s = workout_execution_score(intervals, workout, session)
    assert s.kind == "workout" and s.reason is None
    by = {c.name: c for c in s.components}
    assert by["intensity"].score == 100.0
    assert by["completion"].score >= 99.0
    assert by["consistency"].score == 100.0
    assert sum(c.weight for c in s.components) == pytest.approx(1.0)
    assert s.score == pytest.approx(sum(c.score * c.weight for c in s.components), abs=0.2)
    assert s.score >= 99.0


def test_bailed_reps_lower_completion_and_intensity(intervals, workout, session):
    weak = intervals.model_copy(update={"reps_completed": 12, "reps_in_band_pct": 50.0})
    s = workout_execution_score(weak, workout, session)
    full = workout_execution_score(intervals, workout, session)
    assert s.score < full.score - 20
    assert {c.name: c for c in s.components}["completion"].score < 90


def test_fade_beyond_free_band_costs_consistency(intervals, workout, session):
    faded = intervals.model_copy(update={"fade_across_reps_pct": 12.5, "fade_across_rounds_pct": 3.0})
    c = {c.name: c for c in workout_execution_score(faded, workout, session).components}
    assert c["consistency"].score == pytest.approx(50.0)


def test_missing_band_drops_intensity_and_renormalizes(intervals, workout, session):
    no_band = intervals.model_copy(update={"reps_in_band_pct": None})
    s = workout_execution_score(no_band, workout, session)
    by = {c.name: c for c in s.components}
    assert by["intensity"].score is None and by["intensity"].weight == 0.0
    assert sum(c.weight for c in s.components) == pytest.approx(1.0)
    assert s.score is not None


def test_unmatched_workout_has_no_score_and_says_why(intervals, workout, session):
    s = workout_execution_score(intervals, workout, None)
    assert s.score is None and "not matched" in s.reason
    free = intervals.model_copy(update={"matched_to_prescription": False})
    s = workout_execution_score(free, workout, session)
    assert s.score is None and "prescription" in s.reason
    assert workout_execution_score(None, workout, session).score is None


def test_intensity_match_from_analyzer(intervals):
    assert intensity_match(intervals) == "match"
    assert intensity_match(intervals.model_copy(update={"reps_in_band_pct": 40.0})) == "mismatch"
    assert intensity_match(intervals.model_copy(update={"reps_in_band_pct": None})) == "unknown"
    assert intensity_match(intervals.model_copy(update={"matched_to_prescription": False})) == "unknown"
    assert intensity_match(None) == "unknown"


def test_workout_quality_carries_score_and_intensity_match(ride, session, intervals):
    w = dict(ride["workout"])
    w["planned_session_id"] = str(session.id)
    workout = Workout.model_validate(w)
    workout = workout.model_copy(
        update={"analytics": workout.analytics.model_copy(update={"intervals": intervals})}
    )
    athlete = Athlete(
        id=uuid.uuid4(), slug="andrew", name="Andrew", css_pace_s_per_100m=90.0, ftp_watts=FTP
    )
    q = workout_quality(workout, session, athlete=athlete)
    assert q.intensity_match == "match"
    assert q.execution is not None and q.execution.score >= 99.0
    assert workout_quality(workout, None, athlete=athlete).execution is None


# --- race ---------------------------------------------------------------------


def _phases(start: float, nps: list[float]) -> list[RacePhase]:
    out = [RacePhase("start", 0, 90, 90, start, 5.0)]
    for i, np_w in enumerate(nps):
        out.append(RacePhase(f"phase_{i + 1}", 90 + i * 600, 690 + i * 600, 600, np_w, 6.0))
    return out


def _laps(nps: list[float]) -> list[GpsLapMetrics]:
    return [
        GpsLapMetrics(
            lap_n=i + 1, start_s=0, end_s=1, duration_s=300, normalized_power_w=n,
            avg_speed_mps=6.0, efficiency_mps_per_w=None, total_work_kj=None,
            variability_index=None, coasting_s=None,
        )
        for i, n in enumerate(nps)
    ]


def test_even_race_scores_100():
    s = race_execution_score(_phases(260, [250, 250, 250]), _laps([250, 251, 249, 250]))
    assert s.kind == "race" and s.score == 100.0
    assert sum(c.weight for c in s.components) == pytest.approx(1.0)


def test_faded_hot_start_race_scores_lower():
    even = race_execution_score(_phases(260, [250, 250, 250]), _laps([250, 250, 250]))
    bad = race_execution_score(_phases(400, [260, 240, 200]), _laps([270, 250, 200]))
    by = {c.name: c for c in bad.components}
    assert bad.score < even.score - 30
    assert by["late_fade"].score < 50 and by["start_control"].score < 50


def test_race_without_laps_renormalizes_and_short_ride_unscored():
    s = race_execution_score(_phases(260, [250, 250, 250]), [])
    lap = {c.name: c for c in s.components}["lap_consistency"]
    assert lap.score is None and lap.weight == 0.0 and s.score == 100.0
    short = race_execution_score([RacePhase("start", 0, 90, 90, 200, 5.0)], [])
    assert short.score is None and short.reason
