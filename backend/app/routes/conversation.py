"""The athlete<->coach conversation (IDEA 016 "Part 2") -- a persisted, three-party (athlete, AI
coach, human coach) thread per athlete-coach pair, NOT scoped to a workout. The athlete sees it
as "My coach" inside the Coach tab; the coach sees it on the roster's Conversations sub-tab.

Athlete side (`resolve_athlete`, the athlete's own routes; the thread's coach must hold an ACTIVE
grant for this athlete, else 404):
  GET   /api/conversations                               -- the athlete's threads (one per active coach)
  GET   /api/conversations/{coach_athlete_id}/messages   -- messages (`?since=` cursor) + mute state
  POST  /api/conversations/{coach_athlete_id}/messages   -- post; SSE stream with the AI's reply
  PATCH /api/conversations/{coach_athlete_id}            -- mute/unmute the AI

Coach side (`resolve_coach_athlete`, requires a grant; always a real coach identity -- a service
credential has none to stamp on a message):
  GET   /api/coach/athletes/{slug}/conversation          -- messages (`?since=`) + mute state
  POST  /api/coach/athletes/{slug}/conversation/messages -- the coach's comment (no model call)
  PATCH /api/coach/athletes/{slug}/conversation          -- mute/unmute the AI

AI behaviour mirrors the per-workout thread (`routes/chat.py`): an athlete post gets an AI reply
through the same `stream_chat_response` machinery (daily cap and rate limit included) unless the
thread is muted; a coach comment never triggers a reply by itself -- an unanswered one is folded
onto the athlete's next message so the Messages API's user/assistant alternation holds
(`_history_from_workout_chat`). A MUTED thread skips the model call entirely and consumes no
chat cap. Polling: clients pass the newest `created_at` they hold as `since` (inclusive) and
de-duplicate by id.
"""

from __future__ import annotations

import functools
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from swim_coach.models import ConversationMessage
from swim_coach.store import StoreInterface

from app.auth import Principal, require_auth, resolve_athlete, resolve_coach_athlete
from app.claude import ClaudeChat
from app.config import Settings
from app.notify import notify_athlete_of_conversation_message, notify_coach_of_conversation_message
from app.routes.chat import (
    ChatRequest,
    _append_conversation_message,
    _muted_thread_stream,
    get_claude_chat,
    stream_chat_response,
)
from app.store_factory import make_store

router = APIRouter()

# Same seam convention as `routes/coach.py`'s `get_workout_chat_notifier`: a dependency indirection
# so tests can swap in a spy instead of a real Resend call.
ConversationNotifier = Callable[[StoreInterface, Settings, ConversationMessage, str], None]

MAX_MESSAGE_CHARS = 4000


def get_athlete_side_notifier(request: Request) -> ConversationNotifier:
    """Notifies the thread's COACH of an athlete's message (overridable in tests)."""
    return notify_coach_of_conversation_message


def get_coach_side_notifier(request: Request) -> ConversationNotifier:
    """Notifies the ATHLETE of a coach's message (overridable in tests)."""
    return notify_athlete_of_conversation_message


def _parse_since(since: str | None) -> datetime | None:
    if since is None:
        return None
    try:
        parsed = datetime.fromisoformat(since)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="since must be an ISO-8601 timestamp") from exc
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _clean_body(raw: Any, field: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise HTTPException(status_code=422, detail=f"{field} must be a non-empty string")
    if len(raw) > MAX_MESSAGE_CHARS:
        raise HTTPException(status_code=422, detail=f"{field} must be at most {MAX_MESSAGE_CHARS} characters")
    return raw.strip()


def _require_ai_muted_flag(payload: dict[str, Any]) -> bool:
    muted = payload.get("ai_muted")
    if not isinstance(muted, bool):
        raise HTTPException(status_code=422, detail="ai_muted must be true or false")
    return muted


def _thread_payload(
    store: StoreInterface, slug: str, coach_athlete_id: UUID, since: datetime | None
) -> dict:
    messages = store.list_conversation_messages(slug, coach_athlete_id, since=since)
    return {
        "coach_athlete_id": str(coach_athlete_id),
        "ai_muted": store.get_conversation(slug, coach_athlete_id).ai_muted,
        "messages": [m.model_dump(mode="json") for m in messages],
    }


def _coach_identity(store: StoreInterface, principal: Principal) -> UUID:
    """The coach's own athlete id -- a message needs one real coach identity, which a service
    credential does not have (same rule as `routes/coach.py`'s other coach-writes)."""
    if principal.kind != "athlete" or principal.athlete is None:
        raise HTTPException(
            status_code=403,
            detail="the coach conversation requires a single coach identity; a service credential has none",
        )
    return store.load_athlete(principal.athlete).id


def _require_active_coach(store: StoreInterface, athlete: str, coach_athlete_id: UUID) -> None:
    grants = store.list_coach_grants(athlete_slug=athlete, status="active")
    if not any(g.coach_athlete_id == coach_athlete_id for g in grants):
        raise HTTPException(status_code=404, detail="no such conversation")


# --- athlete side -----------------------------------------------------------


@router.get("/api/conversations")
async def list_conversations(
    request: Request,
    athlete: str | None = Query(None),
    principal: Principal = Depends(require_auth),
) -> list[dict]:
    athlete = resolve_athlete(principal, athlete)
    store = make_store(request.app.state.settings)
    grants = store.list_coach_grants(athlete_slug=athlete, status="active")
    return [
        {
            "coach_athlete_id": str(g.coach_athlete_id),
            "ai_muted": store.get_conversation(athlete, g.coach_athlete_id).ai_muted,
        }
        for g in grants
    ]


@router.get("/api/conversations/{coach_athlete_id}/messages")
async def get_conversation_messages(
    coach_athlete_id: UUID,
    request: Request,
    athlete: str | None = Query(None),
    since: str | None = Query(None),
    principal: Principal = Depends(require_auth),
) -> dict:
    athlete = resolve_athlete(principal, athlete)
    store = make_store(request.app.state.settings)
    _require_active_coach(store, athlete, coach_athlete_id)
    return _thread_payload(store, athlete, coach_athlete_id, _parse_since(since))


@router.patch("/api/conversations/{coach_athlete_id}")
async def set_conversation_muted(
    coach_athlete_id: UUID,
    payload: dict[str, Any],
    request: Request,
    athlete: str | None = Query(None),
    principal: Principal = Depends(require_auth),
) -> dict:
    athlete = resolve_athlete(principal, athlete)
    store = make_store(request.app.state.settings)
    _require_active_coach(store, athlete, coach_athlete_id)
    muted = _require_ai_muted_flag(payload)
    store.set_conversation_muted(athlete, coach_athlete_id, muted)
    return {"coach_athlete_id": str(coach_athlete_id), "ai_muted": muted}


def _notify_coach_of_latest_athlete_message(
    notifier: ConversationNotifier, store: StoreInterface, settings: Settings,
    athlete: str, coach_athlete_id: UUID,
) -> None:
    """Background task: runs AFTER the athlete's turn finished streaming, so the message
    (saved up front by the thread-persistence wrapper) is in the store. Notifies for the most
    recent athlete message in the thread."""
    recent = store.list_conversation_messages(athlete, coach_athlete_id, limit=10)
    latest = next((m for m in reversed(recent) if m.sender_role == "athlete"), None)
    if latest is not None:
        notifier(store, settings, latest, athlete)


@router.post("/api/conversations/{coach_athlete_id}/messages")
async def post_conversation_message(
    coach_athlete_id: UUID,
    payload: dict[str, Any],
    request: Request,
    background_tasks: BackgroundTasks,
    athlete: str | None = Query(None),
    principal: Principal = Depends(require_auth),
    claude_chat: ClaudeChat = Depends(get_claude_chat),
    notifier: ConversationNotifier = Depends(get_athlete_side_notifier),
) -> StreamingResponse:
    """The athlete's message in the thread. Answers with an SSE stream (the exact event contract
    of `POST /api/chat`): the AI's reply when the thread is not muted, a short notice when it is.
    The message is persisted either way, and the thread's coach is notified (throttled)."""
    athlete = resolve_athlete(principal, athlete)
    settings = request.app.state.settings
    store = make_store(settings)
    _require_active_coach(store, athlete, coach_athlete_id)
    message = _clean_body(payload.get("message"), "message")
    background_tasks.add_task(
        _notify_coach_of_latest_athlete_message, notifier, store, settings, athlete, coach_athlete_id
    )

    if store.get_conversation(athlete, coach_athlete_id).ai_muted:
        append = functools.partial(_append_conversation_message, store, athlete, coach_athlete_id)
        response = StreamingResponse(
            _muted_thread_stream(append, message), media_type="text/event-stream"
        )
        response.background = background_tasks
        return response

    chat_payload = ChatRequest(message=message, athlete=athlete)
    response = await stream_chat_response(
        chat_payload, request, principal, claude_chat,
        athlete=athlete, conversation_coach_id=coach_athlete_id,
    )
    response.background = background_tasks
    return response


# --- coach side -------------------------------------------------------------


@router.get("/api/coach/athletes/{slug}/conversation")
async def coach_get_conversation(
    slug: str,
    request: Request,
    since: str | None = Query(None),
    principal: Principal = Depends(require_auth),
) -> dict:
    slug = resolve_coach_athlete(principal, slug)
    store = make_store(request.app.state.settings)
    coach_id = _coach_identity(store, principal)
    return _thread_payload(store, slug, coach_id, _parse_since(since))


@router.post("/api/coach/athletes/{slug}/conversation/messages")
async def coach_post_conversation_message(
    slug: str,
    payload: dict[str, Any],
    request: Request,
    background_tasks: BackgroundTasks,
    principal: Principal = Depends(require_auth),
    notifier: ConversationNotifier = Depends(get_coach_side_notifier),
) -> dict:
    """The human coach's comment -- a plain append, no model call (the AI sees it as context on
    the athlete's next turn and does not reply on its own)."""
    settings = request.app.state.settings
    slug = resolve_coach_athlete(principal, slug)
    store = make_store(settings)
    coach_id = _coach_identity(store, principal)
    body = _clean_body(payload.get("body"), "body")

    message = ConversationMessage(
        id=uuid4(), athlete_id=store.load_athlete(slug).id, coach_athlete_id=coach_id,
        sender_role="coach", body=body, created_at=datetime.now(timezone.utc),
    )
    store.append_conversation_message(slug, message)
    background_tasks.add_task(notifier, store, settings, message, slug)
    return message.model_dump(mode="json")


@router.patch("/api/coach/athletes/{slug}/conversation")
async def coach_set_conversation_muted(
    slug: str,
    payload: dict[str, Any],
    request: Request,
    principal: Principal = Depends(require_auth),
) -> dict:
    slug = resolve_coach_athlete(principal, slug)
    store = make_store(request.app.state.settings)
    coach_id = _coach_identity(store, principal)
    muted = _require_ai_muted_flag(payload)
    store.set_conversation_muted(slug, coach_id, muted)
    return {"coach_athlete_id": str(coach_id), "ai_muted": muted}
