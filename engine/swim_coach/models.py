"""Pydantic v2 data models for the swim-coach engine.

Every entity that references an athlete carries ``athlete_id: UUID`` (the
``Athlete`` model is the exception — its own ``id`` fills that role). Every
model that maps to a persisted YAML file carries ``schema_version: int = 1``
so future migrations have a field to branch on.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Literal
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
    has_pool_coach: bool = True
    # Defaults True -- zero behavior change for every existing profile.yaml
    # (no key present) unless explicitly set False. True means a real
    # masters/pool coach hands out this athlete's pool-day workout content
    # post-hoc (the system's original, still-default assumption); False
    # means no such coach is on deck, so `generate_week` (plan.py) must
    # author real warm-up/main-set/cool-down structure for those pool-day
    # sessions itself instead of emitting a content-less placeholder.
    email_notifications_enabled: bool = True
    # Settings-tab toggle (coach-mode Q&A notification build): gates BOTH
    # directions of the Resend email wiring in `backend/app/notify.py` --
    # this athlete's own email as a Feedback recipient (coach-reply
    # notifications) AND, when this athlete is acting as a COACH (coaches
    # are themselves athlete accounts, see CoachGrant's docstring), this
    # athlete's own email as a coach notified of a new question. Defaults
    # True per this session's explicit decision -- zero behavior change for
    # every existing profile.yaml (no key present) unless explicitly toggled
    # off, same additive/no-schema_version-bump convention as
    # `has_pool_coach` above.


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
    active: bool = True
    # Soft delete/reactivate flag (backend/app/tools.py's
    # set_event_active_status), NOT a hard delete -- a macro's event_id can
    # still reference an event after the athlete has moved on, and
    # hard-deleting risks orphaning that reference. Defaults True so every
    # existing Event YAML (no active key) and every newly-created event via
    # create_event validates/behaves unchanged -- purely additive, no
    # schema_version bump. Existing event-by-id/-name lookups elsewhere
    # (draft_macro_plan/replace_macro_plan/propose_adaptation) deliberately
    # do NOT filter on this field -- it only changes how the coach *talks
    # about* events in conversation, never which events those lookups find.


class WorkoutTarget(BaseModel):
    """Intensity target for a cardio-style (swim) `WorkoutStep`.

    `basis` distinguishes a TEMPLATE's relative target from a resolved
    WORKOUT's absolute one -- the same shape serves both stages of the
    template/workout split (see `workout_templates.resolve_template`, the
    one place this resolution happens). A template step carries
    `basis="zone"` (e.g. Z3) or `basis="percent_css"` (e.g. 135% of CSS)
    with no athlete-specific numbers; resolving a template against an
    athlete's `css_pace_s_per_100m` (via `zones.zone_table`) fills in
    `basis="absolute"` `low`/`high` pace values (seconds per 100m).
    `rpe`/`open` never need resolving -- already athlete-relative or
    deliberately untargeted. `rpe` reuses `low`/`high` too (a 1-10 value,
    the same scale `Workout.rpe` already uses athlete-facing elsewhere in
    this app) rather than a dedicated field -- `low`/`high` are already
    generic per-`basis` numbers, so a distinct `rpe_value` field would just
    duplicate that shape for no benefit. No engine-generated template sets
    `basis="rpe"` today (every real swim/strength template resolves off CSS
    or is `basis="bodyweight"` -- see `plan.py`'s `_additional_swim_
    structure_template`/`_strength_session_structure_template`); it exists
    for the coach's ad hoc structured-authoring tool (`backend/app/tools.py`'s
    `create_week_plan`/`replace_week_plan` `structured` param) to use on a
    genuinely effort-based day (recovery, technique) where no pace target
    is the right anchor.
    """

    schema_version: int = 1
    basis: Literal["zone", "percent_css", "absolute", "rpe", "open"]
    zone: Literal["Z1", "Z2", "Z3", "Z4", "Z5"] | None = None  # basis="zone"
    low: float | None = None  # percent_css: % of CSS; absolute: pace_s_per_100m; rpe: 1-10
    high: float | None = None  # same units as low


class WorkoutLoad(BaseModel):
    """Resistance target for a strength-style `WorkoutStep` -- same
    relative/resolved split as `WorkoutTarget`, against 1RM instead of CSS.
    """

    schema_version: int = 1
    basis: Literal["bodyweight", "percent_1rm", "absolute", "rpe_only"]
    value: float | None = None  # percent_1rm: 0-100; absolute: resolved weight


class WorkoutStep(BaseModel):
    """One leaf node in a `WorkoutStructure` tree -- a single swim rep/segment
    or a single strength exercise. `kind` is the tagged-union discriminator
    that lets `WorkoutRepeat.steps` hold a mix of steps and nested repeats
    (see `WorkoutStepOrRepeat` below)."""

    schema_version: int = 1
    kind: Literal["step"] = "step"
    label: str  # athlete-facing short name
    role: Literal["warmup", "steady", "interval", "rest", "recovery", "cooldown", "open"]
    duration_kind: Literal["time_s", "distance_m", "reps", "open"]
    duration_value: float | None = None
    target: WorkoutTarget | None = None  # swim/cardio steps
    load: WorkoutLoad | None = None  # strength steps
    modality: Literal["swim", "strength"] = "swim"
    stroke: Literal["free", "back", "breast", "fly", "im", "mixed", "drill"] | None = None
    equipment: list[str] = Field(default_factory=list)  # e.g. ["paddles"]
    exercise_name: str | None = None  # strength steps, e.g. "kettlebell swing"
    reference_url: str | None = None  # technique/demo link
    # Optional coach- or engine-set link (e.g. plan.py's
    # STRENGTH_EXERCISE_REFERENCE_URLS, or a coach-authored step's own URL
    # via session_overrides' `structured`) shown to the athlete as a
    # clickable technique/demo reference and written into the exported FIT
    # step's notes -- see garmin_export.py's `_build_leaf_step`. Additive/
    # optional, same pattern as `Session.structured` above: every existing
    # persisted WorkoutStep has no `reference_url` key and validates
    # unchanged as `reference_url=None`; no schema_version bump.


class WorkoutRepeat(BaseModel):
    """A loop wrapper around an ordered list of steps (nested repeats
    allowed, rarely used). `repeat_mode` matters more than it looks -- a
    plain `count` (execute N times) can't express EMOM ("every minute on
    the minute" -- a new round starts on a fixed interval regardless of how
    long the round took, `for_duration` + `interval_s`) or AMRAP (as many
    rounds/reps as possible in a time window, `amrap` + `duration_s`).
    Without this distinction, `isEMOM`/`isAMRAP` become underivable and
    collapse back into exactly the kind of hand-typed, drift-prone tag this
    model is designed to avoid -- so this needs to be right at the model
    level, not patched on later.
    """

    schema_version: int = 1
    kind: Literal["repeat"] = "repeat"
    repeat_mode: Literal["count", "for_duration", "amrap"] = "count"
    count: int | None = None  # repeat_mode == "count"
    duration_s: float | None = None  # for_duration/amrap: total window length
    interval_s: float | None = None  # for_duration: e.g. 60 for classic EMOM
    steps: list["WorkoutStepOrRepeat"]  # nested loops allowed, rarely used


# Tagged union on `kind` so pydantic v2 can discriminate step vs. repeat
# nodes in `WorkoutRepeat.steps` / `WorkoutStructure.items` without a class
# hierarchy (WorkoutStep/WorkoutRepeat stay flat siblings, matching this
# file's no-inheritance house style).
WorkoutStepOrRepeat = Annotated[WorkoutStep | WorkoutRepeat, Field(discriminator="kind")]
WorkoutRepeat.model_rebuild()


class WorkoutStructure(BaseModel):
    """The canonical structured workout intermediate representation (IR).
    Both a workout TEMPLATE (relative targets) and a resolved WORKOUT
    (absolute targets) use this same shape -- see `WorkoutTarget`/
    `WorkoutLoad`'s `basis` field and `workout_templates.resolve_template`.
    Prose (`Session.structure`) and any future device export (Garmin, etc.)
    are both just renderings of this IR, never the source of truth.
    """

    schema_version: int = 1
    items: list[WorkoutStepOrRepeat]  # top-level ordered sequence


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
    structured: WorkoutStructure | None = None
    # Canonical structured IR alongside the legacy prose `structure` field
    # (kept, not replaced -- see workout_templates.py / plan.py module
    # docstrings for the migration rationale). Additive/optional: every
    # existing persisted Session (YAML file or DB jsonb row) has no
    # `structured` key and validates unchanged as `structured=None`; no
    # schema_version bump, no backfill, same pattern as every other
    # additive field in this file.
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


class RaceWeekChecklistItem(BaseModel):
    """One dated, categorized action item surfaced on the final taper week
    immediately preceding an athlete's active A-priority event -- see
    `engine/swim_coach/plan.py`'s `_race_week_checklist` for how these are
    computed and `library/16-race-week.md` for the citations/rationale
    behind each category.

    `date` is the specific calendar date the item applies to, computed
    directly from `Event.event_date` -- it is deliberately NOT guaranteed
    to fall within the parent `WeekPlan`'s own Monday-Sunday span. A race
    that isn't itself on a Monday (the common case) pushes windows like the
    36-72h pre-race carbohydrate-load onto calendar days that land in the
    following week -- the one containing the event itself, which
    `plan.scaffold_macro`/`generate_week` deliberately don't model as a
    macro block (see that module's docstring: "race week itself is ...
    handled separately"). A per-session field couldn't represent a date
    outside the week it's attached to; this dedicated, independently-dated
    list can.

    `category` distinguishes the three genuinely different kinds of content
    this list can carry, each with its own timing/evidence basis -- see
    `plan.py`'s citation comments for each:
      - "carb_load": the 36-72h pre-race carbohydrate-loading window.
      - "bodywork": the 3-5-day-out light bodywork/massage window.
      - "logistics": athlete-specific event-logistics checklist items
        (travel/acclimatization, fueling-plan rehearsal, support-crew
        confirmation) derived from the event's own fields, not universal
        taper science.
    """

    schema_version: int = 1
    date: date
    category: Literal["carb_load", "bodywork", "logistics"]
    label: str


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
    race_week_checklist: list[RaceWeekChecklistItem] = Field(default_factory=list)
    # Populated only for the final week of a taper block immediately
    # preceding the athlete's active, A-priority target event -- see
    # `plan.generate_week`'s `event` parameter and `_race_week_checklist`.
    # Additive/optional: every existing persisted WeekPlan (YAML file or DB
    # jsonb row) has no `race_week_checklist` key and validates unchanged as
    # an empty list; no schema_version bump, same pattern as every other
    # additive field in this file.

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
    # 0-10 Foster CR-10 modified-Borg scale (0 = "Rest / Nothing at all"),
    # see library/19-srpe-protocol.md -- not 1-10, so 0 is a real, valid
    # response, not an unreachable floor.
    rpe: int | None = Field(default=None, ge=0, le=10)
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
    # When this workout record was actually saved (DbStore: the real
    # `workouts.created_at` DB column, surfaced read-only -- see
    # store_db.row_to_workout; FileStore: always None, no equivalent
    # durable "first saved" timestamp exists on disk). Never written back
    # into the persisted JSONB blob -- read-derived only. Additive/
    # optional so every existing Workout YAML/row keeps validating
    # unchanged -- no schema_version bump.
    logged_at: datetime | None = None
    # Real workout end-time estimate: populated from parse_fit's FIT
    # session.start_time (+ duration_min) when a real .fit start_time was
    # captured -- see parse_files.parse_fit. None for tcx/csv ingests (no
    # equivalent extracted field) and for any .fit without a session
    # start_time. Additive/optional so every existing Workout YAML/row
    # keeps validating unchanged -- no schema_version bump.
    started_at: datetime | None = None


class WorkoutQuality(BaseModel):
    """Per-workout planned-vs-actual interpretation, computed by
    `swim_coach.quality.workout_quality` -- NOT persisted (a
    response/computed shape only, hence no `schema_version`).

    Distinct from `load.compliance`'s aggregate weekly-volume-percentage
    number, which remains this codebase's sole authoritative "compliance":
    this is one workout matched against (at most) one planned `Session`, not
    a sum across a week. Named `WorkoutQuality` (not `WorkoutCompliance`,
    its original Phase-1 name) specifically to avoid colliding with that
    aggregate -- see `IDEAS.md`'s resolved IDEA 006 and `quality.py`'s
    module docstring for the full distinction and the Phase-1
    `intensity_match` gap.
    """

    matched: bool
    distance_delta_pct: float | None = None
    duration_delta_pct: float | None = None
    load_delta_pct: float | None = None
    # Percent difference between this workout's actual training load
    # (`swim_coach.load.session_load`) and its matched session's projected
    # load (`swim_coach.load.session_target_load_au`) -- `None` when
    # unmatched, same convention as `distance_delta_pct`/
    # `duration_delta_pct` above. Part of the training-load validation
    # mechanism (see `quality.workout_quality`'s docstring and
    # `cli.py`'s `validate-load-model` diagnostic) -- informational only,
    # never wired into `adapt.py`.
    intensity_match: Literal["match", "mismatch", "unknown"] = "unknown"
    quality_summary: str | None = None


FeedbackType = Literal[
    "research_question", "feature_request", "comment", "bug", "question", "coach_review"
]
# "question" -- athlete-initiated, expects an answer (workout-linked via
# `workout_id`, or direct-to-coach). "coach_review" -- AI-flagged
# `needs_human_review=True` with no research gap behind it (pain/safety
# escalations, an explicit "talk to my coach" request, or any other
# high-stakes judgment call the AI declines to make alone).
FeedbackSource = Literal["coach", "athlete"]


class Feedback(BaseModel):
    """A durable feedback-log entry.

    Replaces the ephemeral `research/open-questions.jsonl` file (IDEA 005,
    the coach's `log_open_question` tool) -- Cloud Run's disk is wiped on
    scale-to-zero, so a plain file was silently losing every logged research
    gap. Generalized here to also carry athlete-submitted feature requests,
    comments, and bug reports from the app's Feedback tab, and (coach-mode
    Chunk A) athlete questions and human-coach review/reply state.

    `athlete_id` is nullable: a research question logged by the coach about
    the athlete's own session is still tied to that athlete, but feedback
    isn't required to be athlete-scoped in general. `context` is a free-form
    bag for type-specific extras (e.g. `{"topic": "taper", "expert_mode":
    true}` for a research_question) -- see backend/app/tools.py and
    backend/app/routes/feedback.py for what each type puts there.

    `type` and `needs_human_review` are orthogonal: a `"research_question"`
    row can ALSO carry `needs_human_review=True` when it's both
    under-evidenced AND urgent -- one row, not a fork into a second entry.
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
    # Human-coach-review fields (coach-mode Chunk A). All optional/defaulted
    # so every existing Feedback YAML/row (with none of these keys) keeps
    # validating unchanged -- additive, no schema_version bump needed, same
    # pattern as `Workout.external_id` above.
    workout_id: UUID | None = None  # links a comment/question to a Workout
    # `session_date`/`session_sport` link a question to a PLANNED Session
    # instead of a completed Workout -- mutually exclusive with `workout_id`
    # (enforced by the route, not here; see backend/app/routes/feedback.py).
    # Linking by (date, sport) rather than a raw Session.id is deliberate:
    # `Session.id` does NOT survive `replace_week_plan` (every session gets
    # a fresh uuid4() on a full week regenerate -- see plan.py/tools.py), so
    # a question linked by raw id would silently orphan the moment its week
    # is regenerated. (date, sport) is the same stability fallback
    # `quality.match_workout_to_session` already trusts for matching a
    # completed workout to its planned session. Both optional/defaulted so
    # every existing persisted Feedback row (with neither key) keeps
    # validating unchanged -- additive, no schema_version bump, same
    # pattern as `workout_id` above.
    session_date: date | None = None
    session_sport: Sport | None = None
    needs_human_review: bool = False  # independently settable by AI or athlete
    ai_provisional_answer: str | None = None
    coach_athlete_id: UUID | None = None  # which coach (an athlete_id) replied
    coach_reply: str | None = None
    coach_reply_at: datetime | None = None


CoachGrantStatus = Literal["active", "revoked"]
ChatVisibility = Literal["full", "shared_only"]


class CoachGrant(BaseModel):
    """One athlete's grant of coach access to another athlete (coaches in
    this system are themselves athlete accounts -- e.g. Tim, a consulting
    physiologist with no training data of his own, still has an
    `athletes/tim/` profile purely to hold a session identity; a
    `CoachGrant` just references the athletes table twice rather than
    needing a separate Coach identity model).

    `chat_visibility` controls whether the granted coach can see the
    athlete's full AI-chat history or only messages the athlete explicitly
    shares -- defined here now but NOT YET ENFORCED anywhere (chat isn't
    durably persisted at all yet); defaults to the more private
    `"shared_only"` so an athlete who never touches the setting doesn't
    over-share by default once enforcement lands.
    """

    schema_version: int = 1
    id: UUID
    coach_athlete_id: UUID  # the coach's own athlete row
    athlete_id: UUID        # the athlete being coached
    status: CoachGrantStatus = "active"
    chat_visibility: ChatVisibility = "shared_only"
    granted_at: datetime
    revoked_at: datetime | None = None


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

    `pending_email` (Slice 2 of self-service onboarding, `supabase/
    migrations/<onboarding_session_email>.sql`) is the verified Google email
    this session belongs to -- set ONLY for an onboarding session
    (`athlete_slug is None`); always `None` for an athlete-bound session,
    which already knows who it is via `athlete_slug`. It's what lets
    `POST /api/onboard` (backend/app/routes/onboard.py) know which PENDING
    `allowed_emails` row it's completing without trusting anything the
    client claims about its own identity -- the email is read off the
    server-side session, never the request body.
    """

    schema_version: int = 1
    token_hash: str
    athlete_slug: str | None = None
    pending_email: str | None = None
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None


class Wellness(BaseModel):
    """A daily wellness check-in.

    The four subjective fields (sleep_quality/stress/soreness/motivation) and
    sleep_hours are optional -- required historically, but an automated
    intervals.icu sync (backend/app/sync.py) can only ever populate the
    objective resting_hr/hrv fields, never a fabricated 1-5 subjective rating
    (same "real load exists regardless of whether it was surveyed"
    principle used elsewhere in this engine). Additive/optional change, no
    schema_version bump -- every existing row already has all five populated.
    """

    schema_version: int = 1
    id: UUID
    athlete_id: UUID
    date: date
    sleep_quality: int | None = Field(default=None, ge=1, le=5)
    sleep_hours: float | None = Field(default=None, ge=0)
    stress: int | None = Field(default=None, ge=1, le=5)
    soreness: int | None = Field(default=None, ge=1, le=5)
    motivation: int | None = Field(default=None, ge=1, le=5)
    resting_hr: int | None = None
    hrv: float | None = None
    notes: str | None = None
    # Provenance, mirroring Workout.source's existing convention. `None` for
    # every pre-existing row (unknown/manual provenance, written before this
    # field existed) -- additive/optional, no schema_version bump.
    source: Literal["manual", "intervals_sync"] | None = None
