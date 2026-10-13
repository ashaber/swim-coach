"""Race-day checklist models + helpers (engine/swim_coach/race_day.py) and RaceWeekChecklistItem back-compat."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from pydantic import ValidationError

from swim_coach.models import (
    Athlete,
    ChecklistItem,
    ChecklistSection,
    RaceChecklistTemplate,
    TimelineEntry,
    WeekPlan,
)
from swim_coach.race_day import (
    find_plan,
    new_plan_from_template,
    set_checked,
    timeline_clock,
    visible_items,
)

TEMPLATE = RaceChecklistTemplate(
    sections=[
        ChecklistSection(id="kit", title="Kit", items=[
            ChecklistItem(id="helmet", text="Helmet", default_checked=True),
            ChecklistItem(id="covers", text="Shoe covers", tags=["cold", "wet"]),
            ChecklistItem(id="arm", text="Arm warmers", tags=["cool"]),
        ]),
    ],
    timeline=[
        TimelineEntry(id="dinner", label="Dinner", day="eve", at="19:00"),
        TimelineEntry(id="wake", label="Wake up", offset_min=-315),
        TimelineEntry(id="start", label="Start", offset_min=0, is_start=True),
        TimelineEntry(id="cool", label="Cooldown", offset_min=60),
    ],
)


def _plan(start="09:00"):
    return new_plan_from_template(TEMPLATE, race_date=date(2026, 10, 17), name="Day 1", session_id="s1", start_time=start)


def _week(items):
    return WeekPlan(
        id=uuid.uuid4(), athlete_id=uuid.uuid4(), iso_week="2026-W42", meso_block="race", focus="race",
        target_volume_m=0, race_week_checklist=items,
    )


def test_week_plan_backfills_stable_unique_item_ids_from_old_rows() -> None:
    rows = [
        {"date": "2026-10-12", "category": "carb_load", "label": "Carb load"},
        {"date": "2026-10-12", "category": "carb_load", "label": "Carb load"},
        {"date": "2026-10-13", "category": "bike", "label": "Clean bike", "done": True, "note": "n"},
    ]
    a, b = _week(rows), _week(rows)
    ids = [i.id for i in a.race_week_checklist]
    assert all(ids) and len(set(ids)) == 3
    assert ids == [i.id for i in b.race_week_checklist]
    assert a.race_week_checklist[2].done is True and a.race_week_checklist[0].done is False


def test_unknown_category_rejected() -> None:
    with pytest.raises(ValidationError):
        _week([{"date": "2026-10-12", "category": "nope", "label": "x"}])


def test_timeline_entry_validation() -> None:
    with pytest.raises(ValidationError):
        TimelineEntry(id="a", label="x", day="eve")
    with pytest.raises(ValidationError):
        TimelineEntry(id="a", label="x", day="race")
    with pytest.raises(ValidationError):
        TimelineEntry(id="a", label="x", day="eve", at="25:00")


def test_instance_copies_template_and_prechecks_defaults() -> None:
    plan = _plan()
    assert plan.checked == ["helmet"]
    plan.sections[0].items[0].text = "changed"
    assert TEMPLATE.sections[0].items[0].text == "Helmet"


def test_tag_filtering() -> None:
    plan = _plan()
    assert [i.id for i in visible_items(plan)] == ["helmet"]
    plan.active_tags = ["wet"]
    assert [i.id for i in visible_items(plan)] == ["helmet", "covers"]
    plan.active_tags = ["cold", "cool"]
    assert [i.id for i in visible_items(plan)] == ["helmet", "covers", "arm"]


def test_timeline_clock_times_and_start_shift() -> None:
    clock = timeline_clock(_plan("09:00"))
    assert [(c["id"], c["time"]) for c in clock] == [
        ("dinner", "19:00"), ("wake", "03:45"), ("start", "09:00"), ("cool", "10:00"),
    ]
    shifted = timeline_clock(_plan("10:30"))
    assert [c["time"] for c in shifted if c["day"] == "race"] == ["05:15", "10:30", "11:30"]
    assert [c["time"] for c in shifted if c["day"] == "eve"] == ["19:00"]


def test_timeline_crossing_midnight_and_no_start_time() -> None:
    early = timeline_clock(_plan("03:00"))
    wake = next(c for c in early if c["id"] == "wake")
    assert wake["time"] == "21:45" and wake["day_shift"] == -1
    none = timeline_clock(_plan(None))
    assert next(c for c in none if c["id"] == "wake")["time"] is None
    assert next(c for c in none if c["id"] == "dinner")["time"] == "19:00"


def test_set_checked_is_idempotent_and_ignores_unknown() -> None:
    plan = _plan()
    set_checked(plan, {"covers": True, "ghost": True})
    set_checked(plan, {"covers": True})
    assert plan.checked == ["helmet", "covers"]
    set_checked(plan, {"helmet": False})
    set_checked(plan, {"helmet": False})
    assert plan.checked == ["covers"]


def test_find_plan_prefers_session_id_then_date() -> None:
    athlete = Athlete(id=uuid.uuid4(), slug="a", name="A", race_day_plans=[_plan()])
    assert find_plan(athlete, session_id="s1", race_date=date(2030, 1, 1)) is athlete.race_day_plans[0]
    assert find_plan(athlete, session_id="other", race_date=date(2026, 10, 17)) is athlete.race_day_plans[0]
    assert find_plan(athlete, session_id="other", race_date=date(2026, 10, 18)) is None
