"""Push a planned session's Garmin `.FIT` workout to the athlete's
intervals.icu calendar as a WORKOUT event, so intervals.icu's own Garmin
Connect integration forwards it to the watch wirelessly -- no new OAuth
scope, no USB cable. This is the "everything reachable in app and chat, not
just a USB copy" answer to the athlete's actual ask (see
`app.routes.garmin`'s `GET .../garmin.fit` module docstring for the older
USB-copy export path, which this supplements rather than replaces).

Mechanism (confirmed live against the intervals.icu API, not re-derived
here -- do not substitute a different one): `POST
/api/v1/athlete/{id}/events/bulk?upsert=true` with a JSON array of calendar
events, each carrying the real Garmin workout-type `.FIT` file (from
`swim_coach.garmin_export.to_garmin_fit_workout`, used completely unchanged)
as base64 in `file_contents_base64`. `external_id=<session id>` plus
`upsert=true` makes a re-push idempotent -- per intervals.icu's own docs,
`external_id` matching is scoped to events created by this application, so
it can never collide with some other tool's calendar entries. See
`app.sync.IntervalsClient.push_workout_events` for the actual HTTP call this
module builds events for.

**One-time athlete-side setup this module cannot automate -- do not try to
build around it**: Intervals.icu -> Settings -> Connections -> authorize
Garmin Connect -> tick "Upload planned workouts". Without that box checked,
a pushed event lands on the intervals.icu calendar and stops there -- it
never reaches the watch. See ROADMAP.md's "Now / Next" section, and this
module's `push_to_garmin` chat-tool description (app/tools.py) which warns
the coach to mention it.

Also worth being honest about (see ROADMAP.md): intervals.icu has no
exercise-catalog/icon rendering for strength workouts, so a pushed strength
session shows up on the watch as named steps + reps + lap-advance, not with
Garmin's own per-exercise icons/animations -- same limitation
`swim_coach.garmin_export`'s "Strength exercise-catalog caveat" already
documents for the USB-copy path, inherited here unchanged.
"""

from __future__ import annotations

import base64
from typing import Any
from uuid import UUID

from swim_coach.garmin_export import to_garmin_fit_workout
from swim_coach.models import Session
from swim_coach.store import StoreInterface

from app.config import ConfigError
from app.logging_config import get_logger
from app.routes.garmin import _SESSION_SPORT_TO_GARMIN_SPORT, _find_session
from app.sync import (
    SYNC_NOT_CONFIGURED_ERROR,
    IntervalsAthleteConfig,
    IntervalsClient,
    load_sync_config,
)

log = get_logger("app.garmin_push")

# `Session.sport` -> intervals.icu's own `type` field for a calendar WORKOUT
# event (their activity-type vocabulary). This is DISTINCT from
# `app.routes.garmin`'s `_SESSION_SPORT_TO_GARMIN_SPORT` (imported above) --
# that dict selects the `sport` argument to
# `swim_coach.garmin_export.to_garmin_fit_workout`, i.e. a FIT sub_sport
# encoding; this dict is intervals.icu's *own* calendar-event vocabulary,
# an entirely different API surface. A future reader must not "helpfully"
# merge these two just because they happen to share the same three keys
# today -- that's a coincidence of scope (both only cover the sports this
# feature supports pushing), not a sign they're the same mapping.
_SESSION_SPORT_TO_INTERVALS_TYPE: dict[str, str] = {
    "swim_pool": "Swim",
    "swim_ow": "Swim",
    "strength": "WeightTraining",
}


def build_workout_event(session: Session) -> dict[str, Any]:
    """Builds one intervals.icu calendar WORKOUT event dict (this module's
    docstring's bulk-events contract) for `session`.

    Raises `ValueError` -- distinguishable by message -- for a session with
    no `structured` workout data (nothing real to export) or an unsupported
    sport (only swim_pool/swim_ow/strength -- same narrow scope as
    `to_garmin_fit_workout` itself; cycling etc. is explicitly out of
    scope). Callers that need to skip-and-count rather than fail (see
    `push_on_demand` below) check these same two conditions themselves
    before calling this, so they can attach a friendly, structured reason;
    this function's own raise is just a safety net for any other caller.
    """
    if session.structured is None:
        raise ValueError(f"session {session.id} has no structured workout data to push")

    garmin_sport = _SESSION_SPORT_TO_GARMIN_SPORT.get(session.sport)
    intervals_type = _SESSION_SPORT_TO_INTERVALS_TYPE.get(session.sport)
    if garmin_sport is None or intervals_type is None:
        raise ValueError(f"garmin push isn't supported for sport {session.sport!r}")

    fit_bytes = to_garmin_fit_workout(session.structured, sport=garmin_sport, name=session.purpose)

    return {
        "category": "WORKOUT",
        "type": intervals_type,
        "start_date_local": f"{session.date.isoformat()}T00:00:00",
        "filename": f"session-{session.id}.fit",
        "file_contents_base64": base64.b64encode(fit_bytes).decode("ascii"),
        "external_id": str(session.id),
        "name": session.purpose,
    }


def push_session_to_intervals(
    session: Session,
    *,
    cfg: IntervalsAthleteConfig,
    client: IntervalsClient | None = None,
) -> dict[str, Any]:
    """Builds and pushes one session's workout event to intervals.icu.

    `client=None` builds (and closes) a real `IntervalsClient` from `cfg` --
    the seam tests inject a mocked-transport client through instead, same
    convention as `app.sync.sync_athlete`'s own `client=None` parameter.
    Raises whatever `build_workout_event` or the HTTP call raise; the caller
    (the `POST /api/sessions/{id}/push-intervals` route, or `push_on_demand`
    below) decides how to turn that into a friendly response -- this
    function stays a thin, honest "do the push" primitive so both callers
    share the exact same push logic instead of each re-implementing it.
    """
    event = build_workout_event(session)

    owns_client = client is None
    if client is None:
        client = IntervalsClient(cfg.intervals_athlete_id, cfg.api_key)
    try:
        client.push_workout_events([event])
    finally:
        if owns_client:
            client.close()

    log.info(
        "garmin_push.session_pushed",
        slug=cfg.slug,
        session_id=str(session.id),
        date=str(session.date),
        type=event["type"],
    )
    return {
        "pushed": True,
        "session_id": str(session.id),
        "date": session.date.isoformat(),
        "type": event["type"],
    }


def _load_athlete_config(slug: str) -> IntervalsAthleteConfig | None:
    """Looks up `slug` in `INTERVALS_SYNC_CONFIG` (the exact same config
    `app.sync.sync_on_demand` reads). `None` covers both "the config itself
    is missing/malformed" and "it's fine but doesn't list this athlete" --
    both collapse to the same `SYNC_NOT_CONFIGURED_ERROR` at every caller."""
    try:
        configs = load_sync_config()
    except ConfigError as exc:
        log.error("garmin_push.config_error", slug=slug, error=str(exc))
        return None
    return next((c for c in configs if c.slug == slug), None)


def _coerce_session_id(session_id: str | UUID | None) -> UUID | None:
    if session_id is None or isinstance(session_id, UUID):
        return session_id
    return UUID(str(session_id))


def _resolve_sessions(
    store: StoreInterface, slug: str, *, iso_week: str | None, session_id: UUID | None
) -> list[Session] | dict[str, str]:
    """Resolves the sessions `push_on_demand` should attempt: a single
    session (by id, via the same `_find_session` linear scan
    `app.routes.garmin`'s GET route uses) or every session in one week.
    Returns an `{"error": ...}` dict instead of a list for "no such
    session" / "no such week" / "neither given" -- `push_on_demand` returns
    that dict straight through."""
    if session_id is not None:
        session = _find_session(store, slug, session_id)
        if session is None:
            return {"error": f"no such session: {session_id}"}
        return [session]
    if iso_week is not None:
        week = store.load_week(slug, iso_week)
        if week is None:
            return {"error": f"no such week: {iso_week}"}
        return list(week.sessions)
    return {"error": "push_on_demand requires session_id or iso_week"}


def push_on_demand(
    store: StoreInterface,
    slug: str,
    *,
    iso_week: str | None = None,
    session_id: str | UUID | None = None,
) -> dict[str, Any]:
    """Single-athlete, on-demand Garmin push shared by the coach chat's
    `push_to_garmin` tool (`app.tools`) -- mirrors `app.sync.sync_on_demand`'s
    shape: look up `slug` in `INTERVALS_SYNC_CONFIG` and return
    `{"error": SYNC_NOT_CONFIGURED_ERROR}` if it's missing/malformed or
    doesn't list this athlete. Otherwise pushes either one session
    (`session_id`) or every session in one week (`iso_week`) -- pass
    whichever the caller has; if both are omitted, or `session_id`/`iso_week`
    doesn't resolve to anything real, returns a clean `{"error": ...}`
    instead of raising.

    A session with no `structured` workout data or an unsupported sport is
    skipped and counted (`summary["skipped"]`), never fatal to the rest of
    the batch -- same failure-isolation spirit as `sync_athlete`'s
    per-activity handling. A session that resolves fine but fails the actual
    HTTP push (a transient intervals.icu error, etc.) is counted under
    `summary["failed"]` instead, also non-fatal to the rest of the batch.
    """
    cfg = _load_athlete_config(slug)
    if cfg is None:
        return {"error": SYNC_NOT_CONFIGURED_ERROR}

    try:
        resolved_session_id = _coerce_session_id(session_id)
    except ValueError:
        return {"error": f"invalid session_id: {session_id!r}"}

    sessions = _resolve_sessions(store, slug, iso_week=iso_week, session_id=resolved_session_id)
    if isinstance(sessions, dict):
        return sessions

    summary: dict[str, Any] = {"pushed": 0, "skipped": 0, "failed": 0, "results": []}
    client = IntervalsClient(cfg.intervals_athlete_id, cfg.api_key)
    try:
        for session in sessions:
            unsupported = session.sport not in _SESSION_SPORT_TO_GARMIN_SPORT
            if session.structured is None or unsupported:
                reason = (
                    "no structured workout data"
                    if session.structured is None
                    else f"unsupported sport {session.sport!r}"
                )
                log.info(
                    "garmin_push.session_skipped",
                    slug=slug,
                    session_id=str(session.id),
                    reason=reason,
                )
                summary["skipped"] += 1
                summary["results"].append(
                    {"session_id": str(session.id), "pushed": False, "reason": reason}
                )
                continue

            try:
                result = push_session_to_intervals(session, cfg=cfg, client=client)
            except Exception as exc:  # noqa: BLE001 - one bad session must not abort the batch
                log.error(
                    "garmin_push.session_failed",
                    slug=slug,
                    session_id=str(session.id),
                    error=str(exc),
                )
                summary["failed"] += 1
                summary["results"].append(
                    {"session_id": str(session.id), "pushed": False, "error": str(exc)}
                )
                continue

            summary["pushed"] += 1
            summary["results"].append(result)
    finally:
        client.close()

    return summary
