"""`set_weekly_template` (IDEA 023 v3): the coach tool that saves the SHAPE of
the athlete's week. Preview by default; `confirm: true` persists. It replaces
the one-hard-day-only `set_schedule_preferences` for anything beyond a simple
standing ride (D3/D5)."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from swim_coach.store import FileStore

from app.context import PERSONA_AND_RULES, build_per_request_context
from app.tools import TOOLS_SCHEMA, build_tool_handlers

CLUB = "Heinous club ride"
WEEK = {
    "mon": [{"kind": "skills", "label": "CX skills"}, {"kind": "yoga"}],
    "tue": [{"kind": "bike", "role": "hard"}, {"kind": "strength"}],
    "wed": [{"kind": "bike", "role": "endurance", "label": CLUB}],
    "thu": [],
    "fri": [{"kind": "yoga"}],
    "sat": [{"kind": "bike", "role": "hard"}, {"kind": "strength"}],
    "sun": [{"kind": "bike", "role": "endurance", "label": CLUB}],
}


def _run(store, payload):
    return build_tool_handlers(store, slug="renee", expert_mode=False)["set_weekly_template"](payload)


def test_preview_persists_nothing_and_reads_the_week_back_as_a_grid(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    before = store.load_athlete("renee").model_dump(mode="json")

    result = _run(store, {"template": WEEK})

    assert result["persisted"] is False
    assert result["week"]["mon"] == ["CX skills (skills)", "yoga"]
    assert result["week"]["tue"] == ["bike: hard", "strength (after the intervals)"]
    assert result["week"]["wed"] == [f"bike: endurance - {CLUB}"]
    assert result["week"]["thu"] == []
    assert result["summary"] == {"hard_rides": 2, "bike_days": 4, "days_off": ["thu"]}
    assert "taper" in result["applies_to"].lower()
    assert store.load_athlete("renee").model_dump(mode="json") == before


def test_confirm_persists_and_reads_back_verified(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)

    result = _run(store, {"template": WEEK, "confirm": True})

    assert result["persisted"] is True and result["verified"] is True
    assert store.load_athlete("renee").weekly_template == WEEK


def test_two_hard_days_are_accepted(athletes_dir) -> None:
    # The whole point: the limit that broke set_schedule_preferences is gone.
    store = FileStore(base_dir=athletes_dir)
    result = _run(store, {"template": WEEK, "confirm": True})
    assert "error" not in result and result["summary"]["hard_rides"] == 2


def test_more_than_three_hard_rides_is_warned_never_refused(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    template = {d: [{"kind": "bike", "role": "hard"}] for d in ("mon", "tue", "thu", "fri")}

    result = _run(store, {"template": template, "confirm": True})

    assert result["persisted"] is True
    assert result["warnings"]  # realism guardrail speaks up
    assert store.load_athlete("renee").weekly_template is not None


def test_clear_removes_the_template(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    _run(store, {"template": WEEK, "confirm": True})

    result = _run(store, {"clear": True, "confirm": True})

    assert result["persisted"] is True
    assert store.load_athlete("renee").weekly_template is None


def test_clear_previews_without_confirm(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    _run(store, {"template": WEEK, "confirm": True})
    result = _run(store, {"clear": True})
    assert result["persisted"] is False
    assert store.load_athlete("renee").weekly_template == WEEK


@pytest.mark.parametrize(
    "payload, fragment",
    [
        ({}, "template"),
        ({"confirm": True}, "template"),
        ({"template": "yoga"}, "template"),
        ({"template": {"someday": [{"kind": "yoga"}]}}, "weekday"),
        ({"template": {"mon": [{"kind": "swimming"}]}}, "kind"),
        ({"template": {"mon": [{"kind": "bike"}]}}, "role"),
        ({"template": {"mon": [{"kind": "yoga", "role": "hard"}]}}, "role"),
        ({"template": {"mon": [{"kind": "yoga", "duration_min": 1}]}}, "duration"),
        ({"template": {"mon": [{"kind": "yoga", "label": "x" * 100}]}}, "label"),
        ({"template": WEEK, "clear": True}, "either"),
    ],
)
def test_invalid_input_is_a_clear_error_and_persists_nothing(athletes_dir, payload, fragment) -> None:
    store = FileStore(base_dir=athletes_dir)
    before = store.load_athlete("renee").model_dump(mode="json")

    result = _run(store, {**payload, "confirm": True})

    assert fragment in result["error"].lower()
    assert store.load_athlete("renee").model_dump(mode="json") == before


def test_saved_template_is_visible_to_the_coach_in_context(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    _run(store, {"template": WEEK, "confirm": True})
    assert CLUB in build_per_request_context(store, "renee", expert_mode=False)


def test_andrews_real_week_end_to_end_through_the_tool_into_the_generator(athletes_dir) -> None:
    from swim_coach.models import Event
    from swim_coach.plan import generate_week, scaffold_macro

    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    handlers["update_athlete_profile"]({"sports": ["bike"]})
    assert _run(store, {"template": WEEK, "confirm": True})["persisted"] is True

    athlete = store.load_athlete("renee")
    start = date(2026, 1, 5)
    event = Event(
        id=uuid.uuid4(), athlete_id=athlete.id, name="CX Race", event_date=start + timedelta(weeks=24),
        target_metric="duration_min", distance_m=None, target_value=300.0, primary_sport="bike", priority="A",
    )
    macro = scaffold_macro(athlete, event, start, current_weekly_volume_m=200, peak_weekly_volume_m=600)
    ws = next(b for b in macro.blocks if b.name in ("build", "peak")).start_date
    y, w, _ = ws.isocalendar()
    week = generate_week(athlete, macro, f"{y}-W{w:02d}", ws, primary_sport="bike", event=event, events=[event])

    assert len(week.sessions) == 9
    by_day = {}
    for s in week.sessions:
        by_day.setdefault((s.date - ws).days, []).append(s.sport)
    assert sorted(by_day) == [0, 1, 2, 4, 5, 6]  # Thursday off
    hard = [s for s in week.sessions if s.sport == "bike" and s.intensity.get("zone") not in (None, "Z2")]
    assert sorted((s.date - ws).days for s in hard) == [1, 5]  # Tuesday AND Saturday


def test_old_tool_points_at_the_new_one_when_two_hard_days_are_asked(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    result = build_tool_handlers(store, slug="renee", expert_mode=False)["set_schedule_preferences"](
        {"standing_rides": [{"day": "wed", "role": "hard"}], "hard_day": "fri", "confirm": True}
    )
    assert "set_weekly_template" in result["error"]


def test_tool_registered_and_persona_prefers_it_for_a_whole_week() -> None:
    schema = next(t for t in TOOLS_SCHEMA if t["name"] == "set_weekly_template")
    assert {"template", "clear", "confirm"} <= set(schema["input_schema"]["properties"])
    assert "set_weekly_template" in PERSONA_AND_RULES
    assert "set_weekly_template" in next(
        t for t in TOOLS_SCHEMA if t["name"] == "set_schedule_preferences"
    )["description"]
