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

Also owns GET /api/sessions/{session_id}/zwo (engine/cycling-coach Part C):
the INDOOR/trainer counterpart for a bike session -- a `.zwo` file for
MyWhoosh/Zwift's own Workout Builder, a genuinely different piece of
software from Garmin/intervals.icu, not reachable through the Garmin push
path above at all. See `app.zwo_export`'s module docstring for why this is a
plain download rather than a draft-then-confirm flow.
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
#
# "bike" (engine/cycling-coach Part C): outdoor cycling now gets the SAME
# Garmin FIT push path already built for swim/strength -- see
# `_reject_indoor_bike` below for the one exception (an `is_indoor` session
# routes to `.zwo` export instead, not this path).
_SESSION_SPORT_TO_GARMIN_SPORT: dict[str, str] = {
    "swim_pool": "swim",
    "swim_ow": "swim",
    "strength": "strength",
    "bike": "bike",
}


def _reject_indoor_bike(session: Session) -> None:
    """A live Garmin/intervals.icu calendar push assumes an outdoor ride --
    an indoor/trainer bike session should be exported as `.zwo`
    (`GET /api/sessions/{id}/zwo` below, or `swim_coach.zwo_export` directly)
    for MyWhoosh/Zwift instead, per this build's own explicit design split
    (see PR description). Raises a 422 with a clear pointer to the right
    export, rather than silently pushing a trainer session as if it were a
    real outdoor GPS ride. A plain `GET .../garmin.fit` DOWNLOAD (the
    USB-copy path) is deliberately NOT gated the same way -- an athlete
    could still legitimately want a raw .fit file for an indoor session on
    non-Zwift-compatible hardware (e.g. a Wahoo/Garmin head unit on a
    trainer), and that path has no live-calendar-write consequence to guard
    against.
    """
    if session.sport == "bike" and session.is_indoor:
        raise HTTPException(
            status_code=422,
            detail=(
                "this is an indoor/trainer bike session -- Garmin push assumes an "
                "outdoor ride; export it as a .zwo file instead "
                f"(GET /api/sessions/{session.id}/zwo)"
            ),
        )


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
    _reject_indoor_bike(session)

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


# The Zwift/MyWhoosh workout-file MIME type has no dedicated IANA
# registration (unlike .FIT's `application/vnd.ant.fit` above) -- ZWO is
# plain XML, so `application/xml` is the honest, standard choice.
_ZWO_CONTENT_TYPE = "application/xml"


@router.get("/api/sessions/{session_id}/zwo")
async def get_session_zwo(
    session_id: UUID,
    request: Request,
    athlete: str | None = Query(None),
    principal: Principal = Depends(require_auth),
) -> Response:
    """Downloads one INDOOR/trainer bike session's `.zwo` file for MyWhoosh/
    Zwift's own Workout Builder import (engine/cycling-coach Part C) -- the
    trainer-software counterpart to `GET .../garmin.fit` above, NOT a
    replacement for it (see `app.zwo_export`'s module docstring). Not gated
    on `Session.is_indoor` -- an outdoor-tagged bike session can still be
    exported this way if the athlete wants it (see `_reject_indoor_bike`'s
    own docstring for why only the live Garmin PUSH path is gated, not this
    plain download); it IS gated on `sport == "bike"` (422 otherwise),
    `structured is not None` (404, same convention as `garmin.fit`), and the
    athlete having a real `ftp_watts` on file (422 -- a `.zwo` file's power
    targets are meaningless without one, and this build refuses to guess).
    """
    settings = request.app.state.settings
    athlete_slug = resolve_athlete(principal, athlete)
    store = make_store(settings)

    session = _find_session(store, athlete_slug, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"no such session: {session_id}")
    if session.sport != "bike":
        raise HTTPException(
            status_code=422, detail=f"zwo export isn't supported for sport {session.sport!r}"
        )
    if session.structured is None:
        raise HTTPException(
            status_code=404,
            detail="this session has no structured workout data to export (structured is None)",
        )

    try:
        athlete_obj = store.load_athlete(athlete_slug)
    except Exception as exc:  # noqa: BLE001 - a resolved-but-somehow-missing athlete is a clean 404
        raise HTTPException(status_code=404, detail=f"no such athlete: {athlete_slug}") from exc
    if athlete_obj.ftp_watts is None:
        raise HTTPException(
            status_code=422,
            detail="no ftp_watts on file for this athlete -- required for a .zwo export",
        )

    # Deferred import: same circular-import reasoning as app.garmin_push's
    # deferred import above.
    from app.zwo_export import build_zwo_export

    try:
        result = build_zwo_export(session, athlete_obj.ftp_watts)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return Response(
        content=result["zwo_xml"].encode("utf-8"),
        media_type=_ZWO_CONTENT_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{result["filename"]}"'},
    )
