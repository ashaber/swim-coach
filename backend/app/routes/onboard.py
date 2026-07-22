"""POST /api/onboard -- Slice 2 of self-service in-app onboarding (design
docs/design-self-service-onboarding.md, PR #63; stacks on Slice 1, PR #67).

Lets an ONBOARDING-scoped session (see `app/auth.py`'s `Principal(kind=
"onboarding", ...)`, minted by `POST /api/auth/google` for a PENDING
allowlist entry -- an email invited before any athlete exists for it)
provision its OWN athlete and upgrade to an athlete-bound session, in one
call. This is the one route an onboarding principal is allowed to reach
besides `GET /api/me` -- see `app/auth.py`'s `resolve_athlete` docstring,
which 403s an onboarding principal on every athlete-SCOPED route; this route
is deliberately unscoped (it creates the athlete an onboarding session will
be scoped to, so `resolve_athlete` doesn't apply here at all).

Persistence is entirely delegated to `swim_coach.provision.provision_athlete`
-- the same function `swim_coach.cli`'s `onboard` subcommand calls -- so a
CLI-provisioned athlete and a self-service one go through identical
engine math (zone_table/scaffold_macro/generate_week) and write order.
This route's own job is narrower: turn the HTTP body into the `Athlete`/
`Event` models `provision_athlete` expects (reusing `zones.css_from_test`/
`cli.parse_time_to_s` for a CSS-test-derived pace, exactly like `cli.
_cmd_onboard` does), resolve which invited email is provisioning (from the
SESSION, never the request body -- see `Principal.pending_email`'s
docstring), and perform the session upgrade below.

Session upgrade: on success, a NEW athlete-bound session is minted
(`create_session(slug, ...)`) and the CALLER's onboarding session is
revoked (`revoke_session`) -- the response shape exactly matches
`POST /api/auth/google`'s athlete-bound success shape (`{token, athlete,
name, role, expires_at}`) so the frontend can swap tokens the same way
either path produces one.
"""

from __future__ import annotations

import re
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError, model_validator
from swim_coach.cli import parse_time_to_s
from swim_coach.models import Athlete, Event
from swim_coach.provision import provision_athlete
from swim_coach.zones import css_from_test

from app.auth import Principal, hash_token, require_auth
from app.logging_config import get_logger
from app.store_factory import make_store

router = APIRouter()
log = get_logger("app.routes.onboard")

# Mirrors routes/auth.py's own `_DEFAULT_ROLE` -- every athlete minted
# through EITHER path (POST /api/auth/google's athlete-bound branch, or this
# route's session upgrade) is role "athlete" today. Kept as a separate
# constant (not imported from routes/auth.py) because that name is a private
# module constant there, not a shared one -- see that file's own comment on
# why "coach" is a deliberate later addition.
_DEFAULT_ROLE = "athlete"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    """Deterministic slug from an athlete's display name: lowercase,
    non-alphanumeric runs collapsed to single hyphens, leading/trailing
    hyphens stripped. Falls back to "athlete" if nothing alphanumeric
    survives (e.g. a name that's entirely emoji/punctuation) rather than
    producing an empty slug."""
    slug = _SLUG_RE.sub("-", name.strip().lower()).strip("-")
    return slug or "athlete"


class OnboardEventIn(BaseModel):
    """One target event from the onboarding form. Server-owned fields
    (`id`, `athlete_id`, `schema_version`) are never accepted here -- minted
    fresh once the athlete's own id is known, same as `cli._cmd_onboard`
    does for events parsed from a local events.yaml."""

    name: str
    event_date: str  # ISO date string; parsed into swim_coach.models.Event below
    distance_m: int = Field(gt=0)
    water_temp_c: float | None = None
    wetsuit: bool = False
    priority: str = "A"
    event_format: Literal["single_day", "multi_day_stage"] = "single_day"


class OnboardRequest(BaseModel):
    """The onboarding form's hard-data fields. Validated at the boundary
    (pydantic) before anything touches the store -- a malformed body never
    reaches `provision_athlete`."""

    name: str
    slug: str | None = None
    css_pace_s_per_100m: float | None = None
    test_400: str | None = None
    test_200: str | None = None
    sex: Literal["male", "female", "other"] | None = None
    height_cm: float | None = Field(default=None, gt=0)
    weight_kg: float | None = Field(default=None, gt=0)
    dob: str | None = None  # ISO date string
    pool_schedule: list[str | dict] = Field(default_factory=list)
    events: list[OnboardEventIn] = Field(default_factory=list)
    # Name of the event within `events` to scaffold the macro against --
    # only required when `events` has more than one entry (mirrors
    # `cli._cmd_onboard`'s `--event`; matched case-insensitively, exact).
    target_event: str | None = None
    current_volume_m: int | None = None
    peak_volume_m: int | None = None
    macro_start: str | None = None  # ISO date string

    @model_validator(mode="after")
    def _css_pace_or_test_times(self) -> "OnboardRequest":
        if self.css_pace_s_per_100m is not None:
            return self
        if self.test_400 and self.test_200:
            return self
        raise ValueError(
            "css_pace_s_per_100m, or both test_400 and test_200 (MM:SS), is required"
        )


@router.post("/api/onboard")
async def onboard(
    payload: OnboardRequest,
    request: Request,
    principal: Principal = Depends(require_auth),
) -> dict:
    if principal.kind != "onboarding":
        # An already-provisioned athlete (or the service credential) has
        # nothing to onboard -- see module docstring, this is the one route
        # ONLY an onboarding principal may reach.
        raise HTTPException(
            status_code=403, detail="only an onboarding session can self-provision an athlete"
        )
    # Invariant from app/auth.py's require_auth: every onboarding principal
    # carries the verified email its session was minted for.
    assert principal.pending_email is not None

    settings = request.app.state.settings
    store = make_store(settings)

    invite = store.get_allowed_email(principal.pending_email)
    if invite is None:
        # The invite backing this session was revoked mid-flow (e.g. an
        # admin ran `revoke-invite` after the sign-in that minted this
        # session). Never silently provision an athlete for a revoked
        # invite.
        log.warn("onboard.invite_revoked", email_hash=hash_token(principal.pending_email))
        raise HTTPException(status_code=403, detail="invite no longer valid")
    if invite.athlete_slug is not None:
        # Another session for the SAME email already completed onboarding
        # (e.g. two tabs) -- this token is still live but its invite is no
        # longer pending. Must not re-provision or silently reuse the other
        # athlete.
        log.warn("onboard.invite_already_claimed", email_hash=hash_token(principal.pending_email))
        raise HTTPException(status_code=409, detail="this invite has already been completed")

    slug = payload.slug.strip() if payload.slug else _slugify(payload.name)
    try:
        store.load_athlete(slug)
    except FileNotFoundError:
        pass  # slug is free -- expected path
    else:
        raise HTTPException(status_code=409, detail=f"athlete slug '{slug}' already exists")

    # CSS pace: direct, or derived from a 400m/200m test -- same
    # `zones.css_from_test`/`cli.parse_time_to_s` cli._cmd_onboard uses.
    css_pace = payload.css_pace_s_per_100m
    if css_pace is None:
        # The model_validator above guarantees test_400/test_200 are both
        # set whenever css_pace_s_per_100m is None.
        try:
            t400 = parse_time_to_s(payload.test_400)
            t200 = parse_time_to_s(payload.test_200)
            css_pace = css_from_test(t400, t200)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    athlete_id = uuid4()
    try:
        profile = Athlete(
            id=athlete_id,
            slug=slug,
            name=payload.name,
            css_pace_s_per_100m=css_pace,
            constraints={},
            pool_schedule=payload.pool_schedule,
            dob=payload.dob,
            sex=payload.sex,
            height_cm=payload.height_cm,
            weight_kg=payload.weight_kg,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        events = [
            Event(
                id=uuid4(),
                athlete_id=athlete_id,
                name=e.name,
                event_date=e.event_date,
                distance_m=e.distance_m,
                water_temp_c=e.water_temp_c,
                wetsuit=e.wetsuit,
                priority=e.priority,
                event_format=e.event_format,
            )
            for e in payload.events
        ]
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    target_event: Event | None = None
    if payload.target_event:
        query = payload.target_event.strip().lower()
        target_event = next((e for e in events if e.name.strip().lower() == query), None)
        if target_event is None:
            raise HTTPException(
                status_code=422,
                detail=f"no event named {payload.target_event!r} in events",
            )
    elif len(events) == 1:
        target_event = events[0]
    elif len(events) > 1:
        raise HTTPException(
            status_code=422,
            detail=f"{len(events)} events given; set target_event to pick which one "
            "to scaffold the macro against",
        )

    macro_start = None
    if payload.macro_start:
        try:
            macro_start = date.fromisoformat(payload.macro_start)
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"invalid macro_start {payload.macro_start!r}"
            ) from exc

    try:
        result = provision_athlete(
            store,
            profile=profile,
            events=events,
            email=principal.pending_email,
            note=invite.note,
            target_event=target_event,
            current_volume_m=payload.current_volume_m,
            peak_volume_m=payload.peak_volume_m,
            macro_start=macro_start,
        )
    except ValueError as exc:
        # e.g. insufficient runway before the target event -- a real,
        # actionable input problem (see provision_athlete's own docstring),
        # not a server error.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    log.info(
        "onboard.provisioned",
        athlete=result.athlete.slug,
        macro=result.macro is not None,
        skipped=result.skipped,
    )

    # Session upgrade: mint a fresh athlete-bound session, then revoke the
    # caller's onboarding session -- the old token 401s on every subsequent
    # request (see routes/auth.py's logout, same revoke_session call).
    raw_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.session_ttl_days)
    store.create_session(hash_token(raw_token), athlete=result.athlete.slug, expires_at=expires_at)
    store.revoke_session(hash_token(principal.token))
    log.info("onboard.session_upgraded", athlete=result.athlete.slug)

    return {
        "token": raw_token,
        "athlete": result.athlete.slug,
        "name": result.athlete.name,
        "role": _DEFAULT_ROLE,
        "expires_at": expires_at.isoformat(),
    }
