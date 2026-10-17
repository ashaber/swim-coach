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
    ChecklistSection,
    RaceChecklistTemplate,
    RaceDayPlan,
    TimelineEntry,
    validate_timeline_refs,
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


def parse_timeline(raw: list[dict]) -> list[TimelineEntry]:
    """Validate a full replacement timeline: each entry valid, ids unique, exactly one start."""
    entries = [TimelineEntry(**e) for e in raw]
    validate_timeline_refs(entries)
    if sum(1 for e in entries if e.is_start) != 1:
        raise ValueError("timeline needs exactly one start entry (is_start)")
    return entries


def set_timeline(plan: RaceDayPlan, entries: list[TimelineEntry]) -> None:
    """Replace this race's timeline (the template is untouched); marks it hand-edited."""
    plan.timeline = entries
    plan.timeline_edited = True


def reset_timeline(plan: RaceDayPlan, template: RaceChecklistTemplate) -> None:
    plan.timeline = [t.model_copy(deep=True) for t in template.timeline]
    plan.timeline_edited = False


def timeline_clock(plan: RaceDayPlan) -> list[dict]:
    """Timeline entries with a computed `time` ("HH:MM"), `abs_min` (minutes from race-day
    midnight; None until a start_time is set) and `day_shift` (-1 for the evening before, or a
    race-day offset landing before midnight).

    Rules on race-day entries: `offset_min` from the start, or `after` another entry's computed
    time (+`after_min`); then `not_later_than` / `not_earlier_than` clamp the clock time into
    the athlete's normal day; `only_if_start_after` / `only_if_start_before` (strict) drop the
    entry for starts outside the window (conditional entries are hidden with no start_time).
    An entry that follows a dropped entry is dropped too. Sorted by clock time (eve first)."""
    start = _hhmm_to_min(plan.start_time) if plan.start_time else None
    by_id = {e.id: e for e in plan.timeline}
    out = [c for c in (_clock_entry(e, start, by_id) for e in plan.timeline) if c is not None]
    timed = sorted((o for o in out if o["abs_min"] is not None), key=lambda o: o["abs_min"])
    untimed = sorted((o for o in out if o["abs_min"] is None), key=lambda o: o["offset_min"] or 0)
    return timed + untimed


def _hhmm_to_min(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _visible_for_start(e: TimelineEntry, start: int | None, by_id: dict[str, TimelineEntry]) -> bool:
    if e.day == "eve":
        return True
    if e.after and not _visible_for_start(by_id[e.after], start, by_id):
        return False
    if not (e.only_if_start_after or e.only_if_start_before):
        return True
    if start is None:
        return False
    if e.only_if_start_after and not start > _hhmm_to_min(e.only_if_start_after):
        return False
    return not (e.only_if_start_before and not start < _hhmm_to_min(e.only_if_start_before))


def _abs_minute(e: TimelineEntry, start: int, by_id: dict[str, TimelineEntry]) -> int:
    if e.after:
        abs_min = _abs_minute(by_id[e.after], start, by_id) + e.after_min
    else:
        abs_min = start + (e.offset_min or 0)
    if e.not_later_than:
        abs_min = min(abs_min, _hhmm_to_min(e.not_later_than))
    if e.not_earlier_than:
        abs_min = max(abs_min, _hhmm_to_min(e.not_earlier_than))
    return abs_min


def _clock_entry(e: TimelineEntry, start: int | None, by_id: dict[str, TimelineEntry]) -> dict | None:
    if not _visible_for_start(e, start, by_id):
        return None
    base = {
        "id": e.id, "label": e.label, "day": e.day, "is_start": e.is_start,
        "offset_min": e.offset_min, "after": e.after, "after_min": e.after_min,
    }
    if e.day == "eve":
        abs_min = -1440 + _hhmm_to_min(e.at or "00:00")
        return {**base, "time": e.at, "day_shift": -1, "abs_min": abs_min}
    if start is None:
        return {**base, "time": None, "day_shift": 0, "abs_min": None}
    abs_min = _abs_minute(e, start, by_id)
    return {**base, "time": f"{abs_min % 1440 // 60:02d}:{abs_min % 60:02d}", "day_shift": abs_min // 1440, "abs_min": abs_min}


MISC_SECTION_ID = "misc-added"
MISC_SECTION_TITLE = "Misc"
MAX_ITEM_TEXT = 200


class UnknownItemError(KeyError):
    """A checklist edit named an item id that is not on this race-day plan."""


def remove_items(plan: RaceDayPlan, item_ids: list[str]) -> None:
    """Drop items from THIS plan only (the template is untouched) and un-check them. Every id is
    validated before anything changes, so a bad id leaves the plan as it was."""
    known = {i.id for s in plan.sections for i in s.items}
    missing = [i for i in item_ids if i not in known]
    if missing:
        raise UnknownItemError(missing[0])
    gone = set(item_ids)
    for section in plan.sections:
        section.items = [i for i in section.items if i.id not in gone]
    plan.checked = [c for c in plan.checked if c not in gone]


def add_item(plan: RaceDayPlan, text: str, item_id: str | None = None) -> ChecklistItem:
    """Append a free-text item to this plan's "Misc" section (created at the top on first use).
    A supplied id that already exists is a no-op returning the existing item, so an offline
    queue replaying the same add cannot duplicate it."""
    clean = text.strip()
    if not clean or len(clean) > MAX_ITEM_TEXT:
        raise ValueError(f"item text must be 1-{MAX_ITEM_TEXT} characters")
    new_id = item_id or uuid.uuid4().hex[:12]
    for section in plan.sections:
        for existing in section.items:
            if existing.id == new_id:
                return existing
    misc = next((s for s in plan.sections if s.id == MISC_SECTION_ID), None)
    if misc is None:
        misc = ChecklistSection(id=MISC_SECTION_ID, title=MISC_SECTION_TITLE)
        plan.sections.insert(0, misc)
    item = ChecklistItem(id=new_id, text=clean)
    misc.items.append(item)
    return item
