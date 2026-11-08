"""ERG ramp trimming + zone-based rep rating, on a SYNTHETIC trainer ride that reproduces the
2026-11-07 3 x 8 x 40 s / 20 s VO2 session (Hammer H3 in ERG via MyWhoosh).

The trainer ramps ~5 s into every step and takes ~4 s to come down, so whole-lap averages
read ~300 W against a steady ~315 W. Before the fix the ride scored 0 of 24 reps in band.
"""

from __future__ import annotations

import math

import pytest

from swim_coach.interval_analysis import (
    ERG_RAMP_TRIM_S,
    analyze,
    ramp_trim_s,
)
from swim_coach.models import WorkoutLap, WorkoutStructure
from swim_coach.rep_rating import classify_rep, prescribed_zone

FTP = 278.0
BAND = (320.0, 335.0)
REST_W = 139.0
# fraction of the way from the previous level to the new one, per second after a step starts
RAMP_UP = [0.0, 0.05, 0.30, 0.55, 0.80]
RAMP_DOWN_REMAINING = [1.0, 0.8, 0.5, 0.35, 0.15]


def _step(kind: str, dur: float, w: float | None, *, role: str, low=None, high=None) -> dict:
    return {
        "schema_version": 1, "kind": "step", "label": kind, "role": role,
        "duration_kind": "time_s", "duration_value": dur,
        "target": {"schema_version": 1, "basis": "power_w", "zone": None, "low": low, "high": high},
        "modality": "bike",
    }


def _plan(work_w) -> tuple[list[tuple[float, float, dict]], dict]:
    """Timeline [(duration, erg_target_w, step-dict)] and the matching structure dict.
    `work_w(round_n, rep_n)` is the steady watts the trainer is told to hold on a work rep."""
    timeline: list[tuple[float, float, dict]] = []
    items: list[dict] = []

    def add(dur, w, step):
        timeline.append((dur, w, step))

    warm = _step("5m warm", 300, 150, role="warmup", low=150, high=150)
    add(300, 150, warm)
    items.append(warm)
    for rnd in range(1, 4):
        reps = []
        for rep in range(1, 9):
            on = _step("40s on", 40, None, role="interval", low=BAND[0], high=BAND[1])
            off = _step("20s off", 20, None, role="recovery", low=REST_W, high=REST_W)
            add(40, work_w(rnd, rep), on)
            add(20, REST_W, off)
            reps += [on, off]
        items.append({"schema_version": 1, "kind": "repeat", "repeat_mode": "count", "count": 8, "steps": reps[:2]})
        if rnd < 3:
            gap = _step("5m easy", 300, REST_W, role="steady", low=REST_W, high=REST_W)
            add(300, REST_W, gap)
            items.append(gap)
    cool = _step("2m cool", 120, REST_W, role="cooldown", low=REST_W, high=REST_W)
    add(120, REST_W, cool)
    items.append(cool)
    return timeline, {"schema_version": 1, "items": items}


def _ride(work_w=lambda r, k: 315.0):
    timeline, structure = _plan(work_w)
    power: list[float] = []
    laps: list[WorkoutLap] = []
    prev = 100.0
    for i, (dur, target, _step_d) in enumerate(timeline):
        laps_start = len(power)
        for s in range(int(dur)):
            noise = 2.0 * math.sin(len(power) * 1.7)
            if s < 5 and target > prev:
                w = prev + (target - prev) * RAMP_UP[s]
            elif s < 5 and target < prev:
                w = target + (prev - target) * RAMP_DOWN_REMAINING[s]
            else:
                w = target
            power.append(round(w + noise))
        seg = power[laps_start:]
        laps.append(WorkoutLap(index=i, start_offset_s=float(laps_start), duration_s=float(dur),
                               avg_power_w=round(sum(seg) / len(seg))))
        prev = target
    series = {
        "t_s": [float(i) for i in range(len(power))],
        "power_w": power,
        "hr": [150] * len(power),
    }
    return series, laps, WorkoutStructure.model_validate(structure)


def _run(work_w=lambda r, k: 315.0, indoor: bool | None = True):
    series, laps, structure = _ride(work_w)
    return analyze(series, sport="bike", structure=structure, laps=laps, ftp_watts=FTP,
                   indoor=indoor, planned_zone="Z5")


# --- the failure this fixes ---------------------------------------------------------

def test_without_trim_the_ride_reads_as_total_failure():
    out = _run(indoor=False)
    assert out.reps_completed == 24
    assert out.reps_in_band_pct == 0.0
    work = [e for e in out.efforts]
    assert all(e.ramp_trim_s is None for e in work)
    assert 292 <= sum(e.avg_w for e in work) / 24 <= 305  # whole-lap average, ramp included


def test_indoor_trim_scores_the_steady_portion():
    out = _run(indoor=True)
    for e in out.efforts:
        assert e.ramp_trim_s == ERG_RAMP_TRIM_S
        assert 312 <= e.avg_w <= 318
        assert 292 <= e.raw_avg_w <= 305  # the untrimmed lap average is still reported
        assert e.duration_s == 40.0  # the rep itself, not the trimmed window
        assert e.rep_class == "below_band_in_zone"
        assert e.landed_zone == "Z5"


def test_indoor_is_inferred_from_smooth_power_when_not_told():
    out = _run(indoor=None)
    assert out.efforts[0].ramp_trim_s == ERG_RAMP_TRIM_S


def test_session_rating_summary_for_a_uniformly_under_band_ride():
    out = _run()
    r = out.rep_ratings
    assert (r.rated, r.below_band_in_zone, r.in_band, r.dropped_zone, r.above_band) == (24, 24, 0, 0, 0)
    assert r.held_zone_pct == 100.0
    assert r.summary.startswith("24 of 24 reps held VO2 (Z5)")
    assert "320-335 W" in r.summary
    assert out.reps_in_band_pct == 0.0  # the in-band call is kept alongside


def test_rounds_are_the_three_repeat_blocks():
    out = _run()
    assert [rd.reps_prescribed for rd in out.rounds] == [8, 8, 8]
    assert [rd.reps_below_band_in_zone for rd in out.rounds] == [8, 8, 8]


def test_reps_at_the_band_are_in_band():
    out = _run(lambda r, k: 328.0)
    assert {e.rep_class for e in out.efforts} == {"in_band"}
    assert out.reps_in_band_pct == 100.0
    assert out.rep_ratings.in_band == 24


def test_reps_dropped_to_threshold_are_a_different_stimulus():
    out = _run(lambda r, k: 270.0 if r == 3 else 328.0)  # 97% FTP = Z4
    dropped = [e for e in out.efforts if e.rep_class == "dropped_zone"]
    assert len(dropped) == 8 and {e.round_n for e in dropped} == {3}
    assert all(e.landed_zone == "Z4" for e in dropped)
    r = out.rep_ratings
    assert (r.in_band, r.dropped_zone, r.held_zone_pct) == (16, 8, pytest.approx(66.7, abs=0.1))
    assert "8 dropped to threshold (Z4)" in r.summary and "round 3" in r.summary
    assert out.rounds[2].reps_dropped_zone == 8


def test_reps_above_the_band():
    out = _run(lambda r, k: 350.0)
    assert {e.rep_class for e in out.efforts} == {"above_band"}


# --- trim helper --------------------------------------------------------------------

def test_trim_only_indoors_and_only_when_the_rep_is_long_enough():
    assert ramp_trim_s(40.0, indoor=True) == ERG_RAMP_TRIM_S
    assert ramp_trim_s(2 * ERG_RAMP_TRIM_S, indoor=True) == ERG_RAMP_TRIM_S
    assert ramp_trim_s(2 * ERG_RAMP_TRIM_S - 1, indoor=True) == 0.0
    assert ramp_trim_s(40.0, indoor=False) == 0.0


# --- classification -----------------------------------------------------------------

def test_prescribed_zone_comes_from_the_rep_or_the_band_midpoint():
    assert prescribed_zone("Z5", None, None, FTP) == "Z5"
    assert prescribed_zone(None, 320.0, 335.0, FTP) == "Z5"  # midpoint 327.5 W = 118% FTP
    assert prescribed_zone(None, None, None, FTP) is None
    assert prescribed_zone(None, 320.0, 335.0, None) is None


def test_ninety_percent_of_target_lands_by_the_zone_boundary_not_a_fixed_pct():
    # 90% of 327.5 W = 295 W = 106% FTP: still Z5. 285 W = 102.5% FTP: Z4 (boundary 105% = 291.9 W).
    assert classify_rep(295.0, low_w=320, high_w=335, zone=None, ftp_watts=FTP) == ("below_band_in_zone", "Z5")
    assert classify_rep(285.0, low_w=320, high_w=335, zone=None, ftp_watts=FTP) == ("dropped_zone", "Z4")
    assert classify_rep(325.0, low_w=320, high_w=335, zone=None, ftp_watts=FTP) == ("in_band", "Z5")
    assert classify_rep(340.0, low_w=320, high_w=335, zone=None, ftp_watts=FTP) == ("above_band", "Z6")  # Z5 tops out at 120% FTP = 333.6 W


def test_no_band_or_no_ftp_means_no_rating():
    assert classify_rep(300.0, low_w=None, high_w=None, zone=None, ftp_watts=FTP) is None
    assert classify_rep(300.0, low_w=320, high_w=335, zone=None, ftp_watts=None) is None
