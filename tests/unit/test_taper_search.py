"""Tests for swim_coach.taper_search: the injury/layoff-aware ramp-then-taper
projection + grid search, and the derived session-content generator.

No LLM calls, no network access -- pure arithmetic + model validation, same
convention as test_load.py/test_plan.py.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from swim_coach.load import ctl_atl_tsb_series, daily_loads
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
    ctl_at,
    generate_taper_sessions,
    project_ramp_taper_series,
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


# --- taper_volume_fraction (unchanged math) ------------------------------------


def test_taper_volume_fraction_matches_scaffold_macro_formula():
    assert taper_volume_fraction(2, 0.25) == pytest.approx(0.5)
    assert taper_volume_fraction(4, 0.30) == pytest.approx(0.0)  # floored at 0


# --- ctl_at ----------------------------------------------------------------
# CTL-substitution replaces the old flat-mean recent/pre-layoff baselines --
# see module docstring's dated update paragraph. `ctl_at` is the small O(1)
# lookup helper that makes the pre-layoff (ceiling) side of that
# substitution possible: a point-in-time CTL read out of an
# already-computed `ctl_atl_tsb_series` result, not a fresh average.


def test_ctl_at_exact_date_hit():
    loads = {
        date(2026, 8, 1): 100.0,
        date(2026, 8, 2): 100.0,
        date(2026, 8, 3): 100.0,
    }
    series = ctl_atl_tsb_series(loads)
    target = date(2026, 8, 2)
    expected = next(ctl for d, ctl, _atl, _tsb in series if d == target)
    assert ctl_at(series, target) == pytest.approx(expected)


def test_ctl_at_before_series_start_returns_none():
    # `ctl_at` itself stays honest -- "not available from this history," not
    # a fabricated number (see its own docstring). It is the CALLER
    # (`search_taper_grid`) that decides how to handle a `None`, documenting
    # its own fallback choice -- see the search_taper_grid-level tests below.
    loads = {date(2026, 8, 1): 100.0, date(2026, 8, 2): 100.0}
    series = ctl_atl_tsb_series(loads)
    assert ctl_at(series, date(2026, 7, 1)) is None


def test_ctl_at_empty_series_returns_none():
    assert ctl_at([], date(2026, 8, 1)) is None


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
    # 220 days of steady pre-layoff load -- long enough (CTL_TIME_CONSTANT_
    # DAYS=42) for CTL to have converged to within ~3% of the true 400.0
    # steady-state load by `reported_at` (verified: 389.7, a 2.6% gap),
    # comfortably inside this test's rel=0.05 tolerance. A short pre-layoff
    # window (the old flat-mean test used 40 days) would read CTL
    # meaningfully below 400.0 -- CTL is an EWMA that climbs toward, but
    # never reaches, a constant load ceiling -- so this window is widened
    # specifically to isolate "does the cap fraction apply correctly to the
    # pre-layoff CTL ceiling" from "has CTL fully converged yet," which is a
    # separate, already-covered concern (see the CTL-substitution/as_of-
    # extension tests below).
    pre_layoff = _steady_workouts(
        reported_at - timedelta(days=220), reported_at - timedelta(days=1), daily_load=400.0
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
    expected_target = result["pre_layoff_baseline_daily_load"] * LIGHT_ONLY_RAMP_CAP_FRACTION
    assert result["ramp_target_daily_load"] == pytest.approx(expected_target)
    # The cap must never quietly balloon back toward the pre-injury baseline.
    assert result["ramp_target_daily_load"] < result["pre_layoff_baseline_daily_load"]


def test_no_active_health_status_collapses_to_hold_then_decay_regression():
    """With no restriction and a steady (unchanging) training history, the
    ramp is mathematically a no-op -- varying ramp_days across candidates for
    the same (taper_weeks, decay) pair must produce identical projected TSB,
    proving this build didn't change behavior for the non-injury case.

    **Why this invariant still holds EXACTLY (not just approximately) under
    CTL substitution, verified by actually running this test, not assumed:**
    under CTL substitution `resolve_ramp_target`'s two inputs are `ctl0`
    (current recent baseline, at `anchor_date`) and `ctl_at(series,
    pre_layoff_boundary)` (pre-layoff baseline, at an EARLIER date --
    `anchor_date - NO_RESTRICTION_PRE_LAYOFF_LOOKBACK_DAYS` when, as here,
    there's no active HealthStatus). For a steady, constant-load history
    with no gaps, `ctl_atl_tsb_series`'s CTL recursion (`CTL_t = CTL_{t-1} +
    (load_t - CTL_{t-1}) / tau`, seeded at 0) is STRICTLY MONOTONICALLY
    INCREASING day over day -- every day's CTL is closer to (but never
    reaches) the constant load ceiling than the day before. That makes
    `ctl0` (the LATEST point in the series) the running maximum over the
    whole walked history, so it is always >= `ctl_at` of any earlier date
    in the same series. `resolve_ramp_target`'s no-restriction branch is
    `max(current_recent_baseline, pre_layoff_baseline)` -- which therefore
    always evaluates to `current_recent_baseline` (`ctl0`) exactly, not
    merely approximately: `max()` returns the exact object/value passed in,
    with no new floating-point computation in between. So
    `ramp_target_daily_load == current_baseline_daily_load` is bit-for-bit
    true here, and `_phase_day_load`'s documented no-op short-circuit for
    that exact equality applies unchanged -- hence the byte-identical
    projected-TSB collapse this test asserts still holds precisely, for the
    same structural reason it did under the old flat-mean baselines (there,
    both baselines were close-to-equal means over overlapping steady-state
    windows; here, one is provably >= the other via CTL monotonicity, and
    happens to be selected exactly by `max()`)."""
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
    assert result["ramp_target_daily_load"] == pytest.approx(result["recent_baseline_daily_load"])
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


# --- CTL substitution: the real behavioral change over flat-mean baselines -----


def test_ctl_substitution_recent_baseline_is_decay_aware_unlike_a_frozen_flat_mean():
    """The core claim behind this build (Andrew's own ask: 'ACWR would
    account for decay of fitness due to time off... instead of static
    trailing-maximum values'), proven end to end rather than asserted:

    An athlete stops logging entirely once injured (this module's own real
    motivating scenario -- see module docstring). The OLD flat-mean system
    computed `recent_baseline_daily_load` as a plain mean over the
    `window_days` ending at `anchor_date`, where `anchor_date` was always
    the athlete's LAST LOGGED day -- so if she stops logging, that number
    is FROZEN at whatever her last active window looked like, no matter how
    much real time (and real detraining) has since passed. The NEW
    CTL-substituted system's `anchor_date`/`ctl0` are extended through to
    `as_of` (today) whenever she's stopped logging (see search_taper_grid's
    own as_of-extension docstring paragraph) -- so `ctl0` keeps decaying
    for every real day of the gap, correctly reflecting detraining the old
    frozen number could never see.

    This test reproduces the old flat-mean number by hand (the function
    itself is deleted -- CLAUDE.md forbids dead code -- but its 21-day
    trailing-mean arithmetic is trivial to reproduce inline for this
    A/B comparison) and shows the new CTL-based number is meaningfully
    LOWER for real elapsed time off, and that this creates real ramp
    headroom the old system would never have proposed.
    """
    as_of = date(2026, 9, 5)  # "today"
    last_logged = as_of - timedelta(days=20)  # stopped logging 20 days ago
    pre_injury_start = last_logged - timedelta(days=90)
    workouts = _steady_workouts(pre_injury_start, last_logged, daily_load=300.0)
    athlete = _athlete()
    event = _event(as_of + timedelta(days=40))

    # --- the OLD flat-mean number, reproduced by hand for comparison only ---
    old_recent_window_days = 21
    old_loads = daily_loads(workouts, athlete=athlete)
    old_naive_recent_baseline = sum(
        old_loads.get(last_logged - timedelta(days=i), 0.0) for i in range(old_recent_window_days)
    ) / old_recent_window_days
    # Entirely inside the steady 300.0 regime (last_logged is 90 days into
    # it) -- the old system, frozen at last_logged, would have reported her
    # recent baseline as essentially her full pre-injury load.
    assert old_naive_recent_baseline == pytest.approx(300.0)

    # --- the NEW CTL-substituted number ---
    result = search_taper_grid(
        athlete=athlete,
        event=event,
        workouts=workouts,
        as_of=as_of,
        restriction=None,
    )

    assert result["anchor_date"] == as_of  # decayed all the way through to today
    new_recent_baseline = result["recent_baseline_daily_load"]
    assert new_recent_baseline < old_naive_recent_baseline
    # Not just numerically lower -- meaningfully so (a real, observable
    # decay signal, not a rounding-noise difference).
    assert new_recent_baseline < old_naive_recent_baseline * 0.75

    # --- and this creates real ramp headroom the old system would have
    # missed entirely (old target ~= old recent baseline, since both sides
    # of its max() sit in the same steady 300.0 regime -> ~0 ramp proposed
    # for an athlete who has, in reality, detrained for three weeks) ---
    new_ramp_target = result["ramp_target_daily_load"]
    new_ramp_headroom = new_ramp_target - new_recent_baseline
    old_ramp_headroom = 0.0  # old system: both baselines ~300, no ramp needed
    assert new_ramp_headroom > old_ramp_headroom
    assert new_ramp_headroom > 50.0  # a real, substantial ramp, not noise


def test_search_taper_grid_extends_ctl_decay_through_as_of_when_athlete_stopped_logging():
    """Direct test of the as_of-extension mechanism itself (search_taper_
    grid's own docstring paragraph): when the athlete's last logged day is
    well before `as_of`, a zero-load day is seeded at `as_of` so
    `ctl_atl_tsb_series` walks all the way to today -- `anchor_date` becomes
    `as_of`, not the stale last-logged day, and `ctl0` reflects real decay
    through the gap."""
    as_of = date(2026, 9, 5)
    last_logged = as_of - timedelta(days=10)
    workouts = _steady_workouts(last_logged - timedelta(days=60), last_logged, daily_load=200.0)
    athlete = _athlete()
    event = _event(as_of + timedelta(days=30))

    result_extended = search_taper_grid(
        athlete=athlete, event=event, workouts=workouts, as_of=as_of, restriction=None
    )
    result_unextended = search_taper_grid(
        athlete=athlete, event=event, workouts=workouts, as_of=last_logged, restriction=None
    )

    assert result_extended["anchor_date"] == as_of
    assert result_unextended["anchor_date"] == last_logged
    # Ten more days of zero-load decay must measurably lower ctl0/the
    # recent baseline versus stopping the walk at the last logged day.
    assert result_extended["ctl0"] < result_unextended["ctl0"]
    assert result_extended["recent_baseline_daily_load"] < result_unextended["recent_baseline_daily_load"]


def test_search_taper_grid_as_of_extension_is_noop_when_as_of_not_after_last_logged_day():
    """Guard: the extension must ONLY ever extend the walked range forward,
    never touch it when as_of is on or before the last logged day (the
    ordinary case -- an athlete who logged something today or very
    recently) -- must not corrupt the walk range backwards either."""
    last_logged = date(2026, 9, 5)
    workouts = _steady_workouts(last_logged - timedelta(days=30), last_logged, daily_load=150.0)
    athlete = _athlete()
    event = _event(last_logged + timedelta(days=30))

    result_equal = search_taper_grid(
        athlete=athlete, event=event, workouts=workouts, as_of=last_logged, restriction=None
    )
    assert result_equal["anchor_date"] == last_logged

    # as_of strictly BEFORE the last logged day -- the walk must still end
    # at the real latest logged day, not be truncated backward to as_of.
    result_before = search_taper_grid(
        athlete=athlete,
        event=event,
        workouts=workouts,
        as_of=last_logged - timedelta(days=5),
        restriction=None,
    )
    assert result_before["anchor_date"] == last_logged
    assert result_before["ctl0"] == pytest.approx(result_equal["ctl0"])


# --- pre_layoff_baseline: CTL lookup, in-range and out-of-range fallback -------


def test_pre_layoff_baseline_ctl_lookup_normal_in_range_case():
    reported_at = date(2026, 9, 1)
    anchor = date(2026, 9, 10)
    workouts = _steady_workouts(reported_at - timedelta(days=60), anchor, daily_load=250.0)
    athlete = _athlete()
    event = _event(anchor + timedelta(days=30))

    result = search_taper_grid(
        athlete=athlete,
        event=event,
        workouts=workouts,
        as_of=anchor,
        restriction="light_only",
        restriction_reported_at=reported_at,
    )

    series = ctl_atl_tsb_series(daily_loads(workouts, athlete=athlete))
    expected = ctl_at(series, reported_at)
    assert expected is not None  # in range for this scenario -- sanity check
    assert result["pre_layoff_baseline_daily_load"] == pytest.approx(expected)
    assert result["pre_layoff_baseline_used_earliest_fallback"] is False


def test_pre_layoff_baseline_ctl_lookup_falls_back_to_earliest_when_boundary_predates_history():
    # Restriction reported before there is ANY logged history to look up a
    # pre-layoff CTL at (a short/incomplete logging history) -- ctl_at
    # returns None for that out-of-range date, and search_taper_grid falls
    # back to the earliest available CTL in the series (see search_taper_
    # grid's own docstring paragraph on this fallback and why).
    anchor = date(2026, 9, 5)
    history_start = anchor - timedelta(days=5)  # only 5 days of real history
    reported_at = anchor - timedelta(days=15)  # predates all logged history
    workouts = _steady_workouts(history_start, anchor, daily_load=100.0)
    athlete = _athlete()
    event = _event(anchor + timedelta(days=30))

    result = search_taper_grid(
        athlete=athlete,
        event=event,
        workouts=workouts,
        as_of=anchor,
        restriction="light_only",
        restriction_reported_at=reported_at,
    )

    series = ctl_atl_tsb_series(daily_loads(workouts, athlete=athlete))
    assert ctl_at(series, reported_at) is None  # confirms this scenario is genuinely out of range
    assert result["pre_layoff_baseline_daily_load"] == pytest.approx(series[0][1])
    assert result["pre_layoff_baseline_used_earliest_fallback"] is True


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
