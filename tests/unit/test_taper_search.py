"""Tests for swim_coach.taper_search: the read-only race-day-TSB taper grid
search. Pure arithmetic + model construction -- no LLM calls, no network,
no store writes (this module never calls any store.save_* method at all).

Fixture numbers are deliberately in the same ballpark as Renee's real
production data quoted in the task brief (CTL~55.8, ATL~99.9, TSB~-44.1 as
of her most recent logged day 2026-08-25; race 2026-09-18; real taper block
2026-08-31..2026-09-13 i.e. 2 weeks at TAPER_WEEKLY_DECAY=0.25) -- this repo
has no access to her real database, so these are constructed, not pulled.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from swim_coach.load import CTL_TIME_CONSTANT_DAYS, ATL_TIME_CONSTANT_DAYS, RACE_DAY_TSB_BAND
from swim_coach.models import Athlete, Event, Workout
from swim_coach.plan import TAPER_WEEKLY_DECAY
from swim_coach.taper_search import (
    BASELINE_WINDOW_DAYS,
    TaperCandidate,
    build_taper_grid,
    project_tsb_series,
    recent_baseline_daily_load,
    search_taper_grid,
    taper_volume_fraction,
)

ATHLETE_ID = uuid.uuid4()
EVENT_ID = uuid.uuid4()


def make_athlete(**overrides):
    data = dict(id=ATHLETE_ID, slug="renee", name="Renee", css_pace_s_per_100m=90.0)
    data.update(overrides)
    return Athlete(**data)


def make_event(**overrides):
    data = dict(
        id=EVENT_ID,
        athlete_id=ATHLETE_ID,
        name="UltraSwim 33.3 Greece",
        event_date=date(2026, 9, 18),
        distance_m=33300,
        priority="A",
    )
    data.update(overrides)
    return Event(**data)


def make_workout(d: date, *, rpe: int = 6, duration_min: float = 90.0, **overrides):
    data = dict(
        id=uuid.uuid4(),
        athlete_id=ATHLETE_ID,
        date=d,
        sport="swim_pool",
        source="manual",
        distance_m=4000,
        duration_min=duration_min,
        rpe=rpe,
    )
    data.update(overrides)
    return Workout(**data)


def _daily_workouts(start: date, end: date, **kwargs) -> list[Workout]:
    """One workout per day in [start, end] inclusive -- a simple, dense
    real-history stand-in so `daily_loads`/`ctl_atl_tsb_series` have a
    real, gap-free series to seed the simulation's starting CTL/ATL from."""
    workouts = []
    day = start
    while day <= end:
        workouts.append(make_workout(day, **kwargs))
        day += timedelta(days=1)
    return workouts


# --- taper_volume_fraction ---------------------------------------------------------


def test_taper_volume_fraction_matches_scaffold_macro_formula():
    # Renee's real current taper: 2 weeks, 0.25 decay -> 1 - 0.25*2 = 0.5,
    # exactly the 50% (13330/26659) her real macro.yaml already shows.
    assert taper_volume_fraction(2, 0.25) == pytest.approx(0.5)


def test_taper_volume_fraction_floors_at_zero():
    assert taper_volume_fraction(6, 0.25) == 0.0


# --- recent_baseline_daily_load ----------------------------------------------------


def test_recent_baseline_daily_load_averages_window_including_zero_rest_days():
    anchor = date(2026, 8, 25)
    # 20 days of load 100, one rest day (absent -> 0), all inside a 21-day window.
    daily = {anchor - timedelta(days=i): 100.0 for i in range(1, 21)}
    load = recent_baseline_daily_load(daily, anchor, window_days=21)
    # 20 real days at 100 + 1 missing/rest day at 0, over 21 days.
    assert load == pytest.approx(2000.0 / 21)


# --- project_tsb_series: recursion correctness (analytic fixed point) --------------


def test_project_tsb_series_constant_load_converges_toward_fixed_point():
    # decay=0 -> volume_fraction=1 -> the "taper" never actually reduces
    # load, so a long projection at constant baseline load must converge
    # CTL and ATL both toward that same load (the EWMA recursion's known
    # fixed point), TSB -> 0 -- same fixed point load.ctl_atl_tsb_series's
    # own "constant load converges" test already verifies for the plain
    # recursion; this confirms the projection wrapper preserves it.
    anchor = date(2026, 1, 1)
    race_date = anchor + timedelta(days=400)  # long runway relative to the 42-day CTL tau
    baseline = 300.0
    ctl, atl, tsb, volume_fraction, taper_start = project_tsb_series(
        ctl0=0.0,
        atl0=0.0,
        anchor_date=anchor,
        race_date=race_date,
        baseline_daily_load=baseline,
        taper_weeks=1,
        decay=0.0,
    )
    assert volume_fraction == pytest.approx(1.0)
    assert ctl == pytest.approx(baseline, abs=1.0)
    assert atl == pytest.approx(baseline, abs=0.1)
    assert tsb == pytest.approx(0.0, abs=1.0)


def test_project_tsb_series_no_runway_returns_starting_point_unchanged():
    # race_date == anchor_date + 1 day means the "day before race day" IS
    # anchor_date itself -- nothing left to project.
    anchor = date(2026, 9, 17)
    race_date = date(2026, 9, 18)
    ctl, atl, tsb, volume_fraction, taper_start = project_tsb_series(
        ctl0=55.8,
        atl0=99.9,
        anchor_date=anchor,
        race_date=race_date,
        baseline_daily_load=400.0,
        taper_weeks=2,
        decay=0.25,
    )
    assert ctl == pytest.approx(55.8)
    assert atl == pytest.approx(99.9)
    assert tsb == pytest.approx(55.8 - 99.9)


def test_project_tsb_series_taper_raises_tsb_relative_to_no_taper():
    # A real taper (reduced load) should leave TSB higher (fresher) at
    # race-day-adjacent than continuing peak-phase load unchanged all the
    # way to race day -- the entire physiological point of tapering.
    anchor = date(2026, 8, 25)
    race_date = date(2026, 9, 18)
    baseline = 400.0
    _, _, tsb_with_taper, _, _ = project_tsb_series(
        ctl0=55.8, atl0=99.9, anchor_date=anchor, race_date=race_date,
        baseline_daily_load=baseline, taper_weeks=2, decay=0.25,
    )
    _, _, tsb_no_taper, _, _ = project_tsb_series(
        ctl0=55.8, atl0=99.9, anchor_date=anchor, race_date=race_date,
        baseline_daily_load=baseline, taper_weeks=1, decay=0.0,
    )
    assert tsb_with_taper > tsb_no_taper


def test_project_tsb_series_taper_start_date_is_race_date_minus_taper_weeks():
    race_date = date(2026, 9, 18)
    _, _, _, _, taper_start = project_tsb_series(
        ctl0=0.0, atl0=0.0, anchor_date=date(2026, 8, 25), race_date=race_date,
        baseline_daily_load=100.0, taper_weeks=3, decay=0.2,
    )
    assert taper_start == race_date - timedelta(weeks=3)


# --- build_taper_grid --------------------------------------------------------------


def test_build_taper_grid_bounds_taper_weeks_by_available_runway():
    combos = build_taper_grid(weeks_available=3, current_real_taper_weeks=2, current_real_decay=0.25)
    assert all(w <= 3 for w, _ in combos)
    assert max(w for w, _ in combos) == 3


def test_build_taper_grid_always_includes_current_real_taper_even_outside_default_bounds():
    # decay=0.99 and taper_weeks=10 are both well outside the default
    # grid's own bounds/available runway -- must still appear.
    combos = build_taper_grid(
        weeks_available=2,
        current_real_taper_weeks=10,
        current_real_decay=0.99,
    )
    assert (10, 0.99) in combos


def test_build_taper_grid_empty_weeks_grid_still_includes_current_real_taper():
    combos = build_taper_grid(weeks_available=0, current_real_taper_weeks=2, current_real_decay=0.25)
    assert combos == [(2, 0.25)]


def test_build_taper_grid_decay_step_produces_expected_values():
    combos = build_taper_grid(
        weeks_available=1,
        current_real_taper_weeks=1,
        current_real_decay=0.25,
        decay_min=0.10,
        decay_max=0.30,
        decay_step=0.10,
    )
    decays = sorted({d for _, d in combos})
    assert decays == [pytest.approx(0.10), pytest.approx(0.20), pytest.approx(0.25), pytest.approx(0.30)]


# --- search_taper_grid: end-to-end ---------------------------------------------------


def _renee_like_history(as_of: date) -> list[Workout]:
    """~61 days of daily swim workouts ending the day before `as_of`: a
    lower-load ~40-day "base phase" (sRPE ~40/day: duration 20min * rpe 2)
    followed by a higher-load ~21-day "build/peak phase" (sRPE ~100/day:
    duration 25min * rpe 4) -- a real base-to-build ramp, not a flat
    constant load, so ATL (tau=7, catches up fast) legitimately outruns
    CTL (tau=42, still climbing) by the last logged day, the same
    "climbing fitness, currently fatigued" shape the task brief describes
    for Renee's real numbers (CTL~55.8, ATL~99.9, TSB~-44.1). Working the
    EWMA recursion by hand for this exact two-phase shape lands at
    CTL~54.3/ATL~97.0/TSB~-42.7 -- deliberately in the same ballpark as
    those real figures, not an exact reproduction (this repo has no
    access to her real database)."""
    base_phase_end = as_of - timedelta(days=22)
    base_phase_start = base_phase_end - timedelta(days=39)
    build_phase_start = base_phase_end + timedelta(days=1)
    build_phase_end = as_of - timedelta(days=1)
    return _daily_workouts(base_phase_start, base_phase_end, rpe=2, duration_min=20.0) + _daily_workouts(
        build_phase_start, build_phase_end, rpe=4, duration_min=25.0
    )


def test_search_taper_grid_includes_current_real_taper_and_reports_band_membership():
    as_of = date(2026, 8, 27)
    athlete = make_athlete()
    event = make_event(event_date=date(2026, 9, 18))
    workouts = _renee_like_history(as_of)

    result = search_taper_grid(
        athlete=athlete,
        event=event,
        workouts=workouts,
        as_of=as_of,
        current_real_taper_weeks=2,
        current_real_decay=TAPER_WEEKLY_DECAY,
    )

    assert result["race_date"] == date(2026, 9, 18)
    assert result["weeks_available"] == 3  # (Sep 18 - Aug 27).days // 7 == 3
    assert result["current_real_taper"].taper_weeks == 2
    assert result["current_real_taper"].decay == pytest.approx(TAPER_WEEKLY_DECAY)
    assert result["current_real_taper"].volume_fraction == pytest.approx(0.5)
    assert isinstance(result["any_in_band"], bool)
    assert isinstance(result["closest_to_band"], TaperCandidate)
    # closest_to_band must actually be the minimum distance-to-band among all candidates
    band = RACE_DAY_TSB_BAND
    def dist(c):
        if band["low"] <= c.projected_tsb <= band["high"]:
            return 0.0
        return min(abs(c.projected_tsb - band["low"]), abs(c.projected_tsb - band["high"]))
    best = min(result["candidates"], key=dist)
    assert result["closest_to_band"].projected_tsb == pytest.approx(best.projected_tsb)


def test_search_taper_grid_grid_search_correctly_flags_in_band_vs_out_of_band():
    as_of = date(2026, 8, 27)
    athlete = make_athlete()
    event = make_event(event_date=date(2026, 9, 18))
    workouts = _renee_like_history(as_of)

    result = search_taper_grid(
        athlete=athlete, event=event, workouts=workouts, as_of=as_of,
        current_real_taper_weeks=2, current_real_decay=TAPER_WEEKLY_DECAY,
    )
    band = result["tsb_band"]
    for candidate in result["candidates"]:
        expected = band["low"] <= candidate.projected_tsb <= band["high"]
        assert candidate.in_band == expected


def test_search_taper_grid_more_aggressive_taper_than_current_real_gets_closer_to_or_into_band():
    # Andrew expects the real current (2wk/0.25) taper to MISS the band
    # (she's deeply fatigued, TSB~-44 at the real starting point) -- a
    # more aggressive volume cut should move projected TSB up, closer to
    # (or into) the band, not further away.
    as_of = date(2026, 8, 27)
    athlete = make_athlete()
    event = make_event(event_date=date(2026, 9, 18))
    workouts = _renee_like_history(as_of)

    result = search_taper_grid(
        athlete=athlete, event=event, workouts=workouts, as_of=as_of,
        current_real_taper_weeks=2, current_real_decay=TAPER_WEEKLY_DECAY,
    )
    real = result["current_real_taper"]
    more_aggressive = next(
        c for c in result["candidates"] if c.taper_weeks == 3 and c.decay == pytest.approx(0.45)
    )
    assert more_aggressive.projected_tsb > real.projected_tsb


def test_search_taper_grid_raises_when_no_workouts_at_all():
    athlete = make_athlete()
    event = make_event()
    with pytest.raises(ValueError):
        search_taper_grid(
            athlete=athlete, event=event, workouts=[], as_of=date(2026, 8, 27),
            current_real_taper_weeks=2,
        )


def test_search_taper_grid_handles_very_little_runway_honestly():
    # Race only 5 days out -- weeks_available floors to 0, so the default
    # TAPER_WEEKS_GRID_MIN=1 grid produces nothing that "fits," but the
    # current real taper is still reported (flagged, not silently
    # excluded or computed as if it were a sane in-runway plan).
    as_of = date(2026, 9, 13)
    athlete = make_athlete()
    event = make_event(event_date=date(2026, 9, 18))
    workouts = _renee_like_history(as_of)

    result = search_taper_grid(
        athlete=athlete, event=event, workouts=workouts, as_of=as_of,
        current_real_taper_weeks=2, current_real_decay=TAPER_WEEKLY_DECAY,
    )
    assert result["weeks_available"] == 0
    # No grid-generated (fits-the-bounds) candidate should exist, only the
    # forced-in current real taper -- and it must be honestly flagged as
    # not fitting the remaining runway.
    assert all(not c.fits_available_runway or c.is_current_real_taper for c in result["candidates"])
    real = result["current_real_taper"]
    assert real.fits_available_runway is False


def test_search_taper_grid_uses_real_ctl_atl_series_last_entry_as_starting_point():
    as_of = date(2026, 8, 27)
    athlete = make_athlete()
    event = make_event(event_date=date(2026, 9, 18))
    workouts = _renee_like_history(as_of)

    from swim_coach.load import ctl_atl_tsb_series, daily_loads
    loads = daily_loads(workouts, athlete=athlete, wellness=[])
    expected_anchor, expected_ctl, expected_atl, expected_tsb = ctl_atl_tsb_series(loads)[-1]

    result = search_taper_grid(
        athlete=athlete, event=event, workouts=workouts, as_of=as_of,
        current_real_taper_weeks=2, current_real_decay=TAPER_WEEKLY_DECAY,
    )
    assert result["anchor_date"] == expected_anchor
    assert result["ctl0"] == pytest.approx(expected_ctl)
    assert result["atl0"] == pytest.approx(expected_atl)
    assert result["tsb0"] == pytest.approx(expected_tsb)
