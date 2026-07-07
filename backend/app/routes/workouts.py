"""POST/GET /api/workouts -- logging and listing completed workouts.

This is the write half of the seam `plan.py` reads through: everything goes
via `make_store(settings)` (`FileStore` locally, `DbStore` in prod behind
`STORE_BACKEND=db`) so a workout logged here reaches the live coach with no
redeploy. The server assigns `id` (uuid4), `athlete_id` (from the athlete's
own profile) and `schema_version`; this endpoint always logs `source="manual"`
-- ingestion from a `.fit`/`.tcx`/`.csv` file or a pool-coach text goes
through the CLI/skills, not this route. Input is validated by constructing
the pydantic `Workout` model directly (never hand-computed) -- a
`pydantic.ValidationError` becomes a 422 with the app's standard
`{"error": ...}` shape (same `HTTPException` -> `StarletteHTTPException`
handler `app.main` already installs for every other route).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError
from swim_coach.models import Workout

from app.auth import require_auth
from app.store_factory import make_store

router = APIRouter()

# Fields the server assigns itself -- stripped from the client payload before
# constructing the model so a client-supplied value can never collide with
# (or spoof) an id/athlete_id/schema_version, and `source` is always "manual"
# for this human-logging endpoint.
_SERVER_ASSIGNED_FIELDS = {"id", "athlete_id", "schema_version", "source"}


@router.post("/api/workouts")
async def create_workout(
    payload: dict[str, Any],
    request: Request,
    athlete: str = Query("renee"),
    _token: str = Depends(require_auth),
) -> dict:
    settings = request.app.state.settings
    store = make_store(settings)
    try:
        profile = store.load_athlete(athlete)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"no such athlete: {athlete}") from exc

    client_fields = {k: v for k, v in payload.items() if k not in _SERVER_ASSIGNED_FIELDS}
    try:
        workout = Workout(
            id=uuid4(),
            athlete_id=profile.id,
            schema_version=1,
            source="manual",
            **client_fields,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    store.save_workout(athlete, workout)
    return workout.model_dump(mode="json")


@router.get("/api/workouts")
async def list_workouts(
    request: Request,
    athlete: str = Query("renee"),
    _token: str = Depends(require_auth),
) -> list[dict]:
    settings = request.app.state.settings
    store = make_store(settings)
    try:
        store.load_athlete(athlete)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"no such athlete: {athlete}") from exc

    workouts = store.list_workouts(athlete)
    return [w.model_dump(mode="json") for w in workouts]
