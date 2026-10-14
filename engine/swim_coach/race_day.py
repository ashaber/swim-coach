"""Race-day checklist helpers: instance creation from the template, weather-tag filtering, and
the clock-time timeline. Pure functions over `RaceChecklistTemplate` / `RaceDayPlan` -- the
backend routes and coach tools call these; the PWA mirrors `timeline_clock` in
web/src/raceDay.js."""

from __future__ import annotations

import uuid
from datetime import date

from swim_coach.models import (
    Athlete,
    ChecklistItem,
    RaceChecklistTemplate,
    RaceDayPlan,
    TimelineEntry,
)


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
    """Timeline entries with a computed `time` ("HH:MM"), `abs_min` (minutes from race-day
    midnight; None until a start_time is set) and `day_shift` (-1 for the evening before, or a
    race-day offset landing before midnight).

    Rules on race-day entries: `offset_min` from the start, then `not_later_than` /
    `not_earlier_than` clamp the clock time into the athlete's normal day; `only_if_start_after`
    / `only_if_start_before` (strict) drop the entry for starts outside the window -- and with no
    start_time conditional entries are hidden. Sorted by clock time (eve entries first)."""
    start = _hhmm_to_min(plan.start_time) if plan.start_time else None
    out = [c for c in (_clock_entry(e, start) for e in plan.timeline) if c is not None]
    timed = sorted((o for o in out if o["abs_min"] is not None), key=lambda o: o["abs_min"])
    untimed = sorted((o for o in out if o["abs_min"] is None), key=lambda o: o["offset_min"] or 0)
    return timed + untimed


def _hhmm_to_min(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _visible_for_start(e: TimelineEntry, start: int | None) -> bool:
    if e.day == "eve" or not (e.only_if_start_after or e.only_if_start_before):
        return True
    if start is None:
        return False
    if e.only_if_start_after and not start > _hhmm_to_min(e.only_if_start_after):
        return False
    return not (e.only_if_start_before and not start < _hhmm_to_min(e.only_if_start_before))


def _clock_entry(e: TimelineEntry, start: int | None) -> dict | None:
    if not _visible_for_start(e, start):
        return None
    base = {"id": e.id, "label": e.label, "day": e.day, "is_start": e.is_start, "offset_min": e.offset_min}
    if e.day == "eve":
        abs_min = -1440 + _hhmm_to_min(e.at or "00:00")
        return {**base, "time": e.at, "day_shift": -1, "abs_min": abs_min}
    if start is None:
        return {**base, "time": None, "day_shift": 0, "abs_min": None}
    abs_min = start + (e.offset_min or 0)
    if e.not_later_than:
        abs_min = min(abs_min, _hhmm_to_min(e.not_later_than))
    if e.not_earlier_than:
        abs_min = max(abs_min, _hhmm_to_min(e.not_earlier_than))
    return {**base, "time": f"{abs_min % 1440 // 60:02d}:{abs_min % 60:02d}", "day_shift": abs_min // 1440, "abs_min": abs_min}
