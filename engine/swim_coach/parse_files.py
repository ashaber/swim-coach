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

from swim_coach.analytics import GAP_THRESHOLD_S
from swim_coach.models import (
    Sport,
    WorkoutAnalytics,
    WorkoutLap,
    WorkoutLength,
    WorkoutPause,
    WorkoutSet,
)

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
    # Mirrors of Workout's .fit-analytics fields (Slice 1) -- see
    # swim_coach.models.Workout. `analytics` is left None by every parser;
    # cli.py's `ingest`/`analyze` commands compute it (swim_coach.analytics.
    # compute_analytics) once the draft is in hand, since that also needs
    # the caller's choice of what to persist. `series_ref` is likewise
    # filled in only once the CLI has actually written the sidecar file.
    avg_hr: int | None = None
    max_hr: int | None = None
    laps: list[WorkoutLap] = Field(default_factory=list)
    lengths: list[WorkoutLength] = Field(default_factory=list)
    pauses: list[WorkoutPause] = Field(default_factory=list)
    analytics: WorkoutAnalytics | None = None
    series_ref: str | None = None
    # In-memory columnar time-series payload (see store.FileStore.save_series
    # for the on-disk shape) -- deliberately NOT a Workout field; committed
    # workout YAML must stay human-readable (CLAUDE.md), so full time-series
    # data lives only in the sidecar JSON, never in the draft/Workout YAML.
    series: dict[str, list] | None = None
    # Wall-clock (elapsed) minutes, distinct from `duration_min` (moving/
    # timer minutes) -- carried on the draft only long enough for the CLI to
    # pass both into swim_coach.analytics.compute_analytics.
    elapsed_min: float | None = None


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
    2026-07-09, was a kayak session). The one carve-out: Garmin encodes a
    logged strength workout as session.sport=="training" (sub_sport
    typically "strength_training", surfaces in intervals.icu as
    "WeightTraining") -- that maps to this engine's own "strength" Sport
    instead of cross_train, unambiguous enough to need no warning, same as
    the swim cases above. It still counts toward sRPE load, never swim
    volume, exactly like cross_train does.
    """
    if session_sub_sport is not None and "open" in str(session_sub_sport).lower():
        return "swim_ow"
    if session_sport is None:
        warnings.append("no session.sport field found; assumed swim_pool")
        return "swim_pool"
    session_sport_lower = str(session_sport).lower()
    if "swim" in session_sport_lower:
        return "swim_pool"
    if session_sport_lower == "training" or "strength" in str(session_sub_sport or "").lower():
        return "strength"
    warnings.append(
        f"non-swim FIT sport '{session_sport}' mapped to cross_train "
        "(counts toward sRPE load, not swim volume)"
    )
    return "cross_train"


_SEMICIRCLE_TO_DEG = 180.0 / (2**31)
# FIT stores lat/long as 32-bit semicircles; this is the Garmin FIT SDK's
# documented conversion to degrees.


def _semicircles_to_degrees(value: object) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    return value * _SEMICIRCLE_TO_DEG


def _lap_index_for_length(message_index: object, laps_raw: list[dict]) -> int | None:
    """Which lap (0-based position in laps_raw) a length frame belongs to,
    via the lap's first_length_index/num_lengths range. None if the length
    has no message_index, or no lap's range covers it (e.g. no lengths at
    all, as in a non-pool .fit)."""
    if not isinstance(message_index, int):
        return None
    for i, raw in enumerate(laps_raw):
        first = raw.get("first_length_index")
        count = raw.get("num_lengths")
        if not isinstance(first, int) or not isinstance(count, int):
            continue
        if first <= message_index < first + count:
            return i
    return None


def _build_laps(laps_raw: list[dict], t0: datetime | None) -> list[WorkoutLap]:
    laps: list[WorkoutLap] = []
    for i, raw in enumerate(laps_raw):
        duration_s = raw["total_timer_time"] or raw["total_elapsed_time"] or 0.0
        start_offset_s = None
        if t0 is not None and isinstance(raw["start_time"], datetime):
            start_offset_s = (raw["start_time"] - t0).total_seconds()
        distance_m = raw["total_distance"]
        avg_pace = duration_s / (distance_m / 100) if distance_m and duration_s else None
        stroke = raw["swim_stroke"]
        laps.append(
            WorkoutLap(
                index=i,
                start_offset_s=start_offset_s,
                duration_s=duration_s,
                distance_m=distance_m,
                avg_hr=raw["avg_heart_rate"],
                max_hr=raw["max_heart_rate"],
                avg_pace_s_per_100m=avg_pace,
                stroke=str(stroke) if stroke is not None else None,
                num_lengths=raw["num_lengths"],
            )
        )
    return laps


def _build_lengths(
    lengths_raw: list[dict], laps_raw: list[dict], t0: datetime | None
) -> tuple[list[WorkoutLength], list[WorkoutPause]]:
    """Active length frames -> WorkoutLength (sequential 0-based `index`,
    swolf = duration_s + strokes when both present); idle length frames ->
    WorkoutPause(source="idle_length")."""
    active: list[WorkoutLength] = []
    idle_pauses: list[WorkoutPause] = []
    active_index = 0
    for raw in lengths_raw:
        duration_s = raw["total_timer_time"] or raw["total_elapsed_time"] or 0.0
        start_offset_s = None
        if t0 is not None and isinstance(raw["start_time"], datetime):
            start_offset_s = (raw["start_time"] - t0).total_seconds()
        elif t0 is not None and isinstance(raw["timestamp"], datetime):
            start_offset_s = (raw["timestamp"] - t0).total_seconds() - duration_s

        if raw["length_type"] == "active":
            strokes = raw["total_strokes"]
            stroke = raw["swim_stroke"]
            swolf = (
                duration_s + strokes
                if duration_s is not None and strokes is not None
                else None
            )
            active.append(
                WorkoutLength(
                    index=active_index,
                    lap_index=_lap_index_for_length(raw["message_index"], laps_raw),
                    duration_s=duration_s,
                    strokes=strokes,
                    stroke=str(stroke) if stroke is not None else None,
                    swolf=swolf,
                )
            )
            active_index += 1
        elif raw["length_type"] == "idle" and start_offset_s is not None:
            idle_pauses.append(
                WorkoutPause(start_offset_s=start_offset_s, duration_s=duration_s, source="idle_length")
            )
    return active, idle_pauses


def _build_timer_pauses(events_raw: list[dict], t0: datetime | None) -> list[WorkoutPause]:
    """Pair a timer stop (event_type in stop/stop_all/stop_disable) with the
    next timer start into one WorkoutPause. A trailing stop with no
    following start (e.g. the final stop_all) is the end of the activity,
    not a pause -- it produces nothing."""
    if t0 is None:
        return []
    pauses: list[WorkoutPause] = []
    pending_stop: datetime | None = None
    for event in events_raw:
        if event["event"] != "timer" or not isinstance(event["timestamp"], datetime):
            continue
        event_type = event["event_type"]
        if event_type == "start":
            if pending_stop is not None:
                duration_s = (event["timestamp"] - pending_stop).total_seconds()
                if duration_s > 0:
                    pauses.append(
                        WorkoutPause(
                            start_offset_s=(pending_stop - t0).total_seconds(),
                            duration_s=duration_s,
                            source="timer",
                        )
                    )
            pending_stop = None
        elif event_type in ("stop", "stop_all", "stop_disable"):
            pending_stop = event["timestamp"]
    return pauses


def _build_gap_pauses(records_raw: list[dict], t0: datetime | None) -> list[WorkoutPause]:
    """A record-frame timestamp gap longer than GAP_THRESHOLD_S (see
    swim_coach.analytics) becomes a pause -- distinguishes a real stop from
    ordinary smart-recording sampling variance."""
    if t0 is None:
        return []
    timestamps = [r["timestamp"] for r in records_raw if isinstance(r["timestamp"], datetime)]
    pauses: list[WorkoutPause] = []
    for prev, curr in zip(timestamps, timestamps[1:]):
        gap_s = (curr - prev).total_seconds()
        if gap_s > GAP_THRESHOLD_S:
            pauses.append(
                WorkoutPause(start_offset_s=(prev - t0).total_seconds(), duration_s=gap_s, source="gap")
            )
    return pauses


def _pause_overlaps(pause: WorkoutPause, others: list[WorkoutPause]) -> bool:
    pause_end = pause.start_offset_s + pause.duration_s
    return any(
        pause.start_offset_s < (other.start_offset_s + other.duration_s)
        and other.start_offset_s < pause_end
        for other in others
    )


def _merge_pauses(
    timer_pauses: list[WorkoutPause], gap_pauses: list[WorkoutPause], idle_pauses: list[WorkoutPause]
) -> list[WorkoutPause]:
    """timer pauses always kept; gap/idle-length pauses that overlap a timer
    pause's span are dropped as duplicates of the same real stop."""
    merged = list(timer_pauses)
    merged.extend(p for p in gap_pauses if not _pause_overlaps(p, timer_pauses))
    merged.extend(p for p in idle_pauses if not _pause_overlaps(p, timer_pauses))
    merged.sort(key=lambda p: p.start_offset_s)
    return merged


def _build_series(records_raw: list[dict], t0: datetime | None) -> dict[str, list] | None:
    """Columnar {t_s, hr, speed_mps, dist_m, lat, lng} series from record
    frames, t_s measured from t0. A channel key is included only if at
    least one sample has a non-None value for it (nulls allowed within an
    included channel, for gaps); returns None if every optional channel is
    entirely empty (e.g. a pool swim whose record frames carry only
    temperature+timestamp)."""
    if t0 is None or not records_raw:
        return None

    t_s: list[float] = []
    hr: list[object] = []
    speed_mps: list[object] = []
    dist_m: list[object] = []
    lat: list[object] = []
    lng: list[object] = []
    any_hr = any_speed = any_dist = any_lat = any_lng = False
    prev_t: float | None = None
    prev_dist: float | None = None

    for record in records_raw:
        ts = record["timestamp"]
        if not isinstance(ts, datetime):
            continue
        t = (ts - t0).total_seconds()
        t_s.append(t)

        h = record["heart_rate"]
        hr.append(h)
        any_hr = any_hr or h is not None

        d = record["distance"]
        dist_m.append(d)
        any_dist = any_dist or d is not None

        speed = record["enhanced_speed"]
        if speed is None:
            speed = record["speed"]
        if speed is None and d is not None and prev_dist is not None and prev_t is not None and t > prev_t:
            speed = (d - prev_dist) / (t - prev_t)
        speed_mps.append(speed)
        any_speed = any_speed or speed is not None

        la = _semicircles_to_degrees(record["position_lat"])
        lo = _semicircles_to_degrees(record["position_long"])
        lat.append(la)
        lng.append(lo)
        any_lat = any_lat or la is not None
        any_lng = any_lng or lo is not None

        prev_t = t
        if d is not None:
            prev_dist = d

    if not (any_hr or any_speed or any_dist or any_lat or any_lng):
        return None

    series: dict[str, list] = {"t_s": t_s}
    if any_hr:
        series["hr"] = hr
    if any_speed:
        series["speed_mps"] = speed_mps
    if any_dist:
        series["dist_m"] = dist_m
    if any_lat:
        series["lat"] = lat
    if any_lng:
        series["lng"] = lng
    return series


def parse_fit(path: str | Path) -> WorkoutDraft:
    """Parse a Garmin .fit file's session + lap + length + record + event
    data into a WorkoutDraft.

    Field-name assumptions follow the Garmin FIT SDK global profile
    (total_distance, total_timer_time/total_elapsed_time, sport, sub_sport,
    start_time, swim_stroke for session/lap; total_strokes, length_type,
    start_time for length; heart_rate, distance, enhanced_speed/speed,
    position_lat/position_long for record; event/event_type/timer_trigger
    for event). Verified against two real fixtures (see
    tests/unit/fixtures/fit/README.md): a pool swim (length/lap data, no
    HR, no GPS) and a kayak cross-train activity (record-level HR/GPS/
    distance, no lengths). Every field is read defensively (`fallback=None`
    via `_fit_value`) since real device exports vary in which optional
    fields they populate.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"no such file: {path}")

    warnings: list[str] = []
    session_distance: float | None = None
    session_duration_s: float | None = None  # moving/timer time
    session_elapsed_s: float | None = None  # wall-clock time
    session_sport: object | None = None
    session_sub_sport: object | None = None
    session_start_time: object | None = None
    session_avg_hr: int | None = None
    session_max_hr: int | None = None

    sets: list[WorkoutSet] = []
    laps_raw: list[dict] = []
    lengths_raw: list[dict] = []
    records_raw: list[dict] = []
    events_raw: list[dict] = []

    with fitdecode.FitReader(path) as fit:
        for frame in fit:
            if frame.frame_type != fitdecode.FIT_FRAME_DATA:
                continue
            if frame.name == "session":
                session_distance = _fit_value(frame, "total_distance")
                session_duration_s = _fit_value(frame, "total_timer_time") or _fit_value(
                    frame, "total_elapsed_time"
                )
                session_elapsed_s = _fit_value(frame, "total_elapsed_time")
                session_sport = _fit_value(frame, "sport")
                session_sub_sport = _fit_value(frame, "sub_sport")
                session_start_time = _fit_value(frame, "start_time")
                session_avg_hr = _fit_value(frame, "avg_heart_rate")
                session_max_hr = _fit_value(frame, "max_heart_rate")
            elif frame.name == "lap":
                lap_distance = _fit_value(frame, "total_distance")
                lap_time = _fit_value(frame, "total_elapsed_time")
                stroke = _fit_value(frame, "swim_stroke")
                if lap_distance is not None:
                    # Legacy behavior, kept for back-compat: one free-text
                    # WorkoutSet per lap with distance. _build_laps (below)
                    # separately produces the new numeric WorkoutLap list.
                    sets.append(
                        WorkoutSet(
                            distance_m=round(lap_distance),
                            stroke=str(stroke) if stroke is not None else None,
                            description=f"{lap_time:.0f}s" if isinstance(lap_time, (int, float)) else None,
                        )
                    )
                laps_raw.append(
                    {
                        "total_distance": lap_distance,
                        "total_timer_time": _fit_value(frame, "total_timer_time"),
                        "total_elapsed_time": lap_time,
                        "start_time": _fit_value(frame, "start_time"),
                        "avg_heart_rate": _fit_value(frame, "avg_heart_rate"),
                        "max_heart_rate": _fit_value(frame, "max_heart_rate"),
                        "swim_stroke": stroke,
                        "first_length_index": _fit_value(frame, "first_length_index"),
                        "num_lengths": _fit_value(frame, "num_lengths"),
                    }
                )
            elif frame.name == "length":
                lengths_raw.append(
                    {
                        "message_index": _fit_value(frame, "message_index"),
                        "start_time": _fit_value(frame, "start_time"),
                        "timestamp": _fit_value(frame, "timestamp"),
                        "total_timer_time": _fit_value(frame, "total_timer_time"),
                        "total_elapsed_time": _fit_value(frame, "total_elapsed_time"),
                        "total_strokes": _fit_value(frame, "total_strokes"),
                        "swim_stroke": _fit_value(frame, "swim_stroke"),
                        "length_type": _fit_value(frame, "length_type"),
                    }
                )
            elif frame.name == "record":
                records_raw.append(
                    {
                        "timestamp": _fit_value(frame, "timestamp"),
                        "heart_rate": _fit_value(frame, "heart_rate"),
                        "distance": _fit_value(frame, "distance"),
                        "enhanced_speed": _fit_value(frame, "enhanced_speed"),
                        "speed": _fit_value(frame, "speed"),
                        "position_lat": _fit_value(frame, "position_lat"),
                        "position_long": _fit_value(frame, "position_long"),
                    }
                )
            elif frame.name == "event":
                events_raw.append(
                    {
                        "timestamp": _fit_value(frame, "timestamp"),
                        "event": _fit_value(frame, "event"),
                        "event_type": _fit_value(frame, "event_type"),
                    }
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

    t0: datetime | None
    if isinstance(session_start_time, datetime):
        workout_date = session_start_time.date()
        t0 = session_start_time
    else:
        workout_date = date.today()
        warnings.append("no session.start_time found; date defaulted to today")
        first_record_ts = records_raw[0]["timestamp"] if records_raw else None
        t0 = first_record_ts if isinstance(first_record_ts, datetime) else None

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

    laps = _build_laps(laps_raw, t0)
    lengths, idle_pauses = _build_lengths(lengths_raw, laps_raw, t0)
    timer_pauses = _build_timer_pauses(events_raw, t0)
    gap_pauses = _build_gap_pauses(records_raw, t0)
    pauses = _merge_pauses(timer_pauses, gap_pauses, idle_pauses)
    series = _build_series(records_raw, t0)

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
        avg_hr=session_avg_hr,
        max_hr=session_max_hr,
        laps=laps,
        lengths=lengths,
        pauses=pauses,
        series=series,
        elapsed_min=session_elapsed_s / 60 if session_elapsed_s is not None else None,
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
