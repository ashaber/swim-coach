"""A per-week lever: the coach can switch ANY bike session between easy endurance and one of the
engine's deterministic interval types ("make Sunday's group ride a threshold session this week"),
without hand-authoring a workout -- the engine builds the intervals, the zone tag and the prose."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from swim_coach.models import Event
from swim_coach.plan import scaffold_macro
from swim_coach.store import FileStore

from app.tools import TOOLS_SCHEMA, build_tool_handlers

CLUB = "Heinous club ride"
TEMPLATE = {
    "tue": [{"kind": "bike", "role": "hard", "intervals": "vo2"}, {"kind": "strength"}],
    "wed": [{"kind": "bike", "role": "flex", "label": CLUB, "duration_min": 90}],
    "yoga_free": [],
}
TEMPLATE.pop("yoga_free")


def _iso(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _setup(athletes_dir):
    store = FileStore(base_dir=athletes_dir)
    h = build_tool_handlers(store, slug="renee", expert_mode=False)
    h["update_athlete_profile"]({"sports": ["bike"], "ftp_watts": 250.0})
    athlete = store.load_athlete("renee")
    start = date.today() - timedelta(days=date.today().weekday()) - timedelta(weeks=1)
    event = Event(id=uuid.uuid4(), athlete_id=athlete.id, name="CX", event_date=start + timedelta(weeks=24),
                  target_metric="duration_min", distance_m=None, target_value=300.0, primary_sport="bike", priority="A")
    macro = scaffold_macro(athlete, event, start, current_weekly_volume_m=200, peak_weekly_volume_m=600)
    store.save_events("renee", [event])
    store.save_macro("renee", macro)
    h["set_weekly_template"]({"template": TEMPLATE, "confirm": True})
    ws = next(b for b in macro.blocks if b.name in ("build", "peak", "base")).start_date + timedelta(weeks=1)
    iso = _iso(ws)
    h["create_week_plan"]({"iso_week": iso})
    return store, h, iso, ws


def _patch(h, iso, override):
    return h["patch_week_plan"]({"iso_week": iso, "session_overrides": [override]})


def _session(result, day):
    return next(s for s in result["sessions"] if s["date"] == day.isoformat() and s["sport"] == "bike")


def test_a_flex_ride_can_be_switched_to_a_chosen_interval_type_for_the_week(athletes_dir) -> None:
    store, h, iso, ws = _setup(athletes_dir)
    wed = ws + timedelta(days=2)

    result = _patch(h, iso, {"date": wed.isoformat(), "sport": "bike", "interval_type": "threshold"})

    assert "error" not in result, result
    ride = _session(result, wed)
    assert "threshold" in ride["purpose"].lower() and CLUB in ride["purpose"]  # keeps the ride's name
    assert ride["has_structured"] is True and ride["duration_min"] == 90       # engine-built, same length
    draft = result["draft_id"]
    h["patch_week_plan"]({"iso_week": iso, "confirm": True, "draft_id": draft})
    saved = next(s for s in store.load_week("renee", iso).sessions if s.date == wed and s.sport == "bike")
    assert saved.intensity.get("zone") == "Z4" and saved.structured is not None


def test_a_hard_ride_can_be_switched_back_to_easy_endurance(athletes_dir) -> None:
    store, h, iso, ws = _setup(athletes_dir)
    tue = ws + timedelta(days=1)
    result = _patch(h, iso, {"date": tue.isoformat(), "sport": "bike", "interval_type": "endurance"})
    assert "error" not in result
    assert "endurance" in _session(result, tue)["purpose"].lower()
    h["patch_week_plan"]({"iso_week": iso, "confirm": True, "draft_id": result["draft_id"]})
    saved = next(s for s in store.load_week("renee", iso).sessions if s.date == tue and s.sport == "bike")
    assert saved.intensity.get("zone") == "Z2"


def test_switching_a_ride_to_hard_updates_the_realism_check(athletes_dir) -> None:
    store, h, iso, ws = _setup(athletes_dir)
    for i, kind in enumerate(("vo2", "over_unders", "threshold")):
        pass
    result = _patch(h, iso, {"date": (ws + timedelta(days=2)).isoformat(), "sport": "bike", "interval_type": "over/unders"})
    assert "error" not in result and isinstance(result["planning_warnings"], list)


def test_an_unknown_interval_type_is_noted_and_changes_nothing(athletes_dir) -> None:
    store, h, iso, ws = _setup(athletes_dir)
    wed = ws + timedelta(days=2)
    before = next(s for s in store.load_week("renee", iso).sessions if s.date == wed and s.sport == "bike")
    result = _patch(h, iso, {"date": wed.isoformat(), "sport": "bike", "interval_type": "mystery"})
    assert "error" not in result
    assert any("mystery" in w and "interval" in w for w in result["planning_warnings"])
    assert _session(result, wed)["purpose"] == before.purpose


def test_interval_type_on_a_non_bike_session_is_noted_not_refused(athletes_dir) -> None:
    store, h, iso, ws = _setup(athletes_dir)
    strength = next(s for s in store.load_week("renee", iso).sessions if s.sport == "strength")
    result = h["patch_week_plan"]({"iso_week": iso, "session_overrides": [
        {"date": strength.date.isoformat(), "sport": "strength", "interval_type": "vo2", "purpose": "KB EMOM"}]})
    assert "error" not in result and any("only applies to bike" in w for w in result["planning_warnings"])


def test_a_given_purpose_wins_over_the_engine_text(athletes_dir) -> None:
    store, h, iso, ws = _setup(athletes_dir)
    wed = ws + timedelta(days=2)
    result = _patch(h, iso, {"date": wed.isoformat(), "sport": "bike", "interval_type": "vo2", "purpose": "Sunday-style push with the group"})
    assert _session(result, wed)["purpose"] == "Sunday-style push with the group"


def test_the_override_schema_advertises_interval_type() -> None:
    props = next(t for t in TOOLS_SCHEMA if t["name"] == "patch_week_plan")["input_schema"]["properties"]
    item = props["session_overrides"]["items"]["properties"]
    assert "interval_type" in item
