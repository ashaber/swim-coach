"""Calibration cases A-L for stimulus / progression / progression_check, reproduced from real data
with synthetic fixtures (bike athlete FTP 250 W, swim CSS 90 s/100 m)."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from swim_coach.models import (
    Athlete,
    FreeRideRead,
    FreeRideZoneTime,
    IntervalEffort,
    Session,
    SwimRep,
    SwimSet,
    WeekPlan,
    Workout,
    WorkoutAnalytics,
    WorkoutIntervals,
    WorkoutRepeat,
    WorkoutStep,
    WorkoutStructure,
    WorkoutTarget,
)
from swim_coach.progression import (
    ProgressionRead,
    RecoveryResponse,
    StimulusRecord,
    build_ledger,
    read_progression,
    week_stimulus_review,
)
from swim_coach.progression_check import ProgressionInputs, build_progression_inputs, check_week_progression
from swim_coach.stimulus import ExecutedStimulus, StimulusDose, executed_dose, zone_pace_s_per_100m

AID = uuid.uuid4()
ATHLETE = Athlete(id=AID, slug="t", name="T", css_pace_s_per_100m=90.0, ftp_watts=250.0)
MON = date(2026, 11, 9)
AS_OF = date(2026, 11, 14)

Z2_W, TEMPO_W, THR_W, VO2_W = 150, 220, 250, 290


def tstep(role, kind, value, zone, modality="bike"):
    return WorkoutStep(label=role, role=role, duration_kind=kind, duration_value=value,
                       target=WorkoutTarget(basis="zone", zone=zone), modality=modality)


def bike_session(day, *, zone="Z2", minutes=110.0, structured=None, **kw):
    return Session(id=uuid.uuid4(), athlete_id=AID, date=day, sport="bike", source="ai_coach", duration_min=minutes,
                   intensity={"zone": zone}, purpose="t", structured=structured, **kw)


def threshold_structure():
    return WorkoutStructure(items=[WorkoutRepeat(count=3, steps=[tstep("interval", "time_s", 600, "Z4"),
                                                                  tstep("rest", "time_s", 300, "Z1")])])


def effort(n, start, dur, w):
    return IntervalEffort(n=n, start_s=start, duration_s=dur, avg_w=w, verdict="ok")


def bike_workout(day, efforts=None, *, minutes=60.0, analytics=None, **kw):
    if analytics is None:
        iv = WorkoutIntervals(efforts_detected=len(efforts), detection_basis="power", efforts=efforts,
                              **kw.pop("iv", {})) if efforts else None
        analytics = WorkoutAnalytics(intervals=iv)
    else:
        kw.pop("iv", None)
    return Workout(id=uuid.uuid4(), athlete_id=AID, date=day, sport="bike", source="fit", distance_m=0,
                   duration_min=minutes, analytics=analytics, **kw)


def week(sessions, iso="2026-W46"):
    return WeekPlan(id=uuid.uuid4(), athlete_id=AID, iso_week=iso, meso_block="b", focus="f",
                    target_volume_m=0, sessions=sessions)


# --- A: kind mismatch ----------------------------------------------------------------------------


def club_ride_case(day=MON + timedelta(days=1)):
    s = bike_session(day, zone="Z2", minutes=80)
    efforts = [effect for effect in (effort(i + 1, 300 + i * 600, 520, TEMPO_W) for i in range(5))]
    return s, bike_workout(day, efforts, minutes=80)


def test_a_kind_mismatch_has_no_completion_and_is_flagged_substituted():
    s, w = club_ride_case()
    e = executed_dose(w, ATHLETE, s)
    assert e.dose.kind == "tempo" and e.planned_kind == "endurance" and e.substituted is True
    assert e.completion_pct is None and e.in_band_pct is None


def test_a_substituted_record_never_grades_poor_nor_reduces():
    s, w = club_ride_case()
    ledger = build_ledger([w], [week([s])], [], ATHLETE, as_of=AS_OF)
    assert len(ledger) == 1 and ledger[0].kind == "tempo" and ledger[0].substituted
    assert ledger[0].grade() != "poor"
    (r,) = read_progression(ledger, as_of=AS_OF)
    assert r.verdict == "insufficient_data"  # a substituted session never sets a verdict
    assert any("Also delivered" in x and "planned endurance" in x for x in r.reasons)


def test_a_matching_kind_still_gets_completion():
    s = bike_session(MON, zone="Z4", structured=threshold_structure())
    w = bike_workout(MON, [effort(i + 1, 600 * i, 600, THR_W) for i in range(3)])
    e = executed_dose(w, ATHLETE, s)
    assert e.substituted is False and e.completion_pct == pytest.approx(100.0)


# --- B: endurance dose -----------------------------------------------------------------------------


def free_ride(moving, zones):
    return FreeRideRead(moving_s=moving, coasting_s=0, coasting_pct=0, zero_or_null_power_pct=0,
                        power_zones=[FreeRideZoneTime(zone=z, seconds=sec, pct=0) for z, sec in zones])


def test_b_endurance_dose_is_moving_time_not_detected_efforts():
    s = bike_session(MON, zone="Z2", minutes=30)
    efforts = [effort(i + 1, 300 * i, 176, Z2_W) for i in range(3)]  # 528 s of detected efforts
    a = WorkoutAnalytics(intervals=WorkoutIntervals(efforts_detected=3, detection_basis="power", efforts=efforts),
                         free_ride=free_ride(1800, [("Z1", 720), ("Z2", 60)]))
    e = executed_dose(bike_workout(MON, minutes=30, analytics=a), ATHLETE, s)
    assert e.dose.kind == "endurance" and e.dose.work_s == 1800
    assert e.completion_pct == pytest.approx(100.0)


def test_b_endurance_dose_falls_back_to_workout_duration():
    s = bike_session(MON, zone="Z2", minutes=30)
    efforts = [effort(1, 0, 400, Z2_W)]
    e = executed_dose(bike_workout(MON, efforts, minutes=30), ATHLETE, s)
    assert e.dose.kind == "endurance" and e.dose.work_s == 1800


def swim_sets(reps):
    return WorkoutAnalytics(swim_sets=[SwimSet(count=len(reps), rep_distance=100, avg_pace_s_per_100=90,
                                               total_distance=sum(r.distance for r in reps), description="x", reps=reps)])


def swim_rep(i, rank, dist=100):
    pace = zone_pace_s_per_100m(rank, 90.0)
    return SwimRep(start_offset_s=i * 150, distance=dist, swim_time_s=pace * dist / 100, pace_s_per_100=pace, rest_after_s=15.0)


def swim_workout(reps, **kw):
    total = sum(r.distance for r in reps)
    return Workout(id=uuid.uuid4(), athlete_id=AID, date=MON, sport="swim_pool", source="fit", distance_m=kw.pop("distance_m", total),
                   duration_min=kw.pop("duration_min", 40.0), analytics=swim_sets(reps), **kw)


def test_b_swim_endurance_dose_is_total_distance():
    reps = [swim_rep(i, 2) for i in range(9)]
    reps[3] = swim_rep(3, 1)
    w = swim_workout(reps, distance_m=1000)
    e = executed_dose(w, ATHLETE)
    assert e.dose.kind == "endurance" and e.dose.work_m == 1000


# --- C: dose consistency -----------------------------------------------------------------------------


def test_c_longest_rep_never_exceeds_work_when_an_easy_effort_is_longest():
    s = bike_session(MON, zone="Z4", structured=threshold_structure(), minutes=45)
    efforts = [effort(1, 100, 768, Z2_W), effort(2, 1200, 500, THR_W), effort(3, 1800, 500, THR_W)]
    e = executed_dose(bike_workout(MON, efforts, minutes=45), ATHLETE, s)
    d = e.dose
    assert d.kind == "threshold" and d.work_s == 1000 and d.longest_rep_s <= d.work_s and d.rep_count == 2


def invariant_cases():
    easy = [effort(1, 0, 768, Z2_W), effort(2, 900, 500, THR_W), effort(3, 1500, 500, THR_W)]
    quality = [effort(i + 1, 900 * i, 600, THR_W) for i in range(3)]
    yield "bike-mixed-efforts", bike_workout(MON, easy), None
    yield "bike-quality", bike_workout(MON, quality), None
    yield "bike-free-ride", bike_workout(MON, analytics=WorkoutAnalytics(free_ride=free_ride(3600, [("Z2", 2400), ("Z3", 1200)]))), None
    yield "bike-whole", bike_workout(MON, analytics=WorkoutAnalytics(avg_power_w=170.0), minutes=90), None
    yield "bike-endurance-efforts", bike_workout(MON, [effort(1, 0, 400, Z2_W), effort(2, 900, 300, Z2_W)]), None
    yield "swim-quality", swim_workout([swim_rep(i, 4) for i in range(8)]), None
    yield "swim-mixed", swim_workout([swim_rep(i, 2) for i in range(6)] + [swim_rep(6 + i, 4, 200) for i in range(3)]), None
    yield "swim-endurance", swim_workout([swim_rep(i, 2) for i in range(9)]), None
    yield "swim-whole", Workout(id=uuid.uuid4(), athlete_id=AID, date=MON, sport="swim_pool", source="fit",
                                distance_m=2000, duration_min=36.0), None


@pytest.mark.parametrize("name,w,s", list(invariant_cases()), ids=lambda v: v if isinstance(v, str) else "")
def test_c_dose_invariants_hold_on_every_executed_path(name, w, s):
    e = executed_dose(w, ATHLETE, s)
    assert e is not None
    d = e.dose
    for work, longest in ((d.work_s, d.longest_rep_s), (d.work_m, d.longest_rep_m)):
        if work is not None and longest is not None:
            assert longest <= work + 1e-6
            if d.rep_count:
                assert work <= d.rep_count * longest + 1e-6


# --- D: matched prescription inherits planned kind ------------------------------------------------------


def matched_case(**iv):
    s = bike_session(MON, zone="Z4", structured=threshold_structure(), minutes=60)
    efforts = [effort(1, 600, 600, 215), effort(2, 1500, 600, 245), effort(3, 2400, 600, 215)]  # Z3 / Z4 / Z3 by watts
    w = bike_workout(MON, efforts, iv=dict(matched_to_prescription=True, reps_completed=3, prescribed_count=3, **iv))
    return s, w


def test_d_matched_prescription_inherits_planned_kind():
    s, w = matched_case(reps_in_band_pct=100.0, target_zone="Z4")
    e = executed_dose(w, ATHLETE, s)
    assert e.dose.kind == "threshold" and e.dose.work_s == 1800 and e.substituted is False
    assert e.completion_pct == pytest.approx(100.0)


def test_d_unresolved_band_zero_is_unknown_not_zero():
    s, w = matched_case(reps_in_band_pct=0.0, target_zone=None, target_band_w=None)
    e = executed_dose(w, ATHLETE, s)
    assert e.in_band_pct is None


def test_d_resolved_band_zero_stays_zero():
    s, w = matched_case(reps_in_band_pct=0.0, target_zone="Z4", target_band_w=(237.0, 262.0))
    assert executed_dose(w, ATHLETE, s).in_band_pct == 0.0


def test_d_unknown_in_band_does_not_reduce():
    s, w = matched_case(reps_in_band_pct=0.0, target_zone=None, target_band_w=None)
    ledger = build_ledger([w], [week([s])], [], ATHLETE, as_of=AS_OF)
    assert ledger[0].grade() != "poor"
    assert read_progression(ledger, as_of=AS_OF)[0].verdict != "reduce"


# --- E: estimated execution -----------------------------------------------------------------------------


def vo2_structure():
    return WorkoutStructure(items=[WorkoutRepeat(count=7, steps=[tstep("interval", "time_s", 140, "Z5"),
                                                                  tstep("rest", "time_s", 140, "Z1")])])


def estimated_case():
    s = bike_session(MON, zone="Z5", structured=vo2_structure(), minutes=70)
    return s, bike_workout(MON, minutes=70, analytics=WorkoutAnalytics(avg_power_w=215.0))


def test_e_estimated_execution_has_no_completion():
    s, w = estimated_case()
    e = executed_dose(w, ATHLETE, s)
    assert e.dose.confidence == "estimated" and e.completion_pct is None


def test_e_estimated_record_is_unknown_grade_and_insufficient():
    s, w = estimated_case()
    ledger = build_ledger([w], [week([s])], [], ATHLETE, as_of=AS_OF)
    assert ledger[0].grade() == "unknown"
    (r,) = read_progression(ledger, as_of=AS_OF)
    assert r.verdict == "insufficient_data" and r.reference_dose is None
    assert any("insufficient execution data" in x for x in r.reasons)


def test_e_over_150_percent_on_structured_data_gets_a_reason():
    d = StimulusDose(sport="bike", kind="threshold", work_s=3000.0, longest_rep_s=600.0, rep_count=5, confidence="structured")
    rec = StimulusRecord(date=AS_OF - timedelta(days=3), sport="bike", kind="threshold", planned=True,
                         executed=ExecutedStimulus(dose=d, completion_pct=200.0, in_band_pct=90.0, planned=True),
                         recovery=RecoveryResponse(status="recovered"))
    (r,) = read_progression([rec], as_of=AS_OF)
    assert any("150%" in x for x in r.reasons)


# --- F: races leak in -------------------------------------------------------------------------------------


@pytest.mark.parametrize("session_kind,workout_kind", [("race", None), ("race", "free_ride"), ("opener", None),
                                                        ("warmup", None), (None, "race")])
def test_f_race_opener_warmup_create_no_record(session_kind, workout_kind):
    s = bike_session(MON, zone="Z5", minutes=27, kind=session_kind)
    kw = {"kind_override": workout_kind} if workout_kind else {}
    w = bike_workout(MON, [effort(1, 0, 37, VO2_W)], minutes=27, **kw)
    w = w.model_copy(update={"planned_session_id": s.id})
    assert executed_dose(w, ATHLETE, s) is None
    assert build_ledger([w], [week([s])], [], ATHLETE, as_of=AS_OF) == []


# --- G: minimum dose floor ------------------------------------------------------------------------------------


def test_g_one_workout_yields_one_record_and_small_quality_falls_back_to_endurance():
    reps = [swim_rep(i, 2) for i in range(9)] + [swim_rep(9, 3), swim_rep(10, 5, 50)]
    w = swim_workout(reps, distance_m=1050)
    ledger = build_ledger([w], [], [], ATHLETE, as_of=AS_OF)
    assert [(r.kind, r.executed.dose.work_m) for r in ledger] == [("endurance", 1050)]
    assert read_progression(ledger, as_of=AS_OF)[0].kind == "endurance"


@pytest.mark.parametrize("sport,floor_work,below", [("swim", 400, 350), ("bike", 600, 540)])
def test_g_tempo_floor_boundary(sport, floor_work, below):
    if sport == "swim":
        make = lambda total: swim_workout([swim_rep(i, 3, 50) for i in range(total // 50)] + [swim_rep(99, 1, 600)], distance_m=total + 600)
        kind_at, kind_below = executed_dose(make(floor_work), ATHLETE).dose.kind, executed_dose(make(below), ATHLETE).dose.kind
    else:
        make = lambda total: bike_workout(MON, [effort(1, 0, total, TEMPO_W)], minutes=90)
        kind_at, kind_below = executed_dose(make(floor_work), ATHLETE).dose.kind, executed_dose(make(below), ATHLETE).dose.kind
    assert kind_at == "tempo" and kind_below != "tempo"


def test_g_profile_owns_the_floors():
    from swim_coach.stimulus import profile_for

    assert profile_for("bike").min_dose == {"tempo": 600.0, "threshold": 480.0, "vo2": 180.0}
    assert profile_for("swim_pool").min_dose == {"tempo": 400.0, "threshold": 300.0, "vo2": 200.0}


# --- H: findings on past sessions -------------------------------------------------------------------------------


def jump_read():
    d = StimulusDose(sport="bike", kind="threshold", work_s=1800.0, longest_rep_s=600.0, confidence="structured")
    rec = StimulusRecord(date=MON - timedelta(days=3), sport="bike", kind="threshold", planned=True,
                         executed=ExecutedStimulus(dose=d, completion_pct=100.0, in_band_pct=90.0, planned=True),
                         recovery=RecoveryResponse(status="recovered"))
    return ProgressionRead(sport="bike", kind="threshold", verdict="progress", unit="s", confidence="high",
                           reasons=["Last session did 30 min."], last=rec, reference_dose=d,
                           suggested_work_range=(1800.0, 1980.0), days_since_last=3)


def big_session(day, **kw):
    st = WorkoutStructure(items=[WorkoutRepeat(count=4, steps=[tstep("interval", "time_s", 900, "Z4"), tstep("rest", "time_s", 300, "Z1")])])
    return bike_session(day, zone="Z4", structured=st, minutes=90, **kw)


def run_h(sessions, as_of):
    return check_week_progression(week(sessions), ATHLETE, reads=[jump_read()], as_of=as_of)


def test_h_past_sessions_are_not_checked_when_as_of_is_mid_week():
    past, future = big_session(MON + timedelta(days=1)), big_session(MON + timedelta(days=4))
    found = run_h([past, future], MON + timedelta(days=2))
    assert [f.evidence.count(f"on {future.date.isoformat()}") for f in found] == [1]


def test_h_today_counts_unless_completed_and_all_past_week_is_silent():
    today = big_session(MON + timedelta(days=2))
    assert len(run_h([today], MON + timedelta(days=2))) == 1
    done = big_session(MON + timedelta(days=2), status="completed")
    assert run_h([done], MON + timedelta(days=2)) == []
    assert run_h([big_session(MON + timedelta(days=1))], MON + timedelta(days=10)) == []


def test_h_future_week_checks_every_session():
    assert len(run_h([big_session(MON + timedelta(days=1))], MON - timedelta(days=5))) == 1


def test_h_check_week_and_builder_pass_as_of_through():
    w = week([big_session(MON + timedelta(days=1))])
    inputs = build_progression_inputs([], [w], [], ATHLETE, w, as_of=MON + timedelta(days=3))
    assert inputs.as_of == MON + timedelta(days=3)


# --- I: practical rounding ---------------------------------------------------------------------------------------


def record_of(sport, work, longest, day=3, kind="threshold"):
    pname, sport = sport, ("bike" if sport == "bike" else "swim_pool")
    key, lkey = ("work_s", "longest_rep_s") if pname == "bike" else ("work_m", "longest_rep_m")
    d = StimulusDose(sport=sport, kind=kind, confidence="structured", **{key: work, lkey: longest})
    return StimulusRecord(date=AS_OF - timedelta(days=day), sport=sport, kind=kind, planned=True,
                          executed=ExecutedStimulus(dose=d, completion_pct=100.0, in_band_pct=90.0, fade_pct=1.0, rpe=7, planned=True),
                          recovery=RecoveryResponse(status="recovered"))


@pytest.mark.parametrize("sport,work,longest,work_unit,rep_unit", [
    ("bike", 1309.7, 437.0, 30, 15), ("bike", 1380.6, 600.0, 30, 15), ("swim", 773.0, 100.0, 50, 25), ("swim", 1210.0, 173.0, 50, 25)])
def test_i_ranges_are_practical_multiples(sport, work, longest, work_unit, rep_unit):
    (r,) = read_progression([record_of(sport, work, longest)], as_of=AS_OF)
    low, high = r.suggested_work_range
    assert low % work_unit == 0 and high % work_unit == 0 and low <= high
    if r.suggested_longest_rep_max is not None:
        assert r.suggested_longest_rep_max % rep_unit == 0 and r.suggested_longest_rep_max > longest


def test_i_swim_rep_cap_never_rounds_back_to_the_current_rep():
    (r,) = read_progression([record_of("swim", 800.0, 100.0)], as_of=AS_OF)
    assert r.suggested_longest_rep_max == 125.0


def test_i_reduce_and_rebuild_ranges_are_rounded_and_ordered():
    bad = record_of("bike", 1500.0, 500.0)
    bad.executed.completion_pct = 60.0
    (r,) = read_progression([bad], as_of=AS_OF)
    assert r.verdict == "reduce" and all(v % 30 == 0 for v in r.suggested_work_range)
    (stale,) = read_progression([record_of("bike", 1500.0, 500.0, day=60)], as_of=AS_OF)
    assert stale.verdict == "rebuild" and stale.suggested_work_range[0] <= stale.suggested_work_range[1]


# --- J: load units ---------------------------------------------------------------------------------------------------


def power_workout(day, minutes=60.0):
    return bike_workout(day, minutes=minutes, analytics=WorkoutAnalytics(normalized_power_w=200.0, avg_power_w=190.0))


def test_j_done_and_planned_load_are_on_one_scale():
    sessions = [bike_session(MON + timedelta(days=i), zone="Z3", minutes=60) for i in range(6)]
    done = [power_workout(MON + timedelta(days=i)) for i in range(3)]
    r = week_stimulus_review(week(sessions), done, ATHLETE, [], as_of=MON + timedelta(days=2))
    assert r.load_comparable is True
    assert r.done_load_au == pytest.approx(r.planned_load_au / 2)
    assert not [i for i in r.impacts if i.impact == "load_over_target"]


def test_j_unplanned_work_without_rpe_makes_load_unavailable_and_suppresses_the_impact():
    easy = bike_session(MON + timedelta(days=4), zone="Z2", minutes=60)
    big = Workout(id=uuid.uuid4(), athlete_id=AID, date=MON, sport="cross_train", source="manual", distance_m=0, duration_min=600)
    r = week_stimulus_review(week([easy]), [big], ATHLETE, [], as_of=MON + timedelta(days=1))
    assert r.load_comparable is False
    assert not [i for i in r.impacts if i.impact == "load_over_target"]


# --- K: substituted work as an impact source -------------------------------------------------------------------------------


def test_k_substituted_session_is_listed_and_raises_hard_too_soon():
    tue = MON + timedelta(days=1)
    club = bike_session(tue, zone="Z2", minutes=80)
    thu = bike_session(MON + timedelta(days=2), zone="Z4", structured=threshold_structure(), minutes=60)
    w = bike_workout(tue, [effort(i + 1, 300 + i * 600, 336, TEMPO_W) for i in range(5)], minutes=80)
    r = week_stimulus_review(week([club, thu]), [w], ATHLETE, [], as_of=tue)
    assert [s.sport for s in r.substituted_done] == ["bike"] and r.unplanned_done == []
    assert club.id in [m.session_id for m in r.planned_missed] and r.planned_done == []
    soon = [i for i in r.impacts if i.impact == "hard_too_soon"]
    assert [i.session_id for i in soon] == [thu.id]
    assert "Tuesday's planned endurance bike session delivered 28 min of tempo" in soon[0].evidence[0]


# --- L: evidence wording ---------------------------------------------------------------------------------------------------


def test_l_evidence_uses_the_verdict_cause_not_the_first_reason():
    r = jump_read()
    r.reasons = ["Last session did 30 min of threshold.", "Next dose 30 min to 33 min."]
    r.verdict_reason = "Next dose 30 min to 33 min."
    found = check_week_progression(week([big_session(MON + timedelta(days=4))]), ATHLETE, reads=[r])
    assert "Next dose 30 min to 33 min." in found[0].evidence and "Last session did 30 min of threshold." not in found[0].evidence


def test_l_format_amount_is_public_and_progression_check_does_not_import_private_names():
    from swim_coach.formatting import format_amount

    assert format_amount(1800.0, "s") == "30 min" and format_amount(1200.0, "m") == "1200 m" and format_amount(None, "m") == "unknown"
    import inspect

    import swim_coach.progression_check as pc

    assert "_fmt" not in inspect.getsource(pc)
