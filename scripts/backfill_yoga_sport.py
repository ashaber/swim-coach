"""One-time backfill: yoga/pilates/stretching workouts stored as `strength` become `recovery`.

Before `parse_files._fit_sport` mapped `training/yoga` (and pilates, flexibility_training,
breathing) to `recovery`, every Garmin "training" activity was stored as `strength`. For each such
workout this re-sports it, drops a plan link that points at a non-recovery session (the +-1 day
window had matched the neighbouring strength day), matches it again against the plan, and re-runs
the analyzer (which re-stamps the derived kind). Workouts already linked to a recovery session
keep that link. Idempotent: a second run finds nothing to do.

It also LISTS (never changes) older `cross_train` workouts whose detail is cycling, which predate
the cycling -> bike mapping, so the owner can decide about them separately.

Default is a DRY RUN; `--apply` saves the changed workouts.

Usage:
    python scripts/backfill_yoga_sport.py [--store file --athletes-dir athletes] [--athlete SLUG ...]
    DATABASE_URL=... python scripts/backfill_yoga_sport.py --store db [--apply]
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import timedelta
from pathlib import Path

from swim_coach.analysis import build_analysis_context
from swim_coach.models import Session, Workout
from swim_coach.sport_backfill import legacy_cycling_cross_train, resport_and_rematch, yoga_resport_candidates
from swim_coach.store import FileStore, StoreInterface


def _slugs(store: StoreInterface, args: argparse.Namespace) -> list[str]:
    if args.athlete:
        return sorted(args.athlete)
    if isinstance(store, FileStore):
        return sorted(p.name for p in Path(args.athletes_dir).iterdir() if p.is_dir())
    with store._connect() as conn, conn.cursor() as cur:  # noqa: SLF001 - one-off ops script
        cur.execute("select slug from athletes order by slug")
        return [row["slug"] for row in cur.fetchall()]


def _sessions_around(store: StoreInterface, slug: str, workout: Workout) -> list[Session]:
    sessions: list[Session] = []
    seen: set[str] = set()
    for delta in (-7, 0, 7):
        year, week, _ = (workout.date + timedelta(days=delta)).isocalendar()
        iso = f"{year}-W{week:02d}"
        if iso in seen:
            continue
        seen.add(iso)
        plan = store.load_week(slug, iso)
        if plan is not None:
            sessions.extend(plan.sessions)
    return sessions


def _reanalyzed(store: StoreInterface, slug: str, moved: Workout, sessions: list[Session]) -> Workout:
    session = next((s for s in sessions if s.id == moved.planned_session_id), None)
    series = store.load_series(slug, moved.id)
    ctx = build_analysis_context(store, slug, moved, session=session, series=series)  # also stamps kind
    return moved.model_copy(update={"analytics": moved.analyze(ctx)})


def _save(store: StoreInterface, slug: str, before: Workout, after: Workout) -> None:
    """Upsert `after`. DbStore keys on the id so the row updates in place; FileStore names the file
    by sport, so the superseded same-id file (this very record under its old sport) is replaced."""
    store.save_workout(slug, after)
    if isinstance(store, FileStore):
        directory = store._athlete_dir(slug) / "logs" / "workouts"  # noqa: SLF001 - one-off ops script
        old = directory / f"{before.date.isoformat()}-{before.sport}-{str(before.id)[:8]}.yaml"
        if old.exists():
            old.unlink()


def backfill(store: StoreInterface, slugs: list[str], *, apply: bool) -> dict[str, list[dict]]:
    """`{"changed": rows, "legacy_cross_train": rows}`; writes the changed workouts when `apply`."""
    changed: list[dict] = []
    legacy: list[dict] = []
    for slug in slugs:
        workouts = store.list_workouts(slug)
        for w in legacy_cycling_cross_train(workouts):
            legacy.append({"slug": slug, "date": w.date.isoformat(), "sport_detail": w.sport_detail, "id": str(w.id)})
        candidates = yoga_resport_candidates(workouts)
        ids = {w.id for w in candidates}
        settled = [w for w in workouts if w.id not in ids]  # as they stand after the backfill, growing
        for w in sorted(candidates, key=lambda x: x.date):
            sessions = _sessions_around(store, slug, w)
            moved = resport_and_rematch(w, sessions=sessions, others=settled)
            moved = _reanalyzed(store, slug, moved, sessions)
            settled.append(moved)
            changed.append(
                {"slug": slug, "date": w.date.isoformat(), "sport_detail": w.sport_detail, "id": str(w.id),
                 "link_before": str(w.planned_session_id) if w.planned_session_id else None,
                 "link_after": str(moved.planned_session_id) if moved.planned_session_id else None}
            )
            if apply:
                _save(store, slug, w, moved)
    return {"changed": changed, "legacy_cross_train": legacy}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", choices=("file", "db"), default="file")
    ap.add_argument("--athletes-dir", default="athletes")
    ap.add_argument("--database-url", default=None)
    ap.add_argument("--athlete", action="append", help="only this slug (repeatable)")
    ap.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
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

    result = backfill(store, _slugs(store, args), apply=args.apply)
    for r in result["changed"]:
        print(f"{r['slug']:<12} {r['date']} {r['sport_detail']:<24} link {r['link_before']} -> {r['link_after']}")
    verb = "re-sported to recovery" if args.apply else "would be re-sported to recovery (dry run; pass --apply to write)"
    print(f"{len(result['changed'])} workout(s) {verb}")
    print(f"{len(result['legacy_cross_train'])} legacy cross_train cycling workout(s) (listed only, never changed):")
    for r in result["legacy_cross_train"]:
        print(f"  {r['slug']:<12} {r['date']} {r['sport_detail']} {r['id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
