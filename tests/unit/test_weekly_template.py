"""IDEA 023 v3 -- the weekly template: the athlete states the SHAPE of their
week (which sessions on which days); the engine fills in content and volume
and keeps its safety rails. Acceptance test = Andrew's real week (2026-09-20):

  Mon CX skills + yoga | Tue intervals then strength | Wed group ride |
  Thu off | Fri yoga | Sat intervals then strength | Sun group ride

which the old single-hard-session generator could not produce (D3/D4).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from swim_coach.models import Athlete, Event
from swim_coach.plan import generate_week, scaffold_macro

START = date(2026, 1, 5)  # a Monday
ATHLETE_ID = uuid.uuid4()
CLUB = "Heinous club ride"

ANDREWS_WEEK = {
    "mon": [{"kind": "skills", "label": "CX skills"}, {"kind": "yoga"}],
    "tue": [{"kind": "bike", "role": "hard"}, {"kind": "strength"}],
    "wed": [{"kind": "bike", "role": "endurance", "label": CLUB}],
    "thu": [],
    "fri": [{"kind": "yoga"}],
    "sat": [{"kind": "bike", "role": "hard"}, {"kind": "strength"}],
    "sun": [{"kind": "bike", "role": "endurance", "label": CLUB}],
}


def make_athlete(**overrides) -> Athlete:
    data = dict(
        id=ATHLETE_ID, slug="andrew", name="Andrew", css_pace_s_per_100m=95.0, zones=None,
        constraints={}, pool_schedule=[], sports=["bike"],
    )
    data.update(overrides)
    return Athlete(**data)


def _iso(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _setup(athlete: Athlete):
    event = Event(
        id=uuid.uuid4(), athlete_id=ATHLETE_ID, name="CX Race", event_date=START + timedelta(weeks=24),
        target_metric="duration_min", distance_m=None, target_value=300.0, primary_sport="bike", priority="A",
    )
    macro = scaffold_macro(athlete, event, START, current_weekly_volume_m=200, peak_weekly_volume_m=600)
    return event, macro


def _build_week(athlete: Athlete):
    event, macro = _setup(athlete)
    ws = next(b for b in macro.blocks if b.name in ("build", "peak")).start_date
    return generate_week(athlete, macro, _iso(ws), ws, primary_sport="bike", event=event, events=[event]), ws


def _by_day(week, ws):
    days: dict[int, list] = {}
    for s in sorted(week.sessions, key=lambda s: s.date):
        days.setdefault((s.date - ws).days, []).append(s)
    return days


# --- the acceptance test: Andrew's week ---------------------------------------------


def test_andrews_week_is_generated_exactly_as_stated() -> None:
    week, ws = _build_week(make_athlete(weekly_template=ANDREWS_WEEK))
    days = _by_day(week, ws)

    assert sorted(days) == [0, 1, 2, 4, 5, 6]  # Thursday (3) is off
    assert sorted(s.sport for s in days[0]) == ["bike", "recovery"]  # CX skills + yoga
    assert sorted(s.sport for s in days[1]) == ["bike", "strength"]
    assert [s.sport for s in days[2]] == ["bike"]
    assert [s.sport for s in days[4]] == ["recovery"]
    assert sorted(s.sport for s in days[5]) == ["bike", "strength"]
    assert [s.sport for s in days[6]] == ["bike"]
    assert len(week.sessions) == 9


def test_both_interval_days_are_hard_and_differ_from_each_other() -> None:
    week, ws = _build_week(make_athlete(weekly_template=ANDREWS_WEEK))
    days = _by_day(week, ws)
    tue = next(s for s in days[1] if s.sport == "bike")
    sat = next(s for s in days[5] if s.sport == "bike")
    for s in (tue, sat):
        assert s.intensity.get("zone") not in (None, "Z2")
        assert s.structured is not None
    assert tue.purpose != sat.purpose  # a different interval archetype each hard day


def test_group_rides_are_labelled_z2_and_skills_and_yoga_are_not_hard() -> None:
    week, ws = _build_week(make_athlete(weekly_template=ANDREWS_WEEK))
    days = _by_day(week, ws)
    for offset in (2, 6):
        ride = days[offset][0]
        assert CLUB in ride.purpose and ride.intensity.get("zone") == "Z2"
    skills = next(s for s in days[0] if s.sport == "bike")
    assert "skills" in skills.purpose.lower() and skills.intensity.get("zone") in (None, "Z2")
    yoga = next(s for s in days[0] if s.sport == "recovery")
    assert "yoga" in yoga.purpose.lower()


def test_strength_after_intervals_is_stated_on_the_session() -> None:
    week, ws = _build_week(make_athlete(weekly_template=ANDREWS_WEEK))
    days = _by_day(week, ws)
    for offset in (1, 5):
        strength = next(s for s in days[offset] if s.sport == "strength")
        assert "after" in strength.purpose.lower() and "interval" in strength.purpose.lower()


def test_template_keeps_bike_volume_within_the_macro_target() -> None:
    week, ws = _build_week(make_athlete(weekly_template=ANDREWS_WEEK))
    bike_min = sum(
        s.duration_min for s in week.sessions
        if s.sport == "bike" and "skills" not in s.purpose.lower()
    )
    assert bike_min <= week.target_volume_m * 1.15  # floors may nudge, never blow past the ramp target
    assert bike_min >= week.target_volume_m * 0.6


def test_a_plan_with_two_hard_days_produces_no_structural_warning() -> None:
    week, _ = _build_week(make_athlete(weekly_template=ANDREWS_WEEK))
    assert week.planning_warnings == []


def test_three_hard_days_is_allowed_but_warned_never_blocked() -> None:
    template = {
        "mon": [{"kind": "bike", "role": "hard"}],
        "wed": [{"kind": "bike", "role": "hard"}],
        "fri": [{"kind": "bike", "role": "hard"}],
        "sun": [{"kind": "bike", "role": "endurance"}],
        "tue": [{"kind": "bike", "role": "hard"}],
    }
    week, ws = _build_week(make_athlete(weekly_template=template))
    hard = [s for s in week.sessions if s.sport == "bike" and s.intensity.get("zone") not in (None, "Z2")]
    assert len(hard) == 4  # honoured, not silently reduced
    assert week.planning_warnings  # the realism guardrail speaks up instead of blocking


def test_no_template_is_unchanged() -> None:
    a, ws = _build_week(make_athlete())
    b, _ = _build_week(make_athlete(weekly_template=None))
    strip = lambda w: [(s.date, s.sport, s.purpose, s.duration_min) for s in w.sessions]  # noqa: E731
    assert strip(a) == strip(b)


# --- taper / race weeks: the template yields, and says so -------------------------------


def test_taper_week_does_not_apply_the_template_and_warns() -> None:
    athlete = make_athlete(weekly_template=ANDREWS_WEEK)
    event, macro = _setup(athlete)
    ws = next(b for b in macro.blocks if b.name == "taper").start_date
    week = generate_week(athlete, macro, _iso(ws), ws, primary_sport="bike", event=event, events=[event])
    assert not any(s.sport == "recovery" for s in week.sessions)
    assert any("weekly_template" in w for w in week.planning_warnings)


def test_race_week_does_not_apply_the_template_and_warns() -> None:
    athlete = make_athlete(weekly_template=ANDREWS_WEEK)
    event, macro = _setup(athlete)
    ws = macro.blocks[0].start_date + timedelta(weeks=2)
    race = Event(
        id=uuid.uuid4(), athlete_id=ATHLETE_ID, name="CX #1", event_date=ws + timedelta(days=5),
        target_metric="duration_min", distance_m=None, target_value=1.0, primary_sport="bike", priority="B",
    )
    week = generate_week(athlete, macro, _iso(ws), ws, primary_sport="bike", event=event, events=[event, race])
    assert any("weekly_template" in w for w in week.planning_warnings)


# --- model validation ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "template",
    [
        {"someday": [{"kind": "bike", "role": "hard"}]},
        {"mon": [{"kind": "swimming"}]},
        {"mon": [{"kind": "bike"}]},                              # bike needs a role
        {"mon": [{"kind": "yoga", "role": "hard"}]},              # role only for bike
        {"mon": [{"kind": "bike", "role": "medium"}]},
        {"mon": [{"kind": "yoga", "label": "x" * 200}]},
        {"mon": [{"kind": "yoga", "duration_min": 2}]},
        {"mon": "yoga"},
    ],
)
def test_invalid_templates_are_rejected(template) -> None:
    with pytest.raises(ValidationError):
        make_athlete(weekly_template=template)


def test_weekday_names_are_case_insensitive_and_full_names_work() -> None:
    a = make_athlete(weekly_template={"Monday": [{"kind": "yoga"}], "FRI": [{"kind": "yoga"}]})
    week, ws = _build_week(a)
    assert sorted(_by_day(week, ws)) == [0, 4]


def test_weekly_template_defaults_to_none() -> None:
    assert make_athlete().weekly_template is None
