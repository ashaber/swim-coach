"""Backfill script: dry-run by default, --apply sets only the temperature fields; get_workouts exposes them."""

from __future__ import annotations

import importlib.util
import uuid
from datetime import date
from pathlib import Path

import pytest
from swim_coach.models import Workout
from swim_coach.store import FileStore

from app.tools import build_tool_handlers

REPO = Path(__file__).resolve().parents[2]

_SPEC = importlib.util.spec_from_file_location("backfill_workout_temperature", REPO / "scripts" / "backfill_workout_temperature.py")
script = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(script)


class FakeClient:
    """Stands in for IntervalsClient: only list_activities exists, so a FIT download would raise."""

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.calls: list[tuple[date, date]] = []

    def list_activities(self, *, oldest: date, newest: date) -> list[dict]:
        self.calls.append((oldest, newest))
        return self.rows


ROWS = [
    {"id": "i1", "average_temp": 21, "min_temp": 10, "max_temp": 31, "trainer": None},
    {"id": "i3", "average_temp": None, "min_temp": None, "max_temp": None},
    {"id": "i2", "average_temp": 9, "min_temp": 8, "max_temp": 10},
]


def _w(athlete_id: uuid.UUID, external_id: str | None, **kw) -> Workout:
    return Workout(
        id=uuid.uuid4(), athlete_id=athlete_id, date=date(2026, 10, 3), sport="cross_train", source="fit",
        distance_m=1000, duration_min=30.0, rpe=6, notes="keep me", external_id=external_id, **kw,
    )


@pytest.fixture()
def seeded(athletes_dir: Path):
    store = FileStore(base_dir=athletes_dir)
    aid = store.load_athlete("renee").id
    synced, manual, done = _w(aid, "intervals:i1"), _w(aid, None), _w(aid, "intervals:i2", avg_temp_c=5.0)
    no_temp = _w(aid, "intervals:i3")
    for w in (synced, manual, done, no_temp):
        store.save_workout("renee", w)
    return store, synced, manual, done


def test_dry_run_writes_nothing(seeded) -> None:
    store, synced, _, _ = seeded
    client = FakeClient(ROWS)
    tally = script.backfill(store, "renee", client, apply=False)
    assert tally["updated"] == 1 and tally["no_temperature_in_file"] == 1 and len(client.calls) == 1
    saved = {w.id: w for w in store.list_workouts("renee")}
    assert saved[synced.id].avg_temp_c is None


def test_apply_sets_only_temperature_and_skips_others(seeded) -> None:
    store, synced, manual, done = seeded
    script.backfill(store, "renee", FakeClient(ROWS), apply=True)
    saved = {w.id: w for w in store.list_workouts("renee")}
    got = saved[synced.id]
    assert (got.avg_temp_c, got.min_temp_c, got.max_temp_c) == (21, 10, 31)
    assert got.model_dump(exclude={"avg_temp_c", "min_temp_c", "max_temp_c"}) == synced.model_dump(
        exclude={"avg_temp_c", "min_temp_c", "max_temp_c"}
    )
    assert saved[manual.id].avg_temp_c is None  # no file to re-download
    assert saved[done.id].avg_temp_c == 5.0  # already has a value: untouched


def test_apply_is_opt_in() -> None:
    parser = script.build_parser()
    assert parser.parse_args([]).apply is False
    assert parser.parse_args(["--apply"]).apply is True


def test_get_workouts_exposes_temperature_in_both_units(athletes_dir: Path) -> None:
    store = FileStore(base_dir=athletes_dir)
    aid = store.load_athlete("renee").id
    store.save_workout("renee", _w(aid, None, avg_temp_c=21.0, min_temp_c=10.0, max_temp_c=31.0, sport_detail="cycling/mountain"))
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    out = handlers["get_workouts"]({"start_date": "2026-10-03"})
    temp = out["workouts"][0]["temperature"]
    assert temp["min_c"] == 10.0 and temp["min_f"] == 50.0 and temp["max_f"] == 87.8
