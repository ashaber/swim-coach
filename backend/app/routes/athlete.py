"""GET/PATCH /api/athlete -- self-service profile read/edit.

Lets an athlete edit their own profile (name, dob, sex, height_cm,
weight_kg, css_pace_s_per_100m, pool_schedule) from the PWA instead of Fable
hand-loading YAML. Same conventions as routes/workouts.py and
routes/wellness.py: everything goes via `make_store(settings)`
(`FileStore` locally, `DbStore` in prod) so an edit here reaches the live
coach with no redeploy, and validation happens by constructing the pydantic
`Athlete` model directly -- a `ValidationError` becomes a 422.

`id`/`slug`/`schema_version`/`zones` are never accepted from the client:
`id`/`slug`/`schema_version` are stripped and the existing profile's values
kept; `zones` is DERIVED -- it's always recomputed from `zone_table()` (the
same engine function `cli zones --write` uses), and only when
`css_pace_s_per_100m` actually changes (an athlete with no CSS pace set yet
keeps `zones: null` until one exists).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError
from swim_coach.models import Athlete
from swim_coach.zones import zone_table

from app.auth import Principal, require_auth, resolve_athlete
from app.store_factory import make_store

router = APIRouter()

# Fields the server owns -- never taken from the client payload. `id`/
# `slug`/`schema_version` keep the existing profile's values; `zones` is
# always re-derived (see module docstring), never accepted verbatim.
_SERVER_OWNED_FIELDS = {"id", "slug", "schema_version", "zones"}


@router.get("/api/athlete")
async def get_athlete(
    request: Request,
    athlete: str | None = Query(None),
    principal: Principal = Depends(require_auth),
) -> dict:
    settings = request.app.state.settings
    athlete = resolve_athlete(principal, athlete)
    store = make_store(settings)
    try:
        profile = store.load_athlete(athlete)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"no such athlete: {athlete}") from exc
    return profile.model_dump(mode="json")


@router.patch("/api/athlete")
async def patch_athlete(
    payload: dict[str, Any],
    request: Request,
    athlete: str | None = Query(None),
    principal: Principal = Depends(require_auth),
) -> dict:
    settings = request.app.state.settings
    athlete = resolve_athlete(principal, athlete)
    store = make_store(settings)
    try:
        current = store.load_athlete(athlete)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"no such athlete: {athlete}") from exc

    client_fields = {k: v for k, v in payload.items() if k not in _SERVER_OWNED_FIELDS}
    merged = {**current.model_dump(mode="json"), **client_fields}
    merged["id"] = current.id
    merged["slug"] = current.slug
    merged["schema_version"] = current.schema_version
    merged["zones"] = current.zones

    try:
        updated = Athlete(**merged)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # CSS pace changed -> recompute the zone table via the engine's own
    # zone_table() (same function `python -m swim_coach.cli zones --write`
    # uses) -- never hand-computed here. Leave zones untouched (whatever the
    # existing profile had, including None) if css_pace_s_per_100m didn't
    # change or is now None.
    if (
        updated.css_pace_s_per_100m is not None
        and updated.css_pace_s_per_100m != current.css_pace_s_per_100m
    ):
        updated.zones = zone_table(updated.css_pace_s_per_100m)

    store.save_athlete(updated)
    return updated.model_dump(mode="json")
