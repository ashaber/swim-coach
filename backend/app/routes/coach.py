"""GET /api/coach/athletes, GET .../workouts, GET .../feedback, PATCH
.../feedback/{id} -- the coach-side view (coach-mode Phase 1).

Gated via `resolve_coach_athlete` (backend/app/auth.py, merged on main) --
a wholly separate access mode from the athlete-self-scoped routes
(`resolve_athlete`, `routes/grants.py`). `resolve_coach_athlete` checks
`principal.coach_for` (the athlete slugs this session holds an ACTIVE
`CoachGrant` for) rather than "is this my own data."
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from swim_coach.quality import match_workout_to_session, workout_quality
from swim_coach.models import Session

from app.auth import Principal, require_auth, resolve_coach_athlete
from app.store_factory import make_store

router = APIRouter()


@router.get("/api/coach/athletes")
async def list_coached_athletes(
    request: Request, principal: Principal = Depends(require_auth)
) -> list[dict]:
    settings = request.app.state.settings
    store = make_store(settings)

    # No `athlete` param here at all -- derived entirely from
    # `principal.coach_for`. `coach_for` is only ever populated for
    # kind=="athlete" (see Principal.coach_for's docstring): a `service`
    # principal always has an EMPTY coach_for, since it already has
    # unrestricted cross-athlete access and no single coach identity of its
    # own to look grants up by. GET /api/me 403s a service principal
    # because that route is asking "who am I" of a credential with no single
    # identity -- but a 403 here would be needlessly harsh for a route with
    # no request param to get wrong: this route is just "list the athletes
    # I coach," and for a service credential the honest, harmless answer is
    # an empty list, not an error.
    slugs = sorted(principal.coach_for)
    result = []
    for slug in slugs:
        athlete = store.load_athlete(slug)
        result.append({"slug": athlete.slug, "name": athlete.name})
    return result


@router.get("/api/coach/athletes/{slug}/workouts")
async def coach_view_workouts(
    slug: str, request: Request, principal: Principal = Depends(require_auth)
) -> list[dict]:
    settings = request.app.state.settings
    slug = resolve_coach_athlete(principal, slug)
    store = make_store(settings)

    workouts = store.list_workouts(slug)

    sessions: list[Session] = []
    for iso_week in store.list_week_ids(slug):
        week = store.load_week(slug, iso_week)
        if week is not None:
            sessions.extend(week.sessions)

    result = []
    for workout in workouts:
        session = match_workout_to_session(workout, sessions)
        quality = workout_quality(workout, session)
        result.append({**workout.model_dump(mode="json"), "quality": quality.model_dump(mode="json")})

    # `list_workouts` returns filename order (which happens to sort
    # date-ascending today, since filenames are "{date}-{sport}-{id8}.yaml")
    # -- re-sort explicitly by date descending (most-recent-first) rather
    # than relying on that filename-ordering coincidence.
    result.sort(key=lambda w: w["date"], reverse=True)
    return result


@router.get("/api/coach/athletes/{slug}/feedback")
async def coach_view_feedback(
    slug: str, request: Request, principal: Principal = Depends(require_auth)
) -> list[dict]:
    settings = request.app.state.settings
    slug = resolve_coach_athlete(principal, slug)
    store = make_store(settings)

    # Full visibility -- no chat_visibility filtering in Phase 1 (this is
    # the durable Feedback/Q&A log, not live chat).
    entries = store.list_feedback(athlete=slug)
    return [e.model_dump(mode="json") for e in entries]


@router.patch("/api/coach/athletes/{slug}/feedback/{feedback_id}")
async def coach_reply_to_feedback(
    slug: str,
    feedback_id: UUID,
    payload: dict[str, Any],
    request: Request,
    principal: Principal = Depends(require_auth),
) -> dict:
    settings = request.app.state.settings
    slug = resolve_coach_athlete(principal, slug)
    store = make_store(settings)

    coach_reply = payload.get("coach_reply")
    if not isinstance(coach_reply, str) or not coach_reply:
        raise HTTPException(status_code=422, detail="coach_reply must be a non-empty string")

    existing = store.get_feedback(feedback_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"no such feedback entry: {feedback_id}")

    athlete_row = store.load_athlete(slug)
    # Defense in depth: resolve_coach_athlete already confirmed the coach
    # can act on `slug`, but this confirms the specific feedback row
    # actually belongs to THAT athlete, not some other one the id might
    # collide with. 404, not 403 -- don't leak the existence of another
    # athlete's feedback id to a coach who isn't authorized for it beyond
    # what resolve_coach_athlete already gated.
    if existing.athlete_id != athlete_row.id:
        raise HTTPException(status_code=404, detail=f"no such feedback entry: {feedback_id}")

    # "Reply as coach" fundamentally needs one coach identity -- a coach
    # here is always an athlete-kind principal (coaches in this system are
    # themselves athlete accounts, per CoachGrant's docstring). A service
    # credential has unrestricted cross-athlete access everywhere ELSE, but
    # there's no sensible single "which coach is this" identity to stamp
    # onto coach_athlete_id for it, so this specific write action requires
    # kind=="athlete" and 403s a service principal with a clear message.
    if principal.kind != "athlete" or principal.athlete is None:
        raise HTTPException(
            status_code=403,
            detail="replying as coach requires a single coach identity; a service credential has none",
        )
    coach_athlete_id = store.load_athlete(principal.athlete).id

    updated = store.update_feedback(
        feedback_id,
        coach_reply=coach_reply,
        coach_reply_at=datetime.now(timezone.utc),
        coach_athlete_id=coach_athlete_id,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail=f"no such feedback entry: {feedback_id}")

    return updated.model_dump(mode="json")
