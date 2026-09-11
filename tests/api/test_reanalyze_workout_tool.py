"""Handler tests for the `reanalyze_workout` coach tool -- all target-
resolution branches (supplied watts, FTP+pct, recovered from a matched
planned session's structure, none) plus the error paths.

Uses the real MTB race .fit fixture only as a source of a realistic power/
grade series to persist; it's an unstructured race, so the point here is
the tool's plumbing (which target it uses, that it persists, its error
handling), not exact interval counts.
"""

from __future__ import annotations

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


def _seed_bike_workout(store: FileStore, *, with_series: bool = True, raw_ref: str | None = None) -> Workout:
    profile = store.load_athlete("renee")
    draft = parse_fit(FIT_MTB)
    w = Workout(
        id=uuid.uuid4(),
        athlete_id=profile.id,
        date=RIDE_DATE,
        sport="bike",
        source="fit",
        distance_m=draft.distance_m,
        duration_min=draft.duration_min,
        rpe=7,
        notes="race day",
        laps=draft.laps,
        pauses=draft.pauses,
        raw_ref=raw_ref,
    )
    store.save_workout("renee", w)
    if with_series:
        store.save_series("renee", w.date, w.sport, w.id, draft.series)
    return w


def _handlers(store: FileStore):
    return build_tool_handlers(store, slug="renee", expert_mode=False)


def test_reanalyze_with_explicit_target_watts(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    w = _seed_bike_workout(store)
    res = _handlers(store)["reanalyze_workout"]({"workout_id": str(w.id), "target_watts": 239})
    assert res["reanalyzed"] is True
    assert res["target_watts"] == 239
    assert res["target_source"] == "target_watts"
    assert res["series_source"] == "stored series"
    intervals = res["intervals"]
    assert intervals is not None and intervals["efforts_detected"] > 0
    assert all(e["target_w"] == 239 for e in intervals["efforts"])
    # Persisted in place.
    reloaded = store.get_workout("renee", w.id)
    assert reloaded.analytics.intervals is not None
    assert reloaded.analytics.intervals.efforts_detected == intervals["efforts_detected"]


def test_reanalyze_with_ftp_and_pct(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    w = _seed_bike_workout(store)
    res = _handlers(store)["reanalyze_workout"](
        {"workout_id": str(w.id), "ftp_watts": 263, "pct_ftp": 91}
    )
    assert res["reanalyzed"] is True
    assert res["target_watts"] == pytest.approx(239.3, abs=0.1)
    assert "263" in res["target_source"] and "91" in res["target_source"]


def test_reanalyze_recovers_target_from_matched_planned_session(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    w = _seed_bike_workout(store)
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
                        target=WorkoutTarget(basis="power_w", low=245, high=245),
                    ),
                ],
            ),
        ]
    )
    week = WeekPlan(
        id=uuid.uuid4(),
        athlete_id=profile.id,
        iso_week=iso_week_str(RIDE_DATE),
        meso_block="build",
        focus="threshold",
        target_volume_m=0,
        sessions=[
            Session(
                id=uuid.uuid4(),
                athlete_id=profile.id,
                date=RIDE_DATE,
                sport="bike",
                source="ai_coach",
                duration_min=90.0,
                intensity={"zone": "Z4"},
                purpose="2x12 threshold",
                structured=structure,
            )
        ],
    )
    store.save_week("renee", week)

    res = _handlers(store)["reanalyze_workout"]({"workout_id": str(w.id)})
    assert res["reanalyzed"] is True
    assert res["target_source"] == "matched planned session structure"
    intervals = res["intervals"]
    # first two detected efforts get the prescribed 245W rep target
    assert intervals["efforts"][0]["target_w"] == 245
    assert intervals["prescribed_count"] == 2


def test_reanalyze_no_target_still_detects_on_dynamic_threshold(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    w = _seed_bike_workout(store)
    res = _handlers(store)["reanalyze_workout"]({"workout_id": str(w.id)})
    assert res["reanalyzed"] is True
    assert res["target_source"] == "none"
    intervals = res["intervals"]
    assert intervals["efforts_detected"] > 0
    assert all(e["target_w"] is None for e in intervals["efforts"])


def test_reanalyze_falls_back_to_reparsing_raw_ref_when_no_stored_series(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    w = _seed_bike_workout(store, with_series=False, raw_ref=str(FIT_MTB))
    res = _handlers(store)["reanalyze_workout"]({"workout_id": str(w.id), "target_watts": 239})
    assert res["reanalyzed"] is True
    assert res["series_source"].startswith("re-parsed")
    # And now a series row exists for the real workout id.
    assert store.load_series("renee", w.id) is not None


def test_reanalyze_errors_when_no_series_and_no_raw(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    w = _seed_bike_workout(store, with_series=False, raw_ref=None)
    res = _handlers(store)["reanalyze_workout"]({"workout_id": str(w.id), "target_watts": 239})
    assert "error" in res and "no time-series data" in res["error"]


def test_reanalyze_errors_on_unknown_workout(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    res = _handlers(store)["reanalyze_workout"]({"workout_id": str(uuid.uuid4())})
    assert "error" in res and "no workout matching" in res["error"]


def test_reanalyze_errors_on_non_bike_workout(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    profile = store.load_athlete("renee")
    w = Workout(
        id=uuid.uuid4(), athlete_id=profile.id, date=RIDE_DATE, sport="swim_pool",
        source="fit", distance_m=2000, duration_min=40.0,
    )
    store.save_workout("renee", w)
    res = _handlers(store)["reanalyze_workout"]({"workout_id": str(w.id), "target_watts": 239})
    assert "error" in res and "only runs on bike" in res["error"]
    # A genuinely non-bike sport (not cross_train) gets no mis-tag hint.
    assert "pull_activity_stream" not in res["error"]


def test_reanalyze_on_cross_train_workout_hints_at_pull_activity_stream(athletes_dir) -> None:
    """This tool's gate is legitimate (it has no fresh source to defer to
    -- see its docstring), but a cross_train tag specifically is plausibly
    stale historical data (predating the bike carve-out), so the error
    should point the coach at the tool that CAN re-pull and correct it."""
    store = FileStore(base_dir=athletes_dir)
    profile = store.load_athlete("renee")
    w = Workout(
        id=uuid.uuid4(), athlete_id=profile.id, date=RIDE_DATE, sport="cross_train",
        source="fit", distance_m=20000, duration_min=45.0,
    )
    store.save_workout("renee", w)
    res = _handlers(store)["reanalyze_workout"]({"workout_id": str(w.id), "target_watts": 239})
    assert "error" in res and "only runs on bike" in res["error"]
    assert "pull_activity_stream" in res["error"]


def test_reanalyze_errors_on_bad_ftp_pct_pairing(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    w = _seed_bike_workout(store)
    res = _handlers(store)["reanalyze_workout"]({"workout_id": str(w.id), "ftp_watts": 263})
    assert "error" in res and "together" in res["error"]
