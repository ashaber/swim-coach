"""update_race_checklist timeline ops: template timeline, per-race replace, reset."""

from __future__ import annotations

from swim_coach.store import FileStore

from app.tools import build_tool_handlers

TL = [
    {"id": "wake", "label": "Wake up", "offset_min": -315, "not_later_than": "07:00"},
    {"id": "lunch", "label": "Lunch", "offset_min": -180, "only_if_start_after": "12:00"},
    {"id": "start", "label": "Start", "offset_min": 0, "is_start": True},
]


def _h(athletes_dir):
    store = FileStore(base_dir=athletes_dir)
    return store, build_tool_handlers(store, slug="renee", expert_mode=False)


def test_template_timeline_then_race_edit_then_reset(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    r = h["update_race_checklist"]({"add_items": [{"section": "Kit", "text": "Helmet"}], "timeline": TL})
    assert r["updated"] is True and r["timeline_entries"] == 3
    assert h["get_race_checklist"]({})["template"]["timeline"][0]["not_later_than"] == "07:00"

    edited = [TL[0], {"id": "start", "label": "Start", "offset_min": 0, "is_start": True}]
    r = h["update_race_checklist"]({"date": "2026-10-17", "start_time": "15:15", "timeline": edited})
    assert r["updated"] is True and r["timeline_edited"] is True and len(r["timeline"]) == 2
    assert len(h["get_race_checklist"]({})["template"]["timeline"]) == 3  # template untouched
    assert store.load_athlete("renee").race_day_plans[0].timeline_edited is True

    r = h["update_race_checklist"]({"date": "2026-10-17", "reset_timeline": True})
    assert r["timeline_edited"] is False and [t["id"] for t in r["timeline"]] == ["wake", "lunch", "start"]


def test_bad_timelines_are_errors(athletes_dir) -> None:
    _, h = _h(athletes_dir)
    h["update_race_checklist"]({"add_items": [{"section": "Kit", "text": "Helmet"}]})
    no_start = [{"id": "a", "label": "A", "offset_min": -5}]
    assert "error" in h["update_race_checklist"]({"timeline": no_start})
    assert "error" in h["update_race_checklist"]({"date": "2026-10-17", "timeline": no_start})
    bad_rule = [{"id": "a", "label": "A", "offset_min": -5, "not_later_than": "late"}, TL[2]]
    assert "error" in h["update_race_checklist"]({"date": "2026-10-17", "timeline": bad_rule})
