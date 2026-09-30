"""Prescription-aware interval analysis on a real ride (2026-09-29, 3 rounds of
6 x 40s Z5 / 20s Z1 with 4 min between rounds; fixture is the owner's own data).

Before this build the analyzer, handed no prescription, reported 3 x 5.6 min
"efforts" at ~259 W. With the planned session's `structured` and the athlete's
FTP it must report the 18 real reps.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from swim_coach.analytics import compute_analytics
from swim_coach.interval_analysis import analyze
from swim_coach.models import Session, Workout, WorkoutLap, WorkoutStructure
from swim_coach.prescription import flatten_prescription, resolve_step_band_w

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "ride_2026_09_29_vo2_40_20.json"
FTP = 276.0


@pytest.fixture(scope="module")
def ride() -> dict:
    return json.loads(FIXTURE.read_text())


@pytest.fixture()
def series(ride) -> dict:
    return copy.deepcopy(ride["series"])


@pytest.fixture()
def laps(ride) -> list[WorkoutLap]:
    return [WorkoutLap.model_validate(x) for x in ride["workout"]["laps"]]


@pytest.fixture()
def structure(ride) -> WorkoutStructure:
    return WorkoutStructure.model_validate(ride["planned_session"]["structured"])


def test_flatten_expands_nested_repeats_into_rounds(structure):
    reps = flatten_prescription(structure, ftp_watts=FTP)
    intervals = [leaf.rep for leaf in reps if leaf.rep is not None]
    assert len(intervals) == 18
    assert [r.round_n for r in intervals] == [1] * 6 + [2] * 6 + [3] * 6
    assert [r.rep_in_round for r in intervals[:7]] == [1, 2, 3, 4, 5, 6, 1]
    assert all(r.duration_s == 40.0 and r.zone == "Z5" for r in intervals)
    # Z5 for FTP 276 = 105-120% = 289.8-331.2 W (zones.bike_zone_table)
    assert intervals[0].low_w == pytest.approx(289.8, abs=0.1)
    assert intervals[0].high_w == pytest.approx(331.2, abs=0.1)
    assert reps[0].role == "warmup" and reps[0].offset_s == 0.0
    assert intervals[0].offset_s == 900.0


def test_zone_without_ftp_has_no_watts(structure):
    reps = flatten_prescription(structure, ftp_watts=None)
    first = next(leaf.rep for leaf in reps if leaf.rep is not None)
    assert first.low_w is None and first.high_w is None and first.zone == "Z5"


def test_resolve_step_band_power_basis():
    from swim_coach.models import WorkoutStep, WorkoutTarget

    step = WorkoutStep(
        label="x", role="interval", duration_kind="time_s", duration_value=60,
        modality="bike", target=WorkoutTarget(basis="power_w", low=250, high=270),
    )
    assert resolve_step_band_w(step.target, FTP) == (250, 270)


def test_analyze_without_prescription_is_unchanged(series):
    result = analyze(series, sport="bike", home_elevation_m=823.0)
    assert result.efforts_detected == 3
    assert result.matched_to_prescription is False


def test_analyze_with_prescription_reports_18_reps_from_laps(series, laps, structure):
    result = analyze(
        series, sport="bike", structure=structure, laps=laps, ftp_watts=FTP,
        home_elevation_m=823.0,
    )
    assert result.matched_to_prescription is True
    assert result.detection_source == "laps"
    assert result.efforts_detected == 18
    assert result.prescribed_count == 18
    assert result.reps_completed == 18
    assert len(result.efforts) == 18
    for e in result.efforts:
        assert 300 <= e.avg_w <= 315
        assert e.duration_s == pytest.approx(40, abs=1)
        assert e.in_target_band is True
    assert result.reps_in_band_pct == 100.0
    assert result.target_zone == "Z5"
    assert result.target_band_w == pytest.approx((289.8, 331.2), abs=0.1)
    assert [e.round_n for e in result.efforts][:7] == [1] * 6 + [2]


def test_round_summary_and_fade(series, laps, structure):
    result = analyze(series, sport="bike", structure=structure, laps=laps, ftp_watts=FTP)
    assert [r.n for r in result.rounds] == [1, 2, 3]
    for r in result.rounds:
        assert r.reps_prescribed == 6 and r.reps_completed == 6
        assert 300 <= r.avg_w <= 315
        assert r.avg_hr is not None
    # coach read: "zero fade" -- power flat across reps and rounds
    assert abs(result.fade_across_reps_pct) < 3
    assert abs(result.fade_across_rounds_pct) < 3


def test_series_fallback_when_no_laps(series, structure):
    result = analyze(series, sport="bike", structure=structure, laps=None, ftp_watts=FTP)
    assert result.matched_to_prescription is True
    assert result.detection_source == "series"
    assert result.efforts_detected == 18
    assert all(295 <= e.avg_w <= 320 for e in result.efforts)


def test_series_fallback_tolerates_time_offset(series, structure):
    shifted = dict(series)
    shifted["t_s"] = [t + 25 for t in series["t_s"]]
    # a 25 s late start of the whole structure: pad the front with easy riding
    pad = list(range(25))
    for key in ("power_w", "hr", "grade", "dist_m", "speed_mps", "altitude_m", "cadence_rpm"):
        shifted[key] = [series[key][0]] * 25 + list(series[key])
    shifted["t_s"] = pad + [t + 25 for t in series["t_s"]]
    result = analyze(shifted, sport="bike", structure=structure, laps=None, ftp_watts=FTP)
    assert result.matched_to_prescription is True
    assert result.efforts_detected == 18
    assert all(295 <= e.avg_w <= 320 for e in result.efforts)


def test_incomplete_ride_counts_completed_reps(series, laps, structure):
    cut = [lap for lap in laps if lap.index <= 26]  # through round 2's recovery
    cut_series = {k: [v for v, t in zip(vals, series["t_s"]) if t < 1860] for k, vals in series.items()}
    result = analyze(cut_series, sport="bike", structure=structure, laps=cut, ftp_watts=FTP)
    assert result.prescribed_count == 18
    assert result.reps_completed == 12
    assert result.efforts_detected == 12
    assert len(result.rounds) == 3
    assert result.rounds[2].reps_completed == 0


def test_rep_below_band_is_flagged(series, laps, structure):
    weak = copy.deepcopy(series)
    for i, t in enumerate(weak["t_s"]):
        if 960 <= t < 1000:  # rep 2
            weak["power_w"][i] = 250
    result = analyze(weak, sport="bike", structure=structure, laps=laps, ftp_watts=FTP)
    assert result.efforts[1].in_target_band is False
    assert result.reps_in_band_pct == pytest.approx(17 / 18 * 100, abs=0.2)


def test_prescription_without_ftp_still_finds_reps(series, laps, structure):
    result = analyze(series, sport="bike", structure=structure, laps=laps, ftp_watts=None)
    assert result.matched_to_prescription is True
    assert result.efforts_detected == 18
    assert result.reps_in_band_pct is None
    assert result.target_band_w is None


def test_compute_analytics_bike_has_no_swim_fields(ride, series, laps, structure):
    a = compute_analytics(
        laps=laps, lengths=[], pauses=[], series=series, elapsed_min=55.5, moving_min=55.5,
        sport="bike", prescribed_structure=structure, ftp_watts=FTP, home_elevation_m=823.0,
    )
    assert a.first_half_pace_s_per_100m is None
    assert a.second_half_pace_s_per_100m is None
    assert a.split_label is None
    assert a.swolf_degradation_pct is None
    assert a.intervals.matched_to_prescription is True
    assert a.avg_power_w is not None


def test_compute_analytics_swim_keeps_swim_fields():
    laps = [
        WorkoutLap(index=0, start_offset_s=0, duration_s=60, distance_m=100, avg_pace_s_per_100m=60.0),
        WorkoutLap(index=1, start_offset_s=60, duration_s=66, distance_m=100, avg_pace_s_per_100m=66.0),
    ]
    a = compute_analytics(
        laps=laps, lengths=[], pauses=[], series=None, elapsed_min=2, moving_min=2, sport="swim_pool"
    )
    assert a.first_half_pace_s_per_100m is not None
