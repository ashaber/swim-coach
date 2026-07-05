"""Command-line entry point for the swim-coach engine.

Invocable as `python -m swim_coach.cli <command> ...` (or `python -m
swim_coach`, via `__main__.py`). Every command prints exactly one JSON
object to stdout and returns a process exit code: 0 on success, non-zero on
failure (errors are also JSON: `{"error": ..., ...}`), never a bare
traceback or HTML.

Skills/agents shell out to this module -- see ROADMAP.md "Engine CLI" --
and must never hand-compute zones/volumes/dates in chat; this is the only
place that logic runs.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

import yaml

from swim_coach.adapt import adapt_week
from swim_coach.load import (
    acute_chronic_ratio,
    compliance as compute_compliance,
    daily_loads,
    monotony,
    weekly_volume_m,
    wellness_trend,
)
from swim_coach.models import Event, Wellness, WeekPlan, Workout
from swim_coach.plan import generate_week, scaffold_macro
from swim_coach.store import FileStore
from swim_coach.zones import css_from_test, zone_table


def _iso_week(d: date) -> str:
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def parse_time_to_s(value: str) -> float:
    """Parse a CSS test time given as 'MM:SS[.f]' or plain seconds into seconds."""
    value = value.strip()
    if ":" in value:
        minutes_str, seconds_str = value.split(":", 1)
        return int(minutes_str) * 60 + float(seconds_str)
    return float(value)


def _load_yaml_file(path: Path) -> dict | list | None:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _error(message: str, **extra: object) -> int:
    print(json.dumps({"error": message, **extra}))
    return 1


def _error_from_exception(path: Path, exc: Exception) -> int:
    return _error(str(exc), file=str(path))


def _validate_dir(directory: Path, model_cls, label: str, counts: dict) -> int | None:
    """Validate every *.yaml file in `directory` against `model_cls`.

    Returns None on success (with counts[label] set), or an int exit code
    (from _error_from_exception) on the first failure.
    """
    count = 0
    if directory.exists():
        for path in sorted(directory.glob("*.yaml")):
            try:
                model_cls.model_validate(_load_yaml_file(path))
            except Exception as exc:  # noqa: BLE001 - report, don't crash
                return _error_from_exception(path, exc)
            count += 1
    counts[label] = count
    return None


def _cmd_validate(args: argparse.Namespace, store: FileStore) -> int:
    slug = args.athlete
    athlete_dir = store.base_dir / slug
    counts: dict[str, int] = {}

    try:
        store.load_athlete(slug)
        counts["athlete"] = 1
    except Exception as exc:  # noqa: BLE001
        return _error_from_exception(athlete_dir / "profile.yaml", exc)

    try:
        counts["events"] = len(store.load_events(slug))
    except Exception as exc:  # noqa: BLE001
        return _error_from_exception(athlete_dir / "events.yaml", exc)

    try:
        macro = store.load_macro(slug)
        counts["macro"] = 1 if macro is not None else 0
    except Exception as exc:  # noqa: BLE001
        return _error_from_exception(athlete_dir / "plan" / "macro.yaml", exc)

    rc = _validate_dir(athlete_dir / "plan" / "weeks", WeekPlan, "weeks", counts)
    if rc is not None:
        return rc
    rc = _validate_dir(athlete_dir / "logs" / "workouts", Workout, "workouts", counts)
    if rc is not None:
        return rc
    rc = _validate_dir(athlete_dir / "logs" / "wellness", Wellness, "wellness", counts)
    if rc is not None:
        return rc

    print(json.dumps({"athlete": slug, "counts": counts}))
    return 0


def _cmd_zones(args: argparse.Namespace, store: FileStore) -> int:
    slug = args.athlete
    try:
        athlete = store.load_athlete(slug)
    except Exception as exc:  # noqa: BLE001
        return _error_from_exception(store.base_dir / slug / "profile.yaml", exc)

    if bool(args.test_400) != bool(args.test_200):
        return _error("--test-400 and --test-200 must be provided together")

    if args.test_400 and args.test_200:
        try:
            t400 = parse_time_to_s(args.test_400)
            t200 = parse_time_to_s(args.test_200)
            css = css_from_test(t400, t200)
        except ValueError as exc:
            return _error(str(exc))
    else:
        if athlete.css_pace_s_per_100m is None:
            return _error("athlete has no css_pace_s_per_100m and no test times were given")
        css = athlete.css_pace_s_per_100m

    table = zone_table(css)

    if args.write:
        athlete.css_pace_s_per_100m = css
        athlete.zones = table
        store.save_athlete(athlete)

    print(json.dumps({"athlete": slug, "css_pace_s_per_100m": css, "zones": table}))
    return 0


def _find_event(events: list[Event], query: str) -> Event | None:
    """Match an event by UUID prefix (case-insensitive) or exact,
    case-insensitive name."""
    q = query.strip().lower()
    for event in events:
        if str(event.id).lower().startswith(q):
            return event
    for event in events:
        if event.name.strip().lower() == q:
            return event
    return None


def _cmd_scaffold_macro(args: argparse.Namespace, store: FileStore) -> int:
    slug = args.athlete
    try:
        athlete = store.load_athlete(slug)
    except Exception as exc:  # noqa: BLE001
        return _error_from_exception(store.base_dir / slug / "profile.yaml", exc)

    try:
        events = store.load_events(slug)
    except Exception as exc:  # noqa: BLE001
        return _error_from_exception(store.base_dir / slug / "events.yaml", exc)

    event = _find_event(events, args.event)
    if event is None:
        return _error(f"no event matching {args.event!r}")

    start = date.fromisoformat(args.start) if args.start else date.today()

    if args.current_volume is None:
        return _error(
            "--current-volume is required (deriving it from logged history "
            "isn't implemented yet -- that lands with load.py)"
        )

    try:
        macro = scaffold_macro(
            athlete, event, start, args.current_volume, args.peak_volume
        )
    except ValueError as exc:
        return _error(str(exc))

    store.save_macro(slug, macro)
    print(
        json.dumps(
            {
                "athlete": slug,
                "event": event.name,
                "blocks": [
                    {
                        "name": block.name,
                        "start_date": block.start_date.isoformat(),
                        "end_date": block.end_date.isoformat(),
                        "weekly_volume_target_m": block.weekly_volume_target_m,
                        "focus": block.focus,
                    }
                    for block in macro.blocks
                ],
            }
        )
    )
    return 0


def _event_format_for_macro(store: FileStore, slug: str, macro) -> str:
    """Look up the macro's Event and return its event_format, defaulting to
    "single_day" if the event can't be found (e.g. deleted from events.yaml
    after the macro was scaffolded) -- never let a lookup miss crash
    plan-week, since single_day is also Event's own model default."""
    try:
        events = store.load_events(slug)
    except Exception:  # noqa: BLE001
        return "single_day"
    for event in events:
        if event.id == macro.event_id:
            return event.event_format
    return "single_day"


def _cmd_plan_week(args: argparse.Namespace, store: FileStore) -> int:
    slug = args.athlete
    try:
        athlete = store.load_athlete(slug)
    except Exception as exc:  # noqa: BLE001
        return _error_from_exception(store.base_dir / slug / "profile.yaml", exc)

    try:
        macro = store.load_macro(slug)
    except Exception as exc:  # noqa: BLE001
        return _error_from_exception(store.base_dir / slug / "plan" / "macro.yaml", exc)
    if macro is None:
        return _error("no macro plan for this athlete; run scaffold-macro first")

    try:
        year_str, week_str = args.week.split("-W")
        week_start = date.fromisocalendar(int(year_str), int(week_str), 1)
    except (ValueError, IndexError):
        return _error(f"invalid --week {args.week!r}; expected format 'YYYY-Wnn'")

    existing = store.load_week(slug, args.week)
    if existing is not None and not existing.draft and not args.force:
        return _error(
            f"week {args.week} already exists and is not a draft; pass --force to overwrite"
        )

    event_format = _event_format_for_macro(store, slug, macro)
    try:
        week = generate_week(athlete, macro, args.week, week_start, event_format=event_format)
    except ValueError as exc:
        return _error(str(exc))

    store.save_week(slug, week)
    print(
        json.dumps(
            {
                "athlete": slug,
                "iso_week": week.iso_week,
                "meso_block": week.meso_block,
                "focus": week.focus,
                "target_volume_m": week.target_volume_m,
                "sessions": [
                    {
                        "date": session.date.isoformat(),
                        "sport": session.sport,
                        "source": session.source,
                        "distance_m": session.distance_m,
                        "duration_min": session.duration_min,
                        "purpose": session.purpose,
                    }
                    for session in week.sessions
                ],
            }
        )
    )
    return 0


def _cmd_summarize(args: argparse.Namespace, store: FileStore) -> int:
    """Compact JSON training-load/wellness/compliance rollup over the
    trailing `--weeks` weeks (default 4), ending at `--as-of` (default
    today). Reused by `/adapt`'s Sunday ritual and, per ROADMAP.md, by
    Phase 2's chat context assembler.
    """
    slug = args.athlete
    try:
        store.load_athlete(slug)
    except Exception as exc:  # noqa: BLE001
        return _error_from_exception(store.base_dir / slug / "profile.yaml", exc)

    if args.as_of:
        try:
            as_of = date.fromisoformat(args.as_of)
        except ValueError:
            return _error(f"invalid --as-of {args.as_of!r}; expected 'YYYY-MM-DD'")
    else:
        as_of = date.today()

    weeks = args.weeks
    as_of_monday = as_of - timedelta(days=as_of.weekday())
    week_starts = [as_of_monday - timedelta(weeks=i) for i in range(weeks - 1, -1, -1)]
    span_start = week_starts[0]
    span_end = as_of_monday + timedelta(days=6)

    workouts = store.list_workouts(slug)
    wellness = store.list_wellness(slug)

    volume_by_week = {_iso_week(ws): weekly_volume_m(workouts, ws) for ws in week_starts}

    loads = daily_loads(workouts)
    window_loads = {d: v for d, v in loads.items() if span_start <= d <= span_end}
    monotony_value = monotony(window_loads)
    load_ratio = acute_chronic_ratio(workouts, as_of)

    window_wellness = [w for w in wellness if span_start <= w.date <= span_end]
    trend = wellness_trend(window_wellness)

    planned_sessions = []
    for ws in week_starts:
        week_plan = store.load_week(slug, _iso_week(ws))
        if week_plan is not None:
            planned_sessions.extend(week_plan.sessions)
    window_workouts = [w for w in workouts if span_start <= w.date <= span_end]
    compliance_pct = compute_compliance(planned_sessions, window_workouts) if planned_sessions else None

    print(
        json.dumps(
            {
                "athlete": slug,
                "as_of": as_of.isoformat(),
                "weeks": weeks,
                "volume_m": volume_by_week,
                "srpe_load_by_day": {d.isoformat(): v for d, v in sorted(window_loads.items())},
                "load_ratio_7d_28d": load_ratio,
                "monotony": monotony_value,
                "wellness_trend": [[d.isoformat(), v] for d, v in trend],
                "compliance_pct": compliance_pct,
            }
        )
    )
    return 0


def _cmd_adapt(args: argparse.Namespace, store: FileStore) -> int:
    """Run the deterministic adaptation draft for `--week` and write it as a
    draft WeekPlan (`draft: true`) -- see `swim_coach.adapt.adapt_week`.
    Refuses to overwrite an existing non-draft week without `--force`."""
    slug = args.athlete
    try:
        athlete = store.load_athlete(slug)
    except Exception as exc:  # noqa: BLE001
        return _error_from_exception(store.base_dir / slug / "profile.yaml", exc)

    try:
        macro = store.load_macro(slug)
    except Exception as exc:  # noqa: BLE001
        return _error_from_exception(store.base_dir / slug / "plan" / "macro.yaml", exc)
    if macro is None:
        return _error("no macro plan for this athlete; run scaffold-macro first")

    try:
        events = store.load_events(slug)
    except Exception as exc:  # noqa: BLE001
        return _error_from_exception(store.base_dir / slug / "events.yaml", exc)
    event = next((e for e in events if e.id == macro.event_id), None)
    if event is None:
        return _error(f"macro's event_id {macro.event_id} not found in events.yaml")

    try:
        year_str, week_str = args.week.split("-W")
        week_start = date.fromisocalendar(int(year_str), int(week_str), 1)
    except (ValueError, IndexError):
        return _error(f"invalid --week {args.week!r}; expected format 'YYYY-Wnn'")

    existing = store.load_week(slug, args.week)
    if existing is not None and not existing.draft and not args.force:
        return _error(
            f"week {args.week} already exists and is not a draft; pass --force to overwrite"
        )

    current_week_start = week_start - timedelta(days=7)
    current_iso = _iso_week(current_week_start)
    current_week = store.load_week(slug, current_iso)
    if current_week is None:
        return _error(
            f"no existing week plan for {current_iso!r} (the week before --week) to adapt from"
        )

    workouts = store.list_workouts(slug)
    wellness = store.list_wellness(slug)
    as_of = week_start - timedelta(days=1)

    try:
        week = adapt_week(
            athlete,
            event,
            macro,
            args.week,
            week_start,
            current_week,
            workouts,
            wellness,
            as_of,
            days_since_last_milestone=args.days_since_last_milestone,
        )
    except ValueError as exc:
        return _error(str(exc))

    store.save_week(slug, week)
    print(
        json.dumps(
            {
                "athlete": slug,
                "iso_week": week.iso_week,
                "draft": week.draft,
                "target_volume_m": week.target_volume_m,
                "rationale": json.loads(week.adaptation_rationale),
            }
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m swim_coach.cli")
    parser.add_argument("--base-dir", default="athletes", help="athlete data root (default: athletes)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_validate = subparsers.add_parser("validate", help="validate an athlete's whole data tree")
    p_validate.add_argument("--athlete", required=True)

    p_zones = subparsers.add_parser("zones", help="compute/print CSS zone table")
    p_zones.add_argument("--athlete", required=True)
    p_zones.add_argument("--test-400", dest="test_400")
    p_zones.add_argument("--test-200", dest="test_200")
    p_zones.add_argument("--write", action="store_true")

    p_scaffold = subparsers.add_parser("scaffold-macro", help="build the macro periodization scaffold")
    p_scaffold.add_argument("--athlete", required=True)
    p_scaffold.add_argument("--event", required=True, help="event name or id (prefix)")
    p_scaffold.add_argument("--start", help="YYYY-MM-DD, default today")
    p_scaffold.add_argument("--current-volume", dest="current_volume", type=int)
    p_scaffold.add_argument("--peak-volume", dest="peak_volume", type=int)

    p_plan_week = subparsers.add_parser("plan-week", help="generate one week's sessions")
    p_plan_week.add_argument("--athlete", required=True)
    p_plan_week.add_argument("--week", required=True, help="ISO week, e.g. 2026-W28")
    p_plan_week.add_argument("--force", action="store_true")

    p_summarize = subparsers.add_parser(
        "summarize", help="compact JSON training-load/wellness/compliance rollup"
    )
    p_summarize.add_argument("--athlete", required=True)
    p_summarize.add_argument("--weeks", type=int, default=4)
    p_summarize.add_argument("--as-of", dest="as_of", help="YYYY-MM-DD, default today")

    p_adapt = subparsers.add_parser(
        "adapt", help="run the deterministic adaptation draft for one week"
    )
    p_adapt.add_argument("--athlete", required=True)
    p_adapt.add_argument("--week", required=True, help="ISO week, e.g. 2026-W29")
    p_adapt.add_argument("--force", action="store_true")
    p_adapt.add_argument(
        "--days-since-last-milestone",
        dest="days_since_last_milestone",
        type=int,
        default=None,
        help="days since the last long-swim milestone, to gate the mandated recovery window",
    )

    return parser


_COMMANDS = {
    "validate": _cmd_validate,
    "zones": _cmd_zones,
    "scaffold-macro": _cmd_scaffold_macro,
    "plan-week": _cmd_plan_week,
    "summarize": _cmd_summarize,
    "adapt": _cmd_adapt,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    store = FileStore(base_dir=args.base_dir)

    handler = _COMMANDS[args.command]
    try:
        return handler(args, store)
    except Exception as exc:  # noqa: BLE001 - never let the CLI crash with a traceback
        return _error(f"unexpected error: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
