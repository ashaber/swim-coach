"""intervals.icu -> Garmin workout auto-sync job. Entrypoint: `python -m app.sync`.

Chain: watch -> Garmin Connect -> intervals.icu (already live, zero work here)
-> this job -> the same enrichment `POST /api/workouts/ingest` gives a manual
upload (`app.enrich.enrich_draft`) -> `store.save_workout` -> the PWA
history/detail views and the coach's `get_workouts` tool see it automatically,
with no redeploy and no athlete action.

Both Andrew and Renee already have intervals.icu accounts with Garmin
connected, so Garmin pushes every new activity there within minutes of watch
sync. intervals.icu exposes a free per-athlete personal API key (Settings ->
Developer) that lists activities and downloads the original device FIT file.
Garmin's own Connect Developer Program is enterprise-only (no personal tier)
and the unofficial `garminconnect`/`garth` route is ToS-gray and requires
storing real Garmin credentials -- both explicitly declined in favor of this
approach (see ROADMAP.md).

Step 0 spike (run 2026-07-12 with Andrew's key, live-verified, do not
re-verify): auth is HTTP Basic with username literally `API_KEY` and the
athlete's personal key as the password; `GET .../activities` lists sessions;
`GET .../activity/{id}/file` returns the ORIGINAL Garmin device .fit (parses
identically to a device-file fixture of the same workout, including pool
length frames and SWOLF). `GET .../activity/{id}/fit-file` is a lossy
intervals.icu re-encode -- see `IntervalsClient.download_fit`'s docstring --
and must never be used.

Runs stateless: every invocation re-lists a trailing window of activities and
relies on dedupe (by `Workout.external_id`, plus a secondary date+sport+
duration heuristic) to make re-runs idempotent. Deployed as a Cloud Run Job
(`swim-coach-sync`, same image as the API service, command override) on a
Cloud Scheduler cron -- see `backend/README.md` for the one-time setup and
`.github/workflows/deploy-backend.yml` for how the job's image tag is kept in
sync with the service's.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from swim_coach.models import Athlete, Workout
from swim_coach.parse_files import PARSERS_BY_EXTENSION, WorkoutDraft
from swim_coach.store import StoreInterface

from app.config import ConfigError, Settings
from app.enrich import enrich_draft
from app.logging_config import get_logger
from app.store_factory import make_store

log = get_logger("app.sync")

API_BASE = "https://intervals.icu/api/v1"
_HTTP_TIMEOUT_S = 30.0

# Trailing window of activities re-checked on every run. This is an
# operational overlap that makes re-runs idempotent (dedupe below skips
# anything already saved) -- NOT a physiological threshold, so it needs no
# library/ citation.
SYNC_WINDOW_DAYS = 14

# Secondary dedupe tolerance (see `_is_probable_duplicate`): a manually
# uploaded workout (via POST /api/workouts/ingest, no external_id) that
# happens to be the same session a Garmin watch also pushed to intervals.icu
# won't line up to the second on duration_min (moving-time rounding differs
# slightly between the two ingest paths), so this is intentionally a little
# loose rather than an exact match.
_DUPLICATE_DURATION_TOLERANCE_MIN = 1.0

# On-demand sync window (as opposed to the scheduled job's 14-day
# SYNC_WINDOW_DAYS above) -- shared by both on-demand callers: the coach
# chat's `sync_workouts` tool (app.tools) and the PWA Log tab's "Sync from
# watch" button (POST /api/workouts/sync, app.routes.workouts). The athlete
# just finished a session and wants it pulled in now, not a full re-check of
# two weeks of history -- today + yesterday is cheap and covers the case
# where Garmin/intervals.icu hasn't finished processing yet at the moment of
# the request (tz-safe by construction -- matches this module's own
# date.today() usage rather than doing timezone math).
ON_DEMAND_SYNC_WINDOW_DAYS = 2

# Friendly, caller-facing-safe error for "this athlete has no working
# intervals.icu sync set up" -- covers both "INTERVALS_SYNC_CONFIG itself is
# missing/malformed" and "the env var is fine but doesn't list this athlete"
# without ever leaking env var names or raw config contents to a chat model
# or an HTTP client.
SYNC_NOT_CONFIGURED_ERROR = "sync not configured for this athlete"


class SyncConfigError(ConfigError):
    """Raised when INTERVALS_SYNC_CONFIG is missing or malformed."""


@dataclass(frozen=True)
class IntervalsAthleteConfig:
    slug: str
    intervals_athlete_id: str
    api_key: str


def load_sync_config() -> list[IntervalsAthleteConfig]:
    """Parses `INTERVALS_SYNC_CONFIG` (a JSON array of
    `{"slug", "intervals_athlete_id", "api_key"}` objects, one per synced
    athlete) and fails fast with a clear `SyncConfigError` if it's missing
    or malformed -- per Andrew's global standard ("fail fast on startup if
    required env vars are missing"). See `.env.example` for the documented
    shape."""
    raw = os.environ.get("INTERVALS_SYNC_CONFIG")
    if raw is None or not raw.strip():
        raise SyncConfigError(
            "missing required environment variable INTERVALS_SYNC_CONFIG -- see .env.example"
        )

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SyncConfigError(f"INTERVALS_SYNC_CONFIG is not valid JSON: {exc}") from exc

    if not isinstance(parsed, list) or not parsed:
        raise SyncConfigError(
            "INTERVALS_SYNC_CONFIG must be a non-empty JSON array of athlete configs"
        )

    configs: list[IntervalsAthleteConfig] = []
    for i, entry in enumerate(parsed):
        if not isinstance(entry, dict):
            raise SyncConfigError(f"INTERVALS_SYNC_CONFIG[{i}] must be a JSON object")
        required = ("slug", "intervals_athlete_id", "api_key")
        missing = [key for key in required if not entry.get(key)]
        if missing:
            raise SyncConfigError(
                f"INTERVALS_SYNC_CONFIG[{i}] missing required key(s): {', '.join(missing)}"
            )
        configs.append(
            IntervalsAthleteConfig(
                slug=entry["slug"],
                intervals_athlete_id=entry["intervals_athlete_id"],
                api_key=entry["api_key"],
            )
        )
    return configs


def _request_with_retry(client: httpx.Client, method: str, url: str, **kwargs: Any) -> httpx.Response:
    """One retry on a 5xx response, a timeout, or a connection error -- a
    single transient intervals.icu hiccup must not fail an entire sync run
    (per-activity/per-athlete failure isolation happens a layer up; this is
    just "don't give up on the very first blip")."""
    attempts = 2
    last_exc: Exception | None = None
    response: httpx.Response | None = None
    for attempt in range(attempts):
        try:
            response = client.request(method, url, **kwargs)
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            last_exc = exc
            continue
        if response.status_code >= 500 and attempt < attempts - 1:
            continue
        return response
    if response is not None:
        return response
    assert last_exc is not None  # pragma: no cover - defensive, loop always sets one of the two
    raise last_exc


class IntervalsClient:
    """Thin wrapper over the intervals.icu personal API. Auth is HTTP Basic
    with the username literally `API_KEY` and the athlete's own key as the
    password (verified live 2026-07-12 -- see this module's docstring)."""

    def __init__(
        self,
        athlete_id: str,
        api_key: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._athlete_id = athlete_id
        # `transport=` is only ever set by tests (httpx.MockTransport) --
        # production callers get httpx's real transport.
        self._client = httpx.Client(
            auth=("API_KEY", api_key), timeout=_HTTP_TIMEOUT_S, transport=transport
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "IntervalsClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def list_activities(self, *, oldest: date, newest: date) -> list[dict]:
        response = _request_with_retry(
            self._client,
            "GET",
            f"{API_BASE}/athlete/{self._athlete_id}/activities",
            params={"oldest": oldest.isoformat(), "newest": newest.isoformat()},
        )
        response.raise_for_status()
        return response.json()

    def download_fit(self, activity_id: str) -> bytes:
        # CRITICAL: `/file` returns the ORIGINAL Garmin device .fit.
        # `/activity/{id}/fit-file` is intervals.icu's own lossy re-encode
        # (manufacturer id 30051) -- verified live 2026-07-12 to drop every
        # pool length frame (so SWOLF can't be derived), lose the pool/
        # open-water sub-sport (a pool swim comes back mislabeled swim_ow),
        # and drop session-level HR fields. NEVER switch this to `fit-file`.
        response = _request_with_retry(
            self._client, "GET", f"{API_BASE}/activity/{activity_id}/file"
        )
        response.raise_for_status()
        return response.content


def _is_probable_duplicate(
    draft: WorkoutDraft, existing: list[tuple[date, str, float]]
) -> bool:
    """Secondary dedupe: guards against a workout that was already logged by
    some *other* path (typically a manual .fit upload via the PWA, which
    carries no `external_id`) matching an activity the sync job is about to
    pull in independently. Primary dedupe (external_id) can't catch this
    because that upload never recorded one."""
    return any(
        existing_date == draft.date
        and existing_sport == draft.sport
        and abs(existing_duration - draft.duration_min) <= _DUPLICATE_DURATION_TOLERANCE_MIN
        for existing_date, existing_sport, existing_duration in existing
    )


def _ingest_activity(
    activity: dict,
    *,
    client: IntervalsClient,
    store: StoreInterface,
    slug: str,
    profile: Athlete,
    dedupe_keys: list[tuple[date, str, float]],
) -> Workout | None:
    """Downloads, parses, enriches, and (unless it's a probable duplicate)
    saves one intervals.icu activity. Returns the saved `Workout`, or `None`
    if it was skipped as a probable duplicate. Any exception here is the
    caller's responsibility to catch (see `sync_athlete`) -- a single bad
    activity must not abort the run."""
    activity_id = activity["id"]
    tmp_dir = Path(tempfile.mkdtemp(prefix="swimcoach-sync-"))
    try:
        start = time.monotonic()
        fit_bytes = client.download_fit(activity_id)
        duration_ms = round((time.monotonic() - start) * 1000, 2)
        log.info(
            "sync.fit_downloaded",
            slug=slug,
            activity_id=activity_id,
            byte_count=len(fit_bytes),
            duration_ms=duration_ms,
        )

        tmp_path = tmp_dir / f"{activity_id}.fit"
        tmp_path.write_bytes(fit_bytes)
        draft = PARSERS_BY_EXTENSION[".fit"](tmp_path)
        enrich_draft(draft, store=store, athlete=slug, tmp_path=tmp_path)

        if _is_probable_duplicate(draft, dedupe_keys):
            log.info(
                "sync.skipped_probable_duplicate",
                slug=slug,
                activity_id=activity_id,
                date=str(draft.date),
                sport=draft.sport,
                duration_min=draft.duration_min,
            )
            return None

        workout = Workout(
            id=uuid4(),
            athlete_id=profile.id,
            schema_version=1,
            date=draft.date,
            sport=draft.sport,
            source="fit",
            distance_m=draft.distance_m,
            duration_min=draft.duration_min,
            avg_pace_s_per_100m=draft.avg_pace_s_per_100m,
            rpe=None,  # never knowable from the file -- athlete logs it separately
            sets=draft.sets,
            planned_session_id=draft.planned_session_id,
            raw_ref=draft.raw_ref,
            notes=draft.notes,
            avg_hr=draft.avg_hr,
            max_hr=draft.max_hr,
            laps=draft.laps,
            lengths=draft.lengths,
            pauses=draft.pauses,
            analytics=draft.analytics,
            series_ref=draft.series_ref,
            external_id=f"intervals:{activity_id}",
            sport_detail=draft.sport_detail,
        )
        store.save_workout(slug, workout)
        log.info(
            "sync.workout_saved",
            slug=slug,
            activity_id=activity_id,
            workout_id=str(workout.id),
            external_id=workout.external_id,
        )
        return workout
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def sync_athlete(
    cfg: IntervalsAthleteConfig,
    *,
    store: StoreInterface,
    client: IntervalsClient | None = None,
    window_days: int = SYNC_WINDOW_DAYS,
) -> dict[str, int]:
    """Syncs one athlete's trailing `window_days` (default `SYNC_WINDOW_DAYS`,
    the scheduled job's 14-day operational overlap) of intervals.icu
    activities into the store. Never raises for anything short of a
    programming error -- every failure mode (unknown athlete, list call
    failure, one activity's download/parse failure) is caught, logged, and
    reflected in the returned summary so the caller can always finish the
    run and log a final tally.

    `window_days` lets a caller narrow the lookback -- e.g. the coach chat
    tool (`app.tools._handle_sync_workouts`) passes a cheap 2-day window
    (today's activity plus yesterday's, in case Garmin/intervals.icu hasn't
    finished processing a just-finished session yet) for an on-demand sync,
    rather than re-checking the job's full 14-day trailing window on every
    chat turn.

    `client`, when given, is used as-is (and NOT closed by this function --
    the caller owns it, e.g. tests injecting a mocked transport). When
    omitted, a real `IntervalsClient` is built from `cfg` and closed before
    returning.
    """
    summary = {"listed": 0, "new": 0, "saved": 0, "skipped_duplicate": 0, "failed": 0}

    try:
        profile = store.load_athlete(cfg.slug)
    except FileNotFoundError:
        log.error("sync.unknown_athlete", slug=cfg.slug)
        summary["failed"] += 1
        return summary

    owns_client = client is None
    if client is None:
        client = IntervalsClient(cfg.intervals_athlete_id, cfg.api_key)

    try:
        today = date.today()
        oldest = today - timedelta(days=window_days)
        start = time.monotonic()
        try:
            activities = client.list_activities(oldest=oldest, newest=today)
        except Exception as exc:  # noqa: BLE001 - any transport/HTTP error ends this athlete's run cleanly
            log.error("sync.list_failed", slug=cfg.slug, error=str(exc))
            summary["failed"] += 1
            return summary
        duration_ms = round((time.monotonic() - start) * 1000, 2)
        summary["listed"] = len(activities)
        log.info(
            "sync.activities_listed",
            slug=cfg.slug,
            count=len(activities),
            oldest=str(oldest),
            newest=str(today),
            duration_ms=duration_ms,
        )

        existing_workouts = store.list_workouts(cfg.slug)
        existing_external_ids = {w.external_id for w in existing_workouts if w.external_id}
        dedupe_keys = [(w.date, w.sport, w.duration_min) for w in existing_workouts]

        new_activities = [
            activity
            for activity in activities
            if f"intervals:{activity['id']}" not in existing_external_ids
        ]
        summary["new"] = len(new_activities)

        for activity in new_activities:
            try:
                workout = _ingest_activity(
                    activity,
                    client=client,
                    store=store,
                    slug=cfg.slug,
                    profile=profile,
                    dedupe_keys=dedupe_keys,
                )
            except Exception as exc:  # noqa: BLE001 - one bad activity must not abort the run
                log.error(
                    "sync.activity_failed",
                    slug=cfg.slug,
                    activity_id=activity.get("id"),
                    error=str(exc),
                )
                summary["failed"] += 1
                continue

            if workout is None:
                summary["skipped_duplicate"] += 1
            else:
                summary["saved"] += 1
                dedupe_keys.append((workout.date, workout.sport, workout.duration_min))

        return summary
    finally:
        if owns_client:
            client.close()


def sync_on_demand(
    store: StoreInterface, slug: str, *, window_days: int = ON_DEMAND_SYNC_WINDOW_DAYS
) -> dict[str, Any]:
    """Single-athlete, on-demand sync shared by the coach chat's
    `sync_workouts` tool (`app.tools._handle_sync_workouts`) and the PWA's
    `POST /api/workouts/sync` (`app.routes.workouts`) -- both just want "run
    this one athlete's sync right now, with a small window, and give me a
    friendly reason if it's not set up" rather than the scheduled job's
    multi-athlete `main()` loop below.

    Looks up `slug` in `INTERVALS_SYNC_CONFIG` (via `load_sync_config`) and,
    if found, runs `sync_athlete` with `window_days`. Returns
    `{"error": SYNC_NOT_CONFIGURED_ERROR}` if the config is missing/
    malformed OR simply doesn't list this athlete -- both collapse to the
    same message (see that constant's docstring). On success, returns just
    the plain counts (`listed`/`new`/`saved`/`failed`) -- `skipped_duplicate`
    is an implementation detail neither caller's response shape includes.
    """
    try:
        configs = load_sync_config()
    except ConfigError as exc:
        log.error("sync_on_demand.config_error", slug=slug, error=str(exc))
        return {"error": SYNC_NOT_CONFIGURED_ERROR}

    cfg = next((c for c in configs if c.slug == slug), None)
    if cfg is None:
        log.error("sync_on_demand.athlete_not_configured", slug=slug)
        return {"error": SYNC_NOT_CONFIGURED_ERROR}

    summary = sync_athlete(cfg, store=store, window_days=window_days)
    return {
        "listed": summary["listed"],
        "new": summary["new"],
        "saved": summary["saved"],
        "failed": summary["failed"],
    }


def main() -> int:
    try:
        configs = load_sync_config()
        settings = Settings.from_env()
    except ConfigError as exc:
        log.error("sync.config_error", error=str(exc))
        return 1

    store = make_store(settings)
    run_start = time.monotonic()
    log.info("sync.run_start", athlete_count=len(configs))

    overall = {"listed": 0, "new": 0, "saved": 0, "skipped_duplicate": 0, "failed": 0}
    for cfg in configs:
        summary = sync_athlete(cfg, store=store)
        log.info("sync.athlete_summary", slug=cfg.slug, **summary)
        for key in overall:
            overall[key] += summary[key]

    run_duration_ms = round((time.monotonic() - run_start) * 1000, 2)
    log.info("sync.run_end", duration_ms=run_duration_ms, **overall)
    # Config/startup failures are the only non-zero exit (checked above) --
    # a completed run always exits 0, even with individual activity/athlete
    # failures baked into the summary, per the plan's failure-isolation rule.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
