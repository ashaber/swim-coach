"""File-based workout ingest: .tcx, .csv, .fit -> a common WorkoutDraft.

Each parser is best-effort and tolerant of missing/unexpected fields --
every assumption it has to make (units, defaulted dates, inferred sport)
is recorded in the returned draft's `warnings` list rather than silently
swallowed, so a human (or the /log-workout skill) can double check before
the draft becomes a persisted Workout.

None of these parsers call an LLM or the network -- `.tcx` uses stdlib
`xml.etree.ElementTree`, `.csv` uses stdlib `csv`, `.fit` uses
`fitdecode` (see engine/pyproject.toml).
"""

from __future__ import annotations

import csv
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

import fitdecode
from pydantic import BaseModel, Field

from swim_coach.models import Sport, WorkoutSet

WorkoutSource = Literal["manual", "fit", "tcx", "csv", "coach_text"]


class WorkoutDraft(BaseModel):
    """A not-yet-persisted Workout, as produced by a file parser.

    Mirrors `swim_coach.models.Workout` minus `id`/`athlete_id` (those are
    only known at save time -- see `cli.py`'s `ingest --save`), plus
    `warnings` for every assumption the parser had to make.
    """

    schema_version: int = 1
    date: date
    sport: Sport
    source: WorkoutSource
    distance_m: int = Field(ge=0)
    duration_min: float = Field(gt=0)
    avg_pace_s_per_100m: float | None = None
    rpe: int | None = Field(default=None, ge=1, le=10)
    sets: list[WorkoutSet] = Field(default_factory=list)
    planned_session_id: UUID | None = None
    raw_ref: str | None = None
    notes: str | None = None
    warnings: list[str] = Field(default_factory=list)


# --- shared helpers ------------------------------------------------------------------

_MIN_DURATION_MIN = 0.1
# Workout.duration_min requires > 0; a file with no usable duration data
# floors to this rather than failing validation outright -- the draft's
# warnings list always explains why.


def _floor_duration_min(duration_min: float, warnings: list[str], reason: str) -> float:
    if duration_min <= 0:
        warnings.append(reason)
        return _MIN_DURATION_MIN
    return duration_min


# --- .tcx (stdlib ElementTree) ---------------------------------------------------------

_TCX_NS = {"tcx": "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"}


def _tcx_find(elem: ET.Element, tag: str) -> ET.Element | None:
    found = elem.find(f"tcx:{tag}", _TCX_NS)
    if found is None:
        found = elem.find(tag)  # tolerate a missing/different xmlns
    return found


def _parse_tcx_date(value: str) -> date:
    return date.fromisoformat(value[:10])


def parse_tcx(path: str | Path) -> WorkoutDraft:
    """Parse a Garmin/TrainingPeaks-style .tcx export into a WorkoutDraft.

    Sport inference: TCX's <Activity Sport="..."> attribute has no
    standard "open water swim" value, so this assumes swim_pool unless the
    attribute (or lack thereof) hints otherwise ("open"/"ow" substrings) --
    documented via a warning either way. Every <Lap> becomes one
    WorkoutSet (distance_m only; TCX laps don't carry stroke/interval
    data).
    """
    path = Path(path)
    warnings: list[str] = []
    tree = ET.parse(path)  # noqa: S314 - local trusted file, not untrusted network XML
    root = tree.getroot()

    activity = root.find(".//tcx:Activity", _TCX_NS)
    if activity is None:
        activity = root.find(".//Activity")
    if activity is None:
        raise ValueError(f"no <Activity> element found in {path}")

    sport_attr = (activity.get("Sport") or "").strip()
    sport: Sport = "swim_ow" if "open" in sport_attr.lower() or "ow" in sport_attr.lower() else "swim_pool"
    if not sport_attr:
        warnings.append("no Sport attribute on <Activity>; assumed swim_pool")
    elif sport != "swim_ow":
        warnings.append(f"Sport attribute {sport_attr!r} has no open-water hint; assumed swim_pool")

    id_elem = _tcx_find(activity, "Id")
    if id_elem is not None and id_elem.text:
        workout_date = _parse_tcx_date(id_elem.text)
    else:
        workout_date = date.today()
        warnings.append("no <Id> timestamp found; date defaulted to today")

    laps = activity.findall("tcx:Lap", _TCX_NS) or activity.findall("Lap")
    if not laps:
        warnings.append("no <Lap> elements found; distance/duration default to 0")

    sets: list[WorkoutSet] = []
    total_distance = 0.0
    total_time_s = 0.0
    for lap in laps:
        dist_elem = _tcx_find(lap, "DistanceMeters")
        time_elem = _tcx_find(lap, "TotalTimeSeconds")
        distance = float(dist_elem.text) if dist_elem is not None and dist_elem.text else 0.0
        time_s = float(time_elem.text) if time_elem is not None and time_elem.text else 0.0
        total_distance += distance
        total_time_s += time_s
        sets.append(WorkoutSet(distance_m=round(distance)))

    avg_pace = total_time_s / (total_distance / 100) if total_distance > 0 and total_time_s > 0 else None
    duration_min = _floor_duration_min(
        round(total_time_s / 60, 1),
        warnings,
        "total lap time is 0; duration_min floored to satisfy the Workout schema",
    )

    return WorkoutDraft(
        date=workout_date,
        sport=sport,
        source="tcx",
        distance_m=round(total_distance),
        duration_min=duration_min,
        avg_pace_s_per_100m=avg_pace,
        sets=sets,
        raw_ref=str(path),
        warnings=warnings,
    )


# --- .csv (stdlib csv, header-mapping table) --------------------------------------------

_CSV_DATE_ALIASES = ["date", "activity date"]
_CSV_DISTANCE_ALIASES = ["distance", "distance (m)", "distance_m"]
_CSV_DURATION_ALIASES = ["time", "moving time", "elapsed time", "duration"]
_CSV_PACE_ALIASES = ["avg pace", "average pace", "avg_pace", "avg_pace_s_per_100m"]
_CSV_SPORT_ALIASES = ["activity type", "type", "sport"]
# Common Garmin Connect / Strava per-activity export column names. Any
# missing column falls back to a documented default (see parse_csv).


def _normalize_csv_row(row: dict[str, str | None]) -> dict[str, str]:
    return {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}


def _first_present(norm_row: dict[str, str], aliases: list[str]) -> str | None:
    for alias in aliases:
        value = norm_row.get(alias)
        if value:
            return value
    return None


def _parse_clock_to_seconds(value: str) -> float:
    parts = [float(p) for p in value.strip().split(":")]
    if len(parts) == 3:
        hours, minutes, seconds = parts
    elif len(parts) == 2:
        hours, (minutes, seconds) = 0.0, parts
    elif len(parts) == 1:
        hours, minutes, seconds = 0.0, 0.0, parts[0]
    else:
        raise ValueError(f"unrecognized clock format: {value!r}")
    return hours * 3600 + minutes * 60 + seconds


def _parse_duration_to_min(value: str) -> float:
    value = value.strip()
    if ":" in value:
        return _parse_clock_to_seconds(value) / 60.0
    # A bare number with no colon is assumed to be seconds (matches raw
    # Strava "moving_time"/"elapsed_time" exports); documented via warning
    # by the caller.
    return float(value) / 60.0


def _parse_csv_date(value: str) -> tuple[date, bool]:
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).date(), True
        except ValueError:
            continue
    try:
        return date.fromisoformat(value[:10]), True
    except ValueError:
        return date.today(), False


def parse_csv(path: str | Path) -> WorkoutDraft:
    """Parse a common Garmin/Strava per-activity export CSV into a WorkoutDraft.

    Only the first data row is used (one workout per CSV, matching a
    single-activity export); a warning notes it if more rows are present.
    Missing columns fall back to documented defaults rather than raising.
    A plain CSV row has no per-lap/set detail, so `sets` is always empty.
    """
    path = Path(path)
    warnings: list[str] = []
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ValueError(f"no data rows found in {path}")
    if len(rows) > 1:
        warnings.append(f"{len(rows)} data rows found; only the first row is used")
    row = _normalize_csv_row(rows[0])

    date_raw = _first_present(row, _CSV_DATE_ALIASES)
    if date_raw is not None:
        workout_date, ok = _parse_csv_date(date_raw)
        if not ok:
            warnings.append(f"could not parse date {date_raw!r}; defaulted to today")
    else:
        workout_date = date.today()
        warnings.append("no recognizable date column; defaulted to today")

    distance_raw = _first_present(row, _CSV_DISTANCE_ALIASES)
    if distance_raw is not None:
        try:
            distance_m = round(float(distance_raw.replace(",", "")))
        except ValueError:
            distance_m = 0
            warnings.append(f"could not parse distance {distance_raw!r}; defaulted to 0")
        else:
            warnings.append(
                "distance column assumed to already be in meters -- verify against your "
                "export's unit settings"
            )
    else:
        distance_m = 0
        warnings.append("no recognizable distance column; defaulted to 0")

    duration_raw = _first_present(row, _CSV_DURATION_ALIASES)
    duration_min = 0.0
    if duration_raw is not None:
        try:
            duration_min = _parse_duration_to_min(duration_raw)
            if ":" not in duration_raw:
                warnings.append(f"duration {duration_raw!r} has no ':'; assumed seconds")
        except ValueError:
            warnings.append(f"could not parse duration {duration_raw!r}; defaulted to 0")
    else:
        warnings.append("no recognizable duration column; defaulted to 0")
    duration_min = _floor_duration_min(
        duration_min, warnings, "duration is 0; duration_min floored to satisfy the Workout schema"
    )

    pace_raw = _first_present(row, _CSV_PACE_ALIASES)
    avg_pace: float | None = None
    if pace_raw is not None:
        try:
            avg_pace = _parse_clock_to_seconds(pace_raw) if ":" in pace_raw else float(pace_raw)
        except ValueError:
            warnings.append(f"could not parse avg pace {pace_raw!r}; left unset")
    if avg_pace is None and distance_m > 0 and duration_min > 0:
        avg_pace = (duration_min * 60) / (distance_m / 100)

    sport_raw = _first_present(row, _CSV_SPORT_ALIASES)
    sport: Sport = "swim_pool"
    if sport_raw is not None:
        lowered = sport_raw.lower()
        if "open" in lowered:
            sport = "swim_ow"
        elif "swim" not in lowered and "pool" not in lowered:
            warnings.append(f"unrecognized activity type {sport_raw!r}; assumed swim_pool")
    else:
        warnings.append("no recognizable activity-type column; assumed swim_pool")

    return WorkoutDraft(
        date=workout_date,
        sport=sport,
        source="csv",
        distance_m=distance_m,
        duration_min=duration_min,
        avg_pace_s_per_100m=avg_pace,
        sets=[],
        raw_ref=str(path),
        warnings=warnings,
    )


# --- .fit (fitdecode) ------------------------------------------------------------------


def _fit_value(frame: "fitdecode.FitDataMessage", name: str) -> object | None:
    return frame.get_value(name, fallback=None)


def _fit_sport(session_sport: object | None, session_sub_sport: object | None, warnings: list[str]) -> Sport:
    """Map a FIT session's sport/sub_sport to this engine's Sport values.

    Anything that isn't recognizably swimming maps to cross_train with a
    warning -- a kayak/run/ride file must never be silently logged as a swim
    (it would pollute swim-volume math; the first real .fit ingested,
    2026-07-09, was a kayak session).
    """
    if session_sub_sport is not None and "open" in str(session_sub_sport).lower():
        return "swim_ow"
    if session_sport is None:
        warnings.append("no session.sport field found; assumed swim_pool")
        return "swim_pool"
    if "swim" in str(session_sport).lower():
        return "swim_pool"
    warnings.append(
        f"non-swim FIT sport '{session_sport}' mapped to cross_train "
        "(counts toward sRPE load, not swim volume)"
    )
    return "cross_train"


def parse_fit(path: str | Path) -> WorkoutDraft:
    """Parse a Garmin .fit file's session + lap data into a WorkoutDraft.

    Field-name assumptions follow the Garmin FIT SDK global profile for
    'session' and 'lap' messages (total_distance, total_timer_time /
    total_elapsed_time, sport, sub_sport, start_time, swim_stroke). There
    is no real .fit fixture in this repo yet (see
    tests/unit/fixtures/fit/README.md) so these assumptions are untested
    against a real export -- treat this parser as a strong first draft to
    validate against the first real file, not as verified.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"no such file: {path}")

    warnings: list[str] = []
    session_distance: float | None = None
    session_duration_s: float | None = None
    session_sport: object | None = None
    session_sub_sport: object | None = None
    session_start_time: object | None = None
    sets: list[WorkoutSet] = []

    with fitdecode.FitReader(path) as fit:
        for frame in fit:
            if frame.frame_type != fitdecode.FIT_FRAME_DATA:
                continue
            if frame.name == "session":
                session_distance = _fit_value(frame, "total_distance")
                session_duration_s = _fit_value(frame, "total_timer_time") or _fit_value(
                    frame, "total_elapsed_time"
                )
                session_sport = _fit_value(frame, "sport")
                session_sub_sport = _fit_value(frame, "sub_sport")
                session_start_time = _fit_value(frame, "start_time")
            elif frame.name == "lap":
                lap_distance = _fit_value(frame, "total_distance")
                if lap_distance is None:
                    continue
                lap_time = _fit_value(frame, "total_elapsed_time")
                stroke = _fit_value(frame, "swim_stroke")
                sets.append(
                    WorkoutSet(
                        distance_m=round(lap_distance),
                        stroke=str(stroke) if stroke is not None else None,
                        description=f"{lap_time:.0f}s" if isinstance(lap_time, (int, float)) else None,
                    )
                )

    if session_distance is None:
        warnings.append(
            "no session.total_distance field found; distance_m defaulted to sum of laps"
        )
        session_distance = float(sum(s.distance_m for s in sets))

    if session_duration_s is None:
        warnings.append(
            "no session total_timer_time/total_elapsed_time found; duration_min defaulted to 0"
        )
        session_duration_s = 0.0

    sport = _fit_sport(session_sport, session_sub_sport, warnings)

    if isinstance(session_start_time, datetime):
        workout_date = session_start_time.date()
    else:
        workout_date = date.today()
        warnings.append("no session.start_time found; date defaulted to today")

    avg_pace = (
        session_duration_s / (session_distance / 100)
        if session_distance and session_duration_s
        else None
    )
    duration_min = _floor_duration_min(
        round(session_duration_s / 60, 1),
        warnings,
        "session duration is 0; duration_min floored to satisfy the Workout schema",
    )

    return WorkoutDraft(
        date=workout_date,
        sport=sport,
        source="fit",
        distance_m=round(session_distance),
        duration_min=duration_min,
        avg_pace_s_per_100m=avg_pace,
        sets=sets,
        raw_ref=str(path),
        warnings=warnings,
    )


# --- shared extension -> parser dispatch table -------------------------------------------
# The single source of truth for "which file extensions this system can
# ingest," keyed lowercase-with-dot. Both `cli.py`'s `ingest` subcommand and
# the backend's `POST /api/workouts/ingest` route (Phase 3, athlete-facing
# upload) dispatch through this same table rather than each keeping their own
# copy, so adding/removing a supported extension is a one-line change in one
# place.
PARSERS_BY_EXTENSION: dict[str, Callable[[str | Path], WorkoutDraft]] = {
    ".tcx": parse_tcx,
    ".csv": parse_csv,
    ".fit": parse_fit,
}
