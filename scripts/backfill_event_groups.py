"""One-time backfill: tag existing events as an event group (stage race / double header / omnium).

Explicit arguments only (no name sniffing): you say which event and which race dates. Member
events for dates that have none yet are created as copies of the source event. Default is a DRY
RUN that prints what would change; `--apply` saves (via the store's `save_events`).

Examples (prod uses `--store db` with DATABASE_URL; events already hold the groups in their JSONB,
so NO SQL migration is involved):
    python scripts/backfill_event_groups.py --athlete andrew \\
        --group "Masters Cyclocross Series - Peak Weekend" --type double_header \\
        --source-event "Masters Cyclocross Series - Peak Weekend" --race-dates 2026-10-17,2026-10-18
    python scripts/backfill_event_groups.py --athlete andrew --group "Halloween Weekend" \\
        --type double_header --source-event "Halloween Weekend" --race-dates 2026-10-31,2026-11-01
    # Renee's Greece event: stage dates are not stored on the event, so they are required here
    python scripts/backfill_event_groups.py --athlete renee --group "UltraSwim Greece" \\
        --type stage_race --source-event "<exact event name>" --race-dates <d1>,<d2>,<d3>,<d4> \\
        [--peak-date <date>]   # default: earliest race

Re-running is idempotent (members matched by date; the group is replaced, not duplicated).
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import date
from pathlib import Path

from swim_coach.event_groups import set_group
from swim_coach.models import Event
from swim_coach.store import FileStore, StoreInterface


def plan_group(
    events: list[Event],
    *,
    group_name: str,
    group_type: str,
    source_event: str,
    race_dates: list[date],
    peak_date: date | None = None,
) -> tuple[list[Event], list[str]]:
    """`(new events list, human-readable change lines)`. Raises ValueError on bad input."""
    sources = [e for e in events if e.name == source_event]
    if len(sources) != 1:
        raise ValueError(f"expected exactly one event named {source_event!r}, found {len(sources)}")
    source = sources[0]
    if source.event_date not in race_dates:
        raise ValueError(f"--race-dates must include the source event's own date {source.event_date}")
    if peak_date is not None and peak_date not in race_dates:
        raise ValueError("--peak-date must be one of --race-dates")
    existing_gid = source.group_id
    lines: list[str] = []
    out = list(events)
    member_ids: list[uuid.UUID] = []
    for d in sorted(set(race_dates)):
        member = next(
            (e for e in out if e.event_date == d and e.primary_sport == source.primary_sport
             and (e.id == source.id or (existing_gid is not None and e.group_id == existing_gid))),
            None,
        )
        if member is None:
            member = source.model_copy(
                update={"id": uuid.uuid4(), "event_date": d, "name": f"{source.name} — {d.isoformat()}",
                        "group_id": None, "group_name": None, "group_type": None, "group_peak": False}
            )
            out.append(member)
            lines.append(f"  create member event {member.name!r} on {d} (copy of {source.name!r})")
        else:
            lines.append(f"  use existing event {member.name!r} on {d}")
        member_ids.append(member.id)
    peak_id = next((m for m in member_ids if next(e for e in out if e.id == m).event_date == peak_date), None) if peak_date else None
    _gid, out = set_group(
        out, name=group_name, group_type=group_type, member_ids=member_ids, peak_event_id=peak_id, group_id=existing_gid
    )
    lines.append(f"  group {group_name!r} ({group_type}): {len(member_ids)} races, peak = {peak_date or 'earliest race'}")
    return out, lines


def _store(args: argparse.Namespace) -> StoreInterface:
    if args.store == "file":
        return FileStore(base_dir=Path(args.athletes_dir))
    dsn = args.database_url or os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("missing --database-url / DATABASE_URL")
    from swim_coach.store_db import DbStore

    return DbStore(dsn=dsn)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", choices=("file", "db"), default="file")
    ap.add_argument("--athletes-dir", default="athletes")
    ap.add_argument("--database-url", default=None)
    ap.add_argument("--athlete", required=True, help="athlete slug")
    ap.add_argument("--group", required=True, help="group name")
    ap.add_argument("--type", required=True, choices=("stage_race", "double_header", "omnium"))
    ap.add_argument("--source-event", required=True, help="exact name of the existing event to group")
    ap.add_argument("--race-dates", required=True, help="comma-separated ISO dates of every race")
    ap.add_argument("--peak-date", default=None, help="taper-peak race date (default earliest)")
    ap.add_argument("--apply", action="store_true", help="write the change (default: dry run)")
    args = ap.parse_args(argv)

    store = _store(args)
    try:
        events, lines = plan_group(
            store.load_events(args.athlete),
            group_name=args.group,
            group_type=args.type,
            source_event=args.source_event,
            race_dates=[date.fromisoformat(d) for d in args.race_dates.split(",")],
            peak_date=date.fromisoformat(args.peak_date) if args.peak_date else None,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{args.athlete}:")
    print("\n".join(lines))
    if args.apply:
        store.save_events(args.athlete, events)
        print("applied")
    else:
        print("dry run; pass --apply to write")
    return 0


if __name__ == "__main__":
    sys.exit(main())
