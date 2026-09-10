"""Unit tests for the deterministic interval analyzer.

Effort detection is exercised against the real MTB race fixture (a
robustness fixture -- an unstructured race, not a 2x12 session); the
per-interval quality math, terrain-confound flag, and tightened decoupling
are exercised against synthetic sample arrays with known answers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swim_coach import interval_analysis as ia
from swim_coach.models import (
    WorkoutRepeat,
    WorkoutStep,
    WorkoutStructure,
    WorkoutTarget,
)
from swim_coach.parse_files import parse_fit

FIT_MTB_RACE = Path(__file__).parent / "fixtures" / "fit" / "real_mtb_race.fit"
FIT_SWIM = Path(__file__).parent / "fixtures" / "fit" / "real_swim.fit"


# --- synthetic series builders --------------------------------------------------------


def _steady_effort_series(
    *, power: float, seconds: int, hr: int = 150, grade: float = 0.05, t0: float = 0.0
) -> dict:
    """A single flat effort: `seconds` 1Hz samples at constant power/hr/grade,
    bracketed by 90s of easy soft-pedalling either side so `detect_efforts`
    sees a real edge."""
    easy_n = 90
    t, p, h, g = [], [], [], []
    clock = t0
    for _ in range(easy_n):
        t.append(clock); p.append(80.0); h.append(110); g.append(0.0); clock += 1
    for _ in range(seconds):
        t.append(clock); p.append(power); h.append(hr); g.append(grade); clock += 1
    for _ in range(easy_n):
        t.append(clock); p.append(80.0); h.append(110); g.append(0.0); clock += 1
    return {"t_s": t, "power_w": p, "hr": h, "grade": g}


def _ramp_effort(power_start: float, power_end: float, seconds: int, *, hr, grade) -> dict:
    """One effort whose power moves linearly start->end, with caller-supplied
    per-sample hr / grade lists (len == seconds), padded with easy edges."""
    easy_n = 90
    t, p, h, g = [], [], [], []
    clock = 0.0
    for _ in range(easy_n):
        t.append(clock); p.append(70.0); h.append(105); g.append(0.0); clock += 1
    for i in range(seconds):
        frac = i / (seconds - 1)
        t.append(clock)
        p.append(power_start + (power_end - power_start) * frac)
        h.append(hr[i])
        g.append(grade[i])
        clock += 1
    for _ in range(easy_n):
        t.append(clock); p.append(70.0); h.append(105); g.append(0.0); clock += 1
    return {"t_s": t, "power_w": p, "hr": h, "grade": g}


# --- detect_efforts -----------------------------------------------------------------


def test_detect_efforts_finds_a_single_clean_interval():
    s = _steady_effort_series(power=240, seconds=720)  # 12 min
    efforts = ia.detect_efforts(s, target_w=240)
    assert len(efforts) == 1
    e = efforts[0]
    assert e.duration_s == pytest.approx(720, abs=20)
    assert e.start_s == pytest.approx(90, abs=5)


def test_detect_efforts_finds_two_intervals_with_recovery_between():
    a = _steady_effort_series(power=240, seconds=720)
    # stitch a second effort after the first, sharing the clock
    b = _steady_effort_series(power=238, seconds=720, t0=a["t_s"][-1] + 1)
    s = {k: a[k] + b[k] for k in a}
    efforts = ia.detect_efforts(s, target_w=239)
    assert len(efforts) == 2
    assert all(560 <= e.duration_s <= 820 for e in efforts)


def test_detect_efforts_ignores_a_sub_two_minute_surge():
    s = _steady_effort_series(power=300, seconds=60)  # 1 min -- below EFFORT_MIN_S
    assert ia.detect_efforts(s, target_w=250) == []


def test_detect_efforts_bridges_a_short_dip_mid_interval():
    s = _steady_effort_series(power=240, seconds=720)
    # drop 10s in the middle to soft-pedal (a corner)
    mid = len(s["power_w"]) // 2
    for i in range(mid, mid + 10):
        s["power_w"][i] = 60.0
    efforts = ia.detect_efforts(s, target_w=240)
    assert len(efforts) == 1  # not split into two


def test_detect_efforts_hr_fallback_when_no_power():
    s = _steady_effort_series(power=240, seconds=600)
    del s["power_w"]  # HR-only ride
    efforts = ia.detect_efforts(s)
    assert len(efforts) == 1


def test_detect_efforts_empty_series():
    assert ia.detect_efforts({}) == []
    assert ia.detect_efforts({"t_s": [0, 1, 2], "power_w": [None, None, None]}) == []


# --- assess_effort: quality math ---------------------------------------------------


def test_assess_effort_on_target_interval():
    s = _steady_effort_series(power=240, seconds=720, hr=150, grade=0.0)
    e = ia.detect_efforts(s, target_w=240)[0]
    q = ia.assess_effort(s, e, target_w=240)
    assert q.avg_w == pytest.approx(240, abs=1)
    assert q.pct_of_target == pytest.approx(100, abs=1)
    assert q.avg_vs_target_w == pytest.approx(0, abs=1)
    assert q.time_in_band_pct == pytest.approx(100, abs=1)
    assert q.fade_pct == pytest.approx(0, abs=1)
    assert q.terrain_flag is None
    assert q.verdict.startswith("on target")


def test_assess_effort_under_target():
    s = _steady_effort_series(power=200, seconds=720, hr=150, grade=0.0)
    e = ia.detect_efforts(s, target_w=240)[0]
    q = ia.assess_effort(s, e, target_w=240)
    assert q.pct_of_target == pytest.approx(200 / 240 * 100, abs=1)
    assert q.avg_vs_target_w == pytest.approx(-40, abs=1)
    assert q.time_in_band_pct == pytest.approx(0, abs=1)
    assert "under target" in q.verdict


def test_assess_effort_fade_flagged_when_power_drops_and_hr_holds():
    n = 720
    hr = [150] * n
    grade = [0.05] * n  # flat grade -- no terrain explanation
    s = _ramp_effort(280, 210, n, hr=hr, grade=grade)  # first/last-third means ~18% apart
    e = ia.detect_efforts(s, target_w=240)[0]
    q = ia.assess_effort(s, e, target_w=240)
    assert q.fade_pct is not None and q.fade_pct >= ia.FADE_FLAG_PCT
    assert q.terrain_flag is not None
    assert "genuine fade" in q.terrain_flag


def test_assess_effort_terrain_confound_downhill_grade_with_held_hr():
    n = 720
    hr = [148 + i // 180 for i in range(n)]  # HR drifts slightly UP
    grade = [0.09 - 0.10 * (i / (n - 1)) for i in range(n)]  # +9% climb -> -1% descent
    s = _ramp_effort(280, 200, n, hr=hr, grade=grade)  # power fades hard
    e = ia.detect_efforts(s, target_w=250)[0]
    q = ia.assess_effort(s, e, target_w=250)
    assert q.grade_delta_pct_pts is not None and q.grade_delta_pct_pts >= 3
    assert q.terrain_flag is not None
    assert "terrain" in q.terrain_flag and "downhill" in q.terrain_flag


def test_assess_effort_backed_off_when_power_and_hr_both_drop():
    n = 720
    hr = [160 - int(20 * (i / (n - 1))) for i in range(n)]  # HR falls 20 bpm
    grade = [0.0] * n
    s = _ramp_effort(255, 215, n, hr=hr, grade=grade)
    e = ia.detect_efforts(s, target_w=240)[0]
    q = ia.assess_effort(s, e, target_w=240)
    assert q.terrain_flag == "power and HR both dropped -- backed off"


# --- match_efforts_to_structure --------------------------------------------------


def _two_by_twelve_structure(target_w: float) -> WorkoutStructure:
    return WorkoutStructure(
        items=[
            WorkoutStep(
                label="warmup", role="warmup", duration_kind="time_s", duration_value=600,
                modality="bike",
            ),
            WorkoutRepeat(
                repeat_mode="count",
                count=2,
                steps=[
                    WorkoutStep(
                        label="threshold", role="interval", duration_kind="time_s",
                        duration_value=720, modality="bike",
                        target=WorkoutTarget(basis="power_w", low=target_w, high=target_w),
                    ),
                    WorkoutStep(
                        label="recover", role="recovery", duration_kind="time_s",
                        duration_value=360, modality="bike",
                    ),
                ],
            ),
        ]
    )


def test_match_efforts_to_structure_aligns_two_reps():
    struct = _two_by_twelve_structure(239)
    a = _steady_effort_series(power=239, seconds=720)
    b = _steady_effort_series(power=239, seconds=720, t0=a["t_s"][-1] + 400)
    s = {k: a[k] + b[k] for k in a}
    detected = ia.detect_efforts(s, target_w=239)
    res = ia.match_efforts_to_structure(detected, struct)
    assert res.prescribed_count == 2
    assert res.detected_count == 2
    assert res.matched is True
    assert [tw for _, tw, _ in res.per_rep] == [239, 239]


def test_match_efforts_to_structure_count_mismatch_reports_unmatched():
    struct = _two_by_twelve_structure(239)
    s = _steady_effort_series(power=239, seconds=720)  # only one effort
    detected = ia.detect_efforts(s, target_w=239)
    res = ia.match_efforts_to_structure(detected, struct)
    assert res.matched is False
    assert res.prescribed_count == 2 and res.detected_count == 1
    assert res.per_rep[1][0] is None  # second rep unmatched


def test_match_efforts_to_structure_none_structure():
    res = ia.match_efforts_to_structure([], None)
    assert res.matched is False and res.prescribed_count == 0


# --- tightened_decoupling ---------------------------------------------------------


def test_tightened_decoupling_none_on_stop_start_ride():
    # Only ~40% of moving time is spent working (> COASTING_FLOOR_W) -- below
    # TIGHTENED_DECOUPLING_MIN_WORKING_FRAC.
    n = 1500
    t = [float(i) for i in range(n)]
    power = [200.0 if i % 5 < 2 else 5.0 for i in range(n)]
    hr = [150] * n
    speed = [8.0 if i % 5 < 2 else 1.0 for i in range(n)]
    val, reason = ia.tightened_decoupling({"t_s": t, "power_w": power, "hr": hr, "speed_mps": speed})
    assert val is None
    assert "stop-start" in reason


def test_tightened_decoupling_real_number_on_steady_effort():
    n = 2400
    t = [float(i) for i in range(n)]
    # steady power, HR drifts up 8 bpm over the effort -> positive decoupling
    power = [230.0] * n
    hr = [145 + int(8 * (i / (n - 1))) for i in range(n)]
    val, reason = ia.tightened_decoupling({"t_s": t, "power_w": power, "hr": hr})
    assert val is not None
    assert 1.0 <= val <= 5.0  # first-half vs second-half midpoints compress the 8bpm drift
    assert "working" in reason


def test_tightened_decoupling_no_hr_returns_none():
    val, reason = ia.tightened_decoupling({"t_s": [0.0, 1.0], "power_w": [200, 210]})
    assert val is None and "heart rate" in reason


# --- analyze(): the public entry point / sport gating ----------------------------


def test_analyze_returns_none_for_non_bike_sport():
    s = _steady_effort_series(power=240, seconds=600)
    assert ia.analyze(s, sport="swim_pool") is None
    assert ia.analyze(s, sport="cross_train") is None
    assert ia.analyze(None, sport="bike") is None


def test_analyze_bike_ride_with_target_produces_block():
    a = _steady_effort_series(power=239, seconds=720)
    b = _steady_effort_series(power=225, seconds=720, t0=a["t_s"][-1] + 400)
    s = {k: a[k] + b[k] for k in a}
    block = ia.analyze(s, sport="bike", target_w=239)
    assert block is not None
    assert block.detection_basis == "power"
    assert block.efforts_detected == 2
    assert block.efforts[0].target_w == 239
    assert block.efforts[0].pct_of_target == pytest.approx(100, abs=2)
    assert block.efforts[1].pct_of_target == pytest.approx(225 / 239 * 100, abs=2)


def test_analyze_bike_ride_uses_structure_targets_over_supplied():
    struct = _two_by_twelve_structure(300)
    a = _steady_effort_series(power=300, seconds=720)
    b = _steady_effort_series(power=300, seconds=720, t0=a["t_s"][-1] + 400)
    s = {k: a[k] + b[k] for k in a}
    block = ia.analyze(s, sport="bike", target_w=200, structure=struct)
    assert block.matched_to_prescription is True
    assert all(e.target_w == 300 for e in block.efforts)


# --- real fixture: robustness ---------------------------------------------------


@pytest.mark.skipif(not FIT_MTB_RACE.exists(), reason="no real MTB race .fit fixture")
def test_analyze_real_mtb_race_detects_sane_efforts():
    draft = parse_fit(FIT_MTB_RACE)
    block = ia.analyze(draft.series, sport="bike")
    assert block is not None
    assert block.detection_basis == "power"
    # An unstructured 4.5h race -- a robustness fixture, not a 2x12. Assert
    # only that the numbers are sane, per the build brief.
    assert 5 <= block.efforts_detected <= 60
    for e in block.efforts:
        assert 110 <= e.duration_s <= 1200
        assert 40 <= (e.avg_w or 0) <= 450
        assert e.verdict
    # At least one real terrain-confound flag fires on a real dirt-road ride.
    assert any(e.terrain_flag and "terrain" in e.terrain_flag for e in block.efforts)
    # Tightened decoupling resolves to a real number on this near-continuous race.
    assert block.decoupling_tightened_pct is not None
    assert block.decoupling_note and "working" in block.decoupling_note


@pytest.mark.skipif(not FIT_SWIM.exists(), reason="no real pool-swim .fit fixture")
def test_analyze_real_pool_swim_is_none():
    draft = parse_fit(FIT_SWIM)
    assert ia.analyze(draft.series, sport=draft.sport) is None
