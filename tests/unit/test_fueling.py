"""Tests for swim_coach.fueling -- the deterministic fueling-plan
calculator. See engine/fueling-calculator's plan
(`/home/ashaber/.claude/plans/ui-coach-can-logical-lantern.md`) for the four
real event archetypes this must generalize across, and
`library/08-ultra-feeding.md`'s new bike/CX section for the research this
module's constants cite.
"""

from __future__ import annotations

from datetime import date

import pytest

from swim_coach.fueling import (
    DEFAULT_CARB_TOLERANCE_G_PER_HR,
    PRODUCTS,
    FixedIntervalAccess,
    IrregularAccess,
    NoAccess,
    build_pre_event_nutrition_session,
    compute_fueling_plan,
    target_band_g_per_hr,
)


# ============================================================================
# target_band_g_per_hr
# ============================================================================


def test_steady_short_effort_band_is_30():
    assert target_band_g_per_hr(90, "steady") == (30.0, 30.0)


def test_steady_2_to_3h_band_is_45_to_60():
    low, high = target_band_g_per_hr(150, "steady")  # 2.5h
    assert low == 45.0
    assert high == 60.0


def test_steady_long_effort_band_is_60_to_90():
    low, high = target_band_g_per_hr(600, "steady")  # 10h, Skopelos-shaped
    assert low == 60.0
    assert high == 90.0


def test_high_intensity_intermittent_always_gets_top_band_even_when_short():
    """The CX test case: 90min total exposure (45min warmup + 45min race)
    should NOT be read off the <2h/30g-h steady row -- Essén (1978)/Romijn
    et al. (1993) support treating high-intensity-intermittent effort as
    needing at least the literature's long-duration steady-state band
    regardless of actual duration."""
    low, high = target_band_g_per_hr(90, "high_intensity_intermittent")
    assert low == 60.0
    assert high == 90.0


def test_high_intensity_intermittent_band_independent_of_duration():
    short = target_band_g_per_hr(45, "high_intensity_intermittent")
    long = target_band_g_per_hr(240, "high_intensity_intermittent")
    assert short == long == (60.0, 90.0)


# ============================================================================
# compute_fueling_plan -- the four real event archetypes
# ============================================================================


def test_skopelos_irregular_boat_access_reproduces_hand_verified_numbers():
    """Multi-day ultra swim, irregular support-boat access ~90min apart
    (2.5-5km spacing at ultra open-water pace) -- must reproduce the
    ~60g/h, 3-scoop, 30-min-cadence numbers already verified by hand
    (this build's own brief), using Formula 369 (30g carb/scoop) at the
    athlete's default (unset) carb_tolerance_g_per_hr fallback of 60g/h.
    """
    access = IrregularAccess(access_points_min=(90.0, 180.0, 270.0, 360.0))
    plan = compute_fueling_plan(
        duration_min=600,  # 10h, within the real 9-12h Skopelos leg range
        intensity_class="steady",
        access=access,
        product_key="formula_369",
    )
    assert plan.carb_tolerance_g_per_hr == DEFAULT_CARB_TOLERANCE_G_PER_HR
    assert plan.carb_tolerance_source == "default_fallback"
    # Flat 60g/h band (default tolerance clamps the 60-90 long-duration band
    # down to its floor) -- every segment targets the same rate.
    assert len(plan.segments) == 5
    first_segment = plan.segments[0]
    assert first_segment.duration_min == 90.0
    assert first_segment.target_g_per_hr_low == 60.0
    assert first_segment.target_g_per_hr_high == 60.0
    # 60 g/h * 1.5h = 90g -> 3 scoops of Formula 369's 30g/scoop.
    assert first_segment.target_carb_g_low == pytest.approx(90.0)
    assert first_segment.servings_low == pytest.approx(3.0)
    # 30-minute feed cadence within each ~90min segment -> 3 feed points.
    assert first_segment.feed_timestamps_min == (0.0, 30.0, 60.0)


def test_lap_based_regular_access_9_to_5_style():
    """8-hour single-day ultra MTB, lap-based, regular ~50min pit access
    every lap -- proves the fixed-interval access shape generalizes (a
    genuinely different access pattern than Skopelos's irregular boat)."""
    access = FixedIntervalAccess(interval_min=50.0)
    plan = compute_fueling_plan(
        duration_min=480,  # 8h
        intensity_class="steady",
        access=access,
        product_key="formula_369",
    )
    # 480 / 50 = 9.6 -> 9 interior access points -> 10 segments.
    assert len(plan.segments) == 10
    for seg in plan.segments[:-1]:
        assert seg.duration_min == pytest.approx(50.0)
    # Last (partial) segment is the remainder.
    assert plan.segments[-1].duration_min == pytest.approx(480 - 9 * 50)
    # Every segment shares the same flat target rate (default tolerance).
    assert all(seg.target_g_per_hr_low == 60.0 for seg in plan.segments)


def test_self_carried_only_cx_race_with_warmup_matches_real_expectation():
    """45min warmup + 45min CX race = 90min total exposure, zero external
    access -- the real test case from this build's own brief. Must land at
    60g/h+ (not the naive <2h/30g-h steady reading), a gel-shaped feed at
    the very start, then a small number of self-carried feeds."""
    plan = compute_fueling_plan(
        duration_min=90,
        intensity_class="high_intensity_intermittent",
        access=NoAccess(),
        product_key="maurten_gel_100",
    )
    assert len(plan.segments) == 1
    segment = plan.segments[0]
    assert segment.target_g_per_hr_low >= 60.0
    assert segment.duration_min == 90.0
    # A small number of self-carried feed points, first one at the start
    # (matches "gel at the start, then zero-to-a-few self-carried drinks").
    assert segment.feed_timestamps_min[0] == 0.0
    assert 1 <= len(segment.feed_timestamps_min) <= 4


def test_sparse_irregular_aid_station_100_mile_mtb_shape():
    """100-mile MTB, 5 aid stations, sparse/irregular 1-2.5h gaps --
    a different irregular shape than Skopelos's tighter boat spacing,
    proving the model generalizes rather than being tuned to one case."""
    access = IrregularAccess(access_points_min=(75.0, 220.0, 350.0, 480.0, 630.0))
    plan = compute_fueling_plan(
        duration_min=720,  # 12h total race time
        intensity_class="steady",
        access=access,
        product_key="tailwind",
    )
    assert len(plan.segments) == 6
    durations = [seg.duration_min for seg in plan.segments]
    assert durations == pytest.approx([75.0, 145.0, 130.0, 130.0, 150.0, 90.0])
    # Every segment's carb total is independently derived from its own
    # (shorter) duration at the SAME flat rate -- not re-deriving a new
    # target band per segment.
    for seg, dur in zip(plan.segments, durations):
        assert seg.target_carb_g_low == pytest.approx(60.0 * dur / 60.0)


# ============================================================================
# Carb tolerance clamping (never prescribe above a demonstrated tolerance)
# ============================================================================


def test_explicit_carb_tolerance_above_default_unlocks_higher_band():
    plan = compute_fueling_plan(
        duration_min=600,
        intensity_class="steady",
        access=NoAccess(),
        product_key="formula_369",
        carb_tolerance_g_per_hr=90.0,
    )
    assert plan.carb_tolerance_source == "athlete_set"
    assert plan.segments[0].target_g_per_hr_high == 90.0


def test_low_carb_tolerance_clamps_band_down_and_warns():
    plan = compute_fueling_plan(
        duration_min=600,
        intensity_class="steady",
        access=NoAccess(),
        product_key="formula_369",
        carb_tolerance_g_per_hr=40.0,
    )
    assert plan.segments[0].target_g_per_hr_low == 40.0
    assert plan.segments[0].target_g_per_hr_high == 40.0
    assert any("tolerance" in w.lower() for w in plan.warnings)


# ============================================================================
# Heat: does not silently invent a numeric modifier.
# ============================================================================


def test_heat_flag_does_not_raise_target_but_adds_a_warning():
    baseline = compute_fueling_plan(
        duration_min=90,
        intensity_class="high_intensity_intermittent",
        access=NoAccess(),
        product_key="maurten_gel_100",
        heat=False,
    )
    hot = compute_fueling_plan(
        duration_min=90,
        intensity_class="high_intensity_intermittent",
        access=NoAccess(),
        product_key="maurten_gel_100",
        heat=True,
    )
    assert baseline.segments[0].target_g_per_hr_low == hot.segments[0].target_g_per_hr_low
    assert baseline.segments[0].target_g_per_hr_high == hot.segments[0].target_g_per_hr_high
    assert not baseline.warnings
    assert any("heat" in w.lower() for w in hot.warnings)


# ============================================================================
# Validation
# ============================================================================


def test_unknown_product_key_raises():
    with pytest.raises(ValueError, match="formula_369|maurten_gel_100|tailwind"):
        compute_fueling_plan(
            duration_min=90,
            intensity_class="steady",
            access=NoAccess(),
            product_key="not_a_real_product",
        )


def test_non_positive_duration_raises():
    with pytest.raises(ValueError):
        compute_fueling_plan(
            duration_min=0,
            intensity_class="steady",
            access=NoAccess(),
            product_key="formula_369",
        )


def test_fixed_interval_requires_positive_interval():
    with pytest.raises(ValueError):
        compute_fueling_plan(
            duration_min=90,
            intensity_class="steady",
            access=FixedIntervalAccess(interval_min=0),
            product_key="formula_369",
        )


def test_products_table_has_the_three_verified_products():
    assert set(PRODUCTS) == {"formula_369", "maurten_gel_100", "tailwind"}
    for product in PRODUCTS.values():
        assert product.carb_g_per_serving > 0


# ============================================================================
# Pre-event nutrition as a Session-shaped plan entry (deliverable 5)
# ============================================================================


def test_build_pre_event_nutrition_session_is_session_shaped():
    from uuid import uuid4

    athlete_id = uuid4()
    plan = compute_fueling_plan(
        duration_min=600,
        intensity_class="steady",
        access=IrregularAccess(access_points_min=(90.0, 180.0)),
        product_key="formula_369",
    )
    session = build_pre_event_nutrition_session(
        athlete_id=athlete_id,
        event_date=date(2026, 9, 20),
        plan=plan,
        product_label=PRODUCTS["formula_369"].label,
    )
    assert session.athlete_id == athlete_id
    assert session.date == date(2026, 9, 19)
    assert session.sport == "recovery"
    assert session.source == "ai_coach"
    assert session.duration_min > 0
    assert session.status == "planned"
    assert "Formula 369" in session.structure
    assert session.purpose
