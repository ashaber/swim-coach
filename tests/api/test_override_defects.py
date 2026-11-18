"""Coach-reported tool defects (IDEA 024) that blocked or silently corrupted a
week: #3 hard validation errors, #4 a relabelled session whose zone tag never
changed. Policy (Andrew, 2026-09-21): flag the risk, never block, never corrupt."""

from __future__ import annotations

import uuid
from datetime import date

from swim_coach.models import Athlete, Session, WeekPlan
from swim_coach.store import FileStore

from app.tools import _apply_session_overrides, build_tool_handlers

D = date(2026, 9, 26)


def _week(sport="bike", zone="Z2", purpose="endurance ride (Z2) — aerobic base"):
    a = Athlete(id=uuid.uuid4(), slug="x", name="X", css_pace_s_per_100m=95.0, zones=None, constraints={},
                pool_schedule=[], sports=["bike"])
    s = Session(id=uuid.uuid4(), athlete_id=a.id, date=D, sport=sport, source="ai_coach", duration_min=90.0,
                distance_m=None, intensity={"zone": zone}, purpose=purpose, status="planned")
    w = WeekPlan(id=uuid.uuid4(), athlete_id=a.id, iso_week="2026-W39", meso_block="build", focus="x",
                 target_volume_m=90, sessions=[s], adaptation_rationale=None, draft=False)
    return a, w


def test_purpose_says_intervals_but_zone_tag_unchanged_is_flagged_not_blocked_or_rewritten() -> None:
    a, w = _week()
    err, notes = _apply_session_overrides(w, [{"date": D.isoformat(), "sport": "bike",
                                               "purpose": "over/unders, second interval day"}], a)
    assert err is None
    assert w.sessions[0].purpose == "over/unders, second interval day"
    assert w.sessions[0].intensity == {"zone": "Z2"}  # never silently rewritten
    assert any("zone tag" in n and "intensity" in n for n in notes)


def test_modify_mode_can_set_the_zone_so_the_session_is_what_its_label_says() -> None:
    a, w = _week()
    err, notes = _apply_session_overrides(
        w, [{"date": D.isoformat(), "sport": "bike", "purpose": "over/unders", "intensity": {"zone": "z4"}}], a
    )
    assert err is None and notes == []
    assert w.sessions[0].intensity == {"zone": "Z4"}


def test_intensity_alone_is_a_valid_override() -> None:
    a, w = _week()
    err, _ = _apply_session_overrides(w, [{"date": D.isoformat(), "sport": "bike", "intensity": {"zone": "Z3"}}], a)
    assert err is None and w.sessions[0].intensity["zone"] == "Z3"


def test_invalid_intensity_is_a_clear_error() -> None:
    a, w = _week()
    err, _ = _apply_session_overrides(w, [{"date": D.isoformat(), "sport": "bike", "intensity": {"zone": "hard"}}], a)
    assert err and "intensity" in err
    assert w.sessions[0].intensity == {"zone": "Z2"}


def test_a_hard_purpose_on_an_already_hard_session_is_not_flagged() -> None:
    a, w = _week(zone="Z4", purpose="threshold")
    _, notes = _apply_session_overrides(w, [{"date": D.isoformat(), "sport": "bike", "purpose": "over/unders"}], a)
    assert notes == []


def test_an_easy_purpose_is_not_flagged() -> None:
    a, w = _week()
    _, notes = _apply_session_overrides(w, [{"date": D.isoformat(), "sport": "bike", "purpose": "easy spin with Sam"}], a)
    assert notes == []


def test_structure_without_distance_is_not_required_for_non_swim_sessions() -> None:
    a, w = _week()
    err, notes = _apply_session_overrides(
        w, [{"date": D.isoformat(), "sport": "bike", "structure": "10 min warm-up, 3 x 8 min over/unders, 10 min easy"}], a
    )
    assert err is None and notes == []

