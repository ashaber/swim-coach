"""Race-day checklist helpers: instance creation from the template, weather-tag filtering, and
the clock-time timeline. Pure functions over `RaceChecklistTemplate` / `RaceDayPlan` -- the
backend routes and coach tools call these; the PWA mirrors `timeline_clock` in
web/src/raceDay.js."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from swim_coach.models import (
    Athlete,
    ChecklistItem,
    RaceChecklistTemplate,
    RaceDayPlan,
    TimelineEntry,
)

_BASE_DAY = date(2000, 1, 2)


def new_plan_from_template(
    template: RaceChecklistTemplate,
    *,
    race_date: date,
    name: str = "",
    session_id: str | None = None,
    start_time: str | None = None,
) -> RaceDayPlan:
    """A fresh instance: deep copies of the template's sections/timeline and the template's
    `default_checked` items pre-checked."""
    sections = [s.model_copy(deep=True) for s in template.sections]
    return RaceDayPlan(
        id=uuid.uuid4().hex[:12],
        date=race_date,
        name=name,
        session_id=session_id,
        start_time=start_time,
        checked=[i.id for s in sections for i in s.items if i.default_checked],
        sections=sections,
        timeline=[t.model_copy(deep=True) for t in template.timeline],
    )


def find_plan(athlete: Athlete, *, session_id: str | None, race_date: date) -> RaceDayPlan | None:
    """Match by race session id first, then by date (a replaced week gives sessions new ids)."""
    if session_id:
        for p in athlete.race_day_plans:
            if p.session_id == session_id:
                return p
    for p in athlete.race_day_plans:
        if p.date == race_date:
            return p
    return None


def item_visible(item: ChecklistItem, active_tags: list[str]) -> bool:
    return not item.tags or any(t in active_tags for t in item.tags)


def visible_items(plan: RaceDayPlan) -> list[ChecklistItem]:
    return [i for s in plan.sections for i in s.items if item_visible(i, plan.active_tags)]


def set_checked(plan: RaceDayPlan, states: dict[str, bool]) -> None:
    """Idempotent absolute set (so an offline queue can replay safely); unknown ids are ignored."""
    known = {i.id for s in plan.sections for i in s.items}
    current = [c for c in plan.checked if c in known]
    for item_id, on in states.items():
        if item_id not in known:
            continue
        if on and item_id not in current:
            current.append(item_id)
        if not on and item_id in current:
            current.remove(item_id)
    plan.checked = current


def timeline_clock(plan: RaceDayPlan) -> list[dict]:
    """Timeline entries with a computed `time` ("HH:MM") and `day_shift` (-1 for the evening
    before, or a race-day offset landing before midnight). Race entries have `time=None` until
    a start_time is set. Order: eve by clock, then race by offset."""
    out = [_clock_entry(e, plan.start_time) for e in plan.timeline]
    eve = sorted((o for o in out if o["day"] == "eve"), key=lambda o: o["time"])
    race = sorted((o for o in out if o["day"] == "race"), key=lambda o: o["offset_min"])
    return eve + race


def _clock_entry(e: TimelineEntry, start_time: str | None) -> dict:
    base = {"id": e.id, "label": e.label, "day": e.day, "is_start": e.is_start, "offset_min": e.offset_min}
    if e.day == "eve":
        return {**base, "time": e.at, "day_shift": -1}
    if start_time is None:
        return {**base, "time": None, "day_shift": 0}
    start = datetime.combine(_BASE_DAY, datetime.strptime(start_time, "%H:%M").time())
    at = start + timedelta(minutes=e.offset_min or 0)
    return {**base, "time": at.strftime("%H:%M"), "day_shift": (at.date() - _BASE_DAY).days}
