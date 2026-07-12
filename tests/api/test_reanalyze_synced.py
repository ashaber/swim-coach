"""scripts/reanalyze_synced.py -- re-download + re-parse intervals.icu-synced
workouts, updating them in place.

Same conventions as test_sync.py: no real HTTP (httpx.MockTransport), real
FileStore over an isolated tmp_path copy of athletes/renee (via the
athletes_dir fixture), no LLM/network in tests per Andrew's global standard.
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import date
from pathlib import Path

import httpx
import pytest
from swim_coach.models import Workout
from swim_coach.store import FileStore

from app.sync import IntervalsAthleteConfig, IntervalsClient

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from reanalyze_synced import main, reanalyze_athlete  # noqa: E402

FIT_FIXTURE = REPO_ROOT / "tests" / "unit" / "fixtures" / "fit" / "real_swim.fit"
FIT_MTB_FIXTURE = REPO_ROOT / "tests" / "unit" / "fixtures" / "fit" / "real_mtb_race.fit"

pytestmark = pytest.mark.skipif(
    not FIT_FIXTURE.exists() or not FIT_MTB_FIXTURE.exists(),
    reason="real .fit fixtures required at tests/unit/fixtures/fit/",
)

# real_swim.fit parses to date=2026-03-14, sport=swim_pool, duration_min=54.0,
# zero pauses, sport_detail=None (see tests/unit/test_parse_files.py).
FIT_DATE = date(2026, 3, 14)
FIT_SPORT = "swim_pool"
FIT_DURATION_MIN = 54.0

# real_mtb_race.fit parses to date=2026-06-13, sport=cross_train,
# sport_detail="cycling/mountain", >=5 stationary pauses (see
# tests/unit/test_parse_files.py). The FileStore filename embeds date+sport
# (see engine/swim_coach/store.py's save_workout) -- the "existing" workout
# saved below must carry the SAME date+sport the real fixture will re-parse
# to, or reanalyze would (correctly, per FileStore's own filename scheme)
# write a second file rather than overwriting the first. In production this
# is a non-issue: the original sync always saves the file's own actual
# parsed date/sport in the first place.
MTB_DATE = date(2026, 6, 13)
MTB_SPORT = "cross_train"


def _download_handler(downloads: dict[str, bytes], *, requested: list[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        for activity_id, fit_bytes in downloads.items():
            if request.url.path == f"/api/v1/activity/{activity_id}/file":
                return httpx.Response(200, content=fit_bytes)
        return httpx.Response(404, json={"error": "not found"})

    return handler


def _make_client(handler) -> IntervalsClient:
    return IntervalsClient("i999", "test-api-key", transport=httpx.MockTransport(handler))


def _save_synced_workout(store: FileStore, slug: str, *, activity_id: str, **overrides) -> Workout:
    profile = store.load_athlete(slug)
    data = dict(
        id=uuid.uuid4(),
        athlete_id=profile.id,
        date=FIT_DATE,
        sport=FIT_SPORT,
        source="fit",
        distance_m=1,  # deliberately stale -- proves reanalyze overwrites it
        duration_min=1.0,
        rpe=7,
        notes="felt strong",
        external_id=f"intervals:{activity_id}",
    )
    data.update(overrides)
    workout = Workout(**data)
    store.save_workout(slug, workout)
    return workout


# --- reanalyze_athlete: update-in-place decision logic ----------------------


def test_reanalyze_athlete_updates_pauses_and_sport_detail_in_place(athletes_dir: Path) -> None:
    store = FileStore(base_dir=athletes_dir)
    original = _save_synced_workout(
        store, "renee", activity_id="i-mtb", date=MTB_DATE, sport=MTB_SPORT, distance_m=1, duration_min=1.0
    )
    cfg = IntervalsAthleteConfig(slug="renee", intervals_athlete_id="i999", api_key="test-key")
    requested: list[str] = []
    handler = _download_handler({"i-mtb": FIT_MTB_FIXTURE.read_bytes()}, requested=requested)

    summary = reanalyze_athlete(cfg, store=store, dry_run=False, client=_make_client(handler))

    assert summary == {"workouts_considered": 1, "changed": 1, "unchanged": 0, "failed": 0}
    assert requested == ["/api/v1/activity/i-mtb/file"]

    reloaded = [w for w in store.list_workouts("renee") if w.id == original.id]
    assert len(reloaded) == 1  # same id -- overwritten in place, not duplicated
    updated = reloaded[0]
    assert updated.id == original.id
    assert updated.athlete_id == original.athlete_id
    assert updated.external_id == "intervals:i-mtb"
    assert updated.sport_detail == "cycling/mountain"
    assert len(updated.pauses) >= 5  # the real MTB fixture's stationary bottle stops
    assert updated.distance_m > 1  # stale placeholder overwritten with the real value
    # Athlete-entered fields a .fit can never carry are preserved, not reset.
    assert updated.rpe == 7
    assert updated.notes == "felt strong"


def test_reanalyze_athlete_dry_run_writes_nothing(athletes_dir: Path) -> None:
    store = FileStore(base_dir=athletes_dir)
    original = _save_synced_workout(
        store, "renee", activity_id="i-mtb", date=MTB_DATE, sport=MTB_SPORT, distance_m=1, duration_min=1.0
    )
    cfg = IntervalsAthleteConfig(slug="renee", intervals_athlete_id="i999", api_key="test-key")
    handler = _download_handler({"i-mtb": FIT_MTB_FIXTURE.read_bytes()}, requested=[])

    summary = reanalyze_athlete(cfg, store=store, dry_run=True, client=_make_client(handler))

    assert summary == {"workouts_considered": 1, "changed": 1, "unchanged": 0, "failed": 0}
    reloaded = [w for w in store.list_workouts("renee") if w.id == original.id][0]
    # Untouched -- dry-run must not write the row, the raw file, or the
    # series sidecar.
    assert reloaded == original
    assert reloaded.distance_m == 1
    assert reloaded.sport_detail is None
    assert reloaded.pauses == []


def test_reanalyze_athlete_ignores_manual_and_non_intervals_workouts(athletes_dir: Path) -> None:
    store = FileStore(base_dir=athletes_dir)
    profile = store.load_athlete("renee")
    manual = Workout(
        id=uuid.uuid4(),
        athlete_id=profile.id,
        date=FIT_DATE,
        sport=FIT_SPORT,
        source="manual",
        distance_m=2000,
        duration_min=40.0,
        external_id=None,
    )
    store.save_workout("renee", manual)
    cfg = IntervalsAthleteConfig(slug="renee", intervals_athlete_id="i999", api_key="test-key")

    summary = reanalyze_athlete(cfg, store=store, dry_run=False, client=_make_client(lambda r: httpx.Response(404)))

    assert summary == {"workouts_considered": 0, "changed": 0, "unchanged": 0, "failed": 0}
    reloaded = [w for w in store.list_workouts("renee") if w.id == manual.id][0]
    assert reloaded == manual


def test_reanalyze_athlete_no_change_when_reparse_matches_existing(athletes_dir: Path) -> None:
    # Re-parsing a pool swim (real_swim.fit) yields the same sport_detail
    # (None) and pause_count (0) it already had -- "changed" must stay 0.
    store = FileStore(base_dir=athletes_dir)
    _save_synced_workout(
        store,
        "renee",
        activity_id="i-pool",
        sport=FIT_SPORT,
        distance_m=1623,
        duration_min=FIT_DURATION_MIN,
        sport_detail=None,
    )
    cfg = IntervalsAthleteConfig(slug="renee", intervals_athlete_id="i999", api_key="test-key")
    handler = _download_handler({"i-pool": FIT_FIXTURE.read_bytes()}, requested=[])

    summary = reanalyze_athlete(cfg, store=store, dry_run=False, client=_make_client(handler))

    assert summary == {"workouts_considered": 1, "changed": 0, "unchanged": 1, "failed": 0}


def test_reanalyze_athlete_one_workout_failure_does_not_stop_others(athletes_dir: Path, capsys) -> None:
    store = FileStore(base_dir=athletes_dir)
    _save_synced_workout(store, "renee", activity_id="i-bad", date=MTB_DATE, sport=MTB_SPORT)
    _save_synced_workout(store, "renee", activity_id="i-good", date=MTB_DATE, sport=MTB_SPORT)
    cfg = IntervalsAthleteConfig(slug="renee", intervals_athlete_id="i999", api_key="test-key")
    garbage = Path(__file__).read_bytes()  # not a real .fit -- fitdecode chokes on it
    handler = _download_handler(
        {"i-bad": garbage, "i-good": FIT_MTB_FIXTURE.read_bytes()}, requested=[]
    )

    summary = reanalyze_athlete(cfg, store=store, dry_run=False, client=_make_client(handler))

    assert summary == {"workouts_considered": 2, "changed": 1, "unchanged": 0, "failed": 1}
    log_lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert any(
        entry.get("msg") == "reanalyze failed" and entry.get("external_id") == "intervals:i-bad"
        for entry in log_lines
    )


def test_reanalyze_athlete_unknown_athlete_is_a_clean_failure(athletes_dir: Path) -> None:
    store = FileStore(base_dir=athletes_dir)
    cfg = IntervalsAthleteConfig(slug="nobody", intervals_athlete_id="i999", api_key="test-key")

    summary = reanalyze_athlete(cfg, store=store, dry_run=False)

    assert summary == {"workouts_considered": 0, "changed": 0, "unchanged": 0, "failed": 1}


# --- main(): CLI wiring, --athlete filter, exit codes ------------------------


def test_main_missing_sync_config_is_exit_1(athletes_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INTERVALS_SYNC_CONFIG", raising=False)
    assert main(["--athletes-dir", str(athletes_dir), "--dry-run"]) == 1


def test_main_athlete_filter_skips_athletes_without_a_config_entry(
    athletes_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "INTERVALS_SYNC_CONFIG",
        json.dumps([{"slug": "renee", "intervals_athlete_id": "i999", "api_key": "k"}]),
    )
    # --athlete requests a slug with no matching config entry -- a clean,
    # logged failure (exit 1), not a crash.
    assert main(["--athletes-dir", str(athletes_dir), "--athlete", "someone-else", "--dry-run"]) == 1


def test_main_store_db_without_database_url_is_exit_1(athletes_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "INTERVALS_SYNC_CONFIG",
        json.dumps([{"slug": "renee", "intervals_athlete_id": "i999", "api_key": "k"}]),
    )
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert main(["--store", "db", "--dry-run"]) == 1
