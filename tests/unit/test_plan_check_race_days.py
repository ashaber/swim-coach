"""check_week: race-day awareness from the athlete's events, opener/warmup exemptions, finding category."""

from __future__ import annotations

import uuid
from datetime import date

from swim_coach.models import Athlete, Event, PlanCheckFinding, Session, WeekPlan, WorkoutStructure
from swim_coach.plan_check import check_week

ATHLETE_ID = uuid.uuid4()
SAT = date(2026, 10, 31)
SUN = date(2026, 11, 1)


def _athlete() -> Athlete:
    return Athlete(id=ATHLETE_ID, slug="a", name="A", css_pace_s_per_100m=90.0, ftp_watts=276.0)


def _event(d: date, group_id: uuid.UUID | None = None) -> Event:
    return Event(
        id=uuid.uuid4(), athlete_id=ATHLETE_ID, name=f"CX {d}", event_date=d, primary_sport="bike", priority="A", target_metric="duration_min", target_value=45.0,
        group_id=group_id, group_type="double_header" if group_id else None,
    )


def _bike(d: date, zone: str = "Z5", kind: str | None = None, structured: dict | None = None) -> Session:
    return Session(
        id=uuid.uuid4(), athlete_id=ATHLETE_ID, date=d, sport="bike", source="ai_coach",
        duration_min=45.0, intensity={"zone": zone}, purpose="x", kind=kind,
        structured=WorkoutStructure.model_validate(structured) if structured else None,
    )


def _week(*sessions: Session) -> WeekPlan:
    return WeekPlan(
        id=uuid.uuid4(), athlete_id=ATHLETE_ID, iso_week="2026-W44", meso_block="race", focus="race",
        target_volume_m=0, sessions=list(sessions),
    )


def _findings(week: WeekPlan, events: list[Event] | None = None, recent: list[WeekPlan] | None = None):
    return check_week(week, None, _athlete(), recent_weeks=recent or [], events=events).findings


def _is_b2b(f: PlanCheckFinding) -> bool:
    return f.id.startswith("week-realism") and "back-to-back" in f.evidence


def test_grouped_untagged_race_days_no_back_to_back():
    gid = uuid.uuid4()
    week = _week(_bike(SAT), _bike(SUN))
    assert any(_is_b2b(f) for f in _findings(week))  # baseline: no events -> unchanged behaviour
    out = _findings(week, [_event(SAT, gid), _event(SUN, gid)])
    assert not any(_is_b2b(f) for f in out)


def test_race_dates_excluded_from_hard_day_count_and_polarization():
    week = _week(_bike(SAT), _bike(SUN))
    ids = [f.id for f in _findings(week, [_event(SAT), _event(SUN)])]
    assert "polarization" not in ids


def test_untagged_single_race_gets_untagged_finding_authoring():
    out = _findings(_week(_bike(SAT)), [_event(SAT)])
    f = next(f for f in out if f.id == f"race-day-untagged-{SAT.isoformat()}")
    assert f.severity == "low" and f.category == "authoring"
    assert "kind" in f.fix


def test_tagged_race_day_has_no_untagged_finding():
    out = _findings(_week(_bike(SAT, kind="race")), [_event(SAT)])
    assert not any(f.id.startswith("race-day-untagged") for f in out)


def test_no_events_no_untagged_finding():
    assert not any(f.id.startswith("race-day-untagged") for f in _findings(_week(_bike(SAT))))


_HARD_NO_PRIMER = {"items": [
    {"kind": "step", "role": "warmup", "label": "wu", "duration_kind": "time_s", "duration_value": 600,
     "modality": "bike", "target": {"basis": "zone", "zone": "Z4"}},
    {"kind": "repeat", "count": 4, "steps": [
        {"kind": "step", "role": "interval", "label": "i", "duration_kind": "time_s", "duration_value": 240,
         "modality": "bike", "target": {"basis": "zone", "zone": "Z5"}},
        {"kind": "step", "role": "recovery", "label": "r", "duration_kind": "time_s", "duration_value": 120,
         "modality": "bike", "target": {"basis": "zone", "zone": "Z1"}},
    ]},
]}


def test_opener_and_warmup_exempt_from_primer_checks():
    for kind in ("opener", "warmup"):
        out = _findings(_week(_bike(date(2026, 10, 30), kind=kind, structured=_HARD_NO_PRIMER)))
        assert not [f for f in out if f.id.startswith(("primer-missing", "warmup-start"))], kind


def test_plain_workout_still_gets_primer_findings_as_authoring():
    out = _findings(_week(_bike(date(2026, 10, 30), kind="workout", structured=_HARD_NO_PRIMER)))
    mech = [f for f in out if f.id.startswith(("primer-missing", "warmup-start"))]
    assert mech and all(f.category == "authoring" for f in mech)


def test_opener_warmup_not_hard_for_polarization():
    week = _week(
        _bike(date(2026, 10, 30), zone="Z4", kind="opener"),
        _bike(date(2026, 10, 31), zone="Z4", kind="warmup"),
    )
    assert "polarization" not in [f.id for f in _findings(week)]


def test_default_category_is_judgment():
    f = PlanCheckFinding(id="x", severity="low", evidence="e", consequence="c", fix="f")
    assert f.category == "judgment"


def test_confirm_and_realism_findings_stay_judgment():
    prev = _week(_bike(date(2026, 10, 24), zone="Z2"))
    prev.target_volume_m = 1000
    cur = _week(_bike(date(2026, 10, 27), zone="Z4"), _bike(date(2026, 10, 28), zone="Z4"))
    cur.target_volume_m = 5000
    out = _findings(cur, recent=[prev])
    assert any(f.id.startswith("confirm-") for f in out)
    assert any(_is_b2b(f) for f in out)
    for f in out:
        if f.id.startswith(("confirm-", "week-", "polarization")):
            assert f.category == "judgment", f.id


def test_realism_hard_day_count_excludes_opener_and_warmup():
    from swim_coach.plan import evaluate_week_realism

    days = [date(2026, 10, 26 + i) for i in range(4)]
    sessions = [_bike(days[0], zone="Z4"), _bike(days[1], zone="Z4", kind="opener"),
                _bike(days[2], zone="Z4", kind="warmup"), _bike(days[3], zone="Z4", kind="opener")]
    assert not any("hard bike days" in w for w in evaluate_week_realism(sessions))
