"""Tests for swim_coach.progression: recovery response, ledger, and the per-kind progression read."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from swim_coach.models import (
    Athlete,
    IntervalEffort,
    Session,
    SwimRep,
    SwimSet,
    WeekPlan,
    Wellness,
    Workout,
    WorkoutAnalytics,
    WorkoutIntervals,
    WorkoutRepeat,
    WorkoutStep,
    WorkoutStructure,
    WorkoutTarget,
)
from swim_coach.progression import (
    PROGRESSION_STALE_DAYS,
    PROGRESSION_STEP_FRACTION,
    RecoveryResponse,
    StimulusRecord,
    build_ledger,
    read_progression,
    recovery_response,
)
from swim_coach.stimulus import ExecutedStimulus, StimulusDose

AID = uuid.uuid4()
ATHLETE = Athlete(id=AID, slug="t", name="T", css_pace_s_per_100m=90.0, ftp_watts=250.0)
AS_OF = date(2026, 11, 14)

# One scenario table per sport: the same scenarios run through both profiles.
SPORTS = {
    "bike": dict(unit="s", work=1800.0, short_rep=300.0, long_rep=1200.0, key="work_s", rep="longest_rep_s"),
    "swim_pool": dict(unit="m", work=1200.0, short_rep=100.0, long_rep=400.0, key="work_m", rep="longest_rep_m"),
}


def rec(sport, *, days_ago=3, kind="threshold", completion=100.0, in_band=90.0, fade=2.0, rpe=7,
        recovery="recovered", rep=None, planned=True, confidence="structured", scale=1.0):
    s = SPORTS[sport]
    dose = StimulusDose(sport=sport, kind=kind, confidence=confidence, **{s["key"]: s["work"] * scale, s["rep"]: rep or s["long_rep"]})
    return StimulusRecord(
        date=AS_OF - timedelta(days=days_ago), sport=sport, kind=kind, planned=planned,
        executed=ExecutedStimulus(dose=dose, completion_pct=completion if planned else None, in_band_pct=in_band,
                                  fade_pct=fade, rpe=rpe, planned=planned),
        recovery=RecoveryResponse(status=recovery),
    )


def read_one(records):
    reads = read_progression(records, as_of=AS_OF)
    assert len(reads) == 1
    return reads[0]


@pytest.mark.parametrize("sport", SPORTS)
class TestSameScenariosBothSports:
    def test_progress(self, sport):
        r = read_one([rec(sport)])
        s = SPORTS[sport]
        assert r.verdict == "progress" and r.unit == s["unit"]
        assert r.suggested_work_range == pytest.approx((s["work"], s["work"] * (1 + PROGRESSION_STEP_FRACTION)))
        assert r.suggested_longest_rep_max is None and r.reference_dose is not None

    def test_progress_unplanned_but_clean(self, sport):
        assert read_one([rec(sport, planned=False)]).verdict == "progress"

    @pytest.mark.parametrize("override", [
        dict(completion=80.0), dict(in_band=60.0), dict(fade=9.0), dict(rpe=9), dict(recovery="strained"),
    ])
    def test_repeat_when_marginal(self, sport, override):
        r = read_one([rec(sport, **override)])
        assert r.verdict == "repeat"
        assert r.suggested_work_range[1] == pytest.approx(SPORTS[sport]["work"])

    @pytest.mark.parametrize("override", [dict(completion=70.0), dict(in_band=40.0)])
    def test_reduce_when_poor(self, sport, override):
        r = read_one([rec(sport, **override)])
        assert r.verdict == "reduce" and r.suggested_work_range[1] < SPORTS[sport]["work"]

    def test_two_consecutive_repeats_reduce(self, sport):
        r = read_one([rec(sport, days_ago=10, fade=9.0), rec(sport, days_ago=3, rpe=9)])
        assert r.verdict == "reduce" and any("in a row" in x for x in r.reasons)

    def test_repeat_then_clean_does_not_reduce(self, sport):
        assert read_one([rec(sport, days_ago=10, fade=9.0), rec(sport, days_ago=3)]).verdict == "progress"

    def test_stale_rebuilds_regardless_of_how_it_went(self, sport):
        r = read_one([rec(sport, days_ago=PROGRESSION_STALE_DAYS + 1)])
        assert r.verdict == "rebuild"
        assert r.suggested_work_range[1] == pytest.approx(SPORTS[sport]["work"] * (1 - PROGRESSION_STEP_FRACTION))

    def test_estimated_only_is_insufficient(self, sport):
        r = read_one([rec(sport, confidence="estimated")])
        assert r.verdict == "insufficient_data" and r.suggested_work_range is None

    def test_unknown_recovery_still_progresses_with_lower_confidence(self, sport):
        known = read_one([rec(sport, days_ago=9), rec(sport)])
        unknown = read_one([rec(sport, days_ago=9, recovery="unknown"), rec(sport, recovery="unknown")])
        assert unknown.verdict == "progress" and known.confidence == "high" and unknown.confidence == "medium"
        assert any("Recovery is unknown" in x for x in unknown.reasons)

    def test_short_reps_raise_rep_length_before_volume(self, sport):
        s = SPORTS[sport]
        r = read_one([rec(sport, rep=s["short_rep"])])
        assert r.verdict == "progress"
        assert r.suggested_work_range == pytest.approx((s["work"], s["work"]))
        assert r.suggested_longest_rep_max > s["short_rep"]
        assert any("lengthen reps" in x for x in r.reasons)


def test_kinds_are_read_separately_and_reasons_quote_numbers():
    reads = read_progression([rec("bike", kind="tempo"), rec("bike", kind="vo2", completion=60.0)], as_of=AS_OF)
    assert {(r.kind, r.verdict) for r in reads} == {("tempo", "progress"), ("vo2", "reduce")}
    assert any("60%" in x for r in reads for x in r.reasons)


def test_unsupported_sport_records_yield_no_read():
    r = rec("bike")
    r.sport = "strength"
    assert read_progression([r], as_of=AS_OF) == []


def test_swim_ow_and_pool_share_one_read():
    a, b = rec("swim_pool", days_ago=9), rec("swim_pool")
    b.sport = "swim_ow"
    assert len(read_progression([a, b], as_of=AS_OF)) == 1


# --- recovery response ---------------------------------------------------------------------


def wl(day, **kw):
    return Wellness(id=uuid.uuid4(), athlete_id=AID, date=day, **kw)


def baseline_rows(day, hrv=60.0, rhr=50, n=20):
    return [wl(day - timedelta(days=i), hrv=hrv, resting_hr=rhr) for i in range(n, 0, -1)]


def test_missing_wellness_is_unknown_never_recovered():
    day = date(2026, 11, 5)
    assert recovery_response(day, [], as_of=AS_OF).status == "unknown"
    assert recovery_response(day, baseline_rows(day), as_of=AS_OF).status == "unknown"  # nothing after the session


def test_session_today_has_no_post_window_yet():
    assert recovery_response(AS_OF, baseline_rows(AS_OF), as_of=AS_OF).status == "unknown"


def test_recovered_when_signals_present_and_flat():
    day = date(2026, 11, 5)
    rows = baseline_rows(day + timedelta(days=2))
    assert recovery_response(day, rows, as_of=AS_OF).status == "recovered"


def test_strained_on_hrv_suppression():
    day = date(2026, 11, 5)
    rows = baseline_rows(day) + [wl(day + timedelta(days=1), hrv=50.0, resting_hr=50), wl(day + timedelta(days=2), hrv=50.0, resting_hr=50)]
    r = recovery_response(day, rows, as_of=AS_OF)
    assert r.status == "strained" and r.hrv_pct_deviation <= -5 and "HRV" in r.evidence[0]


def test_strained_on_red_composite():
    day = date(2026, 11, 5)
    bad = dict(sleep_quality=1, stress=5, soreness=5, motivation=1)
    r = recovery_response(day, [wl(day + timedelta(days=1), **bad)], as_of=AS_OF)
    assert r.status == "strained" and r.composite_post == 1.0 and r.soreness_max == 5


def test_recovery_never_reads_wellness_after_as_of():
    day = AS_OF - timedelta(days=1)
    rows = [wl(AS_OF + timedelta(days=1), sleep_quality=1, stress=5, soreness=5, motivation=1)]
    assert recovery_response(day, rows, as_of=AS_OF).status == "unknown"


# --- ledger ---------------------------------------------------------------------------------


def tstep(role, kind, value, zone, modality):
    return WorkoutStep(label=role, role=role, duration_kind=kind, duration_value=value,
                       target=WorkoutTarget(basis="zone", zone=zone), modality=modality)


def bike_session(day, **kw):
    st = WorkoutStructure(items=[WorkoutRepeat(count=3, steps=[tstep("interval", "time_s", 600, "Z4", "bike"), tstep("rest", "time_s", 300, "Z1", "bike")])])
    return Session(id=uuid.uuid4(), athlete_id=AID, date=day, sport="bike", source="ai_coach", duration_min=60,
                   intensity={"zone": "Z4"}, purpose="t", structured=st, **kw)


def bike_workout(day, **kw):
    iv = WorkoutIntervals(efforts_detected=3, detection_basis="power", reps_completed=3, reps_in_band_pct=100.0, efforts=[
        IntervalEffort(n=i + 1, start_s=600 + i * 900, duration_s=600, avg_w=245, verdict="ok") for i in range(3)])
    return Workout(id=uuid.uuid4(), athlete_id=AID, date=day, sport="bike", source="fit", distance_m=0,
                   duration_min=60, analytics=WorkoutAnalytics(intervals=iv), **kw)


def week(sessions):
    return WeekPlan(id=uuid.uuid4(), athlete_id=AID, iso_week="2026-W45", meso_block="b", focus="f",
                    target_volume_m=0, sessions=sessions)


def test_ledger_matches_planned_session_and_orders_oldest_first():
    d1, d2 = date(2026, 11, 3), date(2026, 11, 10)
    s1, s2 = bike_session(d1), bike_session(d2)
    w1, w2 = bike_workout(d1), bike_workout(d2)
    ledger = build_ledger([w2, w1], [week([s1, s2])], baseline_rows(AS_OF), ATHLETE, as_of=AS_OF)
    assert [r.date for r in ledger] == [d1, d2]
    assert all(r.planned and r.kind == "threshold" and r.executed.completion_pct == 100.0 for r in ledger)
    assert ledger[0].session_id == s1.id and ledger[0].planned_dose.work_s == 1800


def test_ledger_honours_planned_session_id_and_marks_unplanned():
    d = date(2026, 11, 10)
    s = bike_session(date(2026, 11, 6))
    linked = bike_workout(d, planned_session_id=s.id)
    free = bike_workout(date(2026, 11, 12))
    ledger = build_ledger([linked, free], [week([s])], [], ATHLETE, as_of=AS_OF)
    assert [r.planned for r in ledger] == [True, False]
    assert ledger[1].executed.completion_pct is None


def test_ledger_skips_races_unsupported_sports_and_outside_lookback():
    d = date(2026, 11, 10)
    race = bike_workout(d, kind="race")
    strength = Workout(id=uuid.uuid4(), athlete_id=AID, date=d, sport="strength", source="manual", distance_m=0, duration_min=30)
    old = bike_workout(AS_OF - timedelta(days=60))
    assert build_ledger([race, strength, old], [], [], ATHLETE, as_of=AS_OF) == []


def test_ledger_swim_record_end_to_end():
    reps = [SwimRep(start_offset_s=i * 120, distance=100, swim_time_s=90, pace_s_per_100=90, rest_after_s=15) for i in range(8)]
    sets = [SwimSet(count=8, rep_distance=100, avg_pace_s_per_100=90, total_distance=800, description="8x100", reps=reps)]
    w = Workout(id=uuid.uuid4(), athlete_id=AID, date=date(2026, 11, 10), sport="swim_pool", source="fit",
                distance_m=1500, duration_min=40, analytics=WorkoutAnalytics(swim_sets=sets))
    ledger = build_ledger([w], [], [], ATHLETE, as_of=AS_OF)
    assert len(ledger) == 1 and ledger[0].kind == "threshold" and ledger[0].executed.dose.work_m == 800
    assert read_progression(ledger, as_of=AS_OF)[0].unit == "m"


# --- week stimulus review -------------------------------------------------------------------

from swim_coach.progression import week_stimulus_review  # noqa: E402

MON = date(2026, 11, 9)


def swim_session(day, zone="Z4", **kw):
    st = WorkoutStructure(items=[WorkoutRepeat(count=8, steps=[tstep("interval", "distance_m", 100, zone, "swim"),
                                                                tstep("rest", "time_s", 15, "Z1", "swim")])])
    return Session(id=uuid.uuid4(), athlete_id=AID, date=day, sport="swim_pool", source="ai_coach", duration_min=45,
                   distance_m=1800, intensity={"zone": zone}, purpose="t", structured=st, **kw)


def easy_bike_session(day):
    return Session(id=uuid.uuid4(), athlete_id=AID, date=day, sport="bike", source="ai_coach", duration_min=60,
                   intensity={"zone": "Z2"}, purpose="t")


def review(sessions, workouts, as_of):
    return week_stimulus_review(week(sessions), workouts, ATHLETE, [], as_of=as_of)


def test_week_without_unplanned_work_has_no_impacts():
    s_done, s_future = bike_session(MON), bike_session(MON + timedelta(days=4))
    r = review([s_done, s_future], [bike_workout(MON)], MON + timedelta(days=2))
    assert r.impacts == [] and r.unplanned_done == []
    assert [e.session_id for e in r.planned_done] == [s_done.id]
    assert [e.session_id for e in r.remaining] == [s_future.id]
    assert r.week_start == MON


def test_planned_and_missed_when_date_passed():
    missed, future = bike_session(MON), bike_session(MON + timedelta(days=5))
    r = review([missed, future], [], MON + timedelta(days=3))
    assert [e.session_id for e in r.planned_missed] == [missed.id]
    assert [e.session_id for e in r.remaining] == [future.id]


def test_unplanned_work_is_classified_with_dose_and_load():
    r = review([bike_session(MON + timedelta(days=5))], [bike_workout(MON + timedelta(days=1), rpe=7)], MON + timedelta(days=2))
    u = r.unplanned_done[0]
    assert u.kind == "threshold" and u.executed.dose.work_s == 1800 and u.load_au > 0 and not u.executed.planned


def test_duplicate_stimulus_impact():
    remaining = bike_session(MON + timedelta(days=4))
    r = review([remaining], [bike_workout(MON)], MON + timedelta(days=2))
    dup = [i for i in r.impacts if i.impact == "duplicate_stimulus"]
    assert len(dup) == 1 and dup[0].session_id == remaining.id and "100%" in dup[0].evidence[0]


def test_no_duplicate_when_unplanned_dose_is_small():
    small = bike_workout(MON)
    small.analytics.intervals.efforts = small.analytics.intervals.efforts[:1]
    r = review([bike_session(MON + timedelta(days=4))], [small], MON + timedelta(days=2))
    assert not [i for i in r.impacts if i.impact == "duplicate_stimulus"]


def test_hard_too_soon_across_sports_within_48h():
    tuesday_swim, thursday_swim = swim_session(MON + timedelta(days=1)), swim_session(MON + timedelta(days=3))
    r = review([tuesday_swim, thursday_swim], [bike_workout(MON)], MON + timedelta(days=1))
    soon = [i for i in r.impacts if i.impact == "hard_too_soon"]
    assert [i.session_id for i in soon] == [tuesday_swim.id] and "24 h" in soon[0].evidence[0]


def test_load_over_target_attaches_to_heaviest_remaining():
    easy = easy_bike_session(MON + timedelta(days=4))
    big = Workout(id=uuid.uuid4(), athlete_id=AID, date=MON, sport="cross_train", source="manual", distance_m=0,
                  duration_min=240, rpe=9)
    r = review([easy], [big], MON + timedelta(days=1))
    over = [i for i in r.impacts if i.impact == "load_over_target"]
    assert len(over) == 1 and over[0].session_id == easy.id
    assert r.done_load_au > r.planned_load_au * 1.08


def test_no_load_impact_when_within_rail():
    r = review([bike_session(MON + timedelta(days=4))], [], MON + timedelta(days=1))
    assert not [i for i in r.impacts if i.impact == "load_over_target"]


def test_unsupported_sport_unplanned_work_counts_load_but_has_no_kind():
    w = Workout(id=uuid.uuid4(), athlete_id=AID, date=MON, sport="strength", source="manual", distance_m=0, duration_min=45, rpe=6)
    r = review([easy_bike_session(MON + timedelta(days=4))], [w], MON + timedelta(days=1))
    assert r.unplanned_done[0].kind is None and r.done_load_au > 0
