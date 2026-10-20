"""Course sectors for the race view: one lap model, passes + efficiency, splits, timing noise.

The course is the synthetic one in `synthetic_course` (made-up coordinates, never real GPS).
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

import synthetic_course as sc
from swim_coach.canonical_laps import build_canonical_laps
from swim_coach.course_sectors import build_course_sectors
from swim_coach.models import Workout, WorkoutLap

PTS = sc.loop_xy(sc.RECT_WITH_S_BEND)
SPEED = sc.loop_length(PTS) / round(sc.loop_length(PTS) / 6.0)  # exactly one whole number of seconds per lap
LOOP_M = sc.loop_length(PTS)
LAP_S = round(LOOP_M / SPEED)


def _series(n_laps: int = 5, slow: dict | None = None) -> dict:
    series = sc.ride(PTS, [SPEED] * n_laps, slow=slow)
    n = len(series["t_s"])
    lap_pos = [d % LOOP_M for d in series["dist_m"]]
    series["power_w"] = [200.0 + 40.0 * ((t // LAP_S) % 3) for t in series["t_s"]]
    series["flow"] = [8.0 if 150 <= p < 175 else 0.5 for p in lap_pos]
    series["altitude_m"] = [-5.0 * min(max((p - 100.0) / 40.0, 0.0), 1.0) for p in lap_pos]  # a 5 m drop inside S1
    assert len(series["power_w"]) == n
    return series


def _workout(n_laps: int, series: dict) -> Workout:
    """Device laps pressed at the first sample past each lap-mark crossing (a slow lap is a longer lap)."""
    starts = [next(t for t, d in zip(series["t_s"], series["dist_m"]) if d >= i * LOOP_M - 1e-6) for i in range(n_laps)]
    ends = [*starts[1:], series["t_s"][-1] + 1]
    laps = [
        WorkoutLap(index=i + 1, start_offset_s=float(a), duration_s=float(b - a), distance_m=LOOP_M, avg_power_w=250.0)
        for i, (a, b) in enumerate(zip(starts, ends))
    ]
    return Workout(id=uuid.uuid4(), athlete_id=uuid.uuid4(), date=date(2026, 10, 17), sport="bike", source="fit",
                   distance_m=round(LOOP_M * n_laps), duration_min=ends[-1] / 60, laps=laps)


def _build(n_laps: int = 5, **kw):
    series = _series(n_laps, kw.pop("slow", None))
    laps = build_canonical_laps(_workout(n_laps, series).laps, series)
    return laps, build_course_sectors(laps, series, **kw)


def test_lap_times_are_the_canonical_lap_durations() -> None:
    """One lap model: the sector lap's time is the canonical lap's duration (it used to be one sample short)."""
    laps, cs = _build()
    comparable = {l.n: l.duration_s for l in laps if l.comparable}
    assert {l.lap: l.time_s for l in cs.laps} == pytest.approx(comparable)
    for lap in cs.laps:
        assert sum(lap.sector_times_s) == pytest.approx(lap.time_s, abs=0.02)


def test_best_lap_and_ideal_gap_come_from_the_canonical_lap_times() -> None:
    laps, cs = _build(slow={i: (120.0, 140.0, 3.0) for i in (1, 2, 3, 4)})
    durations = {l.n: l.duration_s for l in laps if l.comparable}
    assert cs.best_lap == min(durations, key=durations.get)
    assert cs.ideal_gap_s == pytest.approx(round(durations[cs.best_lap] - cs.ideal_lap_s, 1), abs=0.11)


def test_every_section_has_one_pass_per_lap_and_corners_get_efficiency() -> None:
    _, cs = _build()
    for row in cs.sectors:
        assert len(row.passes) == len(cs.laps)
        assert [p.lap for p in row.passes] == [l.lap for l in cs.laps]
        if row.kind == "corners":
            assert row.efficiency_applies is True and row.mean_extra_w is not None
            assert all(p.extra_w is not None and p.extra_w >= 0 for p in row.passes)


def test_a_flat_straight_has_no_efficiency_and_a_descent_straight_does() -> None:
    _, cs = _build()
    first = cs.sectors[0]
    assert first.kind == "straight" and first.terrain == "descent" and first.efficiency_applies is True
    flat = next(s for s in cs.sectors if s.kind == "straight" and s.terrain == "flat")
    assert flat.efficiency_applies is False and flat.mean_extra_w is None
    assert all(p.extra_w is None for p in flat.passes)


def test_the_slow_stretch_is_a_significant_loss_and_steady_sections_are_not() -> None:
    _, cs = _build(slow={i: (120.0, 140.0, 3.0) for i in (1, 2, 3, 4)})
    assert cs.top_loss_sectors[0] == 1 and cs.sectors[0].loss_significant is True
    assert all(cs.sectors[n - 1].loss_significant for n in cs.top_loss_sectors)
    quiet = [s for s in cs.sectors[1:] if not s.loss_significant]
    assert quiet and all(s.noise_floor_s is not None and s.sigma_s is not None for s in cs.sectors)


def test_losses_inside_the_timing_noise_are_not_top_loss_sectors() -> None:
    _, cs = _build()  # identical laps: whatever loss there is, is noise
    assert cs.top_loss_sectors == []
    assert cs.edge_noise_s is not None and cs.ideal_gap_noise_s is not None
    assert cs.ideal_gap_beyond_noise_s == pytest.approx(max(0.0, cs.ideal_gap_s - cs.ideal_gap_noise_s), abs=0.06)


def test_splitting_a_section_recomputes_the_table() -> None:
    _, base = _build()
    _, split = _build(section_splits={"C1": 3, "NOPE": 2})
    assert split.splits == {"C1": 3}
    labels = [s.label for s in split.sectors]
    assert labels[:5] == ["S1", "C1a", "C1b", "C1c", "S2"]
    assert split.sector_count == base.sector_count + 2
    parts = [s for s in split.sectors if s.split_of == "C1"]
    assert len(parts) == 3
    c1 = next(s for s in base.sectors if s.label == "C1")
    assert sum(p.length_m for p in parts) == pytest.approx(c1.length_m, abs=0.3)
    for lap_i, lap in enumerate(base.laps):
        c1_time = lap.sector_times_s[1]
        assert sum(split.laps[lap_i].sector_times_s[1:4]) == pytest.approx(c1_time, abs=0.02)
    assert [t.name for t in split.track.sectors][:5] == labels[:5]


def test_splits_outside_two_to_four_parts_are_ignored() -> None:
    _, cs = _build(section_splits={"C1": 9, "S1": 1})
    assert cs.splits == {} and cs.sector_count == _build()[1].sector_count
