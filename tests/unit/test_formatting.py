"""Tests for swim_coach.formatting: shared pace/rounding/iso-week helpers."""

from __future__ import annotations

from datetime import date

from swim_coach.formatting import duration_min_for_distance, format_pace_s, iso_week_str, round_100


def test_format_pace_s_rounds_to_whole_seconds():
    assert format_pace_s(92.3) == "1:32"
    assert format_pace_s(92.6) == "1:33"
    assert format_pace_s(65) == "1:05"


def test_round_100_rounds_to_nearest_hundred():
    assert round_100(149) == 100
    assert round_100(151) == 200
    assert round_100(0) == 0


def test_duration_min_for_distance_clamps_negative_and_rounds():
    assert duration_min_for_distance(1000, 90) == 15.0
    assert duration_min_for_distance(-50, 90) == 0.0


def test_iso_week_str_pads_week_and_uses_iso_year():
    assert iso_week_str(date(2026, 1, 5)) == "2026-W02"
    assert iso_week_str(date(2027, 1, 1)) == "2026-W53"
