"""Handler tests for the `pull_activity_stream` coach tool -- the
"re-pull the original .fit from intervals.icu, run the current analyzer,
cache the result" counterpart to `reanalyze_workout`.

No network: `app.tools.IntervalsClient` is monkeypatched with a fake whose
`download_fit` returns the bytes of the committed real MTB race fixture
(per Andrew's "no network in tests" standard). Credentials come from an
`INTERVALS_SYNC_CONFIG` env var the test sets, exercising the real
`app.sync.load_sync_config`.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path

import pytest
from swim_coach.models import (
    Session,
    WeekPlan,
    Workout,
    WorkoutRepeat,
    WorkoutStep,
    WorkoutStructure,
    WorkoutTarget,
)
from swim_coach.parse_files import parse_fit
from swim_coach.store import FileStore

from app.context import iso_week_str
from app.tools import build_tool_handlers

REPO_ROOT = Path(__file__).resolve().parents[2]
FIT_MTB = REPO_ROOT / "tests" / "unit" / "fixtures" / "fit" / "real_mtb_race.fit"

pytestmark = pytest.mark.skipif(not FIT_MTB.exists(), reason="no real MTB race .fit fixture")

RIDE_DATE = date(2026, 7, 15)
ACTIVITY_ID = "i84213507"


class _FakeIntervalsClient:
    """Stands in for `app.sync.IntervalsClient`: a context manager whose
    `download_fit` returns the fixture bytes and records the id it was
    asked for. Set `raise_on_download` to simulate a transport failure."""

    last_id: str | None = None
    raise_on_download = False

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def __enter__(self) -> "_FakeIntervalsClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def download_fit(self, activity_id: str) -> bytes:
        _FakeIntervalsClient.last_id = activity_id
        if _FakeIntervalsClient.raise_on_download:
            raise RuntimeError("intervals.icu 503")
        return FIT_MTB.read_bytes()


@pytest.fixture(autouse=True)
def _reset_fake() -> None:
    _FakeIntervalsClient.last_id = None
    _FakeIntervalsClient.raise_on_download = False


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.tools.IntervalsClient", _FakeIntervalsClient)
    monkeypatch.setenv(
        "INTERVALS_SYNC_CONFIG",
        json.dumps([{"slug": "renee", "intervals_athlete_id": "iX", "api_key": "k"}]),
    )


def _handlers(store: FileStore):
    return build_tool_handlers(store, slug="renee", expert_mode=False)


def _seed_synced_bike(store: FileStore, *, activity_id: str = ACTIVITY_ID, sport: str = "bike") -> Workout:
    profile = store.load_athlete("renee")
    w = Workout(
        id=uuid.uuid4(),
        athlete_id=profile.id,
        date=RIDE_DATE,
        sport=sport,
        source="fit",
        distance_m=1000,
        duration_min=60.0,
        external_id=f"intervals:{activity_id}",
    )
    store.save_workout("renee", w)
    return w


def test_pull_by_workout_id_fetches_analyzes_and_caches(athletes_dir, wired) -> None:
    store = FileStore(base_dir=athletes_dir)
    w = _seed_synced_bike(store)

    res = _handlers(store)["pull_activity_stream"](
        {"workout_id": str(w.id), "target_watts": 239}
    )

    assert res["pulled"] is True
    assert res["cached"] is True
    assert res["series_source"] == "re-pulled from intervals.icu"
    assert res["target_watts"] == 239
    assert _FakeIntervalsClient.last_id == ACTIVITY_ID
    intervals = res["intervals"]
    assert intervals is not None and intervals["efforts_detected"] > 0
    assert all(e["target_w"] == 239 for e in intervals["efforts"])
    # cached: series row + analytics persisted in place
    assert store.load_series("renee", w.id) is not None
    reloaded = store.get_workout("renee", w.id)
    assert reloaded.analytics.intervals.efforts_detected == intervals["efforts_detected"]


def test_pull_by_explicit_activity_id_without_local_workout(athletes_dir, wired) -> None:
    store = FileStore(base_dir=athletes_dir)

    res = _handlers(store)["pull_activity_stream"](
        {"intervals_activity_id": "i999999", "target_watts": 240}
    )

    assert res["pulled"] is True
    assert res["cached"] is False
    assert res["workout_id"] is None
    assert _FakeIntervalsClient.last_id == "i999999"
    assert res["intervals"]["efforts_detected"] > 0


def test_pull_by_activity_id_matches_local_workout_and_caches(athletes_dir, wired) -> None:
    store = FileStore(base_dir=athletes_dir)
    w = _seed_synced_bike(store, activity_id="i555")

    res = _handlers(store)["pull_activity_stream"]({"intervals_activity_id": "i555"})

    assert res["cached"] is True
    assert res["workout_id"] == str(w.id)
    assert res["target_source"] == "none"
    assert all(e["target_w"] is None for e in res["intervals"]["efforts"])


def test_pull_recovers_target_from_matched_planned_session(athletes_dir, wired) -> None:
    store = FileStore(base_dir=athletes_dir)
    w = _seed_synced_bike(store)
    profile = store.load_athlete("renee")
    structure = WorkoutStructure(
        items=[
            WorkoutRepeat(
                repeat_mode="count",
                count=2,
                steps=[
                    WorkoutStep(
                        label="threshold", role="interval", duration_kind="time_s",
                        duration_value=720, modality="bike",
                        target=WorkoutTarget(basis="power_w", low=248, high=248),
                    ),
                ],
            ),
        ]
    )
    store.save_week(
        "renee",
        WeekPlan(
            id=uuid.uuid4(), athlete_id=profile.id, iso_week=iso_week_str(RIDE_DATE),
            meso_block="build", focus="threshold", target_volume_m=0,
            sessions=[
                Session(
                    id=uuid.uuid4(), athlete_id=profile.id, date=RIDE_DATE, sport="bike",
                    source="ai_coach", duration_min=90.0, intensity={"zone": "Z4"},
                    purpose="2x12", structured=structure,
                )
            ],
        ),
    )

    res = _handlers(store)["pull_activity_stream"]({"workout_id": str(w.id)})

    assert res["target_source"] == "matched planned session structure"
    assert res["intervals"]["efforts"][0]["target_w"] == 248


def test_pull_with_ftp_and_pct(athletes_dir, wired) -> None:
    store = FileStore(base_dir=athletes_dir)
    w = _seed_synced_bike(store)
    res = _handlers(store)["pull_activity_stream"](
        {"workout_id": str(w.id), "ftp_watts": 263, "pct_ftp": 91}
    )
    assert res["target_watts"] == pytest.approx(239.3, abs=0.1)
    assert "263" in res["target_source"] and "91" in res["target_source"]


def test_pull_requires_an_identifier(athletes_dir, wired) -> None:
    store = FileStore(base_dir=athletes_dir)
    res = _handlers(store)["pull_activity_stream"]({})
    assert "error" in res and "workout_id or intervals_activity_id" in res["error"]


def test_pull_rejects_a_workout_not_synced_from_intervals(athletes_dir, wired) -> None:
    store = FileStore(base_dir=athletes_dir)
    profile = store.load_athlete("renee")
    w = Workout(
        id=uuid.uuid4(), athlete_id=profile.id, date=RIDE_DATE, sport="bike",
        source="fit", distance_m=1000, duration_min=60.0, external_id=None,
    )
    store.save_workout("renee", w)
    res = _handlers(store)["pull_activity_stream"]({"workout_id": str(w.id)})
    assert "error" in res and "wasn't synced" in res["error"]


def test_pull_rejects_non_bike_workout(athletes_dir, wired) -> None:
    store = FileStore(base_dir=athletes_dir)
    w = _seed_synced_bike(store, sport="swim_pool")
    res = _handlers(store)["pull_activity_stream"]({"workout_id": str(w.id)})
    assert "error" in res and "only runs on bike" in res["error"]


def test_pull_errors_when_sync_not_configured(athletes_dir, monkeypatch) -> None:
    monkeypatch.setattr("app.tools.IntervalsClient", _FakeIntervalsClient)
    monkeypatch.delenv("INTERVALS_SYNC_CONFIG", raising=False)
    store = FileStore(base_dir=athletes_dir)
    w = _seed_synced_bike(store)
    res = _handlers(store)["pull_activity_stream"]({"workout_id": str(w.id)})
    assert "error" in res and "sync not configured" in res["error"]


def test_pull_surfaces_a_download_failure_as_a_clean_error(athletes_dir, wired) -> None:
    store = FileStore(base_dir=athletes_dir)
    w = _seed_synced_bike(store)
    _FakeIntervalsClient.raise_on_download = True
    res = _handlers(store)["pull_activity_stream"]({"workout_id": str(w.id)})
    assert "error" in res and "could not download" in res["error"]
    # nothing cached on a failed pull
    assert store.load_series("renee", w.id) is None
