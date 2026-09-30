"""Sync stores a workout on the athlete's LOCAL calendar day and links it to its
planned session (2026-09-29 regression: an evening ride was dated the next day
in UTC and never matched).

No real HTTP -- intervals.icu is an `httpx.MockTransport`.
"""

from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path

import httpx
import pytest
from swim_coach.models import Session, WeekPlan
from swim_coach.store import FileStore

from app.sync import IntervalsAthleteConfig, IntervalsClient, sync_athlete

REPO_ROOT = Path(__file__).resolve().parents[2]
FIT_MTB = REPO_ROOT / "tests" / "unit" / "fixtures" / "fit" / "real_mtb_race.fit"  # parses to bike, 2026-06-13 UTC

pytestmark = pytest.mark.skipif(not FIT_MTB.exists(), reason="real_mtb_race.fit fixture missing")


def _client(start_date_local: str) -> IntervalsClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/activities"):
            return httpx.Response(200, json=[{"id": "i77", "start_date_local": start_date_local}])
        if request.url.path == "/api/v1/activity/i77/file":
            return httpx.Response(200, content=FIT_MTB.read_bytes())
        return httpx.Response(404, json={"error": "not found"})

    return IntervalsClient("i999", "k", transport=httpx.MockTransport(handler))


def _plan_bike_session(store: FileStore, day: date) -> Session:
    profile = store.load_athlete("renee")
    session = Session(
        id=uuid.uuid4(), athlete_id=profile.id, date=day, sport="bike", source="ai_coach",
        duration_min=60.0, distance_m=0, intensity={"zone": "Z2"}, purpose="endurance",
    )
    year, week, _ = day.isocalendar()
    store.save_week(
        "renee",
        WeekPlan(
            id=uuid.uuid4(), athlete_id=profile.id, iso_week=f"{year}-W{week:02d}",
            meso_block="build", focus="build", target_volume_m=0, sessions=[session],
        ),
    )
    return session


def _new_workout(store: FileStore, baseline: set):
    return next(w for w in store.list_workouts("renee") if w.id not in baseline)


def test_sync_dates_workout_by_provider_local_start_and_matches_adjacent_session(athletes_dir: Path) -> None:
    store = FileStore(base_dir=athletes_dir)
    baseline = {w.id for w in store.list_workouts("renee")}
    planned = _plan_bike_session(store, date(2026, 6, 12))
    cfg = IntervalsAthleteConfig(slug="renee", intervals_athlete_id="i999", api_key="k")

    summary = sync_athlete(cfg, store=store, client=_client("2026-06-12T20:30:00"))

    assert summary["saved"] == 1
    workout = _new_workout(store, baseline)
    assert workout.date == date(2026, 6, 12)  # local day, not the FIT's UTC 06-13
    assert workout.planned_session_id == planned.id


def test_sync_without_provider_local_keeps_fit_date(athletes_dir: Path) -> None:
    store = FileStore(base_dir=athletes_dir)
    baseline = {w.id for w in store.list_workouts("renee")}
    cfg = IntervalsAthleteConfig(slug="renee", intervals_athlete_id="i999", api_key="k")

    sync_athlete(cfg, store=store, client=_client("not-a-timestamp"))

    workout = _new_workout(store, baseline)
    assert workout.date == date(2026, 6, 13)
    assert workout.planned_session_id is None


def test_sync_does_not_steal_a_session_already_covered_by_another_workout(athletes_dir: Path) -> None:
    store = FileStore(base_dir=athletes_dir)
    baseline = {w.id for w in store.list_workouts("renee")}
    planned = _plan_bike_session(store, date(2026, 6, 12))
    profile = store.load_athlete("renee")
    from swim_coach.models import Workout

    store.save_workout(
        "renee",
        Workout(
            id=uuid.uuid4(), athlete_id=profile.id, date=date(2026, 6, 12), sport="bike",
            source="manual", distance_m=1000, duration_min=30.0, planned_session_id=planned.id,
        ),
    )
    baseline |= {w.id for w in store.list_workouts("renee")}
    cfg = IntervalsAthleteConfig(slug="renee", intervals_athlete_id="i999", api_key="k")

    sync_athlete(cfg, store=store, client=_client("2026-06-13T09:00:00"))

    assert _new_workout(store, baseline).planned_session_id is None
