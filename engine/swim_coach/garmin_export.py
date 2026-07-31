"""Export a resolved `WorkoutStructure` (see models.py) as a real Garmin
workout-type `.FIT` file.

This is the "USB-copy a .fit file to the watch's `Workouts` folder" export
path -- the one actually-real, actually-documented Garmin workout-file path
(confirmed via Garmin's own manuals and Tredict's / 80/20 Endurance's
published USB-transfer guides), explicitly supported for pool swim
(speed/pace + HR targets) as well as strength. This is deliberately NOT a
Garmin Connect JSON document: Garmin Connect's own import/upload UI is
activities-only (no workout-file import), and the `ExecutableStepDTO`/
`RepeatGroupDTO` JSON shape Connect's workout builder itself uses is only
reachable through Garmin's OAuth Developer API -- out of scope here (no
network/API call happens in this module; `to_garmin_fit_workout` is a pure
function).

Library choice: `fit_tool` (PyPI `fit_tool`, a community-maintained fork of
the original `python_fit_tool` project -- the original was removed from
PyPI by its author and cannot be restored; this fork continues publishing
under the same package name, actively released as of Feb 2026). Chosen after
checking what real Python FIT libraries exist and actually verifying (not
assuming) they support WRITING workout-type FIT messages:
- `fitparse` / `fitdecode` (the latter already an engine dependency, used by
  `parse_files.py` for reading uploaded activity files): both READ-ONLY
  decoders, no message-building/encoding API at all.
- `fit_tool`: implements `WorkoutMessage`, `WorkoutStepMessage`,
  `FitFileBuilder`, and ships its own `write_workout_example.py` -- genuine
  FIT-writing support, confirmed by extracting the wheel and reading the
  actual `WorkoutStepMessage` field API (target/duration subfield unions,
  swim stroke targets, equipment, repeat-step fields) before committing to
  it, not by trusting the package description alone.
Tests in `tests/unit/test_garmin_export.py` validate output by round-
tripping through `fitdecode` -- a genuinely independent reader -- rather than
just trusting `fit_tool`'s own reader agrees with itself.

**A real bug found and worked around**: `fit_tool` 0.9.15's
`SubField.is_valid()` (`fit_tool/sub_field.py`) has a genuine defect --
`field.get_value() in self.reference_map` checks membership against the
reference_map dict's KEYS (which are field_ids, e.g. `1` for `duration_type`)
instead of `self.reference_map[field_id]` (the actual list of valid
reference VALUES). This silently selects the WRONG subfield -- and thus the
wrong scale factor -- whenever a discriminator field's current raw value
happens to numerically collide with a field_id (confirmed by writing a
400m `duration_distance` step and getting back 4000.0 on an independent
fitdecode round-trip: `duration_type=DISTANCE` has raw value 1, which
collides with `WorkoutStepDurationTypeField.ID == 1`, so the FIRST-listed
subfield -- `duration_time`, scale 1000 -- won every time instead of
`duration_distance`, scale 100). This affects essentially every subfielded
workout_step property (all `duration_*`, all `target_*`/`custom_target_*`,
`target_repeat_*`). Worked around here by writing every subfielded value
via the low-level `Field.set_value(0, value, sub_field)` API with an
explicitly resolved `SubField` (via `Field.get_sub_field(name=...)`,
itself unaffected by the bug) instead of `fit_tool`'s buggy high-level
convenience properties/setters -- see `_set_subfield` below. Plain
(non-subfielded) fields -- `workout_step_name`, `duration_type`,
`target_type`, `intensity`, `equipment`, `exercise_weight`,
`weight_display_unit`, `message_index` -- are unaffected and still use
`fit_tool`'s normal properties directly.

FIT repeat-step encoding (no tree/nesting primitive in the format): a
`WorkoutRepeat` group is flattened into its child steps (recursively -- a
nested `WorkoutRepeat` becomes its own child block plus its own closing
marker, in place) followed by ONE closing "repeat marker" `workout_step`
whose `duration_type` is `REPEAT_UNTIL_STEPS_CMPLT` (`repeat_mode="count"`)
or `REPEAT_UNTIL_TIME` (`repeat_mode="for_duration"`/`"amrap"`) and whose
`duration_step` points back at the flattened `message_index` of the group's
first child step. This is the FIT SDK's own documented repeat-step shape
(the `duration_step`/`repeat_steps`/`repeat_time` field semantics below,
cross-checked field-by-field against BOTH `fit_tool`'s and `fitdecode`'s
independently-authored profile declarations, which agree) -- `fit_tool`'s
own test suite references a real TrainerRoad-exported `.fit` repeat file
(`fit_tool/tests/data/trainerroad_744490.fit`, "test decoding workout repeat
greater than step file") confirming a real authoring tool uses this same
loop-back-index shape, though that specific fixture file isn't bundled in
the installed wheel to decode directly.

EMOM caveat: the FIT SDK's `WorkoutStepDuration` enum has no dedicated
"every N seconds on the clock" repeat primitive. `REPEAT_UNTIL_TIME` (loop
until a cumulative elapsed-time budget is used up) is the closest legitimate
encoding available for both `repeat_mode="for_duration"` (EMOM-shaped) and
`repeat_mode="amrap"` groups, using the group's total `duration_s` as the
budget. A Garmin device following this file will NOT re-clock each round to
a fixed minute boundary the way a coach saying "EMOM" means -- that's a real
format limitation, not a shortcut taken here.

Strength exercise-catalog caveat: FIT's `exercise_category`/`exercise_name`
workout_step fields are integer indices into Garmin's own proprietary
exercise catalog (a separate spreadsheet Garmin publishes, not available
here) -- out of scope to map this engine's free-text `exercise_name` strings
(e.g. "kettlebell swing") onto that catalog. The free-text name is instead
written into `workout_step_name`, the athlete-facing label every step
already carries, which Garmin devices display regardless of catalog match
(just without the catalog's built-in exercise animation/icon).
"""

from __future__ import annotations

import time
from typing import Literal

from fit_tool.fit_file_builder import FitFileBuilder
from fit_tool.profile.messages.file_id_message import FileIdMessage
from fit_tool.profile.messages.workout_message import WorkoutMessage
from fit_tool.profile.messages.workout_step_message import WorkoutStepMessage
from fit_tool.profile.profile_type import (
    DisplayMeasure,
    FileType,
    Intensity,
    Manufacturer,
)
from fit_tool.profile.profile_type import Sport as FitSport
from fit_tool.profile.profile_type import (
    SubSport,
    SwimStroke,
    WorkoutEquipment,
    WorkoutStepDuration,
    WorkoutStepTarget,
)

from swim_coach.models import WorkoutLoad, WorkoutRepeat, WorkoutStep, WorkoutStepOrRepeat, WorkoutStructure, WorkoutTarget

# `Session.sport`/modality strings this module supports exporting -- kept
# narrow and explicit (matches the plan's scope) rather than accepting every
# `Sport` the engine models elsewhere; raises a clear `ValueError` for
# anything else (see `to_garmin_fit_workout`).
_SPORT_TO_FIT: dict[str, tuple[FitSport, SubSport]] = {
    "swim": (FitSport.SWIMMING, SubSport.LAP_SWIMMING),
    "strength": (FitSport.TRAINING, SubSport.STRENGTH_TRAINING),
}

# `WorkoutStep.role` -> FIT step intensity. FIT's `Intensity` enum has no
# "open"/untargeted value, so `role="open"` (section-header/rationale steps
# carried on the structure -- see workout_templates.render_prose) maps to
# `OTHER`, the closest neutral bucket.
_ROLE_TO_INTENSITY: dict[str, Intensity] = {
    "warmup": Intensity.WARMUP,
    "steady": Intensity.ACTIVE,
    "interval": Intensity.INTERVAL,
    "rest": Intensity.REST,
    "recovery": Intensity.RECOVERY,
    "cooldown": Intensity.COOLDOWN,
    "open": Intensity.OTHER,
}

_DURATION_KIND_TO_FIT: dict[str, WorkoutStepDuration] = {
    "time_s": WorkoutStepDuration.TIME,
    "distance_m": WorkoutStepDuration.DISTANCE,
    "reps": WorkoutStepDuration.REPS,
    "open": WorkoutStepDuration.OPEN,
}

_STROKE_TO_FIT: dict[str, SwimStroke] = {
    "free": SwimStroke.FREESTYLE,
    "back": SwimStroke.BACKSTROKE,
    "breast": SwimStroke.BREASTSTROKE,
    "fly": SwimStroke.BUTTERFLY,
    "im": SwimStroke.IM,
    "mixed": SwimStroke.MIXED,
    "drill": SwimStroke.DRILL,
}

_EQUIPMENT_TO_FIT: dict[str, WorkoutEquipment] = {
    "fins": WorkoutEquipment.SWIM_FINS,
    "kickboard": WorkoutEquipment.SWIM_KICKBOARD,
    "paddles": WorkoutEquipment.SWIM_PADDLES,
    "pull_buoy": WorkoutEquipment.SWIM_PULL_BUOY,
    "snorkel": WorkoutEquipment.SWIM_SNORKEL,
}

_ZONE_TO_INT: dict[str, int] = {"Z1": 1, "Z2": 2, "Z3": 3, "Z4": 4, "Z5": 5}

# FIT string fields are fixed-size on write; `fit_tool`'s `FitFileBuilder`
# is constructed with `min_string_size` below, but names are still truncated
# defensively here so an unusually long label can't blow past whatever size
# the builder settles on.
_MAX_STRING_LEN = 63

# `workout_step` field IDs (from `fit_tool.profile.messages.
# workout_step_message`'s `WorkoutStep*Field.ID` constants) needed for the
# `_set_subfield` bypass -- see module docstring's "real bug found" section.
_FIELD_DURATION_VALUE = 2
_FIELD_TARGET_VALUE = 4
_FIELD_CUSTOM_TARGET_LOW = 5
_FIELD_CUSTOM_TARGET_HIGH = 6


def _set_subfield(fit_step: WorkoutStepMessage, field_id: int, sub_field_name: str, value) -> None:
    """Set one subfielded `workout_step` value directly, bypassing
    `fit_tool`'s buggy `get_valid_sub_field()` auto-detection (see module
    docstring). `Field.get_sub_field(name=...)` does an exact name lookup
    against the field's own declared subfield list -- unaffected by the
    reference-value-vs-key bug, since it never consults the discriminator
    field's current value at all.
    """
    field = fit_step.get_field(field_id)
    sub_field = field.get_sub_field(name=sub_field_name)
    if sub_field is None:
        raise AssertionError(f"fit_tool workout_step field {field_id} has no subfield named {sub_field_name!r}")
    field.set_value(0, value, sub_field)


def _pace_s_to_speed_mps(pace_s_per_100m: float) -> float:
    """Convert a resolved seconds-per-100m swim pace to FIT's speed target
    unit (meters/second)."""
    return 100.0 / pace_s_per_100m


def _apply_target(fit_step: WorkoutStepMessage, target: WorkoutTarget | None, stroke: str | None) -> None:
    """Set `fit_step`'s target fields from a resolved `WorkoutTarget` and/or
    a swim `stroke`.

    FIT stores exactly one target per workout step (`target_type` selects
    which subfield of the underlying value union is meaningful) -- a pace
    target and a stroke target cannot both be encoded on the same step. A
    real pace/zone target always wins (the more actionable signal for a
    device to follow); `stroke` is only encoded via
    `target_type=SWIM_STROKE` when there is no numeric target to show
    instead. When a pace target IS present, the stroke is still preserved in
    the step's `label` text (already authored by workout_templates.py/
    plan.py), just not as a separate FIT target field.
    """
    if target is None:
        if stroke and stroke in _STROKE_TO_FIT:
            fit_step.target_type = WorkoutStepTarget.SWIM_STROKE
            _set_subfield(fit_step, _FIELD_TARGET_VALUE, "target_stroke_type", _STROKE_TO_FIT[stroke].value)
        else:
            fit_step.target_type = WorkoutStepTarget.OPEN
        return

    if target.basis == "absolute":
        # `target.low`/`target.high` are resolved seconds-per-100m paces
        # with `low` the FASTER (smaller-number) bound and `high` the
        # SLOWER (larger-number) bound (see workout_templates.
        # resolve_template / zones.zone_table) -- speed is inversely
        # related to pace, so the slower pace (`high`) becomes the LOWER
        # FIT speed bound and the faster pace (`low`) becomes the HIGHER
        # FIT speed bound. Either bound may be `None` (an open-ended zone,
        # e.g. Z1's low side / Z5's high side) -- only set what's real.
        low_speed = _pace_s_to_speed_mps(target.high) if target.high else None
        high_speed = _pace_s_to_speed_mps(target.low) if target.low else None
        if low_speed is None and high_speed is None:
            fit_step.target_type = WorkoutStepTarget.OPEN
            return
        fit_step.target_type = WorkoutStepTarget.SPEED
        if low_speed is not None:
            _set_subfield(fit_step, _FIELD_CUSTOM_TARGET_LOW, "custom_target_speed_low", low_speed)
        if high_speed is not None:
            _set_subfield(fit_step, _FIELD_CUSTOM_TARGET_HIGH, "custom_target_speed_high", high_speed)
    elif target.basis == "zone" and target.zone in _ZONE_TO_INT:
        # Defensive support for an unresolved-but-zone-tagged target (a
        # template step, or a workout whose zone was deliberately left
        # device-relative) -- the device applies its own configured pace
        # zone rather than a specific number range.
        fit_step.target_type = WorkoutStepTarget.SPEED
        _set_subfield(fit_step, _FIELD_TARGET_VALUE, "target_speed_zone", _ZONE_TO_INT[target.zone])
    elif target.basis == "percent_css":
        raise ValueError(
            "to_garmin_fit_workout requires a RESOLVED WorkoutStructure -- got an "
            "unresolved WorkoutTarget(basis='percent_css'); resolve the template via "
            "workout_templates.resolve_template() first."
        )
    else:
        # basis in ("rpe", "open") -- no FIT-native numeric target exists
        # for RPE; OPEN is the honest encoding (RPE language lives in the
        # step's label text instead).
        fit_step.target_type = WorkoutStepTarget.OPEN


def _apply_load(fit_step: WorkoutStepMessage, load: WorkoutLoad | None) -> None:
    """Set `fit_step`'s resistance target from a resolved `WorkoutLoad`.

    Only `basis="absolute"` has a real FIT counterpart (`exercise_weight`).
    `bodyweight`/`rpe_only` carry no numeric resistance target by design.
    `percent_1rm` reaching this function unresolved (no 1RM data on file for
    that exercise -- see `workout_templates.resolve_template`'s docstring:
    a documented no-op pass-through, not an error) is treated the same as
    `bodyweight` rather than raised, since real production strength content
    may legitimately have no 1RM baseline collected yet.
    """
    if load is None:
        return
    if load.basis == "absolute" and load.value is not None:
        fit_step.exercise_weight = float(load.value)
        fit_step.weight_display_unit = DisplayMeasure.METRIC


def _build_leaf_step(step: WorkoutStep) -> WorkoutStepMessage:
    fit_step = WorkoutStepMessage()
    fit_step.workout_step_name = step.label[:_MAX_STRING_LEN]
    fit_step.intensity = _ROLE_TO_INTENSITY.get(step.role, Intensity.OTHER)

    duration_type = _DURATION_KIND_TO_FIT.get(step.duration_kind, WorkoutStepDuration.OPEN)
    if duration_type == WorkoutStepDuration.TIME and step.duration_value is not None:
        fit_step.duration_type = duration_type
        _set_subfield(fit_step, _FIELD_DURATION_VALUE, "duration_time", float(step.duration_value))
    elif duration_type == WorkoutStepDuration.DISTANCE and step.duration_value is not None:
        fit_step.duration_type = duration_type
        _set_subfield(fit_step, _FIELD_DURATION_VALUE, "duration_distance", float(step.duration_value))
    elif duration_type == WorkoutStepDuration.REPS and step.duration_value is not None:
        fit_step.duration_type = duration_type
        _set_subfield(fit_step, _FIELD_DURATION_VALUE, "duration_reps", int(step.duration_value))
    else:
        fit_step.duration_type = WorkoutStepDuration.OPEN
        fit_step.duration_value = 0

    _apply_target(fit_step, step.target, step.stroke if step.modality == "swim" else None)
    _apply_load(fit_step, step.load)

    if step.modality == "swim" and step.equipment:
        # FIT encodes exactly one equipment value per step; first recognized
        # item wins (matches a real device, which shows one equipment icon
        # per step).
        for item in step.equipment:
            if item in _EQUIPMENT_TO_FIT:
                fit_step.equipment = _EQUIPMENT_TO_FIT[item]
                break

    return fit_step


def _build_repeat_marker(repeat: WorkoutRepeat, loop_start_index: int) -> WorkoutStepMessage:
    """The closing 'repeat marker' step for a flattened `WorkoutRepeat`
    group -- see module docstring's "FIT repeat-step encoding" section.
    """
    fit_step = WorkoutStepMessage()
    fit_step.intensity = Intensity.ACTIVE
    fit_step.target_type = WorkoutStepTarget.OPEN

    if repeat.repeat_mode == "count":
        fit_step.duration_type = WorkoutStepDuration.REPEAT_UNTIL_STEPS_CMPLT
        _set_subfield(fit_step, _FIELD_DURATION_VALUE, "duration_step", loop_start_index)
        count = repeat.count if repeat.count is not None else 1
        # NOTE: the underlying `target_value` field's subfield is
        # registered internally as `repeat_steps` (NOT `target_repeat_steps`
        # -- that's only the convenience *property* name on
        # `WorkoutStepMessage`, which resolves to this differently-named
        # subfield). Confirmed directly against the installed `fit_tool`
        # 0.9.15 field object rather than assumed from the property name.
        _set_subfield(fit_step, _FIELD_TARGET_VALUE, "repeat_steps", count)
    else:
        # "for_duration" (EMOM-shaped) / "amrap" -- see module docstring's
        # EMOM caveat for why REPEAT_UNTIL_TIME is the closest legitimate
        # FIT primitive for both.
        fit_step.duration_type = WorkoutStepDuration.REPEAT_UNTIL_TIME
        _set_subfield(fit_step, _FIELD_DURATION_VALUE, "duration_step", loop_start_index)
        duration_s = float(repeat.duration_s) if repeat.duration_s is not None else 0.0
        _set_subfield(fit_step, _FIELD_TARGET_VALUE, "repeat_time", duration_s)

    return fit_step


def _flatten(items: list[WorkoutStepOrRepeat], fit_steps: list[WorkoutStepMessage]) -> None:
    """Depth-first flatten `items` (a `WorkoutStructure`/`WorkoutRepeat`'s
    ordered children) into `fit_steps`, appending in place. See module
    docstring for the flat-list-plus-back-reference repeat encoding;
    `message_index` values are assigned by the caller once flattening is
    complete (indices must be final positions, not assigned mid-recursion).
    """
    for item in items:
        if isinstance(item, WorkoutStep):
            fit_steps.append(_build_leaf_step(item))
        else:
            loop_start_index = len(fit_steps)
            _flatten(item.steps, fit_steps)
            fit_steps.append(_build_repeat_marker(item, loop_start_index))


def to_garmin_fit_workout(
    structured: WorkoutStructure,
    sport: Literal["swim", "strength"],
    name: str,
) -> bytes:
    """Encode a RESOLVED `WorkoutStructure` (absolute targets -- see
    `workout_templates.resolve_template`) as the bytes of a real Garmin
    workout-type `.FIT` file: a `file_id` + `workout` + `workout_step`*
    message sequence a Garmin watch can load directly from a USB-copied file
    in its `Workouts` folder and follow on deck.

    Pure function -- no I/O, no network, no OAuth. Raises `ValueError` for
    an unsupported `sport`, or for an unresolved `WorkoutTarget(basis=
    "percent_css")` anywhere in `structured` (a template, not a workout --
    see `_apply_target`).
    """
    if sport not in _SPORT_TO_FIT:
        raise ValueError(f"unsupported sport {sport!r}, must be one of {sorted(_SPORT_TO_FIT)}")
    fit_sport, sub_sport = _SPORT_TO_FIT[sport]

    fit_steps: list[WorkoutStepMessage] = []
    _flatten(structured.items, fit_steps)
    for index, fit_step in enumerate(fit_steps):
        fit_step.message_index = index

    file_id = FileIdMessage()
    file_id.type = FileType.WORKOUT
    file_id.manufacturer = Manufacturer.DEVELOPMENT.value
    file_id.product = 0
    file_id.time_created = round(time.time() * 1000)
    file_id.serial_number = 0xA5F17B00  # fixed, arbitrary -- no per-athlete data in the file

    workout = WorkoutMessage()
    workout.workout_name = name[:_MAX_STRING_LEN]
    workout.sport = fit_sport
    workout.sub_sport = sub_sport
    workout.num_valid_steps = len(fit_steps)

    builder = FitFileBuilder(auto_define=True, min_string_size=64)
    builder.add(file_id)
    builder.add(workout)
    builder.add_all(fit_steps)

    return builder.build().to_bytes()
