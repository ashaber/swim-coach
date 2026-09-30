"""check_week advisory: a hard session's warm-up should start low and end with a primer
before the first hard rep (library/37-plan-authoring-guide.md, "Warm-up and primers")."""

from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path

from swim_coach.models import Athlete, Session, WeekPlan, WorkoutStructure
from swim_coach.plan_check import check_week

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "ride_2026_09_29_vo2_40_20.json"
ATHLETE_ID = uuid.uuid4()


def _athlete() -> Athlete:
    return Athlete(id=ATHLETE_ID, slug="a", name="A", css_pace_s_per_100m=90.0, ftp_watts=276.0)


def _step(role: str, dur: float, zone: str) -> dict:
    return {
        "kind": "step", "role": role, "label": role, "duration_kind": "time_s", "duration_value": dur,
        "modality": "bike", "target": {"basis": "zone", "zone": zone},
    }


def _repeat(count: int, *steps: dict) -> dict:
    return {"kind": "repeat", "count": count, "steps": list(steps)}


def _week(*sessions: Session) -> WeekPlan:
    return WeekPlan(
        id=uuid.uuid4(), athlete_id=ATHLETE_ID, iso_week="2026-W40", meso_block="build", focus="build",
        target_volume_m=0, sessions=list(sessions),
    )


def _session(items: list[dict], *, duration_min: float = 60.0, zone: str = "Z5", sport: str = "bike") -> Session:
    return Session(
        id=uuid.uuid4(), athlete_id=ATHLETE_ID, date=date(2026, 9, 29), sport=sport, source="ai_coach",
        duration_min=duration_min, intensity={"zone": zone}, purpose="Build — VO2",
        structured=WorkoutStructure.model_validate({"items": items}),
    )


def _ids(session: Session) -> list[str]:
    report = check_week(_week(session), None, _athlete(), recent_weeks=[])
    return [f.id for f in report.findings if f.id.startswith(("warmup-", "primer-"))]


def _rounds():
    return _repeat(3, _repeat(6, _step("interval", 40, "Z5"), _step("recovery", 20, "Z1")), _step("recovery", 240, "Z1"))


def test_real_session_flat_z2_warmup_no_primer_gets_both_findings():
    fx = json.loads(FIXTURE.read_text())["planned_session"]
    fx["athlete_id"] = str(ATHLETE_ID)
    ids = _ids(Session.model_validate(fx))
    assert any(i.startswith("warmup-start-") for i in ids)
    assert any(i.startswith("primer-missing-") for i in ids)


def test_low_start_ramp_and_primer_is_clean():
    session = _session([
        _step("warmup", 300, "Z1"), _step("warmup", 300, "Z2"), _step("warmup", 300, "Z3"),
        _step("steady", 20, "Z5"), _step("recovery", 60, "Z1"), _step("steady", 20, "Z5"), _step("recovery", 120, "Z1"),
        _rounds(), _step("cooldown", 600, "Z1"),
    ])
    assert _ids(session) == []


def test_findings_carry_the_fix():
    session = _session([_step("warmup", 900, "Z3"), _rounds()])
    report = check_week(_week(session), None, _athlete(), recent_weeks=[])
    found = {f.id.split("-2026")[0]: f for f in report.findings if f.id.startswith(("warmup-", "primer-"))}
    assert found["warmup-start"].severity == "medium"  # Z3 start is well above Z1
    assert "Z1" in found["warmup-start"].fix
    assert "20" in found["primer-missing"].fix


def test_short_session_gets_a_compressed_expectation():
    # 40 min: a Z2 opener is acceptable; a missing primer is still flagged, but only low.
    session = _session([_step("warmup", 300, "Z2"), _repeat(6, _step("interval", 40, "Z5"), _step("recovery", 20, "Z1"))], duration_min=40.0)
    report = check_week(_week(session), None, _athlete(), recent_weeks=[])
    warm = [f for f in report.findings if f.id.startswith("warmup-")]
    primer = [f for f in report.findings if f.id.startswith("primer-")]
    assert warm == []
    assert [f.severity for f in primer] == ["low"]


def test_easy_session_is_not_checked():
    session = _session([_step("steady", 3600, "Z2")], zone="Z2")
    assert _ids(session) == []


def test_session_without_structured_is_not_checked():
    session = Session(
        id=uuid.uuid4(), athlete_id=ATHLETE_ID, date=date(2026, 9, 29), sport="bike", source="ai_coach",
        duration_min=60, intensity={"zone": "Z5"}, purpose="VO2",
    )
    assert _ids(session) == []
