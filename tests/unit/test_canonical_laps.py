"""One canonical lap derivation: every lap-based calculation reads the same laps."""

from __future__ import annotations

import pytest
from canonical_laps_fixture import CROSSINGS, END_S, RACE_START_S, race_device_laps, race_series, race_workout

from swim_coach.analysis import AnalysisContext
from swim_coach.canonical_laps import build_canonical_laps
from swim_coach.course_sectors import build_course_sectors
from swim_coach.gps_laps import analyze_laps, detect_gps_laps, mark_crossings
from swim_coach.lap_normalise import start_point
from swim_coach.models import WorkoutLap
from swim_coach.mtb_dynamics import build_mtb_dynamics
from swim_coach.race_efficiency import build_race_efficiency


@pytest.fixture(scope="module")
def series() -> dict:
    return race_series()


@pytest.fixture(scope="module")
def laps(series):
    return build_canonical_laps(race_device_laps(series), series, race_start_s=RACE_START_S)


def test_race_laps_start_from_the_gun_and_drop_the_warmup_and_line_wait(laps):
    assert laps[0].start_s == RACE_START_S
    assert laps[0].source == "split_at_start"
    assert laps[0].start_lap and not laps[0].comparable
    assert laps[0].end_s == CROSSINGS[0]
    assert laps[0].duration_s == pytest.approx(150.0)


def test_double_trigger_fragments_are_merged_and_the_missed_lap_is_filled(laps):
    assert [(round(l.start_s), round(l.end_s), l.source) for l in laps] == [
        (480, 630, "split_at_start"),
        (630, 830, "merged"),
        (830, 1030, "gps_filled"),
        (1030, 1230, "gps_filled"),
        (1230, 1430, "merged"),
        (1430, 1490, "device"),
    ]
    assert [l.n for l in laps] == [1, 2, 3, 4, 5, 6]


def test_only_full_laps_from_the_mark_are_comparable(laps):
    assert [l.comparable for l in laps] == [False, True, True, True, True, False]
    assert [l.start_lap for l in laps] == [True, False, False, False, False, False]


def test_start_lap_power_excludes_the_wait_on_the_line(laps):
    assert laps[0].avg_power_w == pytest.approx(250.0, abs=1)


def test_lap_distances_come_from_the_recording(laps):
    assert laps[1].distance_m == pytest.approx(600.0, abs=5)
    assert laps[0].distance_m == pytest.approx(450.0, abs=5)


def test_non_race_ride_keeps_its_device_laps(series):
    device = [
        WorkoutLap(index=i, start_offset_s=630.0 + 200 * i, duration_s=200.0, distance_m=600.0, avg_hr=170)
        for i in range(4)
    ]
    device.append(WorkoutLap(index=4, start_offset_s=1430.0, duration_s=60.0, distance_m=180.0, avg_hr=170))
    laps = build_canonical_laps(device, series, race_start_s=None)
    assert [(l.start_s, l.end_s, l.source, l.comparable, l.start_lap) for l in laps] == [
        *((630.0 + 200 * i, 830.0 + 200 * i, "device", True, False) for i in range(4)),
        (1430.0, 1490.0, "device", False, False),
    ]


def test_without_device_laps_gps_crossings_of_the_mark_make_the_laps(series):
    laps = build_canonical_laps([], series, race_start_s=CROSSINGS[0])
    assert [round(l.start_s) for l in laps if l.comparable] == [630, 830, 1030, 1230]
    assert {l.source for l in laps if l.comparable} == {"gps"}


def test_a_single_device_lap_spanning_the_race_is_cut_at_the_mark(series):
    only = [WorkoutLap(index=0, start_offset_s=0.0, duration_s=END_S, distance_m=series["dist_m"][-1])]
    laps = build_canonical_laps(only, series, race_start_s=CROSSINGS[0])
    assert [round(l.start_s) for l in laps if l.comparable] == [630, 830, 1030, 1230]
    assert laps[0].start_s == CROSSINGS[0] and not laps[0].start_lap  # the gun was at the mark


def test_gps_detection_can_use_a_reference_point_instead_of_the_first_sample(series):
    mark = start_point(series, CROSSINGS[0])
    assert detect_gps_laps(series) == []  # first sample = warm-up start: never returns to it
    found = detect_gps_laps(series, reference=mark, from_s=CROSSINGS[0])
    assert [round(l.start_s) for l in found] == [630, 830, 1030, 1230]
    assert [round(t) for t in mark_crossings(series, mark)] == [round(c) for c in CROSSINGS]


def test_every_consumer_uses_the_same_laps(series, laps):
    workout = race_workout(series)
    comparable = [l for l in laps if l.comparable]

    mtb = build_mtb_dynamics(workout, series, laps)
    assert [(m.lap, m.start_offset_s) for m in mtb.laps] == [(l.n, l.start_s) for l in laps]

    sectors = build_course_sectors(laps, series)
    assert [s.lap for s in sectors.laps] == [l.n for l in comparable]

    efficiency = build_race_efficiency(laps, series)
    assert [e.lap for e in efficiency.laps] == [l.n for l in laps if l.comparable or l.start_lap]
    assert efficiency.laps[0].start_lap
    assert efficiency.trend.time_change_pct == pytest.approx(0.0, abs=1.0)  # trends exclude the start lap

    pacing = analyze_laps(series, laps)
    assert [(p.lap_n, p.start_s) for p in pacing] == [(l.n, l.start_s) for l in laps]
    assert [p.lap_n for p in pacing if p.comparable] == [l.n for l in comparable]
    assert pacing[0].coasting_s == pytest.approx(0.0, abs=1.0)  # the wait on the line is not lap 1


def test_the_analyzer_stores_the_canonical_laps_and_the_race_lap_table_uses_them(series):
    workout = race_workout(series)
    analytics = workout.analyze(AnalysisContext(kind="race", series=series, race_start_s=RACE_START_S))
    assert [l.n for l in analytics.laps] == [1, 2, 3, 4, 5, 6]
    assert [(r.n, r.duration_s) for r in analytics.intervals.race_laps] == [(l.n, l.duration_s) for l in analytics.laps]
    assert [m.lap for m in analytics.mtb_dynamics.laps] == [l.n for l in analytics.laps]
    assert [s.lap for s in analytics.course_sectors.laps] == [2, 3, 4, 5]
    assert analytics.race_efficiency.laps[0].lap == 1


def test_analytics_without_series_have_no_laps():
    assert race_workout().analyze(AnalysisContext(kind="race", series=None)).laps == []
