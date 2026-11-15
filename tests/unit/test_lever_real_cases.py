"""Real-data cases for the lever read: dominant-block shapes, reference selection, substituted rides."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from swim_coach.lever_read import read_levers
from swim_coach.models import Athlete, MacroWeek, Session, WeekPlan, WorkoutRepeat, WorkoutStep, WorkoutStructure, WorkoutTarget
from swim_coach.progression import ExecutedStimulus, RecoveryResponse, StimulusDose, StimulusRecord
from swim_coach.progression_check import check_week_progression
from swim_coach.progression_levers import SessionShape, shape_from_executed, shape_from_structure
from swim_coach.stimulus import _quality_floor, profile_named
from swim_coach.workout_builders import compile_workout, parse_rung

AID = uuid.uuid4()
ATHLETE = Athlete(id=AID, slug="a", name="A", ftp_watts=278.0, css_pace_s_per_100m=90.0)
AS_OF = date(2026, 11, 15)


def st(role, secs, zone):
    return WorkoutStep(label=role, role=role, duration_kind="time_s", duration_value=secs,
                       target=WorkoutTarget(basis="zone", zone=zone), modality="bike")


def structure(*items):
    return WorkoutStructure(items=[st("warmup", 600, "Z2"), *items, st("cooldown", 300, "Z1")])


def rep(count, *steps):
    return WorkoutRepeat(count=count, steps=list(steps))


SHARPENER = structure(
    rep(2, st("interval", 20, "Z5"), st("recovery", 100, "Z1")),
    st("interval", 300, "Z4"), st("recovery", 180, "Z1"),
    rep(2, st("interval", 15, "Z5"), st("interval", 285, "Z4"), st("recovery", 180, "Z1")),
)
TEN_TEN = structure(
    rep(2, st("interval", 20, "Z5"), st("recovery", 100, "Z1")),
    rep(2, st("interval", 15, "Z5"), st("interval", 585, "Z4"), st("recovery", 300, "Z1")),
)


def test_surge_merges_into_the_rep_and_primers_are_ignored_in_a_planned_structure() -> None:
    shape, note = shape_from_structure(SHARPENER, ATHLETE, "bike")
    assert shape.describe() == "3x5 min/3 min Z4" and note == "ignored 2 primer reps"
    shape, note = shape_from_structure(TEN_TEN, ATHLETE, "bike")
    assert shape.describe() == "2x10 min/5 min Z4" and note == "ignored 2 primer reps"
    assert SessionShape.from_structure(TEN_TEN, ATHLETE, "bike") == shape


VO2_SIZES = [20, 20, 15, 15, 15] + [40] * 12
VO2_GAPS = [60, 120, 150, 150, 300] + [20] * 5 + [320] + [20] * 5


def raw(kind, sizes, gaps, day, *, planned=True, substituted=False, in_band=90.0, completion=100.0, work=None, fade=2.0):
    work = work if work is not None else float(sum(sizes or [600]))
    dose = StimulusDose(sport="bike", kind=kind, confidence="structured", work_s=work, rep_count=len(sizes or []) or None,
                        longest_rep_s=max(sizes) if sizes else None, rep_sizes=sizes, rest_gaps_s=gaps)
    ex = ExecutedStimulus(dose=dose, completion_pct=None if substituted else completion, in_band_pct=None if substituted else in_band,
                          fade_pct=fade, rpe=7, planned=planned, planned_kind="endurance" if substituted else kind,
                          substituted=substituted)
    return StimulusRecord(date=day, sport="bike", kind=kind, planned=planned, executed=ex,
                          recovery=RecoveryResponse(status="recovered"), anchor_value=278.0, anchor_known=True)


def test_executed_dominant_block_with_primers_and_a_snapped_set_rest() -> None:
    shape, note = shape_from_executed(raw("vo2", VO2_SIZES, VO2_GAPS, date(2026, 11, 10), in_band=47.0))
    assert shape.describe() == "2x(6x40 s/20 s)/5.5 min Z5" and note == "ignored 5 primer reps"


def test_adjacent_executed_efforts_merge_and_scattered_work_has_no_shape() -> None:
    merged, _ = shape_from_executed(raw("threshold", [15, 585, 15, 585], [0, 300, 0], date(2026, 11, 5)))
    assert merged.describe() == "2x10 min/5 min Z4"
    assert shape_from_executed(raw("threshold", [300, 600, 300, 900], [60, 60, 60], date(2026, 11, 5)))[0] is None


def test_mixed_floor_is_the_largest_quality_floor() -> None:
    profile = profile_named("bike")
    assert _quality_floor("mixed", profile) == max(profile.min_dose.values())


def ledger():
    d = lambda m, day: date(2026, m, day)  # noqa: E731
    rows = [
        raw("threshold", [600] * 3, [300, 300], d(10, 20), in_band=0.0),
        raw("tempo", None, None, d(10, 21), substituted=True, work=778.0),
        raw("vo2", [40] * 24, ([20] * 5 + [210]) * 3 + [20] * 5, d(10, 24), in_band=26.0),
        raw("tempo", None, None, d(10, 25), substituted=True, work=1200.0),
        raw("threshold", [288, 298, 303], [192, 179], d(10, 27)),
        raw("tempo", None, None, d(10, 28), substituted=True, work=1000.0),
        raw("tempo", None, None, d(11, 4), substituted=True, work=900.0),
        raw("threshold", [596, 596], [302], d(11, 5), completion=96.0),
        raw("threshold", None, None, d(11, 8), substituted=True, work=2568.0),
        raw("vo2", VO2_SIZES, VO2_GAPS, d(11, 10), in_band=47.0, fade=36.0),
        raw("tempo", None, None, d(11, 11), substituted=True, work=1685.0),
        raw("mixed", None, None, d(11, 14), substituted=True, work=489.0),
    ]
    return rows


def reads():
    return {r.kind: r for r in read_levers(ledger(), ATHLETE, as_of=AS_OF)}


def test_threshold_reference_is_the_last_shaped_session_not_the_club_ride() -> None:
    r = reads()["threshold"]
    assert r.last.date == date(2026, 11, 5) and r.verdict == "progress"
    assert r.shape.describe() == "2x10 min/5 min Z4" and r.candidates[0].rung == "2x12 min/5 min Z4"
    assert [a.date for a in r.also_delivered] == [date(2026, 11, 8)] and r.also_delivered[0].label == "planned endurance"
    assert any(x.startswith("Also delivered") and "11-08" in x and "43 min" in x for x in r.reasons)


def test_a_poor_session_keeps_its_shape_and_steps_down() -> None:
    r = reads()["vo2"]
    assert r.verdict == "reduce" and r.last.date == date(2026, 11, 10)
    assert r.shape.describe() == "2x(6x40 s/20 s)/5.5 min Z5" and r.shape_note == "ignored 5 primer reps"
    assert r.candidates and all(c.direction == "down" for c in r.candidates)


def test_a_kind_with_only_club_rides_offers_the_entry_shape() -> None:
    r = reads()["tempo"]
    assert r.verdict == "insufficient_data" and r.shape is None
    assert [(c.direction, c.rung) for c in r.candidates] == [("entry", "2x8 min/4 min Z3")]
    assert any("5 unstructured tempo sessions" in x and "93 min" in x for x in r.reasons)


def test_substituted_only_mixed_never_sets_a_verdict() -> None:
    assert reads()["mixed"].verdict == "insufficient_data"


def planned(text, day, group="bike"):
    c = compile_workout(SessionShape.from_intent(parse_rung(text, group)).to_intent(), ATHLETE)
    return Session(id=uuid.uuid4(), athlete_id=AID, date=day, sport="bike", source="ai_coach", duration_min=c.duration_min,
                   intensity=c.intensity, purpose="t", structured=c.structured)


def week(*sessions):
    return WeekPlan(id=uuid.uuid4(), athlete_id=AID, iso_week="2026-W47", meso_block="b", focus="f", target_volume_m=0,
                    sessions=list(sessions))


def test_guardrail_compares_against_the_chosen_reference() -> None:
    found = check_week_progression(week(planned("3x12 min/4 min Z4", date(2026, 11, 18))), ATHLETE,
                                   reads=list(reads().values()), ledger=ledger())
    f = next(x for x in found if x.id == "progression-multi-lever-bike-threshold")
    assert "last clean 2x10 min/5 min Z4" in f.evidence and "reps +1, rep +2 min, rest -1 min" in f.evidence


def tempo_only(text):
    r = raw("tempo", [480, 480], [240], date(2026, 11, 5))
    r.executed.dose = r.executed.dose.model_copy(update={"rep_sizes": [480, 480]})
    return [r]


def test_zone_jump_fires_only_with_an_unfinished_easier_zone() -> None:
    sess = planned("2x10 min/5 min Z4", date(2026, 11, 18))
    easy = read_levers(tempo_only("x"), ATHLETE, as_of=AS_OF)
    found = check_week_progression(week(sess), ATHLETE, reads=easy, ledger=[])
    assert [(f.id, f.severity) for f in found] == [("progression-zone-jump-bike-threshold", "low")]
    assert check_week_progression(week(sess), ATHLETE, reads=[], ledger=[]) == []
    top = [raw("tempo", [1200] * 3, [240, 240], date(2026, 11, 5))]
    assert check_week_progression(week(sess), ATHLETE, reads=read_levers(top, ATHLETE, as_of=AS_OF), ledger=[]) == []
