"""Course-feature sections: straights vs corner sequences found on the best lap, aligned across laps by position."""

from __future__ import annotations

import uuid
from datetime import date

import pytest

import synthetic_course as sc
from swim_coach.course_features import align_edges, project_xy, segment_course
from swim_coach.course_sectors import SECTOR_COUNT, build_course_sectors
from swim_coach.models import Workout, WorkoutLap

PTS = sc.loop_xy(sc.RECT_WITH_S_BEND)
SPEED = 6.0
EXPECTED_KINDS = ["straight", "corners"] * 5 + ["straight"]  # S C S C S C(S-bend) S C S C S


def _xy_t(series: dict) -> tuple[list[tuple[float, float]], list[float]]:
    return project_xy(series["lat"], series["lng"], range(len(series["t_s"])), series["lat"][0], series["lng"][0]), series["t_s"]


def _first_lap(series: dict) -> dict:
    n = int(sc.loop_length(PTS) / SPEED) + 1
    return {k: v[:n] for k, v in series.items()}


def test_rectangle_with_s_bend_alternates_straights_and_corner_sequences():
    lap = _first_lap(sc.ride(PTS, [SPEED]))
    xy, t = _xy_t(lap)
    sections = segment_course(xy, t, None)
    assert sections is not None
    kinds = [s.kind for s in sections]
    assert kinds == EXPECTED_KINDS
    assert len(sections) == 11
    assert sections[0].start_i == 0 and sections[-1].end_i == len(xy) - 1
    assert all(a.end_i == b.start_i for a, b in zip(sections, sections[1:]))  # contiguous
    assert [s.label for s in sections][:4] == ["S1", "C1", "S2", "C2"]


def test_the_s_bend_is_one_corner_sequence():
    lap = _first_lap(sc.ride(PTS, [SPEED]))
    xy, t = _xy_t(lap)
    corners = [s for s in segment_course(xy, t, None) if s.kind == "corners"]
    lengths = sorted(c.length_m for c in corners)
    assert lengths[-1] > 1.5 * lengths[0]  # the S-bend (two bends + link) is longer than a plain corner


def test_flow_alone_marks_cornering():
    lap = _first_lap(sc.ride(PTS, [SPEED]))
    xy, t = _xy_t(lap)
    flow = [0.0] * len(xy)
    for i in range(80, 90):
        flow[i] = 8.0
    plain = segment_course(xy, t, None)
    with_flow = segment_course(xy, t, flow)
    assert with_flow is not None and plain is not None
    assert len(with_flow) >= len(plain)


def test_a_straight_line_has_no_course_features():
    line = [(float(i) * 6.0, 0.0) for i in range(100)]
    assert segment_course(line, [float(i) for i in range(100)], None) is None


def test_section_count_is_capped():
    # a dense chicane: alternating tight turns every 40 m
    spec = []
    for _ in range(30):
        spec += [("line", 40.0, 0.0), ("arc", 8.0, 90.0), ("line", 40.0, 0.0), ("arc", 8.0, -90.0)]
    pts = sc.loop_xy(spec)
    series = sc.ride(pts, [SPEED])
    xy, t = _xy_t(series)
    sections = segment_course(xy, t, None)
    assert sections is None or 4 <= len(sections) <= 24


# --- alignment ----------------------------------------------------------------------------------


def test_edges_align_by_position_not_time_or_distance():
    fast = _first_lap(sc.ride(PTS, [SPEED]))
    slow = sc.ride(PTS, [4.5])
    slow = {k: v[: int(sc.loop_length(PTS) / 4.5) + 1] for k, v in slow.items()}
    xy, t = _xy_t(fast)
    sections = segment_course(xy, t, None)
    bounds = [s.start_i for s in sections] + [sections[-1].end_i]
    slow_xy = project_xy(slow["lat"], slow["lng"], range(len(slow["t_s"])), fast["lat"][0], fast["lng"][0])
    edges = align_edges(xy, bounds, slow_xy, slow["t_s"])
    assert edges is not None and len(edges) == len(bounds)
    fast_edges = [t[b] for b in bounds]
    ratio = 6.0 / 4.5
    for fe, se in zip(fast_edges, edges):
        assert se == pytest.approx(fe * ratio, abs=2.5)
    assert edges == sorted(edges)


def test_edges_reject_a_lap_that_never_reaches_the_end():
    fast = _first_lap(sc.ride(PTS, [SPEED]))
    xy, t = _xy_t(fast)
    sections = segment_course(xy, t, None)
    bounds = [s.start_i for s in sections] + [sections[-1].end_i]
    half = xy[: len(xy) // 3]
    assert align_edges(xy, bounds, half, t[: len(half)]) is None


# --- through build_course_sectors ---------------------------------------------------------------


def _workout(series: dict, lap_len_s: float, n: int) -> Workout:
    laps = [
        WorkoutLap(index=i + 1, start_offset_s=i * lap_len_s, duration_s=lap_len_s, distance_m=sc.loop_length(PTS), avg_power_w=250.0)
        for i in range(n)
    ]
    return Workout(id=uuid.uuid4(), athlete_id=uuid.uuid4(), date=date(2026, 10, 17), sport="bike", source="fit",
                   distance_m=sc.loop_length(PTS) * n, duration_min=n * lap_len_s / 60, laps=laps)


def _three_laps(length_scale: float = 1.0, slow: dict | None = None) -> tuple[Workout, dict]:
    loop_s = sc.loop_length(PTS) / SPEED
    # each lap is exactly `lap_len` seconds long: pad speeds so laps end on the lap boundary
    series = sc.ride(PTS, [SPEED] * 3, slow=slow, length_scale=length_scale)
    lap_len = round(loop_s)
    return _workout(series, float(lap_len), 3), series


def test_build_uses_course_sections_when_the_course_has_features():
    workout, series = _three_laps()
    cs = build_course_sectors(workout, series)
    assert cs is not None and cs.sector_count == 11 != SECTOR_COUNT
    assert [s.kind for s in cs.sectors] == EXPECTED_KINDS
    assert [s.label for s in cs.sectors][:3] == ["S1", "C1", "S2"]
    assert all(len(lap.sector_times_s) == 11 for lap in cs.laps)
    assert cs.track is not None and len(cs.track.sectors) == 11
    assert [t.name for t in cs.track.sectors][:2] == ["S1", "C1"]
    assert all(s.length_m and s.length_m > 0 for s in cs.sectors)


def test_the_slow_stretch_lands_in_the_matching_section():
    # lap 3 rides 120-140 m of the lap at 3 m/s: that is inside the first long straight (S1)
    workout, series = _three_laps(slow={2: (120.0, 140.0, 3.0)})
    cs = build_course_sectors(workout, series)
    assert cs.top_loss_sectors[0] == 1
    assert cs.sectors[0].kind == "straight" and cs.sectors[0].total_loss_s > 3


def test_odometer_scaling_does_not_move_the_sections():
    base = build_course_sectors(*_three_laps())
    for scale in (0.95, 1.05):
        workout, series = _three_laps(length_scale=scale)
        cs = build_course_sectors(workout, series)
        assert cs.sector_count == base.sector_count
        assert [s.kind for s in cs.sectors] == [s.kind for s in base.sectors]
        for a, b in zip(cs.laps[0].sector_times_s, base.laps[0].sector_times_s):
            assert a == pytest.approx(b, abs=2.5)


def test_corner_sections_carry_speed_and_straights_do_not_need_them():
    workout, series = _three_laps()
    cs = build_course_sectors(workout, series)
    corner = next(s for s in cs.sectors if s.kind == "corners")
    assert corner.entry_speed_mps == pytest.approx(SPEED, abs=0.1) and corner.min_speed_mps is not None


def test_without_gps_the_equal_distance_sectors_remain():
    workout, series = _three_laps()
    series = {k: v for k, v in series.items() if k not in ("lat", "lng")}
    cs = build_course_sectors(workout, series)
    assert cs.sector_count == SECTOR_COUNT and all(s.kind is None for s in cs.sectors)
