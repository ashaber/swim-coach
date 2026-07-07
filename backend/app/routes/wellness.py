"""POST/GET /api/wellness -- logging and listing daily wellness check-ins.

Same conventions as `routes/workouts.py` (see its module docstring): writes
go through `make_store(settings)`, the server assigns `id`/`athlete_id`/
`schema_version`, and validation happens by constructing the pydantic
`Wellness` model directly, turning a `ValidationError` into a 422
`{"error": ...}` response.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError
from swim_coach.models import Wellness

from app.auth import require_auth
from app.store_factory import make_store

router = APIRouter()

_SERVER_ASSIGNED_FIELDS = {"id", "athlete_id", "schema_version"}


@router.post("/api/wellness")
async def create_wellness(
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
        wellness = Wellness(
            id=uuid4(),
            athlete_id=profile.id,
            schema_version=1,
            **client_fields,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    store.save_wellness(athlete, wellness)
    return wellness.model_dump(mode="json")


@router.get("/api/wellness")
async def list_wellness(
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

    entries = store.list_wellness(athlete)
    return [w.model_dump(mode="json") for w in entries]
