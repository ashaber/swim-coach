"""Tests for swim_coach.zones: CSS derivation, zone table, OW pace inference.

No LLM calls, no network access — pure arithmetic.
"""

import pytest

from swim_coach.zones import css_from_test, infer_ow_pace, zone_table


# --- css_from_test -----------------------------------------------------------


def test_css_from_test_known_example():
    # (400m time - 200m time) / 2, per Wakayoshi et al. critical velocity method
    assert css_from_test(360.0, 170.0) == 95.0


def test_css_from_test_another_example():
    assert css_from_test(400.0, 190.0) == 105.0


def test_css_from_test_rejects_t400_equal_t200():
    with pytest.raises(ValueError):
        css_from_test(200.0, 200.0)


def test_css_from_test_rejects_t400_less_than_t200():
    with pytest.raises(ValueError):
        css_from_test(150.0, 200.0)


# --- zone_table ----------------------------------------------------------------


def test_zone_table_has_all_five_zones():
    table = zone_table(95.0)
    assert set(table.keys()) == {"Z1", "Z2", "Z3", "Z4", "Z5"}


def test_zone_table_z1_open_ended_slow():
    zone = zone_table(95.0)["Z1"]
    assert zone["name"] == "Z1"
    assert zone["lo_offset"] == 10.0
    assert zone["hi_offset"] is None
    assert zone["pace_lo_s"] == 105.0
    assert zone["pace_hi_s"] is None


def test_zone_table_z2_bounds():
    zone = zone_table(95.0)["Z2"]
    assert zone["lo_offset"] == 5.0
    assert zone["hi_offset"] == 9.0
    assert zone["pace_lo_s"] == 100.0
    assert zone["pace_hi_s"] == 104.0


def test_zone_table_z3_bounds():
    zone = zone_table(95.0)["Z3"]
    assert zone["lo_offset"] == 2.0
    assert zone["hi_offset"] == 4.0
    assert zone["pace_lo_s"] == 97.0
    assert zone["pace_hi_s"] == 99.0


def test_zone_table_z4_straddles_css():
    zone = zone_table(95.0)["Z4"]
    assert zone["lo_offset"] == -1.0
    assert zone["hi_offset"] == 1.0
    assert zone["pace_lo_s"] == 94.0
    assert zone["pace_hi_s"] == 96.0


def test_zone_table_z5_open_ended_fast():
    zone = zone_table(95.0)["Z5"]
    assert zone["lo_offset"] is None
    assert zone["hi_offset"] == -2.0
    assert zone["pace_lo_s"] is None
    assert zone["pace_hi_s"] == 93.0


def test_zone_table_scales_with_css():
    table = zone_table(105.0)
    assert table["Z3"]["pace_lo_s"] == 107.0
    assert table["Z3"]["pace_hi_s"] == 109.0


# --- infer_ow_pace ---------------------------------------------------------------


def test_infer_ow_pace_calm_no_wetsuit_warm():
    # css + calm(+2.0), no wetsuit adj, no cold adj
    assert infer_ow_pace(95.0, wetsuit=False, conditions="calm", water_temp_c=20.0) == 97.0


def test_infer_ow_pace_moderate_wetsuit_no_temp():
    # css + wetsuit(-4.5) + moderate(+5.0), water_temp_c=None skips cold adj
    result = infer_ow_pace(95.0, wetsuit=True, conditions="moderate", water_temp_c=None)
    assert result == pytest.approx(95.5)


def test_infer_ow_pace_wetsuit_rough_cold_combo():
    # css + wetsuit(-4.5) + rough(+8.0) + cold(+2.0)
    result = infer_ow_pace(95.0, wetsuit=True, conditions="rough", water_temp_c=14.0)
    assert result == pytest.approx(100.5)


def test_infer_ow_pace_warm_water_no_cold_adjustment():
    result = infer_ow_pace(95.0, wetsuit=False, conditions="rough", water_temp_c=25.0)
    assert result == pytest.approx(103.0)


def test_infer_ow_pace_water_temp_exactly_at_threshold_not_cold():
    # 16.0 is not < 16.0, so no cold penalty applies
    result = infer_ow_pace(95.0, wetsuit=False, conditions="calm", water_temp_c=16.0)
    assert result == pytest.approx(97.0)


def test_infer_ow_pace_rejects_unknown_conditions():
    with pytest.raises(ValueError):
        infer_ow_pace(95.0, wetsuit=False, conditions="hurricane", water_temp_c=20.0)
