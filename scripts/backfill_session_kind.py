"""One-time backfill of `Session.kind` on live week plans (drafts are never touched).

Sessions without an explicit `kind` get a PROPOSED one from their purpose/title
(`swim_coach.session_kind_backfill.propose_kind`): race, warmup, or nothing (left untagged = workout).
Sessions that already carry a kind are skipped, so re-running is idempotent.

Default is a DRY RUN that prints a table; `--apply` saves only the changed weeks (via the store's
week save, so validation runs) and prints a summary.

Usage:
    python scripts/backfill_session_kind.py [--store file --athletes-dir athletes] [--athlete SLUG ...]
    DATABASE_URL=... python scripts/backfill_session_kind.py --store db [--apply]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from swim_coach.session_kind_backfill import propose_kind
from swim_coach.store import FileStore, StoreInterface


def _slugs(store: StoreInterface, args: argparse.Namespace) -> list[str]:
    if args.athlete:
        return sorted(args.athlete)
    if isinstance(store, FileStore):
        return sorted(p.name for p in Path(args.athletes_dir).iterdir() if p.is_dir())
    with store._connect() as conn, conn.cursor() as cur:  # noqa: SLF001 - one-off ops script
        cur.execute("select slug from athletes order by slug")
        return [row["slug"] for row in cur.fetchall()]


def backfill(store: StoreInterface, slugs: list[str], *, apply: bool) -> list[dict]:
    """Rows `{slug, iso_week, date, sport, kind, purpose}` for every proposed change; writes the
    changed weeks when `apply`."""
    rows: list[dict] = []
    for slug in slugs:
        for iso_week in store.list_week_ids(slug):
            week = store.load_week(slug, iso_week)
            if week is None:
                continue
            changed = False
            for s in week.sessions:
                if s.kind is not None:
                    continue
                kind = propose_kind(s.purpose, s.title)
                if kind is None:
                    continue
                rows.append(
                    {"slug": slug, "iso_week": iso_week, "date": s.date.isoformat(), "sport": s.sport,
                     "kind": kind, "purpose": s.purpose}
                )
                if apply:
                    s.kind = kind
                    changed = True
            if changed:
                store.save_week(slug, week)
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", choices=("file", "db"), default="file")
    ap.add_argument("--athletes-dir", default="athletes")
    ap.add_argument("--database-url", default=None)
    ap.add_argument("--athlete", action="append", help="only this slug (repeatable)")
    ap.add_argument("--apply", action="store_true", help="write the proposed kinds (default: dry run)")
    args = ap.parse_args(argv)

    if args.store == "file":
        store: StoreInterface = FileStore(base_dir=Path(args.athletes_dir))
    else:
        dsn = args.database_url or os.environ.get("DATABASE_URL")
        if not dsn:
            print("missing --database-url / DATABASE_URL", file=sys.stderr)
            return 1
        from swim_coach.store_db import DbStore

        store = DbStore(dsn=dsn)

    rows = backfill(store, _slugs(store, args), apply=args.apply)
    for r in rows:
        print(f"{r['slug']:<12} {r['iso_week']:<9} {r['date']} {r['sport']:<10} {r['kind']:<7} {r['purpose'][:60]}")
    verb = "applied" if args.apply else "proposed (dry run; pass --apply to write)"
    print(f"{len(rows)} session kind(s) {verb}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
