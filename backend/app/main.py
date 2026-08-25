"""FastAPI app factory: JSON-logging middleware, CORS, /health, global
exception handling, fail-fast config.

`create_app()` is called once per process (module-level `app` below, for
`uvicorn app.main:app`) and once per test (tests build their own app after
monkeypatching env vars, so each test gets an independently-configured
`Settings`).
"""

from __future__ import annotations

import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.auth import ChatRateLimiter, DailyChatLimiter
from app.config import Settings
from app.logging_config import get_logger
from app.routes.athlete import router as athlete_router
from app.routes.auth import router as auth_router
from app.routes.chat import router as chat_router
from app.routes.coach import router as coach_router
from app.routes.feedback import router as feedback_router
from app.routes.garmin import router as garmin_router
from app.routes.grants import router as grants_router
from app.routes.onboard import router as onboard_router
from app.routes.plan import router as plan_router
from app.routes.wellness import router as wellness_router
from app.routes.workouts import router as workouts_router

log = get_logger("app.main")


def create_app() -> FastAPI:
    # Fails fast: Settings.from_env() raises ConfigError (a RuntimeError
    # subclass) if ANTHROPIC_API_KEY or API_TOKEN is missing, or if
    # CLAUDE_THINKING is set to something other than adaptive/disabled --
    # this must happen before the app can serve anything.
    settings = Settings.from_env()

    app = FastAPI(title="swim-coach-api")
    app.state.settings = settings
    app.state.chat_rate_limiter = ChatRateLimiter(settings.chat_rate_per_min)
    app.state.chat_daily_limiter = DailyChatLimiter(settings.chat_daily_cap_per_athlete)
    app.state.claude_chat = None  # lazily built by routes.chat.get_claude_chat

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        # PATCH added for /api/athlete (Phase 2.5 profile-edit screen) --
        # without it here, the browser's CORS preflight for the PATCH itself
        # gets rejected (400) before the request ever reaches the route,
        # even though the route handler is otherwise correct. Caught by
        # driving the real (unmocked) backend through a real browser -- the
        # e2e suite's Playwright route-mocking fulfills the OPTIONS
        # preflight itself, so it never exercises this middleware.
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        # `Content-Disposition` isn't one of the CORS "simple response
        # headers" a cross-origin `fetch` can read by default -- without
        # exposing it explicitly here, `response.headers.get(
        # 'content-disposition')` silently returns null in the browser even
        # though the server sends it correctly (curl/TestClient both see it
        # fine, since neither enforces CORS) -- so `web/src/api.js`'s
        # `downloadGarminFit` always fell back to its generic
        # `{sessionId}.fit` filename. Caught by driving the real (unmocked)
        # backend through a real browser (GET /api/sessions/{id}/garmin.fit),
        # not by the API test suite alone (TestClient doesn't enforce CORS
        # header-exposure rules either).
        expose_headers=["Content-Disposition"],
    )

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = round((time.monotonic() - start) * 1000, 2)
        log.info(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
        )
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        log.error("unhandled exception", error=str(exc), path=request.url.path)
        return JSONResponse(status_code=500, content={"error": "internal server error"})

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    app.include_router(chat_router)
    app.include_router(plan_router)
    app.include_router(workouts_router)
    app.include_router(wellness_router)
    app.include_router(athlete_router)
    app.include_router(feedback_router)
    app.include_router(auth_router)
    app.include_router(onboard_router)
    app.include_router(garmin_router)
    app.include_router(grants_router)
    app.include_router(coach_router)

    log.info(
        "service start",
        port=settings.port,
        model=settings.claude_model,
        thinking=settings.claude_thinking,
    )
    return app


app = create_app()
