"""GET /api/plan -- the read-only exported plan JSON for one athlete.

Reuses `scripts/export_plan_json.export_athlete` (the same exporter the
`web/` PWA's prebuild step calls) rather than re-deriving the export shape
here -- one exporter, two consumers (a static prebuild step and this live
endpoint).

`scripts/` isn't an installed package, so it's added to `sys.path` at import
time. The repo layout this assumes (`backend/app/routes/plan.py` is three
directories under the repo root, which also contains `scripts/`) is the same
layout `backend/Dockerfile` reproduces in the image -- see its `COPY
scripts/` step.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.auth import Principal, require_auth, resolve_athlete
from app.context import summarize_rollup
from app.store_factory import make_store

_REPO_ROOT_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
if str(_REPO_ROOT_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT_SCRIPTS_DIR))

from export_plan_json import export_athlete  # noqa: E402 - after sys.path setup

router = APIRouter()

# `get_plan_summary` (the coach-chat tool, backend/app/tools.py) defaults to
# 4 trailing weeks -- fine for volume/compliance/monotony, but too short to
# read a CTL/ATL/TSB trend against: CTL is a 42-day (6-week) exponentially
# weighted average, so a 4-week window barely gets past cold-start (see
# `ctl_atl_tsb_series`'s docstring in engine/swim_coach/load.py) and never
# shows the trend actually settling. 12 weeks (~84 days, exactly the tool's
# own upper bound) gives roughly 2x the CTL time constant's worth of history
# -- enough for the fitness line's shape to be readable on a graph -- while
# still matching the same 1-12 bound `get_plan_summary`'s own `weeks`
# parameter already enforces, so this isn't a new convention.
LOAD_GRAPH_DEFAULT_WEEKS = 12
LOAD_GRAPH_MIN_WEEKS = 1
LOAD_GRAPH_MAX_WEEKS = 12


@router.get("/api/plan")
async def get_plan(
    request: Request,
    athlete: str | None = Query(None),
    principal: Principal = Depends(require_auth),
) -> dict:
    settings = request.app.state.settings
    athlete = resolve_athlete(principal, athlete)
    store = make_store(settings)
    try:
        return export_athlete(store, athlete)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"no such athlete: {athlete}") from exc


@router.get("/api/plan/load")
async def get_plan_load(
    request: Request,
    athlete: str | None = Query(None),
    weeks: int = Query(LOAD_GRAPH_DEFAULT_WEEKS, ge=LOAD_GRAPH_MIN_WEEKS, le=LOAD_GRAPH_MAX_WEEKS),
    principal: Principal = Depends(require_auth),
) -> dict:
    """The Banister CTL/ATL/TSB series (`summarize_rollup`'s `ctl_atl_tsb`
    field) plus the `wellness_baseline_deviation` resting-HR/HRV cross-check
    for the athlete's own Plan-tab chart -- a minimal, graph-shaped slice of
    the rollup rather than the whole dict, since those are the only fields
    the chart needs. Calls `summarize_rollup` directly; no math is
    reimplemented here."""
    settings = request.app.state.settings
    athlete = resolve_athlete(principal, athlete)
    store = make_store(settings)
    try:
        store.load_athlete(athlete)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"no such athlete: {athlete}") from exc
    rollup = summarize_rollup(store, athlete, weeks=weeks)
    return {
        "athlete": athlete,
        "weeks": weeks,
        "ctl_atl_tsb": rollup["ctl_atl_tsb"],
        "wellness_baseline_deviation": rollup["wellness_baseline_deviation"],
    }
