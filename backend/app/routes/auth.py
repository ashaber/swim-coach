"""POST /api/auth/google + GET /api/me -- verified server-side identity
(Slice 1 of the auth plan).

`POST /api/auth/google` is the new front door: it verifies a raw Google ID
token's signature/audience/issuer/expiry (never trusting an unverified
client-side decode -- see web/src/identity.js's own docstring, "IDENTITY FOR
UX, NOT A SECURITY BOUNDARY", which this endpoint exists to fix), looks the
verified email up in the `allowed_emails` store, and on success mints an
opaque session token bound to that email's athlete. On a non-allowlisted
email it returns 403 `{"error": "request access"}` -- deliberately no
session and no athlete row is ever created for an unrecognized email.

`GET /api/me` is what a later frontend PR calls to resolve "who am I" from a
bearer token -- only meaningful for an athlete-session principal (a service
credential has no single identity to report).

This module is purely ADDITIVE: nothing here is on the request path of any
existing route, and no existing behavior changes until an athlete actually
signs in via Google.
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
# no role column yet, matching web/src/identity.js's own EMAIL_IDENTITY_MAP,
# where all three seeded users are role "athlete". A "coach" role (with
# cross-athlete access) is a deliberate later addition, same as that file's
# own comment says -- not invented here.
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

    athlete = store.load_athlete(allowed.athlete_slug)

    raw_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.session_ttl_days)
    store.create_session(allowed.athlete_slug, hash_token(raw_token), expires_at=expires_at)

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
