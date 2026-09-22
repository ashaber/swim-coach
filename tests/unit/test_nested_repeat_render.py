"""The workout model ACCEPTS a repeat inside a repeat ("2 sets of 3 x kettlebell swings" is the
natural shape for strength work) but render_prose used to crash on it with
"'WorkoutRepeat' object has no attribute 'role'" -- a raw exception that blocked the write
(coach-reported as "nested repeat-inside-repeat is rejected"; seen live 2026-09-21)."""

from __future__ import annotations

from swim_coach.models import WorkoutStructure
from swim_coach.workout_templates import render_prose


def step(label, role="interval", kind="reps", value=12):
    return {"kind": "step", "label": label, "role": role, "duration_kind": kind, "duration_value": value, "modality": "strength"}


NESTED = {"items": [
    step("Warm-up: 5 min easy", role="warmup", kind="time_s", value=300),
    {"kind": "repeat", "count": 2, "steps": [
        {"kind": "repeat", "count": 3, "steps": [step("KB swing x12"), step("Rest 30s", role="rest", kind="time_s", value=30)]},
        step("Set rest 2 min", role="rest", kind="time_s", value=120),
    ]},
]}


def test_a_nested_repeat_renders_instead_of_crashing() -> None:
    text = render_prose(WorkoutStructure.model_validate(NESTED))
    assert "KB swing x12" in text and "Rest 30s" in text and "Set rest 2 min" in text


def test_a_nested_repeat_says_how_many_times_it_repeats() -> None:
    text = render_prose(WorkoutStructure.model_validate(NESTED))
    assert "Repeat 3x" in text  # the inner count is not lost


def test_a_flat_single_level_repeat_renders_exactly_as_before() -> None:
    from swim_coach.workout_templates import _render_step_line

    flat = WorkoutStructure.model_validate(
        {"items": [{"kind": "repeat", "count": 3, "steps": [step("Fast 50"), step("Easy 50", role="rest")]}]}
    )
    # exactly what the pre-fix renderer produced: each inner step's own line, no repeat header
    assert render_prose(flat) == "\n".join(_render_step_line(s) for s in flat.items[0].steps)


def test_deeper_nesting_also_renders() -> None:
    deep = {"items": [{"kind": "repeat", "count": 2, "steps": [{"kind": "repeat", "count": 2, "steps": [
        {"kind": "repeat", "count": 2, "steps": [step("Burpee x5")]}]}]}]}
    assert "Burpee x5" in render_prose(WorkoutStructure.model_validate(deep))
