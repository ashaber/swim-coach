"""`set_schedule_preferences` (IDEA 023 phase 2): the coach tool that persists
standing schedule preferences on the Athlete so the week generator honors them
on every regeneration. Preview by default; `confirm: true` persists."""

from __future__ import annotations

import pytest
from swim_coach.plan import _bike_training_days
from swim_coach.store import FileStore

from app.context import build_per_request_context
from app.tools import TOOLS_SCHEMA, build_tool_handlers

CLUB = "Heinous club ride"
RIDES = [{"day": "wed", "label": CLUB}, {"day": "sun", "label": CLUB}]


def _run(store, payload):
    return build_tool_handlers(store, slug="renee", expert_mode=False)["set_schedule_preferences"](payload)


def test_preview_persists_nothing_and_reports_the_resolved_layout(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    before = store.load_athlete("renee").model_dump(mode="json")

    result = _run(store, {"standing_rides": RIDES, "strength_placement": "same_day_as_hard"})

    assert result["persisted"] is False
    assert result["bike_days"]["hard"] == {"day": "fri", "chosen_automatically": True}
    assert result["bike_days"]["endurance"] == [
        {"day": "wed", "label": CLUB},
        {"day": "sun", "label": CLUB},
    ]
    assert result["strength_placement"] == "same_day_as_hard"
    assert "taper" in result["applies_to"].lower() and "race" in result["applies_to"].lower()
    assert store.load_athlete("renee").model_dump(mode="json") == before


def test_confirm_persists_and_the_generator_input_reads_back(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)

    result = _run(store, {"standing_rides": RIDES, "strength_placement": "same_day_as_hard", "confirm": True})

    assert result["persisted"] is True and result["verified"] is True
    athlete = store.load_athlete("renee")
    assert athlete.strength_placement == "same_day_as_hard"
    assert athlete.training_days["bike"] == [
        {"day": "wed", "label": CLUB, "role": "endurance"},
        {"day": "sun", "label": CLUB, "role": "endurance"},
    ]
    offsets, labels = _bike_training_days(athlete)
    assert offsets == [4, 2, 6] and labels == {2: CLUB, 6: CLUB}


def test_explicit_hard_day_is_stored_and_reported_as_chosen(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)

    result = _run(store, {"standing_rides": RIDES, "hard_day": "tue", "confirm": True})

    assert result["bike_days"]["hard"] == {"day": "tue", "chosen_automatically": False}
    assert _bike_training_days(store.load_athlete("renee"))[0] == [1, 2, 6]


def test_other_training_day_patterns_are_preserved(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    athlete = store.load_athlete("renee")
    athlete.training_days = {"strength": ["thu"], "skills": ["mon"]}
    store.save_athlete(athlete)

    _run(store, {"standing_rides": RIDES, "confirm": True})

    days = store.load_athlete("renee").training_days
    assert days["strength"] == ["thu"] and days["skills"] == ["mon"] and "bike" in days


def test_strength_placement_alone_leaves_the_bike_pattern_alone(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    _run(store, {"standing_rides": RIDES, "confirm": True})

    _run(store, {"strength_placement": "same_day_as_hard", "confirm": True})

    athlete = store.load_athlete("renee")
    assert athlete.strength_placement == "same_day_as_hard"
    assert len(athlete.training_days["bike"]) == 2


def test_empty_standing_rides_clears_the_bike_pattern(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    athlete = store.load_athlete("renee")
    athlete.training_days = {"bike": ["tue", "wed"], "strength": ["thu"]}
    store.save_athlete(athlete)

    result = _run(store, {"standing_rides": [], "confirm": True})

    assert result["persisted"] is True
    days = store.load_athlete("renee").training_days
    assert "bike" not in days and days["strength"] == ["thu"]


def test_null_strength_placement_clears_it(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    _run(store, {"strength_placement": "same_day_as_hard", "confirm": True})
    _run(store, {"strength_placement": None, "confirm": True})
    assert store.load_athlete("renee").strength_placement is None


@pytest.mark.parametrize(
    "payload, fragment",
    [
        ({}, "at least one"),
        ({"confirm": True}, "at least one"),
        ({"standing_rides": "wed"}, "list"),
        ({"standing_rides": [{"day": "someday"}]}, "day"),
        ({"standing_rides": [{"label": "x"}]}, "day"),
        ({"standing_rides": [{"day": "wed"}, {"day": "wednesday"}]}, "duplicate"),
        ({"standing_rides": [{"day": "wed", "role": "recovery"}]}, "role"),
        ({"standing_rides": [{"day": "wed", "label": "x" * 200}]}, "label"),
        ({"standing_rides": RIDES, "hard_day": "wed"}, "hard_day"),
        ({"standing_rides": [{"day": "wed", "role": "hard"}], "hard_day": "fri"}, "one hard"),
        ({"hard_day": "noday"}, "hard_day"),
        ({"strength_placement": "whenever"}, "strength_placement"),
    ],
)
def test_invalid_input_is_a_clear_error_and_persists_nothing(athletes_dir, payload, fragment) -> None:
    store = FileStore(base_dir=athletes_dir)
    before = store.load_athlete("renee").model_dump(mode="json")

    result = _run(store, {**payload, "confirm": True} if "confirm" not in payload else payload)

    assert fragment in result["error"].lower()
    assert store.load_athlete("renee").model_dump(mode="json") == before


def test_saved_preferences_are_visible_to_the_coach_in_context(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    _run(store, {"standing_rides": RIDES, "strength_placement": "same_day_as_hard", "confirm": True})

    text = build_per_request_context(store, "renee", expert_mode=False)

    assert CLUB in text and "same_day_as_hard" in text


def test_tool_is_registered_with_a_schema_and_a_handler(athletes_dir) -> None:
    schema = next(t for t in TOOLS_SCHEMA if t["name"] == "set_schedule_preferences")
    props = schema["input_schema"]["properties"]
    assert {"standing_rides", "hard_day", "strength_placement", "confirm"} <= set(props)
    assert "set_schedule_preferences" in build_tool_handlers(FileStore(base_dir=athletes_dir), slug="renee", expert_mode=False)


def test_persona_tells_the_coach_when_to_use_it_and_that_existing_weeks_are_unchanged() -> None:
    from app.context import PERSONA_AND_RULES

    assert "set_schedule_preferences" in PERSONA_AND_RULES
    assert "ALREADY on file are not changed" in PERSONA_AND_RULES


def test_saved_preferences_change_the_week_the_generator_builds_end_to_end(athletes_dir) -> None:
    import uuid
    from datetime import date, timedelta

    from swim_coach.models import Event
    from swim_coach.plan import generate_week, scaffold_macro

    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    handlers["update_athlete_profile"]({"sports": ["bike"]})
    handlers["set_schedule_preferences"](
        {"standing_rides": RIDES, "strength_placement": "same_day_as_hard", "confirm": True}
    )

    athlete = store.load_athlete("renee")  # what the real tools/generator load
    start = date(2026, 1, 5)
    event = Event(
        id=uuid.uuid4(), athlete_id=athlete.id, name="CX Race", event_date=start + timedelta(weeks=24),
        target_metric="duration_min", distance_m=None, target_value=300.0, primary_sport="bike", priority="A",
    )
    macro = scaffold_macro(athlete, event, start, current_weekly_volume_m=200, peak_weekly_volume_m=600)
    block = next(b for b in macro.blocks if b.name in ("build", "peak"))
    ws = block.start_date
    year, week, _ = ws.isocalendar()
    plan = generate_week(athlete, macro, f"{year}-W{week:02d}", ws, primary_sport="bike", event=event, events=[event])

    bike = {(s.date - ws).days: s for s in plan.sessions if s.sport == "bike"}
    assert CLUB in bike[2].purpose and CLUB in bike[6].purpose
    hard = next(s for s in bike.values() if s.intensity.get("zone") not in (None, "Z2"))
    assert (hard.date - ws).days == 4  # Friday
    strength_days = [(s.date - ws).days for s in plan.sessions if s.sport == "strength"]
    assert 4 in strength_days  # same day as the intervals
