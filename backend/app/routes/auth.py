"""POST /api/auth/google + GET /api/me -- verified server-side identity
(Slice 1 of the auth plan; also Slice 1 of self-service onboarding, docs/
design-self-service-onboarding.md, PR #63).

`POST /api/auth/google` is the front door: it verifies a raw Google ID
token's signature/audience/issuer/expiry (never trusting an unverified
client-side decode -- see web/src/identity.js's own docstring, "IDENTITY FOR
UX, NOT A SECURITY BOUNDARY", which this endpoint exists to fix), looks the
verified email up in the `allowed_emails` store, and on success mints an
opaque session token. On a non-allowlisted email it returns 403 `{"error":
"request access"}` -- deliberately no session and no athlete row is ever
created for an unrecognized email.

TWO outcomes on success, distinguished by whether the allowlist entry has an
athlete yet:
  - athlete-bound entry -> ordinary athlete session, `{token, athlete, name,
    role, expires_at}` (unchanged from before self-service onboarding).
  - PENDING entry (`allowed.athlete_slug is None` -- invited before any
    athlete exists for it) -> an ONBOARDING session, `{token, athlete: null,
    onboarding: true, role: "onboarding", expires_at}`. This session can
    reach GET /api/me (below) and, in a later slice, the endpoint that
    provisions the athlete -- `require_auth`/`resolve_athlete`
    (backend/app/auth.py) 403 it on every existing athlete-scoped route.

`GET /api/me` is what a later frontend PR calls to resolve "who am I" from a
bearer token. An onboarding principal gets a 200 (`{onboarding: true,
athlete: null, ...}`) -- the one read an onboarding session IS allowed, so a
future frontend can detect onboarding mode -- a service credential still
gets 403 (no single identity to report).

This module is purely ADDITIVE: nothing here is on the request path of any
existing route, and no existing behavior changes for an already-provisioned
athlete.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.auth import Principal, hash_token, require_auth
from app.google_auth import GoogleVerifier, get_google_verifier
from app.logging_config import get_logger
from app.store_factory import make_store

router = APIRouter()
log = get_logger("app.routes.auth")

# Every athlete minted through this endpoint is role "athlete" today -- the
# allowed_emails table (supabase/migrations/20260714000000_identity.sql) has
# no role column yet; all three seeded beta users are role "athlete". A
# "coach" role (with cross-athlete access) is a deliberate later addition.
_DEFAULT_ROLE = "athlete"


class GoogleSignInRequest(BaseModel):
    id_token: str


@router.post("/api/auth/google")
async def google_sign_in(
    payload: GoogleSignInRequest,
    request: Request,
    verify: GoogleVerifier = Depends(get_google_verifier),
) -> dict:
    settings = request.app.state.settings
    store = make_store(settings)

    try:
        claims = verify(payload.id_token)
    except ValueError as exc:
        # google-auth raises ValueError for every verification failure --
        # bad signature, wrong audience, wrong issuer, expired. Never the
        # raw token or the exception's full text (it can echo the token) --
        # just that a rejection happened.
        log.warn("auth.google_token_rejected")
        raise HTTPException(status_code=401, detail="invalid Google ID token") from exc

    email = str(claims.get("email") or "").strip().lower()
    if not email:
        log.warn("auth.google_token_missing_email")
        raise HTTPException(status_code=401, detail="invalid Google ID token")

    allowed = store.get_allowed_email(email)
    if allowed is None:
        # Never log the raw email (PII) -- a hash is enough to correlate
        # repeated "please invite me" attempts without exposing who asked.
        log.info("auth.request_access", email_hash=hash_token(email))
        raise HTTPException(status_code=403, detail="request access")

    raw_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.session_ttl_days)

    if allowed.athlete_slug is None:
        # PENDING invite (Slice 1 of self-service onboarding) -- allowlisted
        # before any athlete exists for it. Mint an onboarding-scoped
        # session (athlete=None) rather than loading an athlete that doesn't
        # exist yet. See app/auth.py's Principal(kind="onboarding", ...).
        store.create_session(hash_token(raw_token), athlete=None, expires_at=expires_at)
        log.info("auth.onboarding_session_minted", email_hash=hash_token(email))
        return {
            "token": raw_token,
            "athlete": None,
            "onboarding": True,
            "role": "onboarding",
            "expires_at": expires_at.isoformat(),
        }

    athlete = store.load_athlete(allowed.athlete_slug)
    store.create_session(
        hash_token(raw_token), athlete=allowed.athlete_slug, expires_at=expires_at
    )

    log.info("auth.session_minted", athlete=allowed.athlete_slug)

    return {
        "token": raw_token,
        "athlete": athlete.slug,
        "name": athlete.name,
        "role": _DEFAULT_ROLE,
        "expires_at": expires_at.isoformat(),
    }


@router.get("/api/me")
async def get_me(request: Request, principal: Principal = Depends(require_auth)) -> dict:
    if principal.kind == "onboarding":
        # The one read an onboarding session IS allowed -- so a future
        # frontend can detect "signed in, not yet provisioned" and route to
        # the onboarding form instead of 403ing.
        return {
            "onboarding": True,
            "athlete": None,
            "role": "onboarding",
            "expires_at": principal.expires_at.isoformat() if principal.expires_at else None,
        }
    if principal.kind != "athlete" or principal.athlete is None:
        # A service credential (the legacy shared API_TOKEN) isn't bound to
        # one athlete -- there's no single identity to report.
        raise HTTPException(status_code=403, detail="no athlete identity for this credential")

    settings = request.app.state.settings
    store = make_store(settings)
    athlete = store.load_athlete(principal.athlete)

    return {
        "athlete": athlete.slug,
        "name": athlete.name,
        "role": _DEFAULT_ROLE,
        "expires_at": principal.expires_at.isoformat() if principal.expires_at else None,
    }


@router.post("/api/auth/logout")
async def logout(request: Request, principal: Principal = Depends(require_auth)) -> dict:
    """Revokes the calling session so its token 401s on every subsequent
    request -- there is no refresh endpoint by design (see web/src/
    identity.js), so the frontend's only way back in after a sign-out is a
    fresh Google sign-in. Still returns 200 for a service-token principal:
    hashing it and revoking finds no matching session row (a service token
    was never minted as a session), so it's a harmless no-op rather than an
    error -- logout is only ever meaningful for athlete sessions, and
    callers never need a separate code path to know which kind of token
    they're holding.
    """
    settings = request.app.state.settings
    store = make_store(settings)
    store.revoke_session(hash_token(principal.token))
    log.info("auth.logout", kind=principal.kind, athlete=principal.athlete)
    return {"ok": True}
