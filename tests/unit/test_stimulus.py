"""Tests for swim_coach.stimulus: planned/executed dose, kind rule, sport profiles."""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from swim_coach.models import (
    Athlete,
    FreeRideRead,
    FreeRideZoneTime,
    IntervalEffort,
    Session,
    SwimRep,
    SwimSet,
    Workout,
    WorkoutAnalytics,
    WorkoutIntervals,
    WorkoutRepeat,
    WorkoutStep,
    WorkoutStructure,
    WorkoutTarget,
)
from swim_coach.stimulus import (
    classify_kind,
    executed_dose,
    pace_zone_rank,
    planned_dose,
    profile_for,
    walk_leaves,
    zone_rank,
)

AID = uuid.uuid4()
ATHLETE = Athlete(id=AID, slug="t", name="T", css_pace_s_per_100m=90.0, ftp_watts=250.0)


def step(role, kind, value, *, zone=None, basis=None, low=None, high=None, modality="bike"):
    target = None
    if zone:
        target = WorkoutTarget(basis="zone", zone=zone)
    elif basis:
        target = WorkoutTarget(basis=basis, low=low, high=high)
    return WorkoutStep(label=role, role=role, duration_kind=kind, duration_value=value, target=target, modality=modality)


def session(sport="bike", structured=None, kind=None, zone="Z2", duration_min=60.0, distance_m=None, day=date(2026, 11, 2)):
    return Session(
        id=uuid.uuid4(), athlete_id=AID, date=day, sport=sport, source="ai_coach", duration_min=duration_min,
        distance_m=distance_m, intensity={"zone": zone}, purpose="t", structured=structured, kind=kind,
    )


def workout(sport="bike", analytics=None, **kw):
    data = dict(
        id=uuid.uuid4(), athlete_id=AID, date=date(2026, 11, 2), sport=sport, source="fit",
        distance_m=0, duration_min=60.0, analytics=analytics,
    )
    data.update(kw)
    return Workout(**data)


def bike_threshold_structure():
    return WorkoutStructure(items=[
        step("warmup", "time_s", 600, zone="Z1"),
        WorkoutRepeat(count=3, steps=[step("interval", "time_s", 600, zone="Z4"), step("rest", "time_s", 300, zone="Z1")]),
        step("cooldown", "time_s", 600, zone="Z1"),
    ])


def test_bike_planned_dose_from_nested_repeats():
    inner = WorkoutRepeat(count=2, steps=[step("interval", "time_s", 120, zone="Z5"), step("rest", "time_s", 60, zone="Z1")])
    s = session(structured=WorkoutStructure(items=[WorkoutRepeat(count=3, steps=[inner])]))
    d = planned_dose(s, ATHLETE)
    assert d.kind == "vo2" and d.confidence == "structured"
    assert d.work_s == 3 * 2 * 120 and d.rep_count == 6 and d.longest_rep_s == 120
    assert d.work_rest_ratio == pytest.approx(2.0)


def test_bike_power_w_target_resolves_against_ftp():
    s = session(structured=WorkoutStructure(items=[
        WorkoutRepeat(count=3, steps=[step("interval", "time_s", 600, basis="power_w", low=235, high=250)]),
    ]))
    d = planned_dose(s, ATHLETE)
    assert d.kind == "threshold" and d.work_s == 1800


def test_swim_distance_set_with_percent_css_and_pace():
    st = WorkoutStructure(items=[
        step("warmup", "distance_m", 400, zone="Z1", modality="swim"),
        WorkoutRepeat(count=8, steps=[
            step("interval", "distance_m", 100, basis="percent_css", low=98, high=102, modality="swim"),
            step("rest", "time_s", 15, modality="swim"),
        ]),
    ])
    d = planned_dose(session("swim_pool", st, zone="Z4"), ATHLETE)
    assert d.kind == "threshold" and d.work_m == 800 and d.rep_count == 8 and d.longest_rep_m == 100
    assert d.work_s == pytest.approx(8 * 90.0)  # Z4 midpoint pace is CSS
    assert d.work_rest_ratio is None or d.work_rest_ratio > 0


def test_swim_absolute_pace_target_ranked_against_css():
    st = WorkoutStructure(items=[step("interval", "distance_m", 400, basis="absolute", low=93, high=95, modality="swim")])
    assert zone_rank(st.items[0], css_pace_s_per_100m=90.0) == 3


def test_estimated_fallback_uses_zone_and_totals():
    d = planned_dose(session(zone="Z4", duration_min=60), ATHLETE)
    assert d.confidence == "estimated" and d.kind == "threshold" and d.work_s == 1800 and d.rep_count is None
    d = planned_dose(session("swim_pool", zone="Z2", duration_min=50, distance_m=2000), ATHLETE)
    assert d.kind == "endurance" and d.work_m == 2000


def test_no_zone_no_dose():
    s = session()
    s.intensity.pop("zone")
    assert planned_dose(s, ATHLETE) is None


@pytest.mark.parametrize("weights,expected", [
    ([(2, 100)], "endurance"),
    ([(2, 90), (3, 10)], "tempo"),
    ([(2, 95), (3, 5)], "endurance"),
    ([(4, 100)], "threshold"),
    ([(3, 40), (4, 60)], "mixed"),
    ([(4, 85), (5, 15)], "vo2"),
    ([(4, 95), (5, 5)], "threshold"),
    ([(6, 100)], "vo2"),
])
def test_kind_boundaries(weights, expected):
    assert classify_kind(weights, sum(w for _, w in weights), profile_for("bike")) == expected


def test_long_uses_floor_and_recent_longest():
    p = profile_for("bike")
    assert classify_kind([(2, 6000)], 6000, p) == "long"
    assert classify_kind([(2, 6000)], 6000, p, recent_longest=9000) == "endurance"
    assert classify_kind([(2, 5000)], 5000, p) == "endurance"


@pytest.mark.parametrize("kind", ["race", "opener", "warmup"])
def test_non_stimulus_kinds_return_none(kind):
    assert planned_dose(session(kind=kind, structured=bike_threshold_structure()), ATHLETE) is None
    assert executed_dose(workout(kind=kind), ATHLETE) is None


def test_unsupported_sport_returns_none_without_raising():
    assert profile_for("strength") is None
    assert planned_dose(session("strength"), ATHLETE) is None
    assert executed_dose(workout("strength"), ATHLETE) is None


def test_walk_leaves_handles_distance_and_time_only_filter():
    st = WorkoutStructure(items=[
        step("interval", "distance_m", 200, zone="Z4", modality="swim"),
        step("interval", "time_s", 60, zone="Z4", modality="swim"),
    ])
    assert len(walk_leaves(st)) == 2
    assert [leaf.duration_s for leaf in walk_leaves(st, time_only=True)] == [60.0]


def test_pace_zone_rank_midpoint_gaps():
    assert [pace_zone_rank(p, 90.0) for p in (85, 90, 93, 97, 105)] == [5, 4, 3, 2, 1]


def bike_intervals(efforts, **kw):
    return WorkoutIntervals(efforts_detected=len(efforts), detection_basis="power", efforts=efforts, **kw)


def effort(n, start, dur, avg_w):
    return IntervalEffort(n=n, start_s=start, duration_s=dur, avg_w=avg_w, verdict="ok")


def test_bike_executed_from_intervals_with_completion():
    iv = bike_intervals(
        [effort(1, 600, 600, 245), effort(2, 1500, 600, 244), effort(3, 2400, 480, 238)],
        reps_completed=3, reps_in_band_pct=100.0, fade_across_reps_pct=2.0,
    )
    s = session(structured=bike_threshold_structure())
    w = workout(analytics=WorkoutAnalytics(intervals=iv), rpe=7)
    e = executed_dose(w, ATHLETE, s)
    assert e.dose.kind == "threshold" and e.dose.work_s == 1680 and e.dose.rep_count == 3
    assert e.completion_pct == pytest.approx(1680 / 1800 * 100)
    assert e.in_band_pct == 100.0 and e.fade_pct == 2.0 and e.rpe == 7 and e.planned
    assert e.dose.work_rest_ratio == pytest.approx(1680 / 600)


def test_bike_unstructured_ride_from_free_ride_zones():
    zones = [FreeRideZoneTime(zone="Z1", seconds=600, pct=10), FreeRideZoneTime(zone="Z2", seconds=3000, pct=60),
             FreeRideZoneTime(zone="Z3", seconds=1200, pct=30)]
    w = workout(analytics=WorkoutAnalytics(free_ride=FreeRideRead(moving_s=4800, coasting_s=0, coasting_pct=0,
                                                                 zero_or_null_power_pct=0, power_zones=zones)))
    e = executed_dose(w, ATHLETE)
    assert e.dose.kind == "tempo" and e.dose.work_s == 1200 and e.completion_pct is None and not e.planned


def test_bike_whole_ride_falls_back_to_average_power_estimated():
    w = workout(analytics=WorkoutAnalytics(avg_power_w=170.0), duration_min=90)
    e = executed_dose(w, ATHLETE)
    assert e.dose.kind == "long" and e.dose.confidence == "estimated"


def swim_sets_analytics(reps, unit="m"):
    sets = [SwimSet(count=len(reps), rep_distance=100, avg_pace_s_per_100=90, total_distance=100 * len(reps),
                    description="x", reps=reps)]
    return WorkoutAnalytics(swim_sets=sets, pool_unit=unit)


def rep(i, pace, dist=100, rest=15.0):
    return SwimRep(start_offset_s=i * 120, distance=dist, swim_time_s=pace * dist / 100, pace_s_per_100=pace, rest_after_s=rest)


def test_swim_executed_from_sets_with_completion_and_in_band():
    st = WorkoutStructure(items=[
        WorkoutRepeat(count=8, steps=[step("interval", "distance_m", 100, zone="Z4", modality="swim"),
                                      step("rest", "time_s", 15, modality="swim")]),
    ])
    s = session("swim_pool", st, zone="Z4")
    reps = [rep(i, 90) for i in range(6)] + [rep(6, 105), rep(7, 105)]
    w = workout("swim_pool", swim_sets_analytics(reps), distance_m=800)
    e = executed_dose(w, ATHLETE, s)
    assert e.dose.kind == "threshold" and e.dose.work_m == 600 and e.dose.rep_count == 6
    assert e.completion_pct == pytest.approx(75.0)
    assert e.in_band_pct == 100.0 and e.dose.work_rest_ratio is not None


def test_swim_yard_pool_converted_to_metres():
    reps = [rep(i, 82.3, dist=100) for i in range(4)]  # per 100 yd 82.3 -> ~90 s/100 m
    w = workout("swim_pool", swim_sets_analytics(reps, unit="yd"))
    e = executed_dose(w, ATHLETE)
    assert e.dose.work_m == pytest.approx(365.76)
    assert e.dose.kind == "threshold"


def test_swim_whole_workout_pace_fallback():
    w = workout("swim_pool", None, distance_m=2000, duration_min=36.0)  # 108 s/100 m -> Z1/Z2
    e = executed_dose(w, ATHLETE)
    assert e.dose.confidence == "estimated" and e.dose.work_m == 2000 and e.dose.kind == "endurance"


def test_swim_without_css_has_no_executed_dose_unplanned():
    a = Athlete(id=AID, slug="t", name="T")
    assert executed_dose(workout("swim_pool", None, distance_m=2000), a) is None


def test_ow_swim_shares_the_swim_profile():
    assert profile_for("swim_ow") is profile_for("swim_pool")
