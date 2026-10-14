"""Seed an athlete's reusable race-day checklist template from a JSON file.

Default is a DRY RUN: validates the file and prints what would change. `--apply` writes the
template onto the athlete via the store. Existing per-race plans are left untouched unless
`--rederive-plans` is given: then each plan whose timeline was never hand-edited
(`timeline_edited` false) gets the template's timeline copied in; hand-edited plans are skipped.

Usage:
    python scripts/seed_race_checklist.py --athlete andrew [--file athletes/andrew/race-checklist-template.json]
    python scripts/seed_race_checklist.py --athlete andrew --apply            # file store (athletes/)
    python scripts/seed_race_checklist.py --athlete andrew --rederive-plans   # dry run: which plans' timelines would refresh
    python scripts/seed_race_checklist.py --athlete andrew --apply --rederive-plans
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
from swim_coach.race_day import reset_timeline
from swim_coach.store import FileStore, StoreInterface


def load_template(path: Path) -> RaceChecklistTemplate:
    return RaceChecklistTemplate(**json.loads(path.read_text()))


def seed(
    store: StoreInterface, slug: str, template: RaceChecklistTemplate, *, apply: bool, rederive_plans: bool = False
) -> dict:
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
    if rederive_plans:
        stale = [p for p in athlete.race_day_plans if not p.timeline_edited]
        summary["plans_rederived"] = [str(p.date) for p in stale]
        summary["plans_skipped_edited"] = [str(p.date) for p in athlete.race_day_plans if p.timeline_edited]
    if apply:
        athlete.race_checklist_template = template
        if rederive_plans:
            for plan in athlete.race_day_plans:
                if not plan.timeline_edited:
                    reset_timeline(plan, template)
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
    parser.add_argument(
        "--rederive-plans", action="store_true",
        help="also re-copy the template timeline into race plans with no manual timeline edits",
    )
    args = parser.parse_args(argv)

    path = Path(args.file) if args.file else Path(args.athletes_dir) / args.athlete / "race-checklist-template.json"
    try:
        template = load_template(path)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        print(json.dumps({"error": f"cannot load template {path}: {exc}"}))
        return 1
    try:
        summary = seed(_make_store(args), args.athlete, template, apply=args.apply, rederive_plans=args.rederive_plans)
    except FileNotFoundError as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps({**summary, "dry_run": not args.apply}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
