"""Canonical compact text for one progression rung, in both directions.

    2x8 min/4 min Z3                reps x work / rest, at a zone
    2x(3x3 min/1 min)/5 min Z4      sets x (reps x work / rest) / set rest
    6x15 s/15 s Z5                  seconds work and rest
    8x200 m/20 s Z4                 swim: metres of work, seconds of rest

Rest is a progression lever, so `describe_rung` always prints the rest actually built (the builder's
default when the intent leaves it out); `parse_rung` accepts it omitted. Work is `min`, `s` or `m`
(metres, swim); rest is `min` or `s`. The zone is required.
"""

from __future__ import annotations

import re

from swim_coach.workout_builders.intent import WorkoutIntent
from swim_coach.workout_builders.registry import WorkoutBuilder, builders_for

_TIME = r"(\d+(?:\.\d+)?)\s*(min|s)(?![a-z])"
_WORK = r"(\d+(?:\.\d+)?)\s*(min|m|s)(?![a-z])"
_REST = rf"(?:\s*/\s*{_TIME})?"
_ZONE = r"\s+(Z[1-5])"
_FLAT = re.compile(rf"^(\d+)\s*x\s*{_WORK}{_REST}{_ZONE}$", re.IGNORECASE)
_SETS = re.compile(rf"^(\d+)\s*x\s*\(\s*(\d+)\s*x\s*{_WORK}{_REST}\s*\){_REST}{_ZONE}$", re.IGNORECASE)


def format_duration(seconds: float) -> str:
    """"8 min", "7.5 min" or "90 s": minutes when that is exact to half a minute and at least 2 min."""
    if seconds % 60 == 0 and seconds >= 60:
        return f"{int(seconds // 60)} min"
    if seconds >= 120 and seconds % 30 == 0:
        return f"{seconds / 60:g} min"
    return f"{seconds:g} s"


def format_rung(
    sets: int | None, reps: int, work: str, rest_s: float, set_rest_s: float | None, zone: str
) -> str:
    inner = f"{reps}x{work}/{format_duration(rest_s)}"
    if sets and sets > 1:
        return f"{sets}x({inner})/{format_duration(set_rest_s or 0)} {zone}"
    return f"{inner} {zone}"


def _rung_builder(sport: str) -> WorkoutBuilder:
    for builder in builders_for(sport):
        if builder.rung:
            return builder
    raise ValueError(f"no rung builder registered for sport {sport!r}")


def describe_rung(intent: WorkoutIntent) -> str:
    """The canonical rung text of `intent` (reps x size, rest actually built, zone)."""
    if not (intent.reps and intent.target_zone and (intent.rep_duration_s or intent.rep_distance_m)):
        raise ValueError("a rung needs reps, a rep size (rep_duration_s or rep_distance_m) and target_zone")
    builder = _rung_builder(intent.sport)
    rest_s, set_rest_s = builder.rest_defaults(intent)
    work = f"{intent.rep_distance_m} m" if intent.rep_distance_m else format_duration(intent.rep_duration_s)
    return format_rung(intent.sets, intent.reps, work, rest_s, set_rest_s, intent.target_zone)


def _seconds(value: str, unit: str) -> float:
    return float(value) * (60.0 if unit.lower() == "min" else 1.0)


def _match(text: str) -> tuple:
    """(sets, reps, work value, work unit, rest value, rest unit, set-rest value, set-rest unit, zone)."""
    sets = _SETS.match(text.strip())
    if sets:
        return sets.groups()
    flat = _FLAT.match(text.strip())
    if flat:
        reps, wv, wu, rv, ru, zone = flat.groups()
        return (None, reps, wv, wu, rv, ru, None, None, zone)
    raise ValueError(
        f"not a rung: {text!r}; write e.g. '2x8 min/4 min Z3', '2x(3x3 min/1 min)/5 min Z4', '8x200 m/20 s Z4'"
    )


def parse_rung(text: str, sport: str) -> WorkoutIntent:
    """Parse the canonical form into a `WorkoutIntent` for the sport's rung builder."""
    sets, reps, w_val, w_unit, r_val, r_unit, s_val, s_unit, zone = _match(text)
    sets = int(sets) if sets else None
    builder = _rung_builder(sport)
    session_sport = sport if sport in builder.sports else sorted(builder.sports)[0]
    fields: dict = {"sport": session_sport, "archetype": builder.archetype, "reps": int(reps), "sets": sets,
                    "target_zone": zone.upper()}
    if w_unit.lower() == "m":
        fields["rep_distance_m"] = int(float(w_val))
    else:
        fields["rep_duration_s"] = _seconds(w_val, w_unit)
    size_field = "rep_distance_m" if "rep_distance_m" in fields else "rep_duration_s"
    if size_field not in builder.params:
        raise ValueError(f"{builder.archetype} for {sport} does not take work in '{w_unit}'")
    if r_val is not None:
        fields["rest_s"] = _seconds(r_val, r_unit)
    if s_val is not None:
        fields["set_rest_s"] = _seconds(s_val, s_unit)
    return WorkoutIntent(**fields)
