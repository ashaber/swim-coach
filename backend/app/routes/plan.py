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
from app.store_factory import make_store

_REPO_ROOT_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
if str(_REPO_ROOT_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT_SCRIPTS_DIR))

from export_plan_json import export_athlete  # noqa: E402 - after sys.path setup

router = APIRouter()


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
