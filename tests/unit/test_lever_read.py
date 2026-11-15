"""Tests for the threshold anchor on the ledger, the rebase, and `lever_read.read_levers`."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from swim_coach.lever_read import read_levers
from swim_coach.models import (
    Athlete,
    IntervalEffort,
    ThresholdRecord,
    Workout,
    WorkoutAnalytics,
    WorkoutIntervals,
)
from swim_coach.progression import (
    ExecutedStimulus,
    RecoveryResponse,
    StimulusDose,
    StimulusRecord,
    build_ledger,
    read_progression,
)
from swim_coach.progression_levers import LeverPolicy, SessionShape, rebase_for_threshold_change
from swim_coach.stimulus import profile_for, profile_named
from swim_coach.workout_builders import parse_rung

AID = uuid.uuid4()
AS_OF = date(2026, 11, 14)
POLICY = LeverPolicy.load()

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


def read_one(records: list[StimulusRecord], athlete: Athlete):
    reads = read_levers(records, athlete, as_of=AS_OF, policy=POLICY)
    assert len(reads) == 1
    return reads[0]


# --- the anchor on the ledger -----------------------------------------------------------------


def test_profile_anchor_in_effect_uses_the_latest_record_on_or_before_the_day() -> None:
    profile = profile_named("bike")
    athlete = Athlete(id=AID, slug="t", name="T", ftp_watts=262.0)

    def tr(value: float, day: date) -> ThresholdRecord:
        return ThresholdRecord(id=uuid.uuid4(), athlete_id=AID, sport="bike", metric="ftp_watts", value=value,
                               measured_at=day, source="ramp_test")

    records = [tr(240, date(2026, 9, 1)), tr(250, date(2026, 10, 1)), tr(262, date(2026, 11, 10))]
    assert profile.anchor_on(date(2026, 10, 15), athlete, records) == (250.0, True)
    assert profile.anchor_on(date(2026, 11, 10), athlete, records) == (262.0, True)
    assert profile.anchor_on(date(2026, 8, 1), athlete, records) == (262.0, False)  # none before: current, unknown
    assert profile.anchor_on(date(2026, 10, 15), athlete, []) == (262.0, False)


def test_profile_pace_threshold_is_higher_when_the_pace_is_smaller() -> None:
    swim, bike = profile_named("swim"), profile_named("bike")
    assert swim.anchor_gain_pct(90.0, 87.0) == pytest.approx(3.333, abs=1e-3)
    assert swim.anchor_gain_pct(90.0, 94.0) < 0
    assert bike.anchor_gain_pct(250.0, 260.0) == pytest.approx(4.0)


def test_ledger_records_the_anchor_and_the_per_rep_detail() -> None:
    athlete = Athlete(id=AID, slug="t", name="T", ftp_watts=262.0, css_pace_s_per_100m=90.0)
    day = date(2026, 11, 3)
    iv = WorkoutIntervals(efforts_detected=3, detection_basis="power", reps_completed=3, reps_in_band_pct=100.0, efforts=[
        IntervalEffort(n=i + 1, start_s=600 + i * 900, duration_s=600, avg_w=245, verdict="ok") for i in range(3)])
    w = Workout(id=uuid.uuid4(), athlete_id=AID, date=day, sport="bike", source="fit", distance_m=0,
                duration_min=60, analytics=WorkoutAnalytics(intervals=iv))
    tr = ThresholdRecord(id=uuid.uuid4(), athlete_id=AID, sport="bike", metric="ftp_watts", value=250.0,
                         measured_at=date(2026, 10, 1), source="ramp_test")
    ledger = build_ledger([w], [], [], athlete, as_of=AS_OF, thresholds=[tr])
    assert len(ledger) == 1 and (ledger[0].anchor_value, ledger[0].anchor_known) == (250.0, True)
    assert ledger[0].executed.dose.rep_sizes == [600, 600, 600] and ledger[0].executed.dose.rest_gaps_s == [300, 300]
    assert SessionShape.from_executed(ledger[0]).describe() == "3x10 min/5 min Z4"
    unknown = build_ledger([w], [], [], athlete, as_of=AS_OF)
    assert (unknown[0].anchor_value, unknown[0].anchor_known) == (262.0, False)


# --- rebase_for_threshold_change ---------------------------------------------------------------


@pytest.mark.parametrize("group", ROWS)
def test_rebase_steps_down_when_the_threshold_rose(group: str) -> None:
    row = ROWS[group]
    ref = shape(group, row["top"])
    read = rebase_for_threshold_change(ref, anchor_then=row["then"], anchor_now=row["now"], policy=POLICY)
    assert read.rebased and read.steps_down >= 1 and read.shape.work() < ref.work() and not read.threshold_fell
    assert "restarting" in read.reason and f"{row['then']:g} -> {row['now']:g}" in read.reason


def test_rebase_bike_example_reads_like_the_brief() -> None:
    read = rebase_for_threshold_change(shape("bike", "2x15 min/5 min Z4"), anchor_then=250, anchor_now=262, policy=POLICY)
    assert read.reason == "FTP rose 5% (250 -> 262 W) since this session; restarting 2 steps lower."
    assert read.shape.describe() == "2x10 min/5 min Z4"


@pytest.mark.parametrize("group", ROWS)
def test_rebase_ignores_a_change_under_the_minimum(group: str) -> None:
    row = ROWS[group]
    nearly = row["then"] * (1.005 if group == "bike" else 0.995)
    ref = shape(group, row["top"])
    read = rebase_for_threshold_change(ref, anchor_then=row["then"], anchor_now=nearly, policy=POLICY)
    assert not read.rebased and read.shape == ref and "restarts" in read.reason


@pytest.mark.parametrize("group", ROWS)
def test_rebase_notes_a_fall_and_does_not_rebase_up(group: str) -> None:
    row = ROWS[group]
    ref = shape(group, row["rung"])
    read = rebase_for_threshold_change(ref, anchor_then=row["then"], anchor_now=row["fell"], policy=POLICY)
    assert read.threshold_fell and not read.rebased and read.shape == ref and "fell" in read.reason


@pytest.mark.parametrize("then", [None, 0])
def test_rebase_with_unknown_history_does_nothing_and_says_so(then) -> None:
    ref = shape("bike", "2x20 min/5 min Z4")
    read = rebase_for_threshold_change(ref, anchor_then=then, anchor_now=262, policy=POLICY)
    assert not read.rebased and read.shape == ref and "unknown" in read.reason


def test_rebase_never_goes_below_the_entry_shape() -> None:
    entry = POLICY.entry("bike", "Z4")
    read = rebase_for_threshold_change(entry, anchor_then=200, anchor_now=260, policy=POLICY)  # +30%: many steps
    assert not read.rebased and read.shape == entry and "entry" in read.reason
    ref = shape("bike", "2x12 min/5 min Z4")
    big = rebase_for_threshold_change(ref, anchor_then=200, anchor_now=260, policy=POLICY)
    assert big.shape.work() >= entry.work() and big.steps_down < 15


def test_rebase_swim_pace_sign_uses_the_profile() -> None:
    ref = shape("swim", "8x200 m/15 s Z4")
    faster = rebase_for_threshold_change(ref, anchor_then=90, anchor_now=87, policy=POLICY)
    slower = rebase_for_threshold_change(ref, anchor_then=87, anchor_now=90, policy=POLICY)
    assert faster.rebased and "improved" in faster.reason
    assert slower.threshold_fell and not slower.rebased


# --- read_levers -------------------------------------------------------------------------------


@pytest.mark.parametrize("group", ROWS)
def test_read_exposes_shape_and_single_lever_candidates(group: str) -> None:
    row = ROWS[group]
    read = read_one([lrec(group, row["rung"], anchor=row["now"])], athlete_for(row))
    ref = shape(group, row["rung"])
    assert read.verdict == "progress" and read.shape == ref and read.rebase is not None and not read.rebase.rebased
    assert read.candidates and not read.at_ceiling and not read.retest_suggested
    assert all(c.shape != ref for c in read.candidates)
    assert "Next:" in read.verdict_reason and not any("lengthen reps" in r for r in read.reasons)


@pytest.mark.parametrize("group", ROWS)
def test_read_rebases_before_generating_candidates(group: str) -> None:
    row = ROWS[group]
    read = read_one([lrec(group, row["top"], anchor=row["then"])], athlete_for(row))
    ref = shape(group, row["top"])
    assert read.rebase.rebased and read.shape == ref
    assert [c.direction for c in read.candidates] == ["rebase"]
    assert read.candidates[0].shape == read.rebase.shape and read.candidates[0].shape.work() < ref.work()
    assert read.verdict_reason == read.rebase.reason
    assert not read.at_ceiling and not read.retest_suggested  # the on-ramp comes before another test


@pytest.mark.parametrize("group", ROWS)
def test_read_does_not_rebase_without_threshold_history(group: str) -> None:
    row = ROWS[group]
    read = read_one([lrec(group, row["rung"], anchor=row["then"], known=False)], athlete_for(row))
    assert not read.rebase.rebased and "unknown" in read.rebase.reason and read.candidates[0].direction == "up"


@pytest.mark.parametrize("group", ROWS)
def test_read_at_the_ceiling_suggests_a_retest(group: str) -> None:
    row = ROWS[group]
    read = read_one([lrec(group, row["top"], anchor=row["now"])], athlete_for(row))
    assert read.at_ceiling and read.retest_suggested
    assert [c.direction for c in read.candidates] == ["retest"]


@pytest.mark.parametrize("group", ROWS)
def test_read_steps_down_after_a_poor_session(group: str) -> None:
    row = ROWS[group]
    read = read_one([lrec(group, row["rung"], anchor=row["now"], in_band=30.0)], athlete_for(row))
    assert read.verdict == "reduce" and read.candidates and all(c.direction == "down" for c in read.candidates)


@pytest.mark.parametrize("group", ROWS)
def test_read_without_a_derivable_shape_keeps_the_dose_read(group: str) -> None:
    row = ROWS[group]
    rec = lrec(group, row["rung"], anchor=row["now"])
    rec.executed.dose.rep_sizes = None
    read = read_one([rec], athlete_for(row))
    plain = read_progression([rec], as_of=AS_OF)[0]
    assert read.shape is None and read.candidates == [] and read.suggested_work_range == plain.suggested_work_range
    assert read.verdict_reason == plain.verdict_reason


# --- defect fixes ------------------------------------------------------------------------------


@pytest.mark.parametrize("group", ROWS)
def test_a_structured_session_is_the_reference_over_an_unstructured_one_with_more_work(group: str) -> None:
    """A club ride's detected threshold time must not become the reference when a structured session exists."""
    row = ROWS[group]
    structured = lrec(group, row["rung"], days_ago=9, anchor=row["now"])
    club = lrec(group, row["rung"], days_ago=2, planned=False, anchor=row["now"])
    irregular = {"rep_sizes": None, "rest_gaps_s": None, row["key"]: shape(group, row["rung"]).work() * 3}
    club.executed.dose = club.executed.dose.model_copy(update=irregular)
    read = read_one([structured, club], athlete_for(row))
    assert read.last.date == structured.date
    assert read.shape == shape(group, row["rung"])


@pytest.mark.parametrize("group", ROWS)
def test_with_no_structured_session_the_unstructured_one_is_still_read(group: str) -> None:
    row = ROWS[group]
    club = lrec(group, row["rung"], days_ago=2, planned=False)
    club.executed.dose = club.executed.dose.model_copy(update={"rep_sizes": None, "rest_gaps_s": None})
    assert read_progression([club], as_of=AS_OF)[0].last.date == club.date


def test_tempo_read_no_longer_says_lengthen_to_the_current_rep() -> None:
    rec = lrec("bike", "2x8 min/4 min Z3", anchor=250.0)
    plain = read_progression([rec], as_of=AS_OF)[0]
    read = read_one([rec], Athlete(id=AID, slug="t", name="T", ftp_watts=250.0))
    assert not any("lengthen reps" in r for r in read.reasons)
    assert all(c.shape != read.shape for c in read.candidates)
    assert plain.verdict == read.verdict == "progress"
