"""Race-week item ticks + the race-day checklist (template and per-race instances).

Everything lives in existing JSONB (`athletes.data` for the template and `race_day_plans`,
`week_plans.data` for `race_week_checklist`) -- no migration. Mutations are absolute-state
("set item X to checked"), never toggles, so the PWA's offline queue can replay them safely.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, ValidationError
from swim_coach.models import Athlete, RaceChecklistTemplate, RaceDayPlan
from swim_coach.race_day import (
    UnknownItemError,
    find_plan,
    new_plan_from_template,
    parse_timeline,
    remove_items,
    reset_timeline,
    set_checked,
    set_timeline,
)

from app.auth import Principal, require_auth, resolve_athlete
from app.logging_config import get_logger
from app.store_factory import make_store

router = APIRouter()
log = get_logger(__name__)

_HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


class ItemStates(BaseModel):
    states: dict[str, bool] = Field(min_length=1)


ItemId = Annotated[str, Field(min_length=1, max_length=64)]


class ChecklistEdit(BaseModel):
    remove: list[ItemId] = Field(min_length=1, max_length=100)


class PlanPatch(BaseModel):
    start_time: str | None = Field(default=None, pattern=_HHMM)
    active_tags: list[str] | None = None
    notes: str | None = None


class WeekItemPatch(BaseModel):
    done: bool


def _load_athlete(request: Request, athlete: str | None, principal: Principal) -> tuple[Any, str, Athlete]:
    slug = resolve_athlete(principal, athlete)
    store = make_store(request.app.state.settings)
    try:
        return store, slug, store.load_athlete(slug)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"no such athlete: {slug}") from exc


def _plan_or_404(profile: Athlete, plan_id: str) -> RaceDayPlan:
    plan = next((p for p in profile.race_day_plans if p.id == plan_id), None)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"no race-day plan {plan_id!r}")
    return plan


@router.get("/api/race-checklist/template")
async def get_template(
    request: Request, athlete: str | None = Query(None), principal: Principal = Depends(require_auth)
) -> dict:
    _, _, profile = _load_athlete(request, athlete, principal)
    template = profile.race_checklist_template or RaceChecklistTemplate()
    return template.model_dump(mode="json")


@router.put("/api/race-checklist/template")
async def put_template(
    payload: dict[str, Any],
    request: Request,
    athlete: str | None = Query(None),
    principal: Principal = Depends(require_auth),
) -> dict:
    store, slug, profile = _load_athlete(request, athlete, principal)
    try:
        template = RaceChecklistTemplate(**payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    profile.race_checklist_template = template
    store.save_athlete(profile)
    log.info("race checklist template saved", athlete=slug, sections=len(template.sections))
    return template.model_dump(mode="json")


@router.get("/api/race-day")
async def get_race_day(
    request: Request,
    date_: date = Query(..., alias="date"),
    session_id: str | None = Query(None),
    name: str = Query(""),
    athlete: str | None = Query(None),
    principal: Principal = Depends(require_auth),
) -> dict:
    """The race-day plan for this race, created from the template on first open."""
    store, slug, profile = _load_athlete(request, athlete, principal)
    plan = find_plan(profile, session_id=session_id, race_date=date_)
    if plan is None:
        if profile.race_checklist_template is None:
            raise HTTPException(status_code=404, detail="no race checklist template yet -- ask the coach to set one up")
        plan = new_plan_from_template(
            profile.race_checklist_template, race_date=date_, name=name[:120], session_id=session_id
        )
        profile.race_day_plans.append(plan)
        store.save_athlete(profile)
        log.info("race-day plan created", athlete=slug, date=str(date_), plan_id=plan.id)
    elif session_id and plan.session_id != session_id:
        plan.session_id = session_id
        store.save_athlete(profile)
    return plan.model_dump(mode="json")


@router.patch("/api/race-day/{plan_id}/items")
async def patch_race_day_items(
    plan_id: str,
    body: ItemStates,
    request: Request,
    athlete: str | None = Query(None),
    principal: Principal = Depends(require_auth),
) -> dict:
    store, slug, profile = _load_athlete(request, athlete, principal)
    plan = _plan_or_404(profile, plan_id)
    set_checked(plan, body.states)
    store.save_athlete(profile)
    log.info("race-day items set", athlete=slug, plan_id=plan_id, n=len(body.states))
    return plan.model_dump(mode="json")


@router.patch("/api/race-day/{plan_id}/checklist")
async def patch_race_day_checklist(
    plan_id: str,
    body: ChecklistEdit,
    request: Request,
    athlete: str | None = Query(None),
    principal: Principal = Depends(require_auth),
) -> dict:
    """Edit THIS race's checklist (never the template): `remove` drops items by id. All-or-nothing:
    an unknown id is a 404 and nothing changes."""
    store, slug, profile = _load_athlete(request, athlete, principal)
    plan = _plan_or_404(profile, plan_id)
    try:
        remove_items(plan, body.remove)
    except UnknownItemError as exc:
        raise HTTPException(status_code=404, detail=f"no checklist item {exc.args[0]!r}") from exc
    store.save_athlete(profile)
    log.info("race-day checklist edited", athlete=slug, plan_id=plan_id, removed=len(body.remove))
    return plan.model_dump(mode="json")


@router.patch("/api/race-day/{plan_id}")
async def patch_race_day(
    plan_id: str,
    payload: dict[str, Any],
    request: Request,
    athlete: str | None = Query(None),
    principal: Principal = Depends(require_auth),
) -> dict:
    store, slug, profile = _load_athlete(request, athlete, principal)
    plan = _plan_or_404(profile, plan_id)
    try:
        patch = PlanPatch(**{k: v for k, v in payload.items() if k in ("start_time", "active_tags", "notes")})
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if "start_time" in payload:
        plan.start_time = patch.start_time
    if patch.active_tags is not None:
        plan.active_tags = [t.strip().lower() for t in patch.active_tags if t.strip()]
    if "notes" in payload:
        plan.notes = patch.notes
    store.save_athlete(profile)
    log.info("race-day plan updated", athlete=slug, plan_id=plan_id, keys=sorted(payload))
    return plan.model_dump(mode="json")


@router.patch("/api/race-day/{plan_id}/timeline")
async def patch_race_day_timeline(
    plan_id: str,
    payload: dict[str, Any],
    request: Request,
    athlete: str | None = Query(None),
    principal: Principal = Depends(require_auth),
) -> dict:
    """Replace this race's timeline (`{timeline: [...]}`) or restore the template's
    (`{reset: true}`). The template itself is never touched. Absolute state, so replay-safe."""
    store, slug, profile = _load_athlete(request, athlete, principal)
    plan = _plan_or_404(profile, plan_id)
    try:
        if payload.get("reset") is True:
            reset_timeline(plan, profile.race_checklist_template or RaceChecklistTemplate())
        elif isinstance(payload.get("timeline"), list):
            set_timeline(plan, parse_timeline(payload["timeline"]))
        else:
            raise ValueError("send `timeline` (a list) or `reset: true`")
    except (ValidationError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    store.save_athlete(profile)
    log.info("race-day timeline updated", athlete=slug, plan_id=plan_id, entries=len(plan.timeline), reset=bool(payload.get("reset")))
    return plan.model_dump(mode="json")


@router.patch("/api/plan/weeks/{iso_week}/race-week-items/{item_id}")
async def patch_race_week_item(
    iso_week: str,
    item_id: str,
    body: WeekItemPatch,
    request: Request,
    athlete: str | None = Query(None),
    principal: Principal = Depends(require_auth),
) -> dict:
    slug = resolve_athlete(principal, athlete)
    store = make_store(request.app.state.settings)
    week = store.load_week(slug, iso_week)
    if week is None:
        raise HTTPException(status_code=404, detail=f"no week plan for {iso_week}")
    item = next((i for i in week.race_week_checklist if i.id == item_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail=f"no race-week item {item_id!r}")
    item.done = body.done
    store.save_week(slug, week)
    log.info("race-week item set", athlete=slug, iso_week=iso_week, item_id=item_id, done=body.done)
    return item.model_dump(mode="json")
