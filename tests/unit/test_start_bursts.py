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
    from swim_coach.analysis import analytics_for_coach
    import uuid

    d = json.loads((FIX / "ride_2026_10_10_starts_race_pace.json").read_text())
    s = Session.model_validate(d["planned_session"])
    athlete = Athlete(id=uuid.UUID(int=1), slug="t", name="T", **d["athlete_profile"])
    an = Workout.model_validate(d["workout"]).analyze(
        AnalysisContext(athlete=athlete, session=s, kind=s.kind, series=d["series"])
    )
    view = analytics_for_coach(an, sport="bike")
    keys = list(view["intervals"])
    assert keys.index("starts") < keys.index("starts_note") < keys.index("efforts")
    assert list(view).index("power_curve") < list(view).index("intervals")
    five = next(p for p in view["power_curve"] if p["duration"] == "5s")
    assert abs(five["watts"] - 956) <= 2
    assert not any(e["verdict"] == "warm-up build (not scored)" for e in view["intervals"]["efforts"])


def _coach_view_1010():
    import uuid

    from swim_coach.analysis import AnalysisContext
    from swim_coach.models import Athlete, Workout
    from swim_coach.analysis import analytics_for_coach

    d = json.loads((FIX / "ride_2026_10_10_starts_race_pace.json").read_text())
    s = Session.model_validate(d["planned_session"])
    athlete = Athlete(id=uuid.UUID(int=1), slug="t", name="T", **d["athlete_profile"])
    an = Workout.model_validate(d["workout"]).analyze(
        AnalysisContext(athlete=athlete, session=s, kind=s.kind, series=d["series"])
    )
    return analytics_for_coach(an, sport="bike")


def _walk(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k, v
            yield from _walk(v)
    elif isinstance(x, list):
        for v in x:
            yield from _walk(v)


def test_slim_coach_view_has_no_warmup_builds_starts_rounds_nulls_or_swim_fields():
    view = _coach_view_1010()
    text = json.dumps(view)
    assert "161.2" not in text and "130.8" not in text
    assert len(text) < 9500  # was ~17,200 chars; now includes traces and start findings
    assert all(v is not None for _k, v in _walk(view))
    for k in ("first_half_pace_s_per_100m", "swolf_first_quarter", "split_label"):
        assert k not in view
    iv = view["intervals"]
    assert [e["n"] for e in iv["efforts"]] == list(range(1, len(iv["efforts"]) + 1))
    assert all(e["duration_s"] > 60 for e in iv["efforts"])  # starts live only in `starts`
    assert "rounds" not in iv  # every round was a single rep, repeating its effort
    assert len(iv["starts"]) == 5 and all(len(s["trace_w"]) >= 30 for s in iv["starts"])
    assert "trace_cadence" not in iv["starts"][0]
    four = iv["starts"][3]
    assert four["dips"][0]["to_w"] == 721 and four["stopped_early_s"] == 9.0


def test_swim_coach_view_drops_power_fields():
    from swim_coach.models import WorkoutAnalytics
    from swim_coach.analysis import analytics_for_coach

    out = analytics_for_coach(
        WorkoutAnalytics(first_half_pace_s_per_100m=95.0, swolf_first_quarter=40.0, elapsed_min=30.0),
        sport="swim_pool",
    )
    assert out == {"first_half_pace_s_per_100m": 95.0, "swolf_first_quarter": 40.0, "elapsed_min": 30.0}


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
    assert [st.stopped_early_s is None for st in r.starts[2:]] == [True, True]
    assert r.starts[0].stopped_early_s is not None  # start 1 stopped after a 7 s burst of a 22 s shape


def test_launch_reads_use_library_39_bands(result):
    assert [s.launch_read for s in result.starts] == ["slow", "slow", "typical", "slow", "slow"]
    four = result.starts[3]
    assert abs(four.launch_s - 6) <= 1
    assert "slow vs 2-3.5 s typical (library/39)" in four.launch_note
    assert "(slow vs 2-3.5 s typical)" in four.verdict


def test_start_findings_are_deduped_capped_and_point_at_library_cues(result):
    findings = result.start_findings
    assert 1 <= len(findings) <= 3
    assert len({f.cue_key for f in findings}) == len(findings)
    slow = next(f for f in findings if f.cue_key == "slow_launch")
    assert "4 of 5" in slow.finding.replace("on 4 of 5 starts", "4 of 5") and "start 4" not in slow.evidence.split(":")[0]
    assert "starts 1, 2, 4, 5" in slow.evidence and "6 s to peak" in slow.evidence
    assert findings[0].cue_key == "stopped_early"  # most important first


def test_every_finding_cue_key_has_a_row_in_library_39():
    from swim_coach.start_trace import FINDING_ORDER

    table = (Path(__file__).resolve().parents[2] / "library" / "39-cycling-start-analysis.md").read_text()
    for key in FINDING_ORDER:
        assert f"| `{key}` |" in table


def test_coach_view_carries_findings_and_launch_notes_before_the_starts_note():
    view = _coach_view_1010()
    iv = view["intervals"]
    keys = list(iv)
    assert keys.index("starts") < keys.index("start_findings") < keys.index("starts_note")
    assert iv["starts"][3]["launch_read"] == "slow" and "library/39" in iv["starts"][3]["launch_note"]
    assert "lead with the top start_finding" in iv["starts_note"]
