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

from pydantic import BaseModel, Field, field_validator, model_validator

# cross_train: logged non-swim endurance activity (kayak, run, ride, ...).
# Counts toward sRPE load (load.py is sport-agnostic there) but never toward
# swim volume (load.py's volume filters allowlist {swim_pool, swim_ow}).
# The planner never schedules it; it exists so real .fit imports of non-swim
# activities aren't mislabeled as swims.
#
# bike: a first-class, PLANNABLE cycling sport (engine/cycling-coach branch,
# IDEA 008 use case 5) -- deliberately NOT reusing `cross_train`, which is
# explicitly documented above as a logging-only catch-all the planner never
# schedules. `bike` is the opposite: `plan.generate_week` can author real
# bike sessions for it (see that module's `primary_sport` parameter). Road/
# MTB/cyclocross/gravel sub-classification reuses the EXISTING
# `Workout.sport_detail` free-text field below (confirmed real production
# values: "cycling/mountain", "cycling/road", "cycling/gravel_cycling",
# "cycling/cyclocross") rather than a new field -- see that field's own
# comment.
Sport = Literal["swim_pool", "swim_ow", "strength", "recovery", "cross_train", "bike"]

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
    sports: list[Sport] | None = None
    # Which sport(s) this athlete's OWN training actually spans -- IDEA 008's
    # "never surface cycling guidance to a swim-only athlete" hard
    # requirement (`engine/cycling-coach` branch), the structural half of
    # the constraint `library/23-cycling-training.md`'s own guidance-scoping
    # note names. `None` (the default) means "not yet declared" -- every
    # existing athlete's profile.yaml has no `sports` key today. Additive/
    # optional, no schema_version bump, same convention as every other
    # additive field in this file.
    #
    # **Do not read this raw field for sport-scope routing -- use
    # `effective_sports` below.** A real review bug (PR #167 review,
    # Finding 1): `backend/app/context.py`'s sport-scope filtering used to
    # treat `sports is None` as "apply no filtering at all" (i.e. every
    # sport), which meant cycling library content reached 100% of real
    # athletes -- every one of whom has `sports=None` today, since setting
    # it on real athlete data was explicitly deferred. `None` must mean
    # "not yet declared, so assume swim-only" (this project's actual
    # population today), never "declared as every sport."

    @property
    def effective_sports(self) -> list[Sport]:
        """`sports` resolved to a concrete list for any consumer that needs
        to know which sport(s) actually ground this athlete's routing/
        guidance scope -- an unset `sports` field behaves as swim-only
        (`["swim_pool", "swim_ow"]`), matching every real athlete's actual
        training today, NEVER as "every sport." See the bug this fixes in
        `sports`'s own comment above. Prefer this over reading `.sports`
        directly wherever a concrete sport list is actually needed (sport-
        scope library routing today); `.sports` itself stays `None`-capable
        for callers that specifically care whether the athlete has ever
        declared it at all.
        """
        return self.sports if self.sports is not None else ["swim_pool", "swim_ow"]

    lthr_bpm: int | None = None
    # Lactate-threshold heart rate (bpm) -- a physiological anchor the
    # athlete supplies directly (e.g. from a field test, or read off a
    # platform like intervals.icu/Garmin that already estimates it), the
    # same role `css_pace_s_per_100m` plays for swim pace: a real,
    # athlete-specific reference point rather than a population default or
    # an incidentally-observed extreme. Used by `load.py`'s HR-based TRIMP
    # tier to rescale onto the same "100 = one hour at threshold" unit TSS
    # uses for power -- see that module's `_normalize_trimp_to_lthr_hour`
    # and `library/15-tiered-session-load.md`. `None` (the default) leaves
    # tier 2 exactly as before -- raw, un-normalized TRIMP -- for every
    # existing profile.yaml (no key present) and any athlete who hasn't
    # set one. Additive, no schema_version bump.
    ftp_watts: float | None = None
    # Functional Threshold Power (watts) -- cycling's own physiological
    # anchor, the same role `css_pace_s_per_100m` plays for swim pace and
    # `lthr_bpm` plays for HR (engine/cycling-coach Part C). Used by
    # `zones.bike_zone_table` (via `plan._bike_step`/`_bike_week_sessions`)
    # to resolve a bike session's %FTP zone into absolute watts, and by
    # `backend/app/zwo_export.build_zwo_export` to express a `.zwo` file's
    # power targets as fractions of a real, athlete-specific FTP rather than
    # an arbitrary one supplied per-request. `None` (the default) leaves
    # every existing profile.yaml (no key present) validating unchanged --
    # `generate_week`'s bike path already tolerates `ftp_watts=None`
    # gracefully (zone-name-only targets, no absolute watts), and the `.zwo`
    # export route/tool return a clear 422 rather than guessing at a number
    # when it's missing. Additive, no schema_version bump.


class Event(BaseModel):
    """A target event (e.g. a channel swim) the athlete is training toward."""

    schema_version: int = 1
    id: UUID
    athlete_id: UUID
    name: str
    event_date: date
    target_metric: Literal["distance_m", "duration_min", "load_au"] = "distance_m"
    # Discriminator for what this event's target is measured in -- follows
    # this codebase's own `basis`-discriminator idiom (see WorkoutTarget/
    # WorkoutLoad above: a discriminator field + generic value field(s)
    # reused across variants, documented per-variant in comments) rather
    # than a true `Field(discriminator=...)` tagged union of separate
    # classes (that mechanism exists here too -- WorkoutStepOrRepeat -- but
    # is reserved for structurally different tree nodes, not this case).
    # No single universal target metric exists across sports (multi-sport-
    # unlock design discussion, ROADMAP.md IDEA 007-010): duration+intensity
    # is what actually tells you something for cycling ("a 2-hour endurance
    # ride tells me what I need to know"); distance is genuinely the right
    # universal unit for swimming, especially open water where pace is
    # unknown; strength is measured in cumulative work (e.g. total lbs
    # lifted). Defaults to "distance_m" so every existing Event YAML (no
    # target_metric key) validates unchanged and means exactly what it
    # always meant -- additive, no schema_version bump.
    primary_sport: Literal["swim", "bike"] = "swim"
    # Which sport this event is FOR -- deliberately the same `Literal["swim",
    # "bike"]` shape `plan.generate_week`'s own `primary_sport` parameter
    # already uses (not the finer-grained `Sport` enum `Workout`/`Session`
    # rows use, which distinguishes `swim_pool`/`swim_ow` -- an event's
    # primary discipline doesn't need that granularity). Deliberately
    # ORTHOGONAL to `target_metric` above: `target_metric` says what UNIT
    # this event's target is measured in (distance/duration/load),
    # `primary_sport` says WHICH SPORT it's for -- do not infer one from the
    # other anywhere, going forward. That conflation was a real, audited bug
    # (threshold-history build): `backend/app/tools.py`'s
    # `_handle_propose_adaptation` and `cli.py`'s `_cmd_adapt` used to derive
    # `primary_sport = "bike" if event.target_metric != "distance_m" else
    # "swim"` -- invisible only while bike was the sole non-swim sport and
    # happened to always use `duration_min`; a future running event (running
    # is typically ALSO distance-based, e.g. a 5K) would be misidentified as
    # "swim" under that inference. A plain, flat `Literal` string list (not
    # a richer type) is the right shape for "cheap to extend later, don't
    # over-engineer now" -- same precedent as `ThresholdRecord.metric` and
    # `00-conventions.md`'s `[EVIDENCE: <discipline>]` tag -- extend the
    # Literal with each new sport as it's actually built (running next, per
    # ROADMAP.md). Defaults "swim" so every existing Event YAML (no
    # primary_sport key) validates unchanged and means exactly what it
    # always meant -- additive, no schema_version bump, matching every other
    # additive field in this file.
    distance_m: int | None = Field(default=None, gt=0)
    # Relaxed from required (`Field(gt=0)`) to optional -- required in
    # practice (enforced by `_validate_target_metric_fields` below) only
    # when target_metric == "distance_m". Deliberately KEPT AS ITS OWN
    # NAMED FIELD rather than folded into `target_value` below -- a
    # deliberate departure from WorkoutTarget/WorkoutLoad's pure single-
    # generic-value idiom. `distance_m` is consumed BY NAME across ~10 real
    # call sites (the create_event tool schema, the onboarding route, the
    # PWA plan-view form/validation and long-swim-ladder rendering, the
    # JSON export, and 20+ existing tests) -- renaming it would be a much
    # wider, riskier blast radius than this build needs.
    target_value: float | None = None
    # Meaning depends on target_metric: minutes when target_metric ==
    # "duration_min", AU (arbitrary training-load units, see load.py's
    # module docstring) when target_metric == "load_au". Unused/None when
    # target_metric == "distance_m" (distance_m carries that meaning
    # instead, see above). Required in practice (enforced below) whenever
    # target_metric != "distance_m".
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

    @model_validator(mode="after")
    def _validate_target_metric_fields(self) -> "Event":
        """Cross-field rule: `distance_m` is required when target_metric ==
        "distance_m"; `target_value` is required otherwise. New precedent --
        this codebase has zero existing `model_validator`s (only
        `field_validator`s on individual fields) before this one; kept
        deliberately small and narrowly scoped to this single cross-field
        rule, not a general validation-framework expansion.
        """
        if self.target_metric == "distance_m":
            if self.distance_m is None:
                raise ValueError(
                    "distance_m is required when target_metric == 'distance_m'"
                )
        elif self.target_value is None:
            raise ValueError(
                f"target_value is required when target_metric is {self.target_metric!r} "
                "(not 'distance_m')"
            )
        return self


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

    `basis="power_w"` (engine/cycling-coach Part C -- delivery/logging):
    the bike-modality RESOLVED counterpart to `basis="absolute"` above --
    `low`/`high` are absolute watts (not pace), populated by
    `plan._bike_step` from `zones.bike_zone_table` once an athlete's
    `ftp_watts` is known. `basis="zone"` still covers the bike case where
    FTP is unknown (the zone name alone, e.g. "Z2", for a device to apply
    its own configured power zone -- same graceful partial-data fallback
    `_bike_step`'s docstring documents); `"power_w"` is only ever reached
    once real watts numbers exist. Not reusing `"absolute"` itself: that
    basis's `low`/`high` are documented everywhere else in this codebase
    (`workout_templates.resolve_template`, `garmin_export._apply_target`)
    as seconds-per-100m pace specifically, and silently overloading its
    unit by modality would be a real footgun for any future reader who
    forgets to check `WorkoutStep.modality` first.
    """

    schema_version: int = 1
    basis: Literal["zone", "percent_css", "absolute", "rpe", "open", "power_w"]
    zone: Literal["Z1", "Z2", "Z3", "Z4", "Z5"] | None = None  # basis="zone"
    low: float | None = None  # percent_css: % of CSS; absolute: pace_s_per_100m; rpe: 1-10; power_w: watts
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
    role: Literal["warmup", "steady", "interval", "rest", "recovery", "cooldown", "open", "ramp"]
    # "ramp" added for the bike ramp-test generator (`plan._bike_ramp_test_
    # structure` -- threshold-history build): a genuine mid-workout power
    # PROGRESSION (start low, climb steadily to a real ceiling), unlike
    # every other role's flat/fixed target. Before this, no real producer
    # in this codebase ever emitted a role whose `WorkoutTarget` low/high
    # bounds were meant to be read as "climbs from low to high over the
    # step's duration" rather than "a flat target band" -- `zwo_export.
    # _convert_leaf`'s own `<Ramp>`-element branch existed only as
    # defensive/forward-compatible dead code, documented there as
    # UNREACHABLE via any value of this Literal that existed at the time.
    # "ramp" is the first role that actually reaches it.
    duration_kind: Literal["time_s", "distance_m", "reps", "open"]
    duration_value: float | None = None
    target: WorkoutTarget | None = None  # swim/cardio steps
    load: WorkoutLoad | None = None  # strength steps
    modality: Literal["swim", "strength", "bike"] = "swim"
    # "bike" added alongside `Sport`'s own "bike" value (engine/cycling-coach
    # branch) -- a harder, per-step constraint than `Session.sport` since a
    # single WorkoutStructure tree's steps are all one modality in practice
    # today (see `workout_templates.render_main_set`'s modality-uniformity
    # assumption). Real cycling `WorkoutStep`s ARE now constructed by
    # `plan._bike_session_structure` (engine/cycling-coach Part C) -- a
    # minimal warm-up/main-block/cool-down shape, the same
    # deferred-until-delivery-stage groundwork this comment originally
    # flagged. Additive/no schema_version bump.
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
    is_indoor: bool | None = None
    # Engine/cycling-coach Part C (delivery/logging): the lightweight signal
    # this build's own brief asked for -- "does this bike session need the
    # outdoor Garmin/intervals.icu push, or the indoor/trainer .zwo export"
    # (see `backend/app/garmin_push.py` and `swim_coach.zwo_export`). `None`
    # (the default) means "not indoor" for gating purposes -- every real bike
    # session this engine currently generates (`plan._bike_week_sessions`)
    # is a generic outdoor Z2/Z3 ride (matching this athlete's real,
    # already-flowing production `.fit` data: "cycling/mountain",
    # "cycling/road", all outdoor sub_sports), so defaulting to the outdoor
    # push path is the honest default, not a guess. Only ever meaningful for
    # `sport == "bike"` today; every other sport ignores this field. Purely
    # additive/optional, no schema_version bump, same convention as every
    # other additive field in this file.

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
    """One block within a MacroPlan.

    `"base"`/`"build"`/`"peak"`/`"taper"` are `plan.scaffold_macro`'s
    original base->build->peak->taper shape. `"hold"`/`"sharpen"` are the
    established-base, short-runway "sharpening" shape's own two new phases
    (`plan.scaffold_sharpening_macro`) -- Issurin's block-periodization
    "transmutation" block, plus an optional flat maintenance phase ahead of
    it when the runway allows more than the minimum -- see that function's
    own docstring for the full design and citation. That second shape
    reuses `"taper"` UNCHANGED (same block, same volume-decay math,
    `plan.generate_week`'s existing taper handling) rather than inventing a
    third taper variant.

    **Scope note, sharpening-macro build:** `scaffold_sharpening_macro` is a
    separate function, never called from any swim-path code -- as of this
    build, only `backend/app/tools.py`'s `draft_macro_plan` handler ever
    invokes it, and only when the target event's `primary_sport == "bike"`.
    `plan.generate_week`'s swim-primary path (`_no_coach_pool_purpose`,
    `_additional_swim_structure`, the taper-decay long-swim cap) is
    therefore never handed a `"hold"`/`"sharpen"`-named block in practice,
    and was NOT audited or extended to specifically understand those two
    names in this build -- deliberately out of scope, see
    `scaffold_sharpening_macro`'s own docstring.
    """

    name: Literal["base", "build", "peak", "taper", "hold", "sharpen"]
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


class IntervalEffort(BaseModel):
    """One detected sustained effort within a ride, assessed against a
    target when one is known -- produced by
    `swim_coach.interval_analysis.assess_effort`. All quality fields are
    optional: a ride with a power meter fills them in, an HR-only ride
    leaves the power/target ones `None`. See `library/11-workout-
    analytics.md` ("Deterministic interval detection", "Interval quality
    vs. target", "Terrain-confound detection")."""

    n: int  # 1-based effort index within the ride, in time order
    start_s: float
    duration_s: float
    avg_w: float | None = None
    avg_hr: int | None = None
    target_w: float | None = None
    pct_of_target: float | None = None  # avg_w / target_w * 100
    avg_vs_target_w: float | None = None  # avg_w - target_w (signed)
    time_in_band_pct: float | None = None  # % of samples within +/-5% of target
    fade_pct: float | None = None  # (first-third mean - last-third mean) / first-third mean * 100
    hr_drift_bpm: float | None = None  # last-third mean HR - first-third mean HR
    grade_delta_pct_pts: float | None = None  # first-third mean grade - last-third, in percentage points
    terrain_flag: str | None = None
    verdict: str


class WorkoutIntervals(BaseModel):
    """The compact interval block on `WorkoutAnalytics` -- deterministic
    output of `swim_coach.interval_analysis.analyze`, computed inside
    `compute_analytics` for `sport == "bike"` rides that carry a power (or,
    failing that, HR) series. `None` on `WorkoutAnalytics` for every other
    sport. `decoupling_tightened_pct` SUPPLEMENTS `WorkoutAnalytics.
    cardiac_drift_pct` (it does not replace it) -- it's the same first-half-
    vs-second-half efficiency-factor calc restricted to genuinely working
    samples, so it's meaningful on a stop-start dirt-road ride where the
    unfiltered number is not; `decoupling_note` says which."""

    schema_version: int = 1
    efforts_detected: int
    detection_basis: Literal["power", "hr"]
    matched_to_prescription: bool = False
    prescribed_count: int | None = None
    efforts: list[IntervalEffort] = Field(default_factory=list)
    decoupling_tightened_pct: float | None = None
    decoupling_note: str | None = None


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
    # Interval-analyzer block (deterministic, no LLM) -- populated only for
    # `sport == "bike"` rides with a usable power/HR series; `None` for
    # every swim/kayak/strength workout. See `WorkoutIntervals` and
    # `swim_coach.interval_analysis`.
    intervals: WorkoutIntervals | None = None


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


class HealthStatus(BaseModel):
    """A durable, append-only LOG of an athlete's injury/illness/medical
    status over time -- built after a real incident exposed that this
    system had NO durable record of health status anywhere: `Wellness.
    soreness` is just a daily 1-5 self-rating with no memory beyond "today,"
    `backend/app/routes/chat.py` persists nothing server-side (chat history
    is client-supplied per request, so a raw injury description that never
    triggers a tool call vanishes the moment the browser tab closes), and
    there was no model of this shape at all. CLAUDE.md's own standing safety
    rail -- "any pain report -> stop-and-assess" -- was enforced ONLY as
    prompt-level guidance with zero durable backing before this model
    existed.

    This is a LOG, not a single mutable field, deliberately mirroring
    `Feedback` above: health status evolves over days/weeks, and the
    HISTORY matters as much as the current state -- a physio's guidance
    last week and this week's may differ, and a later entry must never
    silently overwrite what was said before. Every entry this athlete has
    ever had recorded stays on file permanently (this codebase's own safety
    rail: never delete logs; see CLAUDE.md).

    `restriction` is a coarse, closed 3-value enum -- NOT a replacement for
    `description`'s free text, which still carries the full human detail
    (what hurts, what a practitioner said, context) -- because an AI reading
    this field later (the future ramp-back-up-then-taper planning engine
    this build is the foundation for, but does NOT itself implement) needs
    something it can safely branch on without re-interpreting prose every
    time. "none" / "light_only" / "no_training" is deliberately coarse: a
    machine can trust an enum value where it can't safely trust its own
    parse of a paragraph of free text describing a shoulder.

    `reported_by` (who told the system: "athlete" in her own chat, or
    "coach" relaying something) and `source` (the underlying claim's
    provenance: "self_reported" -- the athlete's own account of how she
    feels -- vs "practitioner" -- a physio/doctor's actual clinical
    guidance, typically relayed by the coach) are independent axes, both
    worth keeping: a coach can relay a self-reported feeling ("she told me
    her shoulder's been off") just as an athlete could in principle relay
    practitioner guidance herself ("my physio said light-only this week").
    Neither is a lesser kind of claim than the other, but they're not the
    SAME kind of claim either, and a future reader (human or AI) should be
    able to tell which is which.

    `resolved`/`resolved_at` let one status be explicitly closed out (e.g.
    "cleared to resume full training as of DATE") WITHOUT deleting the
    history that came before it -- a new entry, not an edit to the old one,
    is how a status changes; nothing here is ever mutated in place except
    flipping `resolved` on the entry being closed. The MOST RECENT entry
    (by `reported_at`) with `resolved=False` for a given athlete is that
    athlete's current active status. If NO such entry exists -- either
    nothing has ever been logged, or every entry on file has since been
    resolved -- there is NO active restriction on file. That is explicitly
    NOT the same thing as "she's definitely fine": it means nothing has
    been recorded, one way or the other. An absence of data must never be
    read as an all-clear, by a human OR by any future automated logic that
    reads this log -- say so plainly wherever this fact is surfaced.

    --- Second-iteration fields (`body_region`/`onset`/`severity`/
    `related_status_id`) -- industry-modeling evolution, before this ever
    shipped or migrated ---

    The first version above ("Is there industry modeling we can validate the
    health status class?") leaned entirely on free-text `description` for
    anything beyond a coarse restriction level -- workable as a start, but
    exactly the kind of thing that "will quickly run short" once real
    automated logic (a future ramp-then-taper planning engine, not part of
    this build) needs to reason about WHICH activities a restriction
    affects, not just how severe it sounds. These four fields close that
    gap by adapting three real, established sports-medicine consensus
    frameworks -- `[ADAPTED: general-endurance]`, Confidence: medium (the
    underlying frameworks are real, verified, high-quality consensus
    documents; the specific choice of which fields to adopt at what
    granularity for a single-athlete coaching app, rather than a research
    surveillance tool, is Coach judgment, not itself directly validated).
    Test: if this athlete population's injury patterns diverge meaningfully
    from what this coarse taxonomy anticipates, or a genuine need for
    finer-grained OSICS-style coding emerges, revisit.

      - Fuller CW, Ekstrand J, Junge A, Andersen TE, Bahr R, Dvorak J,
        Hagglund M, McCrory P, Meeuwisse WH (2006), "Consensus statement on
        injury definitions and data collection procedures in studies of
        football (soccer) injuries," Scandinavian Journal of Medicine &
        Science in Sports / British Journal of Sports Medicine -- the
        field-defining consensus paper (FIFA/F-MARC). Classifies every
        injury by location, type, diagnosis, and cause; defines recurrence
        with precise timing (early: within 2 months of return to full
        participation; late: 2-12 months after; delayed: >12 months after).
      - Bahr R, Clarsen B, Derman W, et al. -- International Olympic
        Committee Injury and Illness Epidemiology Consensus Group (2020),
        "International Olympic Committee consensus statement: methods for
        recording and reporting of epidemiological data on injury and
        illness in sport 2020 (including STROBE-SIIS)," British Journal of
        Sports Medicine / Orthopaedic Journal of Sports Medicine (PMID
        32118084 / 32071062) -- the current cross-sport standard (covers
        illness, not just injury); grades severity by TIME-LOSS (days of
        full/modified training availability lost), not by a point-in-time
        restriction level.
      - Time-loss severity bands, used across multiple sports' consensus
        statements (Fuller 2006 and successors): slight (<=1 day), minimal
        (2-3 days), mild (4-7 days), moderate (8-28 days), serious (>28
        days-6 months), long-term (>6 months) -- keyed to actual/expected
        days of full or modified training lost.
      - OSICS/OSIICS (Orchard Sports Injury and Illness Classification
        System), the ~800-code body-region+tissue+pathology standard most
        sports injury surveillance databases use, is explicitly NOT being
        adopted in full here -- that system is built for population-level
        research comparing injury rates across many athletes/teams, which
        is overkill for a single-athlete coaching app. Only its
        STRUCTURING PRINCIPLE (classify by body region) is adapted here, at
        a deliberately coarse level.

    `body_region` is a coarse 9-value enum, NOT full OSICS coding -- the
    goal is "can automated logic reason about which activities this
    restriction affects" (a shoulder issue rules out pulling/catch-up drills
    specifically, not swimming generally), never population-level injury-
    rate epidemiology. Optional/`None` because a first-contact report right
    after an incident often genuinely doesn't yet know a precise region --
    forcing a guess here would fabricate false precision on safety-relevant
    data, exactly the failure mode this codebase's own "a real value beats a
    missing one, but never invent false precision" philosophy (see e.g.
    `engine/swim_coach/load.py`'s `HR_REST_GENERIC_FALLBACK_BPM` comment)
    already commits to elsewhere.

    `severity` is a SEPARATE axis from `restriction`, not a replacement for
    it: `restriction` answers "how much can she do RIGHT NOW" (a point-in-
    time operational fact); `severity` answers "how big a deal is this
    expected to be OVERALL" (a time-loss-based clinical/prognostic
    judgment, per Bahr et al. 2020 / Fuller 2006's severity grading). A
    broken toe might be `restriction="no_training"` today but only
    `severity="mild"` (short expected recovery); a stress fracture could be
    BOTH `no_training` AND `severity="serious"` or `"long_term"`.
    Conflating these into one field is exactly the gap this evolution
    closes. `severity` is optional and MUST stay that way even for a
    `resolved=True` entry being closed out -- the athlete/coach might
    genuinely never learn (or bother recording) an exact time-loss
    classification, and absence of a severity value is NOT itself
    meaningful information, same "absence isn't evidence" doctrine this
    whole model already commits to for the record's existence overall.

    `onset` (acute vs. gradual/overuse) follows Fuller/IOC's own standard
    split -- informs whether this is a discrete event or a cumulative
    pattern. Optional for the same "don't force a guess" reason as
    `body_region`/`severity`.

    `related_status_id` links a new entry to an EARLIER `HealthStatus.id`
    this is a recurrence/continuation of -- not enforced via a DB foreign
    key at the JSONB layer, just a same-athlete id reference the reader is
    expected to resolve. This is what makes Fuller (2006)'s early/late/
    delayed recurrence classification (2mo / 2-12mo / >12mo since return to
    full participation) actually COMPUTABLE later, from the gap between the
    linked entries' dates, instead of only inferable by a human re-reading
    free text across the whole history. This build does NOT implement
    automatic early/late/delayed recurrence computation/labeling -- that's
    a real, worthwhile follow-up once enough linked entries exist to make it
    meaningful; this build only adds the linking field itself. No
    validation that `related_status_id` actually references a real prior
    entry for THIS athlete belongs here (a cross-record consistency check
    doesn't belong at the single-model-validation layer) -- if implemented
    anywhere, it belongs in the tool handler / route layer where the full
    history is actually available, and even there a dangling reference
    should be at most a soft warning, never a hard validation failure that
    could block saving a real health report over a linking mistake.

    Across all four: `description` remains the necessary free-text escape
    valve for everything that doesn't fit these coarse structured fields --
    these additions give AUTOMATED logic (the coach roster's display today;
    a future ramp-then-taper planning engine, not part of this build)
    something real to branch on, not a replacement for human judgment
    reading the actual description.
    """

    schema_version: int = 1
    id: UUID
    athlete_id: UUID
    reported_at: datetime
    reported_by: Literal["athlete", "coach"]
    source: Literal["self_reported", "practitioner"]
    description: str
    restriction: Literal["none", "light_only", "no_training"]
    expected_review_date: date | None = None
    resolved: bool = False
    resolved_at: datetime | None = None
    body_region: Literal[
        "shoulder", "knee", "back", "hip", "ankle_foot", "elbow_wrist",
        "illness_systemic", "head_neck", "other",
    ] | None = None
    onset: Literal["acute", "gradual"] | None = None
    severity: Literal["slight", "minimal", "mild", "moderate", "serious", "long_term"] | None = None
    related_status_id: UUID | None = None


class ThresholdRecord(BaseModel):
    """A durable, append-only LOG of one dated per-sport threshold reading
    -- same shape as `HealthStatus` above, and for the same reason: a
    threshold (FTP, LTHR, CSS) is not a single mutable fact, it decays in
    accuracy over time, and a later reading must never silently erase an
    earlier one's record. Built to close a real gap: PR #167 added three
    ad-hoc, undated, unsourced threshold fields directly on `Athlete`
    (`css_pace_s_per_100m`, `lthr_bpm`, `ftp_watts`) with no way for the
    coach to ever write them at all -- `record_health_status`/`create_event`
    existed as real coach tools, but nothing let the coach persist an
    athlete's own reported FTP. Rather than bolt on a narrow "set FTP" tool,
    this generalizes the requirement, verbatim from Andrew (the athlete/
    project owner) this session: "We know for HR based training, will use
    LTHR, for run, pace. But, there are per-sport values. This value needs
    to be stored, dated (it will decompose over time). Coach can use
    judgement for trustworthiness of the value (I was 350w 10 years ago is
    invalid vs, ramp test last week is accurate)."

    The ENGINE's job is only to store/surface this history -- see
    `backend/app/context.py`'s `_recent_thresholds`/render function -- it
    NEVER picks a "current" value automatically; the COACH exercises
    judgment about which reading is currently trustworthy (a ramp test last
    week outweighs a number from ten years ago), the same "never let the
    engine guess at subjective trust" boundary `HealthStatus` already draws
    for injury-restriction judgment (see that model's own docstring). The
    engine-resolved value an athlete's zones/load math actually reads stays
    exactly where it already lives -- `Athlete.ftp_watts`/`lthr_bpm`/
    `css_pace_s_per_100m` -- set via `update_athlete_profile`
    (`backend/app/tools.py`) only after a human or the coach model judges a
    `ThresholdRecord` reading trustworthy enough to adopt; this model itself
    resolves nothing.

    Every entry ever recorded stays on file permanently (this codebase's
    own safety rail: never delete logs; see CLAUDE.md) -- there is no
    resolved/superseded flag on this model at all (unlike `HealthStatus`'s
    `resolved`), because a threshold reading is never "wrong" the way an
    open injury status can be closed out -- it just ages. Recency
    (`measured_at`) and provenance (`source`) are read together, not
    collapsed into one score.

    `metric` is a flat string list, trivially extensible (e.g. a future
    `run_pace_s_per_km` once running support exists -- IDEA 008's later
    build, not this one). Deliberately NOT derived from `sport` alone -- an
    athlete could plausibly have both an HR- and pace-based reading for the
    same sport (e.g. LTHR from a chest strap alongside a CSS-equivalent
    pace test for the same swim sport), so `sport` and `metric` are
    independent axes, both required.

    `source` is the trustworthiness signal Andrew's own example names
    directly: "I was 350w 10 years ago" -> `self_reported_historical`;
    "ramp test last week" -> `ramp_test`. Coach-facing, not engine-consumed
    -- the coach reads this alongside `measured_at` to judge recency and
    provenance together, same two-axis judgment `HealthStatus`'s
    `reported_by`/`source` pair already models for a different question.
    `field_test` covers a real standalone test that ISN'T the ramp-test
    protocol (e.g. a swim CSS time-trial pair, a 20-minute FTP test);
    `app_estimate` covers a platform's own algorithmic estimate (e.g.
    TrainerRoad's AI FTP detection) -- real signal, but modelled rather than
    directly tested, which is exactly the kind of distinction Andrew's own
    "modelled not tested" framing (his real profile.md) already draws and
    this field makes structurally queryable instead of only prose.

    `notes` is free text, e.g. "TrainerRoad AI FTP detection, modelled not
    tested" (matching Andrew's own real profile.md phrasing) -- same role
    `HealthStatus.description` plays: the engine can't safely parse this,
    the coach can.
    """

    schema_version: int = 1
    id: UUID
    athlete_id: UUID
    sport: Sport
    metric: Literal["ftp_watts", "lthr_bpm", "css_pace_s_per_100m"]
    value: float
    measured_at: date
    source: Literal[
        "field_test", "ramp_test", "race_file", "app_estimate", "self_reported_historical"
    ]
    notes: str | None = None


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
