"""Seed an athlete's reusable race-day checklist template from a JSON file.

Default is a DRY RUN: validates the file and prints what would change. `--apply` writes the
template onto the athlete via the store (existing per-race plans are left untouched).

Usage:
    python scripts/seed_race_checklist.py --athlete andrew [--file athletes/andrew/race-checklist-template.json]
    python scripts/seed_race_checklist.py --athlete andrew --apply            # file store (athletes/)
    DATABASE_URL=... python scripts/seed_race_checklist.py --athlete andrew --store db --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from pydantic import ValidationError
from swim_coach.models import RaceChecklistTemplate
from swim_coach.store import FileStore, StoreInterface


def load_template(path: Path) -> RaceChecklistTemplate:
    return RaceChecklistTemplate(**json.loads(path.read_text()))


def seed(store: StoreInterface, slug: str, template: RaceChecklistTemplate, *, apply: bool) -> dict:
    """Returns a summary; writes only when `apply`."""
    athlete = store.load_athlete(slug)
    existing = athlete.race_checklist_template
    summary = {
        "athlete": slug,
        "sections": len(template.sections),
        "items": sum(len(s.items) for s in template.sections),
        "timeline_entries": len(template.timeline),
        "replaces_existing": existing is not None,
        "applied": False,
    }
    if apply:
        athlete.race_checklist_template = template
        store.save_athlete(athlete)
        summary["applied"] = True
    return summary


def _make_store(args: argparse.Namespace) -> StoreInterface:
    if args.store == "db":
        from swim_coach.store_db import DbStore

        return DbStore(dsn=os.environ["DATABASE_URL"])
    return FileStore(base_dir=Path(args.athletes_dir))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--athlete", required=True)
    parser.add_argument("--file", help="template JSON (default: athletes/<slug>/race-checklist-template.json)")
    parser.add_argument("--store", choices=["file", "db"], default="file")
    parser.add_argument("--athletes-dir", default="athletes")
    parser.add_argument("--apply", action="store_true", help="write the template (default: dry run)")
    args = parser.parse_args(argv)

    path = Path(args.file) if args.file else Path(args.athletes_dir) / args.athlete / "race-checklist-template.json"
    try:
        template = load_template(path)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        print(json.dumps({"error": f"cannot load template {path}: {exc}"}))
        return 1
    try:
        summary = seed(_make_store(args), args.athlete, template, apply=args.apply)
    except FileNotFoundError as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps({**summary, "dry_run": not args.apply}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
