"""Tests for swim_coach.load: tiered session load (sRPE / HR-TRIMP /
swim pace-IF / duration-only), volume, monotony, ACWR, wellness composite,
and compliance.

No LLM calls, no network access -- pure arithmetic + model validation.
"""

import math
import uuid
from datetime import date, timedelta

import pytest

from swim_coach.load import (
    ATL_TIME_CONSTANT_DAYS,
    CTL_TIME_CONSTANT_DAYS,
    DURATION_ONLY_ASSUMED_INTENSITY,
    HR_REST_GENERIC_FALLBACK_BPM,
    SWIM_TSS_INTENSITY_EXPONENT,
    TRIMP_FEMALE_COEFFICIENT,
    TRIMP_FEMALE_EXPONENT,
    TRIMP_MALE_COEFFICIENT,
    TRIMP_MALE_EXPONENT,
    WELLNESS_BASELINE_ACUTE_WINDOW_DAYS,
    WELLNESS_BASELINE_CHRONIC_WINDOW_DAYS,
    acute_chronic_ratio,
    compliance,
    ctl_atl_tsb_series,
    daily_loads,
    estimate_hr_max,
    estimate_hr_rest,
    monotony,
    session_load,
    weekly_volume_m,
    wellness_baseline_deviation,
    wellness_composite,
    wellness_trend,
)
from swim_coach.models import Athlete, Session, Wellness, Workout

ATHLETE_ID = uuid.uuid4()


def make_workout(**overrides):
    data = dict(
        id=uuid.uuid4(),
        athlete_id=ATHLETE_ID,
        date=date(2026, 7, 6),
        sport="swim_pool",
        source="manual",
        distance_m=3000,
        duration_min=60.0,
        rpe=6,
    )
    data.update(overrides)
    return Workout(**data)


def make_athlete(**overrides):
    data = dict(
        id=ATHLETE_ID,
        slug="renee",
        name="Renee",
        css_pace_s_per_100m=90.0,
    )
    data.update(overrides)
    return Athlete(**data)


def make_wellness(**overrides):
    data = dict(
        id=uuid.uuid4(),
        athlete_id=ATHLETE_ID,
        date=date(2026, 7, 6),
        sleep_quality=4,
        sleep_hours=7.5,
        stress=2,
        soreness=2,
        motivation=4,
    )
    data.update(overrides)
    return Wellness(**data)


def make_session(**overrides):
    data = dict(
        id=uuid.uuid4(),
        athlete_id=ATHLETE_ID,
        date=date(2026, 7, 6),
        sport="swim_pool",
        source="pool_coach",
        duration_min=60.0,
        distance_m=3000,
        intensity={"anchor": "rpe"},
        purpose="test",
    )
    data.update(overrides)
    return Session(**data)


# --- session_load: tier 1 (sRPE) --------------------------------------------------


def test_session_load_is_duration_times_rpe():
    workout = make_workout(duration_min=60.0, rpe=7)
    result = session_load(workout)
    assert result.tier == "srpe"
    assert result.value == 420.0


def test_session_load_srpe_wins_even_when_hr_and_pace_context_also_available():
    # RPE is the highest-fidelity signal -- if it's logged, it's used,
    # regardless of what other context the caller also happens to pass.
    workout = make_workout(rpe=7, duration_min=60.0, avg_hr=150, avg_pace_s_per_100m=85.0)
    result = session_load(
        workout, hr_max=190.0, hr_rest=50.0, sex="female", css_pace_s_per_100m=90.0
    )
    assert result.tier == "srpe"
    assert result.value == 420.0


# --- session_load: tier 2 (HR-based TRIMP) ------------------------------------------


def test_session_load_hr_trimp_worked_example_female():
    # Banister HRR-fraction TRIMP, female coefficients: weight(x) =
    # 0.86 * e^(1.67*x). avg_hr=150, hr_rest=50, hr_max=190 ->
    # HRR_fraction = 100/140 = 0.714285...
    workout = make_workout(rpe=None, duration_min=60.0, avg_hr=150, avg_pace_s_per_100m=None)
    result = session_load(workout, hr_max=190.0, hr_rest=50.0, sex="female")
    hrr_fraction = (150 - 50) / (190 - 50)
    weight = TRIMP_FEMALE_COEFFICIENT * math.exp(TRIMP_FEMALE_EXPONENT * hrr_fraction)
    expected = 60.0 * hrr_fraction * weight
    assert result.tier == "hr_trimp"
    assert result.value == pytest.approx(expected)
    assert result.value == pytest.approx(121.499, abs=0.01)


def test_session_load_hr_trimp_worked_example_male():
    workout = make_workout(rpe=None, duration_min=60.0, avg_hr=150, avg_pace_s_per_100m=None)
    result = session_load(workout, hr_max=190.0, hr_rest=50.0, sex="male")
    hrr_fraction = (150 - 50) / (190 - 50)
    weight = TRIMP_MALE_COEFFICIENT * math.exp(TRIMP_MALE_EXPONENT * hrr_fraction)
    expected = 60.0 * hrr_fraction * weight
    assert result.tier == "hr_trimp"
    assert result.value == pytest.approx(expected)
    assert result.value == pytest.approx(108.095, abs=0.01)


def test_session_load_hr_trimp_male_and_female_coefficients_differ():
    # Guards against the common bug this project explicitly flagged: some
    # sites apply the MALE 0.64 coefficient to both sexes and only swap the
    # exponent. If that bug crept in here, the male and female results
    # would use the same coefficient and this pair would only differ via
    # the exponent -- assert the actual constants themselves are distinct.
    assert TRIMP_MALE_COEFFICIENT != TRIMP_FEMALE_COEFFICIENT
    assert TRIMP_MALE_EXPONENT != TRIMP_FEMALE_EXPONENT
    workout = make_workout(rpe=None, duration_min=60.0, avg_hr=150)
    male = session_load(workout, hr_max=190.0, hr_rest=50.0, sex="male")
    female = session_load(workout, hr_max=190.0, hr_rest=50.0, sex="female")
    assert male.value != pytest.approx(female.value)


def test_session_load_hr_trimp_defaults_to_averaged_weighting_when_sex_unknown():
    # No sex on file (Athlete.sex is None) must not silently assume one --
    # average the two sex-specific curves as a documented neutral default.
    workout = make_workout(rpe=None, duration_min=60.0, avg_hr=150)
    result = session_load(workout, hr_max=190.0, hr_rest=50.0, sex=None)
    hrr_fraction = (150 - 50) / (190 - 50)
    male_weight = TRIMP_MALE_COEFFICIENT * math.exp(TRIMP_MALE_EXPONENT * hrr_fraction)
    female_weight = TRIMP_FEMALE_COEFFICIENT * math.exp(TRIMP_FEMALE_EXPONENT * hrr_fraction)
    expected = 60.0 * hrr_fraction * (male_weight + female_weight) / 2
    assert result.tier == "hr_trimp"
    assert result.value == pytest.approx(expected)


def test_session_load_hr_trimp_higher_effort_produces_higher_load():
    easy = make_workout(rpe=None, duration_min=60.0, avg_hr=120)
    hard = make_workout(rpe=None, duration_min=60.0, avg_hr=170)
    easy_result = session_load(easy, hr_max=190.0, hr_rest=50.0, sex="female")
    hard_result = session_load(hard, hr_max=190.0, hr_rest=50.0, sex="female")
    assert hard_result.value > easy_result.value


def test_session_load_hr_present_but_no_hrmax_context_falls_through_to_next_tier():
    # avg_hr alone isn't enough -- without a usable hr_max/hr_rest, tier 2
    # can't fire, so this must fall through (here: to tier 3, pace+CSS).
    workout = make_workout(rpe=None, duration_min=60.0, avg_hr=150, avg_pace_s_per_100m=85.0)
    result = session_load(workout, css_pace_s_per_100m=90.0)
    assert result.tier == "pace_if"


def test_session_load_hr_trimp_preferred_over_pace_when_both_available():
    workout = make_workout(rpe=None, duration_min=60.0, avg_hr=150, avg_pace_s_per_100m=85.0)
    result = session_load(
        workout, hr_max=190.0, hr_rest=50.0, sex="female", css_pace_s_per_100m=90.0
    )
    assert result.tier == "hr_trimp"


# --- session_load: tier 3 (swim pace-based intensity) -------------------------------


def test_session_load_pace_tier_worked_example():
    # IF = css_pace / avg_pace = 90/85 (a *lower* pace value is faster);
    # swim_tss = duration_hours * IF^3 * 100.
    workout = make_workout(
        rpe=None, duration_min=60.0, avg_hr=None, avg_pace_s_per_100m=85.0, sport="swim_pool"
    )
    result = session_load(workout, css_pace_s_per_100m=90.0)
    intensity_factor = 90.0 / 85.0
    expected = (60.0 / 60.0) * intensity_factor**SWIM_TSS_INTENSITY_EXPONENT * 100.0
    assert result.tier == "pace_if"
    assert result.value == pytest.approx(expected)
    assert result.value == pytest.approx(118.705, abs=0.01)


def test_session_load_pace_tier_faster_swim_produces_higher_load_than_slower():
    # Direction check: pace_s_per_100m is a TIME value, so LOWER = FASTER.
    # A faster swim of the same duration must score a HIGHER load, not
    # lower -- this is the exact bug the IF direction could get backwards.
    fast = make_workout(
        rpe=None, duration_min=60.0, avg_hr=None, avg_pace_s_per_100m=80.0, sport="swim_pool"
    )
    slow = make_workout(
        rpe=None, duration_min=60.0, avg_hr=None, avg_pace_s_per_100m=100.0, sport="swim_pool"
    )
    fast_result = session_load(fast, css_pace_s_per_100m=90.0)
    slow_result = session_load(slow, css_pace_s_per_100m=90.0)
    assert fast_result.tier == slow_result.tier == "pace_if"
    assert fast_result.value > slow_result.value


def test_session_load_pace_tier_requires_swim_sport():
    # A non-swim sport with a (meaningless) avg_pace_s_per_100m must not
    # use tier 3 -- falls through to duration-only instead.
    workout = make_workout(
        rpe=None,
        duration_min=45.0,
        avg_hr=None,
        avg_pace_s_per_100m=85.0,
        sport="strength",
        distance_m=0,
    )
    result = session_load(workout, css_pace_s_per_100m=90.0)
    assert result.tier == "duration"


def test_session_load_pace_tier_requires_known_css():
    workout = make_workout(
        rpe=None, duration_min=60.0, avg_hr=None, avg_pace_s_per_100m=85.0, sport="swim_pool"
    )
    result = session_load(workout)  # no css_pace_s_per_100m passed
    assert result.tier == "duration"


# --- session_load: tier 4 (duration-only fallback) -----------------------------------


def test_session_load_duration_only_fallback_when_no_signal_available():
    workout = make_workout(
        rpe=None,
        duration_min=45.0,
        avg_hr=None,
        avg_pace_s_per_100m=None,
        sport="strength",
        distance_m=0,
    )
    result = session_load(workout)
    assert result.tier == "duration"
    assert result.value == pytest.approx(45.0 * DURATION_ONLY_ASSUMED_INTENSITY)


def test_session_load_never_returns_none():
    # The core bug being fixed: every tier -- including the last one --
    # must produce a real number, never None.
    workout = make_workout(
        rpe=None,
        avg_hr=None,
        avg_pace_s_per_100m=None,
        sport="recovery",
        distance_m=0,
    )
    result = session_load(workout)
    assert result.value is not None
    assert result.value > 0.0


# --- estimate_hr_max / estimate_hr_rest -----------------------------------------------


def test_estimate_hr_max_returns_highest_observed_across_history():
    workouts = [
        make_workout(max_hr=165),
        make_workout(max_hr=182),
        make_workout(max_hr=170),
    ]
    assert estimate_hr_max(workouts) == 182.0


def test_estimate_hr_max_none_when_never_logged():
    workouts = [make_workout(max_hr=None)]
    assert estimate_hr_max(workouts) is None


def test_estimate_hr_rest_averages_recent_readings():
    as_of = date(2026, 7, 10)
    wellness = [
        make_wellness(date=as_of - timedelta(days=1), resting_hr=48),
        make_wellness(date=as_of - timedelta(days=2), resting_hr=50),
    ]
    assert estimate_hr_rest(wellness, as_of) == pytest.approx((48 + 50) / 2)


def test_estimate_hr_rest_falls_back_to_generic_when_never_logged():
    assert estimate_hr_rest([], date(2026, 7, 10)) == HR_REST_GENERIC_FALLBACK_BPM


def test_estimate_hr_rest_ignores_readings_after_as_of():
    as_of = date(2026, 7, 10)
    wellness = [make_wellness(date=as_of + timedelta(days=1), resting_hr=40)]
    assert estimate_hr_rest(wellness, as_of) == HR_REST_GENERIC_FALLBACK_BPM


def test_estimate_hr_rest_limits_to_lookback_readings():
    as_of = date(2026, 7, 20)
    # 6 readings available, lookback default is 5 -- the oldest (offset 6,
    # resting_hr=100 -- a deliberate outlier) must NOT be included.
    wellness = [make_wellness(date=as_of - timedelta(days=i), resting_hr=50) for i in range(5)]
    wellness.append(make_wellness(date=as_of - timedelta(days=6), resting_hr=100))
    assert estimate_hr_rest(wellness, as_of, lookback_readings=5) == pytest.approx(50.0)


# --- weekly_volume_m ---------------------------------------------------------------


def test_weekly_volume_m_sums_swim_distance_in_window():
    week_start = date(2026, 7, 6)  # Monday
    workouts = [
        make_workout(date=week_start, distance_m=3000, sport="swim_pool"),
        make_workout(date=week_start + timedelta(days=3), distance_m=15000, sport="swim_ow"),
        make_workout(date=week_start + timedelta(days=7), distance_m=9999, sport="swim_pool"),  # next week
    ]
    assert weekly_volume_m(workouts, week_start) == 18000


def test_weekly_volume_m_excludes_non_swim_sports():
    week_start = date(2026, 7, 6)
    workouts = [
        make_workout(date=week_start, sport="swim_pool", distance_m=3000),
        make_workout(date=week_start, sport="strength", distance_m=0, duration_min=45.0),
    ]
    assert weekly_volume_m(workouts, week_start) == 3000


def test_weekly_volume_m_excludes_cross_train_distance():
    # A cross_train session (kayak, run, ride) may carry a real distance_m
    # from a .fit import; that distance must never count as swim volume.
    week_start = date(2026, 7, 6)
    workouts = [
        make_workout(date=week_start, sport="swim_pool", distance_m=3000),
        make_workout(date=week_start, sport="cross_train", distance_m=11494, duration_min=303.0),
    ]
    assert weekly_volume_m(workouts, week_start) == 3000


def test_daily_loads_includes_cross_train_srpe():
    # sRPE load is sport-agnostic: a 5-hour paddle at RPE 4 is real stress
    # the load math must see even though it adds no swim volume.
    d = date(2026, 7, 6)
    workouts = [
        make_workout(date=d, duration_min=60.0, rpe=5),
        make_workout(date=d, duration_min=303.0, rpe=4, sport="cross_train", distance_m=11494),
    ]
    loads = daily_loads(workouts)
    assert loads[d] == 60.0 * 5 + 303.0 * 4


# --- daily_loads -------------------------------------------------------------------


def test_daily_loads_sums_multiple_workouts_same_day():
    d = date(2026, 7, 6)
    workouts = [
        make_workout(date=d, duration_min=60.0, rpe=5),
        make_workout(date=d, duration_min=30.0, rpe=8, sport="strength"),
    ]
    loads = daily_loads(workouts)
    assert loads[d] == 60.0 * 5 + 30.0 * 8


def test_daily_loads_no_longer_excludes_missing_rpe_workouts():
    # This is the core bug this task fixes: an RPE-less workout used to be
    # silently excluded from the day's total (equivalent to zero). It now
    # falls through to a real tiered estimate instead of vanishing.
    d = date(2026, 7, 6)
    workouts = [
        make_workout(
            date=d, rpe=None, duration_min=45.0, avg_hr=None, avg_pace_s_per_100m=None, sport="strength"
        )
    ]
    loads = daily_loads(workouts)
    assert d in loads
    assert loads[d] == pytest.approx(45.0 * DURATION_ONLY_ASSUMED_INTENSITY)


def test_daily_loads_regression_renee_hr_only_workouts_no_longer_total_zero():
    # Matches Renee's real, confirmed situation: 62 of 63 real logged
    # workouts have no RPE but do have avg_hr from device telemetry. Under
    # the old behavior, a day with only such workouts totaled 0 (excluded
    # entirely from CTL/ATL/TSB, ACWR, monotony). It must now total a real,
    # positive number reflecting the actual HR-based tiered load.
    d = date(2026, 7, 6)
    athlete = make_athlete(sex="female")
    workouts = [
        make_workout(
            date=d, rpe=None, duration_min=60.0, avg_hr=150, max_hr=185, sport="swim_pool"
        ),
        make_workout(
            date=d, rpe=None, duration_min=30.0, avg_hr=120, max_hr=160, sport="strength", distance_m=0
        ),
    ]
    wellness = [make_wellness(date=d, resting_hr=50)]

    old_behavior_total = 0.0  # what daily_loads used to report for this day
    loads = daily_loads(workouts, athlete=athlete, wellness=wellness)

    assert d in loads
    assert loads[d] > old_behavior_total
    # Sanity: both workouts should have actually resolved via HR-based
    # TRIMP (real HR + a derivable hr_max from history + a logged
    # resting_hr), not silently dropped to duration-only.
    hr_max = estimate_hr_max(workouts)
    hr_rest = estimate_hr_rest(wellness, d)
    expected = sum(
        session_load(
            w, hr_max=hr_max, hr_rest=hr_rest, sex=athlete.sex, css_pace_s_per_100m=athlete.css_pace_s_per_100m
        ).value
        for w in workouts
    )
    assert loads[d] == pytest.approx(expected)
    for w in workouts:
        assert (
            session_load(
                w,
                hr_max=hr_max,
                hr_rest=hr_rest,
                sex=athlete.sex,
                css_pace_s_per_100m=athlete.css_pace_s_per_100m,
            ).tier
            == "hr_trimp"
        )


def test_daily_loads_without_athlete_or_wellness_still_uses_srpe_and_duration_tiers():
    # Backward-compatible default: a caller with only workouts on hand
    # (no athlete/wellness) still gets tier 1 and tier 4 correctly -- it
    # just can't unlock tiers 2/3 for RPE-less workouts without that
    # context.
    d = date(2026, 7, 6)
    workouts = [
        make_workout(date=d, duration_min=60.0, rpe=5),
        make_workout(date=d, duration_min=30.0, rpe=8, sport="strength"),
    ]
    loads = daily_loads(workouts)
    assert loads[d] == 60.0 * 5 + 30.0 * 8


# --- monotony ------------------------------------------------------------------------


def test_monotony_is_mean_over_stdev():
    daily = {
        date(2026, 7, 6): 300.0,
        date(2026, 7, 7): 400.0,
        date(2026, 7, 8): 200.0,
    }
    import statistics

    expected = statistics.mean(daily.values()) / statistics.stdev(daily.values())
    assert monotony(daily) == pytest.approx(expected)


def test_monotony_none_when_fewer_than_two_days():
    assert monotony({date(2026, 7, 6): 300.0}) is None
    assert monotony({}) is None


def test_monotony_none_when_zero_variation():
    daily = {date(2026, 7, 6): 300.0, date(2026, 7, 7): 300.0}
    assert monotony(daily) is None


# --- acute_chronic_ratio -------------------------------------------------------------


def test_acute_chronic_ratio_one_when_load_is_steady():
    as_of = date(2026, 7, 28)
    workouts = [
        make_workout(date=as_of - timedelta(days=i), duration_min=60.0, rpe=5)
        for i in range(28)
    ]
    ratio = acute_chronic_ratio(workouts, as_of)
    assert ratio == pytest.approx(1.0)


def test_acute_chronic_ratio_above_one_on_load_spike():
    as_of = date(2026, 7, 28)
    # quiet chronic window, big acute week
    workouts = [
        make_workout(date=as_of - timedelta(days=i), duration_min=30.0, rpe=3)
        for i in range(28)
    ]
    workouts += [
        make_workout(date=as_of - timedelta(days=i), duration_min=90.0, rpe=8)
        for i in range(7)
    ]
    ratio = acute_chronic_ratio(workouts, as_of)
    assert ratio > 1.4


def test_acute_chronic_ratio_none_when_no_chronic_load():
    assert acute_chronic_ratio([], date(2026, 7, 28)) is None


def test_acute_chronic_ratio_forwards_athlete_and_wellness_context():
    # Plumbing/call-site correctness: acute_chronic_ratio must forward
    # athlete/wellness through to daily_loads unchanged, not silently drop
    # them on the floor (the exact bug this task's audit is checking for).
    as_of = date(2026, 7, 28)
    athlete = make_athlete(sex="male")
    workouts = [
        make_workout(
            date=as_of - timedelta(days=i), rpe=None, duration_min=60.0, avg_hr=140, max_hr=185
        )
        for i in range(28)
    ]
    wellness = [make_wellness(date=as_of - timedelta(days=i), resting_hr=48) for i in range(28)]

    ratio = acute_chronic_ratio(workouts, as_of, athlete=athlete, wellness=wellness)
    loads = daily_loads(workouts, athlete=athlete, wellness=wellness)
    acute = sum(loads.get(as_of - timedelta(days=i), 0.0) for i in range(7))
    chronic_sum = sum(loads.get(as_of - timedelta(days=i), 0.0) for i in range(28))
    expected = acute / (chronic_sum / 4)
    assert ratio == pytest.approx(expected)

    # sex="male" + a real logged resting_hr=48 must actually reach the
    # HR-TRIMP formula through this call path (not just when daily_loads is
    # called directly) -- proven by the per-day load differing from the
    # no-athlete/no-wellness default (sex=None averaged weighting,
    # hr_rest falling back to HR_REST_GENERIC_FALLBACK_BPM=60).
    loads_no_context = daily_loads(workouts)
    assert loads[as_of] != pytest.approx(loads_no_context[as_of])


# --- wellness_composite / wellness_trend --------------------------------------------


def test_wellness_composite_all_good_scores_five():
    w = make_wellness(sleep_quality=5, stress=1, soreness=1, motivation=5)
    assert wellness_composite(w) == 5.0


def test_wellness_composite_all_bad_scores_one():
    w = make_wellness(sleep_quality=1, stress=5, soreness=5, motivation=1)
    assert wellness_composite(w) == 1.0


def test_wellness_composite_in_range():
    w = make_wellness(sleep_quality=3, stress=3, soreness=3, motivation=3)
    assert 1.0 <= wellness_composite(w) <= 5.0


def test_wellness_trend_sorted_by_date():
    entries = [
        make_wellness(date=date(2026, 7, 8)),
        make_wellness(date=date(2026, 7, 6)),
        make_wellness(date=date(2026, 7, 7)),
    ]
    trend = wellness_trend(entries)
    assert [d for d, _ in trend] == [date(2026, 7, 6), date(2026, 7, 7), date(2026, 7, 8)]


@pytest.mark.parametrize("missing_field", ["sleep_quality", "stress", "soreness", "motivation"])
def test_wellness_composite_none_when_any_subjective_field_missing(missing_field):
    # Never derive a fabricated composite from a partial subjective set --
    # same "honest None over fabricated number" convention as monotony()/
    # wellness_baseline_deviation().
    w = make_wellness(**{missing_field: None})
    assert wellness_composite(w) is None


def test_wellness_composite_none_even_with_objective_data_present():
    # A sync-only row (resting_hr/hrv populated, no subjective fields at all)
    # must not produce a composite -- objective data cannot substitute for a
    # subjective rating.
    w = make_wellness(
        sleep_quality=None,
        stress=None,
        soreness=None,
        motivation=None,
        resting_hr=52,
        hrv=61.0,
    )
    assert wellness_composite(w) is None


def test_wellness_trend_excludes_sync_only_entries():
    entries = [
        make_wellness(date=date(2026, 7, 6)),
        make_wellness(
            date=date(2026, 7, 7),
            sleep_quality=None,
            stress=None,
            soreness=None,
            motivation=None,
            resting_hr=50,
        ),
        make_wellness(date=date(2026, 7, 8)),
    ]
    trend = wellness_trend(entries)
    assert [d for d, _ in trend] == [date(2026, 7, 6), date(2026, 7, 8)]


def test_wellness_trend_stays_sorted_with_entries_filtered():
    entries = [
        make_wellness(date=date(2026, 7, 9)),
        make_wellness(
            date=date(2026, 7, 6),
            sleep_quality=None,
            stress=None,
            soreness=None,
            motivation=None,
        ),
        make_wellness(date=date(2026, 7, 8)),
        make_wellness(
            date=date(2026, 7, 7),
            sleep_quality=None,
            stress=None,
            soreness=None,
            motivation=None,
        ),
    ]
    trend = wellness_trend(entries)
    assert [d for d, _ in trend] == [date(2026, 7, 8), date(2026, 7, 9)]


# --- ctl_atl_tsb_series ----------------------------------------------------------------


def test_ctl_atl_tsb_series_empty_input_returns_empty_series():
    assert ctl_atl_tsb_series({}) == []


def test_ctl_atl_tsb_series_single_day_matches_recursion_with_zero_seed():
    # CTL_0 = ATL_0 = 0 seeded *before* the range, so the first returned
    # point already reflects one recursion step against that zero seed:
    # ctl = 0 + (load - 0) / tau, same for atl. Uses non-default taus to
    # confirm the function isn't hardcoded to the module constants.
    d = date(2026, 7, 6)
    series = ctl_atl_tsb_series({d: 50.0}, ctl_tau_days=10, atl_tau_days=2)
    assert series == [(d, pytest.approx(5.0), pytest.approx(25.0), pytest.approx(-20.0))]


def test_ctl_atl_tsb_series_covers_full_date_range_including_zero_days():
    # A day with no logged load counts as zero, same convention as
    # daily_loads/monotony elsewhere in this module -- the series must
    # include every calendar day spanned, not just the days with an entry.
    start = date(2026, 7, 1)
    end = date(2026, 7, 5)
    daily = {start: 100.0, end: 100.0}
    series = ctl_atl_tsb_series(daily)
    assert [d for d, _, _, _ in series] == [start + timedelta(days=i) for i in range(5)]


def test_ctl_atl_tsb_series_constant_load_converges_ctl_and_atl_with_tsb_near_zero():
    d0 = date(2026, 1, 1)
    load = 300.0
    days = 400  # several multiples of the longer (42-day) time constant
    daily = {d0 + timedelta(days=i): load for i in range(days)}
    series = ctl_atl_tsb_series(daily)
    last_date, ctl, atl, tsb = series[-1]
    assert last_date == d0 + timedelta(days=days - 1)
    assert ctl == pytest.approx(load, abs=0.5)
    assert atl == pytest.approx(load, abs=0.01)
    assert tsb == pytest.approx(0.0, abs=0.5)


def test_ctl_atl_tsb_series_load_spike_after_quiet_period_dips_tsb_negative():
    # ATL's shorter time constant should respond to a sudden spike much
    # faster than CTL's -- TSB should dip clearly negative right after it.
    start = date(2026, 1, 1)
    spike_day = start + timedelta(days=60)
    daily = {start: 0.0, spike_day: 500.0}
    series = ctl_atl_tsb_series(daily)
    spike_date, ctl, atl, tsb = series[-1]
    assert spike_date == spike_day
    # Both CTL/ATL were ~0 going into the spike day (60 quiet days first),
    # so this reduces to one recursion step from a zero seed.
    assert ctl == pytest.approx(500.0 / CTL_TIME_CONSTANT_DAYS)
    assert atl == pytest.approx(500.0 / ATL_TIME_CONSTANT_DAYS)
    assert atl > ctl
    assert tsb < 0


# --- wellness_baseline_deviation ------------------------------------------------------


def test_wellness_baseline_deviation_none_when_no_data_at_all():
    result = wellness_baseline_deviation([], date(2026, 7, 28))
    assert result == {"resting_hr_pct_deviation": None, "hrv_pct_deviation": None}


def test_wellness_baseline_deviation_none_when_only_chronic_data_no_recent_acute():
    # Entries exist inside the 28-day chronic window (offsets 10-20 days
    # back) but none inside the most recent 7-day acute window -- must not
    # report a stale/misleading deviation number just because *some*
    # baseline history exists.
    as_of = date(2026, 7, 28)
    entries = [
        make_wellness(date=as_of - timedelta(days=i), resting_hr=50, hrv=60.0)
        for i in range(10, 21)
    ]
    result = wellness_baseline_deviation(entries, as_of)
    assert result == {"resting_hr_pct_deviation": None, "hrv_pct_deviation": None}


def test_wellness_baseline_deviation_resting_hr_elevation_is_positive():
    # 21 older days (offsets 7-27) at RHR=44, most recent 7 days
    # (offsets 0-6) at RHR=60. Chronic window is coupled (includes the
    # acute days), same shape as acute_chronic_ratio:
    #   chronic_mean = (21*44 + 7*60) / 28 = 48
    #   acute_mean = 60
    #   pct_deviation = (60 - 48) / 48 * 100 = +25.0
    as_of = date(2026, 7, 28)
    entries = [
        make_wellness(date=as_of - timedelta(days=i), resting_hr=44, hrv=None)
        for i in range(7, 28)
    ] + [
        make_wellness(date=as_of - timedelta(days=i), resting_hr=60, hrv=None)
        for i in range(0, 7)
    ]
    result = wellness_baseline_deviation(entries, as_of)
    assert result["resting_hr_pct_deviation"] == pytest.approx(25.0)
    # No hrv logged at all -- must stay None independently of resting_hr.
    assert result["hrv_pct_deviation"] is None


def test_wellness_baseline_deviation_hrv_suppression_is_negative():
    # 21 older days (offsets 7-27) at HRV=52.0, most recent 7 days
    # (offsets 0-6) at HRV=36.0:
    #   chronic_mean = (21*52 + 7*36) / 28 = 48
    #   acute_mean = 36
    #   pct_deviation = (36 - 48) / 48 * 100 = -25.0
    as_of = date(2026, 7, 28)
    entries = [
        make_wellness(date=as_of - timedelta(days=i), resting_hr=None, hrv=52.0)
        for i in range(7, 28)
    ] + [
        make_wellness(date=as_of - timedelta(days=i), resting_hr=None, hrv=36.0)
        for i in range(0, 7)
    ]
    result = wellness_baseline_deviation(entries, as_of)
    assert result["hrv_pct_deviation"] == pytest.approx(-25.0)
    assert result["resting_hr_pct_deviation"] is None


def test_wellness_baseline_deviation_near_zero_when_stable():
    as_of = date(2026, 7, 28)
    entries = [
        make_wellness(date=as_of - timedelta(days=i), resting_hr=50, hrv=60.0)
        for i in range(0, 28)
    ]
    result = wellness_baseline_deviation(entries, as_of)
    assert result["resting_hr_pct_deviation"] == pytest.approx(0.0, abs=1e-9)
    assert result["hrv_pct_deviation"] == pytest.approx(0.0, abs=1e-9)


def test_wellness_baseline_deviation_custom_windows_are_respected():
    # Non-default window sizes are honored, not hardcoded to the module
    # constants -- same convention ctl_atl_tsb_series's tests use.
    as_of = date(2026, 7, 10)
    entries = [
        make_wellness(date=as_of - timedelta(days=i), resting_hr=40, hrv=None)
        for i in range(1, 9)
    ] + [
        make_wellness(date=as_of, resting_hr=50, hrv=None),
    ]
    result = wellness_baseline_deviation(entries, as_of, acute_window_days=1, chronic_window_days=9)
    # chronic_mean = (8*40 + 50) / 9 = 41.111...; acute_mean = 50.
    expected_chronic = (8 * 40 + 50) / 9
    expected = (50 - expected_chronic) / expected_chronic * 100
    assert result["resting_hr_pct_deviation"] == pytest.approx(expected)


def test_wellness_baseline_deviation_default_windows_match_acwr_windows():
    # Documented as a deliberate consistency choice with acute_chronic_ratio,
    # not independent tuning -- see load.py's module comment.
    assert WELLNESS_BASELINE_ACUTE_WINDOW_DAYS == 7
    assert WELLNESS_BASELINE_CHRONIC_WINDOW_DAYS == 28


# --- compliance ----------------------------------------------------------------------


def test_compliance_100_pct_when_exact_match():
    planned = [make_session(distance_m=5000)]
    workouts = [make_workout(distance_m=5000)]
    assert compliance(planned, workouts) == pytest.approx(100.0)


def test_compliance_below_100_when_under_delivered():
    planned = [make_session(distance_m=10000)]
    workouts = [make_workout(distance_m=5000)]
    assert compliance(planned, workouts) == pytest.approx(50.0)


def test_compliance_can_exceed_100_when_over_delivered():
    planned = [make_session(distance_m=5000)]
    workouts = [make_workout(distance_m=7500)]
    assert compliance(planned, workouts) == pytest.approx(150.0)


def test_compliance_zero_when_nothing_planned():
    assert compliance([], [make_workout(distance_m=5000)]) == 0.0


def test_compliance_ignores_non_swim_sessions_and_workouts():
    planned = [
        make_session(distance_m=5000, sport="swim_pool"),
        make_session(distance_m=None, sport="strength", duration_min=45.0),
    ]
    workouts = [
        make_workout(distance_m=5000, sport="swim_pool"),
        make_workout(distance_m=0, sport="strength", duration_min=45.0),
    ]
    assert compliance(planned, workouts) == pytest.approx(100.0)
