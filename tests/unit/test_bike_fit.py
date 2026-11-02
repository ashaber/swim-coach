"""Bike-fit measurement engine: known geometry -> tape distances -> recovered outputs."""

from __future__ import annotations

import math

import pytest
from swim_coach import bike_fit
from swim_coach.bike_fit import BikeFitError, compare_fits, compute_fit
from swim_coach.models import BikeFitInputs

from bike_fit_synth import CX, MTB, Truth, inputs_for, tapes_for


def out(result, key: str):
    return next(o for o in result.outputs if o.key == key)


def truth_metrics(t: Truth) -> dict[str, float]:
    srp = t.s
    axle_y_at_bb = t.ra[1] + (t.fa[1] - t.ra[1]) * (0 - t.ra[0]) / (t.fa[0] - t.ra[0])
    return {
        "setback_tip_mm": -t.st[0],
        "setback_sit_mm": -srp[0],
        "saddle_height_mm": math.hypot(*srp),
        "saddle_tip_height_mm": t.st[1],
        "reach_bc_mm": t.bc[0],
        "reach_hand_mm": t.h[0],
        "stack_bc_mm": t.bc[1],
        "stack_hand_mm": t.h[1],
        "saddle_to_hand_reach_mm": t.h[0] - srp[0],
        "saddle_to_hand_drop_mm": srp[1] - t.h[1],
        "bb_to_hand_mm": math.hypot(*t.h),
        "effective_seat_angle_deg": math.degrees(math.atan2(srp[1], -srp[0])),
        "bb_drop_mm": axle_y_at_bb,
        "clamp_to_hands_horizontal_mm": t.h[0] - t.bc[0],
        "clamp_to_hands_vertical_mm": t.h[1] - t.bc[1],
        "clamp_to_hands_mm": math.dist(t.bc, t.h),
        "sit_to_pedal_down_mm": math.hypot(*srp) + 172.5,
        "sit_to_pedal_up_mm": math.hypot(*srp) - 172.5,
    }


@pytest.mark.parametrize("truth", [CX, MTB], ids=["cx", "mtb"])
def test_round_trip_recovers_known_geometry_including_laterals(truth: Truth) -> None:
    res = compute_fit(inputs_for(truth), truth.bike_type)
    for key, want in truth_metrics(truth).items():
        assert out(res, key).value == pytest.approx(want, abs=0.05), key
    assert res.closure.status == "ok"
    assert all(abs(c.residual_mm) < 0.05 for c in res.closure.checks)
    assert res.assumptions["defaulted"] == []


def test_wheelbase_is_the_measured_axle_distance_projected_on_the_ground() -> None:
    res = compute_fit(inputs_for(CX), "drop_bar")
    true_wb = CX.fa[0] - CX.ra[0]
    assert out(res, "wheelbase_mm").value == pytest.approx(true_wb, abs=0.05)


def test_unequal_wheel_radius_is_corrected_via_axle_heights() -> None:
    good = compute_fit(inputs_for(CX), "drop_bar")
    # same bike, but pretend the heights were equal: ignores a 8 mm radius difference
    wrong = compute_fit(inputs_for(CX, tape={"floor_fa": 340.0, "floor_ra": 340.0}), "drop_bar")
    assert out(wrong, "setback_sit_mm").value != pytest.approx(out(good, "setback_sit_mm").value, abs=1.0)
    assert out(good, "setback_sit_mm").value == pytest.approx(truth_metrics(CX)["setback_sit_mm"], abs=0.05)
    assert good.ground_pitch_deg == pytest.approx(math.degrees(math.asin((CX.fa[1] - CX.ra[1]) / (CX.fa[0] - CX.ra[0]))), abs=0.3)
    assert good.radius_difference_mm == pytest.approx(-8.0, abs=0.01)


DIST_TAPES = ["bb_fa", "bb_bc", "fa_bc", "bb_st", "bc_st", "bb_s", "bc_s", "ra_bb", "ra_st", "bb_h", "st_h",
              "bc_h", "ra_fa", "fa_h", "ra_bc", "ra_s"]


def residuals(res) -> list[float]:
    return [c.residual_mm for c in res.closure.checks]


@pytest.mark.parametrize("truth", [CX, MTB], ids=["cx", "mtb"])
@pytest.mark.parametrize("tape", DIST_TAPES)
def test_every_required_tape_trips_at_least_one_check_on_a_12_mm_typo(truth: Truth, tape: str) -> None:
    t = tapes_for(truth)
    res = compute_fit(inputs_for(truth, tape={tape: t[tape] + 12}), truth.bike_type)
    assert res.closure.status == "bad", residuals(res)
    assert max(abs(r) for r in residuals(res)) > bike_fit.CLOSURE_BAD_MM
    assert tape in [s.measure for s in res.closure.suspects]  # the hint names the typo'd tape


@pytest.mark.parametrize("truth", [CX, MTB], ids=["cx", "mtb"])
def test_a_12_mm_typo_in_the_entered_tip_to_s_distance_trips_the_tip_s_check(truth: Truth) -> None:
    good = inputs_for(truth).sit_point_from_tip_mm
    res = compute_fit(inputs_for(truth, sit_point_from_tip_mm=good + 12), truth.bike_type)
    assert res.closure.status == "bad"
    tip_s = next(c for c in res.closure.checks if c.key == "tip_s")
    assert tip_s.status == "bad" and tip_s.residual_mm == pytest.approx(-12.0, abs=0.1)
    assert "sit_tip" in [s.measure for s in res.closure.suspects]


@pytest.mark.parametrize("truth", [CX, MTB], ids=["cx", "mtb"])
@pytest.mark.parametrize("tape", ["bb_s", "bc_s"])
def test_s_tapes_are_caught_only_by_the_s_checks(truth: Truth, tape: str) -> None:
    t = tapes_for(truth)
    res = compute_fit(inputs_for(truth, tape={tape: t[tape] + 12}), truth.bike_type)
    old = [c for c in res.closure.checks if c.key not in ("tip_s", "ra_s")]
    assert all(c.status == "ok" for c in old)  # S feeds none of the older checks
    by = {c.key: c.status for c in res.closure.checks}
    # BB-S is nearly the saddle height, so the tip-to-S line barely sees it: RA-S is what catches it
    assert by["ra_s" if tape == "bb_s" else "tip_s"] == "bad", by


def test_the_check_pattern_lists_likely_suspects_only_as_a_hint() -> None:
    res = compute_fit(inputs_for(CX, tape={"ra_st": tapes_for(CX)["ra_st"] + 12}), "drop_bar")
    top = res.closure.suspects[0]
    assert top.measure == "ra_st" and top.estimated_error_mm == pytest.approx(12.0, abs=1.5)
    assert 0.9 <= top.fit <= 1.0
    assert compute_fit(inputs_for(CX), "drop_bar").closure.suspects == []


def test_floor_heights_are_not_covered_by_the_checks_and_the_message_says_so() -> None:
    t = tapes_for(CX)
    res = compute_fit(inputs_for(CX, tape={"floor_fa": t["floor_fa"] + 12}), "drop_bar")
    assert res.closure.status == "ok"
    assert "floor heights" in res.closure.not_checked and "crank length" in res.closure.not_checked


def test_false_alarm_rate_at_1_mm_tape_error_is_low_with_the_noise_scaled_thresholds() -> None:
    import random

    rng = random.Random(20261101)
    base = tapes_for(CX)
    sit = inputs_for(CX).sit_point_from_tip_mm
    warn = bad = 0
    runs = 1500
    for _ in range(runs):
        noisy = {k: v + rng.gauss(0, bike_fit.TAPE_SIGMA_MM) for k, v in base.items()}
        mark = sit + rng.gauss(0, bike_fit.TAPE_SIGMA_MM)
        status = compute_fit(inputs_for(CX, tape=noisy, sit_point_from_tip_mm=mark), "drop_bar").closure.status
        warn += status in ("warn", "bad")
        bad += status == "bad"
    assert bad / runs < 0.005
    assert warn / runs < 0.08


def test_closure_check_thresholds_scale_with_each_checks_noise() -> None:
    res = compute_fit(inputs_for(CX), "drop_bar")
    for c in res.closure.checks:
        assert c.warn_mm >= bike_fit.CLOSURE_WARN_MM and c.bad_mm >= bike_fit.CLOSURE_BAD_MM
        assert c.warn_mm == pytest.approx(max(3.0, 2.5 * c.sigma_mm))
    fa_h = next(c for c in res.closure.checks if c.key == "fa_h")
    assert fa_h.bad_mm > 6.0  # the noisiest check gets a wider band


@pytest.mark.parametrize("err,status", [(1.0, "ok"), (5.0, "warn"), (8.0, "bad")])
def test_closure_thresholds_ok_warn_bad(err: float, status: str) -> None:
    res = compute_fit(inputs_for(CX, tape={"ra_fa": tapes_for(CX)["ra_fa"] + err}), "drop_bar")
    assert res.closure.status == status
    assert res.closure.checks[0].residual_mm == pytest.approx(-err, abs=0.1)


def test_closure_never_rejects() -> None:
    res = compute_fit(inputs_for(CX, tape={"ra_fa": 1500.0}), "drop_bar")
    assert res.closure.status == "bad" and res.outputs


def test_triangle_inequality_failure_is_a_clean_error() -> None:
    with pytest.raises(BikeFitError, match="BB-BC"):
        compute_fit(inputs_for(CX, tape={"bb_bc": 100.0}), "drop_bar")


def test_tape_shorter_than_the_lateral_gap_is_a_clean_error() -> None:
    with pytest.raises(BikeFitError, match="lateral"):
        compute_fit(inputs_for(CX, tape={"bb_fa": 8.0}), "drop_bar")


def test_error_estimates_are_near_the_reference_simulation() -> None:
    res = compute_fit(inputs_for(CX), "drop_bar")
    # 1 mm tape sd on a typical CX bike (Jacobian, measured S): tip setback 1.8, sit setback 2.1, height 1.0,
    # saddle-to-hand reach 1.7 and drop 2.6 (S is solved from two tapes, so it is noisier than the old midpoint)
    assert out(res, "setback_tip_mm").sigma == pytest.approx(1.8, rel=0.2)
    assert out(res, "setback_sit_mm").sigma == pytest.approx(2.1, rel=0.2)
    assert out(res, "saddle_height_mm").sigma == pytest.approx(1.0, rel=0.2)
    assert out(res, "saddle_to_hand_reach_mm").sigma == pytest.approx(1.7, rel=0.2)
    assert out(res, "saddle_to_hand_drop_mm").sigma == pytest.approx(2.6, rel=0.2)


def test_error_estimates_are_deterministic_and_scale_with_the_constant(monkeypatch) -> None:
    a = compute_fit(inputs_for(CX), "drop_bar")
    b = compute_fit(inputs_for(CX), "drop_bar")
    assert [o.sigma for o in a.outputs] == [o.sigma for o in b.outputs]
    monkeypatch.setattr(bike_fit, "TAPE_SIGMA_MM", 2.0)
    c = compute_fit(inputs_for(CX), "drop_bar")
    assert out(c, "setback_sit_mm").sigma == pytest.approx(2 * out(a, "setback_sit_mm").sigma, rel=1e-6)


def test_saddle_tilt_and_length_are_recorded_and_move_no_output() -> None:
    a = compute_fit(inputs_for(CX), "drop_bar")
    b = compute_fit(inputs_for(CX, saddle_tilt_deg=3.0, floor_tilt_deg=1.0, saddle_length_mm=250), "drop_bar")
    assert [o.value for o in a.outputs] == [o.value for o in b.outputs]
    assert b.tilt_deg == pytest.approx(2.0)  # saddle reading minus the floor reading


@pytest.mark.parametrize("tilt,floor,flagged", [(4.0, None, False), (4.1, None, True), (-4.5, None, True),
                                                (5.0, 2.0, False), (2.0, -3.0, True)])
def test_tilt_beyond_4_degrees_is_a_neutral_advisory_that_changes_nothing(tilt, floor, flagged) -> None:
    res = compute_fit(inputs_for(CX, saddle_tilt_deg=tilt, floor_tilt_deg=floor), "drop_bar")
    hit = [n for n in res.notes if "Tilt beyond" in n]
    assert bool(hit) is flagged
    if hit:
        assert "check the measurement" in hit[0] and "\u00b14" in hit[0]
    assert res.closure.status == "ok"
    assert bike_fit.TILT_ADVISORY_DEG == 4.0


def test_blank_widths_fall_back_to_labelled_defaults_and_are_flagged() -> None:
    inp = BikeFitInputs(tape=inputs_for(CX).tape, saddle_tilt_deg=0, saddle_length_mm=270, crank_length_mm=172.5,
                        string_length_mm=420, sit_point_from_tip_mm=inputs_for(CX).sit_point_from_tip_mm,
                        saddle_model="Test saddle")
    res = compute_fit(inp, "drop_bar")
    lat = res.assumptions
    assert (lat["bb_mm"], lat["fa_mm"], lat["ra_mm"]) == (60.0, 50.0, 71.0)
    assert lat["defaulted"] == ["crank", "fa", "ra"]
    assert any("Assumed" in n for n in res.notes)
    assert bike_fit.WIDTH_DEFAULTS_MM["mtb"] == {"crank": 140.0, "fa": 110.0, "ra": 148.0}


def test_lateral_offset_is_half_the_measured_width() -> None:
    res = compute_fit(inputs_for(CX, front_axle_width_mm=104.0), "drop_bar")
    assert res.assumptions["fa_mm"] == 52.0 and "fa" not in res.assumptions["defaulted"]
    assert res.assumptions["widths_mm"]["front_axle"] == 104.0


def test_lateral_error_effect_is_computed_and_small() -> None:
    res = compute_fit(inputs_for(CX), "drop_bar")
    eff = res.lateral_effect
    assert eff["width_error_mm"] == 5.0
    assert 0 < eff["max_output_change_mm"] < 1.0  # a 5 mm width error moves nothing by a millimetre
    assert set(eff["per_width_mm"]) == {"crank_bolt", "front_axle", "rear_axle"}


def test_h_has_no_lateral_offset_so_string_length_does_not_change_the_geometry() -> None:
    a = compute_fit(inputs_for(CX), "drop_bar")
    b = compute_fit(inputs_for(CX).model_copy(update={"string_length_mm": 600.0}), "drop_bar")
    assert [o.value for o in a.outputs] == [o.value for o in b.outputs]


def test_clamp_to_hands_offset_is_reported_horizontal_and_vertical_relative_to_ground() -> None:
    res = compute_fit(inputs_for(CX), "drop_bar")
    assert out(res, "clamp_to_hands_horizontal_mm").value == pytest.approx(CX.h[0] - CX.bc[0], abs=0.05)
    assert out(res, "clamp_to_hands_vertical_mm").value == pytest.approx(CX.h[1] - CX.bc[1], abs=0.05)


def test_pedal_distances_are_saddle_height_plus_and_minus_crank_length() -> None:
    res = compute_fit(inputs_for(CX), "drop_bar")
    h = out(res, "saddle_height_mm").value
    assert out(res, "sit_to_pedal_down_mm").value == pytest.approx(h + 172.5)
    assert out(res, "sit_to_pedal_up_mm").value == pytest.approx(h - 172.5)
    assert "not leg" in out(res, "sit_to_pedal_down_mm").definition


def test_crank_length_is_required() -> None:
    with pytest.raises(ValueError):
        BikeFitInputs(tape=inputs_for(CX).tape, saddle_tilt_deg=0, saddle_length_mm=270, string_length_mm=420,
                      sit_point_from_tip_mm=130, saddle_model="Test saddle")


def test_optional_bar_text_fields_are_recorded_not_used() -> None:
    a = compute_fit(inputs_for(CX), "drop_bar")
    inp = inputs_for(CX, bar_model="Zipp SL-70", stem_length="100", bar_backsweep="0", bar_upsweep="0")
    assert inp.bar_model == "Zipp SL-70"
    assert [o.value for o in compute_fit(inp, "drop_bar").outputs] == [o.value for o in a.outputs]


def test_seated_orientation_rotates_the_front_triangle_about_the_bb() -> None:
    # rotate the true unweighted bike 3 deg nose-up about the BB, then 'measure' floor heights
    rho = math.radians(3.0)
    bc_s = (CX.bc[0] * math.cos(rho) - CX.bc[1] * math.sin(rho), CX.bc[0] * math.sin(rho) + CX.bc[1] * math.cos(rho))
    bb_h = 275.0
    res = compute_fit(inputs_for(CX, seated_floor_bb_mm=bb_h, seated_floor_bc_mm=bb_h + bc_s[1]), "drop_bar")
    assert res.seated is not None
    assert res.seated.rotation_deg == pytest.approx(3.0, abs=0.02)
    st = (CX.st[0] * math.cos(rho) - CX.st[1] * math.sin(rho), CX.st[0] * math.sin(rho) + CX.st[1] * math.cos(rho))
    got = {o.key: o for o in res.seated.outputs}
    assert got["setback_tip_mm"].value == pytest.approx(-st[0], abs=0.05)
    assert got["saddle_tip_height_mm"].value == pytest.approx(st[1], abs=0.05)
    assert got["reach_bc_mm"].value == pytest.approx(bc_s[0], abs=0.05)
    # saddle height (a distance) does not change under rotation
    assert got["saddle_height_mm"].value == pytest.approx(out(res, "saddle_height_mm").value, abs=0.05)
    assert "rigid" in res.seated.assumption
    assert got["setback_tip_mm"].sigma > 0


def test_mtb_without_seated_readings_says_unweighted_only() -> None:
    res = compute_fit(inputs_for(MTB), "mtb")
    assert res.seated is None
    assert any("sag" in n and "upright" in n for n in res.notes)
    cx = compute_fit(inputs_for(CX), "drop_bar")
    assert not any("sag" in n for n in cx.notes)


def test_sag_percentages_are_recorded_not_used() -> None:
    a = compute_fit(inputs_for(MTB), "mtb")
    b = compute_fit(inputs_for(MTB, sag_front_pct=20, sag_rear_pct=30), "mtb")
    assert [o.value for o in a.outputs] == [o.value for o in b.outputs]


def test_compare_flags_differences_beyond_combined_error() -> None:
    a = compute_fit(inputs_for(CX), "drop_bar")
    shifted = Truth(**{**CX.__dict__, "st": (CX.st[0] - 3.0, CX.st[1])})  # 3 mm: inside noise
    far = Truth(**{**CX.__dict__, "st": (CX.st[0] - 30.0, CX.st[1])})
    small = compare_fits(a, compute_fit(inputs_for(shifted), "drop_bar"))
    big = compare_fits(a, compute_fit(inputs_for(far), "drop_bar"))
    row = lambda c, k: next(r for r in c.unweighted if r.key == k)  # noqa: E731
    assert row(small, "setback_tip_mm").diff == pytest.approx(3.0, abs=0.05)
    assert row(small, "setback_tip_mm").exceeds_error is False
    assert row(big, "setback_tip_mm").exceeds_error is True
    assert row(big, "setback_tip_mm").sigma_diff == pytest.approx(
        math.hypot(out(a, "setback_tip_mm").sigma, out(a, "setback_tip_mm").sigma), rel=0.05)
    assert small.seated is None


def test_every_output_has_a_label_unit_and_definition() -> None:
    res = compute_fit(inputs_for(CX), "drop_bar")
    for o in res.outputs:
        assert o.label and o.unit in ("mm", "deg") and o.definition
    assert "does not recommend" in res.limits and "drops" in res.limits


def test_points_for_drawing_match_the_known_geometry() -> None:
    res = compute_fit(inputs_for(CX), "drop_bar")
    for name, want in (("BB", (0, 0)), ("FA", CX.fa), ("RA", CX.ra), ("BC", CX.bc), ("ST", CX.st), ("H", CX.h)):
        assert res.points[name] == pytest.approx(list(want), abs=0.05), name
    assert res.axle_heights_mm == {"front": CX.fa[1] - CX.floor_y, "rear": CX.ra[1] - CX.floor_y}


def test_there_is_no_midpoint_constant_and_no_srp_point() -> None:
    assert not hasattr(bike_fit, "SIT_FRACTION")
    res = compute_fit(inputs_for(CX), "drop_bar")
    assert "SRP" not in res.points and res.points["S"] == pytest.approx(list(CX.s), abs=0.05)
    assert "sit_fraction" not in res.constants


def test_s_is_solved_from_bb_s_and_bc_s_and_saddle_length_is_never_used() -> None:
    a = compute_fit(inputs_for(CX), "drop_bar")
    b = compute_fit(inputs_for(CX, saddle_length_mm=330), "drop_bar")
    assert a.points["S"] == b.points["S"]
    assert out(a, "setback_sit_mm").value == pytest.approx(-CX.s[0], abs=0.05)
    assert out(a, "saddle_height_mm").value == pytest.approx(math.hypot(*CX.s), abs=0.05)
    assert out(a, "saddle_height_mm").label.startswith("Saddle height, BB to sit point")
    assert "bb_s" in out(a, "saddle_height_mm").depends_on  # BB-S is the height itself
    assert {"bb_s", "bc_s"} <= set(out(a, "setback_sit_mm").depends_on)


def test_tip_s_check_compares_the_solved_straight_line_with_the_entered_mark_distance() -> None:
    res = compute_fit(inputs_for(CX), "drop_bar")
    tip_s = next(c for c in res.closure.checks if c.key == "tip_s")
    assert tip_s.computed_mm == pytest.approx(math.dist(CX.st, CX.s), abs=0.05)
    assert tip_s.measured_mm == pytest.approx(inputs_for(CX).sit_point_from_tip_mm)
    assert tip_s.warn_mm == pytest.approx(max(3.0, 2.5 * tip_s.sigma_mm))
    assert tip_s.bad_mm == pytest.approx(max(6.0, 4.0 * tip_s.sigma_mm))
    assert len(res.closure.checks) == 6


def test_standard_coordinates_from_the_bb_for_tip_s_clamp_and_hand() -> None:
    res = compute_fit(inputs_for(CX), "drop_bar")
    coords = {c.key: c for c in res.coordinates}
    assert list(coords) == ["st", "s", "bc", "h"]
    for key, want in (("st", CX.st), ("s", CX.s), ("bc", CX.bc), ("h", CX.h)):
        assert (coords[key].x, coords[key].y) == pytest.approx(want, abs=0.05)
        assert coords[key].sigma_x > 0 and coords[key].sigma_y > 0
    labels = {o.key: o.label for o in res.outputs}
    assert "clamp" in labels["reach_bc_mm"].lower() and "clamp" in labels["stack_bc_mm"].lower()
    assert "at H" in labels["reach_hand_mm"] and "at H" in labels["stack_hand_mm"]
    assert "head tube" in bike_fit.FRAME_STACK_REACH_NOTE


def test_recorded_only_fields_move_nothing() -> None:
    a = compute_fit(inputs_for(CX), "drop_bar")
    inp = inputs_for(CX, frame_stack_mm=560, frame_reach_mm=390, saddle_rail_note="2 mm back of center",
                     pedal_stack_mm=12, pedal_stack_source="maker_spec")
    b = compute_fit(inp, "drop_bar")
    assert [o.value for o in a.outputs] == [o.value for o in b.outputs]
    assert b.recorded["frame_stack_mm"] == 560 and b.recorded["saddle_rail_note"] == "2 mm back of center"


def test_pedal_stack_source_needs_a_value() -> None:
    with pytest.raises(ValueError):
        inputs_for(CX, pedal_stack_source="measured")


def test_comparison_shows_saddle_match_crank_difference_and_its_pedal_effect() -> None:
    a = compute_fit(inputs_for(CX, crank_length_mm=172.5), "drop_bar")
    b = compute_fit(inputs_for(CX, crank_length_mm=170.0), "drop_bar")
    cmp = compare_fits(a, b)
    assert cmp.saddle.same is True
    assert cmp.crank.diff_mm == pytest.approx(-2.5)
    assert cmp.crank.pedal_down_effect_mm == pytest.approx(-2.5) and cmp.crank.pedal_up_effect_mm == pytest.approx(2.5)
    row = {r.key: r for r in cmp.unweighted}
    assert row["sit_to_pedal_down_mm"].diff == pytest.approx(-2.5, abs=0.01)
    assert row["sit_to_pedal_up_mm"].diff == pytest.approx(2.5, abs=0.01)
    assert any("seat tube angle" in n for n in cmp.notes)


def test_comparison_flags_a_different_saddle_or_mark_distance() -> None:
    a = compute_fit(inputs_for(CX), "drop_bar")
    b = compute_fit(inputs_for(CX, saddle_model="Other saddle"), "drop_bar")
    assert compare_fits(a, b).saddle.same is False
    c = compute_fit(inputs_for(CX, saddle_model="  test SADDLE "), "drop_bar")
    assert compare_fits(a, c).saddle.same is True
    far = Truth(**{**CX.__dict__, "s": (CX.s[0] - 20, CX.s[1])})
    notes = " ".join(compare_fits(a, compute_fit(inputs_for(far), "drop_bar")).notes)
    assert "mark distance differs" in notes


def test_pedal_stack_comparison_only_when_both_have_it_with_a_large_stated_uncertainty() -> None:
    a = compute_fit(inputs_for(CX, pedal_stack_mm=12, pedal_stack_source="maker_spec"), "drop_bar")
    b = compute_fit(inputs_for(CX, pedal_stack_mm=15, pedal_stack_source="measured", crank_length_mm=170.0),
                    "drop_bar")
    assert compare_fits(a, compute_fit(inputs_for(CX), "drop_bar")).pedal_stack is None
    ps = compare_fits(a, b).pedal_stack
    assert ps is not None and ps.diff_mm == pytest.approx(3.0)
    assert ps.adjusted_pedal_down_diff_mm == pytest.approx(-2.5 + 3.0, abs=0.01)
    assert ps.sigma_each_mm == 3.0 and ps.sigma_diff_mm > 4.2
    assert "shoe" in ps.note and "limited" in ps.note
