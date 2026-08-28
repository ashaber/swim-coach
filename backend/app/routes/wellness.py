"""POST/GET /api/wellness -- logging and listing daily wellness check-ins.

Same conventions as `routes/workouts.py` (see its module docstring): writes
go through `make_store(settings)` and the server assigns `id`/`athlete_id`/
`schema_version`.

`create_wellness` merges into any existing row for the same date via
`app.wellness_merge.merge_wellness` rather than blindly overwriting --
`Wellness`'s subjective fields became optional (see swim_coach.models, added
for the intervals.icu sync in `app.sync`), which means pydantic itself no
longer enforces the check-in form's own required fields. Before this fix,
`create_wellness` built a brand-new `Wellness` from just the request body and
fully overwrote via `save_wellness`'s upsert-by-date -- since the check-in
form always sends `resting_hr`/`hrv` as `null` unless the athlete explicitly
types a value, this would silently null out any sync-derived value the next
time the athlete submitted or edited a check-in for that day. `merge_wellness`
closes that gap; the explicit `_REQUIRED_CHECKIN_FIELDS` check below replaces
pydantic's old free required-field enforcement now that the model is
intentionally more permissive.
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError

from app.auth import Principal, require_auth, resolve_athlete
from app.store_factory import make_store
from app.wellness_merge import merge_wellness

router = APIRouter()

_SERVER_ASSIGNED_FIELDS = {"id", "athlete_id", "schema_version"}

# A human explicitly filling out the check-in form must still supply all
# five subjective fields -- `Wellness` itself no longer enforces this (see
# module docstring) now that a sync-only row is allowed to omit them.
_REQUIRED_CHECKIN_FIELDS = ("sleep_quality", "sleep_hours", "stress", "soreness", "motivation")


@router.post("/api/wellness")
async def create_wellness(
    payload: dict[str, Any],
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

    client_fields = {k: v for k, v in payload.items() if k not in _SERVER_ASSIGNED_FIELDS}
    missing = [f for f in _REQUIRED_CHECKIN_FIELDS if client_fields.get(f) is None]
    if missing:
        raise HTTPException(
            status_code=422, detail=f"missing required check-in field(s): {', '.join(missing)}"
        )

    try:
        check_in_date = date_type.fromisoformat(str(client_fields.get("date")))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="date must be an ISO date string") from exc

    existing = next((w for w in store.list_wellness(athlete) if w.date == check_in_date), None)
    try:
        wellness = merge_wellness(
            existing,
            client_fields,
            athlete_id=profile.id,
            date=check_in_date,
            source="manual",  # a human explicitly submitted this check-in
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    store.save_wellness(athlete, wellness)
    return wellness.model_dump(mode="json")


@router.get("/api/wellness")
async def list_wellness(
    request: Request,
    athlete: str | None = Query(None),
    principal: Principal = Depends(require_auth),
) -> list[dict]:
    settings = request.app.state.settings
    athlete = resolve_athlete(principal, athlete)
    store = make_store(settings)
    try:
        store.load_athlete(athlete)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"no such athlete: {athlete}") from exc

    entries = store.list_wellness(athlete)
    return [w.model_dump(mode="json") for w in entries]
