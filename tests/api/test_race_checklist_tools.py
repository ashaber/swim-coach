"""Coach tools for the race-week checklist and the race-day checklist."""

from __future__ import annotations

from swim_coach.store import FileStore

from app.tools import build_tool_handlers

TEMPLATE_ADD = [
    {"section": "Kit", "text": "Helmet"},
    {"section": "Kit", "text": "Shoe covers", "tags": ["Wet"]},
]


def _h(athletes_dir):
    store = FileStore(base_dir=athletes_dir)
    return store, build_tool_handlers(store, slug="renee", expert_mode=False)


def test_race_week_checklist_draft_then_confirm_keeps_ticks(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    iso = store.list_week_ids("renee")[0]
    items = [
        {"date": "2026-10-14", "category": "bike", "label": "Clean bike"},
        {"date": "2026-10-15", "category": "gear", "label": "Pack kit", "note": "mud tires"},
    ]
    draft = h["set_race_week_checklist"]({"iso_week": iso, "items": items})
    assert draft["persisted"] is False
    assert store.load_week("renee", iso).race_week_checklist == []
    assert h["set_race_week_checklist"]({"iso_week": iso, "items": items, "confirm": True})["persisted"] is True
    week = store.load_week("renee", iso)
    assert [i.label for i in week.race_week_checklist] == ["Clean bike", "Pack kit"]
    week.race_week_checklist[0].done = True
    store.save_week("renee", week)
    h["set_race_week_checklist"]({"iso_week": iso, "items": items + [
        {"date": "2026-10-16", "category": "sleep", "label": "Early night"}], "confirm": True})
    after = store.load_week("renee", iso).race_week_checklist
    assert [i.done for i in after] == [True, False, False]


def test_race_week_checklist_rejects_bad_input(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    iso = store.list_week_ids("renee")[0]
    assert "error" in h["set_race_week_checklist"]({"iso_week": iso, "items": [{"date": "x", "category": "bike", "label": "a"}]})
    assert "error" in h["set_race_week_checklist"]({"iso_week": iso, "items": [{"date": "2026-10-14", "category": "zzz", "label": "a"}]})
    assert "error" in h["set_race_week_checklist"]({"iso_week": "2099-W01", "items": []})


def test_update_template_then_race_plan_and_read_back(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    assert h["get_race_checklist"]({})["template"] is None
    r = h["update_race_checklist"]({"add_items": TEMPLATE_ADD})
    assert r["updated"] is True and r["items"] == 2
    tmpl = h["get_race_checklist"]({})["template"]
    assert tmpl["sections"][0]["items"][1]["tags"] == ["wet"]

    r = h["update_race_checklist"]({
        "date": "2026-10-17", "add_items": [{"section": "Bike prep", "text": "Mount mud tires", "tags": ["mud"]}],
        "remove_items": ["helmet"], "active_tags": ["Mud"], "start_time": "09:30",
    })
    assert r["updated"] is True and r["active_tags"] == ["mud"] and r["start_time"] == "09:30"
    plan = h["get_race_checklist"]({"date": "2026-10-17"})
    titles = [s["title"] for s in plan["sections"]]
    assert titles == ["Kit", "Bike prep"]
    assert [i["text"] for i in plan["sections"][0]["items"]] == ["Shoe covers"]
    # the template itself is untouched by the per-race edit
    assert len(h["get_race_checklist"]({})["template"]["sections"][0]["items"]) == 2
    assert store.load_athlete("renee").race_day_plans[0].start_time == "09:30"


def test_update_race_plan_needs_template_and_valid_input(athletes_dir) -> None:
    _, h = _h(athletes_dir)
    assert "error" in h["update_race_checklist"]({"date": "2026-10-17", "active_tags": ["mud"]})
    h["update_race_checklist"]({"add_items": TEMPLATE_ADD})
    assert "error" in h["update_race_checklist"]({"date": "nope"})
    assert "error" in h["update_race_checklist"]({"date": "2026-10-17", "start_time": "9am"})
    assert "error" in h["get_race_checklist"]({"date": "2030-01-01"})
