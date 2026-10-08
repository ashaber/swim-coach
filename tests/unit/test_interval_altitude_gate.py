"""Endurance-ride all-interval gate + ride-level altitude note (real 10/6, 10/7, 9/29 rides)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swim_coach import interval_analysis as ia
from swim_coach.interval_analysis import analyze

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text())


def _run(name: str, **kw):
    d = _load(name)
    p = d["athlete_profile"]
    return analyze(
        d["series"],
        sport="bike",
        home_elevation_m=p.get("home_elevation_m"),
        ftp_watts=p.get("ftp_watts"),
        **kw,
    )


def _rolling_series(low: float, high: float, n_blocks: int = 8, block_s: int = 120, alt: float = 900.0) -> dict:
    """Alternating low/high power blocks, 1 Hz, flat altitude."""
    power: list[float] = []
    for i in range(n_blocks * 2):
        power += [high if i % 2 else low] * block_s
    n = len(power)
    return {
        "t_s": list(range(n)),
        "power_w": power,
        "hr": [140.0] * n,
        "altitude_m": [alt] * n,
    }


# --- Bug 1: all-interval gate -------------------------------------------------------


def test_endurance_ride_gets_real_decoupling_with_ftp_gate():
    r = _run("ride_2026_10_07_endurance_altitude.json")
    assert r.decoupling_tightened_pct is not None
    assert "all-interval" not in (r.decoupling_note or "")


def test_endurance_ride_gets_real_decoupling_with_planned_zone():
    d = _load("ride_2026_10_07_endurance_altitude.json")
    r = analyze(d["series"], sport="bike", home_elevation_m=823.0, planned_zone="Z2")
    assert r.decoupling_tightened_pct is not None


def test_over_unders_and_vo2_unchanged():
    ou = _run("ride_2026_10_06_over_unders_altitude.json")
    assert ou.decoupling_tightened_pct == 10.3
    vo2 = _run("ride_2026_09_29_vo2_40_20.json")
    assert vo2.decoupling_tightened_pct == 20.8


def test_ftp_gate_ignores_sub_tempo_efforts():
    # 130 W vs 190 W blocks at FTP 278: highs are 68% FTP (below Z3 lower bound).
    s = _rolling_series(130, 190)
    assert ia._is_all_interval(s) is True  # relative threshold alone calls it all-interval
    assert ia._is_all_interval(s, ftp_watts=278.0) is False


def test_ftp_gate_keeps_real_tempo_plus_intervals_all_interval():
    s = _rolling_series(130, 300)
    assert ia._is_all_interval(s, ftp_watts=278.0) is True


def test_planned_endurance_zone_is_never_all_interval():
    s = _rolling_series(130, 300)
    assert ia._is_all_interval(s, ftp_watts=278.0, planned_zone="Z2") is False
    assert ia._is_all_interval(s, ftp_watts=278.0, planned_zone="z1") is False
    assert ia._is_all_interval(s, ftp_watts=278.0, planned_zone="Z4") is True


def test_z3_bound_comes_from_zone_table():
    from swim_coach.zones import bike_zone_table

    assert ia._tempo_floor_w(278.0) == bike_zone_table(278.0)["Z3"]["watts_lo"]


# --- Bug 2: altitude note -----------------------------------------------------------


def test_ride_altitude_note_in_500_to_1000_band():
    r = _run("ride_2026_10_07_endurance_altitude.json")
    assert r.ride_altitude_m is not None and 1600 < r.ride_altitude_m < 1700
    assert 500 <= r.ride_altitude_gain_m < 1000
    assert r.ride_altitude_decrement_pct == pytest.approx(r.ride_altitude_gain_m / 1000 * 6.0, abs=0.05)
    note = r.ride_altitude_note
    assert "home" in note and "823" in note and "not adjusted" in note.lower()
    assert "adjusts at +1000 m" in note
    for e in r.efforts:
        assert e.altitude_decrement_pct is not None
        assert "not adjusted" in e.altitude_context.lower()
        assert e.altitude_adjusted_target_w is None
        assert e.cleared_altitude_adjusted_target is None


def test_no_note_below_500_m():
    s = _rolling_series(130, 300, alt=1100.0)
    r = analyze(s, sport="bike", home_elevation_m=823.0, ftp_watts=278.0)
    assert r.ride_altitude_note is None
    assert r.ride_altitude_m == pytest.approx(1100.0, abs=0.1)
    assert all(e.altitude_context is None for e in r.efforts)


def test_note_above_1000_m_says_targets_adjusted():
    s = _rolling_series(130, 300, alt=2000.0)
    r = analyze(s, sport="bike", home_elevation_m=823.0, ftp_watts=278.0, target_w=250.0)
    assert "targets adjusted" in r.ride_altitude_note.lower()
    assert any(e.altitude_adjusted_target_w is not None for e in r.efforts)


def test_ride_altitude_fields_absent_without_altitude_channel():
    s = _rolling_series(130, 300)
    del s["altitude_m"]
    r = analyze(s, sport="bike", ftp_watts=278.0)
    assert r.ride_altitude_m is None and r.ride_altitude_note is None


# --- intensity-change confound note -------------------------------------------------


def test_decoupling_note_flags_intensity_change_on_1007_ride():
    r = _run("ride_2026_10_07_endurance_altitude.json")
    assert "power fell" in r.decoupling_note
    assert "intensity change" in r.decoupling_note


def test_steady_ride_has_no_intensity_change_note():
    n = 1200
    s = {"t_s": list(range(n)), "power_w": [200.0] * n, "hr": [140.0] * 600 + [143.0] * 600}
    r = analyze(s, sport="bike", ftp_watts=278.0)
    assert r.decoupling_tightened_pct is not None
    assert "intensity change" not in r.decoupling_note


def test_rising_power_also_flagged():
    n = 1200
    s = {"t_s": list(range(n)), "power_w": [180.0] * 600 + [220.0] * 600, "hr": [140.0] * n}
    r = analyze(s, sport="bike", ftp_watts=278.0, planned_zone="Z2")
    assert "power rose" in r.decoupling_note
