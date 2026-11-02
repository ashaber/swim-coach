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
    th = math.radians(t.tilt_deg)
    k = bike_fit.SIT_FRACTION * t.saddle_len
    srp = (t.st[0] - k * math.cos(th), t.st[1] - k * math.sin(th))
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


DIST_TAPES = ["bb_fa", "bb_bc", "fa_bc", "bb_st", "bc_st", "ra_bb", "ra_st", "bb_h", "st_h", "bc_h",
              "ra_fa", "fa_h", "ra_bc"]


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


def test_typo_residual_pattern_matches_the_reference_simulation() -> None:
    # reference sim, 12 mm typo, typical CX bike: residuals [RA-FA, FA-H, RA-BC] (abs, mm)
    want = {"bb_fa": (11.6, 3.1, 0), "bb_bc": (1.3, 11.8, 9.0), "fa_bc": (1.3, 12.3, 0), "bb_st": (2.1, 0.8, 8.5),
            "bc_st": (1.1, 10.8, 5.0), "ra_bb": (11.2, 0, 6.3), "ra_st": (1.8, 0, 8.3), "bb_h": (0, 14.5, 0),
            "st_h": (0, 10.6, 0)}
    for tape, expect in want.items():
        res = compute_fit(inputs_for(CX, tape={tape: tapes_for(CX)[tape] + 12}), "drop_bar")
        got = [abs(r) for r in residuals(res)[:3]]
        assert got == pytest.approx(list(expect), abs=3.5), (tape, got)


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
    warn = bad = 0
    runs = 1500
    for _ in range(runs):
        noisy = {k: v + rng.gauss(0, bike_fit.TAPE_SIGMA_MM) for k, v in base.items()}
        status = compute_fit(inputs_for(CX, tape=noisy), "drop_bar").closure.status
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
    # reference sim, 1 mm tape sd on a typical CX bike: setback 1.5, height 0.9, reach 0.9, drop 2.0
    # (setback = tip, height = BB to sit point, reach/drop = saddle-to-hand)
    assert out(res, "setback_tip_mm").sigma == pytest.approx(1.5, rel=0.4)
    assert out(res, "saddle_height_mm").sigma == pytest.approx(0.9, rel=0.4)
    assert out(res, "saddle_to_hand_reach_mm").sigma == pytest.approx(0.9, rel=0.4)
    assert out(res, "saddle_to_hand_drop_mm").sigma == pytest.approx(2.0, rel=0.4)


def test_error_estimates_are_deterministic_and_scale_with_the_constant(monkeypatch) -> None:
    a = compute_fit(inputs_for(CX), "drop_bar")
    b = compute_fit(inputs_for(CX), "drop_bar")
    assert [o.sigma for o in a.outputs] == [o.sigma for o in b.outputs]
    monkeypatch.setattr(bike_fit, "TAPE_SIGMA_MM", 2.0)
    c = compute_fit(inputs_for(CX), "drop_bar")
    assert out(c, "setback_sit_mm").sigma == pytest.approx(2 * out(a, "setback_sit_mm").sigma, rel=1e-6)


def test_floor_tilt_reading_is_subtracted_from_saddle_tilt() -> None:
    key = "saddle_to_hand_drop_mm"  # the sit point's height is what saddle tilt moves
    plain = compute_fit(inputs_for(CX), "drop_bar")
    skewed = compute_fit(inputs_for(CX, floor_tilt_deg=1.0), "drop_bar")  # tilt 0 - floor 1 = -1 deg
    assert out(skewed, key).value != pytest.approx(out(plain, key).value, abs=1.0)
    ref = compute_fit(inputs_for(Truth(**{**MTB.__dict__, "tilt_deg": 1.0})), "mtb")
    assert out(compute_fit(inputs_for(MTB, floor_tilt_deg=1.0), "mtb"), key).value == pytest.approx(
        out(ref, key).value, abs=1e-6)


def test_blank_widths_fall_back_to_labelled_defaults_and_are_flagged() -> None:
    inp = BikeFitInputs(tape=inputs_for(CX).tape, saddle_tilt_deg=0, saddle_length_mm=270, crank_length_mm=172.5,
                        string_length_mm=420)
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
        BikeFitInputs(tape=inputs_for(CX).tape, saddle_tilt_deg=0, saddle_length_mm=270, string_length_mm=420)


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


def test_sit_reference_point_is_the_midpoint_of_the_saddle() -> None:
    assert bike_fit.SIT_FRACTION == 0.5
