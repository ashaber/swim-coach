"""`compile_workout`: intent in, exact structured workout (plus prose, dose, totals) out.

Sport-neutral. The builder owns every sport difference; this module only measures what the builder
produced with the same stimulus code that measures every other session, and reports every place the
result differs from what was asked (never a silent clamp).
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import date

from pydantic import BaseModel, Field

from swim_coach.models import Athlete, Session, WorkoutStructure
from swim_coach.stimulus import REST_ROLES, SportProfile, StimulusDose, planned_dose, profile_for, walk_leaves
from swim_coach.workout_builders.intent import SIZE_FIELDS, WorkoutIntent
from swim_coach.workout_builders.registry import WorkoutBuilder, get_builder
from swim_coach.workout_templates import render_prose

# Coach judgment: totals within this are "as asked" (rounding in warm-up/cool-down sizing).
TOTAL_TOLERANCE_MIN = 0.5
TOTAL_TOLERANCE_M = 50
_FIXED_ID = uuid.UUID(int=0)
_FIXED_DATE = date(2000, 1, 3)


class CompiledWorkout(BaseModel):
    sport: str
    archetype: str
    structured: WorkoutStructure
    prose: str
    dose: StimulusDose | None
    duration_min: float
    distance_m: int | None
    intensity: dict
    adjustments: list[str] = Field(default_factory=list)


def structure_totals(structure: WorkoutStructure, athlete: Athlete, profile: SportProfile) -> tuple[float, int | None]:
    """(minutes, metres or None) of the whole structure, by the profile's own leaf arithmetic."""
    seconds = metres = 0.0
    leaves = walk_leaves(structure, ftp_watts=athlete.ftp_watts, css_pace_s_per_100m=athlete.css_pace_s_per_100m)
    for leaf in leaves:
        s, m = profile.leaf_work(dataclasses.replace(leaf, rank=leaf.rank or 1), athlete)
        seconds += (s or 0.0) * leaf.reps
        if leaf.role not in REST_ROLES:
            metres += (m or 0.0) * leaf.reps
    return seconds / 60.0, (round(metres) or None)


def measure_dose(
    structure: WorkoutStructure, intensity: dict, minutes: float, metres: int | None, sport: str, athlete: Athlete
) -> StimulusDose | None:
    """The stimulus dose of a compiled structure, measured by `stimulus.planned_dose` like any session."""
    session = Session(
        id=_FIXED_ID,
        athlete_id=athlete.id,
        date=_FIXED_DATE,
        sport=sport,
        source="ai_coach",
        duration_min=minutes,
        distance_m=metres,
        intensity=intensity,
        purpose="compiled workout",
        structured=structure,
    )
    return planned_dose(session, athlete)


def _unused_field_notes(intent: WorkoutIntent, builder: WorkoutBuilder) -> list[str]:
    return [
        f"{name}={getattr(intent, name)} is not used by {builder.archetype}"
        for name in SIZE_FIELDS
        if getattr(intent, name) is not None and name not in builder.params
    ]


def _total_notes(intent: WorkoutIntent, builder: WorkoutBuilder, minutes: float, metres: int | None) -> list[str]:
    notes: list[str] = []
    asked = intent.total_duration_min
    if asked and "total_duration_min" in builder.params and abs(minutes - asked) > TOTAL_TOLERANCE_MIN:
        notes.append(f"asked {asked:g} min total; built {minutes:.0f} min")
    asked_m = intent.total_distance_m
    if asked_m and metres and "total_distance_m" in builder.params and abs(metres - asked_m) > TOTAL_TOLERANCE_M:
        notes.append(f"asked {asked_m} m total; built {metres} m")
    return notes


def compile_workout(intent: WorkoutIntent, athlete: Athlete) -> CompiledWorkout:
    """Build the workout `intent` asks for. Raises `ValueError` for an unknown sport or archetype
    (listing what exists). Anything the builder could not honour exactly is in `adjustments`."""
    builder = get_builder(intent.sport, intent.archetype)
    result = builder.build(intent, athlete)
    profile = profile_for(intent.sport) or profile_for(sorted(builder.sports)[0])
    minutes, metres = structure_totals(result.structure, athlete, profile)
    minutes = result.duration_min or minutes
    adjustments = list(result.adjustments)
    adjustments += _unused_field_notes(intent, builder)
    adjustments += _total_notes(intent, builder, minutes, metres)
    dose = measure_dose(result.structure, result.intensity, minutes, metres, intent.sport, athlete)
    if dose is None or not builder.delivers(dose.kind):
        adjustments.append(
            f"{builder.archetype} declares {builder.kind} but the compiled workout measures "
            f"{dose.kind if dose else 'no stimulus'}"
        )
    return CompiledWorkout(
        sport=intent.sport,
        archetype=intent.archetype,
        structured=result.structure,
        prose=render_prose(result.structure),
        dose=dose,
        duration_min=minutes,
        distance_m=metres,
        intensity=result.intensity,
        adjustments=adjustments,
    )
