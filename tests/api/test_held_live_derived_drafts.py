"""A draft derived from the LIVE week (patch / merge / session adjustment) must get its own
week id, or `pending_drafts` treats it as already written and the coach never sees it."""

from __future__ import annotations

from datetime import date

from swim_coach.store import FileStore

from app.drafts import render_pending_drafts
from app.tools import build_tool_handlers

ISO = "2026-W28"
MERGE = {
    "iso_week": ISO,
    "proposed_sessions": [{"date": "2026-07-07", "sport": "strength", "duration_min": 55,
                           "purpose": "kettlebell-focused dryland strength"}],
    "accept_from_proposed": [{"date": "2026-07-07", "sport": "strength"}],
}
ADJ = {"iso_week": ISO, "date": "2026-07-06", "sport": "swim_pool", "direction": "reduce",
       "magnitude_pct": 20, "reason": "fatigued"}


def _setup(athletes_dir):
    store = FileStore(base_dir=athletes_dir)
    return store, build_tool_handlers(store, slug="renee", expert_mode=False)


def _patch_args(store):
    target = next(s for s in store.load_week("renee", ISO).sessions if s.date == date(2026, 7, 8))
    return {"iso_week": ISO, "session_overrides": [
        {"date": "2026-07-08", "sport": target.sport, "duration_min": 20}]}, target


def _check_lifecycle(store, draft, confirm_call) -> None:
    live_id = store.load_week("renee", ISO).id
    assert draft["draft_id"] != str(live_id)
    rendered = render_pending_drafts(store, "renee")
    assert rendered is not None and draft["draft_id"] in rendered
    # next turn: fresh handlers, only the draft_id from the prior request
    fresh = build_tool_handlers(store, slug="renee", expert_mode=False)
    done = confirm_call(fresh)
    assert done["persisted"] is True
    assert render_pending_drafts(store, "renee") is None


def test_held_patch_draft_is_visible_and_confirmable_next_turn(athletes_dir) -> None:
    store, h = _setup(athletes_dir)
    args, target = _patch_args(store)
    before_ids = {str(s.id) for s in store.load_week("renee", ISO).sessions}
    draft = h["patch_week_plan"](args)
    _check_lifecycle(store, draft, lambda f: f["patch_week_plan"](
        {"iso_week": ISO, "confirm": True, "draft_id": draft["draft_id"]}))
    written = store.load_week("renee", ISO)
    assert next(s for s in written.sessions if s.date == date(2026, 7, 8) and s.sport == target.sport).duration_min == 20
    assert {str(s.id) for s in written.sessions} == before_ids  # session ids are stable


def test_held_merge_draft_is_visible_and_confirmable_next_turn(athletes_dir) -> None:
    store, h = _setup(athletes_dir)
    draft = h["merge_week_plan"](MERGE)
    _check_lifecycle(store, draft, lambda f: f["merge_week_plan"](
        {"iso_week": ISO, "confirm": True, "draft_id": draft["draft_id"]}))


def test_held_session_adjustment_draft_is_visible_and_confirmable_next_turn(athletes_dir) -> None:
    store, h = _setup(athletes_dir)
    draft = h["propose_session_adjustment"](ADJ)
    _check_lifecycle(store, draft, lambda f: f["propose_session_adjustment"](
        {**ADJ, "confirm": True, "draft_id": draft["draft_id"]}))
