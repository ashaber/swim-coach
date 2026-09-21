"""IDEA 023 phase 1 -- scheduling preferences the GENERATOR honors.

Standing commitments (a club group ride on fixed weekdays that counts as an
endurance day) and strength placement (same day as the interval session) live
on the Athlete, so they survive every regeneration of a week. No LLM, no
network.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from swim_coach.models import Athlete, Event
from swim_coach.plan import (
    _bike_training_days,
    _bike_week_sessions,
    generate_week,
    scaffold_macro,
)

START = date(2026, 1, 5)  # a Monday
ATHLETE_ID = uuid.uuid4()
CLUB = "Heinous club ride"
CLUB_DAYS = [
    {"day": "wed", "label": CLUB, "role": "endurance"},
    {"day": "sun", "label": CLUB, "role": "endurance"},
]


def make_athlete(**overrides) -> Athlete:
    data = dict(
        id=ATHLETE_ID, slug="andrew", name="Andrew", css_pace_s_per_100m=95.0, zones=None,
        constraints={}, pool_schedule=[], sports=["bike"],
    )
    data.update(overrides)
    return Athlete(**data)


def _iso_week(d: date) -> str:
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def _bike_setup(athlete: Athlete, *, weeks: int = 24):
    event = Event(
        id=uuid.uuid4(), athlete_id=ATHLETE_ID, name="CX Race", event_date=START + timedelta(weeks=weeks),
        target_metric="duration_min", distance_m=None, target_value=300.0, primary_sport="bike", priority="A",
    )
    macro = scaffold_macro(athlete, event, START, current_weekly_volume_m=200, peak_weekly_volume_m=600)
    return event, macro


# --- Athlete model -------------------------------------------------------------


def test_new_fields_default_to_none_so_existing_athletes_are_unchanged() -> None:
    a = make_athlete()
    assert a.strength_placement is None
    assert a.training_days is None


def test_strength_placement_rejects_unknown_values() -> None:
    with pytest.raises(ValidationError):
        make_athlete(strength_placement="whenever")


def test_training_days_role_must_be_hard_or_endurance() -> None:
    with pytest.raises(ValidationError):
        make_athlete(training_days={"bike": [{"day": "wed", "role": "recovery"}]})


def test_training_days_dict_entry_needs_a_day() -> None:
    with pytest.raises(ValidationError):
        make_athlete(training_days={"bike": [{"role": "endurance"}]})


# --- role-aware bike day resolution ---------------------------------------------


def test_no_roles_keeps_declared_order_and_no_labels() -> None:
    a = make_athlete(training_days={"bike": ["tue", "wed", "sun"]})
    assert _bike_training_days(a) == ([1, 2, 6], {})


def test_no_pattern_returns_none() -> None:
    assert _bike_training_days(make_athlete()) == (None, {})


def test_explicit_hard_day_goes_first_endurance_days_follow_with_labels() -> None:
    a = make_athlete(training_days={"bike": [CLUB_DAYS[0], {"day": "tue", "role": "hard"}, CLUB_DAYS[1]]})
    offsets, labels = _bike_training_days(a)
    assert offsets == [1, 2, 6]
    assert labels == {2: CLUB, 6: CLUB}


def test_unroled_entry_is_the_hard_day_next_to_endurance_entries() -> None:
    a = make_athlete(training_days={"bike": ["tue", *CLUB_DAYS]})
    assert _bike_training_days(a)[0][0] == 1


def test_only_endurance_days_gets_a_hard_day_added_farthest_from_them() -> None:
    a = make_athlete(training_days={"bike": CLUB_DAYS})
    offsets, labels = _bike_training_days(a)
    assert offsets == [4, 2, 6]  # Friday: two days clear of both Wednesday and Sunday
    assert labels == {2: CLUB, 6: CLUB}


# --- generate_week: build weeks ---------------------------------------------------


def _peak_build_week(athlete: Athlete):
    event, macro = _bike_setup(athlete)
    block = next(b for b in macro.blocks if b.name in ("build", "peak"))
    ws = block.start_date
    week = generate_week(athlete, macro, _iso_week(ws), ws, primary_sport="bike", event=event, events=[event])
    return week, ws


def test_build_week_puts_labelled_endurance_rides_on_the_standing_days() -> None:
    week, ws = _peak_build_week(make_athlete(training_days={"bike": CLUB_DAYS}))
    bike = {(s.date - ws).days: s for s in week.sessions if s.sport == "bike"}
    for offset in (2, 6):
        assert CLUB in bike[offset].purpose
        assert bike[offset].intensity.get("zone") == "Z2"
    hard = [s for s in bike.values() if s.intensity.get("zone") not in (None, "Z2")]
    assert len(hard) == 1
    assert (hard[0].date - ws).days not in (2, 6)
    assert CLUB not in hard[0].purpose


def test_no_standing_days_is_byte_identical_to_before() -> None:
    athlete = make_athlete()
    a, ws = _peak_build_week(athlete)
    b, _ = _peak_build_week(make_athlete(training_days=None, strength_placement=None))
    strip = lambda w: [(s.date, s.sport, s.purpose, s.duration_min) for s in w.sessions]  # noqa: E731
    assert strip(a) == strip(b)


# --- taper / race weeks: the standing claim yields -----------------------------------


def test_taper_week_does_not_apply_the_standing_labels_or_reorder() -> None:
    athlete = make_athlete(training_days={"bike": CLUB_DAYS})
    event, macro = _bike_setup(athlete)
    taper = next(b for b in macro.blocks if b.name == "taper")
    ws = taper.start_date
    week = generate_week(athlete, macro, _iso_week(ws), ws, primary_sport="bike", event=event, events=[event])
    assert not any(CLUB in s.purpose for s in week.sessions)


def _b_race(day: date) -> Event:
    return Event(
        id=uuid.uuid4(), athlete_id=ATHLETE_ID, name="CX Series #1", event_date=day,
        target_metric="duration_min", distance_m=None, target_value=1.0, primary_sport="bike", priority="B",
    )


def test_week_with_a_race_in_it_does_not_apply_the_standing_labels() -> None:
    athlete = make_athlete(training_days={"bike": CLUB_DAYS})
    event, macro = _bike_setup(athlete)
    ws = macro.blocks[0].start_date + timedelta(weeks=2)
    race = _b_race(ws + timedelta(days=5))  # Saturday of this base-block week
    week = generate_week(athlete, macro, _iso_week(ws), ws, primary_sport="bike", event=event, events=[event, race])
    assert not any(CLUB in s.purpose for s in week.sessions)


def test_week_just_before_a_race_uses_openers_and_drops_the_standing_labels() -> None:
    athlete = make_athlete(training_days={"bike": CLUB_DAYS})
    event, macro = _bike_setup(athlete)
    ws = macro.blocks[0].start_date + timedelta(weeks=2)
    race = _b_race(ws + timedelta(days=6 + 5))  # 5 days after this week ends
    week = generate_week(athlete, macro, _iso_week(ws), ws, primary_sport="bike", event=event, events=[event, race])
    assert any("opener" in s.purpose.lower() for s in week.sessions if s.sport == "bike")
    assert not any(CLUB in s.purpose for s in week.sessions)


# --- strength placement -------------------------------------------------------------


def _hard_and_strength(week, ws):
    hard = next(s for s in week.sessions if s.sport == "bike" and s.intensity.get("zone") not in (None, "Z2"))
    strength = sorted(((s.date - ws).days, s) for s in week.sessions if s.sport == "strength")
    return (hard.date - ws).days, strength


def test_same_day_as_hard_puts_the_first_strength_session_on_the_interval_day() -> None:
    week, ws = _peak_build_week(make_athlete(strength_placement="same_day_as_hard"))
    hard_day, strength = _hard_and_strength(week, ws)
    assert strength[0][0] == hard_day
    assert "after" in strength[0][1].purpose.lower() and "interval" in strength[0][1].purpose.lower()


def test_same_day_as_hard_still_never_puts_strength_the_day_before_a_hard_day() -> None:
    week, ws = _peak_build_week(make_athlete(strength_placement="same_day_as_hard"))
    hard_day, strength = _hard_and_strength(week, ws)
    for offset, _ in strength:
        assert offset >= hard_day
        assert offset != hard_day - 1


def test_default_strength_placement_does_not_force_same_day() -> None:
    week, ws = _peak_build_week(make_athlete(strength_placement="after_hard"))
    other, ws2 = _peak_build_week(make_athlete())
    strip = lambda w: [(s.date, s.sport, s.purpose) for s in w.sessions]  # noqa: E731
    assert strip(week) == strip(other)


def test_same_day_and_standing_days_compose() -> None:
    week, ws = _peak_build_week(
        make_athlete(training_days={"bike": CLUB_DAYS}, strength_placement="same_day_as_hard")
    )
    hard_day, strength = _hard_and_strength(week, ws)
    assert hard_day == 4
    assert strength[0][0] == 4


def test_bike_week_sessions_labels_only_the_days_given() -> None:
    a = make_athlete()
    sessions = _bike_week_sessions(
        a, START, 420.0, None, bike_day_offsets=[1, 2, 6], bike_day_labels={2: CLUB, 6: CLUB}
    )
    by_day = {(s.date - START).days: s for s in sessions}
    assert CLUB in by_day[2].purpose and CLUB in by_day[6].purpose
    assert CLUB not in by_day[1].purpose
