#!/usr/bin/env python3
"""Backfill device temperature (avg/min/max degC) onto already-synced workouts.

Reads the device temperatures (`average_temp`/`min_temp`/`max_temp`, degC) from one intervals.icu
activity-list call per athlete (`IntervalsClient.list_activities`; no FIT downloads) and sets ONLY `avg_temp_c`/`min_temp_c`/
`max_temp_c` on the existing row. Nothing else is touched, nothing is deleted. Rows that already
carry a temperature, and rows with no `intervals:` external_id (manual/coach-text logs have no
activity row to match), are skipped.

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
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from swim_coach.models import Workout  # noqa: E402
from swim_coach.store import FileStore, StoreInterface  # noqa: E402

from app.sync import IntervalsClient, SyncConfigError, load_sync_config  # noqa: E402


def _log(level: str, msg: str, **meta: object) -> None:
    print(json.dumps({"level": level, "msg": msg, **meta, "ts": datetime.now(timezone.utc).isoformat()}))


def _needs_temperature(w: Workout) -> bool:
    return bool(w.external_id and w.external_id.startswith("intervals:")) and (
        w.avg_temp_c is None and w.min_temp_c is None and w.max_temp_c is None
    )


_TEMP_KEYS = {"avg_temp_c": "average_temp", "min_temp_c": "min_temp", "max_temp_c": "max_temp"}


def _temps_from_activity(row: dict) -> dict[str, float | None]:
    """Device temperatures (degC) from an intervals.icu activity-list row. Only the three device
    fields are read; the paid-tier weather/feels-like/wind fields are deliberately ignored."""
    out: dict[str, float | None] = {}
    for field, key in _TEMP_KEYS.items():
        v = row.get(key)
        out[field] = float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    return out


def backfill(store: StoreInterface, slug: str, client: IntervalsClient, *, apply: bool) -> dict[str, int]:
    """One athlete, one activity-list call covering all their candidate dates. A workout matches its
    row by `external_id` ("intervals:<activity id>"). Returns tallies; one bad row never aborts."""
    tally = {"considered": 0, "updated": 0, "no_temperature_in_file": 0, "not_found": 0, "failed": 0}
    todo = [w for w in store.list_workouts(slug) if _needs_temperature(w)]
    if not todo:
        return tally
    tally["considered"] = len(todo)
    oldest = min(w.date for w in todo) - timedelta(days=1)  # a workout's date can differ by a day from UTC
    newest = max(w.date for w in todo) + timedelta(days=1)
    try:
        rows = {str(r["id"]): r for r in client.list_activities(oldest=oldest, newest=newest) if "id" in r}
    except Exception as exc:  # noqa: BLE001 - nothing to match against; report and stop this athlete
        _log("error", "activity list failed", athlete=slug, error=str(exc))
        tally["failed"] = len(todo)
        return tally
    for w in todo:
        row = rows.get(w.external_id.removeprefix("intervals:"))
        if row is None:
            tally["not_found"] += 1
            continue
        temps = _temps_from_activity(row)
        if all(v is None for v in temps.values()):
            tally["no_temperature_in_file"] += 1
            continue
        try:
            if apply:
                store.save_workout(slug, w.model_copy(update=temps))
        except Exception as exc:  # noqa: BLE001 - one bad workout must not abort the run
            _log("error", "backfill failed", athlete=slug, workout_id=str(w.id), error=str(exc))
            tally["failed"] += 1
            continue
        tally["updated"] += 1
        _log("info", "backfill:written" if apply else "backfill:dry-run",
             athlete=slug, workout_id=str(w.id), date=str(w.date), **temps)
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
