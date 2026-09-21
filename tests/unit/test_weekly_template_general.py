"""IDEA 023 v3 follow-ups: the template is a GENERAL structure (not one athlete's
week), slots can carry the athlete's own session content, and a template still
applies when the active macro targets a swim event."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from swim_coach.models import Athlete, Event
from swim_coach.plan import generate_week, scaffold_macro

START = date(2026, 1, 5)
ATHLETE_ID = uuid.uuid4()


def make_athlete(**overrides) -> Athlete:
    data = dict(
        id=ATHLETE_ID, slug="x", name="X", css_pace_s_per_100m=95.0, zones=None, constraints={},
        pool_schedule=["tue", "thu"], sports=["bike", "swim_pool", "swim_ow"],
    )
    data.update(overrides)
    return Athlete(**data)


def _iso(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _bike_event() -> Event:
    return Event(
        id=uuid.uuid4(), athlete_id=ATHLETE_ID, name="CX", event_date=START + timedelta(weeks=24),
        target_metric="duration_min", distance_m=None, target_value=300.0, primary_sport="bike", priority="A",
    )


def _swim_event() -> Event:
    return Event(
        id=uuid.uuid4(), athlete_id=ATHLETE_ID, name="Halloween swim", event_date=START + timedelta(weeks=24),
        distance_m=20000, water_temp_c=18.0, wetsuit=False, priority="A",
    )


def _week(athlete, event, *, primary_sport, week_offset=None, block_name=("build", "peak"), **kw):
    macro = scaffold_macro(athlete, event, START, current_weekly_volume_m=200 if primary_sport == "bike" else 8000,
                           peak_weekly_volume_m=600 if primary_sport == "bike" else 20000)
    block = next(b for b in macro.blocks if b.name in block_name)
    ws = block.start_date
    return generate_week(athlete, macro, _iso(ws), ws, primary_sport=primary_sport, event=event, events=[event], **kw), ws


# --- slot content ---------------------------------------------------------------


def test_slot_purpose_is_used_verbatim_so_the_athletes_own_strength_content_survives() -> None:
    kb = "Kettlebell EMOM: 10 min, swings + goblet squats, alternate minutes"
    a = make_athlete(weekly_template={"tue": [{"kind": "strength", "purpose": kb}], "sat": [{"kind": "bike", "role": "endurance"}]})
    week, ws = _week(a, _bike_event(), primary_sport="bike")
    strength = next(s for s in week.sessions if s.sport == "strength")
    assert strength.purpose == kb


def test_hard_bike_slot_purpose_overrides_the_text_but_keeps_the_structured_intervals() -> None:
    a = make_athlete(weekly_template={"tue": [{"kind": "bike", "role": "hard", "purpose": "over/unders, second interval day"}]})
    week, _ = _week(a, _bike_event(), primary_sport="bike")
    ride = week.sessions[0]
    assert ride.purpose == "over/unders, second interval day"
    assert ride.structured is not None and ride.intensity.get("zone") not in (None, "Z2")


def test_an_unreasonable_purpose_is_fixed_up_with_a_note_not_rejected() -> None:
    a = make_athlete(weekly_template={"mon": [{"kind": "yoga", "purpose": "x" * 4000}, {"kind": "yoga", "purpose": 5}]})
    slots = a.weekly_template["mon"]
    assert len(slots[0]["purpose"]) == 1500 and "purpose" not in slots[1]


# --- generality: not one athlete's week --------------------------------------------


def test_a_completely_different_week_shape_works_and_explicit_durations_win() -> None:
    a = make_athlete(weekly_template={
        "mon": [{"kind": "strength"}],
        "wed": [{"kind": "bike", "role": "hard"}],
        "sat": [{"kind": "bike", "role": "endurance", "duration_min": 180}],
        "sun": [{"kind": "recovery", "duration_min": 20}],
    })
    week, ws = _week(a, _bike_event(), primary_sport="bike")
    by = {(s.date - ws).days: s for s in week.sessions}
    assert sorted(by) == [0, 2, 5, 6]
    assert by[5].duration_min == 180 and by[6].duration_min == 20
    assert by[2].intensity.get("zone") not in (None, "Z2")


def test_a_single_slot_week_is_fine() -> None:
    a = make_athlete(weekly_template={"sat": [{"kind": "bike", "role": "endurance"}]})
    week, _ = _week(a, _bike_event(), primary_sport="bike")
    assert len(week.sessions) == 1


# --- a swim-target macro must not silently swallow the template ---------------------------


def test_template_applies_under_a_swim_target_macro_with_held_volume() -> None:
    a = make_athlete(ftp_watts=250.0, weekly_template={
        "tue": [{"kind": "bike", "role": "hard"}], "wed": [{"kind": "bike", "role": "endurance"}, {"kind": "yoga"}],
    })
    week, ws = _week(a, _swim_event(), primary_sport="swim", template_bike_minutes=240.0, ftp_watts=250.0)
    assert sorted(s.sport for s in week.sessions) == ["bike", "bike", "recovery"]
    bike_min = sum(s.duration_min for s in week.sessions if s.sport == "bike")
    assert 230 <= bike_min <= 260
    assert not any(s.sport in ("swim_pool", "swim_ow") for s in week.sessions)
    assert any("swim" in w.lower() and "held" in w.lower() for w in week.planning_warnings)


def test_default_minutes_are_used_when_no_held_volume_is_known() -> None:
    a = make_athlete(weekly_template={"tue": [{"kind": "bike", "role": "hard"}], "sun": [{"kind": "bike", "role": "endurance"}]})
    week, _ = _week(a, _swim_event(), primary_sport="swim")
    assert sum(s.duration_min for s in week.sessions if s.sport == "bike") == pytest.approx(150, abs=5)  # 60 + 90


def test_swim_target_taper_week_keeps_the_swim_week_and_says_the_template_yielded() -> None:
    a = make_athlete(weekly_template={"tue": [{"kind": "bike", "role": "hard"}]})
    week, _ = _week(a, _swim_event(), primary_sport="swim", block_name=("taper",), template_bike_minutes=200.0)
    assert any(s.sport in ("swim_pool", "swim_ow") for s in week.sessions)
    assert any("weekly_template" in w for w in week.planning_warnings)


def test_swim_athlete_without_a_template_is_unchanged() -> None:
    a = make_athlete()
    week, _ = _week(a, _swim_event(), primary_sport="swim")
    assert any(s.sport in ("swim_pool", "swim_ow") for s in week.sessions)
    assert not any("weekly_template" in w for w in week.planning_warnings)

# --- a week no macro block covers: write it (warned), do not refuse ---------------------------


def _uncovered_week(athlete, event, **kw):
    macro = scaffold_macro(athlete, event, START, current_weekly_volume_m=200, peak_weekly_volume_m=600)
    far = macro.blocks[-1].end_date + timedelta(days=15)
    ws = far - timedelta(days=far.weekday())
    return generate_week(athlete, macro, _iso(ws), ws, primary_sport="bike", event=event, events=[event], **kw), ws


def test_a_week_outside_the_macro_is_still_written_from_the_template_with_held_volume() -> None:
    a = make_athlete(weekly_template={"tue": [{"kind": "bike", "role": "hard"}], "sun": [{"kind": "bike", "role": "endurance"}]})
    week, ws = _uncovered_week(a, _bike_event(), template_bike_minutes=240.0)
    assert sorted((s.date - ws).days for s in week.sessions) == [1, 6]
    assert 230 <= sum(s.duration_min for s in week.sessions) <= 260
    assert week.meso_block == "unplanned"
    assert any("no macro" in w.lower() and "held" in w.lower() for w in week.planning_warnings)


def test_an_uncovered_week_without_a_template_still_raises_a_helpful_error() -> None:
    import pytest as _pytest

    with _pytest.raises(ValueError, match="macro"):
        _uncovered_week(make_athlete(), _bike_event())


def test_an_uncovered_week_containing_a_race_still_raises_rather_than_hiding_the_race() -> None:
    import pytest as _pytest

    a = make_athlete(weekly_template={"tue": [{"kind": "bike", "role": "hard"}]})
    macro = scaffold_macro(a, _bike_event(), START, current_weekly_volume_m=200, peak_weekly_volume_m=600)
    far = macro.blocks[-1].end_date + timedelta(days=15)
    ws = far - timedelta(days=far.weekday())
    race = Event(id=uuid.uuid4(), athlete_id=ATHLETE_ID, name="Late race", event_date=ws + timedelta(days=5),
                 target_metric="duration_min", distance_m=None, target_value=1.0, primary_sport="bike", priority="B")
    with _pytest.raises(ValueError, match="macro"):
        generate_week(a, macro, _iso(ws), ws, primary_sport="bike", event=_bike_event(), events=[_bike_event(), race])
