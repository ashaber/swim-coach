"""Tests for swim_coach.garmin_export: encoding a resolved `WorkoutStructure`
as a real Garmin workout-type .FIT file (see garmin_export.py's module
docstring for the "why .FIT, not Garmin Connect JSON" rationale).

No LLM calls, no network access. Every test round-trips the produced bytes
through `fitdecode` (a genuinely independent FIT-READING library -- not
`fit_tool`'s own reader) to prove the output is real, well-formed, parseable
FIT, not just "didn't raise while writing."
"""

from __future__ import annotations

import uuid

import fitdecode
import pytest

from swim_coach import workout_templates
from swim_coach.garmin_export import _MAX_STRING_LEN, to_garmin_fit_workout
from swim_coach.models import (
    Athlete,
    WorkoutLoad,
    WorkoutRepeat,
    WorkoutStep,
    WorkoutStructure,
    WorkoutTarget,
)
from swim_coach.plan import _strength_session_structure_template
from swim_coach.workout_templates import TEMPLATES_DIR, load_workout_templates, resolve_template
from swim_coach.zones import zone_table


def _decode_workout_steps(fit_bytes: bytes) -> list[dict]:
    """Decode `fit_bytes` via fitdecode and return every `workout_step`
    message's fields as a plain dict, in file order. Also asserts the FIT
    magic header (".FIT" at byte offset 8) is present -- the cheapest
    possible "is this really FIT binary" sanity check, ahead of the full
    semantic decode.
    """
    assert fit_bytes[8:12] == b".FIT"
    steps: list[dict] = []
    with fitdecode.FitReader(fit_bytes) as fit:
        for frame in fit:
            if frame.frame_type != fitdecode.FIT_FRAME_DATA:
                continue
            if frame.name != "workout_step":
                continue
            steps.append({f.name: f.value for f in frame.fields})
    return steps


def _decode_workout_message(fit_bytes: bytes) -> dict:
    with fitdecode.FitReader(fit_bytes) as fit:
        for frame in fit:
            if frame.frame_type == fitdecode.FIT_FRAME_DATA and frame.name == "workout":
                return {f.name: f.value for f in frame.fields}
    raise AssertionError("no workout message found in decoded .fit bytes")


# --- basic swim / strength shapes --------------------------------------------


def test_swim_step_produces_valid_fit_file():
    structured = WorkoutStructure(
        items=[
            WorkoutStep(
                label="Warm-up 400 easy",
                role="warmup",
                duration_kind="distance_m",
                duration_value=400,
                target=WorkoutTarget(basis="absolute", low=90.0, high=100.0),
                modality="swim",
                stroke="free",
            ),
        ]
    )
    fit_bytes = to_garmin_fit_workout(structured, sport="swim", name="Test swim")
    assert isinstance(fit_bytes, bytes)
    assert len(fit_bytes) > 0

    workout_msg = _decode_workout_message(fit_bytes)
    # fitdecode reports this field by its internal FIT SDK short name
    # ("wkt_name"), not `fit_tool`'s friendlier `workout_name` property name.
    assert workout_msg["wkt_name"] == "Test swim"
    assert workout_msg["sport"] == "swimming"
    assert workout_msg["num_valid_steps"] == 1

    steps = _decode_workout_steps(fit_bytes)
    assert len(steps) == 1
    assert steps[0]["duration_type"] == "distance"
    assert steps[0]["target_type"] == "speed"
    # faster pace (low=90s/100m) -> higher speed bound; slower pace
    # (high=100s/100m) -> lower speed bound (see garmin_export's pace<->speed
    # inversion note).
    assert steps[0]["custom_target_speed_low"] == pytest.approx(1.0, rel=1e-3)
    assert steps[0]["custom_target_speed_high"] == pytest.approx(100 / 90, rel=1e-3)


def test_strength_step_with_bodyweight_load():
    structured = WorkoutStructure(
        items=[
            WorkoutStep(
                label="kettlebell swing",
                role="steady",
                duration_kind="reps",
                duration_value=10,
                load=WorkoutLoad(basis="bodyweight"),
                modality="strength",
                exercise_name="kettlebell swing",
            ),
        ]
    )
    fit_bytes = to_garmin_fit_workout(structured, sport="strength", name="Test strength")
    workout_msg = _decode_workout_message(fit_bytes)
    assert workout_msg["sport"] == "training"

    steps = _decode_workout_steps(fit_bytes)
    assert len(steps) == 1
    assert steps[0]["duration_type"] == "reps"
    assert steps[0]["duration_reps"] == 10


def test_step_with_reference_url_round_trips_into_notes():
    structured = WorkoutStructure(
        items=[
            WorkoutStep(
                label="goblet squat",
                role="steady",
                duration_kind="reps",
                duration_value=10,
                load=WorkoutLoad(basis="bodyweight"),
                modality="strength",
                exercise_name="goblet squat",
                reference_url="https://www.rehabhero.ca/exercise/goblet-squat",
            ),
        ]
    )
    fit_bytes = to_garmin_fit_workout(structured, sport="strength", name="Test strength")
    steps = _decode_workout_steps(fit_bytes)
    assert len(steps) == 1
    assert steps[0]["notes"] == "https://www.rehabhero.ca/exercise/goblet-squat"


def test_step_without_reference_url_has_no_notes():
    structured = WorkoutStructure(
        items=[
            WorkoutStep(
                label="kettlebell swing",
                role="steady",
                duration_kind="reps",
                duration_value=10,
                load=WorkoutLoad(basis="bodyweight"),
                modality="strength",
                exercise_name="kettlebell swing",
            ),
        ]
    )
    fit_bytes = to_garmin_fit_workout(structured, sport="strength", name="Test strength")
    steps = _decode_workout_steps(fit_bytes)
    assert len(steps) == 1
    assert steps[0].get("notes") is None


def test_step_with_long_reference_url_is_truncated_to_max_string_len():
    long_url = "https://www.rehabhero.ca/exercise/" + ("a" * 100)
    structured = WorkoutStructure(
        items=[
            WorkoutStep(
                label="goblet squat",
                role="steady",
                duration_kind="reps",
                duration_value=10,
                load=WorkoutLoad(basis="bodyweight"),
                modality="strength",
                exercise_name="goblet squat",
                reference_url=long_url,
            ),
        ]
    )
    fit_bytes = to_garmin_fit_workout(structured, sport="strength", name="Test strength")
    steps = _decode_workout_steps(fit_bytes)
    assert len(steps) == 1
    assert steps[0]["notes"] == long_url[:_MAX_STRING_LEN]


def test_strength_step_with_absolute_load():
    structured = WorkoutStructure(
        items=[
            WorkoutStep(
                label="goblet squat",
                role="steady",
                duration_kind="reps",
                duration_value=12,
                load=WorkoutLoad(basis="absolute", value=16.0),
                modality="strength",
                exercise_name="goblet squat",
            ),
        ]
    )
    fit_bytes = to_garmin_fit_workout(structured, sport="strength", name="Test strength weighted")
    steps = _decode_workout_steps(fit_bytes)
    assert steps[0]["exercise_weight"] == pytest.approx(16.0)


# --- WorkoutRepeat: count / for_duration (EMOM-shaped) / amrap --------------


def test_count_repeat_produces_repeat_marker_step():
    structured = WorkoutStructure(
        items=[
            WorkoutRepeat(
                repeat_mode="count",
                count=3,
                steps=[
                    WorkoutStep(
                        label="100 free",
                        role="interval",
                        duration_kind="distance_m",
                        duration_value=100,
                        modality="swim",
                    ),
                    WorkoutStep(
                        label="rest 15s",
                        role="rest",
                        duration_kind="time_s",
                        duration_value=15,
                        modality="swim",
                    ),
                ],
            ),
        ]
    )
    fit_bytes = to_garmin_fit_workout(structured, sport="swim", name="Repeat test")
    steps = _decode_workout_steps(fit_bytes)
    # 2 child steps + 1 closing repeat-marker step.
    assert len(steps) == 3
    assert steps[0]["duration_type"] == "distance"
    assert steps[1]["duration_type"] == "time"
    marker = steps[2]
    assert marker["duration_type"] == "repeat_until_steps_cmplt"
    assert marker["duration_step"] == 0  # loops back to the first child step
    assert marker["repeat_steps"] == 3


def test_for_duration_repeat_emom_shaped():
    structured = WorkoutStructure(
        items=[
            WorkoutRepeat(
                repeat_mode="for_duration",
                duration_s=600.0,
                interval_s=60.0,
                steps=[
                    WorkoutStep(
                        label="8 kettlebell swings",
                        role="steady",
                        duration_kind="reps",
                        duration_value=8,
                        modality="strength",
                        exercise_name="kettlebell swing",
                    ),
                ],
            ),
        ]
    )
    fit_bytes = to_garmin_fit_workout(structured, sport="strength", name="EMOM test")
    steps = _decode_workout_steps(fit_bytes)
    assert len(steps) == 2
    marker = steps[1]
    assert marker["duration_type"] == "repeat_until_time"
    assert marker["duration_step"] == 0
    assert marker["repeat_time"] == pytest.approx(600.0)


def test_amrap_repeat():
    structured = WorkoutStructure(
        items=[
            WorkoutRepeat(
                repeat_mode="amrap",
                duration_s=900.0,
                steps=[
                    WorkoutStep(
                        label="5 burpees",
                        role="steady",
                        duration_kind="reps",
                        duration_value=5,
                        modality="strength",
                        exercise_name="burpee",
                    ),
                ],
            ),
        ]
    )
    fit_bytes = to_garmin_fit_workout(structured, sport="strength", name="AMRAP test")
    steps = _decode_workout_steps(fit_bytes)
    marker = steps[-1]
    assert marker["duration_type"] == "repeat_until_time"
    assert marker["repeat_time"] == pytest.approx(900.0)


def test_nested_repeat_flattens_with_correct_loop_indices():
    structured = WorkoutStructure(
        items=[
            WorkoutStep(
                label="warmup",
                role="warmup",
                duration_kind="time_s",
                duration_value=300,
                modality="swim",
            ),
            WorkoutRepeat(
                repeat_mode="count",
                count=2,
                steps=[
                    WorkoutRepeat(
                        repeat_mode="count",
                        count=4,
                        steps=[
                            WorkoutStep(
                                label="25 sprint",
                                role="interval",
                                duration_kind="distance_m",
                                duration_value=25,
                                modality="swim",
                            ),
                        ],
                    ),
                    WorkoutStep(
                        label="rest 60s",
                        role="rest",
                        duration_kind="time_s",
                        duration_value=60,
                        modality="swim",
                    ),
                ],
            ),
        ]
    )
    fit_bytes = to_garmin_fit_workout(structured, sport="swim", name="Nested repeat test")
    steps = _decode_workout_steps(fit_bytes)
    # index 0: warmup
    # index 1: 25 sprint (inner loop child)
    # index 2: inner repeat marker (loops back to index 1, count=4)
    # index 3: rest 60s (outer loop child)
    # index 4: outer repeat marker (loops back to index 1, count=2)
    assert len(steps) == 5
    assert steps[2]["duration_type"] == "repeat_until_steps_cmplt"
    assert steps[2]["duration_step"] == 1
    assert steps[2]["repeat_steps"] == 4
    assert steps[4]["duration_type"] == "repeat_until_steps_cmplt"
    assert steps[4]["duration_step"] == 1
    assert steps[4]["repeat_steps"] == 2


# --- zone-basis target, stroke, equipment -----------------------------------


def test_zone_basis_target_uses_speed_zone():
    structured = WorkoutStructure(
        items=[
            WorkoutStep(
                label="Z3 set",
                role="interval",
                duration_kind="distance_m",
                duration_value=200,
                target=WorkoutTarget(basis="zone", zone="Z3"),
                modality="swim",
            ),
        ]
    )
    fit_bytes = to_garmin_fit_workout(structured, sport="swim", name="Zone test")
    steps = _decode_workout_steps(fit_bytes)
    assert steps[0]["target_type"] == "speed"
    assert steps[0]["target_speed_zone"] == 3


def test_stroke_used_as_target_only_when_no_pace_target():
    structured = WorkoutStructure(
        items=[
            WorkoutStep(
                label="drill set",
                role="steady",
                duration_kind="distance_m",
                duration_value=100,
                target=None,
                modality="swim",
                stroke="fly",
            ),
        ]
    )
    fit_bytes = to_garmin_fit_workout(structured, sport="swim", name="Stroke test")
    steps = _decode_workout_steps(fit_bytes)
    assert steps[0]["target_type"] == "swim_stroke"
    assert steps[0]["target_stroke_type"] == "butterfly"


def test_equipment_encoded():
    structured = WorkoutStructure(
        items=[
            WorkoutStep(
                label="kick set",
                role="steady",
                duration_kind="distance_m",
                duration_value=200,
                modality="swim",
                equipment=["kickboard"],
            ),
        ]
    )
    fit_bytes = to_garmin_fit_workout(structured, sport="swim", name="Equipment test")
    steps = _decode_workout_steps(fit_bytes)
    assert steps[0]["equipment"] == "swim_kickboard"


def test_rpe_and_open_targets_encode_as_open():
    structured = WorkoutStructure(
        items=[
            WorkoutStep(
                label="rpe step",
                role="steady",
                duration_kind="open",
                target=WorkoutTarget(basis="rpe"),
                modality="swim",
            ),
        ]
    )
    fit_bytes = to_garmin_fit_workout(structured, sport="swim", name="RPE test")
    steps = _decode_workout_steps(fit_bytes)
    assert steps[0]["target_type"] == "open"
    assert steps[0]["duration_type"] == "open"


def test_unresolved_percent_css_target_raises():
    structured = WorkoutStructure(
        items=[
            WorkoutStep(
                label="unresolved",
                role="interval",
                duration_kind="distance_m",
                duration_value=100,
                target=WorkoutTarget(basis="percent_css", low=110, high=120),
                modality="swim",
            ),
        ]
    )
    with pytest.raises(ValueError, match="resolve"):
        to_garmin_fit_workout(structured, sport="swim", name="Unresolved test")


def test_unsupported_sport_raises():
    structured = WorkoutStructure(items=[])
    with pytest.raises(ValueError):
        to_garmin_fit_workout(structured, sport="cycling", name="bad")  # type: ignore[arg-type]


# --- real template library coverage -----------------------------------------
# Every real *.yaml file in engine/swim_coach/workout_templates/ must, once
# resolved against a real athlete, produce a valid, fitdecode-parseable .fit
# file -- same spirit as test_workout_templates.py's real-file lint test.


def _athlete() -> Athlete:
    return Athlete(id=uuid.uuid4(), slug="t", name="T", css_pace_s_per_100m=92.0)


def test_every_real_template_produces_valid_fit_file():
    templates = load_workout_templates(TEMPLATES_DIR)
    assert len(templates) > 0
    zones = zone_table(92.0)
    z2, z3, z4 = zones["Z2"], zones["Z3"], zones["Z4"]
    athlete = _athlete()

    seen_ids: set[str] = set()
    for macro_block_name in ("base", "build", "peak", "taper"):
        candidates = sorted(
            (t for t in templates if macro_block_name in t.applicable_blocks),
            key=lambda t: t.id,
        )
        for selector, template in enumerate(candidates):
            step = workout_templates.build_main_set_step(
                macro_block_name, selector, reps=6, rep=200, z2=z2, z3=z3, z4=z4
            )
            structured = WorkoutStructure(items=[step])
            resolved = resolve_template(structured, athlete)
            fit_bytes = to_garmin_fit_workout(resolved, sport="swim", name=template.id)
            steps = _decode_workout_steps(fit_bytes)
            assert len(steps) == 1, f"{template.id}: expected 1 workout_step, got {len(steps)}"
            seen_ids.add(template.id)

    # Every real template file was actually exercised at least once.
    assert seen_ids == {t.id for t in templates}


def test_real_strength_session_template_produces_valid_fit_file():
    athlete = _athlete()
    for session_index in (0, 1):
        template = _strength_session_structure_template(session_index)
        resolved = resolve_template(template, athlete)
        fit_bytes = to_garmin_fit_workout(resolved, sport="strength", name=f"Strength {session_index}")
        steps = _decode_workout_steps(fit_bytes)
        assert len(steps) > 0
