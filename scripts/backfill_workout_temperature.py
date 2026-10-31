#!/usr/bin/env python3
"""Backfill device temperature (avg/min/max degC) onto already-synced workouts.

Re-downloads each intervals.icu-synced workout's ORIGINAL .fit (`IntervalsClient.download_fit`,
never the lossy re-encode), parses it with `parse_fit`, and sets ONLY `avg_temp_c`/`min_temp_c`/
`max_temp_c` on the existing row. Nothing else is touched, nothing is deleted. Rows that already
carry a temperature, and rows with no `intervals:` external_id (manual/coach-text logs have no
file to re-download), are skipped.

DRY-RUN BY DEFAULT: without `--apply` it reports what would change and writes nothing.

Usage:
    INTERVALS_SYNC_CONFIG=... python scripts/backfill_workout_temperature.py
    INTERVALS_SYNC_CONFIG=... python scripts/backfill_workout_temperature.py --athlete renee --apply
    ... --store db --database-url postgresql://...     (default store: file, under --athletes-dir)

Exit codes: 0 = clean, 1 = at least one athlete/workout failed. Structured JSON logs to stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from swim_coach.models import Workout  # noqa: E402
from swim_coach.parse_files import PARSERS_BY_EXTENSION  # noqa: E402
from swim_coach.store import FileStore, StoreInterface  # noqa: E402

from app.sync import IntervalsClient, SyncConfigError, load_sync_config  # noqa: E402


def _log(level: str, msg: str, **meta: object) -> None:
    print(json.dumps({"level": level, "msg": msg, **meta, "ts": datetime.now(timezone.utc).isoformat()}))


def _needs_temperature(w: Workout) -> bool:
    return bool(w.external_id and w.external_id.startswith("intervals:")) and (
        w.avg_temp_c is None and w.min_temp_c is None and w.max_temp_c is None
    )


def _temps_from_fit(client: IntervalsClient, activity_id: str) -> dict[str, float | None]:
    with tempfile.TemporaryDirectory(prefix="swimcoach-temp-") as tmp:
        path = Path(tmp) / f"{activity_id}.fit"
        path.write_bytes(client.download_fit(activity_id))
        draft = PARSERS_BY_EXTENSION[".fit"](path)
    return {"avg_temp_c": draft.avg_temp_c, "min_temp_c": draft.min_temp_c, "max_temp_c": draft.max_temp_c}


def backfill(store: StoreInterface, slug: str, client: IntervalsClient, *, apply: bool) -> dict[str, int]:
    """One athlete. Returns tallies; a single bad workout is logged and counted, never fatal."""
    tally = {"considered": 0, "updated": 0, "no_temperature_in_file": 0, "failed": 0}
    for w in store.list_workouts(slug):
        if not _needs_temperature(w):
            continue
        tally["considered"] += 1
        activity_id = w.external_id.removeprefix("intervals:")
        try:
            temps = _temps_from_fit(client, activity_id)
            if all(v is None for v in temps.values()):
                tally["no_temperature_in_file"] += 1
                continue
            if apply:
                store.save_workout(slug, w.model_copy(update=temps))
            tally["updated"] += 1
            _log("info", "backfill:written" if apply else "backfill:dry-run",
                 athlete=slug, workout_id=str(w.id), date=str(w.date), **temps)
        except Exception as exc:  # noqa: BLE001 - one bad workout must not abort the run
            _log("error", "backfill failed", athlete=slug, workout_id=str(w.id), error=str(exc))
            tally["failed"] += 1
    return tally


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--athlete", default=None, help="only this slug (default: every sync-config slug)")
    ap.add_argument("--athletes-dir", default="athletes")
    ap.add_argument("--store", choices=("file", "db"), default="file")
    ap.add_argument("--database-url", default=None)
    ap.add_argument("--apply", action="store_true", help="write the temperatures (default: dry-run)")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        configs = {c.slug: c for c in load_sync_config()}
    except SyncConfigError as exc:
        _log("error", "missing/invalid INTERVALS_SYNC_CONFIG", error=str(exc))
        return 1

    if args.store == "file":
        store: StoreInterface = FileStore(base_dir=Path(args.athletes_dir))
    else:
        url = args.database_url or os.environ.get("DATABASE_URL")
        if not url:
            _log("error", "missing --database-url / DATABASE_URL (required with --store db)")
            return 1
        from swim_coach.store_db import DbStore

        store = DbStore(dsn=url)

    exit_code = 0
    for slug in [args.athlete] if args.athlete else sorted(configs):
        cfg = configs.get(slug)
        if cfg is None:
            _log("error", "no INTERVALS_SYNC_CONFIG entry for athlete", athlete=slug)
            exit_code = 1
            continue
        client = IntervalsClient(cfg.intervals_athlete_id, cfg.api_key)
        try:
            tally = backfill(store, slug, client, apply=args.apply)
        finally:
            client.close()
        _log("info", "backfill athlete complete", athlete=slug, apply=args.apply, **tally)
        if tally["failed"]:
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
