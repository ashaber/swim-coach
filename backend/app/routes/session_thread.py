"""GET/PATCH /api/sessions/{session_id}/thread -- a planned session's own chat thread.

The athlete's messages themselves go through `POST /api/chat` with `session_id` (same SSE contract
as a workout's thread); these two routes read the persisted thread back (old single-turn Q&A
imported, see `app.session_thread`) and flip the AI mute switch.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from swim_coach.models import Session
from swim_coach.session_lookup import find_in_store
from swim_coach.store import StoreInterface

from app.auth import Principal, require_auth, resolve_athlete
from app.session_thread import thread_messages
from app.store_factory import make_store

router = APIRouter()


def _require_session(store: StoreInterface, athlete: str, session_id: UUID) -> Session:
    session = find_in_store(store, athlete, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"no planned session with id {session_id}")
    return session


@router.get("/api/sessions/{session_id}/thread")
async def get_session_thread(
    session_id: UUID,
    request: Request,
    athlete: str | None = Query(None),
    principal: Principal = Depends(require_auth),
) -> dict:
    athlete = resolve_athlete(principal, athlete)
    store = make_store(request.app.state.settings)
    session = _require_session(store, athlete, session_id)
    return {
        "session_id": str(session.id),
        "ai_muted": store.get_session_thread(athlete, session.id).ai_muted,
        "messages": [m.model_dump(mode="json") for m in thread_messages(store, athlete, session)],
    }


@router.patch("/api/sessions/{session_id}/thread")
async def patch_session_thread(
    session_id: UUID,
    payload: dict[str, Any],
    request: Request,
    athlete: str | None = Query(None),
    principal: Principal = Depends(require_auth),
) -> dict:
    athlete = resolve_athlete(principal, athlete)
    muted = payload.get("ai_muted")
    if not isinstance(muted, bool):
        raise HTTPException(status_code=422, detail="ai_muted must be true or false")
    store = make_store(request.app.state.settings)
    session = _require_session(store, athlete, session_id)
    state = store.set_session_thread_muted(athlete, session.id, muted)
    return {"session_id": str(session.id), "ai_muted": state.ai_muted}
