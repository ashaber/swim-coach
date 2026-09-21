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


def test_replace_week_plan_keeps_the_generators_own_warnings(athletes_dir) -> None:
    # A template week under a swim macro carries a 'volume held' warning from the
    # generator; the realism re-run in replace_week_plan must not throw it away.
    from datetime import timedelta
    from swim_coach.models import Event
    from swim_coach.plan import scaffold_macro

    store = FileStore(base_dir=athletes_dir)
    h = build_tool_handlers(store, slug="renee", expert_mode=False)
    h["update_athlete_profile"]({"sports": ["bike", "swim_pool"], "ftp_watts": 250.0})
    athlete = store.load_athlete("renee")
    start = date.today() - timedelta(days=date.today().weekday()) - timedelta(weeks=1)
    event = Event(id=uuid.uuid4(), athlete_id=athlete.id, name="Halloween swim", event_date=start + timedelta(weeks=24),
                  distance_m=20000, water_temp_c=18.0, wetsuit=False, priority="A")
    macro = scaffold_macro(athlete, event, start, current_weekly_volume_m=8000, peak_weekly_volume_m=20000)
    store.save_events("renee", [event])
    store.save_macro("renee", macro)
    h["set_weekly_template"]({"template": {"tue": [{"kind": "bike", "role": "hard"}]}, "confirm": True})
    ws = macro.blocks[0].start_date + timedelta(weeks=1)
    y, w, _ = ws.isocalendar()

    draft = h["replace_week_plan"]({"iso_week": f"{y}-W{w:02d}"})

    assert any("held" in x.lower() for x in draft["planning_warnings"])
