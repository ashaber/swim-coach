"""Week drafts: an agreed plan is held server-side and written VERBATIM on
confirm, never regenerated. Drafts live under a hidden key so they never show up
as weeks."""

from __future__ import annotations

import uuid
from datetime import date

from swim_coach.models import Athlete, Session, WeekPlan
from swim_coach.store import FileStore


def _athlete(store: FileStore) -> Athlete:
    return store.load_athlete("renee")


def _week(athlete: Athlete, iso="2026-W39", purpose="a") -> WeekPlan:
    s = Session(id=uuid.uuid4(), athlete_id=athlete.id, date=date(2026, 9, 22), sport="bike", source="ai_coach",
                duration_min=60.0, distance_m=None, intensity={"zone": "Z2"}, purpose=purpose, status="planned")
    return WeekPlan(id=uuid.uuid4(), athlete_id=athlete.id, iso_week=iso, meso_block="build", focus="x",
                    target_volume_m=60, sessions=[s], adaptation_rationale=None, draft=True)


def test_draft_round_trips_by_id_and_as_the_latest(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    a = _athlete(store)
    d1, d2 = _week(a, purpose="first"), _week(a, purpose="second")
    store.save_week_draft("renee", d1)
    store.save_week_draft("renee", d2)

    assert store.load_week_draft("renee", "2026-W39").sessions[0].purpose == "second"  # latest
    assert store.load_week_draft("renee", "2026-W39", draft_id=str(d1.id)).sessions[0].purpose == "first"
    assert store.load_week_draft("renee", "2026-W39", draft_id=str(uuid.uuid4())) is None
    assert store.load_week_draft("renee", "2026-W40") is None


def test_drafts_are_never_listed_or_loaded_as_weeks(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    before = store.list_week_ids("renee")
    a = _athlete(store)
    store.save_week_draft("renee", _week(a, iso="2026-W45"))

    assert store.list_week_ids("renee") == before
    assert store.load_week("renee", "2026-W45") is None


def test_a_draft_does_not_disturb_the_live_week(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    a = _athlete(store)
    live = _week(a, purpose="live").model_copy(update={"draft": False})
    store.save_week("renee", live)
    store.save_week_draft("renee", _week(a, purpose="proposed"))

    assert store.load_week("renee", "2026-W39").sessions[0].purpose == "live"
