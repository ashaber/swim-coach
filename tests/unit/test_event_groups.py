"""Event groups: model back-compat, effective target, planning targets, kind derivation."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from swim_coach.analysis import derive_workout_kind
from swim_coach.event_groups import (
    disband_group,
    effective_target,
    group_of,
    groups,
    group_span,
    planning_targets,
    race_dates,
    set_group,
)
from swim_coach.models import Athlete, Event, Workout
from swim_coach.plan import _race_week_checklist, generate_week, scaffold_season_macro

ATHLETE_ID = uuid.uuid4()
START = date(2026, 1, 5)  # a Monday


def _event(name: str, day: date, *, priority: str = "A", sport: str = "bike", **kw) -> Event:
    data = dict(
        id=uuid.uuid4(), athlete_id=ATHLETE_ID, name=name, event_date=day, target_metric="duration_min",
        target_value=90.0, priority=priority, primary_sport=sport,
    )
    data.update(kw)
    return Event(**data)


def _weekend(first: date = date(2026, 10, 17)) -> tuple[list[Event], Event, Event]:
    sat, sun = _event("Sat", first), _event("Sun", first + timedelta(days=1))
    _gid, events = set_group(
        [sat, sun], name="Peak Weekend", group_type="double_header", member_ids=[sat.id, sun.id]
    )
    return events, events[0], events[1]


def test_event_without_group_validates_unchanged():
    e = _event("Solo", date(2026, 10, 1))
    assert (e.group_id, e.group_name, e.group_type, e.group_peak) == (None, None, None, False)
    assert group_of(e, [e]) is None
    assert effective_target(e, [e]) is e
    assert planning_targets([e]) == [e]
    # an old stored row without any group key loads
    assert Event.model_validate(e.model_dump(mode="json", exclude={"group_id", "group_name", "group_type", "group_peak"}))


def test_effective_target_defaults_to_first_race_and_honours_override():
    events, sat, sun = _weekend()
    assert effective_target(sun, events).id == sat.id
    assert group_of(sun, events).peak_event_id == sat.id
    _gid, events = set_group(
        events, name="Peak Weekend", group_type="double_header", member_ids=[sat.id, sun.id],
        peak_event_id=sun.id, group_id=sat.group_id,
    )
    assert effective_target(events[0], events).id == events[1].id
    g = group_of(events[0], events)
    assert (g.first_date, g.last_date, g.priority) == (date(2026, 10, 17), date(2026, 10, 18), "A")


def test_group_priority_is_the_peaks_and_a_group_is_one_target():
    a, b = _event("Day1", date(2026, 10, 17), priority="A"), _event("Day2", date(2026, 10, 18), priority="B")
    other = _event("Other", date(2026, 12, 1), priority="B")
    _gid, events = set_group([a, b, other], name="G", group_type="stage_race", member_ids=[a.id, b.id])
    assert [e.name for e in planning_targets(events)] == ["Day1", "Other"]
    assert [g.priority for g in groups(events)] == ["A"]


def test_set_group_validation_and_disband():
    a, b, c = _event("A", date(2026, 10, 1)), _event("B", date(2026, 10, 2)), _event("C", date(2026, 10, 3))
    with pytest.raises(ValueError):
        set_group([a, b], name="G", group_type="omnium", member_ids=[a.id])
    with pytest.raises(ValueError):
        set_group([a, b], name="G", group_type="omnium", member_ids=[a.id, b.id], peak_event_id=c.id)
    gid, events = set_group([a, b, c], name="G", group_type="omnium", member_ids=[a.id, b.id])
    with pytest.raises(ValueError):
        set_group(events, name="H", group_type="omnium", member_ids=[b.id, c.id])
    # replacing the group's members ungroups the dropped one
    _g, events = set_group(events, name="G", group_type="omnium", member_ids=[b.id, c.id], group_id=gid)
    assert [e.group_id for e in events] == [None, gid, gid]
    assert all(e.group_id is None for e in disband_group(events, gid))


def test_span_includes_rest_days_but_race_days_are_members_only():
    a, c = _event("Stage 1", date(2026, 6, 1), sport="swim"), _event("Stage 3", date(2026, 6, 3), sport="swim")
    _gid, events = set_group([a, c], name="Greece", group_type="stage_race", member_ids=[a.id, c.id])
    assert race_dates(events) == {date(2026, 6, 1), date(2026, 6, 3)}  # members only
    assert group_span(events) == {date(2026, 6, 1), date(2026, 6, 2), date(2026, 6, 3)}
    # an inactive group contributes nothing
    off = [e.model_copy(update={"active": False}) for e in events]
    assert race_dates(off) == set() and group_span(off) == set()


def _ride(day: date) -> Workout:
    return Workout(
        id=uuid.uuid4(), athlete_id=ATHLETE_ID, date=day, sport="bike", source="fit", duration_min=60.0, distance_m=1000,
    )


def test_untagged_ride_on_day_two_derives_race_but_a_rest_day_does_not():
    events, sat, sun = _weekend()
    assert derive_workout_kind(_ride(date(2026, 10, 18)), None, events) == "race"
    assert derive_workout_kind(_ride(date(2026, 10, 19)), None, events) == "free_ride"
    a, c = _event("D1", date(2026, 10, 1)), _event("D3", date(2026, 10, 3))
    _gid, gap = set_group([a, c], name="G", group_type="stage_race", member_ids=[a.id, c.id])
    assert derive_workout_kind(_ride(date(2026, 10, 2)), None, gap) == "free_ride"  # rest day in the span
    assert derive_workout_kind(_ride(date(2026, 10, 3)), None, gap) == "race"
    # a swim on a bike group's race day is not a race
    swim = _ride(date(2026, 10, 18)).model_copy(update={"sport": "swim_pool"})
    assert derive_workout_kind(swim, None, events) == "free_ride"


def _athlete() -> Athlete:
    return Athlete(
        id=ATHLETE_ID, slug="t", name="T", css_pace_s_per_100m=95.0, zones=None, constraints={},
        pool_schedule=["tue"], sports=["bike"],
    )


def test_season_macro_counts_a_group_as_one_target_and_tapers_to_its_peak():
    athlete = _athlete()
    sat = _event("Sat", START + timedelta(weeks=14, days=5), priority="A")
    sun = _event("Sun", START + timedelta(weeks=14, days=6), priority="A")
    final = _event("Finale", START + timedelta(weeks=24), priority="B")
    _gid, events = set_group([sat, sun, final], name="Peak", group_type="double_header", member_ids=[sat.id, sun.id])
    macro, _w = scaffold_season_macro(
        athlete, events, START, current_weekly_volume_m=1000, established_base=True, peak_weekly_volume_m=2000
    )
    tagged = {b.race_event_id for b in macro.blocks if b.race_event_id}
    assert tagged == {sat.id, final.id}  # the group is ONE target (its earliest/peak race)
    # same macro as planning for the two peak-only events: groups add nothing
    solo = [sat.model_copy(update={"group_id": None, "group_name": None, "group_type": None}), final]
    solo_macro, _ = scaffold_season_macro(
        athlete, solo, START, current_weekly_volume_m=1000, established_base=True, peak_weekly_volume_m=2000
    )
    assert [(b.name, b.start_date, b.end_date) for b in macro.blocks] == [
        (b.name, b.start_date, b.end_date) for b in solo_macro.blocks
    ]


def test_race_week_checklist_is_dated_to_the_group_peak_not_member_two():
    athlete = _athlete()
    sat = _event("Sat", START + timedelta(weeks=14, days=5), priority="A")
    sun = _event("Sun", START + timedelta(weeks=14, days=6), priority="A")
    final = _event("Finale", START + timedelta(weeks=24), priority="B")
    _gid, events = set_group([sat, sun, final], name="Peak", group_type="double_header", member_ids=[sat.id, sun.id])
    macro, _ = scaffold_season_macro(
        athlete, events, START, current_weekly_volume_m=1000, established_base=True, peak_weekly_volume_m=2000
    )
    taper = next(b for b in macro.blocks if b.name == "taper" and b.race_event_id == sat.id)
    weeks = (taper.end_date - taper.start_date).days // 7 + 1
    final_week = taper.start_date + timedelta(weeks=weeks - 1)
    iso = f"{final_week.isocalendar()[0]}-W{final_week.isocalendar()[1]:02d}"
    # the caller hands the NON-peak member as `event` (macro.event_id / name lookups can);
    # generate_week still aims at the group's peak
    week = generate_week(athlete, macro, iso, final_week, primary_sport="bike", event=sun, events=events)
    expected = _race_week_checklist(sat, final_week)
    assert [(i.date, i.category) for i in week.race_week_checklist] == [(i.date, i.category) for i in expected]


def test_stage_race_rest_day_is_not_a_race_session_and_gets_no_strength():
    from swim_coach.plan import scaffold_macro

    athlete = _athlete()
    week_start = START + timedelta(weeks=10)
    days = [_event(f"D{i}", week_start + timedelta(days=i), priority="A") for i in (3, 4, 6)]  # Thu, Fri, Sun
    _gid, events = set_group(days, name="Stage", group_type="stage_race", member_ids=[e.id for e in days])
    macro = scaffold_macro(athlete, _event("Finale", START + timedelta(weeks=24)), START, 1000, 2000)
    iso = f"{week_start.isocalendar()[0]}-W{week_start.isocalendar()[1]:02d}"
    week = generate_week(athlete, macro, iso, week_start, primary_sport="bike", event=events[0], events=events)
    rest_day = week_start + timedelta(days=5)
    assert {s.date for s in week.sessions if s.kind == "race"} == {e.event_date for e in events}
    assert not [s for s in week.sessions if s.date == rest_day]
