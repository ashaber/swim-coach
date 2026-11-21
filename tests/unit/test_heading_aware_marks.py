"""The lap mark only counts when crossed in the mark's own direction of travel."""

from __future__ import annotations

import pytest
from wrong_way_pass_fixture import (
    GUN_S, MARK_PASSES, WRONG_WAY_PASSES, ll, wrong_way_device_laps, wrong_way_series,
)

from swim_coach.canonical_laps import build_canonical_laps
from swim_coach.gps_laps import detect_gps_laps, heading_at_time, heading_difference, mark_crossings, mark_heading
from swim_coach.race_view import finish_s

MARK = ll(0, 0)


@pytest.fixture(scope="module")
def series() -> dict:
    return wrong_way_series()


def test_heading_is_north_at_the_mark_and_south_on_the_wrong_way_pass(series):
    assert heading_difference(heading_at_time(series, MARK_PASSES[1]), 0.0) < 5
    assert heading_difference(heading_at_time(series, WRONG_WAY_PASSES[1]), 180.0) < 5
    assert heading_at_time(wrong_way_series(gps=False), 100.0) is None


def test_mark_heading_is_read_at_the_closest_approach(series):
    assert heading_difference(mark_heading(series, MARK, MARK_PASSES[2] + 6), 0.0) < 5


def test_without_a_heading_wrong_way_passes_are_crossings_as_before(series):
    found = mark_crossings(series, MARK, from_s=GUN_S)
    assert any(abs(f - WRONG_WAY_PASSES[2]) <= 1 for f in found)


def test_with_a_heading_only_same_direction_passes_cross(series):
    found = mark_crossings(series, MARK, from_s=GUN_S, reference_heading=0.0)
    assert found == pytest.approx(MARK_PASSES[1:], abs=1)


def test_a_reference_heading_the_other_way_selects_the_other_passes(series):
    found = mark_crossings(series, MARK, from_s=GUN_S, reference_heading=180.0)
    assert found == pytest.approx(WRONG_WAY_PASSES[1:], abs=1)


def test_detect_gps_laps_with_a_heading_cuts_at_mark_passes_only(series):
    laps = detect_gps_laps(series, reference=MARK, from_s=GUN_S, reference_heading=0.0)
    assert [round(l.end_s) for l in laps] == [round(p) for p in MARK_PASSES[1:]]


def test_canonical_laps_are_the_mark_to_mark_laps(series):
    laps = build_canonical_laps(wrong_way_device_laps(series), series, race_start_s=GUN_S)
    edges = [(round(l.start_s), round(l.end_s)) for l in laps]
    assert edges == [(335, 749), (749, 1158), (1158, 1567), (1567, 1976), (1976, 2385), (2385, 2794), (2794, 2845)]
    assert laps[0].start_s == GUN_S
    assert [l.comparable for l in laps] == [True] * 6 + [False]


def test_device_splits_at_a_wrong_way_pass_are_recorded_as_merged(series):
    laps = build_canonical_laps(wrong_way_device_laps(series), series, race_start_s=GUN_S)
    assert [l.source for l in laps[2:6]] == ["merged"] * 4
    assert all(l.distance_m == pytest.approx(1227, rel=0.01) for l in laps[2:6])


def test_the_race_ends_at_the_last_mark_pass_not_the_wrong_way_pass(series):
    laps = build_canonical_laps(wrong_way_device_laps(series), series, race_start_s=GUN_S)
    assert finish_s(laps) == pytest.approx(MARK_PASSES[-1], abs=1)


def test_no_gps_behaviour_is_unchanged():
    series = wrong_way_series(gps=False)
    laps = build_canonical_laps(wrong_way_device_laps(series), series, race_start_s=GUN_S)
    assert laps[0].start_s == GUN_S
    assert all(l.source in ("device", "split_at_start") for l in laps)
