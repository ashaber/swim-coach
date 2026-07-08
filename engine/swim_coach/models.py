"""Pydantic v2 data models for the swim-coach engine.

Every entity that references an athlete carries ``athlete_id: UUID`` (the
``Athlete`` model is the exception — its own ``id`` fills that role). Every
model that maps to a persisted YAML file carries ``schema_version: int = 1``
so future migrations have a field to branch on.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

Sport = Literal["swim_pool", "swim_ow", "strength", "recovery"]

_ISO_WEEK_RE = re.compile(r"^\d{4}-W\d{2}$")
_VALID_ZONES = {"Z1", "Z2", "Z3", "Z4", "Z5"}
_VALID_ANCHORS = {"css_pace", "rpe", "hr"}


class Athlete(BaseModel):
    """The athlete profile: identity, CSS pace, zones, constraints, pool schedule."""

    schema_version: int = 1
    id: UUID
    slug: str
    name: str
    css_pace_s_per_100m: float | None = None
    zones: dict | None = None
    constraints: dict = Field(default_factory=dict)
    pool_schedule: list[str | dict] = Field(default_factory=list)
    # Demographic fields: all optional, defaulting to None, so every
    # existing profile.yaml (with none of these keys) keeps validating
    # unchanged -- additive, no schema_version bump needed. Store dob, not
    # age, so age stays correct as time passes rather than going stale the
    # day after it's recorded; callers derive age from dob relative to
    # `date.today()` (see backend/app/context.py).
    dob: date | None = None
    sex: Literal["male", "female", "other"] | None = None
    height_cm: float | None = Field(default=None, gt=0)
    weight_kg: float | None = Field(default=None, gt=0)


class Event(BaseModel):
    """A target event (e.g. a channel swim) the athlete is training toward."""

    schema_version: int = 1
    id: UUID
    athlete_id: UUID
    name: str
    event_date: date
    distance_m: int = Field(gt=0)
    water_temp_c: float | None = None
    wetsuit: bool = False
    priority: str
    event_format: Literal["single_day", "multi_day_stage"] = "single_day"
    # Default preserves current (pre-Day-4) behavior: every existing Event
    # YAML file with no event_format key validates as "single_day", and
    # plan.py's/adapt.py's single-continuous-long-swim ladder is exactly what
    # generate_week already produced before this field existed. See
    # ROADMAP.md "Event format parameter + long-swim progression" and
    # library/06-long-swim-progression.md.


class Session(BaseModel):
    """A single planned session within a WeekPlan."""

    schema_version: int = 1
    id: UUID
    athlete_id: UUID
    date: date
    sport: Sport
    source: Literal["ai_coach", "pool_coach", "athlete"]
    duration_min: float = Field(gt=0)
    distance_m: int | None = Field(default=None, ge=0)
    intensity: dict
    purpose: str
    structure: str | None = None
    status: Literal["planned", "completed", "skipped", "replaced"] = "planned"

    @field_validator("intensity")
    @classmethod
    def _validate_intensity(cls, v: dict) -> dict:
        zone = v.get("zone")
        anchor = v.get("anchor")
        if zone is not None and zone not in _VALID_ZONES:
            raise ValueError(f"invalid zone: {zone!r}, must be one of {sorted(_VALID_ZONES)}")
        if anchor is not None and anchor not in _VALID_ANCHORS:
            raise ValueError(
                f"invalid anchor: {anchor!r}, must be one of {sorted(_VALID_ANCHORS)}"
            )
        return v


class WeekPlan(BaseModel):
    """One week of planned sessions."""

    schema_version: int = 1
    id: UUID
    athlete_id: UUID
    iso_week: str
    meso_block: str
    focus: str
    target_volume_m: int = Field(ge=0)
    sessions: list[Session] = Field(default_factory=list)
    adaptation_rationale: str | None = None
    draft: bool = False

    @field_validator("iso_week")
    @classmethod
    def _validate_iso_week(cls, v: str) -> str:
        if not _ISO_WEEK_RE.match(v):
            raise ValueError(f"iso_week must look like '2026-W28', got {v!r}")
        return v


class MacroBlock(BaseModel):
    """One block (base/build/peak/taper) within a MacroPlan."""

    name: Literal["base", "build", "peak", "taper"]
    start_date: date
    end_date: date
    weekly_volume_target_m: int = Field(ge=0)
    focus: str


class MacroPlan(BaseModel):
    """The macrocycle scaffold (base -> build -> peak -> taper) toward an event."""

    schema_version: int = 1
    id: UUID
    athlete_id: UUID
    event_id: UUID
    blocks: list[MacroBlock] = Field(default_factory=list)


class WorkoutSet(BaseModel):
    """One set within a completed Workout. Only distance_m is required."""

    reps: int | None = None
    distance_m: int = Field(ge=0)
    interval: str | None = None
    target_pace: str | None = None
    stroke: str | None = None
    description: str | None = None


class Workout(BaseModel):
    """A completed workout, logged manually or ingested from a file/coach text."""

    schema_version: int = 1
    id: UUID
    athlete_id: UUID
    date: date
    sport: Sport
    source: Literal["manual", "fit", "tcx", "csv", "coach_text"]
    distance_m: int = Field(ge=0)
    duration_min: float = Field(gt=0)
    avg_pace_s_per_100m: float | None = None
    rpe: int | None = Field(default=None, ge=1, le=10)
    sets: list[WorkoutSet] = Field(default_factory=list)
    planned_session_id: UUID | None = None
    raw_ref: str | None = None
    notes: str | None = None


FeedbackType = Literal["research_question", "feature_request", "comment", "bug"]
FeedbackSource = Literal["coach", "athlete"]


class Feedback(BaseModel):
    """A durable feedback-log entry.

    Replaces the ephemeral `research/open-questions.jsonl` file (IDEA 005,
    the coach's `log_open_question` tool) -- Cloud Run's disk is wiped on
    scale-to-zero, so a plain file was silently losing every logged research
    gap. Generalized here to also carry athlete-submitted feature requests,
    comments, and bug reports from the app's Feedback tab.

    `athlete_id` is nullable: a research question logged by the coach about
    the athlete's own session is still tied to that athlete, but feedback
    isn't required to be athlete-scoped in general. `context` is a free-form
    bag for type-specific extras (e.g. `{"topic": "taper", "expert_mode":
    true}` for a research_question) -- see backend/app/tools.py and
    backend/app/routes/feedback.py for what each type puts there.
    """

    schema_version: int = 1
    id: UUID
    athlete_id: UUID | None = None
    type: FeedbackType
    source: FeedbackSource
    body: str
    context: dict = Field(default_factory=dict)
    status: str = "open"
    created_at: datetime


class Wellness(BaseModel):
    """A daily wellness check-in."""

    schema_version: int = 1
    id: UUID
    athlete_id: UUID
    date: date
    sleep_quality: int = Field(ge=1, le=5)
    sleep_hours: float = Field(ge=0)
    stress: int = Field(ge=1, le=5)
    soreness: int = Field(ge=1, le=5)
    motivation: int = Field(ge=1, le=5)
    resting_hr: int | None = None
    hrv: float | None = None
    notes: str | None = None
