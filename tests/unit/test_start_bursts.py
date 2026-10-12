"""Race-start scoring: read the burst from the stream, not the prescribed 30 s window
(real 10/10 ride: 5 starts, athlete's lap presses drifted off the bursts)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swim_coach.interval_analysis import analyze
from swim_coach.models import Session, WorkoutLap

FIX = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture(scope="module")
def result():
    d = json.loads((FIX / "ride_2026_10_10_starts_race_pace.json").read_text())
    s = Session.model_validate(d["planned_session"])
    laps = [WorkoutLap.model_validate(x) for x in d["workout"]["laps"]]
    p = d["athlete_profile"]
    return analyze(
        d["series"], sport="bike", structure=s.structured, laps=laps,
        ftp_watts=p["ftp_watts"], home_elevation_m=p["home_elevation_m"],
    )


# (peak, s_to_peak, best5, burst_len) from the stream, bursts above ~400 W.
TRUTH = [(1079, 3, 956, 14), (1065, 4, 946, 16), (919, 2, 805, 21), (1100, 2, 894, 18), (978, 3, 826, 26)]


def test_five_starts_match_stream(result):
    assert len(result.starts) == 5
    for st, (peak, to_peak, best5, length) in zip(result.starts, TRUTH):
        assert abs(st.peak_w - peak) <= 2
        assert abs(st.s_to_peak - to_peak) <= 1
        assert abs(st.best_5s_w - best5) <= 2
        assert abs(st.burst_s - length) <= 1
        assert st.prescribed_s == 30.0


def test_drop_vs_best_and_weak_starts_are_isolated_execution_misses(result):
    drops = [s.drop_vs_best_pct for s in result.starts]
    assert drops[0] is None
    assert abs(drops[1] - 1) <= 1 and abs(drops[2] - 16) <= 1
    assert abs(drops[3] - 6) <= 1 and abs(drops[4] - 14) <= 1
    assert [s.weak_start for s in result.starts] == [False, False, True, False, True]
    # start 4 recovered after start 3, and start 4 -> 5 is no steady decline: both are isolated
    assert [s.weak_kind for s in result.starts] == [None, None, "execution_miss", None, "execution_miss"]
    assert result.starts_flag == "start 3 and start 5 off (likely execution) -- skill rep, not fatigue"
    assert "16% below best start (start 1)" in result.starts[2].verdict
    assert "stop" not in result.starts[2].verdict.lower()


def test_held_seconds_lead_the_verdict(result):
    assert [s.held_s for s in result.starts] == [13.0, 16.0, 21.0, 18.0, 26.0]
    assert all(s.intended_s == 30.0 for s in result.starts)
    assert result.starts[2].verdict.startswith("held 21 of 30 s; peak 919 W, best 5 s 805 W")


def test_start_efforts_carry_burst_verdicts_not_fade(result):
    starts = [e for e in result.efforts if e.duration_s < 60 and e.avg_w and e.avg_w > 300]
    assert starts
    for e in starts:
        assert e.fade_pct is None and e.terrain_flag is None
        assert "faded" not in e.verdict and "built through" not in e.verdict
        assert "peak" in e.verdict


def test_race_pace_reps_unchanged(result):
    reps = [e for e in result.efforts if e.duration_s == 180.0]
    assert [e.avg_w for e in reps] == [280.5, 218.0, 247.7, 219.9, 238.0]
    assert reps[0].fade_pct is not None and "target" in reps[0].verdict
