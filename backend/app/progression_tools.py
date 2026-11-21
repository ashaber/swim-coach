"""Progression tools for the coach: the read-only `get_progression` view, compiling a session entry
from a `rung`, and the progression inputs the week check uses.

Everything here is behind `Settings.progression_tools_enabled` (PROGRESSION_TOOLS_ENABLED, default
off); `with_progression_tools` is the one place the model-visible schema changes. The engine owns
every number and every sport difference (`swim_coach.progression*`, `swim_coach.workout_builders`);
nothing here branches on sport, blocks a plan or rewrites one. This module does not import
`app.tools` (which imports it).
"""

from __future__ import annotations

import copy
from datetime import date
from typing import Any

from swim_coach.formatting import format_amount
from swim_coach.models import Athlete, WeekPlan
from swim_coach.progression import ProgressionRead, WeekStimulusReview
from swim_coach.progression_check import ProgressionInputs, build_progression_inputs
from swim_coach.store import StoreInterface
from swim_coach.stimulus import profile_for
from swim_coach.workout_builders import WorkoutIntent, compile_workout, parse_rung

from app.logging_config import get_logger

log = get_logger(__name__)

MAX_CANDIDATES = 4
_WHY_CHARS = 220
_EVIDENCE_CHARS = 240

PROGRESSION_TOOL_NAME = "get_progression"

GET_PROGRESSION_TOOL: dict[str, Any] = {
    "name": PROGRESSION_TOOL_NAME,
    "description": (
        "Read-only. Per stimulus kind (tempo, threshold, vo2): verdict, last reference rung, one-lever "
        "next-step candidates (author one with `rung`), also-delivered work, threshold rebase, retest flag; "
        "plus the week's done/missed/remaining/unplanned counts and impacts. Call before authoring quality sessions."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "iso_week": {"type": "string", "description": "ISO week, e.g. '2026-W46'. Default: current week."},
            "sport": {"type": "string", "description": "Optional sport filter, e.g. 'bike', 'swim'."},
        },
        "additionalProperties": False,
    },
}

RUNG_PROPERTIES: dict[str, Any] = {
    "rung": {
        "type": "string",
        "description": (
            "Engine-compiled quality session: 'reps x work/rest Zn', e.g. '2x12 min/5 min Z4', "
            "'3x(8x30 s/15 s)/4 min Z5', '8x200 m/20 s Z4'. Builds structure, duration, distance and "
            "intensity (adjustments are returned); do not also give structure."
        ),
    },
    "archetype": {"type": "string", "description": "Builder name; with `rung` picks the builder, alone builds from duration/distance."},
}


def with_progression_tools(schema: list[dict[str, Any]], entry_schema: dict[str, Any]) -> list[dict[str, Any]]:
    """`schema` for a flag-on request: every nested session entry (`entry_schema`) also accepts `rung` and
    `archetype` (and no longer requires `duration_min`, which a rung computes), and `get_progression` is
    appended. The input is never mutated."""
    entry = {
        **entry_schema,
        "properties": {**entry_schema["properties"], **RUNG_PROPERTIES},
        "required": [name for name in entry_schema["required"] if name != "duration_min"],
    }
    out = copy.deepcopy(schema)

    def swap(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if value == entry_schema:
                    node[key] = copy.deepcopy(entry)
                else:
                    swap(value)
        elif isinstance(node, list):
            for i, value in enumerate(node):
                if value == entry_schema:
                    node[i] = copy.deepcopy(entry)
                else:
                    swap(value)

    swap(out)
    return [*out, copy.deepcopy(GET_PROGRESSION_TOOL)]


# --- compiling a session entry -----------------------------------------------------------------

_STRUCTURE_FIELDS = ("structure", "structured", "structure_notation")


def compile_entry(entry: dict[str, Any], athlete: Athlete, *, when: str) -> tuple[dict[str, Any], dict[str, Any] | None, str | None]:
    """`(entry, compiled_note, error)`. An entry with `rung` or `archetype` is compiled by the engine:
    the returned entry copy carries the compiled `structured`, `structure`, `duration_min`,
    `distance_m` and `intensity` (the coach's date, sport, purpose, title and kind are kept).
    `compiled_note` names what was built and every adjustment (never silent). Entries with neither are
    returned untouched with `(entry, None, None)`."""
    rung, archetype = entry.get("rung"), entry.get("archetype")
    if rung is None and archetype is None:
        return entry, None, None
    given = [f for f in _STRUCTURE_FIELDS if entry.get(f) is not None]
    if rung is not None and given:
        return entry, None, f"{when}: give `rung` OR {', '.join(f'`{f}`' for f in given)}, not both"
    sport = entry.get("sport")
    try:
        if rung is not None:
            intent = parse_rung(str(rung), str(sport))
            if archetype is not None:
                intent = intent.model_copy(update={"archetype": archetype})
        else:
            zone = (entry.get("intensity") or {}).get("zone") if isinstance(entry.get("intensity"), dict) else None
            intent = WorkoutIntent(
                sport=str(sport), archetype=str(archetype), total_duration_min=entry.get("duration_min"),
                total_distance_m=entry.get("distance_m"), target_zone=zone,
            )
        compiled = compile_workout(intent, athlete)
    except ValueError as exc:  # unknown sport/archetype, a bad rung, or an intent the builder cannot size
        return entry, None, f"{when}: could not compile {rung or archetype!r}: {exc}"
    built = {k: v for k, v in entry.items() if k not in ("rung", "archetype")}
    built.update(
        structured=compiled.structured.model_dump(mode="json"), structure=compiled.prose,
        duration_min=compiled.duration_min, distance_m=compiled.distance_m, intensity=compiled.intensity,
    )
    note = {"date": when, "sport": sport, "archetype": compiled.archetype,
            "duration_min": round(compiled.duration_min, 1), "distance_m": compiled.distance_m,
            "adjustments": list(compiled.adjustments)}
    if rung is not None:
        note["rung"] = str(rung)
    return built, note, None


# --- progression inputs ------------------------------------------------------------------------

def load_progression_inputs(
    store: StoreInterface, slug: str, athlete: Athlete, week: WeekPlan, *, as_of: date
) -> ProgressionInputs:
    """The ledger, reads and review of `week` that `check_week` and `get_progression` use. Raises
    whatever the store or engine raises; callers decide how to degrade."""
    weeks = [w for w in (store.load_week(slug, i) for i in store.list_week_ids(slug)) if w is not None]
    workouts, wellness = store.list_workouts(slug), store.list_wellness(slug)
    thresholds = store.list_threshold_records(slug)
    return build_progression_inputs(workouts, weeks, wellness, athlete, week, as_of=as_of, thresholds=thresholds)


# --- the compact get_progression view ----------------------------------------------------------

def _one_sentence(text: str | None, limit: int) -> str | None:
    if not text:
        return None
    first = text.split(". ")[0].strip()
    return first if len(first) <= limit else first[: limit - 1].rstrip() + "…"


def _also_delivered(read: ProgressionRead) -> str | None:
    if not read.also_delivered:
        return None
    parts = [f"{format_amount(a.work, read.unit)} {a.label} {a.date.strftime('%m-%d')}" for a in read.also_delivered[-3:]]
    more = f" (+{len(read.also_delivered) - 3} more)" if len(read.also_delivered) > 3 else ""
    return f"{len(read.also_delivered)} not read: {'; '.join(parts)}{more}"


def _why(read: ProgressionRead) -> str | None:
    """What decided the verdict. On `progress` the engine's `verdict_reason` is the next step (the
    candidates already say that), so the first reason, what the last session did, is the better why."""
    first = read.reasons[0] if read.reasons else None
    return first if read.verdict == "progress" else (read.verdict_reason or first)


def _read_view(read: ProgressionRead) -> dict[str, Any]:
    return {
        "sport": read.sport,
        "kind": read.kind,
        "verdict": read.verdict,
        "confidence": read.confidence,
        "reference": read.shape.describe() if read.shape else None,
        "days_since_last": read.days_since_last,
        "why": _one_sentence(_why(read), _WHY_CHARS),
        "candidates": [{"rung": c.rung, "change": c.change} for c in read.candidates[:MAX_CANDIDATES]],
        "also_delivered": _also_delivered(read),
        "rebase": _one_sentence(read.rebase.reason, _WHY_CHARS) if read.rebase and read.rebase.rebased else None,
        "retest_suggested": read.retest_suggested,
    }


def _review_view(review: WeekStimulusReview | None) -> dict[str, Any] | None:
    if review is None:
        return None
    return {
        "counts": {
            "planned_done": len(review.planned_done), "planned_missed": len(review.planned_missed),
            "remaining": len(review.remaining), "unplanned": len(review.unplanned_done),
            "substituted": len(review.substituted_done),
        },
        "impacts": [
            {"impact": i.impact, "date": i.date.isoformat(), "evidence": " ".join(i.evidence)[:_EVIDENCE_CHARS]}
            for i in review.impacts
        ],
    }


def progression_view(
    reads: list[ProgressionRead], review: WeekStimulusReview | None, *, iso_week: str, sport: str | None
) -> dict[str, Any]:
    """The compact `get_progression` result: one row per kind, then the week review. No ledger and no
    nested dose objects."""
    if sport:
        profile = profile_for(sport)
        wanted = profile.name if profile else sport
        reads = [r for r in reads if r.sport == wanted]
    return {"iso_week": iso_week, "kinds": [_read_view(r) for r in reads], "week": _review_view(review)}

