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
    assert "consider stopping" not in result.starts[2].verdict.lower()


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


def test_efforts_include_every_start_and_agree_with_the_starts_table(result):
    """Start 1's series window fell in a recording gap and was dropped; the burst search
    still found it, so `efforts` must carry it with the table's numbers."""
    by_start = {e.start_s: e for e in result.efforts}
    for st in result.starts:
        e = by_start[st.burst_start_s]
        assert abs(e.avg_w - st.avg_w) <= 2
        assert f"peak {st.peak_w} W, best 5 s {st.best_5s_w} W" in e.verdict


def test_warmup_builds_are_labelled_not_scored(result):
    builds = [e for e in result.efforts if e.duration_s <= 5]
    assert [e.avg_w for e in builds] == [161.2, 130.8]
    assert all(e.verdict == "warm-up build (not scored)" for e in builds)


def test_coach_view_drops_warmup_builds_and_leads_with_starts_and_curve():
    from swim_coach.models import Athlete
    from swim_coach.analysis import AnalysisContext
    from swim_coach.models import Workout
    from swim_coach.power_curve import analytics_for_coach
    import uuid

    d = json.loads((FIX / "ride_2026_10_10_starts_race_pace.json").read_text())
    s = Session.model_validate(d["planned_session"])
    athlete = Athlete(id=uuid.UUID(int=1), slug="t", name="T", **d["athlete_profile"])
    an = Workout.model_validate(d["workout"]).analyze(
        AnalysisContext(athlete=athlete, session=s, kind=s.kind, series=d["series"])
    )
    view = analytics_for_coach(an)
    keys = list(view["intervals"])
    assert keys.index("starts") < keys.index("starts_note") < keys.index("efforts")
    assert list(view).index("power_curve") < list(view).index("intervals")
    five = next(p for p in view["power_curve"] if p["duration"] == "5s")
    assert abs(five["watts"] - 956) <= 2
    assert not any(e["verdict"] == "warm-up build (not scored)" for e in view["intervals"]["efforts"])


def test_coach_view_renumbers_efforts_and_tags_start_n(result):
    from swim_coach.power_curve import _tag_start_efforts

    iv = {
        "starts": [{"n": s.n, "burst_start_s": s.burst_start_s} for s in result.starts],
        "efforts": [{"n": e.n, "start_s": e.start_s} for e in result.efforts if e.duration_s > 5],
    }
    _tag_start_efforts(iv)
    assert [e["n"] for e in iv["efforts"]] == list(range(1, len(iv["efforts"]) + 1))
    assert [e.get("start_n") for e in iv["efforts"][:6]] == [1, 2, 3, 4, 5, None]


def test_start_4_trace_matches_the_athletes_read_of_the_graph(result):
    """Athlete's read of start 4 (intervals.icu graph): 0 -> 1100 W in ~6 s, dip to ~720 W at
    ~7 s, ~700 W plateau, stops ~19 s, ~2 s coast, weak restart ~360-550 W for ~5 s (30 s step)."""
    s = result.starts[3]
    assert 0 < len(s.trace_w) <= 45 and s.trace_cadence is not None
    assert max(s.trace_w) == s.peak_w == 1100
    assert abs(s.launch_s - 6) <= 1 and s.trace_w[s.trace_t0] < 100
    assert len(s.dips) == 1
    d = s.dips[0]
    assert abs(d.at_s - 7) <= 1 and abs(d.to_w - 720) <= 50 and d.recovered_to_w > d.to_w + 100
    assert abs(s.stopped_at_s - 19) <= 2
    assert abs(s.stopped_early_s - (30 - s.stopped_at_s)) < 0.01
    r = s.restart
    assert abs(r.after_gap_s - 2) <= 1 and abs(r.duration_s - 5) <= 1
    assert 360 <= r.avg_w <= 550 and r.peak_w <= 560
    assert "dip to 721 W" in s.verdict and "likely shift/bobble" in s.verdict
    assert "weak restart" in s.verdict and "before the 30 s mark" in s.verdict


def test_every_start_has_a_bounded_trace_and_a_stop(result):
    for s in result.starts:
        assert 30 <= len(s.trace_w) <= 45
        assert s.stopped_at_s is not None and s.sustained_s > 0
    assert result.starts[4].stopped_early_s is None  # held to within 1 s of the 30 s mark


def test_926_double_burst_brake_is_not_a_stop():
    d = json.loads((FIX / "ride_2026_09_26_starts_technical_5x5.json").read_text())
    s = Session.model_validate(d["planned_session"])
    laps = [WorkoutLap.model_validate(x) for x in d["workout"]["laps"]]
    p = d["athlete_profile"]
    r = analyze(d["series"], sport="bike", structure=s.structured, laps=laps,
                ftp_watts=p["ftp_watts"], home_elevation_m=p["home_elevation_m"])
    assert len(r.starts) == 4
    assert all(st.trace_w for st in r.starts)
    assert [st.stopped_early_s is None for st in r.starts[1:]] == [True, True, True]
    assert r.starts[0].stopped_early_s is not None  # start 1 stopped after a 7 s burst of a 22 s shape
