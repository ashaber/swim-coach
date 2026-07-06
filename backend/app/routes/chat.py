"""POST /api/chat -- the conversational coach endpoint.

Assembles cache-optimized context (`app.context`), builds the tool loop
(`app.tools`, `app.claude`), and streams the reply back as SSE. Persists
nothing server-side for v1 -- `history` is client-supplied on every request
(ROADMAP.md: auth-lite v1, real persistence lands with Supabase in the same
Phase 2 push as the PWA's chat tab, or Phase 3; see the report's TODOs).
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from swim_coach.store import FileStore

from app.auth import require_auth, require_chat_rate_limit
from app.claude import ClaudeChat
from app.context import build_messages, build_system
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
    token: str = Depends(require_auth),
    claude_chat: ClaudeChat = Depends(get_claude_chat),
) -> StreamingResponse:
    settings = request.app.state.settings
    require_chat_rate_limit(request, token)

    store = FileStore(base_dir=settings.athletes_dir)
    system = build_system(settings.library_dir, payload.message)
    history = [{"role": h.role, "content": h.content} for h in payload.history]
    messages = build_messages(
        store,
        payload.athlete,
        message=payload.message,
        history=history,
        expert_mode=payload.expert_mode,
    )
    tool_handlers = build_tool_handlers(
        store,
        slug=payload.athlete,
        research_dir=settings.research_dir,
        expert_mode=payload.expert_mode,
    )

    def event_stream():
        yield from claude_chat.run_streaming(system, messages, TOOLS_SCHEMA, tool_handlers)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
