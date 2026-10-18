"""Weak-ETag / 304 plumbing for the polled read endpoints.

The PWA re-checks the workout list, plan and load on tab switch and app resume. The ETag is a hash
of the store's cheap change token (`StoreInterface.change_token`) plus the request identity, so an
unchanged answer costs one fingerprint query -- the payload is never built for a 304.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from swim_coach.store import StoreInterface

from app.auth import Principal

CACHE_CONTROL = "private, no-cache"


def make_etag(store: StoreInterface, principal: Principal, athlete: str, scope: str, variant: str = "") -> str:
    """Weak ETag for `athlete`'s `scope` data as seen by `principal`. `variant` carries any query
    parameter that changes the payload (e.g. the load window). Raises HTTP 404 for an unknown athlete."""
    try:
        token = store.change_token(athlete, scope)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"no such athlete: {athlete}") from exc
    key = "|".join([principal.kind, principal.athlete or "", athlete, scope, variant, token])
    return 'W/"' + hashlib.sha256(key.encode()).hexdigest()[:32] + '"'


def _matches(request: Request, etag: str) -> bool:
    header = request.headers.get("if-none-match")
    if not header:
        return False
    if header.strip() == "*":
        return True
    opaque = etag.removeprefix("W/")
    return any(candidate.strip().removeprefix("W/") == opaque for candidate in header.split(","))


def respond_with_etag(request: Request, etag: str, build: Callable[[], Any]) -> Response:
    """304 (no body, `build` never called) when If-None-Match matches, else the built payload as
    JSON with the ETag attached."""
    headers = {"ETag": etag, "Cache-Control": CACHE_CONTROL}
    if _matches(request, etag):
        return Response(status_code=304, headers=headers)
    return JSONResponse(jsonable_encoder(build()), headers=headers)
