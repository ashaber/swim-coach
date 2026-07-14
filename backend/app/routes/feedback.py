"""POST/GET/PATCH /api/feedback -- the durable feedback log.

Generalizes IDEA 005's coach `log_open_question` tool (see app/tools.py) into
a durable log that also holds athlete-submitted feature requests, comments,
and bug reports from the PWA's Feedback tab. Persisted via
`store.save_feedback`/`list_feedback` (engine/swim_coach/models.Feedback) --
`FileStore` locally, `DbStore` in prod -- replacing the old ephemeral
`research/open-questions.jsonl` file that Cloud Run silently wiped on every
scale-to-zero.

Same conventions as routes/workouts.py and routes/wellness.py: writes go
through `make_store(settings)`, the server assigns `id`/`athlete_id`/
`schema_version`/`source`/`status`/`created_at`, and validation happens by
constructing the pydantic `Feedback` model directly -- a `ValidationError`
becomes a 422 `{"error": ...}` response.

`type=research_question` is coach-only (it's what `log_open_question` logs,
tagged `source="coach"`, automatically) -- this endpoint always sets
`source="athlete"` and explicitly rejects that type before it ever reaches
model construction, since `Feedback`'s own `type` field accepts it as a
valid literal value.

`PATCH /api/feedback/{id}` closes the research loop: without it, a coach-
logged `research_question` (or an athlete's feature_request/comment/bug) has
no way to be marked resolved once acted on -- e.g. once a library topic file
answers a logged gap -- so the same gap would otherwise be re-researched
indefinitely. Same auth gate as the rest of this module; merges `context`
into the existing entry (via `store.update_feedback`) rather than clobbering
it, and 404s on an unknown id.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError
from swim_coach.models import Feedback

from app.auth import require_auth
from app.store_factory import make_store

router = APIRouter()

# Fields the server assigns itself -- stripped from the client payload before
# constructing the model, same pattern as routes/workouts.py's
# _SERVER_ASSIGNED_FIELDS. `source` is always "athlete" for this endpoint
# (the coach-sourced "research_question" type only ever comes from
# app.tools's log_open_question tool handler); `status` always starts "open".
_SERVER_ASSIGNED_FIELDS = {"id", "athlete_id", "schema_version", "source", "status", "created_at"}

# The only types an athlete may submit through this endpoint --
# "research_question" is coach-only (see module docstring).
_ATHLETE_SUBMITTABLE_TYPES = {"feature_request", "comment", "bug"}


@router.post("/api/feedback")
async def create_feedback(
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
    if client_fields.get("type") not in _ATHLETE_SUBMITTABLE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"type must be one of {sorted(_ATHLETE_SUBMITTABLE_TYPES)}; "
                "research_question is coach-only"
            ),
        )

    try:
        feedback = Feedback(
            id=uuid4(),
            athlete_id=profile.id,
            schema_version=1,
            source="athlete",
            status="open",
            created_at=datetime.now(timezone.utc),
            **client_fields,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    store.save_feedback(feedback)
    return feedback.model_dump(mode="json")


@router.get("/api/feedback")
async def list_feedback(
    request: Request,
    athlete: str = Query("renee"),
    _token: str = Depends(require_auth),
) -> list[dict]:
    settings = request.app.state.settings
    store = make_store(settings)
    try:
        entries = store.list_feedback(athlete=athlete)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"no such athlete: {athlete}") from exc

    return [f.model_dump(mode="json") for f in entries]


@router.patch("/api/feedback/{feedback_id}")
async def update_feedback(
    feedback_id: UUID,
    payload: dict[str, Any],
    request: Request,
    _token: str = Depends(require_auth),
) -> dict:
    settings = request.app.state.settings
    store = make_store(settings)

    status = payload.get("status")
    context = payload.get("context")
    if status is not None and not isinstance(status, str):
        raise HTTPException(status_code=422, detail="status must be a string")
    if context is not None and not isinstance(context, dict):
        raise HTTPException(status_code=422, detail="context must be an object")

    updated = store.update_feedback(feedback_id, status=status, context=context)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"no such feedback entry: {feedback_id}")

    return updated.model_dump(mode="json")
