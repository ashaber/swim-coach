"""backend/app/sync.py -- the intervals.icu -> Garmin auto-sync job.

No real HTTP: every intervals.icu call is served by an `httpx.MockTransport`
handler (per Andrew's global "no network in tests" standard). `IntervalsClient`
accepts an injected `transport=` for exactly this reason -- see its docstring
in sync.py.

Uses the real `FileStore` (via the `athletes_dir` fixture from
tests/api/conftest.py, an isolated tmp_path copy of `athletes/renee`) rather
than a fake, so these tests also exercise `enrich_draft` and
`Workout`/`WorkoutDraft` validation end to end, the same way
test_workouts_ingest_route.py does for the manual-upload path.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import date
from pathlib import Path

import httpx
import pytest
from swim_coach.models import Workout
from swim_coach.store import FileStore

from app.sync import (
    IntervalsAthleteConfig,
    IntervalsClient,
    SyncConfigError,
    load_sync_config,
    main,
    sync_athlete,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIT_FIXTURE = REPO_ROOT / "tests" / "unit" / "fixtures" / "fit" / "real_swim.fit"
FIT_KAYAK_FIXTURE = REPO_ROOT / "tests" / "unit" / "fixtures" / "fit" / "real_kayak.fit"

pytestmark = pytest.mark.skipif(
    not FIT_FIXTURE.exists(), reason="no real .fit fixture at tests/unit/fixtures/fit/real_swim.fit"
)

# real_swim.fit parses to: date=2026-03-14, sport=swim_pool, duration_min=54.0
# (see tests/api/test_workouts_ingest_route.py, which exercises the same
# fixture through the manual-upload path).
FIT_DATE = date(2026, 3, 14)
FIT_SPORT = "swim_pool"
FIT_DURATION_MIN = 54.0


def _activity(activity_id: str, **overrides) -> dict:
    data = {
        "id": activity_id,
        "start_date_local": "2026-03-14T06:00:00",
        "type": "Swim",
        "source": "GARMIN_CONNECT",
        "distance": 1623,
        "pool_length": 25,
    }
    data.update(overrides)
    return data


def _handler_for(activities: list[dict], downloads: dict[str, bytes], *, requested_paths: list[str]):
    """Builds an httpx.MockTransport handler serving a fixed activities list
    and a per-activity-id map of FIT bytes to return from `/file`. Records
    every requested path (so tests can assert `/file` was hit, never
    `/fit-file`, and that dedupe skipped downloads it should have)."""

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path.endswith("/activities"):
            assert "oldest" in request.url.params
            assert "newest" in request.url.params
            return httpx.Response(200, json=activities)
        for activity_id, fit_bytes in downloads.items():
            if request.url.path == f"/api/v1/activity/{activity_id}/file":
                return httpx.Response(200, content=fit_bytes)
        return httpx.Response(404, json={"error": "not found"})

    return handler


def _make_client(handler) -> IntervalsClient:
    return IntervalsClient("i999", "test-api-key", transport=httpx.MockTransport(handler))


# --- IntervalsClient: auth shape, window params, endpoint choice -----------


def test_list_activities_sends_basic_auth_and_window_params() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["params"] = dict(request.url.params)
        captured["auth_header"] = request.headers.get("authorization", "")
        return httpx.Response(200, json=[])

    client = IntervalsClient("i12345", "s3cr3t-key", transport=httpx.MockTransport(handler))
    result = client.list_activities(oldest=date(2026, 6, 28), newest=date(2026, 7, 12))

    assert result == []
    assert captured["path"] == "/api/v1/athlete/i12345/activities"
    assert captured["params"] == {"oldest": "2026-06-28", "newest": "2026-07-12"}

    # HTTP Basic, username literally "API_KEY", password = the athlete's key.
    expected = "Basic " + base64.b64encode(b"API_KEY:s3cr3t-key").decode()
    assert captured["auth_header"] == expected


def test_download_fit_uses_file_endpoint_never_fit_file() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        return httpx.Response(200, content=b"fake-fit-bytes")

    client = IntervalsClient("i12345", "s3cr3t-key", transport=httpx.MockTransport(handler))
    body = client.download_fit("i999888")

    assert body == b"fake-fit-bytes"
    assert requested == ["/api/v1/activity/i999888/file"]
    assert "fit-file" not in requested[0]


# --- sync_athlete: end-to-end against a real FileStore ---------------------


def test_sync_athlete_saves_new_activity_with_external_id_and_analytics(athletes_dir: Path) -> None:
    store = FileStore(base_dir=athletes_dir)
    # athletes/renee's committed tree already has its own workout log(s) --
    # assert on the delta, not an absolute count, so this test doesn't
    # depend on what else happens to be committed there.
    baseline_ids = {w.id for w in store.list_workouts("renee")}
    cfg = IntervalsAthleteConfig(slug="renee", intervals_athlete_id="i999", api_key="test-key")
    requested: list[str] = []
    handler = _handler_for(
        activities=[_activity("i123")],
        downloads={"i123": FIT_FIXTURE.read_bytes()},
        requested_paths=requested,
    )

    summary = sync_athlete(cfg, store=store, client=_make_client(handler))

    assert summary == {"listed": 1, "new": 1, "saved": 1, "skipped_duplicate": 0, "failed": 0}
    assert any(p.endswith("/file") for p in requested)
    assert not any("fit-file" in p for p in requested)

    new_workouts = [w for w in store.list_workouts("renee") if w.id not in baseline_ids]
    assert len(new_workouts) == 1
    workout = new_workouts[0]
    assert workout.external_id == "intervals:i123"
    assert workout.source == "fit"
    assert workout.rpe is None
    assert workout.analytics is not None
    assert workout.date == FIT_DATE
    assert workout.sport == FIT_SPORT


def test_sync_athlete_external_id_dedupe_skips_without_downloading(athletes_dir: Path) -> None:
    store = FileStore(base_dir=athletes_dir)
    baseline_ids = {w.id for w in store.list_workouts("renee")}
    profile = store.load_athlete("renee")
    existing = Workout(
        id=uuid.uuid4(),
        athlete_id=profile.id,
        date=FIT_DATE,
        sport=FIT_SPORT,
        source="fit",
        distance_m=1623,
        duration_min=FIT_DURATION_MIN,
        external_id="intervals:i123",
    )
    store.save_workout("renee", existing)

    cfg = IntervalsAthleteConfig(slug="renee", intervals_athlete_id="i999", api_key="test-key")
    requested: list[str] = []
    handler = _handler_for(
        activities=[_activity("i123")],
        downloads={"i123": FIT_FIXTURE.read_bytes()},
        requested_paths=requested,
    )

    summary = sync_athlete(cfg, store=store, client=_make_client(handler))

    assert summary == {"listed": 1, "new": 0, "saved": 0, "skipped_duplicate": 0, "failed": 0}
    # Primary dedupe happens before any download -- only the list call fires.
    assert not any(p.endswith("/file") for p in requested)
    new_workouts = [w for w in store.list_workouts("renee") if w.id not in baseline_ids]
    assert new_workouts == [existing]


def test_sync_athlete_probable_duplicate_skips_with_log(athletes_dir: Path, capsys) -> None:
    store = FileStore(base_dir=athletes_dir)
    baseline_ids = {w.id for w in store.list_workouts("renee")}
    profile = store.load_athlete("renee")
    # A manually uploaded workout for the same session, carrying no
    # external_id -- primary dedupe can't see it, so the secondary
    # date+sport+duration heuristic must catch it instead.
    manual = Workout(
        id=uuid.uuid4(),
        athlete_id=profile.id,
        date=FIT_DATE,
        sport=FIT_SPORT,
        source="fit",
        distance_m=1623,
        duration_min=FIT_DURATION_MIN + 0.3,  # within the +-1.0min tolerance
    )
    store.save_workout("renee", manual)

    cfg = IntervalsAthleteConfig(slug="renee", intervals_athlete_id="i999", api_key="test-key")
    handler = _handler_for(
        activities=[_activity("i123")],
        downloads={"i123": FIT_FIXTURE.read_bytes()},
        requested_paths=[],
    )

    summary = sync_athlete(cfg, store=store, client=_make_client(handler))

    assert summary == {"listed": 1, "new": 1, "saved": 0, "skipped_duplicate": 1, "failed": 0}
    new_workouts = [w for w in store.list_workouts("renee") if w.id not in baseline_ids]
    assert new_workouts == [manual]  # nothing new saved besides the manual upload itself

    log_lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert any(entry.get("msg") == "sync.skipped_probable_duplicate" for entry in log_lines)


def test_sync_athlete_one_activity_failure_does_not_stop_others(athletes_dir: Path) -> None:
    store = FileStore(base_dir=athletes_dir)
    baseline_ids = {w.id for w in store.list_workouts("renee")}
    cfg = IntervalsAthleteConfig(slug="renee", intervals_athlete_id="i999", api_key="test-key")
    # "bad" gets garbage bytes (this test module's own source, mislabeled
    # .fit) so fitdecode chokes on it -- mirrors
    # test_workouts_ingest_route.py's corrupt-.fit test. "good" gets the real
    # fixture and must still be saved even though "bad" is listed first.
    garbage = Path(__file__).read_bytes()
    handler = _handler_for(
        activities=[_activity("i-bad"), _activity("i-good")],
        downloads={"i-bad": garbage, "i-good": FIT_FIXTURE.read_bytes()},
        requested_paths=[],
    )

    summary = sync_athlete(cfg, store=store, client=_make_client(handler))

    assert summary == {"listed": 2, "new": 2, "saved": 1, "skipped_duplicate": 0, "failed": 1}
    new_workouts = [w for w in store.list_workouts("renee") if w.id not in baseline_ids]
    assert len(new_workouts) == 1
    assert new_workouts[0].external_id == "intervals:i-good"


def test_sync_athlete_unknown_athlete_is_a_clean_failure(athletes_dir: Path) -> None:
    store = FileStore(base_dir=athletes_dir)
    cfg = IntervalsAthleteConfig(slug="nobody", intervals_athlete_id="i999", api_key="test-key")

    summary = sync_athlete(cfg, store=store, client=_make_client(lambda r: httpx.Response(200, json=[])))

    assert summary == {"listed": 0, "new": 0, "saved": 0, "skipped_duplicate": 0, "failed": 1}


def test_sync_athlete_custom_window_days_changes_oldest_param(athletes_dir: Path) -> None:
    # The coach chat tool (app.tools._handle_sync_workouts) calls this same
    # function with a small on-demand window instead of the scheduled job's
    # 14-day SYNC_WINDOW_DAYS default -- this proves the parameter actually
    # reaches the `list_activities` call rather than being ignored.
    store = FileStore(base_dir=athletes_dir)
    cfg = IntervalsAthleteConfig(slug="renee", intervals_athlete_id="i999", api_key="test-key")
    captured_params: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/activities"):
            captured_params.update(dict(request.url.params))
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={"error": "not found"})

    summary = sync_athlete(cfg, store=store, client=_make_client(handler), window_days=2)

    assert summary == {"listed": 0, "new": 0, "saved": 0, "skipped_duplicate": 0, "failed": 0}
    oldest = date.fromisoformat(captured_params["oldest"])
    newest = date.fromisoformat(captured_params["newest"])
    assert (newest - oldest).days == 2


# --- config parsing ----------------------------------------------------------


def test_load_sync_config_missing_env_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INTERVALS_SYNC_CONFIG", raising=False)
    with pytest.raises(SyncConfigError, match="INTERVALS_SYNC_CONFIG"):
        load_sync_config()


def test_load_sync_config_malformed_json_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTERVALS_SYNC_CONFIG", "{not valid json")
    with pytest.raises(SyncConfigError):
        load_sync_config()


def test_load_sync_config_missing_required_key_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "INTERVALS_SYNC_CONFIG", json.dumps([{"slug": "renee", "intervals_athlete_id": "i1"}])
    )
    with pytest.raises(SyncConfigError, match="api_key"):
        load_sync_config()


def test_load_sync_config_parses_valid_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "INTERVALS_SYNC_CONFIG",
        json.dumps(
            [
                {"slug": "renee", "intervals_athlete_id": "i1", "api_key": "k1"},
                {"slug": "andrew", "intervals_athlete_id": "i2", "api_key": "k2"},
            ]
        ),
    )
    configs = load_sync_config()
    assert configs == [
        IntervalsAthleteConfig(slug="renee", intervals_athlete_id="i1", api_key="k1"),
        IntervalsAthleteConfig(slug="andrew", intervals_athlete_id="i2", api_key="k2"),
    ]


def test_main_missing_sync_config_is_nonzero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INTERVALS_SYNC_CONFIG", raising=False)
    assert main() != 0


def test_main_malformed_sync_config_is_nonzero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTERVALS_SYNC_CONFIG", "not json at all")
    assert main() != 0
