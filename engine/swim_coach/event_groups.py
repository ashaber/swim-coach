"""Event groups: several races on the same or consecutive days planned as ONE target.

Examples: a road stage race (road race + criterium), a cyclocross double header, Renee's multi-day
Greece swim. Taper / macro / race-week planning targets the GROUP's peak race (default the
earliest, coach override via `Event.group_peak`), and the first..last span is race days. Members
are ordinary `Event`s (each keeps its own date, each tags as a race); the group is derived from
`Event.group_id` so storage stays in the events JSONB (no migration).

Coach judgment: a taper is built toward one peak, so N races within a few days are one target
(library/03 load monitoring gives the CTL/ATL/TSB taper mechanics; this module only chooses the
date they aim at).
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID, uuid4

from swim_coach.models import Event, EventGroup


def _members(events: list[Event], group_id: UUID) -> list[Event]:
    return sorted((e for e in events if e.group_id == group_id), key=lambda e: (e.event_date, str(e.id)))


def group_of(event: Event, events: list[Event]) -> EventGroup | None:
    """The group `event` belongs to (None when ungrouped)."""
    if event.group_id is None:
        return None
    members = _members(events, event.group_id)
    if not members:
        return None
    peak = next((m for m in members if m.group_peak), members[0])
    return EventGroup(
        id=event.group_id,
        athlete_id=event.athlete_id,
        name=peak.group_name or peak.name,
        group_type=peak.group_type or "stage_race",
        races=[m.id for m in members],
        peak_event_id=peak.id,
        priority=peak.priority,
        first_date=members[0].event_date,
        last_date=members[-1].event_date,
    )


def groups(events: list[Event]) -> list[EventGroup]:
    """Every group in `events`, ordered by first race date."""
    seen: dict[UUID, EventGroup] = {}
    for e in events:
        if e.group_id is not None and e.group_id not in seen:
            g = group_of(e, events)
            if g is not None:
                seen[e.group_id] = g
    return sorted(seen.values(), key=lambda g: g.first_date)


def effective_target(event: Event, events: list[Event]) -> Event:
    """The Event taper/macro/race-week planning aims at: the group's peak race when `event` is
    grouped, else `event` itself."""
    g = group_of(event, events)
    if g is None or g.peak_event_id == event.id:
        return event
    return next(e for e in events if e.id == g.peak_event_id)


def planning_targets(events: list[Event]) -> list[Event]:
    """`events` with each group collapsed to its single peak race (a group is ONE A/B/C target)."""
    return [e for e in events if effective_target(e, events).id == e.id]


def race_dates(events: list[Event]) -> set[date]:
    """Every race day of the active events: member dates plus every day inside a group's span."""
    active = [e for e in events if e.active]
    days = {e.event_date for e in active}
    for g in groups(active):
        days.update(g.first_date + timedelta(days=i) for i in range((g.last_date - g.first_date).days + 1))
    return days


def peak_covering(day: date, events: list[Event]) -> Event | None:
    """The peak race of an active group whose span covers `day` (None when no group does)."""
    active = [e for e in events if e.active]
    for g in groups(active):
        if g.first_date <= day <= g.last_date:
            return next(e for e in active if e.id == g.peak_event_id)
    return None


_UNGROUPED = {"group_id": None, "group_name": None, "group_type": None, "group_peak": False}


def set_group(
    events: list[Event],
    *,
    name: str,
    group_type: str,
    member_ids: list[UUID],
    peak_event_id: UUID | None = None,
    group_id: UUID | None = None,
) -> tuple[UUID, list[Event]]:
    """Return `(group_id, events)` with `member_ids` tagged as one group (a new group when
    `group_id` is None; otherwise that group is REPLACED: previous members not listed are
    ungrouped). `peak_event_id` None leaves the default (earliest race). Pure: returns copies."""
    if len(member_ids) < 2:
        raise ValueError("a group needs at least 2 member events")
    if len(set(member_ids)) != len(member_ids):
        raise ValueError("duplicate member events")
    if peak_event_id is not None and peak_event_id not in member_ids:
        raise ValueError("peak_event_id must be one of the members")
    by_id = {e.id: e for e in events}
    missing = [m for m in member_ids if m not in by_id]
    if missing:
        raise ValueError(f"unknown event ids: {[str(m) for m in missing]}")
    gid = group_id or uuid4()
    for m in member_ids:
        other = by_id[m].group_id
        if other is not None and other != gid:
            raise ValueError(f"{by_id[m].name!r} already belongs to another group; disband it first")
    out: list[Event] = []
    for e in events:
        if e.id in member_ids:
            tag = {"group_id": gid, "group_name": name, "group_type": group_type, "group_peak": e.id == peak_event_id}
            out.append(e.model_copy(update=tag))
        elif e.group_id == gid:
            out.append(e.model_copy(update=_UNGROUPED))
        else:
            out.append(e)
    return gid, out


def disband_group(events: list[Event], group_id: UUID) -> list[Event]:
    """`events` with every member of `group_id` ungrouped (the Events themselves are kept)."""
    return [e.model_copy(update=_UNGROUPED) if e.group_id == group_id else e for e in events]
