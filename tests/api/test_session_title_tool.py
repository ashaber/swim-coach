"""`title` on author_week_plan / merge_week_plan session entries, and the one title used by the
device exports (intervals.icu push name + FIT workout name)."""

from __future__ import annotations

import json
from pathlib import Path

from swim_coach.models import Athlete, Session

from app.garmin_push import build_workout_event
from app.tools import SESSION_ENTRY_SCHEMA, _session_from_add_fields

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "ride_2026_09_29_vo2_40_20.json"


def _athlete() -> Athlete:
    return Athlete(id="8a4969c2-757f-4dc7-8a68-6a773881df42", slug="andrew", name="A", css_pace_s_per_100m=90.0)


def test_schema_asks_the_coach_for_a_title():
    prop = SESSION_ENTRY_SCHEMA["properties"]["title"]
    assert prop["maxLength"] == 40
    assert "ALWAYS" in prop["description"]


def test_session_from_add_fields_carries_title():
    session, error = _session_from_add_fields(
        {"date": "2026-09-29", "sport": "bike", "duration_min": 60, "purpose": "Build — VO2", "title": "3x6 VO2 40/20"},
        athlete=_athlete(),
    )
    assert error is None
    assert session.title == "3x6 VO2 40/20"


def test_overlong_title_is_a_clean_error_not_a_crash():
    session, error = _session_from_add_fields(
        {"date": "2026-09-29", "sport": "bike", "duration_min": 60, "purpose": "x", "title": "y" * 80},
        athlete=_athlete(),
    )
    assert session is None and "title" in error


def test_pushed_event_is_named_from_the_structure_not_the_phase():
    session = Session.model_validate(json.loads(FIXTURE.read_text())["planned_session"])
    event = build_workout_event(session)
    assert event["name"] == "3x6 40/20 VO2"
