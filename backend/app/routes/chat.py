"""POST /api/chat -- the conversational coach endpoint.

Assembles cache-optimized context (`app.context`), builds the tool loop
(`app.tools`, `app.claude`), and streams the reply back as SSE. Persists
nothing server-side for v1 -- `history` is client-supplied on every request
(ROADMAP.md: auth-lite v1, real persistence lands with Supabase in the same
Phase 2 push as the PWA's chat tab, or Phase 3; see the report's TODOs).
"""

from __future__ import annotations

import functools
import json
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from swim_coach.models import ConversationMessage, Workout, WorkoutChatMessage
from swim_coach.store import StoreInterface

from app.auth import (
    Principal,
    require_auth,
    require_chat_rate_limit,
    require_daily_chat_cap,
    resolve_athlete,
)
from app.claude import ClaudeChat, _sse
from app.context import (
    build_context_block,
    build_messages,
    build_routed_library_text,
    build_system,
    find_workout_by_id,
    route_info_for_logging,
)
from app.light_mode import (
    LIGHT_TOOLS,
    build_light_messages,
    build_light_system,
    is_light_turn,
)
from app.logging_config import get_logger
from app.notify import notify_athlete_of_coach_plan_change
from app.store_factory import make_store
from app.tools import TOOLS_SCHEMA, build_tool_handlers

router = APIRouter()
log = get_logger("app.routes.chat")


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


CONVERSATION_ASKER_NOTE = (
    "Thread context: this turn is in the athlete's shared \"My coach\" conversation -- their "
    "human coach can read every message here, and the coach's own comments reach you labelled "
    "\"[Your human coach]\". Answer the athlete as usual, but don't contradict or speak for the "
    "human coach; defer to them where they have already advised on the same point."
)


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


def _history_from_workout_chat(
    messages: list[WorkoutChatMessage] | list[ConversationMessage],
) -> tuple[list[dict[str, str]], str | None]:
    """Folds a persisted three-party thread (a workout's, or the athlete<->coach conversation's
    -- both only need `sender_role` and `body`) into strict user/assistant turns -- the
    Messages API allows no third role, so an athlete message and a human coach's comment
    (labelled, so the model can tell them apart) both become "user" turns, merging into ONE
    turn when they're consecutive rather than alternating awkwardly; an `ai_coach` message
    becomes "assistant". This is the REAL history for a workout-scoped turn now (IDEA 016) --
    the caller uses this instead of the client-supplied `payload.history`, so a human coach's
    comment reaches the AI's own context even though the athlete's browser never fetched it.

    Returns `(history_turns, pending_user_text)`. `build_messages`/`build_light_messages`
    ALWAYS append the new incoming message as a fresh final "user" turn -- if this thread's
    own last turn is already user-side (an unanswered coach comment), returning it as a
    trailing history turn would put two user turns back to back and the API would reject the
    whole request. `pending_user_text` is that trailing text instead, non-None exactly when
    the caller must fold it onto the front of the NEW message before sending -- `None` in the
    ordinary case (empty thread, or the last turn was already the AI's).
    """
    turns: list[dict[str, str]] = []
    for msg in messages:
        if msg.sender_role == "ai_coach":
            role, text = "assistant", msg.body
        elif msg.sender_role == "coach":
            role, text = "user", f"[Your human coach]: {msg.body}"
        else:
            role, text = "user", msg.body
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"] = f"{turns[-1]['content']}\n\n{text}"
        else:
            turns.append({"role": role, "content": text})
    pending = turns.pop()["content"] if turns and turns[-1]["role"] == "user" else None
    return turns, pending


def _append_workout_chat_message(
    store: StoreInterface, athlete: str, workout_id: uuid.UUID, sender_role: str, body: str
) -> None:
    """Appends one message to `workout_id`'s chat thread and saves -- reloading the workout
    FRESH right before writing (not reusing whatever was loaded at request start), so a human
    coach's comment posted via the coach-side route (`routes/coach.py`) during this turn's
    (possibly multi-second) streaming can't be silently lost to a stale overwrite. Logs and
    swallows a save failure rather than raising -- losing the persisted copy of a message the
    athlete/coach already saw stream by (or the coach's own reply) must never surface as a
    500 on top of an otherwise-successful chat turn (IDEA 016)."""
    try:
        workout = store.get_workout(athlete, workout_id)
        if workout is None:  # deleted/moved mid-turn -- nothing to append to
            return
        workout.chat_messages.append(
            WorkoutChatMessage(
                id=uuid.uuid4(), sender_role=sender_role, body=body,
                created_at=datetime.now(timezone.utc),
            )
        )
        store.save_workout(athlete, workout)
    except Exception:  # noqa: BLE001
        log.error(
            "workout chat message save failed", athlete=athlete, workout_id=str(workout_id),
            sender_role=sender_role, exc_info=True,
        )


def _parse_sse(line: str) -> dict[str, Any] | None:
    """The inverse of `app.claude._sse` (`f"data: {json.dumps(payload)}\n\n"`) -- used ONLY to
    peek at an already-SSE-framed line's event type/text for accumulation, never to change what
    actually gets sent to the client (the original string is always forwarded unchanged).
    `None` on anything that doesn't parse -- callers treat that as "not a recognized event",
    never as a reason to drop or alter the line itself."""
    if not line.startswith("data: "):
        return None
    try:
        return json.loads(line[len("data: "):].rstrip("\n"))
    except (json.JSONDecodeError, ValueError):
        return None


ThreadAppend = Callable[[str, str], None]
"""`(sender_role, body) -> None`: appends one message to whichever three-party thread (a
workout's, or the athlete<->coach conversation) the current turn belongs to."""


def _append_conversation_message(
    store: StoreInterface, athlete: str, coach_athlete_id: uuid.UUID, sender_role: str, body: str
) -> None:
    """Appends one message to the athlete<->coach conversation thread. The conversation table is
    append-only (a plain INSERT / line append), so unlike `_append_workout_chat_message` there is
    no read-modify-write to race a coach's concurrent comment. Same log-and-swallow failure
    policy: losing the persisted copy of a message the athlete already saw stream by must never
    become a 500 on an otherwise-successful turn."""
    try:
        store.append_conversation_message(
            athlete,
            ConversationMessage(
                id=uuid.uuid4(), athlete_id=store.load_athlete(athlete).id,
                coach_athlete_id=coach_athlete_id, sender_role=sender_role, body=body,
                created_at=datetime.now(timezone.utc),
            ),
        )
    except Exception:  # noqa: BLE001
        log.error(
            "conversation message save failed", athlete=athlete,
            coach_athlete_id=str(coach_athlete_id), sender_role=sender_role, exc_info=True,
        )


def _muted_thread_stream(append: ThreadAppend, message: str) -> Iterator[str]:
    """The athlete's message still saves (visible in the thread, and to whoever un-mutes it
    later); no model call happens at all. Yields a short, honest notice + done, SSE-framed the
    same way `claude.run_streaming` frames its own events, so the existing streaming UI (which
    expects at least one text event before done) has something to show -- without persisting
    that notice itself as an ai_coach turn."""
    notice = "(Saved. The coach's replies are muted in this thread right now.)"
    append("athlete", message)
    yield _sse({"type": "text", "text": notice})
    yield _sse({"type": "done", "stop_reason": "end_turn"})


def _persisting_thread_stream(
    append: ThreadAppend, message: str, inner: Iterator[str], *, user_first: bool = False,
) -> Iterator[str]:
    """Wraps `inner` (the real, already-SSE-framed `claude_chat.run_streaming` generator) to
    forward every line to the client completely unchanged, while peeking at each one (via
    `_parse_sse`) to accumulate the assistant's visible text exactly the way the PWA's own
    `applyStreamEvent` does (concatenating `text` events in order). Once `inner` is exhausted,
    persists the athlete's message and -- only on a clean `done` with real text, never on a
    `refusal`/`error`/empty turn -- the AI's reply, replacing the old ephemeral, client-only
    workout-chat history (IDEA 016).

    `user_first` saves the athlete's message BEFORE the model call instead of after it: the
    conversation thread is polled by the human coach, who should see the athlete's message
    right away (and in order) rather than only once the AI's reply has finished streaming."""
    reply_text_parts: list[str] = []
    ended_cleanly = False
    if user_first:
        append("athlete", message)
    for line in inner:
        event = _parse_sse(line)
        if event is not None:
            if event.get("type") == "text":
                reply_text_parts.append(event.get("text") or "")
            elif event.get("type") == "done":
                ended_cleanly = True
        yield line
    if not user_first:
        append("athlete", message)
    reply_text = "".join(reply_text_parts).strip()
    if ended_cleanly and reply_text:
        append("ai_coach", reply_text)


@router.post("/api/chat")
async def chat(
    payload: ChatRequest,
    request: Request,
    principal: Principal = Depends(require_auth),
    claude_chat: ClaudeChat = Depends(get_claude_chat),
) -> StreamingResponse:
    # Athlete-session scoping: the session's athlete wins; a mismatched
    # `athlete` in the body is a 403 (the cross-athlete guarantee). A service
    # principal passes through unchanged -- the live PWA (shared token) still
    # sends `athlete` in the body and reaches whichever athlete it names.
    athlete = resolve_athlete(principal, payload.athlete)
    return await stream_chat_response(payload, request, principal, claude_chat, athlete=athlete)


def get_plan_change_notifier(request: Request) -> Callable[..., None]:
    """Returns the real `notify_athlete_of_coach_plan_change` unless overridden via
    `app.dependency_overrides[get_plan_change_notifier] = ...` (same seam convention as
    `routes/coach.py`'s `get_athlete_notifier`/`get_workout_chat_notifier`) -- lets tests spy on
    a coach-confirmed plan change firing the athlete notification without a real Resend call."""
    return notify_athlete_of_coach_plan_change


async def stream_chat_response(
    payload: ChatRequest,
    request: Request,
    principal: Principal,
    claude_chat: ClaudeChat,
    *,
    athlete: str,
    confirmer_role: Literal["athlete", "coach"] = "athlete",
    confirmer_id: str | None = None,
    asker_note: str | None = None,
    plan_change_notifier: Callable[..., None] | None = None,
    conversation_coach_id: uuid.UUID | None = None,
) -> StreamingResponse:
    """The real body of `POST /api/chat` -- factored out (coach-ai-planning build) so `POST
    /api/coach/athletes/{slug}/chat` (`routes/coach.py`) can reuse the EXACT same streaming
    contract (SSE event shapes, light-mode escalation, workout-chat-thread persistence, muted-
    thread short-circuit) rather than duplicating it, with only the caller-resolved `athlete`
    slug and the confirmer/persona context differing.

    `athlete` is resolved by the CALLER (`resolve_athlete` for the athlete-session route above,
    `resolve_coach_athlete` for the coach-mode route) -- this function trusts it as-is; it never
    re-derives athlete scoping from `payload.athlete` itself, so a caller cannot accidentally
    reintroduce the cross-athlete bug this split is designed to keep impossible.

    `confirmer_role`/`confirmer_id` (default: the unchanged athlete-session behavior, `role=
    "athlete"`, no id) flow straight through to `app.tools.build_tool_handlers` -- see that
    function's own docstring for why these are resolved from the authenticated `Principal` here,
    never from anything the model itself could set. `asker_note`, when given, is one persona
    line folded into the per-request context block (`app.context.build_context_block`'s own
    `asker_note` parameter) -- e.g. the coach-mode route's "the asker is this athlete's human
    coach" sentence. `plan_change_notifier` (the raw, unbound `app.notify.
    notify_athlete_of_coach_plan_change`-shaped callable -- `None` for the athlete-session
    route, which never needs it) is bound to THIS request's store/settings/athlete slug via
    `functools.partial` only when `confirmer_role == "coach"` -- see `build_full_request` below.

    `conversation_coach_id` (IDEA 016 Part 2), when given, scopes the turn to the athlete<->
    coach conversation thread with that coach instead of an ad-hoc client-supplied history: the
    persisted thread (human coach's comments included) is the history, the athlete's message is
    saved up front and the AI's reply after. Only `routes/conversation.py` passes it, AFTER
    checking an active grant and the thread's mute state -- never derived from the request body.
    """
    settings = request.app.state.settings
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

    # Fetched once here so build_system's sport-scope filtering (IDEA 008 --
    # never surface cycling content to a swim-only athlete, or vice versa)
    # can see this athlete's own sport scope. Passes `effective_sports`, NOT
    # the raw `.sports` field -- an athlete with no `sports` key set (every
    # real athlete today) resolves to swim-only, never to "every sport" (PR
    # #167 review, Finding 1) -- see Athlete.effective_sports and
    # app.context.filter_files_by_sport_scope.
    # Workout chat thread (IDEA 016): a muted thread skips the model call entirely -- cheaper
    # AND deterministic (no dependence on the model itself declining to answer, per Andrew's
    # own "not hope-the-LLM-complies" steer). Checked here, before anything else gets built.
    if focused_workout is not None and focused_workout.chat_ai_muted:
        workout_append: ThreadAppend = functools.partial(
            _append_workout_chat_message, store, athlete, focused_workout.id
        )

        def event_stream():
            yield from _muted_thread_stream(workout_append, payload.message)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    athlete_profile = store.load_athlete(athlete)
    # Once a workout is focused (and, per the check above, not muted), the athlete's browser-
    # supplied `payload.history` is no longer the source of truth -- the persisted thread is
    # (see _history_from_workout_chat's own docstring for why: it's the only way a human
    # coach's comment, which this browser tab never fetched, reaches the AI's context).
    effective_message = payload.message
    thread_messages: list[Any] | None = None
    if focused_workout is not None:
        thread_messages = focused_workout.chat_messages
    elif conversation_coach_id is not None:
        thread_messages = store.list_conversation_messages(athlete, conversation_coach_id)
    if thread_messages is not None:
        history, pending_coach_text = _history_from_workout_chat(thread_messages)
        if pending_coach_text:
            effective_message = f"{pending_coach_text}\n\n{payload.message}"
    else:
        history = [{"role": h.role, "content": h.content} for h in payload.history]
    light = settings.light_mode and is_light_turn(
        effective_message,
        history_len=len(history),
        focused=focused_workout is not None,
        expert_mode=payload.expert_mode,
    )

    # One request_id per HTTP request (IDEA 025 step 1) -- joins this
    # request's "library route" log line to every "claude turn complete"
    # (and any "route miss") line the same turn emits, so cost can be joined
    # to routing without cross-referencing timestamps.
    request_id = str(uuid.uuid4())

    def build_full_request():
        """The full-mode (system, messages, tools, handlers). A function so a
        light turn only pays for it (DB reads, engine math) if it escalates."""
        in_message = settings.routed_library_in_message
        # System block C (context-trim build, Phase 2): the athlete's own per-request context,
        # cached separately from block B (the routed topic files) so a topic/routing change on
        # this turn never evicts it -- see app.context.build_context_block's own docstring.
        context_block = build_context_block(
            store,
            athlete,
            expert_mode=payload.expert_mode,
            focused_workout=focused_workout,
            cache_ttl=settings.prompt_cache_ttl_context,
            asker_note=asker_note or (CONVERSATION_ASKER_NOTE if conversation_coach_id else None),
        )
        system = build_system(
            settings.library_dir,
            effective_message,
            athlete_sports=athlete_profile.effective_sports,
            include_routed=not in_message,
            cache_ttl=settings.prompt_cache_ttl,
            context_block=context_block,
        )
        library_text = (
            build_routed_library_text(
                settings.library_dir, effective_message, athlete_sports=athlete_profile.effective_sports
            )
            if in_message
            else None
        )
        # IDEA 025 step 1: computed regardless of `in_message` (whether the
        # routed text rides the message or block B) -- one log line either
        # way, and `flag_for_coach_review`'s own "route miss" (kind="topic")
        # needs `routed_files` too.
        routing_info = route_info_for_logging(
            settings.library_dir, effective_message, athlete_sports=athlete_profile.effective_sports
        )
        log.info("library route", request_id=request_id, **routing_info)
        messages = build_messages(
            message=effective_message,
            history=history,
            library_text=library_text,
        )
        bound_plan_change_notifier = (
            functools.partial(plan_change_notifier, store, settings, athlete)
            if confirmer_role == "coach" and plan_change_notifier is not None
            else None
        )
        tool_handlers = build_tool_handlers(
            store,
            slug=athlete,
            expert_mode=payload.expert_mode,
            library_dir=settings.library_dir,
            request_id=request_id,
            routed_files=routing_info["routed_files"],
            confirmer_role=confirmer_role,
            confirmer_id=confirmer_id,
            plan_change_notifier=bound_plan_change_notifier,
        )
        return system, messages, TOOLS_SCHEMA, tool_handlers

    if light:
        light_request = (
            build_light_system(),
            build_light_messages(store, athlete, message=effective_message, history=history),
            LIGHT_TOOLS,
            {},
        )

        def event_stream():
            yield from claude_chat.run_streaming(
                *light_request, escalate=build_full_request, request_id=request_id
            )

    else:
        full_request = build_full_request()

        def event_stream():
            yield from claude_chat.run_streaming(*full_request, request_id=request_id)

    # Workout chat thread (IDEA 016): the athlete's message and the AI's reply get persisted
    # onto Workout.chat_messages -- replacing the old ephemeral, client-only history -- so a
    # human coach (or the athlete, back on another device) reads back the real conversation,
    # not just whatever this one browser tab happened to still have in memory. Only wraps the
    # stream when this turn is actually scoped to a workout; the general (non-workout) Coach
    # tab is untouched.
    if focused_workout is not None:
        workout_id = focused_workout.id
        append_to_workout: ThreadAppend = functools.partial(
            _append_workout_chat_message, store, athlete, workout_id
        )

        def persisted_event_stream():
            yield from _persisting_thread_stream(append_to_workout, payload.message, event_stream())

        return StreamingResponse(persisted_event_stream(), media_type="text/event-stream")

    if conversation_coach_id is not None:
        append_to_conversation: ThreadAppend = functools.partial(
            _append_conversation_message, store, athlete, conversation_coach_id
        )

        def persisted_conversation_stream():
            yield from _persisting_thread_stream(
                append_to_conversation, payload.message, event_stream(), user_first=True
            )

        return StreamingResponse(persisted_conversation_stream(), media_type="text/event-stream")

    return StreamingResponse(event_stream(), media_type="text/event-stream")
