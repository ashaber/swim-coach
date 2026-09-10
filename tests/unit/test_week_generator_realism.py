"""Build A -- week-generator realism (engine/week-generator-realism).

Covers the five defects the bike-primary week generator had, found live
building Andrew's real cyclocross week:

  1. flat 5-session ceiling -> a realistic-planning guardrail
     (`plan.evaluate_week_realism`)
  2. `Athlete.training_days` weekday-pattern field
  3. `session_overrides` add mode (`backend/app/tools.py`)
  4. strength always scheduled AFTER the week's interval session
  5. race-proximity / taper -> "openers" template + volume pull-down,
     race weeks -> RACE-labelled sessions

No LLM, no network -- pure arithmetic + model validation.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from swim_coach.models import Athlete, Event, Session
from swim_coach.plan import (
    BIKE_INTERVAL_TEMPLATE_META,
    BIKE_INTERVAL_TEMPLATES,
    BIKE_MAX_BIKE_DAYS_PER_WEEK,
    BIKE_MAX_HARD_DAYS_PER_WEEK,
    BIKE_OPENERS_PROXIMITY_DAYS,
    STRENGTH_SESSIONS_PER_WEEK,
    _bike_week_sessions,
    _select_bike_interval_template,
    _training_day_offsets,
    evaluate_week_realism,
    generate_week,
    scaffold_macro,
)

START = date(2026, 1, 5)  # a Monday
ATHLETE_ID = uuid.uuid4()


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
        name="Catalina Channel",
        event_date=START + timedelta(weeks=24),
        distance_m=20000,
        water_temp_c=18.0,
        wetsuit=False,
        priority="A",
    )
    data.update(overrides)
    return Event(**data)


def _iso_week(d: date) -> str:
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def _bike_setup(**event_overrides):
    athlete = make_athlete(sports=["bike"])
    event = make_event(
        event_date=START + timedelta(weeks=24),
        target_metric="duration_min",
        distance_m=None,
        target_value=300.0,
        primary_sport="bike",
        **event_overrides,
    )
    macro = scaffold_macro(
        athlete, event, START, current_weekly_volume_m=200, peak_weekly_volume_m=600
    )
    return athlete, event, macro


def _mk_session(offset: int, sport: str, zone: str | None, purpose: str = "x", *, week_start=START):
    return Session(
        id=uuid.uuid4(),
        athlete_id=ATHLETE_ID,
        date=week_start + timedelta(days=offset),
        sport=sport,
        source="ai_coach",
        duration_min=60.0,
        distance_m=None,
        intensity={"zone": zone} if zone else {"anchor": "rpe"},
        purpose=purpose,
        status="planned",
    )


# ===========================================================================
# Defect 2 -- Athlete.training_days weekday pattern
# ===========================================================================


def test_training_days_defaults_to_none_and_existing_athletes_validate():
    a = make_athlete()
    assert a.training_days is None
    assert _training_day_offsets(a, "bike") is None


def test_training_days_maps_weekday_names_to_offsets_preserving_order():
    a = make_athlete(training_days={"bike": ["tue", "wed", "sat", "sun"], "strength": ["thu"]})
    assert _training_day_offsets(a, "bike") == [1, 2, 5, 6]
    assert _training_day_offsets(a, "strength") == [3]
    assert _training_day_offsets(a, "mobility") is None


def test_bike_week_places_sessions_on_pattern_weekdays():
    a = make_athlete(sports=["bike"], training_days={"bike": ["mon", "tue", "wed", "sat", "sun"]})
    sessions = _bike_week_sessions(a, START, 420.0, None, bike_day_offsets=[0, 1, 2, 5, 6])
    offsets = sorted((s.date - START).days for s in sessions)
    assert offsets == [0, 1, 2, 5, 6]


def test_bike_week_without_pattern_is_unchanged_even_spacing():
    a = make_athlete(sports=["bike"])
    with_none = _bike_week_sessions(a, START, 180.0, None)
    offsets = sorted((s.date - START).days for s in with_none)
    # historical even-spacing for a 3-session week
    assert offsets == [0, 2, 5]


# ===========================================================================
# Defect 1 -- realism guardrail
# ===========================================================================


def test_realism_ok_for_a_realistic_multimodal_week():
    # 4 bike days (1 hard), 2 strength, 2 race days -- exactly the shape
    # Andrew called out as legitimate. No warnings.
    sessions = [
        _mk_session(0, "bike", "Z2"),
        _mk_session(1, "bike", "Z4", "sustained threshold intervals"),
        _mk_session(2, "bike", "Z2"),
        _mk_session(3, "bike", "Z2"),
        _mk_session(3, "strength", None),
        _mk_session(4, "strength", None),
        _mk_session(5, "bike", "Z5", "RACE — CX #1"),
        _mk_session(6, "bike", "Z5", "RACE — CX #2"),
    ]
    assert evaluate_week_realism(sessions) == []


def test_realism_flags_too_many_hard_bike_days():
    sessions = [
        _mk_session(0, "bike", "Z4", "intervals"),
        _mk_session(1, "bike", "Z4", "intervals"),
        _mk_session(3, "bike", "Z5", "intervals"),
        _mk_session(5, "bike", "Z4", "intervals"),
    ]
    warnings_out = evaluate_week_realism(sessions)
    assert any("hard bike day" in w.lower() for w in warnings_out)
    assert str(BIKE_MAX_HARD_DAYS_PER_WEEK) in " ".join(warnings_out)


def test_realism_flags_too_many_bike_days_excluding_races():
    sessions = [_mk_session(i, "bike", "Z2") for i in range(7)]
    warnings_out = evaluate_week_realism(sessions)
    assert any("bike training day" in w.lower() for w in warnings_out)


def test_realism_races_are_additive_not_counted_against_bike_ceiling():
    # 5 easy bike days + 2 race days = 7 bike sessions, but races don't
    # count -> only the 5 training days matter, which is under the ceiling.
    sessions = [_mk_session(i, "bike", "Z2") for i in range(5)] + [
        _mk_session(5, "bike", "Z5", "RACE — CX #1"),
        _mk_session(6, "bike", "Z5", "RACE — CX #2"),
    ]
    assert evaluate_week_realism(sessions) == []


def test_realism_flags_back_to_back_hard_days():
    sessions = [
        _mk_session(1, "bike", "Z4", "intervals"),
        _mk_session(2, "bike", "Z4", "intervals"),
    ]
    warnings_out = evaluate_week_realism(sessions)
    assert any("back-to-back" in w.lower() or "consecutive" in w.lower() for w in warnings_out)


def test_realism_flags_weekly_volume_jump_beyond_8pct():
    sessions = [_mk_session(0, "bike", "Z2"), _mk_session(3, "bike", "Z2")]  # 120 min
    warnings_out = evaluate_week_realism(sessions, prev_week_bike_volume_min=100.0)
    assert any("%" in w and ("+" in w or "over" in w) for w in warnings_out)


def test_realism_no_volume_warning_within_8pct():
    sessions = [_mk_session(0, "bike", "Z2")]  # 60 min
    assert evaluate_week_realism(sessions, prev_week_bike_volume_min=100.0) == []


# ===========================================================================
# Defect 4 -- strength after the interval session
# ===========================================================================


def test_strength_lands_after_the_hard_bike_day_no_pattern():
    athlete, event, macro = _bike_setup()
    ws = macro.blocks[0].start_date
    week = generate_week(athlete, macro, _iso_week(ws), ws, primary_sport="bike")
    bike = [s for s in week.sessions if s.sport == "bike"]
    strength = [s for s in week.sessions if s.sport == "strength"]
    hard_offsets = [
        (s.date - ws).days for s in bike if s.intensity.get("zone") not in (None, "Z2")
    ]
    assert hard_offsets, "expected a hard bike session"
    earliest_hard = min(hard_offsets)
    assert strength, "expected strength sessions"
    for s in strength:
        assert (s.date - ws).days >= earliest_hard
        assert (s.date - ws).days != earliest_hard - 1


def test_strength_after_hard_day_with_training_pattern():
    # hard day lands on the first pattern entry; strength must be on/after it
    athlete = make_athlete(
        sports=["bike"],
        training_days={
            "bike": ["tue", "wed", "thu", "sat"],
            "strength": ["mon", "wed", "fri"],
        },
    )
    event = make_event(
        target_metric="duration_min", distance_m=None, target_value=300.0, primary_sport="bike"
    )
    macro = scaffold_macro(
        athlete, event, START, current_weekly_volume_m=200, peak_weekly_volume_m=600
    )
    ws = macro.blocks[0].start_date
    week = generate_week(athlete, macro, _iso_week(ws), ws, primary_sport="bike")
    bike = [s for s in week.sessions if s.sport == "bike"]
    strength = [s for s in week.sessions if s.sport == "strength"]
    hard_offset = min(
        (s.date - ws).days for s in bike if s.intensity.get("zone") not in (None, "Z2")
    )
    assert len(strength) == STRENGTH_SESSIONS_PER_WEEK
    for s in strength:
        assert (s.date - ws).days >= hard_offset  # never a pre-hard "mon" pick


# ===========================================================================
# Defect 5 -- race-proximity / taper -> openers, race weeks -> RACE sessions
# ===========================================================================


def test_openers_template_is_registered():
    assert "openers" in BIKE_INTERVAL_TEMPLATES
    assert "openers" in BIKE_INTERVAL_TEMPLATE_META
    from swim_coach.plan import _BIKE_INTERVAL_TEMPLATE_BUILDERS

    assert "openers" in _BIKE_INTERVAL_TEMPLATE_BUILDERS


def test_select_bike_interval_template_still_cycles_four_in_rotation():
    seen = [_select_bike_interval_template(i) for i in range(8)]
    assert set(seen) == {"sustained_threshold", "over_unders", "short_short_vo2", "race_pace"}
    assert "openers" not in seen  # never in the blind rotation


def test_select_bike_interval_template_yields_openers_when_flagged():
    assert _select_bike_interval_template(1, use_openers=True) == "openers"
    assert _select_bike_interval_template(2, use_openers=True) == "openers"


def test_taper_block_bike_week_uses_openers_and_pulls_volume_down():
    athlete, event, macro = _bike_setup()
    taper = next(b for b in macro.blocks if b.name == "taper")
    ws = taper.start_date  # first taper week (not the collapsed final one)
    # baseline: same week with NO events passed -> rotation pick, no pull-down
    base = generate_week(athlete, macro, _iso_week(ws), ws, primary_sport="bike", event=event)
    withev = generate_week(
        athlete, macro, _iso_week(ws), ws, primary_sport="bike", event=event, events=[event]
    )
    hard = next(
        s for s in withev.sessions if s.sport == "bike" and s.intensity.get("zone") not in (None, "Z2")
    )
    assert "opener" in hard.purpose.lower()
    assert withev.target_volume_m < base.target_volume_m


def test_race_proximity_within_7_days_triggers_openers_outside_taper():
    athlete, event, macro = _bike_setup()
    # a B race 5 days after this (base-block) week ends
    ws = macro.blocks[0].start_date + timedelta(weeks=2)
    race = make_event(
        name="CX Series #1",
        event_date=ws + timedelta(days=6 + BIKE_OPENERS_PROXIMITY_DAYS - 2),
        target_metric="duration_min",
        distance_m=None,
        target_value=1.0,
        primary_sport="bike",
        priority="B",
    )
    week = generate_week(
        athlete, macro, _iso_week(ws), ws, primary_sport="bike", event=event, events=[event, race]
    )
    hard = next(
        s for s in week.sessions if s.sport == "bike" and s.intensity.get("zone") not in (None, "Z2")
    )
    assert "opener" in hard.purpose.lower()


def test_week_containing_two_back_to_back_races_gets_two_race_sessions():
    athlete, event, macro = _bike_setup()
    taper = next(b for b in macro.blocks if b.name == "taper")
    ws = taper.start_date
    sat = ws + timedelta(days=5)
    sun = ws + timedelta(days=6)
    r1 = make_event(
        name="CX #1", event_date=sat, target_metric="duration_min", distance_m=None,
        target_value=1.0, primary_sport="bike", priority="A",
    )
    r2 = make_event(
        name="CX #2", event_date=sun, target_metric="duration_min", distance_m=None,
        target_value=1.0, primary_sport="bike", priority="A",
    )
    week = generate_week(
        athlete, macro, _iso_week(ws), ws, primary_sport="bike", event=event, events=[event, r1, r2]
    )
    race_sessions = [s for s in week.sessions if s.purpose.strip().upper().startswith("RACE — ")]
    assert len(race_sessions) == 2
    assert {(s.date - ws).days for s in race_sessions} == {5, 6}
    # no VO2/threshold training ride the same week -- just a primer + races
    non_race_bike = [
        s for s in week.sessions
        if s.sport == "bike" and not s.purpose.strip().upper().startswith("RACE — ")
    ]
    for s in non_race_bike:
        assert "opener" in s.purpose.lower() or s.intensity.get("zone") in ("Z1", "Z2")


def test_race_week_bike_sessions_do_not_appear_without_events_param():
    # Existing callers that pass only `event=` (not `events=`) keep the old
    # final-taper behavior byte-for-byte.
    athlete, event, macro = _bike_setup()
    taper = next(b for b in macro.blocks if b.name == "taper")
    ws = taper.start_date + timedelta(weeks=3)  # collapsed final week
    week = generate_week(
        athlete, macro, _iso_week(ws), ws, primary_sport="bike", event=event
    )
    assert not any(s.purpose.strip().upper().startswith("RACE — ") for s in week.sessions)


# ===========================================================================
# Regression -- swim-primary output unchanged by the new optional params
# ===========================================================================


def test_swim_primary_week_is_byte_identical_with_new_params_unset():
    athlete = make_athlete()
    event = make_event()
    macro = scaffold_macro(
        athlete, event, START, current_weekly_volume_m=6000, peak_weekly_volume_m=20000
    )
    ws = macro.blocks[0].start_date
    a = generate_week(athlete, macro, _iso_week(ws), ws, event=event)
    b = generate_week(athlete, macro, _iso_week(ws), ws, event=event, events=[event])
    # normalize session ids (fresh uuid4 each call) then compare everything
    da = a.model_dump()
    db = b.model_dump()
    for d in (da, db):
        d["id"] = None
        for s in d["sessions"]:
            s["id"] = None
    assert da == db
    assert a.planning_warnings == []


def test_swim_primary_week_ignores_training_days_field():
    plain = make_athlete()
    with_td = make_athlete(training_days={"bike": ["mon", "wed", "fri"]})
    event = make_event()
    macro = scaffold_macro(
        plain, event, START, current_weekly_volume_m=6000, peak_weekly_volume_m=20000
    )
    ws = macro.blocks[0].start_date
    a = generate_week(plain, macro, _iso_week(ws), ws, event=event)
    b = generate_week(with_td, macro, _iso_week(ws), ws, event=event)
    da, db = a.model_dump(), b.model_dump()
    for d in (da, db):
        d["id"] = None
        for s in d["sessions"]:
            s["id"] = None
            s["athlete_id"] = None
    assert da == db
