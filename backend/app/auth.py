"""Auth: bearer-token dependency, now principal-aware (Slice 1: verified
identity).

Two credential kinds resolve through the SAME `Authorization: Bearer
<token>` header, so no route's request shape changes:

  - the legacy shared `API_TOKEN` (env var, `Settings.token_matches`) --
    resolves to a **service** principal (admin/CLI/sync-job/scripts). Its
    behavior is UNCHANGED from the pre-Slice-1 `require_auth`: it may still
    act as any athlete via `?athlete=`.
  - a session token minted by `POST /api/auth/google` (`routes/auth.py`),
    looked up (sha256-hashed) against the `sessions` store methods --
    resolves to an **athlete** principal, bound to exactly one athlete.

Design note (ROADMAP.md "Auth-lite"): the service-token path is the original
v1 placeholder for a single-athlete deployment; Phase 3's "retire shared
token for athletes" step narrows what the service token can still do, but
this file's job is only ever to resolve a token to a `Principal` --
route bodies depend on `require_auth`/`resolve_athlete`/
`require_chat_rate_limit`, never on token mechanics directly.

Also holds the in-memory per-token-per-minute chat rate limiter
(`ChatRateLimiter`, unchanged) and a new in-memory PER-ATHLETE daily chat cap
(`DailyChatLimiter`) -- both reset on redeploy and don't share state across
Cloud Run instances (same accepted limitation as before; a real multi-
instance limiter would move this to Redis/Supabase, noted as a TODO).
"""

from __future__ import annotations

import hashlib
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from fastapi import HTTPException, Request

from app.logging_config import get_logger
from app.store_factory import make_store

log = get_logger("app.auth")


def hash_token(token: str) -> str:
    """sha256 hex digest -- used both for session-token lookup here and for
    email-hashing in access-request logs (never log a raw email or token)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Principal:
    """The resolved identity of a request's bearer token.

    `kind == "service"`: the legacy shared API_TOKEN. `athlete` is always
    None here -- a service principal isn't bound to one athlete, it may act
    as any (existing CLI/scripts/sync-job behavior, unchanged).

    `kind == "athlete"`: a live session minted by POST /api/auth/google.
    `athlete` is that session's athlete slug; `expires_at` is carried along
    so GET /api/me can report it without a second store round-trip.

    `token` is the raw bearer token as presented (never the hash) -- kept
    only so `ChatRateLimiter`/`DailyChatLimiter` can key off it; it is never
    logged (see module docstring of the old auth.py and CLAUDE.md's logging
    rules).
    """

    kind: Literal["service", "athlete"]
    athlete: str | None
    token: str
    expires_at: datetime | None = None


async def require_auth(request: Request) -> Principal:
    """FastAPI dependency: validates the `Authorization: Bearer <token>`
    header and resolves it to a `Principal`. Raises 401 if the header is
    missing/malformed, or if the token matches neither the service token nor
    a live (unexpired, unrevoked) session."""
    settings = request.app.state.settings
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    provided = header[len("Bearer ") :].strip()
    if not provided:
        raise HTTPException(status_code=401, detail="invalid token")

    # Service credential first -- identical check/outcome to the pre-Slice-1
    # require_auth, so every existing service-token caller is unaffected.
    if settings.token_matches(provided):
        return Principal(kind="service", athlete=None, token=provided)

    store = make_store(settings)
    try:
        session = store.get_session(hash_token(provided))
    except Exception as exc:
        # Can't validate the presented token if the store itself is broken --
        # fail closed to 401 rather than leak a 500/traceback (prod hit this
        # via a missing auth_sessions table; DB is fixed, this is belt/suspenders).
        log.error("auth.session_lookup_failed", error=str(exc))
        raise HTTPException(status_code=401, detail="invalid token") from exc
    now = datetime.now(timezone.utc)
    if session is None or session.revoked_at is not None or session.expires_at <= now:
        raise HTTPException(status_code=401, detail="invalid token")

    return Principal(
        kind="athlete",
        athlete=session.athlete_slug,
        token=provided,
        expires_at=session.expires_at,
    )


def resolve_athlete(principal: Principal, requested: str | None, *, default: str = "renee") -> str:
    """Applies athlete-session scoping to a route's `athlete` parameter
    (a `?athlete=` query param, or the `athlete` field of /api/chat's JSON
    body).

    - Service principal: passes through UNCHANGED from today's behavior --
      `requested` if given, else `default` (every existing route already
      defaults to "renee" this way; nothing changes for CLI/scripts/sync).
    - Athlete-session principal: the SESSION is authoritative. `requested is
      None` (the caller didn't pass `athlete` at all) resolves to the
      session's own athlete with no error -- this is what lets a future
      frontend stop sending `?athlete=` entirely. `requested` given and
      equal to the session's athlete is a no-op. `requested` given and
      DIFFERENT from the session's athlete is a 403 -- the one guarantee
      that must never regress: an athlete session can never read/write
      another athlete's data by changing the query param.
    """
    if principal.kind == "service":
        return requested if requested is not None else default
    if requested is not None and requested != principal.athlete:
        raise HTTPException(status_code=403, detail="athlete mismatch")
    assert principal.athlete is not None  # invariant: every athlete principal has an athlete
    return principal.athlete


class ChatRateLimiter:
    """Fixed-window-ish (sliding, in practice) per-key rate limiter.

    `check(key)` records a hit and returns True iff the key's hit count in
    the trailing 60s is within `per_minute`. One instance lives on
    `app.state.chat_rate_limiter`, keyed by `Principal.token` -- a service
    token's key is the one shared literal value (unchanged from before), an
    athlete session's key is that session's own unique token, so the limit
    is naturally per-athlete-session now.
    """

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._hits: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str, *, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        window_start = now - 60.0
        hits = [t for t in self._hits[key] if t > window_start]
        hits.append(now)
        self._hits[key] = hits
        return len(hits) <= self.per_minute


class DailyChatLimiter:
    """Per-athlete DAILY cap on /api/chat, independent of ChatRateLimiter's
    per-minute window above. Keyed by athlete SLUG (not token), so a
    revoked-and-reissued session for the same athlete doesn't reset the
    day's count. Never consulted for a service principal -- see
    `require_daily_chat_cap` below -- so this is entirely new exposure, not
    a behavior change for the existing shared-token callers.

    "Day" is a rolling 24h window in UTC from the first hit, not a
    calendar-day reset, matching ChatRateLimiter's own rolling-window
    style. Same in-memory/no-cross-instance-sharing caveat as
    ChatRateLimiter (a TODO for a durable, multi-instance-safe counter).
    """

    def __init__(self, per_day: int) -> None:
        self.per_day = per_day
        self._hits: dict[str, list[float]] = defaultdict(list)

    def check(self, athlete: str, *, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        window_start = now - 86_400.0
        hits = [t for t in self._hits[athlete] if t > window_start]
        hits.append(now)
        self._hits[athlete] = hits
        return len(hits) <= self.per_day


def require_chat_rate_limit(request: Request, token: str) -> None:
    """Raises 429 if `token` has exceeded `CHAT_RATE_PER_MIN` in the
    trailing 60s. Not a FastAPI `Depends` itself (it needs the token
    resolved by `require_auth` first) -- called explicitly from the chat
    route after auth succeeds. Callers pass `principal.token`."""
    limiter: ChatRateLimiter = request.app.state.chat_rate_limiter
    if not limiter.check(token):
        raise HTTPException(status_code=429, detail="chat rate limit exceeded")


def require_daily_chat_cap(request: Request, principal: Principal) -> None:
    """Raises 429 if this athlete SESSION has exceeded
    `CHAT_DAILY_CAP_PER_ATHLETE` requests in the trailing 24h. A no-op for a
    service principal -- the legacy shared token's chat behavior is
    unchanged by this PR (see module docstring)."""
    if principal.kind != "athlete" or principal.athlete is None:
        return
    limiter: DailyChatLimiter = request.app.state.chat_daily_limiter
    if not limiter.check(principal.athlete):
        log.warn("chat.daily_cap_exceeded", athlete=principal.athlete)
        raise HTTPException(
            status_code=429,
            detail="daily chat limit reached for this athlete; try again tomorrow",
        )
