"""`WorkoutIntent`: what the coach asks the workout compiler for, in the coach's own terms."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

Zone = Literal["Z1", "Z2", "Z3", "Z4", "Z5"]

# Intent fields a builder may honour; `compile_workout` reports any set field its builder does not.
SIZE_FIELDS = (
    "total_duration_min",
    "total_distance_m",
    "reps",
    "rep_duration_s",
    "rep_distance_m",
    "rest_s",
    "sets",
    "target_zone",
)


class WorkoutIntent(BaseModel):
    """One workout request. `sport` is a `Session.sport` value ("bike", "swim_pool", "swim_ow") or a
    stimulus profile name ("swim"); `archetype` names a registered builder. At least one of a total
    duration, a total distance, or an explicit reps x rep size must be given."""

    schema_version: int = 1
    sport: str
    archetype: str
    total_duration_min: float | None = Field(default=None, gt=0)
    total_distance_m: int | None = Field(default=None, gt=0)
    reps: int | None = Field(default=None, gt=0)
    rep_duration_s: float | None = Field(default=None, gt=0)
    rep_distance_m: int | None = Field(default=None, gt=0)
    rest_s: float | None = Field(default=None, ge=0)
    sets: int | None = Field(default=None, gt=0)
    target_zone: Zone | None = None
    indoor: bool | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _needs_a_size(self) -> "WorkoutIntent":
        sized_reps = self.reps is not None and (self.rep_duration_s or self.rep_distance_m)
        if not (self.total_duration_min or self.total_distance_m or sized_reps):
            raise ValueError(
                "give at least one of total_duration_min, total_distance_m, or reps with "
                "rep_duration_s / rep_distance_m"
            )
        return self
