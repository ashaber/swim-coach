"""GET /api/sessions/{session_id}/garmin.fit -- download one session's
resolved `structured` workout as a real Garmin workout-type `.FIT` file (see
`swim_coach.garmin_export`'s module docstring for why this -- not a Garmin
Connect JSON upload -- is the actually-real export path: USB-copy the
downloaded file into the watch's `Workouts` folder).

This is the "everything accessible in app and coach, not just the CLI" DOD
item's app-side half; `web/src/views.js`'s `renderPlanSessionDetail` links
here for any session with `structured` populated.

Also owns POST /api/sessions/{session_id}/push-intervals -- the wireless
counterpart the athlete actually asked for (USB-copy was tried and rejected
as impractical): pushes the same `.FIT` bytes to the athlete's intervals.icu
calendar, which intervals.icu's own Garmin Connect integration then forwards
to the watch automatically. See `app.garmin_push`'s module docstring for the
full mechanism and the one-time athlete-side setup it depends on.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from swim_coach.garmin_export import to_garmin_fit_workout
from swim_coach.models import Session
from swim_coach.store import StoreInterface

from app.auth import Principal, require_auth, resolve_athlete
from app.config import ConfigError
from app.logging_config import get_logger
from app.store_factory import make_store
from app.sync import SYNC_NOT_CONFIGURED_ERROR, load_sync_config

router = APIRouter()
log = get_logger("app.routes.garmin")

# The ANT+ organization's own registered MIME type for .FIT files (not a
# generic application/octet-stream) -- confirmed via
# https://www.thisisant.com/forum/viewthread/2566.
_FIT_CONTENT_TYPE = "application/vnd.ant.fit"

# `Session.sport` (see models.py's `Sport` Literal) -> the narrower
# `sport` Literal `to_garmin_fit_workout` accepts. "recovery"/"cross_train"
# have no real FIT sport-specific workout-step encoding here and are
# rejected with a clear 422 rather than silently mis-tagged as swim/strength.
_SESSION_SPORT_TO_GARMIN_SPORT: dict[str, str] = {
    "swim_pool": "swim",
    "swim_ow": "swim",
    "strength": "strength",
}


def _find_session(store: StoreInterface, athlete: str, session_id: UUID) -> Session | None:
    """Search every week on file for `athlete` for a session matching
    `session_id`. `StoreInterface` has no by-id session lookup -- weeks are
    the unit of storage -- so this is a linear scan over
    `list_week_ids`/`load_week`, the same access pattern
    `scripts/export_plan_json.py` already uses to enumerate all of an
    athlete's sessions. Fine at this scale (a handful of weeks per athlete).
    """
    for iso_week in store.list_week_ids(athlete):
        week = store.load_week(athlete, iso_week)
        if week is None:
            continue
        for session in week.sessions:
            if session.id == session_id:
                return session
    return None


@router.get("/api/sessions/{session_id}/garmin.fit")
async def get_session_garmin_fit(
    session_id: UUID,
    request: Request,
    athlete: str | None = Query(None),
    principal: Principal = Depends(require_auth),
) -> Response:
    settings = request.app.state.settings
    athlete = resolve_athlete(principal, athlete)
    store = make_store(settings)

    session = _find_session(store, athlete, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"no such session: {session_id}")
    if session.structured is None:
        raise HTTPException(
            status_code=404,
            detail="this session has no structured workout data to export (structured is None)",
        )

    garmin_sport = _SESSION_SPORT_TO_GARMIN_SPORT.get(session.sport)
    if garmin_sport is None:
        raise HTTPException(
            status_code=422,
            detail=f"garmin .fit export isn't supported for sport {session.sport!r}",
        )

    try:
        fit_bytes = to_garmin_fit_workout(session.structured, sport=garmin_sport, name=session.purpose)
    except ValueError as exc:
        # An unresolved template (basis="percent_css") reaching this point
        # would be an engine bug (generate_week always resolves before
        # saving), not an athlete-facing input error -- still a clean 422,
        # never an unhandled 500, per this repo's exception-handling
        # standard.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    filename = f"{session.date.isoformat()}-{session.sport}.fit"
    return Response(
        content=fit_bytes,
        media_type=_FIT_CONTENT_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/api/sessions/{session_id}/push-intervals")
async def push_session_garmin(
    session_id: UUID,
    request: Request,
    athlete: str | None = Query(None),
    principal: Principal = Depends(require_auth),
) -> dict:
    """Pushes one session's Garmin `.FIT` workout to the athlete's
    intervals.icu calendar (see `app.garmin_push`'s module docstring for the
    full mechanism). Same session-resolution and error-status conventions as
    the sibling `GET .../garmin.fit` route above: 404 for no such session,
    404 for `structured is None`, 422 for an unsupported sport. If the
    athlete has no working intervals.icu sync configured, returns 409 with
    the same `{"error": SYNC_NOT_CONFIGURED_ERROR}` shape
    `POST /api/workouts/sync` (`app.routes.workouts.sync_workouts`) already
    uses for the identical situation -- never a bare 500.
    """
    settings = request.app.state.settings
    athlete = resolve_athlete(principal, athlete)
    store = make_store(settings)

    session = _find_session(store, athlete, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"no such session: {session_id}")
    if session.structured is None:
        raise HTTPException(
            status_code=404,
            detail="this session has no structured workout data to push (structured is None)",
        )

    garmin_sport = _SESSION_SPORT_TO_GARMIN_SPORT.get(session.sport)
    if garmin_sport is None:
        raise HTTPException(
            status_code=422,
            detail=f"garmin push isn't supported for sport {session.sport!r}",
        )

    try:
        configs = load_sync_config()
    except ConfigError:
        raise HTTPException(status_code=409, detail=SYNC_NOT_CONFIGURED_ERROR)
    cfg = next((c for c in configs if c.slug == athlete), None)
    if cfg is None:
        raise HTTPException(status_code=409, detail=SYNC_NOT_CONFIGURED_ERROR)

    # Deferred import: `app.garmin_push` imports `_SESSION_SPORT_TO_GARMIN_SPORT`
    # and `_find_session` FROM this module (see that module's docstring) --
    # importing it back at THIS module's top level would be a circular
    # import at load time. Safe here: by the time a request handler actually
    # runs, both modules have already finished loading.
    from app.garmin_push import push_session_to_intervals

    try:
        return push_session_to_intervals(session, cfg=cfg)
    except Exception as exc:  # noqa: BLE001 - an upstream intervals.icu failure, never a bare 500
        log.error(
            "garmin_push.route_failed", athlete=athlete, session_id=str(session_id), error=str(exc)
        )
        raise HTTPException(
            status_code=502, detail=f"failed to push to intervals.icu: {exc}"
        ) from exc
