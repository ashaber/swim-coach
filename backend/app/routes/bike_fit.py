"""Bike-fit snapshots: record dated geometry measurements and compare them.

A measuring and comparison tool only: nothing here recommends fit changes. Snapshots live on the
athlete record (`Athlete.bike_fit_snapshots`, raw inputs only, same no-migration shape as
`setup_log`); derived values are recomputed on every read. A snapshot is immutable once saved
except its `retired` flag, and is never deleted.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ValidationError
from swim_coach.athlete_time import athlete_today
from swim_coach.bike_fit import (
    COMPARE_SIGMA_FACTOR,
    WIDTH_DEFAULTS_MM,
    LIMITS_STATEMENT,
    TAPE_SIGMA_MM,
    TILT_ADVISORY_DEG,
    BikeFitError,
    compare_fits,
    compute_fit,
    resolve_snapshot,
    snapshot_view,
)
from swim_coach.models import Athlete, BikeFitSnapshot

from app.auth import Principal, require_auth, resolve_athlete
from app.bike_fit_tool import bike_setup_entries
from app.logging_config import get_logger
from app.store_factory import make_store

router = APIRouter()
log = get_logger(__name__)


class RetirePatch(BaseModel):
    retired: bool


def _load(request: Request, athlete: str | None, principal: Principal) -> tuple[Any, str, Athlete]:
    slug = resolve_athlete(principal, athlete)
    store = make_store(request.app.state.settings)
    try:
        return store, slug, store.load_athlete(slug)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"no such athlete: {slug}") from exc


def _first_error(exc: ValidationError) -> str:
    err = exc.errors()[0]
    where = ".".join(str(p) for p in err["loc"] if p != "inputs")
    return f"{where}: {err['msg']}" if where else err["msg"]


@router.get("/api/bike-fit")
async def list_bike_fit(
    request: Request, athlete: str | None = Query(None), principal: Principal = Depends(require_auth)
) -> dict:
    _, _, profile = _load(request, athlete, principal)
    return {
        "snapshots": [snapshot_view(s) for s in profile.bike_fit_snapshots],
        "defaults": {
            "width_mm": WIDTH_DEFAULTS_MM,
            "tape_sigma_mm": TAPE_SIGMA_MM,
            "tilt_advisory_deg": TILT_ADVISORY_DEG,
            "compare_sigma_factor": COMPARE_SIGMA_FACTOR,
        },
        "limits": LIMITS_STATEMENT,
        "setup_notes": [
            {"id": str(e.id), "date": e.date.isoformat(), "text": e.text,
             "pressure_front_psi": e.pressure_front_psi, "pressure_rear_psi": e.pressure_rear_psi}
            for e in bike_setup_entries(profile)
        ],
    }


@router.post("/api/bike-fit")
async def save_bike_fit(
    payload: dict[str, Any],
    request: Request,
    athlete: str | None = Query(None),
    principal: Principal = Depends(require_auth),
) -> dict:
    store, slug, profile = _load(request, athlete, principal)
    fields = {k: v for k, v in payload.items() if k not in ("id", "retired")}
    fields.setdefault("date", athlete_today(profile).isoformat())
    try:
        snapshot = BikeFitSnapshot(id=uuid.uuid4(), **fields)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_first_error(exc)) from exc
    except TypeError as exc:
        raise HTTPException(status_code=422, detail="unexpected fields in bike fit snapshot") from exc
    try:
        compute_fit(snapshot.inputs, snapshot.bike_type)
    except BikeFitError as exc:
        log.warn("bike fit unsolvable", athlete=slug, bike_type=snapshot.bike_type)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    profile.bike_fit_snapshots.append(snapshot)
    store.save_athlete(profile)
    log.info("bike fit saved", athlete=slug, snapshot_id=str(snapshot.id), bike_type=snapshot.bike_type)
    return snapshot_view(snapshot)


@router.get("/api/bike-fit/compare")
async def compare_bike_fit(
    request: Request,
    a: str = Query(...),
    b: str = Query(...),
    athlete: str | None = Query(None),
    principal: Principal = Depends(require_auth),
) -> dict:
    _, _, profile = _load(request, athlete, principal)
    first = resolve_snapshot(profile.bike_fit_snapshots, a)
    second = resolve_snapshot(profile.bike_fit_snapshots, b)
    if first is None or second is None:
        raise HTTPException(status_code=404, detail="no such bike fit snapshot")
    try:
        comparison = compare_fits(
            compute_fit(first.inputs, first.bike_type), compute_fit(second.inputs, second.bike_type)
        )
    except BikeFitError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"a": snapshot_view(first), "b": snapshot_view(second), **comparison.model_dump(mode="json")}


@router.patch("/api/bike-fit/{snapshot_id}")
async def retire_bike_fit(
    snapshot_id: str,
    payload: dict[str, Any],
    request: Request,
    athlete: str | None = Query(None),
    principal: Principal = Depends(require_auth),
) -> dict:
    """The only mutation a saved snapshot allows: set or clear `retired`."""
    store, slug, profile = _load(request, athlete, principal)
    snapshot = next((s for s in profile.bike_fit_snapshots if str(s.id) == snapshot_id), None)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="no such bike fit snapshot")
    try:
        patch = RetirePatch(retired=payload.get("retired"))
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail='send {"retired": true or false}') from exc
    snapshot.retired = patch.retired
    store.save_athlete(profile)
    log.info("bike fit retire flag set", athlete=slug, snapshot_id=snapshot_id, retired=patch.retired)
    return snapshot_view(snapshot)
