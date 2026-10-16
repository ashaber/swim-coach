"""scripts/backfill_yoga_sport.py against a FileStore: dry run writes nothing, --apply re-sports and re-links."""

from __future__ import annotations

import importlib.util
import uuid
from datetime import date
from pathlib import Path

from swim_coach.models import Session, WeekPlan, Workout

_SPEC = importlib.util.spec_from_file_location(
    "backfill_yoga_sport", Path(__file__).resolve().parents[2] / "scripts" / "backfill_yoga_sport.py"
)
script = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(script)


def _session(athlete_id, day: date, sport: str, purpose: str) -> Session:
    return Session(
        id=uuid.uuid4(), athlete_id=athlete_id, date=day, sport=sport, source="ai_coach",
        duration_min=30.0, distance_m=0, intensity={"zone": "Z1"}, purpose=purpose,
    )


def _workout(athlete_id, day: date, sport: str, detail: str, **kw) -> Workout:
    return Workout(
        id=uuid.uuid4(), athlete_id=athlete_id, date=day, sport=sport, source="fit",
        distance_m=0, duration_min=30.0, sport_detail=detail, **kw,
    )


def _seed(athlete_tree):
    store, slug, aid = athlete_tree["store"], athlete_tree["slug"], athlete_tree["athlete"].id
    yoga_plan = _session(aid, date(2026, 10, 5), "recovery", "Yoga")
    strength_plan = _session(aid, date(2026, 10, 6), "strength", "Cycling strength")
    store.save_week(
        slug,
        WeekPlan(id=uuid.uuid4(), athlete_id=aid, iso_week="2026-W41", meso_block="base", focus="x",
                 target_volume_m=0, sessions=[yoga_plan, strength_plan]),
    )
    yoga = _workout(aid, date(2026, 10, 5), "strength", "training/yoga", planned_session_id=strength_plan.id)
    lift = _workout(aid, date(2026, 10, 6), "strength", "training/strength_training")
    old_mtb = _workout(aid, date(2026, 6, 1), "cross_train", "cycling/mountain")
    for w in (yoga, lift, old_mtb):
        store.save_workout(slug, w)
    return yoga, lift, old_mtb, yoga_plan


def test_dry_run_reports_but_writes_nothing(athlete_tree):
    yoga, _, old_mtb, _ = _seed(athlete_tree)
    store, slug = athlete_tree["store"], athlete_tree["slug"]
    out = script.backfill(store, [slug], apply=False)
    assert [r["id"] for r in out["changed"]] == [str(yoga.id)]
    assert [r["id"] for r in out["legacy_cross_train"]] == [str(old_mtb.id)]
    assert {w.id: w.sport for w in store.list_workouts(slug)}[yoga.id] == "strength"


def test_apply_resports_relinks_and_is_idempotent(athlete_tree):
    yoga, lift, old_mtb, yoga_plan = _seed(athlete_tree)
    store, slug = athlete_tree["store"], athlete_tree["slug"]
    script.backfill(store, [slug], apply=True)
    saved = {w.id: w for w in store.list_workouts(slug)}
    assert saved[yoga.id].sport == "recovery"
    assert saved[yoga.id].planned_session_id == yoga_plan.id
    assert saved[lift.id].sport == "strength"  # real strength untouched
    assert saved[old_mtb.id].sport == "cross_train"  # legacy rows listed, never changed
    assert script.backfill(store, [slug], apply=True)["changed"] == []
