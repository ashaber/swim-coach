"""The real coach path: can the tools actually WRITE a template week? Covers a
bike-target macro, a swim-target macro (the template must not be swallowed),
held volume, the 'weeks already on file' hint, and an actionable error for a
week outside the macro's range."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from fakes import seed_generated_week
from swim_coach.models import Event, Session, WeekPlan
from swim_coach.plan import scaffold_macro
from swim_coach.store import FileStore

from app.tools import build_tool_handlers

CLUB = "Heinous club ride"
TEMPLATE = {
    "mon": [{"kind": "skills", "label": "CX skills"}, {"kind": "yoga"}],
    "tue": [{"kind": "bike", "role": "hard"}, {"kind": "strength", "purpose": "Kettlebell EMOM 10 min"}],
    "wed": [{"kind": "bike", "role": "endurance", "label": CLUB}],
    "thu": [],
    "fri": [{"kind": "yoga"}],
    "sat": [{"kind": "bike", "role": "hard"}, {"kind": "strength"}],
    "sun": [{"kind": "bike", "role": "endurance", "label": CLUB}],
}


def _iso(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _setup(athletes_dir, *, sport: str):
    """Athlete 'renee' with an active macro toward a bike or swim event."""
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    handlers["update_athlete_profile"]({"sports": ["bike", "swim_pool"], "ftp_watts": 250.0})
    athlete = store.load_athlete("renee")
    start = date.today() - timedelta(days=date.today().weekday()) - timedelta(weeks=1)
    if sport == "bike":
        event = Event(
            id=uuid.uuid4(), athlete_id=athlete.id, name="CX", event_date=start + timedelta(weeks=24),
            target_metric="duration_min", distance_m=None, target_value=300.0, primary_sport="bike", priority="A",
        )
        macro = scaffold_macro(athlete, event, start, current_weekly_volume_m=200, peak_weekly_volume_m=600)
    else:
        event = Event(
            id=uuid.uuid4(), athlete_id=athlete.id, name="Halloween swim", event_date=start + timedelta(weeks=24),
            distance_m=20000, water_temp_c=18.0, wetsuit=False, priority="A",
        )
        macro = scaffold_macro(athlete, event, start, current_weekly_volume_m=8000, peak_weekly_volume_m=20000)
    store.save_events("renee", [event])
    store.save_macro("renee", macro)
    handlers["set_weekly_template"]({"template": TEMPLATE, "confirm": True})
    return store, handlers, macro


def _build_week_start(macro) -> date:
    return next(b for b in macro.blocks if b.name in ("build", "peak", "base")).start_date + timedelta(weeks=1)


def _bike_min(sessions) -> float:
    return sum(s["duration_min"] for s in sessions if s["sport"] == "bike" and "skills" not in s["purpose"].lower())


def _blank_week(store, iso: str) -> None:
    """A week on file with no sessions, so `merge_week_plan` has a current plan to diff its
    regenerated (template) proposal against."""
    athlete = store.load_athlete("renee")
    store.save_week("renee", WeekPlan(
        id=uuid.uuid4(), athlete_id=athlete.id, iso_week=iso, meso_block="build", focus="blank",
        target_volume_m=0, sessions=[], adaptation_rationale=None, draft=False,
    ))


def test_regeneration_under_a_bike_macro_proposes_the_whole_template_week(athletes_dir) -> None:
    store, handlers, macro = _setup(athletes_dir, sport="bike")
    ws = _build_week_start(macro)
    _blank_week(store, _iso(ws))

    result = handlers["merge_week_plan"]({"iso_week": _iso(ws)})

    assert "error" not in result, result
    assert len(result["proposed_plan"]) == 9
    assert store.load_week("renee", _iso(ws)).sessions == []  # diff mode persists nothing


def test_merge_draft_then_confirm_persists_the_template_week(athletes_dir) -> None:
    store, handlers, macro = _setup(athletes_dir, sport="bike")
    ws = _build_week_start(macro)
    _blank_week(store, _iso(ws))

    diff = handlers["merge_week_plan"]({"iso_week": _iso(ws)})
    picks = [{"date": d["date"], "sport": d["sport"]} for d in diff["diff"] if d["status"] == "new_in_proposed"]
    assert len(picks) == 9
    draft = handlers["merge_week_plan"]({"iso_week": _iso(ws), "accept_from_proposed": picks})
    assert draft["persisted"] is False and len(draft["merged_plan"]) == 9
    assert store.load_week("renee", _iso(ws)).sessions == []

    done = handlers["merge_week_plan"](
        {"iso_week": _iso(ws), "accept_from_proposed": picks, "confirm": True, "draft_id": draft["draft_id"]}
    )
    assert done["persisted"] is True
    saved = store.load_week("renee", _iso(ws))
    assert len(saved.sessions) == 9
    kb = next(s for s in saved.sessions if s.sport == "strength" and "Kettlebell" in s.purpose)
    assert kb.purpose.startswith("Kettlebell EMOM 10 min")


def test_swim_target_macro_still_gets_the_template_with_last_weeks_bike_minutes_held(athletes_dir) -> None:
    store, handlers, macro = _setup(athletes_dir, sport="swim")
    ws = _build_week_start(macro)
    prev = ws - timedelta(days=7)
    athlete = store.load_athlete("renee")
    store.save_week("renee", WeekPlan(
        id=uuid.uuid4(), athlete_id=athlete.id, iso_week=_iso(prev), meso_block="build", focus="x",
        target_volume_m=200, adaptation_rationale=None, draft=False,
        sessions=[Session(
            id=uuid.uuid4(), athlete_id=athlete.id, date=prev + timedelta(days=i), sport="bike", source="ai_coach",
            duration_min=100.0, distance_m=None, intensity={"zone": "Z2"}, purpose="endurance", status="planned",
        ) for i in (1, 3, 5)],
    ))

    _blank_week(store, _iso(ws))

    draft = handlers["merge_week_plan"]({"iso_week": _iso(ws)})

    assert "error" not in draft
    assert len(draft["proposed_plan"]) == 9
    assert not any(s["sport"].startswith("swim") for s in draft["proposed_plan"])
    assert 285 <= _bike_min(draft["proposed_plan"]) <= 315  # last week's 300 held


def test_swim_target_macro_with_no_history_uses_slot_defaults_and_still_writes_the_week(athletes_dir) -> None:
    store, handlers, macro = _setup(athletes_dir, sport="swim")
    ws = _build_week_start(macro)
    _blank_week(store, _iso(ws))
    result = handlers["merge_week_plan"]({"iso_week": _iso(ws)})
    assert "error" not in result, result
    assert len(result["proposed_plan"]) == 9


def test_set_weekly_template_reports_weeks_already_on_file_that_it_will_not_change(athletes_dir) -> None:
    store, handlers, macro = _setup(athletes_dir, sport="bike")
    ws = _build_week_start(macro)
    seed_generated_week(store, "renee", _iso(ws))

    result = handlers["set_weekly_template"]({"template": TEMPLATE})

    assert _iso(ws) in result["weeks_on_file_not_changed"]
    assert "author_week_plan" in result["rebuild_hint"]


def test_a_week_outside_the_macro_is_still_proposed_from_the_template(athletes_dir) -> None:
    store, handlers, macro = _setup(athletes_dir, sport="bike")
    far = macro.blocks[-1].end_date + timedelta(days=15)
    far = far - timedelta(days=far.weekday())
    _blank_week(store, _iso(far))

    result = handlers["merge_week_plan"]({"iso_week": _iso(far)})

    assert "error" not in result, result
    assert len(result["proposed_plan"]) == 9


def test_a_week_outside_the_macro_without_a_template_says_what_the_macro_covers(athletes_dir) -> None:
    store, handlers, macro = _setup(athletes_dir, sport="bike")
    handlers["set_weekly_template"]({"clear": True, "confirm": True})
    far = macro.blocks[-1].end_date + timedelta(weeks=10)
    far = far - timedelta(days=far.weekday())

    _blank_week(store, _iso(far))

    result = handlers["merge_week_plan"]({"iso_week": _iso(far)})

    err = result["error"]
    assert macro.blocks[0].start_date.isoformat() in err and macro.blocks[-1].end_date.isoformat() in err
    assert "author_macro_plan" in err


def test_get_plan_summary_exposes_the_macro_coverage_so_the_range_is_discoverable(athletes_dir) -> None:
    store, handlers, macro = _setup(athletes_dir, sport="bike")
    cov = handlers["get_plan_summary"]({})["macro_coverage"]
    assert cov["start"] == macro.blocks[0].start_date.isoformat()
    assert cov["end"] == macro.blocks[-1].end_date.isoformat()
    assert [b["name"] for b in cov["blocks"]] == [b.name for b in macro.blocks]
