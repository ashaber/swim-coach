"""Workout compiler: the coach states an intent, the engine returns the exact structured workout."""

from swim_coach.workout_builders import bike, swim  # noqa: F401  (registers the builders)
from swim_coach.workout_builders.compile import CompiledWorkout, compile_workout
from swim_coach.workout_builders.intent import WorkoutIntent
from swim_coach.workout_builders.registry import (
    BuildResult,
    ParamRange,
    WorkoutBuilder,
    builders_for,
    get_builder,
    list_archetypes,
    register,
    register_loader,
)

__all__ = [
    "BuildResult",
    "CompiledWorkout",
    "ParamRange",
    "WorkoutBuilder",
    "WorkoutIntent",
    "builders_for",
    "compile_workout",
    "get_builder",
    "list_archetypes",
    "register",
    "register_loader",
]
