"""check_week advisory: a race-day `warmup` bike session needs a race-pace effort, numeric power
targets and explicit durations (library/38-race-week-sharpener-and-openers.md, "Race-day warm-up")."""

from __future__ import annotations

import uuid
from datetime import date

from swim_coach.models import Athlete, Session, WeekPlan, WorkoutStructure
from swim_coach.plan_check import check_week

ATHLETE_ID = uuid.uuid4()
FTP = 300.0


def _athlete() -> Athlete:
    return Athlete(id=ATHLETE_ID, slug="a", name="A", css_pace_s_per_100m=90.0, ftp_watts=FTP)


def _pw(dur: float | None, lo_pct: float, hi_pct: float, role: str = "interval") -> dict:
    return {
        "kind": "step", "role": role, "label": role, "modality": "bike",
        "duration_kind": "time_s" if dur else "open", "duration_value": dur,
        "target": {"basis": "power_w", "low": lo_pct * FTP, "high": hi_pct * FTP},
    }


def _rpe(dur: float) -> dict:
    return {
        "kind": "step", "role": "interval", "label": "burst", "modality": "bike",
        "duration_kind": "time_s", "duration_value": dur, "target": {"basis": "rpe", "low": 9, "high": 10},
    }


def _rep(count: int, *steps: dict) -> dict:
    return {"kind": "repeat", "count": count, "steps": list(steps)}


def _ids(items: list[dict], kind: str = "warmup", race_min: float | None = 50.0) -> list[str]:
    race = None if race_min is None else Session(
        id=uuid.uuid4(), athlete_id=ATHLETE_ID, date=date(2026, 10, 17), sport="bike", source="ai_coach",
        duration_min=race_min, intensity={"zone": "Z4"}, purpose="Race", kind="race",
    )
    session = Session(
        id=uuid.uuid4(), athlete_id=ATHLETE_ID, date=date(2026, 10, 17), sport="bike", source="ai_coach",
        duration_min=45, intensity={"zone": "Z3"}, purpose="Race warm-up", kind=kind,
        structured=WorkoutStructure.model_validate({"items": items}),
    )
    week = WeekPlan(
        id=uuid.uuid4(), athlete_id=ATHLETE_ID, iso_week="2026-W42", meso_block="race", focus="race",
        target_volume_m=0, sessions=[session] + ([race] if race else []),
    )
    report = check_week(week, None, _athlete(), recent_weeks=[])
    return [f.id.rsplit("-2026", 1)[0] for f in report.findings if f.id.startswith("race-warmup-")]


def _tim() -> list[dict]:
    return [
        _pw(720, 0.5, 0.7, "warmup"),
        _rep(2, _pw(180, 0.91, 0.96), _pw(120, 0.5, 0.54, "recovery")),
        _rep(3, _pw(20, 1.5, 2.0), _pw(100, 0.5, 0.54, "recovery")),
        _pw(300, 0.5, 0.54, "cooldown"),
    ]


def test_tim_style_warmup_is_clean():
    assert _ids(_tim()) == []


def test_openers_only_flags_no_race_pace():
    items = [_pw(600, 0.5, 0.7, "warmup"), _rep(3, _pw(20, 1.5, 2.0), _pw(100, 0.5, 0.54, "recovery"))]
    assert _ids(items) == ["race-warmup-no-race-pace"]


def test_rpe_only_step_is_flagged():
    items = _tim()[:2] + [_rep(3, _rpe(20), _pw(100, 0.5, 0.54, "recovery"))]
    assert _ids(items) == ["race-warmup-rpe-target"]


def test_untimed_step_is_flagged():
    items = _tim() + [_pw(None, 0.5, 0.6, "recovery")]
    assert _ids(items) == ["race-warmup-untimed"]


def test_non_warmup_kind_is_ignored():
    assert _ids([_pw(600, 0.5, 0.7, "warmup")], kind="workout") == []


def test_mid_length_race_gets_only_a_soft_note_without_priming():
    assert _ids([_pw(600, 0.5, 0.7, "warmup")], race_min=120) == ["race-warmup-no-priming"]


def test_mid_length_race_with_short_priming_effort_is_clean():
    items = [_pw(600, 0.5, 0.7, "warmup"), _pw(90, 0.9, 0.95), _pw(120, 0.5, 0.54, "recovery")]
    assert _ids(items, race_min=120) == []


def test_ultra_race_is_never_flagged_for_missing_threshold_work():
    assert _ids([_pw(900, 0.5, 0.6, "warmup")], race_min=480) == []


def test_unknown_race_duration_gets_no_priming_finding():
    assert _ids([_pw(900, 0.5, 0.6, "warmup")], race_min=None) == []


def test_ultra_race_still_flags_rpe_only_steps():
    assert _ids([_rpe(60)], race_min=480) == ["race-warmup-rpe-target"]
