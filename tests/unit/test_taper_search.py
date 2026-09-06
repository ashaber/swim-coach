"""Tests for swim_coach.taper_search: the injury/layoff-aware ramp-then-taper
projection + grid search, and the derived session-content generator.

No LLM calls, no network access -- pure arithmetic + model validation, same
convention as test_load.py/test_plan.py.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from swim_coach.models import Athlete, Event, Workout
from swim_coach.taper_search import (
    DECAY_GRID_MAX,
    DECAY_GRID_MIN,
    LIGHT_ONLY_RAMP_CAP_FRACTION,
    RACE_DAY_TSB_BAND,
    REST_DAY_LOAD_FRACTION_THRESHOLD,
    TaperCandidate,
    _phase_day_load,
    _session_role,
    generate_taper_sessions,
    pre_layoff_baseline_daily_load,
    project_ramp_taper_series,
    recent_baseline_daily_load,
    resolve_ramp_target,
    search_taper_grid,
    taper_volume_fraction,
)

ATHLETE_ID = uuid.uuid4()


def _athlete(**overrides) -> Athlete:
    defaults = dict(
        id=ATHLETE_ID,
        slug="renee",
        name="Renee Example",
        css_pace_s_per_100m=90.0,
        pool_schedule=["mon", "wed", "fri"],
    )
    defaults.update(overrides)
    return Athlete(**defaults)


def _event(event_date: date, **overrides) -> Event:
    defaults = dict(
        id=uuid.uuid4(),
        athlete_id=ATHLETE_ID,
        name="UltraSwim 33.3 Greece",
        event_date=event_date,
        distance_m=33300,
        priority="A",
        event_format="single_day",
    )
    defaults.update(overrides)
    return Event(**defaults)


def _workout(d: date, *, duration_min: float, rpe: int, sport: str = "swim_ow") -> Workout:
    return Workout(
        id=uuid.uuid4(),
        athlete_id=ATHLETE_ID,
        date=d,
        sport=sport,
        source="manual",
        distance_m=1000,
        duration_min=duration_min,
        rpe=rpe,
    )


def _steady_workouts(start: date, end: date, *, daily_load: float) -> list[Workout]:
    """One workout/day from `start` to `end` inclusive, each sRPE-scored
    (duration_min * rpe) to land exactly on `daily_load` -- rpe=5 (a fixed,
    always-valid CR-10 value) with duration_min = daily_load / 5."""
    duration_min = daily_load / 5
    workouts = []
    day = start
    while day <= end:
        workouts.append(_workout(day, duration_min=duration_min, rpe=5))
        day += timedelta(days=1)
    return workouts


# --- taper_volume_fraction / recent_baseline_daily_load (unchanged math) ------


def test_taper_volume_fraction_matches_scaffold_macro_formula():
    assert taper_volume_fraction(2, 0.25) == pytest.approx(0.5)
    assert taper_volume_fraction(4, 0.30) == pytest.approx(0.0)  # floored at 0


def test_recent_baseline_daily_load_treats_missing_days_as_zero():
    anchor = date(2026, 8, 1)
    loads = {anchor: 100.0, anchor - timedelta(days=1): 100.0}
    # window_days=7, only 2 of 7 days have logged load -> average is diluted
    result = recent_baseline_daily_load(loads, anchor, window_days=7)
    assert result == pytest.approx(200.0 / 7)


# --- pre_layoff_baseline_daily_load -------------------------------------------


def test_pre_layoff_baseline_excludes_days_on_or_after_boundary():
    boundary = date(2026, 8, 20)
    loads = {
        date(2026, 8, 10): 400.0,
        date(2026, 8, 19): 400.0,
        date(2026, 8, 20): 10.0,  # on/after boundary must not count
        date(2026, 8, 21): 10.0,
    }
    result = pre_layoff_baseline_daily_load(loads, boundary, window_days=10)
    # window covers 8/10..8/19 inclusive (10 days ending the day before boundary)
    assert result == pytest.approx(400.0 * 2 / 10)


# --- resolve_ramp_target -------------------------------------------------------


def test_resolve_ramp_target_no_training_never_exceeds_current_baseline():
    target, cap_fraction, ramp_permitted = resolve_ramp_target(
        current_recent_baseline=50.0, pre_layoff_baseline=400.0, restriction="no_training"
    )
    assert target == 50.0
    assert cap_fraction is None
    assert ramp_permitted is False


def test_resolve_ramp_target_light_only_caps_at_documented_fraction():
    target, cap_fraction, ramp_permitted = resolve_ramp_target(
        current_recent_baseline=50.0, pre_layoff_baseline=400.0, restriction="light_only"
    )
    assert cap_fraction == LIGHT_ONLY_RAMP_CAP_FRACTION
    assert target == pytest.approx(400.0 * LIGHT_ONLY_RAMP_CAP_FRACTION)
    assert ramp_permitted is True


def test_resolve_ramp_target_light_only_cap_is_a_hard_ceiling_even_above_current():
    # Real review bug fixed before merge: this used to assert the OPPOSITE
    # of the intended safety behavior -- that when current_recent_baseline
    # reads ABOVE the cap (e.g. from a data artifact: the recent-baseline
    # window can shrink to include a pre-injury day right when a
    # restriction is first reported), the target should silently follow
    # that higher number instead of the cap. That's a safety cap a data
    # artifact can quietly cancel, which isn't a cap at all. The cap is
    # now a hard ceiling: target is always exactly
    # pre_layoff_baseline * LIGHT_ONLY_RAMP_CAP_FRACTION, regardless of
    # whether current_recent_baseline happens to read higher.
    target, cap_fraction, ramp_permitted = resolve_ramp_target(
        current_recent_baseline=300.0, pre_layoff_baseline=400.0, restriction="light_only"
    )
    assert target == pytest.approx(400.0 * LIGHT_ONLY_RAMP_CAP_FRACTION)
    assert target < 300.0  # the cap genuinely constrains, even below current
    assert cap_fraction == LIGHT_ONLY_RAMP_CAP_FRACTION
    assert ramp_permitted is True


def test_resolve_ramp_target_light_only_cap_applies_even_when_current_is_much_higher():
    # A more extreme version of the same real bug: current_recent_baseline
    # near full pre-injury load (e.g. the shrunk-window artifact including
    # a big pre-injury day) must NOT be allowed to erase the cap.
    target, cap_fraction, ramp_permitted = resolve_ramp_target(
        current_recent_baseline=395.0, pre_layoff_baseline=400.0, restriction="light_only"
    )
    assert target == pytest.approx(400.0 * LIGHT_ONLY_RAMP_CAP_FRACTION)
    assert cap_fraction == LIGHT_ONLY_RAMP_CAP_FRACTION
    assert ramp_permitted is True


def test_resolve_ramp_target_no_restriction_targets_higher_of_the_two_baselines():
    target, cap_fraction, ramp_permitted = resolve_ramp_target(
        current_recent_baseline=300.0, pre_layoff_baseline=300.0, restriction=None
    )
    assert target == pytest.approx(300.0)
    assert cap_fraction is None
    assert ramp_permitted is True


# --- project_ramp_taper_series --------------------------------------------------


def test_project_ramp_taper_series_no_runway_left_returns_unchanged():
    anchor = date(2026, 9, 16)
    race_date = date(2026, 9, 17)  # anchor is race_date - 1 day: no days to project
    ctl, atl, tsb, volume_fraction, ramp_end, taper_start = project_ramp_taper_series(
        ctl0=50.0,
        atl0=40.0,
        anchor_date=anchor,
        race_date=race_date,
        current_baseline_daily_load=100.0,
        ramp_target_daily_load=100.0,
        ramp_days=0,
        taper_weeks=1,
        decay=0.25,
    )
    assert ctl == 50.0
    assert atl == 40.0
    assert tsb == pytest.approx(10.0)


def test_project_ramp_taper_series_ramp_is_noop_when_target_equals_current():
    """When ramp_target == current baseline (the no-restriction/steady-state
    case), varying ramp_days must not change the projection at all -- this is
    the mathematical basis for the 'collapses to old hold-then-decay
    behavior' regression guarantee."""
    anchor = date(2026, 8, 1)
    race_date = date(2026, 8, 20)
    kwargs = dict(
        ctl0=100.0,
        atl0=100.0,
        anchor_date=anchor,
        race_date=race_date,
        current_baseline_daily_load=250.0,
        ramp_target_daily_load=250.0,
        taper_weeks=2,
        decay=0.25,
    )
    result_no_ramp = project_ramp_taper_series(ramp_days=0, **kwargs)
    result_with_ramp = project_ramp_taper_series(ramp_days=6, **kwargs)
    assert result_no_ramp[:3] == pytest.approx(result_with_ramp[:3])


def test_project_ramp_taper_series_ramp_rises_linearly_toward_target():
    anchor = date(2026, 8, 1)
    race_date = date(2026, 8, 30)
    # Long taper (large taper_weeks) pushed way out so the ramp completes
    # well before any taper decay could kick in for this short window.
    ctl, atl, tsb, volume_fraction, ramp_end, taper_start = project_ramp_taper_series(
        ctl0=0.0,
        atl0=0.0,
        anchor_date=anchor,
        race_date=race_date,
        current_baseline_daily_load=0.0,
        ramp_target_daily_load=100.0,
        ramp_days=4,
        taper_weeks=1,
        decay=0.0,  # no decay -- isolate the ramp's own shape
    )
    assert ramp_end == anchor + timedelta(days=4)
    # With ctl0=atl0=0 and a load ramping 0 -> 100 over 4 days then holding
    # at 100 until taper (decay=0 means volume_fraction=1, i.e. taper phase
    # also loads at 100) -- ATL (fast time constant) should end up much
    # closer to the held target than a flat zero-then-jump model would allow,
    # confirming the ramp actually interpolates rather than jumping.
    assert 0 < atl < 100


def test_phase_day_load_ramp_reaches_full_target_when_taper_starts_immediately_after():
    # Real review bug fixed before merge: when hold_days == 0 (taper_start_
    # date == ramp_end_date exactly -- no gap between the ramp completing
    # and the taper beginning), the ramp's own FINAL day used to be
    # misclassified as the first TAPER day, silently clipping the ramp one
    # day short of ever reaching ramp_target_daily_load. Reproduces the
    # reviewer's exact numbers: a 50 -> 100 ramp over 4 days.
    anchor = date(2026, 9, 1)
    ramp_end_date = anchor + timedelta(days=4)
    taper_start_date = ramp_end_date  # the exact hold_days == 0 collision

    day_1 = _phase_day_load(
        anchor + timedelta(days=1), anchor_date=anchor, current_baseline_daily_load=50.0,
        ramp_target_daily_load=100.0, ramp_days=4, taper_start_date=taper_start_date,
        volume_fraction=0.7,
    )
    day_4 = _phase_day_load(
        ramp_end_date, anchor_date=anchor, current_baseline_daily_load=50.0,
        ramp_target_daily_load=100.0, ramp_days=4, taper_start_date=taper_start_date,
        volume_fraction=0.7,
    )
    day_5 = _phase_day_load(
        ramp_end_date + timedelta(days=1), anchor_date=anchor, current_baseline_daily_load=50.0,
        ramp_target_daily_load=100.0, ramp_days=4, taper_start_date=taper_start_date,
        volume_fraction=0.7,
    )
    assert day_1 == pytest.approx(62.5)
    # The ramp's own final day must reach the FULL target, not the
    # tapered-down value (100.0 * 0.7 = 70.0, the old buggy result).
    assert day_4 == pytest.approx(100.0)
    # Taper begins correctly the very next day.
    assert day_5 == pytest.approx(100.0 * 0.7)

    assert _session_role(
        ramp_end_date, anchor_date=anchor, current_baseline_daily_load=50.0,
        ramp_target_daily_load=100.0, ramp_days=4, taper_start_date=taper_start_date,
    ) == "ramp"
    assert _session_role(
        ramp_end_date + timedelta(days=1), anchor_date=anchor, current_baseline_daily_load=50.0,
        ramp_target_daily_load=100.0, ramp_days=4, taper_start_date=taper_start_date,
    ) == "taper"


def test_phase_day_load_flat_ramp_still_lets_taper_win_far_before_ramp_end():
    # The regression this fix must NOT break: when ramp_target_daily_load
    # == current_baseline_daily_load (a flat/no-op "ramp" -- the ordinary
    # no-restriction, steady-state case), taper_start_date can legitimately
    # fall WELL BEFORE ramp_end_date (project_ramp_taper_series doesn't
    # clamp it forward in that case, since there's no real ramp to
    # protect) -- TAPER must still win on every one of those days, not
    # just the single hold_days==0 boundary day.
    anchor = date(2026, 9, 1)
    ramp_end_date = anchor + timedelta(days=10)
    taper_start_date = anchor + timedelta(days=3)  # well before ramp_end_date

    mid_ramp_day = _phase_day_load(
        anchor + timedelta(days=5), anchor_date=anchor, current_baseline_daily_load=100.0,
        ramp_target_daily_load=100.0, ramp_days=10, taper_start_date=taper_start_date,
        volume_fraction=0.6,
    )
    # Must be the TAPERED value (100 * 0.6 = 60), not the flat ramp/target
    # value (100) -- taper correctly wins here despite day_offset (5) being
    # well within ramp_days (10).
    assert mid_ramp_day == pytest.approx(60.0)


def test_phase_day_load_flat_ramp_taper_wins_even_on_the_exact_coincidence_day():
    # The narrower, second regression this fix's guard must also not
    # break: a flat/no-op ramp where anchor_date + ramp_days HAPPENS to
    # land exactly on taper_start_date (the same day-count coincidence
    # that triggers the rising-ramp exception) -- since there's no real
    # ramp value to protect (target == current), TAPER must still win on
    # that exact day too, not just the days before/after it.
    anchor = date(2026, 9, 1)
    ramp_days = 4
    taper_start_date = anchor + timedelta(days=ramp_days)  # exact coincidence

    coincidence_day = _phase_day_load(
        taper_start_date, anchor_date=anchor, current_baseline_daily_load=100.0,
        ramp_target_daily_load=100.0, ramp_days=ramp_days, taper_start_date=taper_start_date,
        volume_fraction=0.6,
    )
    assert coincidence_day == pytest.approx(60.0)  # tapered, not the flat 100

    assert _session_role(
        taper_start_date, anchor_date=anchor, current_baseline_daily_load=100.0,
        ramp_target_daily_load=100.0, ramp_days=ramp_days, taper_start_date=taper_start_date,
    ) == "taper"


# --- search_taper_grid: restriction-driven behavior -----------------------------


def test_no_training_restriction_never_produces_a_ramp_candidate():
    anchor = date(2026, 9, 5)
    workouts = _steady_workouts(anchor - timedelta(days=40), anchor, daily_load=50.0)
    athlete = _athlete()
    event = _event(date(2026, 9, 18))

    result = search_taper_grid(
        athlete=athlete,
        event=event,
        workouts=workouts,
        as_of=anchor,
        restriction="no_training",
        restriction_reported_at=anchor - timedelta(days=1),
    )

    assert result["ramp_permitted"] is False
    assert result["ramp_target_daily_load"] == pytest.approx(result["recent_baseline_daily_load"])
    for candidate in result["candidates"]:
        assert candidate.ramp_days == 0
        assert candidate.ramp_target_daily_load <= result["recent_baseline_daily_load"] + 1e-9


def test_light_only_caps_ramp_at_documented_fraction_of_pre_layoff_baseline():
    anchor = date(2026, 9, 5)
    reported_at = anchor - timedelta(days=20)
    pre_layoff = _steady_workouts(
        reported_at - timedelta(days=40), reported_at - timedelta(days=1), daily_load=400.0
    )
    recent = _steady_workouts(reported_at, anchor, daily_load=50.0)
    athlete = _athlete()
    event = _event(date(2026, 9, 18))

    result = search_taper_grid(
        athlete=athlete,
        event=event,
        workouts=pre_layoff + recent,
        as_of=anchor,
        restriction="light_only",
        restriction_reported_at=reported_at,
    )

    assert result["ramp_permitted"] is True
    assert result["ramp_cap_fraction_applied"] == LIGHT_ONLY_RAMP_CAP_FRACTION
    assert result["pre_layoff_baseline_daily_load"] == pytest.approx(400.0, rel=0.05)
    expected_target = 400.0 * LIGHT_ONLY_RAMP_CAP_FRACTION
    assert result["ramp_target_daily_load"] == pytest.approx(expected_target, rel=0.05)
    # The cap must never quietly balloon back toward the pre-injury baseline.
    assert result["ramp_target_daily_load"] < result["pre_layoff_baseline_daily_load"]


def test_recent_baseline_window_does_not_reach_before_a_very_recent_restriction():
    """Real bug caught during this build's own validation pass: a
    restriction reported only a few days ago must not have its 'current
    recent baseline' diluted by weeks of real pre-injury training still
    sitting inside a plain RECENT_BASELINE_WINDOW_DAYS-long window -- the
    effective recent-baseline window must be capped at how many days have
    actually elapsed since the restriction was reported."""
    anchor = date(2026, 9, 5)
    reported_at = anchor - timedelta(days=5)  # restriction reported very recently
    pre_layoff = _steady_workouts(
        reported_at - timedelta(days=40), reported_at - timedelta(days=1), daily_load=300.0
    )
    # Only 6 days of real post-restriction history (reported_at..anchor),
    # at a much lower load -- a full RECENT_BASELINE_WINDOW_DAYS (21-day)
    # window would still be dominated by the 300.0 pre-injury days above.
    recent = _steady_workouts(reported_at, anchor, daily_load=50.0)
    athlete = _athlete()
    event = _event(date(2026, 9, 18))

    result = search_taper_grid(
        athlete=athlete,
        event=event,
        workouts=pre_layoff + recent,
        as_of=anchor,
        restriction="light_only",
        restriction_reported_at=reported_at,
    )

    # The reported recent baseline must reflect ONLY the 6 real post-
    # restriction days (all at 50.0), not a blend with the 300.0 pre-injury
    # regime -- i.e. it must land near 50.0, nowhere near a 21-day blended
    # average (which would sit far higher).
    assert result["recent_baseline_daily_load"] == pytest.approx(50.0, rel=0.05)
    assert result["recent_baseline_window_days"] == 6


def test_no_active_health_status_collapses_to_hold_then_decay_regression():
    """With no restriction and a steady (unchanging) training history, the
    ramp is mathematically a no-op -- varying ramp_days across candidates for
    the same (taper_weeks, decay) pair must produce identical projected TSB,
    proving this build didn't change behavior for the non-injury case."""
    anchor = date(2026, 8, 1)
    workouts = _steady_workouts(anchor - timedelta(days=60), anchor, daily_load=300.0)
    athlete = _athlete()
    event = _event(anchor + timedelta(days=30))

    result = search_taper_grid(
        athlete=athlete,
        event=event,
        workouts=workouts,
        as_of=anchor,
        restriction=None,
    )

    assert result["ramp_permitted"] is True
    assert result["ramp_cap_fraction_applied"] is None
    by_shape: dict[tuple[int, float], set[float]] = {}
    for candidate in result["candidates"]:
        if not candidate.fits_available_runway:
            continue
        key = (candidate.taper_weeks, candidate.decay)
        by_shape.setdefault(key, set()).add(round(candidate.projected_tsb, 6))
    # Every (taper_weeks, decay) shape must map to exactly ONE projected TSB
    # regardless of ramp_days, since ramp_target == current baseline here.
    for key, tsb_values in by_shape.items():
        assert len(tsb_values) == 1, f"{key} produced divergent TSB across ramp_days: {tsb_values}"


def test_search_taper_grid_raises_on_no_workouts():
    athlete = _athlete()
    event = _event(date(2026, 9, 18))
    with pytest.raises(ValueError):
        search_taper_grid(athlete=athlete, event=event, workouts=[], as_of=date(2026, 9, 5))


def test_search_taper_grid_no_runway_left_still_returns_a_result():
    anchor = date(2026, 9, 17)
    workouts = _steady_workouts(anchor - timedelta(days=30), anchor, daily_load=100.0)
    athlete = _athlete()
    event = _event(date(2026, 9, 18))  # as_of is race_date - 1 day

    result = search_taper_grid(
        athlete=athlete, event=event, workouts=workouts, as_of=anchor, restriction=None
    )
    assert result["days_available"] <= 1
    for candidate in result["candidates"]:
        assert candidate.projected_tsb == pytest.approx(result["tsb0"])


def test_race_day_tsb_band_is_sane():
    assert 0 <= RACE_DAY_TSB_BAND["low"] < RACE_DAY_TSB_BAND["high"]


def test_decay_grid_brackets_taper_weekly_decay():
    assert DECAY_GRID_MIN < 0.25 < DECAY_GRID_MAX


# --- generate_taper_sessions ----------------------------------------------------


def test_generate_taper_sessions_never_backdates_when_as_of_is_later_than_anchor():
    # Real review bug fixed before merge: generation used to start from
    # anchor_date (the athlete's last LOGGED workout day) even when as_of
    # (today) was well after it -- exactly the scenario an injured athlete
    # who's stopped logging produces. Every generated session must be
    # dated strictly after as_of, never in the gap between anchor_date and
    # as_of.
    anchor = date(2026, 9, 5)  # last logged workout, 6 days ago
    as_of = date(2026, 9, 11)  # today
    race_date = date(2026, 9, 18)
    athlete = _athlete()
    event = _event(race_date)

    sessions = generate_taper_sessions(
        athlete=athlete,
        event=event,
        anchor_date=anchor,
        race_date=race_date,
        current_baseline_daily_load=50.0,
        ramp_target_daily_load=220.0,
        ramp_days=6,
        taper_start_date=race_date - timedelta(days=7),
        volume_fraction=0.5,
        restriction="light_only",
        as_of=as_of,
    )
    assert sessions, "expected at least one generated session"
    for s in sessions:
        assert s.date > as_of, f"session on {s.date} is not after as_of {as_of}"
        assert s.date > anchor  # still true, but as_of is the binding constraint here


def test_generate_taper_sessions_as_of_before_anchor_is_a_noop_clamp():
    # When as_of is BEFORE (or equal to) anchor_date -- the ordinary case,
    # an athlete who logged something today or very recently -- generation
    # starts right after anchor_date exactly as before this fix.
    anchor = date(2026, 9, 5)
    as_of = date(2026, 9, 5)
    race_date = date(2026, 9, 18)
    athlete = _athlete()
    event = _event(race_date)

    sessions = generate_taper_sessions(
        athlete=athlete,
        event=event,
        anchor_date=anchor,
        race_date=race_date,
        current_baseline_daily_load=50.0,
        ramp_target_daily_load=220.0,
        ramp_days=6,
        taper_start_date=race_date - timedelta(days=7),
        volume_fraction=0.5,
        restriction="light_only",
        as_of=as_of,
    )
    assert sessions[0].date == anchor + timedelta(days=1)


def test_generate_taper_sessions_dates_ordered_and_in_range():
    anchor = date(2026, 9, 5)
    race_date = date(2026, 9, 18)
    athlete = _athlete()
    event = _event(race_date)

    sessions = generate_taper_sessions(
        athlete=athlete,
        event=event,
        anchor_date=anchor,
        race_date=race_date,
        current_baseline_daily_load=50.0,
        ramp_target_daily_load=220.0,
        ramp_days=6,
        taper_start_date=race_date - timedelta(days=7),
        volume_fraction=0.5,
        restriction="light_only",
        as_of=anchor,
    )
    assert sessions, "expected at least one generated session"
    dates = [s.date for s in sessions]
    assert dates == sorted(dates)
    assert dates[0] > anchor
    assert dates[-1] < race_date
    assert len(dates) == len(set(dates))


def test_generate_taper_sessions_rest_days_have_no_distance():
    anchor = date(2026, 9, 5)
    race_date = date(2026, 9, 18)
    athlete = _athlete()
    event = _event(race_date)

    sessions = generate_taper_sessions(
        athlete=athlete,
        event=event,
        anchor_date=anchor,
        race_date=race_date,
        current_baseline_daily_load=50.0,
        ramp_target_daily_load=220.0,
        ramp_days=6,
        taper_start_date=race_date - timedelta(days=7),
        volume_fraction=0.5,
        restriction="light_only",
        as_of=anchor,
    )
    rest_sessions = [s for s in sessions if s.sport == "recovery"]
    assert rest_sessions, "expected at least one rest/recovery day in a 13-day span"
    for s in rest_sessions:
        assert s.distance_m is None


def test_generate_taper_sessions_purpose_mentions_restriction_context():
    anchor = date(2026, 9, 5)
    race_date = date(2026, 9, 18)
    athlete = _athlete()
    event = _event(race_date)

    sessions = generate_taper_sessions(
        athlete=athlete,
        event=event,
        anchor_date=anchor,
        race_date=race_date,
        current_baseline_daily_load=50.0,
        ramp_target_daily_load=220.0,
        ramp_days=6,
        taper_start_date=race_date - timedelta(days=7),
        volume_fraction=0.5,
        restriction="light_only",
        as_of=anchor,
    )
    for s in sessions:
        assert "light_only" in s.purpose
        assert "engine" in s.purpose.lower()


def test_generate_taper_sessions_no_restriction_purpose_says_no_active_status():
    anchor = date(2026, 9, 5)
    race_date = date(2026, 9, 18)
    athlete = _athlete()
    event = _event(race_date)

    sessions = generate_taper_sessions(
        athlete=athlete,
        event=event,
        anchor_date=anchor,
        race_date=race_date,
        current_baseline_daily_load=300.0,
        ramp_target_daily_load=300.0,
        ramp_days=0,
        taper_start_date=race_date - timedelta(days=7),
        volume_fraction=0.5,
        restriction=None,
        as_of=anchor,
    )
    for s in sessions:
        assert "no active" in s.purpose.lower()
