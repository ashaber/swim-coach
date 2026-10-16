"""Pure selection/re-matching logic for the one-time sport backfills (`scripts/backfill_yoga_sport.py`).

Kept in the engine so it is unit-testable without a store or the backend.

Yoga: workouts ingested before `parse_files._fit_sport` mapped `training/yoga` to `recovery` were
stored as `strength`. Re-sporting one also has to redo its plan link: a stale
`planned_session_id` pointing at a strength session (the +-1 day window matched the neighbouring
"Cycling strength" day) is dropped, and the workout is matched again against the plan.
"""

from __future__ import annotations

from typing import Sequence

from swim_coach.models import Session, Workout
from swim_coach.parse_files import is_recovery_training_detail
from swim_coach.quality import match_workout_to_session

RECOVERY_SPORT = "recovery"


def yoga_resport_candidates(workouts: Sequence[Workout]) -> list[Workout]:
    """Strength workouts whose device sub-sport is yoga/pilates/stretching/breathing."""
    return [w for w in workouts if w.sport == "strength" and is_recovery_training_detail(w.sport_detail)]


def legacy_cycling_cross_train(workouts: Sequence[Workout]) -> list[Workout]:
    """Old `cross_train` rows whose detail is cycling (predate the cycling -> bike mapping).
    Listed for the owner to decide on; never changed by the backfill."""
    return [
        w for w in workouts
        if w.sport == "cross_train" and (w.sport_detail or "").lower().split("/")[0] == "cycling"
    ]


def resport_and_rematch(workout: Workout, *, sessions: Sequence[Session], others: Sequence[Workout]) -> Workout:
    """`workout` as `recovery`, linked to the planned session it now matches.

    An existing link survives only if it points at a session of the new sport; otherwise it is
    cleared and the normal matching rules (same sport+date, then the unique +-1 day fit that no
    other workout in `others` already covers) pick the session, or none. `others` should hold the
    athlete's other workouts as they will be after the backfill, so one session is never claimed twice."""
    by_id = {s.id: s for s in sessions}
    linked = by_id.get(workout.planned_session_id) if workout.planned_session_id else None
    keep = workout.planned_session_id if linked is not None and linked.sport == RECOVERY_SPORT else None
    moved = workout.model_copy(update={"sport": RECOVERY_SPORT, "planned_session_id": keep})
    if keep is None:
        match = match_workout_to_session(moved, list(sessions), other_workouts=list(others))
        moved = moved.model_copy(update={"planned_session_id": match.id if match else None})
    return moved
