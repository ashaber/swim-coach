"""Consumed and stale drafts are garbage once they're no longer offered to the
coach -- they were never deleted, only hidden, so they piled up forever
(harmless for behavior, but real production garbage a hand-cleanup just fixed).
This covers the GC wired into the confirm paths that consume a draft, and that
an unrelated write (reschedule_session) never touches a fresh pending draft."""

from __future__ import annotations

from datetime import date, timedelta

from swim_coach.store import FileStore

from app.drafts import MACRO_CARRIER_WEEK
from app.tools import build_tool_handlers

GREECE = "UltraSwim 33.3 Greece (Skopelos) — single-day 33.3 km continuous"


def _h(athletes_dir):
    store = FileStore(base_dir=athletes_dir)
    return store, build_tool_handlers(store, slug="renee", expert_mode=False)


def test_confirming_a_week_draft_leaves_zero_draft_rows_for_that_week(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    draft = h["patch_week_plan"]({"iso_week": "2026-W28", "session_overrides": [
        {"date": "2026-07-06", "sport": "swim_pool", "purpose": "agreed: easy spin"},
    ]})
    assert draft["persisted"] is False
    assert store.load_week_draft("renee", "2026-W28") is not None  # held, pre-confirm

    done = h["patch_week_plan"]({"iso_week": "2026-W28", "confirm": True, "draft_id": draft["draft_id"]})

    assert done["persisted"] is True and done["written_from_draft"] is True
    assert store.load_week_draft("renee", "2026-W28") is None
    assert store.load_week_draft("renee", "2026-W28", draft_id=draft["draft_id"]) is None
    assert all(d.iso_week != "2026-W28" for d in store.list_week_drafts("renee"))


def test_confirming_a_macro_draft_leaves_zero_draft_rows_for_the_macro_carrier(athletes_dir) -> None:
    (athletes_dir / "renee" / "plan" / "macro.yaml").unlink()
    store, h = _h(athletes_dir)
    start = date(2026, 7, 6)
    weeks = [
        {"week_start": (start + timedelta(weeks=i)).isoformat(), "phase": "Base", "focus": "aerobic base",
         "hours": 8.0 + i, "load_tss": 400.0 + i * 20, "ctl_target": 40.0 + i * 2,
         "key_sessions": [], "recovery": False, "notes": None}
        for i in range(3)
    ]
    draft = h["author_macro_plan"]({"event_names": [GREECE], "weeks": weeks, "architecture": "Base toward Greece."})
    assert draft["persisted"] is False
    assert store.load_week_draft("renee", MACRO_CARRIER_WEEK) is not None  # held, pre-confirm

    decisions = [
        {"id": f["id"], "decision": "keep_as_is", "reason": "ok",
         **({"athlete_words": "fine"} if f["severity"] == "high" else {})}
        for f in draft["report"]["findings"]
    ]
    done = h["author_macro_plan"]({"confirm": True, "draft_id": draft["draft_id"], "decisions": decisions})

    assert done["persisted"] is True and done["written_from_draft"] is True
    assert store.load_week_draft("renee", MACRO_CARRIER_WEEK) is None
    assert store.load_week_draft("renee", MACRO_CARRIER_WEEK, draft_id=draft["draft_id"]) is None
    assert all(d.iso_week != MACRO_CARRIER_WEEK for d in store.list_week_drafts("renee"))


def test_a_fresh_pending_draft_survives_an_unrelated_reschedule(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    draft = h["patch_week_plan"]({"iso_week": "2026-W28", "session_overrides": [
        {"date": "2026-07-06", "sport": "swim_pool", "purpose": "agreed: easy spin"},
    ]})
    assert draft["persisted"] is False and draft["draft_id"]

    # An unrelated direct-persist write on the SAME week -- must not touch the pending draft.
    result = h["reschedule_session"]({
        "iso_week": "2026-W28", "current_date": "2026-07-07", "sport": "strength", "new_date": "2026-07-10",
    })
    assert result.get("rescheduled") is True

    still_held = store.load_week_draft("renee", "2026-W28")
    assert still_held is not None and str(still_held.id) == draft["draft_id"]
    assert any(d.iso_week == "2026-W28" for d in store.list_week_drafts("renee"))
