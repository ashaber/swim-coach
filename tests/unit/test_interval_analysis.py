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


# --- synthetic series builders for the refinement-pass fixes --------------------------


def _concat(*parts: dict) -> dict:
    """Stitch flat-shaped {t_s, power_w, hr, grade} chunks onto one clock."""
    out: dict = {"t_s": [], "power_w": [], "hr": [], "grade": []}
    clock = 0.0
    for p in parts:
        for i in range(len(p["t_s"])):
            out["t_s"].append(clock)
            out["power_w"].append(p["power_w"][i])
            out["hr"].append(p["hr"][i])
            out["grade"].append(p["grade"][i])
            clock += 1
    return out


def _flat(power, seconds, *, hr=120, grade=0.0, jitter=0.0):
    import random

    rng = random.Random(int(power * 1000 + seconds))
    p = [
        (power + rng.uniform(-jitter, jitter)) if jitter else float(power)
        for _ in range(seconds)
    ]
    return {
        "t_s": list(range(seconds)),
        "power_w": p,
        "hr": [hr] * seconds,
        "grade": [grade] * seconds,
    }


def _ramp(p0, p1, seconds, *, hr=120, grade=0.0):
    return {
        "t_s": list(range(seconds)),
        "power_w": [p0 + (p1 - p0) * (i / max(1, seconds - 1)) for i in range(seconds)],
        "hr": [hr] * seconds,
        "grade": [grade] * seconds,
    }


def _thirty_thirty_set(*, on_w, off_w, reps, hr):
    parts = []
    for _ in range(reps):
        parts.append(_flat(on_w, 30, hr=hr))
        parts.append(_flat(off_w, 30, hr=hr))
    return _concat(*parts)


def _vo2_session(*, sets=6, reps=5, on_w=320.0, off_w=120.0):
    chunks = [_flat(100, 180, hr=110)]  # warm-up
    for s in range(sets):
        chunks.append(_thirty_thirty_set(on_w=on_w, off_w=off_w, reps=reps, hr=150 + s * 3))
        if s < sets - 1:
            chunks.append(_flat(100, 120, hr=125))  # between-set recovery
    chunks.append(_flat(100, 240, hr=120))  # cool-down
    return _concat(*chunks)


def _over_under_session(*, blocks=3, cycles=4, over_w=290.0, under_w=230.0):
    chunks = [_flat(110, 200, hr=115)]
    for b in range(blocks):
        cyc = []
        for _ in range(cycles):
            cyc.append(_flat(over_w, 90, hr=160 + b * 4))
            cyc.append(_flat(under_w, 90, hr=158 + b * 4))
        chunks.append(_concat(*cyc))
        if b < blocks - 1:
            chunks.append(_flat(100, 180, hr=125))
    chunks.append(_flat(105, 200, hr=118))
    return _concat(*chunks)


# --- fix 1: micro-interval detection + set clustering --------------------------------


def test_vo2_30_30_session_surfaces_as_rep_sets_not_zero_and_not_noise():
    s = _vo2_session(sets=6, reps=5)
    block = ia.analyze(s, sport="bike", target_w=312)
    assert block is not None
    assert block.efforts_detected == 6
    for e in block.efforts:
        assert e.sub_structure is not None
        assert e.sub_structure.pattern == "rep_set"
        assert e.sub_structure.n_reps == 5
        assert e.sub_structure.high_avg_w > e.sub_structure.low_avg_w
        assert 25 <= e.sub_structure.high_s <= 35


def test_a_single_sub_minute_surge_still_does_not_cluster():
    s = _concat(_flat(100, 200, hr=110), _flat(330, 40, hr=150), _flat(100, 200, hr=110))
    assert ia.detect_efforts(s, target_w=300) == []


def test_three_scattered_short_reps_are_below_the_set_floor():
    # 3 reps (< SET_MIN_REPS) 40s apart -> not a set, dropped.
    parts = [_flat(100, 120, hr=110)]
    for _ in range(3):
        parts += [_flat(320, 30, hr=150), _flat(100, 40, hr=120)]
    parts.append(_flat(100, 120, hr=110))
    assert ia.detect_efforts(_concat(*parts), target_w=310) == []


# --- fix 2: non-effort false-positive filter ----------------------------------------


def test_warmup_ramp_does_not_register_as_a_failed_effort():
    s = _concat(
        _ramp(90, 250, 360, hr=120),          # 6-min warm-up ramp, mean ~170
        _flat(100, 240, hr=120),
        _flat(250, 720, hr=155),              # real 12-min block
        _flat(100, 300, hr=125),
        _flat(250, 720, hr=160),              # real 12-min block
        _ramp(200, 70, 150, hr=120),          # cool-down ramp down
    )
    block = ia.analyze(s, sport="bike", target_w=250)
    assert block.efforts_detected == 2
    assert all(230 <= e.avg_w <= 270 for e in block.efforts)
    assert all("under target" not in e.verdict for e in block.efforts)


def test_sustained_blocks_below_but_near_target_still_detect():
    # 200W vs 240W target == 83% -- an attempt, must still be an effort.
    s = _concat(_flat(80, 120, hr=110), _flat(200, 720, hr=150), _flat(80, 120, hr=110))
    efforts = ia.detect_efforts(s, target_w=240)
    assert len(efforts) == 1


# --- fix 3: over/under sub-resolution ----------------------------------------------


def test_clean_over_under_blocks_resolve_into_over_and_under():
    s = _over_under_session(blocks=3, cycles=4, over_w=290, under_w=230)
    block = ia.analyze(s, sport="bike", target_w=260)
    ou = [e for e in block.efforts if e.sub_structure and e.sub_structure.pattern == "over_under"]
    assert len(ou) == 3
    for e in ou:
        sub = e.sub_structure
        assert sub.n_reps >= 3
        assert 275 <= sub.high_avg_w <= 305
        assert 215 <= sub.low_avg_w <= 245
        assert sub.time_in_high_pct and sub.time_in_low_pct


def test_irregular_by_feel_over_under_still_resolves():
    import random

    rng = random.Random(7)
    cyc = []
    for _ in range(5):
        cyc.append(_flat(285 + rng.uniform(-15, 15), rng.randint(70, 130), hr=160))
        cyc.append(_flat(225 + rng.uniform(-15, 15), rng.randint(70, 130), hr=158))
    s = _concat(_flat(110, 150, hr=115), _concat(*cyc), _flat(105, 150, hr=118))
    block = ia.analyze(s, sport="bike", target_w=255)
    ou = [e for e in block.efforts if e.sub_structure and e.sub_structure.pattern == "over_under"]
    assert ou, "an irregular feel-based over/under should still resolve"
    assert ou[0].sub_structure.high_avg_w > ou[0].sub_structure.low_avg_w + 30


def test_steady_threshold_block_is_not_mislabelled_over_under():
    s = _concat(_flat(80, 120, hr=110), _flat(250, 720, hr=155, jitter=18), _flat(80, 120, hr=110))
    block = ia.analyze(s, sport="bike", target_w=250)
    assert block.efforts_detected == 1
    assert block.efforts[0].sub_structure is None


# --- fix 4: decoupling n/a for all-interval rides ----------------------------------


def test_decoupling_is_none_for_an_all_interval_session():
    s = _vo2_session(sets=6, reps=5)
    block = ia.analyze(s, sport="bike")
    assert block.decoupling_tightened_pct is None
    assert "all-interval" in block.decoupling_note


def test_decoupling_survives_a_two_block_threshold_ride():
    s = _concat(
        _flat(120, 900, hr=125),             # long warm-up steady block
        _flat(255, 720, hr=150),
        _flat(120, 420, hr=135),
        _flat(255, 720, hr=158),
        _flat(120, 600, hr=132),             # long cool-down steady block
    )
    block = ia.analyze(s, sport="bike", target_w=255)
    assert block.decoupling_tightened_pct is not None
    assert "all-interval" not in (block.decoupling_note or "")


def test_decoupling_unaffected_on_a_long_steady_ride():
    s = _concat(_flat(185, 3600, hr=140))
    # nudge HR up over the ride so there's a real number to compute
    s["hr"] = [140 + int(12 * i / len(s["hr"])) for i in range(len(s["hr"]))]
    block = ia.analyze(s, sport="bike")
    assert block.decoupling_tightened_pct is not None


# --- fix 5: adaptive in-band tolerance -------------------------------------------------


def test_adaptive_band_is_tight_indoors_and_wider_outdoors():
    smooth = _flat(250, 1200, hr=150)
    rough = _flat(250, 1200, hr=150, jitter=45)
    assert ia._adaptive_in_band_frac(smooth) == ia.IN_BAND_FRAC
    assert ia._adaptive_in_band_frac(rough) > ia.IN_BAND_FRAC
    assert ia._adaptive_in_band_frac(rough) <= ia.IN_BAND_FRAC_MAX


def test_indoor_hint_forces_the_tight_band_on_a_rough_series():
    rough = _flat(250, 1200, hr=150, jitter=45)
    assert ia._adaptive_in_band_frac(rough, indoor=True) == ia.IN_BAND_FRAC


def test_analyze_widens_time_in_band_for_a_rough_ride():
    # same effort, judged with a wide band because the rest of the ride is rough
    rough_ride = _concat(
        _flat(150, 300, hr=120, jitter=50),
        _flat(250, 720, hr=155, jitter=35),
        _flat(150, 300, hr=120, jitter=50),
    )
    smooth_ride = _concat(
        _flat(150, 300, hr=120),
        _flat(250, 720, hr=155, jitter=35),
        _flat(150, 300, hr=120),
    )
    rough_block = ia.analyze(rough_ride, sport="bike", target_w=250)
    smooth_block = ia.analyze(smooth_ride, sport="bike", target_w=250)
    assert rough_block.efforts[0].time_in_band_pct > smooth_block.efforts[0].time_in_band_pct
