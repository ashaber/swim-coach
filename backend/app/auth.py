"""Auth-lite: a single opaque bearer token, sha256-hashed comparison.

Design note (ROADMAP.md "Auth-lite"): this is a v1 placeholder for a
single-athlete deployment -- one shared `API_TOKEN` env var, compared via
constant-time sha256-hash comparison (`Settings.token_matches`). Phase 3
swaps this dependency for a Supabase JWT verifier without touching route
signatures (routes only depend on `require_auth`/`require_chat_rate_limit`,
never on token mechanics directly).

Also holds a simple in-memory per-token rate limiter for `/api/chat`
(`CHAT_RATE_PER_MIN`). In-memory means it resets on redeploy and doesn't
share state across multiple Cloud Run instances -- acceptable for a
single-athlete v1 (`min-instances=0, max-instances=2`); a real multi-instance
limiter would move this to Redis/Supabase. Noted as a TODO.
"""

from __future__ import annotations

import time
from collections import defaultdict

from fastapi import HTTPException, Request


async def require_auth(request: Request) -> str:
    """FastAPI dependency: validates the `Authorization: Bearer <token>`
    header against `Settings.token_matches`. Returns the provided token (so
    downstream dependencies, e.g. the rate limiter, can key off it) or
    raises 401."""
    settings = request.app.state.settings
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    provided = header[len("Bearer ") :].strip()
    if not provided or not settings.token_matches(provided):
        raise HTTPException(status_code=401, detail="invalid token")
    return provided


class ChatRateLimiter:
    """Fixed-window-ish (sliding, in practice) per-key rate limiter.

    `check(key)` records a hit and returns True iff the key's hit count in
    the trailing 60s is within `per_minute`. One instance lives on
    `app.state.chat_rate_limiter`, keyed by bearer token (so a future
    multi-athlete deployment naturally gets a per-athlete limit for free).
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


def require_chat_rate_limit(request: Request, token: str) -> None:
    """Raises 429 if `token` has exceeded `CHAT_RATE_PER_MIN` in the
    trailing 60s. Not a FastAPI `Depends` itself (it needs the token
    resolved by `require_auth` first) -- called explicitly from the chat
    route after auth succeeds."""
    limiter: ChatRateLimiter = request.app.state.chat_rate_limiter
    if not limiter.check(token):
        raise HTTPException(status_code=429, detail="chat rate limit exceeded")
