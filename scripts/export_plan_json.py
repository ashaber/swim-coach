#!/usr/bin/env python3
"""Export an athlete's plan tree (profile, events, macro, all weeks) to JSON
for the read-only PWA in web/ to consume.

Run from the repo root, as a prebuild step for the web app:

    python scripts/export_plan_json.py --out web/public/data

Writes one `<slug>.json` per exported athlete plus an `index.json` listing
`[{"slug": ..., "name": ...}]` for every athlete found. Faithful to the
pydantic models: dates and UUIDs are serialized as strings (via
`model_dump(mode="json")`, same as `FileStore`'s own YAML dump helper) so
the JSON is exactly what the models validated, just re-encoded.

With no `--athlete` given, every slug under `--base-dir` that has a
profile.yaml is exported. `--athlete` may be repeated to export a subset.

Exit codes:
  0 - export succeeded (including the case where base_dir has no athletes
      yet -- an empty index.json is written, not an error).
  1 - a named --athlete doesn't exist, or an athlete tree fails to
      validate while loading.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from swim_coach.store import FileStore


def discover_slugs(base_dir: Path) -> list[str]:
    """Every subdirectory of `base_dir` that has a profile.yaml, sorted."""
    if not base_dir.exists():
        return []
    return sorted(
        p.name for p in base_dir.iterdir() if p.is_dir() and (p / "profile.yaml").exists()
    )


def _iso_weeks_on_disk(base_dir: Path, slug: str) -> list[str]:
    weeks_dir = base_dir / slug / "plan" / "weeks"
    if not weeks_dir.exists():
        return []
    return sorted(p.stem for p in weeks_dir.glob("*.yaml"))


def export_athlete(store: FileStore, slug: str) -> dict:
    """Load one athlete's full tree and return a single JSON-able dict.

    Weeks are sorted by iso_week (lexicographic sort matches chronological
    order for the "YYYY-Wnn" format). Missing macro is `None`, not an
    error -- an athlete may not have one scaffolded yet.
    """
    athlete = store.load_athlete(slug)
    events = store.load_events(slug)
    macro = store.load_macro(slug)
    iso_weeks = _iso_weeks_on_disk(store.base_dir, slug)
    weeks = [store.load_week(slug, iso_week) for iso_week in iso_weeks]

    return {
        "slug": slug,
        "name": athlete.name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "athlete": athlete.model_dump(mode="json"),
        "events": [event.model_dump(mode="json") for event in events],
        "macro": macro.model_dump(mode="json") if macro is not None else None,
        "weeks": [week.model_dump(mode="json") for week in weeks],
    }


def build_index(store: FileStore, slugs: list[str]) -> list[dict]:
    return [{"slug": slug, "name": store.load_athlete(slug).name} for slug in slugs]


def export_all(base_dir: Path, out_dir: Path, athletes: list[str] | None = None) -> dict:
    """Export `athletes` (default: every slug under base_dir) to `out_dir`.

    Writes `<slug>.json` per athlete plus `index.json`. Returns a summary
    dict `{"exported": [...slugs...], "out_dir": str}`.
    """
    store = FileStore(base_dir=base_dir)
    slugs = athletes if athletes is not None else discover_slugs(base_dir)

    out_dir.mkdir(parents=True, exist_ok=True)

    index = build_index(store, slugs)
    (out_dir / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")

    for slug in slugs:
        data = export_athlete(store, slug)
        (out_dir / f"{slug}.json").write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8"
        )

    return {"exported": slugs, "out_dir": str(out_dir)}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", default="athletes", help="athlete data root (default: athletes)")
    parser.add_argument(
        "--out", default="web/public/data", help="output directory (default: web/public/data)"
    )
    parser.add_argument(
        "--athlete",
        action="append",
        dest="athletes",
        help="slug to export (repeatable); default: every athlete under --base-dir",
    )
    args = parser.parse_args(argv)

    base_dir = Path(args.base_dir)
    out_dir = Path(args.out)

    if args.athletes:
        missing = [slug for slug in args.athletes if not (base_dir / slug / "profile.yaml").exists()]
        if missing:
            print(json.dumps({"error": "no such athlete(s)", "slugs": missing}))
            return 1

    try:
        result = export_all(base_dir, out_dir, args.athletes)
    except Exception as exc:  # noqa: BLE001 - report, don't crash with a traceback
        print(json.dumps({"error": str(exc)}))
        return 1

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
