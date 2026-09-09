"""Tests for swim_coach.zones: CSS derivation, zone table, OW pace inference.

No LLM calls, no network access — pure arithmetic.
"""

import pytest

from swim_coach.zones import (
    bike_zone_for_pct,
    bike_zone_table,
    css_from_test,
    infer_ow_pace,
    zone_table,
)


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


# --- bike_zone_for_pct / bike_zone_table (Coggan/Allen 7-zone %FTP model) ---
# library/23-cycling-training.md's boundary convention: inclusive on the
# upper end, continuous (not whole-number-restricted). Z1 <=55%, Z2 >55-75%,
# Z3 >75-90%, Z4 >90-105%, Z5 >105-120%, Z6 >120-150%, Z7 >150% (open).


@pytest.mark.parametrize(
    "pct,expected_zone",
    [
        (0.0, "Z1"),
        (54.9, "Z1"),
        (55.0, "Z1"),  # exact boundary -- inclusive on the upper end
        (55.1, "Z2"),
        (56.0, "Z2"),
        (75.0, "Z2"),  # exact boundary
        (75.1, "Z3"),
        (90.0, "Z3"),  # exact boundary
        (90.1, "Z4"),
        (105.0, "Z4"),  # exact boundary
        (105.1, "Z5"),
        (120.0, "Z5"),  # exact boundary
        (120.1, "Z6"),
        (150.0, "Z6"),  # exact boundary
        (150.1, "Z7"),
        (200.0, "Z7"),  # open-ended, no upper cap
    ],
)
def test_bike_zone_for_pct_boundaries(pct, expected_zone):
    assert bike_zone_for_pct(pct) == expected_zone


def test_bike_zone_table_shape_and_watts():
    table = bike_zone_table(250.0)
    assert set(table) == {"Z1", "Z2", "Z3", "Z4", "Z5", "Z6", "Z7"}
    z2 = table["Z2"]
    assert z2["lo_pct_ftp"] == 55.0
    assert z2["hi_pct_ftp"] == 75.0
    assert z2["watts_lo"] == pytest.approx(250.0 * 0.55)
    assert z2["watts_hi"] == pytest.approx(250.0 * 0.75)


def test_bike_zone_table_z7_is_open_ended():
    table = bike_zone_table(250.0)
    z7 = table["Z7"]
    assert z7["hi_pct_ftp"] is None
    assert z7["watts_hi"] is None
    assert z7["lo_pct_ftp"] == 150.0
    assert z7["watts_lo"] == pytest.approx(250.0 * 1.5)


def test_bike_zone_table_z1_starts_at_zero():
    table = bike_zone_table(300.0)
    z1 = table["Z1"]
    assert z1["lo_pct_ftp"] == 0.0
    assert z1["watts_lo"] == 0.0


# --- threshold-history build: zones.py behavior is completely unchanged ----


def test_zones_module_has_no_threshold_record_dependency():
    # Regression guard the threshold-history build's own brief explicitly
    # asks for: ThresholdRecord is a durable, append-only LOG that the
    # engine only ever WRITES to and reads back verbatim for display
    # (backend/app/context.py's _recent_thresholds/_render_threshold_
    # history) -- it must never become a second, competing source of truth
    # zones.py itself resolves against. An athlete's zones are computed
    # ONLY from the already-existing resolved Athlete fields
    # (css_pace_s_per_100m/ftp_watts/lthr_bpm), exactly as before this
    # build -- zones.py has zero import of, or reference to,
    # ThresholdRecord at all.
    import inspect

    import swim_coach.zones as zones_mod

    source = inspect.getsource(zones_mod)
    assert "ThresholdRecord" not in source
    assert "threshold_record" not in source


def test_bike_zone_table_behavior_unaffected_by_threshold_history_for_athlete_with_no_records():
    # An athlete with a resolved ftp_watts but ZERO ThresholdRecord history
    # on file (every real athlete's state immediately after this build
    # ships, before any record_threshold_test call is ever made) must
    # produce byte-identical zone output to before this build existed --
    # this function takes a raw ftp_watts float, never a store/athlete
    # slug, so there is no code path here that could even see threshold
    # history one way or the other.
    table = bike_zone_table(263.0)
    assert table["Z4"]["watts_lo"] == pytest.approx(263.0 * 0.90)
    assert table["Z2"]["watts_lo"] == pytest.approx(263.0 * 0.55)
