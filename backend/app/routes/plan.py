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
from swim_coach.store import FileStore

from app.auth import require_auth

_REPO_ROOT_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
if str(_REPO_ROOT_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT_SCRIPTS_DIR))

from export_plan_json import export_athlete  # noqa: E402 - after sys.path setup

router = APIRouter()


@router.get("/api/plan")
async def get_plan(
    request: Request,
    athlete: str = Query("renee"),
    _token: str = Depends(require_auth),
) -> dict:
    settings = request.app.state.settings
    store = FileStore(base_dir=settings.athletes_dir)
    try:
        return export_athlete(store, athlete)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"no such athlete: {athlete}") from exc
