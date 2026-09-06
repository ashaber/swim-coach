"""POST/GET /api/health-status -- the athlete's OWN self-service health-
status logging (web/coach-health-nav-and-athlete-self-log).

Gated via `resolve_athlete` (`app.auth`), the same athlete-self-scoped
pattern `routes/wellness.py` and `routes/workouts.py` use for their own
POST/GET pairs -- a wholly separate access mode from the coach-scoped
routes in `routes/coach.py`, which use `resolve_coach_athlete` instead. This
is a distinct resource-oriented file (mirroring `wellness.py`/`workouts.py`,
not folded into either) since `HealthStatus` is its own durable model, not a
daily wellness check-in or a completed workout.

Before this route existed, the ONLY ways to create a `HealthStatus` row were
a coach typing directly into the roster's form (`coach.py`'s
`coach_create_health_status`) or the AI chat tool (`tools.py`'s
`record_health_status`) -- there was no direct athlete-facing UI path at
all. This route closes that gap: same fields, same validation as the coach
route (read that file's `coach_create_health_status` first if you're
touching this), but `reported_by` is always `"athlete"` here (never
`"coach"`) -- she's reporting about herself directly, matching
`HealthStatus.reported_by`'s own documented "athlete in her own chat"
semantic, just through her own UI form instead of chat.

Also creates a linked `needs_human_review=True` Feedback row, same as the
AI tool path (`tools.py`'s `_handle_record_health_status`) -- reusing
`app.health_status_helpers.link_health_status_feedback` so both paths share
the exact same "a human will actually see this" guarantee rather than
drifting independently. The coach's OWN direct-entry route
(`coach_create_health_status`) deliberately does NOT create this link --
see that function's docstring for why (a human coach typing it in directly
already IS the human seeing it).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from swim_coach.models import HealthStatus

from app.auth import Principal, require_auth, resolve_athlete
from app.health_status_helpers import link_health_status_feedback
from app.store_factory import make_store

router = APIRouter()

# Same closed enums as routes/coach.py's coach_create_health_status --
# duplicated rather than imported, matching this codebase's existing
# convention of each route/tool module owning its own inline copy of these
# validation sets (see tools.py's _handle_record_health_status for a third
# independent copy).
_VALID_RESTRICTIONS = {"none", "light_only", "no_training"}
_VALID_HEALTH_SOURCES = {"self_reported", "practitioner"}
_VALID_BODY_REGIONS = {
    "shoulder", "knee", "back", "hip", "ankle_foot", "elbow_wrist",
    "illness_systemic", "head_neck", "other",
}
_VALID_ONSETS = {"acute", "gradual"}
_VALID_SEVERITIES = {"slight", "minimal", "mild", "moderate", "serious", "long_term"}


@router.post("/api/health-status")
async def create_health_status(
    payload: dict[str, Any],
    request: Request,
    athlete: str | None = Query(None),
    principal: Principal = Depends(require_auth),
) -> dict:
    """The athlete logging her own health status directly, no AI chat or
    coach required. Same validation shape as `coach.py`'s
    `coach_create_health_status`; see that function for the field-by-field
    rationale. `reported_by` is always `"athlete"` -- unlike the coach
    route, there's no `expert_mode`-style signal to derive it from, because
    this route can only ever be reached by the athlete herself: the
    optional `?athlete=` query param (same convention as `workouts.py`/
    `wellness.py`) is only ever a no-op or a 403 for a real athlete session
    (`resolve_athlete` never resolves to anyone else's slug -- see
    `test_auth_identity.py`'s cross-athlete regression guarantee)."""
    settings = request.app.state.settings
    slug = resolve_athlete(principal, athlete)
    store = make_store(settings)

    description = payload.get("description")
    if not isinstance(description, str) or not description:
        raise HTTPException(status_code=422, detail="description must be a non-empty string")

    restriction = payload.get("restriction")
    if restriction not in _VALID_RESTRICTIONS:
        raise HTTPException(
            status_code=422,
            detail=f"restriction must be one of {sorted(_VALID_RESTRICTIONS)}",
        )

    source = payload.get("source")
    if source not in _VALID_HEALTH_SOURCES:
        raise HTTPException(
            status_code=422,
            detail=f"source must be one of {sorted(_VALID_HEALTH_SOURCES)}",
        )

    expected_review_date = None
    raw_review_date = payload.get("expected_review_date")
    if raw_review_date:
        try:
            expected_review_date = date.fromisoformat(raw_review_date)
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"invalid expected_review_date {raw_review_date!r}"
            ) from exc

    # Second-iteration fields (industry-modeling evolution) -- all optional,
    # same "absent is always valid, invalid is always rejected" discipline
    # as coach.py's own copy of this validation.
    body_region = payload.get("body_region")
    if body_region is not None and body_region not in _VALID_BODY_REGIONS:
        raise HTTPException(
            status_code=422, detail=f"body_region must be one of {sorted(_VALID_BODY_REGIONS)}"
        )

    onset = payload.get("onset")
    if onset is not None and onset not in _VALID_ONSETS:
        raise HTTPException(status_code=422, detail=f"onset must be one of {sorted(_VALID_ONSETS)}")

    severity = payload.get("severity")
    if severity is not None and severity not in _VALID_SEVERITIES:
        raise HTTPException(
            status_code=422, detail=f"severity must be one of {sorted(_VALID_SEVERITIES)}"
        )

    related_status_id = None
    raw_related_status_id = payload.get("related_status_id")
    if raw_related_status_id:
        try:
            related_status_id = UUID(str(raw_related_status_id))
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"invalid related_status_id {raw_related_status_id!r}"
            ) from exc

    # Same "404 on an unresolvable athlete" check wellness.py's
    # create_wellness uses -- coach.py's coach_create_health_status skips
    # this because resolve_coach_athlete already guarantees a real,
    # actively-granted athlete before this point; that guarantee doesn't
    # exist for a self-scoped route.
    try:
        athlete = store.load_athlete(slug)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"no such athlete: {slug}") from exc

    status = HealthStatus(
        id=uuid4(),
        athlete_id=athlete.id,
        reported_at=datetime.now(timezone.utc),
        reported_by="athlete",
        source=source,
        description=description,
        restriction=restriction,
        expected_review_date=expected_review_date,
        body_region=body_region,
        onset=onset,
        severity=severity,
        related_status_id=related_status_id,
    )
    store.save_health_status(slug, status)

    # Same "a human will actually see this" guarantee the AI tool path
    # already gives -- see this module's own docstring and
    # health_status_helpers.link_health_status_feedback's docstring. Never
    # raises: a failure here must not make this endpoint look like it
    # failed (the HealthStatus row above is already durably saved), but the
    # response still tells the caller plainly if the notification half
    # didn't happen.
    feedback_id, notify_error = link_health_status_feedback(
        store, slug=slug, athlete_id=athlete.id, status=status,
    )

    result = status.model_dump(mode="json")
    result["feedback_id"] = feedback_id
    if notify_error is not None:
        result["notify_error"] = (
            "Your health status was recorded, but flagging it for your coach's "
            "attention failed. Consider telling your coach directly as a precaution."
        )
    return result


@router.get("/api/health-status")
async def list_own_health_status(
    request: Request,
    athlete: str | None = Query(None),
    principal: Principal = Depends(require_auth),
) -> list[dict]:
    """The athlete's own health-status history, most-recent-first (see
    `StoreInterface.list_health_status`'s ordering contract) -- everything
    on file, same shape as the coach's GET route, just self-scoped. Same
    "404 on an unresolvable athlete" check `wellness.py`'s `list_wellness`
    uses (coach.py's GET route skips it -- `resolve_coach_athlete` already
    guarantees the slug is a real, actively-granted athlete before this
    point, but that guarantee doesn't exist for a self-scoped route)."""
    settings = request.app.state.settings
    slug = resolve_athlete(principal, athlete)
    store = make_store(settings)
    try:
        store.load_athlete(slug)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"no such athlete: {slug}") from exc

    entries = store.list_health_status(slug)
    return [e.model_dump(mode="json") for e in entries]
