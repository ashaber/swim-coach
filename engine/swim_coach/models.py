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

# cross_train: logged non-swim endurance activity (kayak, run, ride, ...).
# Counts toward sRPE load (load.py is sport-agnostic there) but never toward
# swim volume (load.py's volume filters allowlist {swim_pool, swim_ow}).
# The planner never schedules it; it exists so real .fit imports of non-swim
# activities aren't mislabeled as swims.
Sport = Literal["swim_pool", "swim_ow", "strength", "recovery", "cross_train"]

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


class WorkoutLap(BaseModel):
    """One device lap/interval, from a FIT `lap` frame.

    Distinct from `WorkoutSet` (which comes from coach-text parsing or a
    generic lap-as-set fallback): a `WorkoutLap` is numeric device telemetry
    (duration/distance/HR/pace), not a free-text description.
    """

    index: int
    start_offset_s: float | None = None
    duration_s: float
    distance_m: float | None = None
    avg_hr: int | None = None
    max_hr: int | None = None
    avg_pace_s_per_100m: float | None = None
    stroke: str | None = None
    num_lengths: int | None = None


class WorkoutLength(BaseModel):
    """One active pool length, from a FIT `length` frame
    (`length_type == "active"` only -- idle lengths become a `WorkoutPause`
    instead, see `parse_files.parse_fit`)."""

    index: int
    lap_index: int | None = None
    duration_s: float
    strokes: int | None = None
    stroke: str | None = None
    swolf: float | None = None


class WorkoutPause(BaseModel):
    """A stopped/idle span within a workout, from one of four sources:
    a FIT `event` timer stop->start pair (`"timer"`), a `record`-frame
    timestamp gap exceeding `analytics.GAP_THRESHOLD_S` (`"gap"`), an idle
    pool length (`"idle_length"`), or a sustained sub-`analytics.
    STATIONARY_SPEED_MPS` span in the speed series (`"stationary"` --
    catches real stops a device with auto-pause off never records as a
    timer event or gap; see `parse_files.parse_fit` and
    `library/11-workout-analytics.md`)."""

    start_offset_s: float
    duration_s: float
    source: Literal["timer", "gap", "idle_length", "stationary"]


class WorkoutAnalytics(BaseModel):
    """Derived workout analytics computed at ingest time by
    `swim_coach.analytics.compute_analytics` -- see that module for the
    pure functions and their library/ citations."""

    cardiac_drift_pct: float | None = None
    split_label: Literal["negative", "even", "positive"] | None = None
    first_half_pace_s_per_100m: float | None = None
    second_half_pace_s_per_100m: float | None = None
    elapsed_min: float | None = None
    moving_min: float | None = None
    pause_total_min: float | None = None
    pause_count: int | None = None
    swolf_first_quarter: float | None = None
    swolf_last_quarter: float | None = None
    swolf_degradation_pct: float | None = None


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
    # Additive fields for the .fit workout-analytics feature (Slice 1).
    # All optional/defaulted so every existing Workout YAML (with none of
    # these keys) keeps validating unchanged -- no schema_version bump.
    avg_hr: int | None = None
    max_hr: int | None = None
    laps: list[WorkoutLap] = Field(default_factory=list)
    lengths: list[WorkoutLength] = Field(default_factory=list)
    pauses: list[WorkoutPause] = Field(default_factory=list)
    analytics: WorkoutAnalytics | None = None
    # Repo-relative path to the columnar time-series sidecar JSON (see
    # store.FileStore.save_series), NOT the Workout YAML itself -- keeps
    # committed YAML human-readable per CLAUDE.md.
    series_ref: str | None = None
    # Dedupe key for auto-ingested workouts, e.g. "intervals:i132013445"
    # (backend/app/sync.py, the intervals.icu -> Garmin auto-sync job).
    # Additive/optional so every existing Workout YAML (with no external_id
    # key) keeps validating unchanged -- no schema_version bump. None for
    # manually logged or CLI-ingested workouts; the sync job is the only
    # writer of a non-None value today.
    external_id: str | None = None
    # Free-text FIT sport/sub_sport detail (e.g. "cycling/mountain",
    # "paddling/kayaking", "walking") for a non-swim `.fit` ingest -- see
    # `parse_files._fit_sport`/`parse_fit`. Additive/optional so every
    # existing Workout YAML (with no sport_detail key) keeps validating
    # unchanged -- no schema_version bump. Always None for swim_pool/
    # swim_ow (the Sport enum already distinguishes pool/open-water, so a
    # detail string there would be redundant).
    sport_detail: str | None = None


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


class AllowedEmail(BaseModel):
    """One entry in the server-side beta allowlist (Slice 1 "verified
    identity" -- see backend/app/routes/auth.py).

    A signed-in Google email that isn't in this list gets `403 {"error":
    "request access"}` from `POST /api/auth/google` and never gets a session
    or an athlete created -- adding a beta user is purely a data change (this
    row), never a code deploy (see `swim_coach.cli`'s `invite`/`list-invites`/
    `revoke-invite` commands).

    `email` is always the normalized (stripped, lowercased) form -- callers
    never see or store the original casing. `athlete_slug` (not `athlete_id`)
    is the identifier here, matching every other StoreInterface method's
    convention (`slug: str` in/out); DbStore's `allowed_emails` table stores
    the FK column (`athlete_id`) underneath and resolves slug<->id at the SQL
    layer via a join, same as `list_feedback`'s `athlete` filter does.

    `athlete_slug is None` (Slice 1 self-service onboarding) means this email
    was invited BEFORE an athlete exists for it -- a PENDING invite. The
    `allowed_emails.athlete_id` column is nullable (`supabase/migrations/
    <onboarding_nullable_athlete>.sql`) precisely so this state is
    representable; `store.add_allowed_email(email)` with no `athlete` creates
    one, and re-inviting the same (normalized) email with an `athlete` later
    upserts it to athlete-bound, same upsert-by-email behavior as always.
    """

    schema_version: int = 1
    email: str
    athlete_slug: str | None = None
    note: str | None = None
    created_at: datetime


class AuthSession(BaseModel):
    """One opaque server-side session (Slice 1 "verified identity").

    Minted by `POST /api/auth/google` after a verified Google ID token
    resolves to an `AllowedEmail`; `token_hash` is the sha256 hex digest of
    the raw session token (the raw token itself is never persisted -- same
    discipline as `Settings.api_token_hash` for the legacy shared token, see
    backend/app/config.py). `require_auth` (backend/app/auth.py) treats a
    session as valid only when `revoked_at is None` and `expires_at` is in
    the future -- both checks happen at the auth layer, not here, so the
    store stays a dumb read/write and the notion of "now" never needs to be
    injected into it.

    Named `AuthSession`, and the DbStore table is `auth_sessions` -- NOT
    `Session`/`sessions` -- because those names are already taken by the
    unrelated WeekPlan-session concept (`Session` above, and the RESERVED
    `sessions` table stub in `supabase/migrations/20260706000000_init.sql`).

    `athlete_slug is None` (Slice 1 self-service onboarding) is an
    ONBOARDING session: minted by `POST /api/auth/google` for an allowlisted
    email with no athlete behind it yet. `require_auth` (backend/app/auth.py)
    resolves such a session to a `Principal(kind="onboarding", athlete=None,
    ...)` -- it can reach `GET /api/me` (so a future frontend can detect
    onboarding mode) but `resolve_athlete` 403s it on every athlete-scoped
    route, since it has no athlete to act as.
    """

    schema_version: int = 1
    token_hash: str
    athlete_slug: str | None = None
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None


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
