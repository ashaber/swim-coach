"""Tests for swim_coach.adapt: the deterministic adaptation rule table +
event-format-aware long-swim ladder.

No LLM calls, no network access -- pure arithmetic + model validation.
"""

import json
import uuid
from datetime import date, timedelta

import pytest

from swim_coach.adapt import (
    COMPLIANCE_ADVANCE_THRESHOLD,
    CUT_VOLUME_FRACTION,
    LOAD_RATIO_RED_THRESHOLD,
    RECOVERY_DAYS_AFTER_MILESTONE_MIN,
    SINGLE_DAY_PEAK_SHARE_MAX,
    SINGLE_SESSION_STEP_CAP,
    STAGE_LONGEST_DAY_SHARE_MAX,
    WELLNESS_RED_THRESHOLD,
    adapt_week,
)
from swim_coach.models import Athlete, Event, Wellness, Workout
from swim_coach.plan import WEEKLY_VOLUME_RAMP_CAP, generate_week, scaffold_macro

ATHLETE_ID = uuid.uuid4()
START = date(2026, 1, 5)  # a Monday


def make_athlete(**overrides):
    data = dict(
        id=ATHLETE_ID,
        slug="wife",
        name="Jane Doe",
        css_pace_s_per_100m=95.0,
        zones=None,
        constraints={},
        pool_schedule=["tue", "thu", "fri"],
    )
    data.update(overrides)
    return Athlete(**data)


def make_event(**overrides):
    data = dict(
        id=uuid.uuid4(),
        athlete_id=ATHLETE_ID,
        name="Greece Ultra Swim",
        event_date=START + timedelta(weeks=24),
        distance_m=33300,
        water_temp_c=24.0,
        wetsuit=False,
        priority="A",
        event_format="single_day",
    )
    data.update(overrides)
    return Event(**data)


def make_workout(**overrides):
    data = dict(
        id=uuid.uuid4(),
        athlete_id=ATHLETE_ID,
        date=date(2026, 1, 10),
        sport="swim_ow",
        source="manual",
        distance_m=5000,
        duration_min=90.0,
        rpe=5,
    )
    data.update(overrides)
    return Workout(**data)


def make_wellness(**overrides):
    data = dict(
        id=uuid.uuid4(),
        athlete_id=ATHLETE_ID,
        date=date(2026, 1, 10),
        sleep_quality=4,
        sleep_hours=7.5,
        stress=2,
        soreness=2,
        motivation=4,
    )
    data.update(overrides)
    return Wellness(**data)


def _iso_week(d: date) -> str:
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def _setup(event_format="single_day", current_volume=14000, peak_volume=20000):
    """athlete, macro, current_week (a real generated week), next_week_start."""
    athlete = make_athlete()
    event = make_event(event_format=event_format)
    macro = scaffold_macro(
        athlete, event, START, current_weekly_volume_m=current_volume, peak_weekly_volume_m=peak_volume
    )
    # Week index 2 of the base block -- comfortably inside the macro, with
    # room for a "next week" still inside the same block.
    current_week_start = macro.blocks[0].start_date + timedelta(weeks=2)
    current_week = generate_week(
        athlete, macro, _iso_week(current_week_start), current_week_start, event_format=event_format
    )
    next_week_start = current_week_start + timedelta(weeks=1)
    next_iso = _iso_week(next_week_start)
    as_of = next_week_start - timedelta(days=1)
    return athlete, event, macro, current_week, next_iso, next_week_start, as_of


def _rationale(week):
    return json.loads(week.adaptation_rationale)


# --- cut: wellness red -------------------------------------------------------------


def test_cut_when_wellness_red():
    athlete, event, macro, current_week, next_iso, next_start, as_of = _setup()
    wellness = [
        make_wellness(date=as_of - timedelta(days=i), sleep_quality=1, stress=5, soreness=5, motivation=1)
        for i in range(7)
    ]
    week = adapt_week(athlete, event, macro, next_iso, next_start, current_week, [], wellness, as_of)

    rationale = _rationale(week)
    assert rationale["action"] == "cut"
    assert week.draft is True
    assert week.target_volume_m == round(current_week.target_volume_m * (1 - CUT_VOLUME_FRACTION))


def test_cut_holds_long_swim_at_previous_distance():
    athlete, event, macro, current_week, next_iso, next_start, as_of = _setup()
    wellness = [
        make_wellness(date=as_of - timedelta(days=i), sleep_quality=1, stress=5, soreness=5, motivation=1)
        for i in range(7)
    ]
    week = adapt_week(athlete, event, macro, next_iso, next_start, current_week, [], wellness, as_of)

    prev_long_swim = next(
        s.distance_m for s in current_week.sessions if s.sport == "swim_ow" and s.date.weekday() == 5
    )
    next_long_swim = next(
        s.distance_m for s in week.sessions if s.sport == "swim_ow" and s.date.weekday() == 5
    )
    # Held, not advanced -- may be trimmed if it no longer fits the (smaller)
    # cut target volume, but never bigger than before.
    assert next_long_swim <= prev_long_swim


def test_cut_adds_a_recovery_day():
    athlete, event, macro, current_week, next_iso, next_start, as_of = _setup()
    wellness = [
        make_wellness(date=as_of - timedelta(days=i), sleep_quality=1, stress=5, soreness=5, motivation=1)
        for i in range(7)
    ]
    week = adapt_week(athlete, event, macro, next_iso, next_start, current_week, [], wellness, as_of)

    recovery_count = sum(1 for s in week.sessions if s.sport == "recovery")
    strength_count = sum(1 for s in week.sessions if s.sport == "strength")
    baseline_recovery = sum(1 for s in current_week.sessions if s.sport == "recovery")
    baseline_strength = sum(1 for s in current_week.sessions if s.sport == "strength")
    assert recovery_count == baseline_recovery + 1
    assert strength_count == baseline_strength - 1


# --- cut: load ratio red -------------------------------------------------------------


def test_cut_when_load_ratio_red():
    athlete, event, macro, current_week, next_iso, next_start, as_of = _setup()
    # quiet chronic 28d window, huge acute week -> ratio spikes above threshold
    workouts = [
        make_workout(date=as_of - timedelta(days=i), duration_min=20.0, rpe=3) for i in range(28)
    ]
    workouts += [
        make_workout(date=as_of - timedelta(days=i), duration_min=120.0, rpe=8) for i in range(7)
    ]
    good_wellness = [make_wellness(date=as_of - timedelta(days=i)) for i in range(7)]
    week = adapt_week(
        athlete, event, macro, next_iso, next_start, current_week, workouts, good_wellness, as_of
    )
    rationale = _rationale(week)
    assert rationale["action"] == "cut"
    assert rationale["signals"]["load_ratio_7d_28d"] > LOAD_RATIO_RED_THRESHOLD


# --- repeat: low compliance -----------------------------------------------------------


def test_repeat_when_compliance_low():
    athlete, event, macro, current_week, next_iso, next_start, as_of = _setup()
    good_wellness = [make_wellness(date=as_of - timedelta(days=i)) for i in range(7)]
    # Only log a fraction of last week's planned swim volume, against a
    # steady background history (so this reads as low compliance, not a
    # load spike).
    last_week_start = min(s.date for s in current_week.sessions)
    workouts = _background_history(current_week) + [
        make_workout(date=last_week_start, distance_m=1000, duration_min=20.0, rpe=4, sport="swim_pool")
    ]
    week = adapt_week(
        athlete, event, macro, next_iso, next_start, current_week, workouts, good_wellness, as_of
    )
    rationale = _rationale(week)
    assert rationale["action"] == "repeat"
    assert week.target_volume_m == current_week.target_volume_m


# --- advance: all green + high compliance ------------------------------------------------


def _background_history(current_week, background_weeks=3, rpe=4):
    """A steady swim-load history for the `background_weeks` before
    `current_week`, built by shifting `current_week`'s own swim sessions
    back by whole weeks at a fixed RPE -- without this, the 7d:28d ACWR sees
    a sudden load onset (0 -> a full week) and always reads as a spike
    (ratio ~4x), which isn't the "steady state" scenario most of these tests
    are after."""
    workouts = []
    swim_sessions = [s for s in current_week.sessions if s.sport in ("swim_pool", "swim_ow")]
    for week_offset in range(1, background_weeks + 1):
        for s in swim_sessions:
            workouts.append(
                make_workout(
                    date=s.date - timedelta(weeks=week_offset),
                    distance_m=s.distance_m,
                    duration_min=s.duration_min,
                    rpe=rpe,
                )
            )
    return workouts


def _fully_compliant_workouts(current_week, background_weeks=3, rpe=4):
    """Last week's swim sessions logged exactly as planned, plus
    `_background_history` before that so the load ratio reads as steady."""
    workouts = []
    swim_sessions = [s for s in current_week.sessions if s.sport in ("swim_pool", "swim_ow")]
    for s in swim_sessions:
        workouts.append(
            make_workout(date=s.date, distance_m=s.distance_m, duration_min=s.duration_min, rpe=rpe)
        )
    workouts += _background_history(current_week, background_weeks=background_weeks, rpe=rpe)
    return workouts


def test_advance_when_all_green_and_compliance_high():
    athlete, event, macro, current_week, next_iso, next_start, as_of = _setup()
    good_wellness = [make_wellness(date=as_of - timedelta(days=i)) for i in range(7)]
    workouts = _fully_compliant_workouts(current_week)
    week = adapt_week(
        athlete,
        event,
        macro,
        next_iso,
        next_start,
        current_week,
        workouts,
        good_wellness,
        as_of,
        days_since_last_milestone=RECOVERY_DAYS_AFTER_MILESTONE_MIN,
    )
    rationale = _rationale(week)
    assert rationale["action"] == "advance"
    assert rationale["signals"]["compliance_pct"] >= COMPLIANCE_ADVANCE_THRESHOLD
    assert week.target_volume_m <= round(current_week.target_volume_m * (1 + WEEKLY_VOLUME_RAMP_CAP))
    assert week.target_volume_m >= current_week.target_volume_m


def test_advance_increases_long_swim_when_recent_swim_data_exists():
    athlete, event, macro, current_week, next_iso, next_start, as_of = _setup()
    good_wellness = [make_wellness(date=as_of - timedelta(days=i)) for i in range(7)]
    # `_fully_compliant_workouts` already logs last week's actual Saturday
    # long swim at its planned distance -- that's the "recent swim data" the
    # ladder steps from, no need for an extra synthetic entry (which would
    # double-count that week's acute load and spuriously trip the load-ratio
    # red flag).
    workouts = _fully_compliant_workouts(current_week)
    prev_long_swim = next(
        s.distance_m for s in current_week.sessions if s.sport == "swim_ow" and s.date.weekday() == 5
    )
    week = adapt_week(
        athlete,
        event,
        macro,
        next_iso,
        next_start,
        current_week,
        workouts,
        good_wellness,
        as_of,
        days_since_last_milestone=RECOVERY_DAYS_AFTER_MILESTONE_MIN,
    )
    rationale = _rationale(week)
    assert rationale["action"] == "advance"
    next_long_swim = next(
        s.distance_m for s in week.sessions if s.sport == "swim_ow" and s.date.weekday() == 5
    )
    assert next_long_swim >= prev_long_swim


def test_milestone_annotates_sunday_session_as_easy():
    athlete, event, macro, current_week, next_iso, next_start, as_of = _setup()
    good_wellness = [make_wellness(date=as_of - timedelta(days=i)) for i in range(7)]
    workouts = _fully_compliant_workouts(current_week)
    week = adapt_week(
        athlete,
        event,
        macro,
        next_iso,
        next_start,
        current_week,
        workouts,
        good_wellness,
        as_of,
        days_since_last_milestone=RECOVERY_DAYS_AFTER_MILESTONE_MIN,
    )
    rationale = _rationale(week)
    if rationale["long_swim"]["milestone"]:
        sunday = next(s for s in week.sessions if s.date.weekday() == 6)
        assert "EASY" in sunday.purpose


# --- hold: default ----------------------------------------------------------------------


def test_hold_when_compliance_is_middling_and_no_red_flags():
    athlete, event, macro, current_week, next_iso, next_start, as_of = _setup()
    good_wellness = [make_wellness(date=as_of - timedelta(days=i)) for i in range(7)]
    last_week_start = min(s.date for s in current_week.sessions)
    planned_swim_total = sum(
        s.distance_m for s in current_week.sessions if s.sport in ("swim_pool", "swim_ow")
    )
    # ~80% compliance: between the repeat (<70) and advance (>=90) thresholds,
    # against a steady background history (so this reads as middling
    # compliance, not a load spike).
    workouts = _background_history(current_week) + [
        make_workout(
            date=last_week_start, distance_m=round(planned_swim_total * 0.8), duration_min=90.0, rpe=4
        )
    ]
    week = adapt_week(
        athlete, event, macro, next_iso, next_start, current_week, workouts, good_wellness, as_of
    )
    rationale = _rationale(week)
    assert rationale["action"] == "hold"
    assert week.target_volume_m == current_week.target_volume_m


# --- forced recovery window (milestone gate) ----------------------------------------------


def test_forced_hold_within_milestone_recovery_window_even_if_all_green():
    athlete, event, macro, current_week, next_iso, next_start, as_of = _setup()
    good_wellness = [make_wellness(date=as_of - timedelta(days=i)) for i in range(7)]
    workouts = _fully_compliant_workouts(current_week)
    week = adapt_week(
        athlete,
        event,
        macro,
        next_iso,
        next_start,
        current_week,
        workouts,
        good_wellness,
        as_of,
        days_since_last_milestone=1,
    )
    rationale = _rationale(week)
    assert rationale["action"] == "hold"
    assert week.target_volume_m == current_week.target_volume_m


# --- event_format: multi_day_stage --------------------------------------------------------


def test_format_switch_changes_weekend_structure():
    athlete, event, macro, current_week, next_iso, next_start, as_of = _setup(event_format="multi_day_stage")
    good_wellness = [make_wellness(date=as_of - timedelta(days=i)) for i in range(7)]
    week = adapt_week(athlete, event, macro, next_iso, next_start, current_week, [], good_wellness, as_of)

    long_swims = {s.date.weekday() for s in week.sessions if s.sport == "swim_ow"}
    assert long_swims == {5, 6}
    recovery = [s for s in week.sessions if s.sport == "recovery"]
    assert recovery == []


def test_single_day_format_has_no_sunday_long_swim():
    athlete, event, macro, current_week, next_iso, next_start, as_of = _setup(event_format="single_day")
    good_wellness = [make_wellness(date=as_of - timedelta(days=i)) for i in range(7)]
    week = adapt_week(athlete, event, macro, next_iso, next_start, current_week, [], good_wellness, as_of)

    long_swims = {s.date.weekday() for s in week.sessions if s.sport == "swim_ow"}
    assert long_swims == {5}


# --- property tests ------------------------------------------------------------------------


def test_property_red_wellness_always_reduces_volume():
    athlete, event, macro, current_week, next_iso, next_start, as_of = _setup()
    for stress, soreness in [(5, 5), (4, 5), (5, 3)]:
        wellness = [
            make_wellness(date=as_of - timedelta(days=i), sleep_quality=1, stress=stress, soreness=soreness, motivation=1)
            for i in range(7)
        ]
        week = adapt_week(athlete, event, macro, next_iso, next_start, current_week, [], wellness, as_of)
        rationale = _rationale(week)
        if rationale["signals"]["wellness_composite_mean"] <= WELLNESS_RED_THRESHOLD:
            assert week.target_volume_m < current_week.target_volume_m


def test_property_never_exceeds_weekly_ramp_cap():
    athlete, event, macro, current_week, next_iso, next_start, as_of = _setup()
    good_wellness = [make_wellness(date=as_of - timedelta(days=i)) for i in range(7)]
    workouts = _fully_compliant_workouts(current_week)
    week = adapt_week(
        athlete,
        event,
        macro,
        next_iso,
        next_start,
        current_week,
        workouts,
        good_wellness,
        as_of,
        days_since_last_milestone=RECOVERY_DAYS_AFTER_MILESTONE_MIN,
    )
    assert week.target_volume_m <= round(current_week.target_volume_m * (1 + WEEKLY_VOLUME_RAMP_CAP)) + 1


@pytest.mark.parametrize("longest_recent_m", [1000, 5000, 12000, 20000])
def test_property_single_session_step_never_exceeds_15pct_over_30day_longest(longest_recent_m):
    athlete, event, macro, current_week, next_iso, next_start, as_of = _setup()
    good_wellness = [make_wellness(date=as_of - timedelta(days=i)) for i in range(7)]
    workouts = _fully_compliant_workouts(current_week)
    workouts.append(
        make_workout(date=as_of - timedelta(days=2), sport="swim_ow", distance_m=longest_recent_m, duration_min=200.0, rpe=5)
    )
    week = adapt_week(
        athlete,
        event,
        macro,
        next_iso,
        next_start,
        current_week,
        workouts,
        good_wellness,
        as_of,
        days_since_last_milestone=RECOVERY_DAYS_AFTER_MILESTONE_MIN,
    )
    next_long_swim = next(
        s.distance_m for s in week.sessions if s.sport == "swim_ow" and s.date.weekday() == 5
    )
    cap = round(longest_recent_m * (1 + SINGLE_SESSION_STEP_CAP))
    assert next_long_swim <= max(cap, 1) + 1  # +1 for rounding slack


def test_property_never_exceeds_single_day_peak_share_of_event_distance():
    athlete, event, macro, current_week, next_iso, next_start, as_of = _setup(
        current_volume=30000, peak_volume=30000
    )
    good_wellness = [make_wellness(date=as_of - timedelta(days=i)) for i in range(7)]
    workouts = _fully_compliant_workouts(current_week)
    # A huge recent "longest swim" so the step cap doesn't bind -- only the
    # event-distance peak-share cap should limit the outcome.
    workouts.append(
        make_workout(date=as_of - timedelta(days=2), sport="swim_ow", distance_m=event.distance_m, duration_min=600.0, rpe=5)
    )
    week = adapt_week(
        athlete,
        event,
        macro,
        next_iso,
        next_start,
        current_week,
        workouts,
        good_wellness,
        as_of,
        days_since_last_milestone=RECOVERY_DAYS_AFTER_MILESTONE_MIN,
    )
    next_long_swim = next(
        s.distance_m for s in week.sessions if s.sport == "swim_ow" and s.date.weekday() == 5
    )
    assert next_long_swim <= round(event.distance_m * SINGLE_DAY_PEAK_SHARE_MAX)


def test_property_stage_format_never_exceeds_longest_day_share_of_event_distance():
    athlete, event, macro, current_week, next_iso, next_start, as_of = _setup(
        event_format="multi_day_stage", current_volume=30000, peak_volume=30000
    )
    good_wellness = [make_wellness(date=as_of - timedelta(days=i)) for i in range(7)]
    workouts = _fully_compliant_workouts(current_week)
    workouts.append(
        make_workout(date=as_of - timedelta(days=2), sport="swim_ow", distance_m=event.distance_m, duration_min=600.0, rpe=5)
    )
    week = adapt_week(
        athlete,
        event,
        macro,
        next_iso,
        next_start,
        current_week,
        workouts,
        good_wellness,
        as_of,
        days_since_last_milestone=RECOVERY_DAYS_AFTER_MILESTONE_MIN,
    )
    saturday = next(s for s in week.sessions if s.sport == "swim_ow" and s.date.weekday() == 5)
    assert saturday.distance_m <= round(event.distance_m * STAGE_LONGEST_DAY_SHARE_MAX)


def test_property_output_always_validates_across_action_matrix():
    # Sweep a matrix of wellness/compliance/format combinations and confirm
    # every result is a valid WeekPlan (construction itself would have
    # raised ValidationError otherwise) with draft=True.
    for event_format in ("single_day", "multi_day_stage"):
        athlete, event, macro, current_week, next_iso, next_start, as_of = _setup(event_format=event_format)
        for wellness_good in (True, False):
            wellness = [
                make_wellness(
                    date=as_of - timedelta(days=i),
                    sleep_quality=4 if wellness_good else 1,
                    stress=2 if wellness_good else 5,
                    soreness=2 if wellness_good else 5,
                    motivation=4 if wellness_good else 1,
                )
                for i in range(7)
            ]
            for workouts in ([], _fully_compliant_workouts(current_week)):
                week = adapt_week(
                    athlete, event, macro, next_iso, next_start, current_week, workouts, wellness, as_of
                )
                assert week.draft is True
                assert week.target_volume_m >= 0
                for s in week.sessions:
                    assert s.duration_min > 0
