"""Draft storage is the one path not verified against a real Postgres. A storage error there
must NEVER become a tool failure that blocks the coach: it degrades to the old behaviour
(write in one step, flagged), and only an explicitly named draft_id that cannot be read
writes nothing (writing some other plan would be the corruption)."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from swim_coach.models import Event
from swim_coach.plan import scaffold_macro
from swim_coach.store import FileStore

from app.context import build_per_request_context
from app.tools import build_tool_handlers


class BrokenDraftStore(FileStore):
    """A FileStore whose draft storage raises, like a Postgres query error would."""

    def save_week_draft(self, slug, week):
        raise RuntimeError("relation week_plans: simulated storage error")

    def load_week_draft(self, slug, iso_week, draft_id=None):
        raise RuntimeError("simulated storage error")

    def list_week_drafts(self, slug):
        raise RuntimeError("simulated storage error")


def _iso(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _setup(athletes_dir):
    store = BrokenDraftStore(base_dir=athletes_dir)
    h = build_tool_handlers(store, slug="renee", expert_mode=False)
    h["update_athlete_profile"]({"sports": ["bike"], "ftp_watts": 250.0})
    athlete = store.load_athlete("renee")
    start = date.today() - timedelta(days=date.today().weekday()) - timedelta(weeks=1)
    event = Event(id=uuid.uuid4(), athlete_id=athlete.id, name="CX", event_date=start + timedelta(weeks=24),
                  target_metric="duration_min", distance_m=None, target_value=300.0, primary_sport="bike", priority="A")
    macro = scaffold_macro(athlete, event, start, current_weekly_volume_m=200, peak_weekly_volume_m=600)
    store.save_events("renee", [event])
    store.save_macro("renee", macro)
    h["set_weekly_template"]({"template": {"tue": [{"kind": "bike", "role": "hard"}]}, "confirm": True})
    ws = next(b for b in macro.blocks if b.name in ("build", "peak", "base")).start_date + timedelta(weeks=1)
    return store, h, _iso(ws)


def test_a_draft_that_cannot_be_stored_does_not_break_drafting(athletes_dir) -> None:
    store, h, iso = _setup(athletes_dir)
    draft = h["replace_week_plan"]({"iso_week": iso})
    assert "error" not in draft and draft["persisted"] is False and draft["sessions"]
    assert "draft_id" not in draft  # nothing could be held, and the response does not pretend otherwise


def test_confirm_still_writes_when_draft_storage_is_down_and_says_it_was_one_step(athletes_dir) -> None:
    store, h, iso = _setup(athletes_dir)
    done = h["replace_week_plan"]({"iso_week": iso, "confirm": True})
    assert done["persisted"] is True and not done.get("written_from_draft")
    assert any("ONE step" in w for w in done["planning_warnings"])


def test_a_named_draft_that_cannot_be_read_writes_nothing_and_says_so(athletes_dir) -> None:
    store, h, iso = _setup(athletes_dir)
    done = h["replace_week_plan"]({"iso_week": iso, "confirm": True, "draft_id": str(uuid.uuid4())})
    assert done["persisted"] is False and "draft" in done["error"].lower()
    assert store.load_week("renee", iso) is None


def test_the_held_drafts_context_section_survives_a_storage_error(athletes_dir) -> None:
    store, h, iso = _setup(athletes_dir)
    assert "Drafts waiting" not in build_per_request_context(store, "renee", expert_mode=False)


def test_the_other_confirming_tools_degrade_the_same_way(athletes_dir) -> None:
    store, h, iso = _setup(athletes_dir)
    adj = {"iso_week": "2026-W28", "date": "2026-07-06", "sport": "swim_pool", "direction": "reduce",
           "magnitude_pct": 20, "reason": "tired"}
    draft = h["propose_session_adjustment"](adj)
    assert "error" not in draft and draft["persisted"] is False
    done = h["propose_session_adjustment"]({**adj, "confirm": True})
    assert "error" not in done and done["persisted"] is True
