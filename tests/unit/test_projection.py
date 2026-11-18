"""Tests for `swim_coach.projection`: deterministic scenario / plan / week-ordering
comparison of load and freshness. Small synthetic fixtures; no I/O, no LLM."""

from __future__ import annotations

import json
import re
import uuid
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from swim_coach.cli import main
from swim_coach.load import ctl_atl_tsb_series
from swim_coach.models import Athlete, Event, MacroPlan, MacroWeek, Session, Workout, WeekPlan
from swim_coach.plan_check import (
    SUSTAINED_LOW_TSB_THRESHOLD,
    _project_ctl_atl_tsb,
    _spread_weekly_tss_to_daily,
    check_macro,
)
from swim_coach.projection import (
    COMPARISON_LIMITS,
    TrainingScenario,
    compare_scenarios,
    compare_week_sequences,
    hard_day_offsets,
    project_macro,
    project_scenario,
    scenario_daily_loads,
    scenario_hard_days,
    scenario_weeks,
    split_load_per_hour,
    training_day_offsets,
)

START = date(2026, 11, 16)  # a Monday
EASY, HARD = 45.0, 75.0
FORBIDDEN = re.compile(
    r"\b(better|worse|best|worst|optimal|winner|wins|recommend\w*|superior|should|ideal)\b", re.I
)


def _athlete(**overrides) -> Athlete:
    defaults = dict(id=uuid.uuid4(), slug="t", name="T", css_pace_s_per_100m=None, constraints={}, pool_schedule=[])
    defaults.update(overrides)
    return Athlete(**defaults)


def _event(day: date, name: str = "Race", athlete_id: uuid.UUID | None = None) -> Event:
    return Event(
        id=uuid.uuid4(),
        athlete_id=athlete_id or uuid.uuid4(),
        name=name,
        event_date=day,
        target_metric="duration_min",
        target_value=50.0,
        distance_m=None,
        priority="A",
        primary_sport="bike",
        active=True,
    )


def _scenario(name: str, days: int, hours: float, **kw) -> TrainingScenario:
    return TrainingScenario(name=name, days_per_week=days, hours_per_week=hours, **kw)


def _project(scenario: TrainingScenario, **overrides):
    kwargs = dict(
        current_ctl=40.0,
        current_atl=40.0,
        start=START,
        end=START + timedelta(weeks=8) - timedelta(days=1),
        events=[_event(START + timedelta(weeks=8) - timedelta(days=1))],
        recent_weekly_hours=[8.0, 9.0],
        recent_tss_per_hour=50.0,
        today=START,
        tss_per_hour_easy=EASY,
        tss_per_hour_hard=HARD,
    )
    kwargs.update(overrides)
    return project_scenario(scenario, _athlete(), **kwargs)


# --- scenario validation ----------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs, message",
    [
        (dict(days_per_week=0, hours_per_week=5), "days_per_week"),
        (dict(days_per_week=8, hours_per_week=5), "days_per_week"),
        (dict(days_per_week=4, hours_per_week=0), "hours_per_week"),
        (dict(days_per_week=3, hours_per_week=5, hard_sessions_per_week=4), "hard_sessions_per_week"),
        (dict(days_per_week=4, hours_per_week=5, long_session_share=0.1), "long_session_share"),
        (dict(days_per_week=4, hours_per_week=5, recovery_week_every=0), "recovery_week_every"),
        (dict(days_per_week=4, hours_per_week=5, taper_weeks=2), "taper_reduction"),
        (dict(days_per_week=4, hours_per_week=5, taper_reduction=0.4), "taper_weeks"),
    ],
)
def test_scenario_validation_names_the_offending_field(kwargs, message):
    with pytest.raises(ValidationError, match=message):
        TrainingScenario(name="x", **kwargs)


# --- scenario -> weeks ------------------------------------------------------------


def test_weeks_honour_ramp_recovery_cadence_and_taper():
    sc = _scenario(
        "ramp", 4, 10.0, weekly_hours_ramp=0.1, recovery_week_every=3, recovery_week_reduction=0.4,
        taper_weeks=1, taper_reduction=0.5,
    )
    weeks = scenario_weeks(
        sc, start=START, end=START + timedelta(weeks=6) - timedelta(days=1),
        tss_per_hour_easy=EASY, tss_per_hour_hard=HARD,
    )
    assert [w.phase for w in weeks] == ["build", "build", "build", "recovery", "build", "taper"]
    assert [w.recovery for w in weeks] == [False, False, False, True, False, False]
    assert weeks[0].hours == pytest.approx(10.0)
    assert weeks[1].hours == pytest.approx(11.0)
    assert weeks[3].hours == pytest.approx(10 * 1.1**3 * 0.6)
    assert weeks[5].hours == pytest.approx(10 * 1.1**5 * 0.5)
    assert all(w.week_start.weekday() == 0 for w in weeks)


def test_default_recovery_cadence_is_the_plan_check_rule():
    sc = _scenario("flat", 4, 10.0)
    weeks = scenario_weeks(
        sc, start=START, end=START + timedelta(weeks=8) - timedelta(days=1),
        tss_per_hour_easy=EASY, tss_per_hour_hard=HARD,
    )
    assert [w.recovery for w in weeks] == [False, False, False, True, False, False, False, True]


# --- daily placement --------------------------------------------------------------


@pytest.mark.parametrize("days", range(1, 8))
def test_training_days_are_distinct_and_include_the_weekend_long_day(days):
    offsets = training_day_offsets(days)
    assert len(offsets) == len(set(offsets)) == days
    assert 6 in offsets


def test_hard_days_are_spaced_as_far_apart_as_the_days_allow():
    training = training_day_offsets(5)
    hard = hard_day_offsets(training, 2)
    gaps = [(hard[1] - hard[0]), 7 - (hard[1] - hard[0])]
    assert min(gaps) == 3  # best possible for two hard days in a week
    assert 6 not in hard


def test_daily_load_sums_to_weekly_load_and_places_long_session_on_sunday():
    sc = _scenario("a", 5, 12.0, long_session_share=0.3)
    weeks = scenario_weeks(
        sc, start=START, end=START + timedelta(weeks=2) - timedelta(days=1),
        tss_per_hour_easy=EASY, tss_per_hour_hard=HARD,
    )
    loads = scenario_daily_loads(sc, weeks, tss_per_hour_easy=EASY, tss_per_hour_hard=HARD)
    for week in weeks:
        total = sum(loads.get(week.week_start + timedelta(days=i), 0.0) for i in range(7))
        assert total == pytest.approx(week.load_tss)
    assert sum(1 for d, v in loads.items() if v > 0) == 10
    sunday = START + timedelta(days=6)
    assert loads[sunday] == pytest.approx(12.0 * 0.3 * EASY)
    assert all(d.weekday() != 6 for d in scenario_hard_days(sc, weeks))


# --- projection and comparison ----------------------------------------------------


def test_bigger_scenario_has_higher_ctl_ramp_and_lower_tsb():
    big = _project(_scenario("A", 5, 12.0))
    small = _project(_scenario("B", 4, 9.0))
    assert big.ctl_end > small.ctl_end
    assert big.peak_ctl_ramp_per_week > small.peak_ctl_ramp_per_week
    assert big.tsb_end < small.tsb_end
    assert big.days_below_tsb_threshold >= small.days_below_tsb_threshold
    assert big.total_hours > small.total_hours
    assert big.event_metrics[0].tsb < small.event_metrics[0].tsb


def test_comparison_quotes_numbers_and_never_names_a_winner():
    big = _project(_scenario("A", 5, 12.0))
    small = _project(_scenario("B", 4, 9.0))
    comparison = compare_scenarios([big, small])
    text = " ".join(comparison.tradeoffs + comparison.limits)
    assert not FORBIDDEN.search(text)
    assert f"A reaches CTL {big.ctl_end:.0f} vs {small.ctl_end:.0f} for B" in comparison.tradeoffs[0]
    assert f"peak ramp of {big.peak_ctl_ramp_per_week:.1f}/wk vs {small.peak_ctl_ramp_per_week:.1f}/wk" in text
    assert any("On Race" in s for s in comparison.tradeoffs)
    assert comparison.limits == COMPARISON_LIMITS
    assert any("no performance prediction" in s.lower() for s in comparison.limits)
    assert any("sleep" in s.lower() for s in comparison.limits)
    row = next(r for r in comparison.rows if r.key == "ctl_end")
    assert row.values["A"] == pytest.approx(big.ctl_end, abs=0.05)
    assert row.difference_vs_first["B"] == pytest.approx(small.ctl_end - big.ctl_end, abs=0.1)
    assert not FORBIDDEN.search(" ".join(r.label for r in comparison.rows))


def test_five_days_space_hard_sessions_further_apart_than_two_hard_in_a_short_run():
    four = _project(_scenario("B", 4, 9.0, hard_sessions_per_week=3))
    five = _project(_scenario("A", 5, 12.0, hard_sessions_per_week=2))
    assert four.min_hours_between_hard is not None and five.min_hours_between_hard is not None
    assert five.min_hours_between_hard >= four.min_hours_between_hard
    assert five.hard_session_count == 16


def test_event_date_ctl_and_tsb_match_the_series():
    race = START + timedelta(weeks=4) + timedelta(days=2)
    proj = _project(_scenario("A", 5, 12.0), events=[_event(race, "Mid race")])
    by_date = {d: (ctl, tsb) for d, ctl, _atl, tsb in proj.series}
    metric = proj.event_metrics[0]
    assert metric.date == race
    assert (metric.ctl, metric.tsb) == pytest.approx(by_date[race])


def test_inactive_and_out_of_range_events_are_skipped_and_noted():
    late = _event(START + timedelta(weeks=20), "Late")
    proj = _project(_scenario("A", 5, 12.0), events=[late])
    assert proj.event_metrics == []
    assert any("Late" in a for a in proj.assumptions)


def test_projection_is_deterministic():
    events = [_event(START + timedelta(weeks=8) - timedelta(days=1))]
    a = _project(_scenario("A", 5, 12.0), events=events)
    b = _project(_scenario("A", 5, 12.0), events=events)
    assert a.model_dump_json() == b.model_dump_json()
    c1 = compare_scenarios([a, _project(_scenario("B", 4, 9.0), events=events)])
    c2 = compare_scenarios([b, _project(_scenario("B", 4, 9.0), events=events)])
    assert c1.model_dump_json() == c2.model_dump_json()


def test_blended_load_fallback_is_recorded_in_assumptions():
    proj = _project(_scenario("A", 5, 12.0), tss_per_hour_easy=None, tss_per_hour_hard=None)
    assert any("blended" in a.lower() for a in proj.assumptions)
    flat = _project(_scenario("A", 5, 12.0), tss_per_hour_easy=50.0, tss_per_hour_hard=50.0)
    assert proj.ctl_end == pytest.approx(flat.ctl_end)


def test_no_load_rate_at_all_is_a_clear_error():
    with pytest.raises(ValueError, match="load per hour"):
        _project(_scenario("A", 5, 12.0), tss_per_hour_easy=None, tss_per_hour_hard=None, recent_tss_per_hour=None)


def test_scenario_findings_come_from_check_macro():
    sc = _scenario("Aggressive", 6, 20.0, weekly_hours_ramp=0.2)
    proj = _project(sc, current_ctl=20.0, current_atl=20.0)
    assert proj.verdict in {"sound", "sound-with-caveats", "fragile", "not-feasible"}
    assert any(f.id == "ctl-ramp-too-steep" for f in proj.findings)


def test_goal_findings_are_surfaced_separately():
    athlete = _athlete(ftp_watts=150.0, weight_kg=75.0, dob=date(1968, 1, 1))
    proj = project_scenario(
        _scenario("A", 4, 9.0), athlete,
        current_ctl=40.0, current_atl=40.0, start=START, end=START + timedelta(weeks=4) - timedelta(days=1),
        events=[], recent_weekly_hours=[8.0], recent_tss_per_hour=50.0, today=START,
        tss_per_hour_easy=EASY, tss_per_hour_hard=HARD, architecture="Goal: reach 4.5 W/kg",
    )
    assert [f.id for f in proj.goal_findings] == ["goal-reality-check"]


# --- project_macro ----------------------------------------------------------------


def _authored_macro() -> MacroPlan:
    weeks = [
        MacroWeek(week_start=START + timedelta(weeks=i), phase="build", focus="x", hours=h, load_tss=t, ctl_target=c)
        for i, (h, t, c) in enumerate([(8, 400, 45), (9, 560, 50), (10, 800, 55), (6, 250, 52)])
    ]
    return MacroPlan(id=uuid.uuid4(), athlete_id=uuid.uuid4(), event_id=uuid.uuid4(), weeks=weeks)


def test_project_macro_agrees_with_check_macro_projection():
    macro, athlete = _authored_macro(), _athlete()
    end = START + timedelta(weeks=4) - timedelta(days=1)
    kwargs = dict(current_ctl=40.0, current_atl=44.0, recent_weekly_hours=[8.0], recent_tss_per_hour=50.0, events=[], today=START)
    proj = project_macro(macro, athlete, start=START, end=end, **kwargs)
    loads, _est, _unres = _spread_weekly_tss_to_daily(macro.weeks, 50.0)
    expected = _project_ctl_atl_tsb(40.0, loads, START, end, current_atl=44.0)
    assert proj.series == expected
    report = check_macro(macro, athlete, **kwargs)
    assert [f.id for f in proj.findings] == [f.id for f in report.findings]
    low_days = sum(1 for *_x, tsb in expected if tsb < SUSTAINED_LOW_TSB_THRESHOLD)
    assert proj.days_below_tsb_threshold == low_days
    assert proj.hard_session_count is None
    assert any("evenly" in a for a in proj.assumptions)


def test_macro_and_scenario_sit_in_one_comparison():
    macro_proj = project_macro(
        _authored_macro(), _athlete(), current_ctl=40.0, current_atl=40.0, start=START,
        end=START + timedelta(weeks=4) - timedelta(days=1), events=[], recent_weekly_hours=[8.0],
        recent_tss_per_hour=50.0, today=START, name="Current plan",
    )
    scen = _project(_scenario("B", 4, 9.0), end=START + timedelta(weeks=4) - timedelta(days=1), events=[])
    comparison = compare_scenarios([macro_proj, scen])
    assert comparison.names == ["Current plan", "B"]
    assert not FORBIDDEN.search(" ".join(comparison.tradeoffs))


# --- sequence comparison ----------------------------------------------------------


def _session(day_offset: int, zone: str, minutes: float, sport: str = "bike") -> Session:
    return Session(
        id=uuid.uuid4(), athlete_id=uuid.uuid4(), date=START + timedelta(days=day_offset), sport=sport,
        source="ai_coach", duration_min=minutes, intensity={"zone": zone}, purpose="p",
    )


def _week(sessions: list[Session]) -> WeekPlan:
    return WeekPlan(
        id=uuid.uuid4(), athlete_id=uuid.uuid4(), iso_week="2026-W47", meso_block="build", focus="f",
        target_volume_m=0, sessions=sessions,
    )


def test_sequence_comparison_flags_back_to_back_hard_and_strength_before_long():
    spaced = _week([_session(1, "Z5", 60), _session(3, "Z4", 60), _session(5, "Z2", 180), _session(6, "Z1", 45)])
    stacked = _week([
        _session(1, "Z5", 60), _session(2, "Z4", 60), _session(4, "Z1", 45, "strength"), _session(5, "Z2", 180),
    ])
    result = compare_week_sequences({"spaced": spaced, "stacked": stacked}, _athlete(), current_ctl=50.0, current_atl=50.0)
    s, k = result.candidates["spaced"], result.candidates["stacked"]
    assert s.min_hours_between_hard == 48.0 and s.back_to_back_hard_pairs == 0
    assert k.min_hours_between_hard == 24.0 and k.back_to_back_hard_pairs == 1
    assert s.strength_before_key_dates == []
    assert k.strength_before_key_dates == [START + timedelta(days=4)]
    assert set(s.hard_morning_tsb) == {START + timedelta(days=1), START + timedelta(days=3)}
    assert k.longest_morning_tsb is not None
    text = " ".join(result.tradeoffs + result.limits)
    assert "24 h" in text and "48 h" in text
    assert not FORBIDDEN.search(text)


def test_sequence_morning_tsb_uses_the_previous_days_load():
    week = _week([_session(0, "Z5", 60), _session(1, "Z5", 60)])
    result = compare_week_sequences({"w": week, "same": week}, _athlete(), current_ctl=50.0, current_atl=60.0)
    metrics = result.candidates["w"]
    assert metrics.hard_morning_tsb[START] == pytest.approx(-10.0)
    assert metrics.hard_morning_tsb[START + timedelta(days=1)] < -10.0


# --- load split -------------------------------------------------------------------


def _workout(day: int, rpe: int | None, minutes: float = 60.0) -> Workout:
    return Workout(
        id=uuid.uuid4(), athlete_id=uuid.uuid4(), date=START - timedelta(days=day), sport="bike",
        source="manual", distance_m=0, duration_min=minutes, rpe=rpe,
    )


def test_split_load_per_hour_needs_enough_workouts_in_each_bucket():
    athlete = _athlete()
    enough = [_workout(i, 3) for i in range(1, 5)] + [_workout(i + 5, 9) for i in range(1, 5)]
    split = split_load_per_hour(enough, START, athlete=athlete)
    assert split is not None and split[1] > split[0]
    assert split_load_per_hour([_workout(1, 3), _workout(2, 9)], START, athlete=athlete) is None


# --- CLI --------------------------------------------------------------------------


def _seed_history(athlete_tree) -> None:
    today = date.today()
    for i in range(1, 9):
        rpe = 3 if i % 2 else 8
        workout = Workout(
            id=uuid.uuid4(), athlete_id=athlete_tree["athlete"].id, date=today - timedelta(days=i), sport="bike",
            source="manual", distance_m=0, duration_min=60.0, rpe=rpe,
        )
        athlete_tree["store"].save_workout(athlete_tree["slug"], workout)


def test_cli_project_prints_a_comparison(athlete_tree, capsys):
    _seed_history(athlete_tree)
    code = main([
        "--base-dir", str(athlete_tree["base_dir"]), "project", "--athlete", athlete_tree["slug"],
        "--scenario", "five:5:12", "--scenario", "four:4:9:1", "--weeks", "6",
    ])
    out = json.loads(capsys.readouterr().out.strip())
    assert code == 0
    assert out["comparison"]["names"] == ["five", "four"]
    assert out["comparison"]["limits"] == COMPARISON_LIMITS
    assert {p["name"] for p in out["projections"]} == {"five", "four"}


def test_cli_project_rejects_a_malformed_scenario(athlete_tree, capsys):
    code = main([
        "--base-dir", str(athlete_tree["base_dir"]), "project", "--athlete", athlete_tree["slug"],
        "--scenario", "nonsense",
    ])
    assert code != 0
    assert "scenario" in json.loads(capsys.readouterr().out.strip())["error"].lower()


# --- follow-up: common window, past weeks, pairing, flags, events, rounding, ids ------

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _macro_from(first_week: date, count: int, load: float = 450.0) -> MacroPlan:
    weeks = [
        MacroWeek(week_start=first_week + timedelta(weeks=i), phase="build", focus="x", hours=9.0, load_tss=load)
        for i in range(count)
    ]
    return MacroPlan(id=uuid.uuid4(), athlete_id=uuid.uuid4(), event_id=uuid.uuid4(), weeks=weeks)


def _macro_proj(macro: MacroPlan, end: date | None = None, **overrides):
    kwargs = dict(
        current_ctl=40.0, current_atl=40.0, start=START, end=end, events=[], recent_weekly_hours=[8.0],
        recent_tss_per_hour=50.0, today=START,
    )
    kwargs.update(overrides)
    return project_macro(macro, _athlete(), **kwargs)


def test_macro_coverage_ends_at_its_last_authored_week_and_never_decays_after():
    proj = _macro_proj(_macro_from(START, 4), end=START + timedelta(weeks=12) - timedelta(days=1))
    assert proj.coverage_end == START + timedelta(weeks=4) - timedelta(days=1)
    assert proj.series[-1][0] == proj.coverage_end


def test_comparison_uses_the_common_window_and_says_so():
    macro = _macro_proj(_macro_from(START, 4), end=START + timedelta(weeks=12) - timedelta(days=1))
    scen = _project(_scenario("A", 5, 12.0), end=START + timedelta(weeks=12) - timedelta(days=1), events=[])
    comparison = compare_scenarios([macro, scen])
    window_end = macro.coverage_end
    assert comparison.window == (START, window_end)
    by_date = {d: ctl for d, ctl, _a, _t in scen.series}
    row = next(r for r in comparison.rows if r.key == "ctl_end")
    assert row.values["A"] == pytest.approx(by_date[window_end], abs=0.05)
    hours = next(r for r in comparison.rows if r.key == "total_hours")
    assert hours.values["A"] == pytest.approx(12 * 3 + 12 * 0.7, abs=0.05)  # three builds and a recovery week
    text = " ".join(comparison.assumptions["Current plan"] + comparison.assumptions["A"] + comparison.notes)
    assert f"authored only to {window_end.isoformat()}" in text
    assert "over 4 weeks" in " ".join(comparison.tradeoffs)


def test_events_after_the_common_window_are_dropped_with_a_note():
    macro = _macro_proj(_macro_from(START, 4), end=START + timedelta(weeks=8) - timedelta(days=1))
    late = _event(START + timedelta(weeks=7), "Late race")
    scen = _project(_scenario("A", 5, 12.0), events=[late])
    assert scen.event_metrics
    comparison = compare_scenarios([macro, scen])
    assert not any(r.key.endswith(":Late race") for r in comparison.rows)
    assert any("Late race" in a and "dropped" in a for a in comparison.assumptions["A"])


def test_macro_that_began_before_start_projects_only_weeks_from_start():
    began = START - timedelta(weeks=4)
    macro = _macro_from(began, 9)  # four past weeks, five remaining
    proj = _macro_proj(macro, current_ctl=60.0, current_atl=60.0)
    assert proj.weeks[0].week_start == START
    assert len(proj.weeks) == 5
    assert proj.total_hours == pytest.approx(45.0)
    assert proj.series[0][0] == START
    loads = _spread_weekly_tss_to_daily(macro.weeks, 50.0)[0]
    expected = _project_ctl_atl_tsb(60.0, loads, START, proj.coverage_end, current_atl=60.0)
    assert proj.series == expected


def test_macro_entirely_in_the_past_is_an_error():
    with pytest.raises(ValueError, match="before"):
        _macro_proj(_macro_from(START - timedelta(weeks=6), 2))


def _three():
    end = START + timedelta(weeks=4) - timedelta(days=1)
    macro = _macro_proj(_macro_from(START, 4), end=end)
    a = _project(_scenario("A", 5, 12.0), end=end, events=[])
    b = _project(_scenario("B", 4, 9.0), end=end, events=[])
    return macro, a, b


def test_three_projections_get_a_sentence_set_for_every_pair():
    macro, a, b = _three()
    text = compare_scenarios([macro, a, b]).tradeoffs
    assert any(s.startswith("Current plan reaches CTL") and "for A" in s for s in text)
    assert any(s.startswith("Current plan reaches CTL") and "for B" in s for s in text)
    assert any(s.startswith("A reaches CTL") and "for B" in s for s in text)


def test_more_than_three_projections_pair_with_the_first_only_and_say_so():
    macro, a, b = _three()
    c = _project(_scenario("C", 3, 6.0), end=macro.coverage_end, events=[])
    comparison = compare_scenarios([macro, a, b, c])
    assert not any(s.startswith("A reaches CTL") for s in comparison.tradeoffs)
    assert any("more than 3" in n for n in comparison.notes)


def test_steep_peak_ramp_is_flagged_with_the_plan_check_cap():
    proj = _project(_scenario("Aggressive", 6, 20.0, weekly_hours_ramp=0.2), current_ctl=20.0, current_atl=20.0)
    assert any("exceeds the 7/wk cap in week of" in f for f in proj.flags)
    comparison = compare_scenarios([proj, _project(_scenario("B", 4, 9.0))])
    assert comparison.flags["Aggressive"] == proj.flags
    assert any("exceeds the 7/wk cap" in s for s in comparison.tradeoffs)


def test_masters_athlete_uses_the_lower_ramp_cap():
    athlete = _athlete(dob=date(1970, 1, 1))
    proj = project_scenario(
        _scenario("A", 6, 14.0), athlete, current_ctl=20.0, current_atl=20.0, start=START,
        end=START + timedelta(weeks=4) - timedelta(days=1), events=[], recent_weekly_hours=[8.0],
        recent_tss_per_hour=50.0, today=START, tss_per_hour_easy=EASY, tss_per_hour_hard=HARD,
    )
    assert any("5/wk cap" in f for f in proj.flags)


def test_long_deep_tsb_is_flagged():
    proj = _project(_scenario("Heavy", 7, 25.0), current_ctl=20.0, current_atl=20.0)
    assert any("consecutive days" in f and "TSB below -30" in f for f in proj.flags)


def test_untapered_scenario_notes_each_in_window_event():
    race = START + timedelta(weeks=5)
    proj = _project(_scenario("A", 5, 12.0), events=[_event(race, "Gran Fondo")])
    assert any(f"No taper applied before Gran Fondo on {race.isoformat()}" in a for a in proj.assumptions)
    tapered = _project(_scenario("A", 5, 12.0, taper_weeks=1, taper_reduction=0.4), events=[_event(race, "Gran Fondo")])
    assert not any("No taper applied" in a for a in tapered.assumptions)


def test_row_values_and_summaries_are_rounded_per_metric():
    big, small = _project(_scenario("A", 5, 12.0)), _project(_scenario("B", 4, 9.0))
    comparison = compare_scenarios([big, small])
    counts = {"days_below_tsb_threshold", "hard_session_count", "finding_count"}
    for row in comparison.rows:
        digits = 2 if row.key == "mean_weekly_monotony" else 0 if row.key in counts else 1
        for value in [*row.values.values(), *row.difference_vs_first.values()]:
            if value is not None:
                assert value == round(value, digits)
    count_row = next(r for r in comparison.rows if r.key == "days_below_tsb_threshold")
    assert all(isinstance(v, int) for v in count_row.values.values())
    summary = big.to_summary()
    assert summary["ctl_end"] == round(big.ctl_end, 1)
    assert summary["weeks"][0]["hours"] == round(big.weeks[0].hours, 1)


def test_tradeoff_sentences_show_event_names_not_uuids():
    race = START + timedelta(weeks=7)
    proj_a = _project(_scenario("A", 5, 12.0), events=[_event(race, "Gran Fondo")])
    proj_b = _project(_scenario("B", 4, 9.0), events=[_event(race, "Gran Fondo")])
    assert any(UUID_RE.search(f.id) for f in proj_a.findings)
    comparison = compare_scenarios([proj_a, proj_b])
    assert not UUID_RE.search(" ".join(comparison.tradeoffs))
    assert "Gran Fondo" in " ".join(comparison.tradeoffs)
    assert any(UUID_RE.search(i) for ids in comparison.findings.values() for i in ids)


def test_cli_project_applies_taper_to_every_scenario(athlete_tree, capsys):
    _seed_history(athlete_tree)
    code = main([
        "--base-dir", str(athlete_tree["base_dir"]), "project", "--athlete", athlete_tree["slug"],
        "--scenario", "five:5:12", "--scenario", "four:4:9", "--weeks", "6", "--taper", "1:0.4",
    ])
    out = json.loads(capsys.readouterr().out.strip())
    assert code == 0
    assert all(p["weeks"][-1]["phase"] == "taper" for p in out["projections"])
