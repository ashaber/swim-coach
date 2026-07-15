"""POST /api/chat -- the conversational coach endpoint.

Assembles cache-optimized context (`app.context`), builds the tool loop
(`app.tools`, `app.claude`), and streams the reply back as SSE. Persists
nothing server-side for v1 -- `history` is client-supplied on every request
(ROADMAP.md: auth-lite v1, real persistence lands with Supabase in the same
Phase 2 push as the PWA's chat tab, or Phase 3; see the report's TODOs).
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.auth import (
    Principal,
    require_auth,
    require_chat_rate_limit,
    require_daily_chat_cap,
    resolve_athlete,
)
from app.claude import ClaudeChat
from app.context import build_messages, build_system, find_workout_by_id
from app.store_factory import make_store
from app.tools import TOOLS_SCHEMA, build_tool_handlers

router = APIRouter()


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[HistoryMessage] = Field(default_factory=list)
    athlete: str = "renee"
    expert_mode: bool = False
    # Scopes this chat to one already-logged workout (the Log tab's embedded
    # workout chat -- see context.render_focused_workout): when present, that
    # workout's full detail is injected into the per-request context block.
    # Matched by exact id or case-insensitive prefix (same convention as the
    # CLI's --workout-id); an unknown id is a 404 before any streaming starts.
    workout_id: str | None = None


def get_claude_chat(request: Request) -> ClaudeChat:
    """Lazily builds (and caches on `app.state`) the real `ClaudeChat`.

    Tests override this dependency via
    `app.dependency_overrides[get_claude_chat] = lambda: fake_chat` so no
    real `anthropic.Anthropic()` client is ever constructed in the test
    suite.
    """
    if getattr(request.app.state, "claude_chat", None) is None:
        request.app.state.claude_chat = ClaudeChat(request.app.state.settings)
    return request.app.state.claude_chat


@router.post("/api/chat")
async def chat(
    payload: ChatRequest,
    request: Request,
    principal: Principal = Depends(require_auth),
    claude_chat: ClaudeChat = Depends(get_claude_chat),
) -> StreamingResponse:
    settings = request.app.state.settings
    # Athlete-session scoping: the session's athlete wins; a mismatched
    # `athlete` in the body is a 403 (the cross-athlete guarantee). A service
    # principal passes through unchanged -- the live PWA (shared token) still
    # sends `athlete` in the body and reaches whichever athlete it names.
    athlete = resolve_athlete(principal, payload.athlete)
    # Per-minute limiter keys off the raw token (per athlete-session now);
    # the per-athlete daily cap is a no-op for a service principal.
    require_chat_rate_limit(request, principal.token)
    require_daily_chat_cap(request, principal)

    store = make_store(settings)

    # Resolve the scoped workout (if any) BEFORE the stream starts -- an
    # unknown workout_id must be an ordinary 404 {"error": ...} JSON
    # response, never a mid-stream crash (once StreamingResponse has begun,
    # a raised exception can't become a clean error status any more).
    focused_workout = None
    if payload.workout_id is not None:
        focused_workout = find_workout_by_id(
            store.list_workouts(athlete), payload.workout_id
        )
        if focused_workout is None:
            raise HTTPException(
                status_code=404, detail=f"no workout matching id {payload.workout_id!r}"
            )

    system = build_system(settings.library_dir, payload.message)
    history = [{"role": h.role, "content": h.content} for h in payload.history]
    messages = build_messages(
        store,
        athlete,
        message=payload.message,
        history=history,
        expert_mode=payload.expert_mode,
        focused_workout=focused_workout,
    )
    tool_handlers = build_tool_handlers(
        store,
        slug=athlete,
        expert_mode=payload.expert_mode,
    )

    def event_stream():
        yield from claude_chat.run_streaming(system, messages, TOOLS_SCHEMA, tool_handlers)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
