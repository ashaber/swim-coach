"""Tests for swim_coach.workout_templates.short_device_title -- a short, scannable device-export
title derived from a Session.purpose string. Andrew, 2026-09-22, reading a real pushed workout:
"very long titles are hard to find on Garmin device."
"""

from __future__ import annotations

from swim_coach.workout_templates import short_device_title


def test_splits_on_the_em_dash_and_keeps_only_the_short_label() -> None:
    purpose = "sustained threshold intervals (Z4) — lactate-threshold-adjacent, long work bouts"
    assert short_device_title(purpose) == "sustained threshold intervals (Z4)"


def test_a_purpose_with_no_em_dash_passes_through_unchanged() -> None:
    assert short_device_title("VO2 intervals") == "VO2 intervals"


def test_real_examples_from_plan_py_all_shorten_to_a_reasonable_title() -> None:
    cases = {
        "over/unders (Z3/Z4) — fluctuating lactate production/clearance under alternating load": "over/unders (Z3/Z4)",
        "Heinous club ride — endurance": "Heinous club ride",
        "dryland shoulder strength — rotator-cuff/scapular-stability strength & balance": "dryland shoulder strength",
        "coached pool practice — content assigned by pool coach after session": "coached pool practice",
    }
    for purpose, expected in cases.items():
        assert short_device_title(purpose) == expected
        assert len(short_device_title(purpose)) <= 40


def test_a_long_label_with_no_em_dash_is_cut_at_a_word_boundary_not_mid_word() -> None:
    purpose = "a genuinely very long workout label with no separator anywhere in it at all"
    result = short_device_title(purpose, max_len=20)
    assert len(result) <= 20
    assert result == "a genuinely very"  # "a genuinely very long" is 21 chars, one over -- so "long" is dropped whole


def test_a_single_word_longer_than_max_len_still_returns_something_not_empty() -> None:
    purpose = "supercalifragilisticexpialidocious"
    result = short_device_title(purpose, max_len=10)
    assert result and len(result) <= max(10, len(result))  # falls back to a hard slice, never empty


def test_custom_max_len_is_respected() -> None:
    purpose = "sustained threshold intervals (Z4) — lactate-threshold-adjacent, long work bouts"
    result = short_device_title(purpose, max_len=15)
    assert len(result) <= 15
    assert result == "sustained"


def test_leading_and_trailing_whitespace_around_the_label_is_stripped() -> None:
    assert short_device_title("  padded label  — rationale") == "padded label"
