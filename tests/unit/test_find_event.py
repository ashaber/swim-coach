"""Tests for swim_coach.event_groups.find_event: UUID-prefix / exact-name lookup."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from swim_coach.event_groups import find_event
from swim_coach.models import Event


def _event(id_: str, name: str) -> Event:
    return Event(id=UUID(id_), athlete_id=UUID(int=1), name=name, event_date=date(2027, 6, 1), priority="A", distance_m=1000)


A = _event("aaaaaaaa-0000-0000-0000-000000000001", "Lake Race")
B = _event("bbbbbbbb-0000-0000-0000-000000000002", "River Swim")


def test_find_event_matches_uuid_prefix_case_insensitively():
    assert find_event([A, B], "  BBBB ") is B


def test_find_event_matches_exact_name_case_insensitively():
    assert find_event([A, B], "lake race") is A


def test_find_event_returns_none_when_unmatched():
    assert find_event([A, B], "nope") is None
