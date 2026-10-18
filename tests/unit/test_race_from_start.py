"""A warm-up and a race recorded in ONE activity: everything race-level is measured from the
race start; the warm-up is summarised apart (incident: Andrew's 2026-10-17 CX race)."""

from __future__ import annotations

import pytest

from swim_coach.bike_coach_view import COURSE_SECTORS_COACH_NOTE, course_sectors_coach_view
from swim_coach.interval_analysis import _laps_from
from swim_coach.models import WorkoutLap
from swim_coach.race_phases import split_race_phases
from swim_coach.race_start import analyze_race_start

FTP = 250.0
WARMUP_S = 900
WAIT_S = 120
RACE_START_S = WARMUP_S + WAIT_S
RACE_S = 1200


def _series() -> dict:
    """1 Hz, no GPS: 15 min warm-up at 150 W with two 600 W openers (each followed by easy
    riding), 2 min stationary on the line, then a race: 10 s at 800 W, then 250 W."""
    power: list[float] = []
    for i in range(WARMUP_S):
        power.append(600.0 if i in range(300, 306) or i in range(600, 606) else 100.0 if i > 300 else 150.0)
    power += [0.0] * WAIT_S
    power += [800.0] * 10 + [250.0] * (RACE_S - 10)
    return {"t_s": [float(i) for i in range(len(power))], "power_w": power}


def test_race_start_is_found_and_warmup_is_summarised_separately() -> None:
    rs = analyze_race_start(_series(), ftp_watts=FTP)
    assert rs is not None and rs.source == "detected"
    assert rs.start_s == pytest.approx(RACE_START_S, abs=1)
    assert rs.warmup is not None
    assert rs.warmup.duration_s == pytest.approx(RACE_START_S, abs=2)
    assert rs.warmup.openers == 2
    assert rs.warmup.avg_w < 150


def test_race_np_excludes_the_warmup() -> None:
    rs = analyze_race_start(_series(), ftp_watts=FTP)
    assert rs is not None
    # Race = a 10 s burst then steady 250 W: NP lands just above 250, nowhere near warm-up levels.
    assert 250 <= rs.race_np_w <= 275
    assert rs.first_5min_np_w is not None and rs.first_5min_np_w < 300


def test_override_wins_over_detection() -> None:
    rs = analyze_race_start(_series(), ftp_watts=FTP, start_s_override=RACE_START_S + 60)
    assert rs is not None
    assert rs.source == "override"
    assert rs.start_s == pytest.approx(RACE_START_S + 60, abs=1)
    assert rs.race_np_w == 250  # past the burst: steady 250 W only


def test_override_before_any_data_falls_back_to_detection() -> None:
    rs = analyze_race_start(_series(), ftp_watts=FTP, start_s_override=10_000)
    assert rs is not None and rs.source == "detected"


def test_phases_start_at_the_race_start_not_at_zero() -> None:
    series = _series()
    phases = split_race_phases(series, race_start_s=float(RACE_START_S))
    assert phases[0].name == "start" and phases[0].start_s == RACE_START_S
    main = [p for p in phases if p.name.startswith("phase_")]
    assert len(main) == 3
    nps = [p.normalized_power_w for p in main]
    assert max(nps) - min(nps) < 5  # an even 250 W race reads as even, not "built +34%"
    from_zero = split_race_phases(series)
    assert from_zero[0].start_s == 0.0  # no race start: unchanged behaviour


def test_device_laps_ending_before_the_start_are_not_race_laps() -> None:
    laps = [
        WorkoutLap(index=0, start_offset_s=0.0, duration_s=600.0),
        WorkoutLap(index=1, start_offset_s=600.0, duration_s=420.0),  # ends exactly at the start
        WorkoutLap(index=2, start_offset_s=1020.0, duration_s=300.0),
        WorkoutLap(index=3, duration_s=300.0),  # no offset: cannot be placed, kept
    ]
    kept = _laps_from(laps, float(RACE_START_S))
    assert [l.index for l in kept] == [2, 3]
    assert _laps_from(laps, None) == laps


def test_sector_flow_stays_in_the_coach_view_labelled_approximate() -> None:
    cs = {
        "fade": {"time_change_pct": 1.0},
        "sector_count": 8,
        "laps": [{"lap": 1, "time_s": 300.0, "time_vs_best_s": 0, "avg_flow": 3.2}],
        "sectors": [
            {"sector": n, "total_loss_s": 5.0 - n * 0.1, "mean_loss_s": 1.0, "best_time_s": 30.0,
             "spread_s": 1.0, "flow_vs_best": 0.5}
            for n in range(1, 6)
        ],
        "top_loss_sectors": [1, 2, 3, 4, 5],
    }
    view = course_sectors_coach_view(cs)
    assert len(view["top_loss_sectors"]) == 3
    assert all("flow" in line for line in view["top_loss_sectors"])
    assert "flow 3.2" in view["laps"][0]
    assert "approximate" in COURSE_SECTORS_COACH_NOTE and "same sector" in COURSE_SECTORS_COACH_NOTE
