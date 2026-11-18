"""Shared fixtures for the lever-progression tests (not collected as tests)."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from swim_coach.models import Athlete
from swim_coach.progression import ExecutedStimulus, RecoveryResponse, StimulusDose, StimulusRecord
from swim_coach.progression_levers import SessionShape
from swim_coach.workout_builders import parse_rung

AID = uuid.uuid4()
AS_OF = date(2026, 11, 14)

# One scenario row per sport group; every scenario below runs through both.
ROWS = {
    "bike": dict(sport="bike", rung="2x10 min/4 min Z4", top="2x20 min/5 min Z4", then=250.0, now=262.0, fell=238.0,
                 athlete=dict(ftp_watts=262.0), unit="s", key="work_s", rep="longest_rep_s", kind_rung="2x8 min/4 min Z3"),
    "swim": dict(sport="swim_pool", rung="8x100 m/15 s Z4", top="10x400 m/40 s Z4", then=90.0, now=86.0, fell=94.0,
                 athlete=dict(css_pace_s_per_100m=86.0), unit="m", key="work_m", rep="longest_rep_m", kind_rung="4x200 m/20 s Z3"),
}


def shape(group: str, text: str) -> SessionShape:
    return SessionShape.from_intent(parse_rung(text, group))


def athlete_for(row: dict) -> Athlete:
    return Athlete(id=AID, slug="t", name="T", **row["athlete"])


def gaps_of(s: SessionShape) -> list[float]:
    gaps: list[float] = []
    for index in range(s.sets):
        gaps += [s.rest_s] * (s.reps - 1)
        if index < s.sets - 1:
            gaps.append(s.set_rest_s)
    return gaps


def lrec(group: str, text: str, *, days_ago: int = 3, anchor: float | None = None, known: bool = True,
         planned: bool = True, in_band: float = 90.0, rpe: int = 7) -> StimulusRecord:
    row, s = ROWS[group], shape(group, text)
    kind = {"Z3": "tempo", "Z4": "threshold", "Z5": "vo2"}[s.zone]
    sizes = [s.rep_size] * (s.sets * s.reps)
    dose = StimulusDose(sport=row["sport"], kind=kind, confidence="structured", rep_count=len(sizes),
                        rep_sizes=sizes, rest_gaps_s=gaps_of(s), **{row["key"]: s.work(), row["rep"]: s.rep_size})
    ex = ExecutedStimulus(dose=dose, completion_pct=100.0 if planned else None, in_band_pct=in_band, fade_pct=2.0,
                          rpe=rpe, planned=planned)
    return StimulusRecord(date=AS_OF - timedelta(days=days_ago), sport=row["sport"], kind=kind, planned=planned,
                          executed=ex, recovery=RecoveryResponse(status="recovered"),
                          anchor_value=anchor, anchor_known=known)
