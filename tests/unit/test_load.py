"""Tests for swim_coach.load: sRPE load, volume, monotony, ACWR, wellness
composite, and compliance.

No LLM calls, no network access -- pure arithmetic + model validation.
"""

import uuid
from datetime import date, timedelta

import pytest

from swim_coach.load import (
    ATL_TIME_CONSTANT_DAYS,
    CTL_TIME_CONSTANT_DAYS,
    DEFAULT_RPE_WHEN_MISSING,
    acute_chronic_ratio,
    compliance,
    ctl_atl_tsb_series,
    daily_loads,
    monotony,
    session_load,
    weekly_volume_m,
    wellness_composite,
    wellness_trend,
)
from swim_coach.models import Session, Wellness, Workout

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


# --- session_load ----------------------------------------------------------------


def test_session_load_is_duration_times_rpe():
    workout = make_workout(duration_min=60.0, rpe=7)
    assert session_load(workout) == 420.0


def test_session_load_none_rpe_returns_none_by_default():
    workout = make_workout(rpe=None)
    assert session_load(workout) is None


def test_session_load_none_rpe_with_default_flag_uses_default_rpe():
    workout = make_workout(rpe=None, duration_min=60.0)
    assert session_load(workout, assume_default_rpe=True) == 60.0 * DEFAULT_RPE_WHEN_MISSING


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


def test_daily_loads_excludes_missing_rpe_by_default():
    d = date(2026, 7, 6)
    workouts = [make_workout(date=d, rpe=None)]
    loads = daily_loads(workouts)
    assert d not in loads


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
