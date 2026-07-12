#!/usr/bin/env python3
"""Re-download + re-parse intervals.icu-synced workouts, updating them in place.

Purpose: `engine/swim_coach/parse_files.parse_fit` gained new derived fields
(sport_detail, stationary-speed pauses -- see library/11-workout-
analytics.md) after some workouts were already synced from intervals.icu.
This script re-downloads each already-synced workout's ORIGINAL .fit (via
`backend/app/sync.IntervalsClient.download_fit`, never the lossy
`fit-file` re-encode -- see that module's big warning comment), re-parses
it with the current parser, recomputes analytics, and overwrites the
EXISTING workout row (same `id`/`athlete_id`) with the refreshed fields.
Never deletes or duplicates a row -- `store.save_workout` upserts by id in
both FileStore and DbStore (see engine/swim_coach/store.py / store_db.py).

Only touches workouts whose `external_id` starts with `"intervals:"` (i.e.
came from the sync job, not a manual upload or coach-text log) -- those are
the only ones this script knows how to re-download. Athlete-entered fields
that a .fit file can never carry (`rpe`, `notes`, `planned_session_id`) are
preserved from the existing row, not overwritten with a default.

Usage:
    INTERVALS_SYNC_CONFIG=... python scripts/reanalyze_synced.py --dry-run
    INTERVALS_SYNC_CONFIG=... python scripts/reanalyze_synced.py --athlete renee
    INTERVALS_SYNC_CONFIG=... python scripts/reanalyze_synced.py --store db --database-url postgresql://...

Flags:
    --athlete SLUG      only this athlete (default: every slug with an
                         INTERVALS_SYNC_CONFIG entry)
    --athletes-dir DIR  FileStore root, only used with --store file (default: athletes)
    --store {file,db}   which StoreInterface backend to read/write (default: file)
    --database-url URL  Supabase DSN, only used with --store db (default: $DATABASE_URL)
    --dry-run           report what WOULD change; write nothing (no raw-file/
                         series-sidecar writes either -- see _reanalyze_workout)

Exit codes: 0 = every considered workout reanalyzed (or would-reanalyze)
cleanly; 1 = at least one athlete/workout failed (a missing sync config, a
download/parse error, etc. -- per-item failures don't abort the run, they're
tallied and reflected in the final exit code, same discipline as
backend/app/sync.py's sync_athlete).

Structured JSON logging to stdout (per the global standard). No LLM calls.
Network only to intervals.icu (via IntervalsClient) -- never mocked/skipped
outside tests, per Andrew's "no network in tests" standard for the test
module that exercises this script.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# `app.sync`/`app.enrich` live under backend/app, not an installed package --
# same sys.path insertion tests/api/conftest.py uses so `import app.*` works
# from outside the backend/ directory.
REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from swim_coach.analytics import compute_analytics  # noqa: E402
from swim_coach.models import Workout  # noqa: E402
from swim_coach.parse_files import PARSERS_BY_EXTENSION  # noqa: E402
from swim_coach.store import FileStore, StoreInterface  # noqa: E402

from app.enrich import enrich_draft  # noqa: E402
from app.sync import IntervalsClient, SyncConfigError, load_sync_config  # noqa: E402


def _log(level: str, msg: str, **meta: object) -> None:
    print(
        json.dumps(
            {
                "level": level,
                "msg": msg,
                **meta,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        )
    )


def _reanalyze_workout(
    existing: Workout,
    *,
    client: IntervalsClient,
    store: StoreInterface,
    slug: str,
    dry_run: bool,
) -> dict:
    """Re-downloads/re-parses one already-synced workout and (unless
    `dry_run`) overwrites its row in place. Returns a before/after summary
    dict for logging/tallying. Raises on any download/parse/save failure --
    the caller (main) is responsible for catching it per-workout, same
    discipline as backend/app/sync.py's _ingest_activity/sync_athlete."""
    activity_id = existing.external_id.removeprefix("intervals:")
    tmp_dir = Path(tempfile.mkdtemp(prefix="swimcoach-reanalyze-"))
    try:
        fit_bytes = client.download_fit(activity_id)
        tmp_path = tmp_dir / f"{activity_id}.fit"
        tmp_path.write_bytes(fit_bytes)
        draft = PARSERS_BY_EXTENSION[".fit"](tmp_path)

        if dry_run:
            # No raw-file copy / series sidecar write under --dry-run (both
            # are real disk/DB writes -- see enrich_draft's docstring).
            # Analytics is a pure function over the in-memory parse, so it's
            # still computed here purely for an accurate dry-run report.
            draft.analytics = compute_analytics(
                laps=draft.laps,
                lengths=draft.lengths,
                pauses=draft.pauses,
                series=draft.series,
                elapsed_min=draft.elapsed_min,
                moving_min=draft.duration_min,
            )
        else:
            enrich_draft(draft, store=store, athlete=slug, tmp_path=tmp_path)

        rebuilt = Workout(
            id=existing.id,
            athlete_id=existing.athlete_id,
            date=draft.date,
            sport=draft.sport,
            source=existing.source,
            distance_m=draft.distance_m,
            duration_min=draft.duration_min,
            avg_pace_s_per_100m=draft.avg_pace_s_per_100m,
            rpe=existing.rpe,  # never knowable from the file -- preserved
            sets=draft.sets,
            planned_session_id=existing.planned_session_id,  # not file-derivable
            raw_ref=draft.raw_ref if not dry_run else existing.raw_ref,
            notes=existing.notes,  # never knowable from the file -- preserved
            avg_hr=draft.avg_hr,
            max_hr=draft.max_hr,
            laps=draft.laps,
            lengths=draft.lengths,
            pauses=draft.pauses,
            analytics=draft.analytics,
            series_ref=draft.series_ref if not dry_run else existing.series_ref,
            external_id=existing.external_id,
            sport_detail=draft.sport_detail,
        )

        if not dry_run:
            store.save_workout(slug, rebuilt)

        return {
            "workout_id": str(existing.id),
            "activity_id": activity_id,
            "date": str(existing.date),
            "sport": existing.sport,
            "pause_count_before": len(existing.pauses),
            "pause_count_after": len(rebuilt.pauses),
            "sport_detail_before": existing.sport_detail,
            "sport_detail_after": rebuilt.sport_detail,
            "written": not dry_run,
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _changed(result: dict) -> bool:
    return (
        result["pause_count_before"] != result["pause_count_after"]
        or result["sport_detail_before"] != result["sport_detail_after"]
    )


def reanalyze_athlete(
    cfg,
    *,
    store: StoreInterface,
    dry_run: bool,
    client: IntervalsClient | None = None,
) -> dict[str, int]:
    """Reanalyzes one athlete's intervals-synced workouts. Returns a summary
    tally. Never raises for anything short of a programming error -- a
    single bad workout is caught, logged, and reflected in the summary, same
    discipline as backend/app/sync.py's sync_athlete.

    `client`, when given, is used as-is and NOT closed by this function (the
    caller owns it -- e.g. tests injecting a mocked transport, mirroring
    sync_athlete's own `client=` parameter). When omitted, a real
    `IntervalsClient` is built from `cfg` and closed before returning.
    """
    summary = {"workouts_considered": 0, "changed": 0, "unchanged": 0, "failed": 0}

    try:
        store.load_athlete(cfg.slug)
    except FileNotFoundError:
        # FileStore.list_workouts silently returns [] for an unknown slug
        # (no directory) rather than raising -- check the profile explicitly
        # first so an unknown athlete is a logged failure, not silent
        # no-op, mirroring backend/app/sync.py's sync_athlete.
        _log("error", "reanalyze.unknown_athlete", athlete=cfg.slug)
        summary["failed"] += 1
        return summary

    workouts = store.list_workouts(cfg.slug)
    synced = [w for w in workouts if w.external_id and w.external_id.startswith("intervals:")]
    _log("info", "athlete synced workouts found", athlete=cfg.slug, count=len(synced), dry_run=dry_run)

    owns_client = client is None
    if client is None:
        client = IntervalsClient(cfg.intervals_athlete_id, cfg.api_key)

    try:
        for workout in synced:
            summary["workouts_considered"] += 1
            try:
                result = _reanalyze_workout(
                    workout, client=client, store=store, slug=cfg.slug, dry_run=dry_run
                )
            except Exception as exc:  # noqa: BLE001 - one bad workout must not abort the run
                _log(
                    "error",
                    "reanalyze failed",
                    athlete=cfg.slug,
                    workout_id=str(workout.id),
                    external_id=workout.external_id,
                    error=str(exc),
                )
                summary["failed"] += 1
                continue

            _log("info", "reanalyze:dry-run" if dry_run else "reanalyze:written", athlete=cfg.slug, **result)
            if _changed(result):
                summary["changed"] += 1
            else:
                summary["unchanged"] += 1
        return summary
    finally:
        if owns_client:
            client.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Re-download + re-parse intervals.icu-synced workouts, updating them in place."
    )
    parser.add_argument(
        "--athlete", default=None, help="only this slug (default: every INTERVALS_SYNC_CONFIG slug)"
    )
    parser.add_argument(
        "--athletes-dir", default="athletes", help="FileStore root (only used with --store file)"
    )
    parser.add_argument(
        "--store", choices=("file", "db"), default="file", help="StoreInterface backend (default: file)"
    )
    parser.add_argument(
        "--database-url", default=None, help="Supabase DSN (default: $DATABASE_URL; only for --store db)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would change; write nothing (no raw-file/series-sidecar writes either)",
    )
    args = parser.parse_args(argv)

    try:
        configs = load_sync_config()
    except SyncConfigError as exc:
        _log("error", "missing/invalid INTERVALS_SYNC_CONFIG", error=str(exc))
        return 1
    configs_by_slug = {cfg.slug: cfg for cfg in configs}

    if args.store == "file":
        store: StoreInterface = FileStore(base_dir=Path(args.athletes_dir))
    else:
        database_url = args.database_url or os.environ.get("DATABASE_URL")
        if not database_url:
            _log("error", "missing --database-url / DATABASE_URL (required with --store db)")
            return 1
        # Imported here (not at module top) so --store file needs neither
        # psycopg nor the [db] extra installed.
        from swim_coach.store_db import DbStore

        store = DbStore(dsn=database_url)

    slugs = [args.athlete] if args.athlete else sorted(configs_by_slug)

    exit_code = 0
    grand_total = {
        "workouts_considered": 0,
        "changed": 0,
        "unchanged": 0,
        "failed": 0,
        "skipped_no_config": 0,
    }

    for slug in slugs:
        cfg = configs_by_slug.get(slug)
        if cfg is None:
            _log("error", "no INTERVALS_SYNC_CONFIG entry for athlete", athlete=slug)
            grand_total["skipped_no_config"] += 1
            exit_code = 1
            continue

        summary = reanalyze_athlete(cfg, store=store, dry_run=args.dry_run)
        for key in ("workouts_considered", "changed", "unchanged", "failed"):
            grand_total[key] += summary[key]
        if summary["failed"]:
            exit_code = 1

    _log("info", "reanalyze complete", dry_run=args.dry_run, athletes=slugs, totals=grand_total)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
