#!/usr/bin/env python3
"""One-shot file -> DB migration: copy the FileStore tree into Supabase.

Reads the `athletes/` YAML/Markdown tree via FileStore and writes every entity
through DbStore. **Idempotent** (all writes upsert), so it is safe to re-run --
re-running reconciles the DB to the current file tree.

SAFETY: this NEVER deletes files. The file tree stays the source of truth /
archive until the DB is validated and the backend is cut over (STORE_BACKEND=db).
There is no delete path in this script at all.

Usage:
    python scripts/migrate_files_to_db.py --database-url postgresql://... [--athlete renee]
    DATABASE_URL=postgresql://... python scripts/migrate_files_to_db.py --dry-run

Flags:
    --athlete SLUG     migrate only this athlete (default: every athlete under --athletes-dir)
    --athletes-dir DIR FileStore root (default: athletes)
    --database-url URL Supabase DSN (default: env DATABASE_URL). Ignored under --dry-run.
    --dry-run          report what WOULD be written; touch nothing (no DB needed)

Exit codes: 0 = success, 1 = a required arg/target missing or a write failed.

Structured JSON logging to stdout (per the global standard).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from swim_coach.store import FileStore


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


def _iso_week_from_path(path: Path) -> str:
    """Week-plan filename stem is the ISO week (e.g. '2026-W28.yaml')."""
    return path.stem


def _day_from_coach_text_path(path: Path):
    from datetime import date

    return date.fromisoformat(path.stem)


def _athlete_slugs(base_dir: Path, only: str | None) -> list[str]:
    if only:
        return [only]
    if not base_dir.exists():
        return []
    return sorted(p.name for p in base_dir.iterdir() if p.is_dir())


def _count_athlete_entities(file_store: FileStore, slug: str, base_dir: Path) -> dict[str, int]:
    """Enumerate what exists on disk for `slug` (used by both dry-run reporting
    and the real migration loop)."""
    athlete_dir = base_dir / slug
    weeks_dir = athlete_dir / "plan" / "weeks"
    coach_texts_dir = athlete_dir / "logs" / "coach-texts"
    return {
        "events": len(file_store.load_events(slug)),
        "macro": 1 if file_store.load_macro(slug) is not None else 0,
        "weeks": len(sorted(weeks_dir.glob("*.yaml"))) if weeks_dir.exists() else 0,
        "workouts": len(file_store.list_workouts(slug)),
        "wellness": len(file_store.list_wellness(slug)),
        "coach_texts": len(sorted(coach_texts_dir.glob("*.md"))) if coach_texts_dir.exists() else 0,
    }


def _migrate_athlete(file_store: FileStore, db_store, slug: str, base_dir: Path) -> dict[str, int]:
    """Copy one athlete's entire tree into the DB via upserts. Athlete row is
    written FIRST so child FKs resolve."""
    athlete_dir = base_dir / slug
    written: dict[str, int] = {
        "athlete": 0,
        "events": 0,
        "macro": 0,
        "weeks": 0,
        "workouts": 0,
        "wellness": 0,
        "coach_texts": 0,
    }

    athlete = file_store.load_athlete(slug)  # raises FileNotFoundError if missing
    db_store.save_athlete(athlete)
    written["athlete"] = 1

    events = file_store.load_events(slug)
    if events:
        db_store.save_events(slug, events)
        written["events"] = len(events)

    macro = file_store.load_macro(slug)
    if macro is not None:
        db_store.save_macro(slug, macro)
        written["macro"] = 1

    weeks_dir = athlete_dir / "plan" / "weeks"
    if weeks_dir.exists():
        for week_path in sorted(weeks_dir.glob("*.yaml")):
            week = file_store.load_week(slug, _iso_week_from_path(week_path))
            if week is not None:
                db_store.save_week(slug, week)
                written["weeks"] += 1

    for workout in file_store.list_workouts(slug):
        db_store.save_workout(slug, workout)
        written["workouts"] += 1

    for wellness in file_store.list_wellness(slug):
        db_store.save_wellness(slug, wellness)
        written["wellness"] += 1

    coach_texts_dir = athlete_dir / "logs" / "coach-texts"
    if coach_texts_dir.exists():
        for ct_path in sorted(coach_texts_dir.glob("*.md")):
            day = _day_from_coach_text_path(ct_path)
            body = ct_path.read_text(encoding="utf-8")
            # force=True: idempotent re-run overwrites the verbatim body with
            # the current file (the file remains source of truth).
            db_store.save_coach_text(slug, day, body, force=True)
            written["coach_texts"] += 1

    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate the FileStore tree into Supabase.")
    parser.add_argument("--athlete", default=None, help="only this slug (default: all)")
    parser.add_argument("--athletes-dir", default="athletes", help="FileStore root")
    parser.add_argument("--database-url", default=None, help="Supabase DSN (default: $DATABASE_URL)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be written; touch nothing (no DB connection made)",
    )
    args = parser.parse_args(argv)

    base_dir = Path(args.athletes_dir)
    file_store = FileStore(base_dir=base_dir)
    slugs = _athlete_slugs(base_dir, args.athlete)

    if not slugs:
        _log("error", "no athletes to migrate", athletes_dir=str(base_dir), athlete=args.athlete)
        return 1

    if args.dry_run:
        total = {}
        for slug in slugs:
            try:
                counts = _count_athlete_entities(file_store, slug, base_dir)
            except FileNotFoundError as exc:
                _log("error", "athlete has no profile.yaml", athlete=slug, error=str(exc))
                return 1
            _log("info", "dry-run: would migrate", athlete=slug, would_write=counts)
            for k, v in counts.items():
                total[k] = total.get(k, 0) + v
        _log("info", "dry-run complete -- nothing written", athletes=slugs, totals=total)
        return 0

    database_url = args.database_url or os.environ.get("DATABASE_URL")
    if not database_url:
        _log("error", "missing --database-url / DATABASE_URL (required unless --dry-run)")
        return 1

    # Imported here (not at module top) so --dry-run needs neither psycopg nor
    # the [db] extra installed.
    from swim_coach.store_db import DbStore

    db_store = DbStore(dsn=database_url)

    grand_total: dict[str, int] = {}
    for slug in slugs:
        try:
            written = _migrate_athlete(file_store, db_store, slug, base_dir)
        except FileNotFoundError as exc:
            _log("error", "athlete has no profile.yaml", athlete=slug, error=str(exc))
            return 1
        except Exception as exc:  # noqa: BLE001 - report-and-fail on any write error
            _log("error", "migration failed", athlete=slug, error=str(exc))
            return 1
        _log("info", "migrated athlete", athlete=slug, written=written)
        for k, v in written.items():
            grand_total[k] = grand_total.get(k, 0) + v

    _log("info", "migration complete", athletes=slugs, totals=grand_total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
