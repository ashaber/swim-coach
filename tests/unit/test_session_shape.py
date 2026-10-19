"""Session-shape reads on real rides: running-best start scoring, double-burst starts,
HR-scored technical reps, lap-shape detection (no plan), race start, and the
decoupling gate (10/10 + 9/26 technical-course rides, 9/19 race, 10/06 + 10/07 unchanged)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swim_coach.interval_analysis import analyze
from swim_coach.models import Session, StartBurst, WorkoutLap
from swim_coach.race_start import analyze_race_start
from swim_coach.rep_shape import RepRead, infer_lap_shape, is_technical, mentions_technical

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def _run(name: str, *, plan: bool = True, **kw):
    d = json.loads((FIX / name).read_text())
    s = Session.model_validate(d["planned_session"]) if d.get("planned_session") else None
    laps = [WorkoutLap.model_validate(x) for x in d["workout"]["laps"]]
    p = d["athlete_profile"]
    return analyze(
        d["series"], sport="bike", structure=s.structured if (s and plan) else None, laps=laps,
        ftp_watts=p["ftp_watts"], home_elevation_m=p["home_elevation_m"], lthr_bpm=p["lthr_bpm"], **kw,
    )


@pytest.fixture(scope="module")
def r926():
    return _run("ride_2026_09_26_starts_technical_5x5.json")


@pytest.fixture(scope="module")
def r926_noplan():
    return _run("ride_2026_09_26_starts_technical_5x5.json", plan=False)


@pytest.fixture(scope="module")
def r1010():
    return _run("ride_2026_10_10_starts_race_pace.json", session_text="3min @ 278-286W technical section, barrier")


# --- 1. running-best weak-start read ----------------------------------------------------------


def test_weak_start_uses_best_start_so_far(r926):
    assert [s.n for s in r926.starts] == [1, 2, 3, 4]
    s1, s2, s3, s4 = r926.starts
    assert s1.drop_vs_best_pct is None and not s1.weak_start
    assert s2.weak_start and s2.weak_kind == "execution_miss" and abs(s2.drop_vs_best_pct - 13.6) <= 1
    # starts 3 and 4 beat start 1's best 5 s, so they are "as strong as the best so far"
    assert s3.drop_vs_best_pct is None and s4.drop_vs_best_pct is None
    assert "as strong as your best start so far" in s3.verdict
    assert r926.starts_flag == "start 2 off (likely execution) -- skill rep, not fatigue"
    assert "stop" not in r926.starts_flag and "consider stopping" not in s2.verdict.lower()


def test_old_stored_rows_with_drop_vs_first_load():
    sb = StartBurst.model_validate(
        {"n": 2, "prescribed_s": 30.0, "drop_vs_first_pct": 15.8, "stop_rule_flag": True, "verdict": "x"}
    )
    assert sb.drop_vs_best_pct is None and sb.weak_start


# --- 2. double bursts -------------------------------------------------------------------


def test_single_burst_starts_stay_single_on_10_10(r1010):
    assert len(r1010.starts) == 5
    assert all(s.burst2_peak_w is None and s.dip_w is None for s in r1010.starts)


def test_double_burst_starts_on_9_26(r926):
    s1, s2, s3, s4 = r926.starts
    assert s1.burst2_peak_w is None  # one clean launch
    # (burst-1 peak, burst-2 peak, dip W) read straight from the stream
    for s, (p1, p2, dip) in zip((s2, s3, s4), [(989, 882, 105), (887, 967, 203), (1094, 954, 52)]):
        assert abs(s.peak_w - p1) <= 2 and abs(s.burst2_peak_w - p2) <= 2 and abs(s.dip_w - dip) <= 2
        assert 2 <= s.dip_s <= 5
        assert s.burst2_start_s > s.burst_start_s and s.burst2_best_5s_w <= s.burst2_peak_w
    assert "burst 2" in s2.verdict
    # five-second builds are openers, not starts
    assert all(s.prescribed_s >= 30 for s in r926.starts)


# --- 3. technical reps scored on HR -----------------------------------------------------


def test_9_26_reps_are_hr_scored(r926):
    reps = [e for e in r926.efforts if e.duration_s == 300.0]
    assert len(reps) == 4
    partial, *technical = reps
    assert "partial stream" in partial.verdict and partial.stream_coverage_pct < 30
    assert [e.technical for e in technical] == [True, True, True]
    assert {e.technical_reason for e in technical} == {"label"}
    for e in technical:
        assert e.fade_pct is None and e.terrain_flag is None
        for banned in ("under target", "faded", "built through"):
            assert banned not in e.verdict
        assert "effort held" in e.verdict and "NP" in e.verdict and "LTHR" in e.verdict
        assert e.np_w >= e.avg_w and e.time_ge90_lthr_s > 200  # full-window NP: rounds equal on a steady rep
    assert [round(e.pct_lthr) for e in technical] == [90, 93, 94]
    assert r926.technical_reps == 3 and r926.hr_rise_across_reps_bpm == 8.0
    assert r926.fade_across_reps_pct is None


def test_10_10_reps_2_to_5_hr_scored_rep_1_power_scored(r1010):
    reps = [e for e in r1010.efforts if e.duration_s == 180.0]
    assert [bool(e.technical) for e in reps] == [False, True, True, True, True]
    assert [e.technical_reason for e in reps[1:]] == ["variability"] * 4
    assert "on target" in reps[0].verdict and "genuine fade" in reps[0].verdict  # paved rep, smooth power
    assert all("effort held" in e.verdict for e in reps[1:])


def test_smooth_over_under_blocks_are_not_technical():
    r = _run("ride_2026_10_06_over_unders_altitude.json", plan=False)
    assert not any(e.technical for e in r.efforts) and r.technical_reps is None
    assert [e.avg_w for e in r.efforts][2:] == [241.2, 261.3, 265.5]


def test_is_technical_rules():
    def read(low):
        return RepRead(1.0, 200, 210, 150, 87.0, 100.0, low)

    assert is_technical(read(1.0), label_says=True, plan_text_says=False) == "label"
    assert is_technical(read(25.0), label_says=False, plan_text_says=False) == "variability"
    assert is_technical(read(12.0), label_says=False, plan_text_says=False) is None
    assert is_technical(read(12.0), label_says=False, plan_text_says=True) == "variability"
    assert is_technical(read(1.0), label_says=False, plan_text_says=True) is None
    assert mentions_technical("run-up, barrier, remount") and not mentions_technical("steady 3 min")


# --- 4. lap-shape detection (no plan) ---------------------------------------------------


def test_lap_shape_finds_starts_and_work_reps_without_a_plan(r926_noplan):
    r = r926_noplan
    assert r.detection_source == "lap_shape" and r.matched_to_prescription is False
    assert len(r.starts) == 4  # the 5 s builds are not starts
    work = [e for e in r.efforts if e.duration_s == 300.0]
    assert len(work) == 4
    assert [e.technical for e in work[1:]] == [True, True, True]
    assert [s.peak_w for s in r.starts][:2] == [977, 989]


def test_lap_shape_needs_a_repeating_pattern():
    class Lap:
        def __init__(self, d, w, off):
            self.duration_s, self.avg_power_w, self.start_offset_s = d, w, off

    laps = [Lap(300, 150, 0), Lap(180, 60, 300), Lap(300, 200, 480), Lap(180, 70, 780)]  # only 2 repeats
    assert infer_lap_shape(laps, None, burst_floor_w=None) is None
    laps += [Lap(300, 210, 960), Lap(180, 60, 1260)]
    got = infer_lap_shape(laps, None, burst_floor_w=None)
    assert got is not None and got.source == "lap_shape" and len(got.windows) == 3


# --- 5. race start ----------------------------------------------------------------------


def test_race_start_on_9_19():
    d = json.loads((FIX / "race_2026_09_19_cyclocross.json").read_text())
    laps = [WorkoutLap.model_validate(x) for x in d["workout"]["laps"]]
    p = d["athlete_profile"]
    r = analyze(d["series"], sport="bike", laps=laps, ftp_watts=p["ftp_watts"], lthr_bpm=p["lthr_bpm"], race=True)
    rs = r.race_start
    assert rs.start_s == 253.0 and rs.peak_w == 862 and 15 <= rs.burst_s <= 22
    assert rs.best_5s_w > rs.best_15s_w > rs.best_30s_w
    assert 20 <= rs.time_to_settle_s <= 90
    assert rs.first_5min_np_w > rs.race_np_w and rs.first_5min_vs_race_np_pct > 110
    assert r.decoupling_tightened_pct is None and r.decoupling_note is None and r.session_shape == "race"
    assert r.efforts == []


def test_race_start_skips_opener_before_the_race():
    t = list(range(0, 1500))
    power = [100.0] * 1500
    for i in range(60, 66):
        power[i] = 700.0  # warm-up opener, then easy spinning
    for i in range(600, 612):
        power[i] = 800.0  # the real start
    for i in range(612, 1500):
        power[i] = 250.0
    rs = analyze_race_start({"t_s": [float(x) for x in t], "power_w": power}, ftp_watts=276.0)
    assert rs.start_s == 600.0 and rs.peak_w == 800
    assert rs.time_to_settle_s is not None and rs.time_to_settle_s <= 45
    assert analyze_race_start({"t_s": [0.0, 1.0], "power_w": [None, None]}, ftp_watts=276.0) is None


# --- 6. decoupling gated by session shape -------------------------------------------------


def test_interval_and_starts_sessions_get_no_decoupling_note(r1010, r926):
    for r in (r1010, r926):
        assert r.decoupling_note is None and r.decoupling_tightened_pct is None
        assert r.session_shape == "starts"


def test_endurance_ride_keeps_its_decoupling_read():
    r = _run("ride_2026_10_07_endurance_altitude.json", plan=False)
    assert r.decoupling_tightened_pct == 7.5 and "intensity change" in r.decoupling_note
    assert r.session_shape is None


# --- lap-key (open) steps -----------------------------------------------------------------


def test_plan_with_lap_key_recoveries_falls_back_to_lap_shape():
    d = json.loads((FIX / "ride_2026_09_26_starts_technical_5x5.json").read_text())
    s = Session.model_validate(d["planned_session"])
    tree = s.structured.model_dump(mode="json")

    def open_recoveries(items):
        for it in items:
            if it["kind"] == "repeat":
                open_recoveries(it["steps"])
            elif it["role"] == "recovery":
                it["duration_kind"], it["duration_value"] = "open", None

    open_recoveries(tree["items"])
    structure = type(s.structured).model_validate(tree)
    laps = [WorkoutLap.model_validate(x) for x in d["workout"]["laps"]]
    p = d["athlete_profile"]
    r = analyze(d["series"], sport="bike", structure=structure, laps=laps, ftp_watts=p["ftp_watts"], lthr_bpm=p["lthr_bpm"])
    assert r.detection_source == "lap_shape" and len(r.starts) == 4 and r.technical_reps == 3


def test_open_duration_bike_step_exports_as_a_lap_button_step():
    import fitdecode
    from swim_coach.garmin_export import to_garmin_fit_workout
    from swim_coach.models import WorkoutStep, WorkoutStructure, WorkoutTarget

    structure = WorkoutStructure(items=[
        WorkoutStep(label="Start", role="interval", duration_kind="time_s", duration_value=30.0, modality="bike",
                    target=WorkoutTarget(basis="open")),
        WorkoutStep(label="Recover until lap key", role="recovery", duration_kind="open", modality="bike",
                    target=WorkoutTarget(basis="power_w", low=143.0, high=143.0)),
    ])
    data = to_garmin_fit_workout(structure, "bike", "starts")
    with fitdecode.FitReader(data) as fit:
        steps = [
            {f.name: f.value for f in fr.fields}
            for fr in fit
            if fr.frame_type == fitdecode.FIT_FRAME_DATA and fr.name == "workout_step"
        ]
    assert [st["duration_type"] for st in steps] == ["time", "open"]


# --- weak-start classification, held seconds ------------------------------------------------


def test_classify_weak_starts():
    from swim_coach.interval_analysis import _classify_weak

    # isolated miss, next start recovers
    assert _classify_weak([900, 700, 890], [False, True, False]) == [None, "execution_miss", None]
    # two consecutive weak starts are fatigue
    assert _classify_weak([900, 700, 650], [False, True, True]) == [None, "fatigue", "fatigue"]
    # last start weak after a steady decline: fatigue; last weak after a fine one: a miss
    assert _classify_weak([950, 900, 800], [False, False, True]) == [None, None, "fatigue"]
    assert _classify_weak([900, 950, 800], [False, False, True]) == [None, None, "execution_miss"]


def test_intended_hold_parses_the_label_shape():
    from swim_coach.interval_analysis import intended_hold_s

    assert intended_hold_s("Start rep (12s all-out, brake for corner, ~10s out)", 30.0) == 22.0
    assert intended_hold_s("Race start", 30.0) == 30.0
    assert intended_hold_s("15 s launch -> hold race pace to beep", 30.0) == 15.0
    assert intended_hold_s("40s then 50s", 30.0) == 30.0  # does not fit inside the step


def test_held_seconds_count_both_bursts_on_9_26(r926):
    held = [s.held_s for s in r926.starts]
    assert held[0] == 7.0 and 14 <= held[1] <= 18 and all(s.intended_s == 22.0 for s in r926.starts)
    assert r926.starts[1].verdict.startswith("held 16 of 22 s; burst 1 peak")
    assert "4 s dip to 105 W" in r926.starts[1].verdict


def test_coach_view_carries_the_skill_rep_note(r926):
    from swim_coach.models import WorkoutAnalytics
    from swim_coach.analysis import analytics_for_coach

    out = analytics_for_coach(WorkoutAnalytics(intervals=r926), sport="bike")
    assert "skill rep" in out["intervals"]["starts_note"]
