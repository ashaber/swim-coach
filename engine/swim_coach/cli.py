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
from datetime import date
from pathlib import Path

import yaml

from swim_coach.models import Event, Wellness, WeekPlan, Workout
from swim_coach.parse_coach_text import parse_coach_text
from swim_coach.plan import generate_week, scaffold_macro
from swim_coach.store import FileStore
from swim_coach.zones import css_from_test, zone_table


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

    try:
        week = generate_week(athlete, macro, args.week, week_start)
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


def _cmd_parse_coach_text(args: argparse.Namespace, store: FileStore) -> int:
    slug = args.athlete
    path = Path(args.file)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return _error(str(exc), file=str(path))

    day = date.fromisoformat(args.date) if args.date else date.today()

    # Save the verbatim text BEFORE parsing (CLAUDE.md: "Coach text is
    # saved verbatim to logs/coach-texts/ BEFORE any parsing").
    try:
        saved_path = store.save_coach_text(slug, day, text, force=args.force)
    except FileExistsError as exc:
        return _error(str(exc))

    result = parse_coach_text(text)
    output = {"athlete": slug, "saved_to": saved_path}
    output.update(result.model_dump(mode="json"))
    print(json.dumps(output))
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

    p_parse_coach_text = subparsers.add_parser(
        "parse-coach-text",
        help="save a pool-coach workout text verbatim and deterministically parse it",
    )
    p_parse_coach_text.add_argument("--athlete", required=True)
    p_parse_coach_text.add_argument("--file", required=True)
    p_parse_coach_text.add_argument("--date", help="YYYY-MM-DD, default today")
    p_parse_coach_text.add_argument("--force", action="store_true")

    return parser


_COMMANDS = {
    "validate": _cmd_validate,
    "zones": _cmd_zones,
    "scaffold-macro": _cmd_scaffold_macro,
    "plan-week": _cmd_plan_week,
    "parse-coach-text": _cmd_parse_coach_text,
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
