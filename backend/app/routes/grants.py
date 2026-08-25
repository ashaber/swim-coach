"""POST/GET/PATCH /api/grants -- athlete-side coach-grant management
(coach-mode Phase 1).

"Manage who can coach ME" -- gated the same, self-access way every other
`?athlete=`-scoped route is (`resolve_athlete`, NOT `resolve_coach_athlete`;
see `routes/coach.py` for that wholly separate coach-side view). Backed by
`store.create_coach_grant`/`list_coach_grants`/`revoke_coach_grant`
(engine/swim_coach/store.py, merged on main) -- this file adds no new store
surface, only the HTTP layer over what's already there.

`chat_visibility` is deliberately not exposed as a payload option yet
(Phase-1 scope) -- `store.create_coach_grant`'s default (`"shared_only"`) is
always used.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.auth import Principal, require_auth, resolve_athlete
from app.store_factory import make_store

router = APIRouter()


@router.post("/api/grants")
async def create_grant(
    payload: dict[str, Any],
    request: Request,
    athlete: str | None = Query(None),
    principal: Principal = Depends(require_auth),
) -> dict:
    settings = request.app.state.settings
    athlete = resolve_athlete(principal, athlete)
    store = make_store(settings)

    coach_slug = payload.get("coach_slug")
    if not isinstance(coach_slug, str) or not coach_slug:
        raise HTTPException(status_code=422, detail="coach_slug must be a non-empty string")

    try:
        grant = store.create_coach_grant(coach_slug=coach_slug, athlete_slug=athlete)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"no such coach: {coach_slug}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return grant.model_dump(mode="json")


@router.get("/api/grants")
async def list_grants(
    request: Request,
    athlete: str | None = Query(None),
    principal: Principal = Depends(require_auth),
) -> list[dict]:
    settings = request.app.state.settings
    athlete = resolve_athlete(principal, athlete)
    store = make_store(settings)

    grants = store.list_coach_grants(athlete_slug=athlete)
    return [g.model_dump(mode="json") for g in grants]


@router.patch("/api/grants/{grant_id}")
async def revoke_grant(
    grant_id: UUID,
    payload: dict[str, Any],
    request: Request,
    athlete: str | None = Query(None),
    principal: Principal = Depends(require_auth),
) -> dict:
    settings = request.app.state.settings
    athlete = resolve_athlete(principal, athlete)
    store = make_store(settings)

    # This route only ever revokes -- there's no other field a body could
    # set -- but for symmetry with the general PATCH-body convention
    # elsewhere (routes/feedback.py), accept an optional {"status":
    # "revoked"} and 422 on any other value rather than silently ignoring
    # it.
    status = payload.get("status")
    if status is not None and status != "revoked":
        raise HTTPException(status_code=422, detail='status, if given, must be "revoked"')

    # Ownership check: an athlete may only revoke grants THEY made (i.e.
    # grants where they are the coached athlete), not ones made by some
    # other athlete -- resolve_athlete alone only proves the caller may act
    # as `athlete`, not that this specific grant belongs to them.
    owned_ids = {g.id for g in store.list_coach_grants(athlete_slug=athlete)}
    if grant_id not in owned_ids:
        raise HTTPException(status_code=404, detail=f"no such grant: {grant_id}")

    updated = store.revoke_coach_grant(grant_id)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"no such grant: {grant_id}")

    return updated.model_dump(mode="json")
