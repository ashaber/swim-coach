"""GET /api/coach/athletes, GET .../workouts, GET .../feedback, PATCH
.../feedback/{id} -- the coach-side view (coach-mode Phase 1).

Gated via `resolve_coach_athlete` (backend/app/auth.py, merged on main) --
a wholly separate access mode from the athlete-self-scoped routes
(`resolve_athlete`, `routes/grants.py`). `resolve_coach_athlete` checks
`principal.coach_for` (the athlete slugs this session holds an ACTIVE
`CoachGrant` for) rather than "is this my own data."
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from swim_coach.load import estimate_hr_max
from swim_coach.quality import match_workout_to_session, workout_quality
from swim_coach.models import Feedback, HealthStatus, Session
from swim_coach.store import StoreInterface

from app.auth import Principal, require_auth, resolve_coach_athlete
from app.config import Settings
from app.context import summarize_rollup
from app.load_helpers import workout_load_au
from app.notify import notify_athlete_of_coach_reply
from app.routes.plan import (
    LOAD_GRAPH_DEFAULT_WEEKS,
    LOAD_GRAPH_MAX_WEEKS,
    LOAD_GRAPH_MIN_WEEKS,
    export_athlete,
)
from app.store_factory import make_store

router = APIRouter()

# Same shape/seam convention as routes/feedback.py's `Notifier`/`get_notifier`
# -- a type alias plus a FastAPI dependency indirection so tests can override
# it with a spy/fake instead of exercising a real BackgroundTask that would
# otherwise try to reach the real Resend API.
AthleteNotifier = Callable[[StoreInterface, Settings, Feedback, str], None]


def get_athlete_notifier(request: Request) -> AthleteNotifier:
    """Returns the real `notify_athlete_of_coach_reply` unless overridden
    via `app.dependency_overrides[get_athlete_notifier] = ...` (see
    tests/api/test_coach_route.py's `spy_athlete_notifier`)."""
    return notify_athlete_of_coach_reply

# A coach reviewing an athlete's roster wants a "how's this athlete doing
# lately" read, not a fetch of the athlete's entire logged history --
# unbounded, `coach_view_workouts`'s DB read (`store.list_workouts`) and the
# plan-week scan it does to find sessions to match workouts against (for
# quality scoring) both grow forever as an athlete accumulates more
# workouts/weeks. 90 days is expressed in days (not weeks, unlike
# `LOAD_GRAPH_DEFAULT_WEEKS` below) since workouts are logged per-day, but
# lands in the same "recent training, not full history" spirit as that
# constant's ~84-day (12-week) window for this same coach-mode roster view's
# load chart.
COACH_WORKOUTS_DEFAULT_DAYS = 90
COACH_WORKOUTS_MIN_DAYS = 7
COACH_WORKOUTS_MAX_DAYS = 365


def _iso_week_date_range(iso_week: str) -> tuple[date, date]:
    """(monday, sunday) for an ISO week id ("2026-W28") -- same
    `date.fromisocalendar(year, week, weekday)` parse `cli.py`'s
    `--week`-argument handling already uses (see e.g. `_cmd_plan_week`),
    just reused here rather than reinvented, since there's no shared public
    helper for it yet in `engine/swim_coach/`."""
    year_str, week_str = iso_week.split("-W")
    monday = date.fromisocalendar(int(year_str), int(week_str), 1)
    return monday, monday + timedelta(days=6)


@router.get("/api/coach/athletes")
async def list_coached_athletes(
    request: Request, principal: Principal = Depends(require_auth)
) -> list[dict]:
    settings = request.app.state.settings
    store = make_store(settings)

    # No `athlete` param here at all -- derived entirely from
    # `principal.coach_for`. `coach_for` is only ever populated for
    # kind=="athlete" (see Principal.coach_for's docstring): a `service`
    # principal always has an EMPTY coach_for, since it already has
    # unrestricted cross-athlete access and no single coach identity of its
    # own to look grants up by. GET /api/me 403s a service principal
    # because that route is asking "who am I" of a credential with no single
    # identity -- but a 403 here would be needlessly harsh for a route with
    # no request param to get wrong: this route is just "list the athletes
    # I coach," and for a service credential the honest, harmless answer is
    # an empty list, not an error.
    slugs = sorted(principal.coach_for)
    result = []
    for slug in slugs:
        athlete = store.load_athlete(slug)
        result.append({"slug": athlete.slug, "name": athlete.name})
    return result


@router.get("/api/coach/athletes/{slug}/workouts")
async def coach_view_workouts(
    slug: str,
    request: Request,
    days: int = Query(
        COACH_WORKOUTS_DEFAULT_DAYS, ge=COACH_WORKOUTS_MIN_DAYS, le=COACH_WORKOUTS_MAX_DAYS
    ),
    principal: Principal = Depends(require_auth),
) -> list[dict]:
    """Coach-mode roster view's per-athlete workout list, each entry
    annotated with a `quality` (match-to-planned-session score) AND, as of
    the coach-load-visibility fix, `load_au`/`load_tier` -- the same shared
    `app.load_helpers.workout_load_au` computation `routes/workouts.py`'s
    `_attach_load`, `tools.py`'s `get_workouts` tool, and `context.py`'s
    `render_focused_workout` already all use, so the coach roster reports
    the identical number the athlete's own view and the AI coach do rather
    than omitting load entirely (the fourth call site that should have had
    this from the start). Windowed to the trailing `days` days (default
    `COACH_WORKOUTS_DEFAULT_DAYS`) -- both `store.list_workouts` (pushed
    down to a real `WHERE date >= ...` on the DB-backed store; see
    `StoreInterface.list_workouts`'s docstring) and the plan-week scan below
    used only to build match candidates for those workouts. Previously both
    were unbounded full-history reads that grew forever with an athlete's
    tenure on the plan. `hr_max`, however, is estimated from the athlete's
    FULL workout history (same pattern `tools.py`'s `get_workouts` uses) --
    it's one estimate for the whole athlete, and estimating it off a short
    window would make it drift depending on which `days` the coach happened
    to request. Rather than a SECOND unbounded `list_workouts` call just for
    that (which would reintroduce the exact unbounded-growth cost the
    windowing refactor above eliminated), the full list is fetched once and
    the windowed subset is filtered from it in Python -- one store round
    trip does both jobs instead of two."""
    settings = request.app.state.settings
    slug = resolve_coach_athlete(principal, slug)
    store = make_store(settings)
    athlete = store.load_athlete(slug)

    today = date.today()
    since = today - timedelta(days=days)

    all_workouts = store.list_workouts(slug)
    hr_max = estimate_hr_max(all_workouts)
    workouts = [w for w in all_workouts if w.date >= since]
    wellness = store.list_wellness(slug)

    # `list_week_ids` itself stays a full, unfiltered id listing (cheap --
    # ids only, no week bodies) so this can filter in Python BEFORE the
    # actual `load_week` calls, which is where the real per-week cost is
    # paid -- only weeks whose date range overlaps `[since, today]` are
    # loaded, rather than every week ever generated for this athlete.
    sessions: list[Session] = []
    for iso_week in store.list_week_ids(slug):
        week_start, week_end = _iso_week_date_range(iso_week)
        if week_end < since or week_start > today:
            continue
        week = store.load_week(slug, iso_week)
        if week is not None:
            sessions.extend(week.sessions)

    result = []
    for workout in workouts:
        session = match_workout_to_session(workout, sessions)
        quality = workout_quality(workout, session, athlete=athlete)
        load_au, load_tier = workout_load_au(workout, athlete=athlete, hr_max=hr_max, wellness=wellness)
        result.append(
            {
                **workout.model_dump(mode="json"),
                "quality": quality.model_dump(mode="json"),
                "load_au": load_au,
                "load_tier": load_tier,
            }
        )

    # `list_workouts` returns filename order (which happens to sort
    # date-ascending today, since filenames are "{date}-{sport}-{id8}.yaml")
    # -- re-sort explicitly by date descending (most-recent-first) rather
    # than relying on that filename-ordering coincidence.
    result.sort(key=lambda w: w["date"], reverse=True)
    return result


@router.get("/api/coach/athletes/{slug}/load")
async def coach_view_load(
    slug: str,
    request: Request,
    weeks: int = Query(LOAD_GRAPH_DEFAULT_WEEKS, ge=LOAD_GRAPH_MIN_WEEKS, le=LOAD_GRAPH_MAX_WEEKS),
    principal: Principal = Depends(require_auth),
) -> dict:
    """The Banister CTL/ATL/TSB series plus the `wellness_baseline_deviation`
    resting-HR/HRV cross-check for the coach-mode roster view's chart --
    coach-access mirror of `GET /api/plan/load` (`backend/app/routes/plan.py`),
    same minimal graph-shaped response, same `summarize_rollup` call, gated
    via `resolve_coach_athlete` instead of `resolve_athlete`. See
    `routes/plan.py`'s `LOAD_GRAPH_DEFAULT_WEEKS` for why the default window
    is longer than `get_plan_summary`'s.

    No caching added here despite `summarize_rollup` being a real cost: it
    internally calls `store.list_workouts(slug)` with NO `since` bound at
    all (see `context.py`), by design -- CTL/ATL's exponentially-weighted
    averages need full history for a real warm-up, not just this `weeks`
    window (`ctl_atl_tsb_series`'s cold-start docstring), same for
    `wellness_baseline_deviation`'s 28-day chronic baseline. That's the same
    *class* of unbounded-growth cost `coach_view_workouts` had, just
    intentional and deeper inside `summarize_rollup` (also used by
    `get_plan_summary` and per-request chat context) -- fixing it means
    reworking how CTL warm-up gets its history, not a `weeks` bound or a
    cache slapped on top (a cache would only mask the cost between calls,
    not remove it). Out of scope for tonight's routing-layer fix; flagged as
    a follow-up rather than spending a speculative caching layer on it."""
    settings = request.app.state.settings
    slug = resolve_coach_athlete(principal, slug)
    store = make_store(settings)
    rollup = summarize_rollup(store, slug, weeks=weeks)
    return {
        "athlete": slug,
        "weeks": weeks,
        "ctl_atl_tsb": rollup["ctl_atl_tsb"],
        "wellness_baseline_deviation": rollup["wellness_baseline_deviation"],
    }


@router.get("/api/coach/athletes/{slug}/plan")
async def coach_view_plan(
    slug: str, request: Request, principal: Principal = Depends(require_auth)
) -> dict:
    """Coach-access mirror of `GET /api/plan` (`routes/plan.py`) -- same
    exported shape (`slug`/`name`/`athlete`/`events`/`macro`/`weeks`), via
    the same `export_athlete` exporter, gated via `resolve_coach_athlete`
    instead of `resolve_athlete`. Powers the coach roster view's Training
    Plan sub-tab."""
    settings = request.app.state.settings
    slug = resolve_coach_athlete(principal, slug)
    store = make_store(settings)
    try:
        return export_athlete(store, slug)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"no such athlete: {slug}") from exc


_VALID_RESTRICTIONS = {"none", "light_only", "no_training"}
_VALID_HEALTH_SOURCES = {"self_reported", "practitioner"}


@router.get("/api/coach/athletes/{slug}/health-status")
async def coach_view_health_status(
    slug: str, request: Request, principal: Principal = Depends(require_auth)
) -> list[dict]:
    """Coach-mode roster view's per-athlete health-status history --
    everything on file, most-recent-first (see `StoreInterface.
    list_health_status`'s ordering contract), so the coach can see the
    current active status AND the full history (never silently lost, per
    HealthStatus's own "never delete logs" rail). Same
    `resolve_coach_athlete` gating as every other GET route in this file."""
    settings = request.app.state.settings
    slug = resolve_coach_athlete(principal, slug)
    store = make_store(settings)
    entries = store.list_health_status(slug)
    return [e.model_dump(mode="json") for e in entries]


@router.post("/api/coach/athletes/{slug}/health-status")
async def coach_create_health_status(
    slug: str,
    payload: dict[str, Any],
    request: Request,
    principal: Principal = Depends(require_auth),
) -> dict:
    """Lets a coach log a health status directly -- e.g. relaying what a
    physio said -- without going through an AI chat conversation at all.
    Distinct write path from `app/tools.py`'s `record_health_status` tool
    (which the AI calls from chat), but the exact same durable model. This
    endpoint does NOT also create a linked `Feedback`/`needs_human_review`
    row the way the AI tool does -- there is no "make sure a human sees
    this" problem to solve when a human coach is the one directly typing it
    in; that guarantee only matters for the AI-authored path."""
    settings = request.app.state.settings
    slug = resolve_coach_athlete(principal, slug)
    store = make_store(settings)

    description = payload.get("description")
    if not isinstance(description, str) or not description:
        raise HTTPException(status_code=422, detail="description must be a non-empty string")

    restriction = payload.get("restriction")
    if restriction not in _VALID_RESTRICTIONS:
        raise HTTPException(
            status_code=422,
            detail=f"restriction must be one of {sorted(_VALID_RESTRICTIONS)}",
        )

    source = payload.get("source")
    if source not in _VALID_HEALTH_SOURCES:
        raise HTTPException(
            status_code=422,
            detail=f"source must be one of {sorted(_VALID_HEALTH_SOURCES)}",
        )

    expected_review_date = None
    raw_review_date = payload.get("expected_review_date")
    if raw_review_date:
        try:
            expected_review_date = date.fromisoformat(raw_review_date)
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"invalid expected_review_date {raw_review_date!r}"
            ) from exc

    athlete = store.load_athlete(slug)
    entry = HealthStatus(
        id=uuid4(),
        athlete_id=athlete.id,
        reported_at=datetime.now(timezone.utc),
        reported_by="coach",
        source=source,
        description=description,
        restriction=restriction,
        expected_review_date=expected_review_date,
    )
    store.save_health_status(slug, entry)
    return entry.model_dump(mode="json")


@router.patch("/api/coach/athletes/{slug}/health-status/{health_status_id}")
async def coach_resolve_health_status(
    slug: str,
    health_status_id: UUID,
    payload: dict[str, Any],
    request: Request,
    principal: Principal = Depends(require_auth),
) -> dict:
    """Marks one existing health-status entry resolved -- the one in-place
    mutation this durable log allows (see `HealthStatus`'s own docstring);
    everything else about the entry, and every other entry in the athlete's
    history, is untouched. `resolved` must be explicitly `true` in the
    body -- this route exists to close out an active status, not to
    reopen one (there's no product need for that yet, and adding it would
    just be an unused surface)."""
    settings = request.app.state.settings
    slug = resolve_coach_athlete(principal, slug)
    store = make_store(settings)

    resolved = payload.get("resolved")
    if resolved is not True:
        raise HTTPException(status_code=422, detail="resolved must be true")

    # No separate ownership pre-check here -- a real review finding fixed
    # before merge: this used to call `store.list_health_status(slug)` (an
    # unbounded full-history read) purely to look up `health_status_id` and
    # cross-check its `athlete_id`, THEN call `store.update_health_status`
    # below, which re-runs an equivalent slug+id-scoped lookup internally
    # anyway -- two store round trips (two separate DB connections in
    # DbStore) to do what one already does. Both `FileStore.
    # update_health_status` and `DbStore.update_health_status` already
    # scope their own lookup to THIS `slug` (never matching an id that
    # belongs to a different athlete) and already return `None` for a
    # not-found/wrong-athlete id -- the 404 branch below delivers the exact
    # same "coach authorized for `slug` but given a wrong-athlete id learns
    # nothing about whether that id exists elsewhere" guarantee the removed
    # pre-check existed for, with one round trip instead of two.
    updated = store.update_health_status(
        slug, health_status_id, resolved=True, resolved_at=datetime.now(timezone.utc)
    )
    if updated is None:
        raise HTTPException(status_code=404, detail=f"no such health status entry: {health_status_id}")
    return updated.model_dump(mode="json")


@router.get("/api/coach/athletes/{slug}/feedback")
async def coach_view_feedback(
    slug: str, request: Request, principal: Principal = Depends(require_auth)
) -> list[dict]:
    settings = request.app.state.settings
    slug = resolve_coach_athlete(principal, slug)
    store = make_store(settings)

    # Full visibility -- no chat_visibility filtering in Phase 1 (this is
    # the durable Feedback/Q&A log, not live chat).
    entries = store.list_feedback(athlete=slug)
    return [e.model_dump(mode="json") for e in entries]


@router.patch("/api/coach/athletes/{slug}/feedback/{feedback_id}")
async def coach_reply_to_feedback(
    slug: str,
    feedback_id: UUID,
    payload: dict[str, Any],
    request: Request,
    background_tasks: BackgroundTasks,
    principal: Principal = Depends(require_auth),
    notifier: AthleteNotifier = Depends(get_athlete_notifier),
) -> dict:
    settings = request.app.state.settings
    slug = resolve_coach_athlete(principal, slug)
    store = make_store(settings)

    coach_reply = payload.get("coach_reply")
    if not isinstance(coach_reply, str) or not coach_reply:
        raise HTTPException(status_code=422, detail="coach_reply must be a non-empty string")

    existing = store.get_feedback(feedback_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"no such feedback entry: {feedback_id}")

    athlete_row = store.load_athlete(slug)
    # Defense in depth: resolve_coach_athlete already confirmed the coach
    # can act on `slug`, but this confirms the specific feedback row
    # actually belongs to THAT athlete, not some other one the id might
    # collide with. 404, not 403 -- don't leak the existence of another
    # athlete's feedback id to a coach who isn't authorized for it beyond
    # what resolve_coach_athlete already gated.
    if existing.athlete_id != athlete_row.id:
        raise HTTPException(status_code=404, detail=f"no such feedback entry: {feedback_id}")

    # "Reply as coach" fundamentally needs one coach identity -- a coach
    # here is always an athlete-kind principal (coaches in this system are
    # themselves athlete accounts, per CoachGrant's docstring). A service
    # credential has unrestricted cross-athlete access everywhere ELSE, but
    # there's no sensible single "which coach is this" identity to stamp
    # onto coach_athlete_id for it, so this specific write action requires
    # kind=="athlete" and 403s a service principal with a clear message.
    if principal.kind != "athlete" or principal.athlete is None:
        raise HTTPException(
            status_code=403,
            detail="replying as coach requires a single coach identity; a service credential has none",
        )
    coach_athlete_id = store.load_athlete(principal.athlete).id

    updated = store.update_feedback(
        feedback_id,
        coach_reply=coach_reply,
        coach_reply_at=datetime.now(timezone.utc),
        coach_athlete_id=coach_athlete_id,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail=f"no such feedback entry: {feedback_id}")

    # Scheduled AFTER the save succeeds, same "schedule after save, never
    # block the request" discipline routes/feedback.py's own notification
    # trigger uses -- a slow/failing email never affects this response or
    # adds latency to the coach's reply. See app/notify.py's
    # `notify_athlete_of_coach_reply`.
    background_tasks.add_task(notifier, store, settings, updated, slug)

    return updated.model_dump(mode="json")
