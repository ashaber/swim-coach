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

`POST /api/feedback/questions` (coach-mode Phase 1) is the athlete-initiated
"ask a question about my own training" endpoint: a one-shot, non-streaming
call through `ClaudeChat.run_once` (app/claude.py) -- built for the SAME
context/tools/system assembly `/api/chat` uses (app.context/app.tools), just
without a multi-turn `history` and without SSE -- persisted as a `Feedback`
row (`type="question"`) carrying the model's `ai_provisional_answer` and,
when `direct_to_coach` is set, `needs_human_review=True` so it surfaces in
the coach's queue (routes/coach.py) even before any AI answer is read.

Both athlete-facing creation paths above additionally schedule a best-effort
coach-notification email (app/notify.py) via FastAPI `BackgroundTasks`, AFTER
`store.save_feedback` has already succeeded and the athlete's own response is
on its way -- so a slow/failing email never affects the feedback save or adds
latency to the athlete's request. `type="research_question"` (coach-sourced,
via app/tools.py's `log_open_question` tool) deliberately does NOT get this
wiring -- a routine AI-flagged research gap notified every time would be
noisy; Andrew's actual ask was specifically about missing ATHLETE feedback.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import ValidationError
from swim_coach.models import Feedback
from swim_coach.store import StoreInterface

from app.auth import (
    Principal,
    require_auth,
    require_chat_rate_limit,
    require_daily_chat_cap,
    resolve_athlete,
)
from app.claude import ClaudeChat
from app.config import Settings
from app.context import build_messages, build_system, find_workout_by_id
from app.notify import notify_coaches_of_feedback
from app.routes.chat import get_claude_chat
from app.store_factory import make_store
from app.tools import TOOLS_SCHEMA, build_tool_handlers

router = APIRouter()

# The notification callable's shape, exactly `notify_coaches_of_feedback`'s
# signature minus the keyword-only `client` -- a type alias purely so
# `get_notifier`'s return annotation reads cleanly.
Notifier = Callable[[StoreInterface, Settings, Feedback, str], None]


def get_notifier(request: Request) -> Notifier:
    """FastAPI dependency, same seam as routes/chat.py's `get_claude_chat`:
    routes call the notifier through this indirection so tests can override
    it (`app.dependency_overrides[get_notifier] = lambda: fake_notifier`)
    with a spy/fake instead of exercising a real BackgroundTask that would
    otherwise try to reach the real Resend API. Returns the real
    `notify_coaches_of_feedback` unless overridden -- no per-app caching
    needed (unlike `get_claude_chat`'s cached `ClaudeChat`), since this is
    just a plain function reference, not an object wrapping a client.
    """
    return notify_coaches_of_feedback

# Fields the server assigns itself -- stripped from the client payload before
# constructing the model, same pattern as routes/workouts.py's
# _SERVER_ASSIGNED_FIELDS. `source` is always "athlete" for this endpoint
# (the coach-sourced "research_question" type only ever comes from
# app.tools's log_open_question tool handler); `status` always starts "open".
_SERVER_ASSIGNED_FIELDS = {"id", "athlete_id", "schema_version", "source", "status", "created_at"}

# The only types an athlete may submit through this endpoint --
# "research_question" is coach-only (see module docstring). "question"
# (coach-mode Phase 1) covers both this route's free-form submissions AND
# POST /api/feedback/questions below (which constructs its own Feedback
# directly, bypassing this set, but keeps the type consistent).
_ATHLETE_SUBMITTABLE_TYPES = {"feature_request", "comment", "bug", "question"}


@router.post("/api/feedback")
async def create_feedback(
    payload: dict[str, Any],
    request: Request,
    background_tasks: BackgroundTasks,
    athlete: str | None = Query(None),
    principal: Principal = Depends(require_auth),
    notifier: Notifier = Depends(get_notifier),
) -> dict:
    settings = request.app.state.settings
    athlete = resolve_athlete(principal, athlete)
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
    # Scheduled AFTER the save succeeds, and runs only after this handler's
    # own response has been sent (FastAPI BackgroundTasks semantics) -- the
    # athlete's request never waits on Resend. See app/notify.py.
    background_tasks.add_task(notifier, store, settings, feedback, athlete)
    return feedback.model_dump(mode="json")


@router.get("/api/feedback")
async def list_feedback(
    request: Request,
    athlete: str | None = Query(None),
    principal: Principal = Depends(require_auth),
) -> list[dict]:
    settings = request.app.state.settings
    athlete = resolve_athlete(principal, athlete)
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
    principal: Principal = Depends(require_auth),
) -> dict:
    settings = request.app.state.settings
    store = make_store(settings)

    status = payload.get("status")
    context = payload.get("context")
    needs_human_review = payload.get("needs_human_review")
    if status is not None and not isinstance(status, str):
        raise HTTPException(status_code=422, detail="status must be a string")
    if context is not None and not isinstance(context, dict):
        raise HTTPException(status_code=422, detail="context must be an object")
    if needs_human_review is not None and not isinstance(needs_human_review, bool):
        raise HTTPException(status_code=422, detail="needs_human_review must be a boolean")

    # This route addresses a feedback entry by id, with no `athlete` param to
    # scope -- so unlike its siblings it can't lean on `resolve_athlete`. An
    # athlete-session principal may therefore only patch entries tied to its
    # OWN athlete_id; anything else is a 403 (the same cross-athlete
    # guarantee the ?athlete= routes get). A SERVICE principal is unrestricted
    # here, exactly as before this PR -- the coach's research-question loop and
    # Andrew's CLI both patch entries across athletes. An ONBOARDING
    # principal has no athlete_id of its own to compare against, so it is
    # ALWAYS 403 here -- same "no athlete to act as" guarantee
    # `resolve_athlete` enforces on every other route.
    if principal.kind == "onboarding":
        raise HTTPException(status_code=403, detail="onboarding session has no athlete")
    if principal.kind == "athlete" and principal.athlete is not None:
        existing = store.get_feedback(feedback_id)
        if existing is None:
            raise HTTPException(status_code=404, detail=f"no such feedback entry: {feedback_id}")
        own_id = store.load_athlete(principal.athlete).id
        if existing.athlete_id != own_id:
            raise HTTPException(status_code=403, detail="athlete mismatch")

    updated = store.update_feedback(
        feedback_id, status=status, context=context, needs_human_review=needs_human_review
    )
    if updated is None:
        raise HTTPException(status_code=404, detail=f"no such feedback entry: {feedback_id}")

    return updated.model_dump(mode="json")


@router.post("/api/feedback/questions")
async def ask_question(
    payload: dict[str, Any],
    request: Request,
    background_tasks: BackgroundTasks,
    athlete: str | None = Query(None),
    principal: Principal = Depends(require_auth),
    claude_chat: ClaudeChat = Depends(get_claude_chat),
    notifier: Notifier = Depends(get_notifier),
) -> dict:
    settings = request.app.state.settings
    athlete = resolve_athlete(principal, athlete)
    require_chat_rate_limit(request, principal.token)
    require_daily_chat_cap(request, principal)

    store = make_store(settings)
    try:
        profile = store.load_athlete(athlete)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"no such athlete: {athlete}") from exc

    body = payload.get("body")
    if not isinstance(body, str) or not body:
        raise HTTPException(status_code=422, detail="body must be a non-empty string")
    workout_id = payload.get("workout_id")
    if workout_id is not None and not isinstance(workout_id, str):
        raise HTTPException(status_code=422, detail="workout_id must be a string")
    direct_to_coach = payload.get("direct_to_coach", False)
    if not isinstance(direct_to_coach, bool):
        raise HTTPException(status_code=422, detail="direct_to_coach must be a boolean")

    # Resolve the scoped workout exactly like /api/chat does -- an unknown
    # workout_id is an ordinary 404 before any model call starts.
    focused_workout = None
    if workout_id is not None:
        focused_workout = find_workout_by_id(store.list_workouts(athlete), workout_id)
        if focused_workout is None:
            raise HTTPException(status_code=404, detail=f"no workout matching id {workout_id!r}")

    system = build_system(settings.library_dir, body)
    messages = build_messages(
        store,
        athlete,
        message=body,
        history=[],
        expert_mode=False,
        focused_workout=focused_workout,
    )
    tool_handlers = build_tool_handlers(store, slug=athlete, expert_mode=False)

    try:
        provisional = claude_chat.run_once(system, messages, TOOLS_SCHEMA, tool_handlers)
    except RuntimeError as exc:
        # A real upstream failure (refusal/error/max-iterations from the
        # model call itself), not a client error -- 502, with a friendly
        # detail, rather than letting it 500 the whole request.
        raise HTTPException(
            status_code=502, detail=f"the coach couldn't answer that just now: {exc}"
        ) from exc

    feedback = Feedback(
        id=uuid4(),
        athlete_id=profile.id,
        schema_version=1,
        type="question",
        source="athlete",
        body=body,
        status="open",
        created_at=datetime.now(timezone.utc),
        workout_id=UUID(str(focused_workout.id)) if focused_workout is not None else None,
        needs_human_review=direct_to_coach,
        ai_provisional_answer=provisional,
    )
    store.save_feedback(feedback)
    background_tasks.add_task(notifier, store, settings, feedback, athlete)
    return feedback.model_dump(mode="json")
