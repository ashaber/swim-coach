"""Prior-race average power curve for the race view (`swim_coach.race_curve_compare`)."""

from __future__ import annotations

import uuid
from datetime import date

from swim_coach.models import PowerCurvePoint, Workout, WorkoutAnalytics
from swim_coach.race_curve_compare import prior_race_curve

CX = "cycling/cyclocross"
MTB = "cycling/mountain"
PLAN = (date(2026, 9, 28), date(2026, 11, 29))


def _curve(watts_by_duration: dict[int, int]) -> list[PowerCurvePoint]:
    return [PowerCurvePoint(duration_s=d, watts=w, start_s=0.0) for d, w in watts_by_duration.items()]


def _race(day: date, detail: str | None = CX, curve: dict[int, int] | None = None, minutes: float = 45) -> Workout:
    pc = _curve(curve if curve is not None else {5: 600, 60: 400, 600: 300})
    return Workout(id=uuid.uuid4(), athlete_id=uuid.uuid4(), date=day, sport="bike", source="fit", kind="race",
                   sport_detail=detail, duration_min=minutes, distance_m=1000,
                   analytics=WorkoutAnalytics(power_curve=pc or None))


def _pts(r) -> dict[int, tuple[int, int]]:
    return {p.duration_s: (p.watts, p.n) for p in r.points}


def test_averages_prior_cx_races_on_the_plan_pointwise() -> None:
    a = _race(date(2026, 10, 3), curve={5: 600, 60: 400})
    b = _race(date(2026, 10, 10), curve={5: 800, 60: 500})
    cur = _race(date(2026, 10, 17))
    r = prior_race_curve(cur, [a, b, cur], PLAN)
    assert r.basis == "plan" and r.count == 2
    assert _pts(r) == {5: (700, 2), 60: (450, 2)}
    assert r.dates == [date(2026, 10, 3), date(2026, 10, 10)]
    assert r.label == "Avg of 2 prior CX races"


def test_an_mtb_race_never_enters_a_cx_average() -> None:
    cx1, cx2 = _race(date(2026, 10, 3)), _race(date(2026, 10, 10))
    mtb = _race(date(2026, 10, 12), detail=MTB, curve={5: 100, 60: 100, 600: 100})
    cur = _race(date(2026, 10, 17))
    r = prior_race_curve(cur, [cx1, cx2, mtb, cur], PLAN)
    assert r.count == 2 and _pts(r)[5] == (600, 2)
    r2 = prior_race_curve(_race(date(2026, 10, 20), detail=MTB, minutes=60), [cx1, cx2, mtb], PLAN)
    assert r2.count == 1 and r2.dates == [date(2026, 10, 12)]


def test_ultra_mtb_only_compares_with_ultras() -> None:
    xc = _race(date(2026, 4, 1), detail=MTB, minutes=90)
    ultra1 = _race(date(2026, 5, 1), detail=MTB, minutes=600, curve={5: 500, 3600: 200})
    ultra2 = _race(date(2026, 5, 20), detail=MTB, minutes=700, curve={5: 700, 3600: 300})
    cur = _race(date(2026, 6, 13), detail=MTB, minutes=800)
    r = prior_race_curve(cur, [xc, ultra1, ultra2, cur], (date(2026, 3, 1), date(2026, 7, 1)))
    assert r.count == 2 and r.label == "Avg of 2 prior ultra MTB races"


def test_current_plan_beats_prior_year() -> None:
    old = _race(date(2025, 11, 1), curve={5: 100, 60: 100})
    on_plan1, on_plan2 = _race(date(2026, 10, 3)), _race(date(2026, 10, 10))
    cur = _race(date(2026, 10, 17))
    r = prior_race_curve(cur, [old, on_plan1, on_plan2, cur], PLAN)
    assert r.basis == "plan" and r.count == 2 and old.date not in r.dates


def test_falls_back_to_prior_year_when_none_on_the_plan() -> None:
    old1, old2 = _race(date(2025, 11, 1), curve={5: 500, 60: 300}), _race(date(2025, 11, 8), curve={5: 700, 60: 500})
    too_old = _race(date(2024, 1, 1))
    cur = _race(date(2026, 10, 3))
    r = prior_race_curve(cur, [old1, old2, too_old, cur], PLAN)
    assert r.basis == "prior_year" and r.count == 2
    assert _pts(r) == {5: (600, 2), 60: (400, 2)}
    assert r.label == "Avg of 2 prior CX races (prior year)"


def test_nothing_available_gives_no_points_and_a_reason() -> None:
    cur = _race(date(2026, 10, 3))
    r = prior_race_curve(cur, [cur], PLAN, history_start=date(2026, 8, 27))
    assert r.points == [] and r.count == 0 and r.basis == "none"
    assert "No earlier CX races" in r.note and "2026-08-27" in r.note


def test_excludes_this_race_and_later_ones() -> None:
    early = _race(date(2026, 10, 3))
    cur = _race(date(2026, 10, 17))
    later = _race(date(2026, 10, 18))
    same_day = _race(date(2026, 10, 17))
    r = prior_race_curve(cur, [early, cur, later, same_day], PLAN)
    assert r.dates == [early.date] and r.basis == "plan"
    assert r.label == "Prior CX race (2026-10-03)"


def test_day_two_includes_day_one() -> None:
    day1, day2 = _race(date(2026, 10, 17)), _race(date(2026, 10, 18))
    r = prior_race_curve(day2, [day1, day2], PLAN)
    assert r.dates == [day1.date]


def test_short_races_drop_out_at_long_durations_and_line_stops_below_two() -> None:
    long1 = _race(date(2026, 10, 3), curve={5: 600, 60: 400, 600: 300, 1800: 250})
    long2 = _race(date(2026, 10, 10), curve={5: 800, 60: 500, 600: 340, 1800: 270})
    short = _race(date(2026, 10, 12), curve={5: 700, 60: 450})
    cur = _race(date(2026, 10, 17))
    r = prior_race_curve(cur, [long1, long2, short, cur], PLAN)
    assert r.count == 3
    assert _pts(r) == {5: (700, 3), 60: (450, 3), 600: (320, 2), 1800: (260, 2)}
    r2 = prior_race_curve(cur, [long1, short, cur], PLAN)
    assert _pts(r2) == {5: (650, 2), 60: (425, 2)}  # 600 s only has one contributor -> stop


def test_single_prior_race_is_labelled_as_a_single_race() -> None:
    only = _race(date(2026, 10, 3), curve={5: 600, 60: 400, 600: 300})
    cur = _race(date(2026, 10, 17))
    r = prior_race_curve(cur, [only, cur], PLAN)
    assert r.single is True and r.count == 1
    assert _pts(r) == {5: (600, 1), 60: (400, 1), 600: (300, 1)}
    assert r.label == "Prior CX race (2026-10-03)"


def test_unclassified_and_curveless_races_are_left_out_and_said_so() -> None:
    good1, good2 = _race(date(2026, 10, 3)), _race(date(2026, 10, 10))
    unknown = _race(date(2026, 10, 5), detail=None)
    nopower = _race(date(2026, 10, 6), curve={})
    cur = _race(date(2026, 10, 17))
    r = prior_race_curve(cur, [good1, good2, unknown, nopower, cur], PLAN)
    assert r.count == 2
    assert any("no discipline" in s for s in r.left_out) and any("no power" in s for s in r.left_out)


def test_current_race_without_a_discipline_gets_a_note_not_a_guess() -> None:
    cur = _race(date(2026, 10, 17), detail=None)
    r = prior_race_curve(cur, [_race(date(2026, 10, 3)), cur], PLAN)
    assert r.points == [] and "discipline" in r.note


def test_no_plan_range_goes_straight_to_prior_year() -> None:
    a, b = _race(date(2026, 10, 3)), _race(date(2026, 10, 10))
    cur = _race(date(2026, 10, 17))
    r = prior_race_curve(cur, [a, b, cur], None)
    assert r.basis == "prior_year" and r.count == 2


def test_context_and_analyzer_attach_the_average_to_a_race_only(tmp_path) -> None:
    from swim_coach.analysis import analyze_workout, build_analysis_context
    from swim_coach.models import Athlete, MacroBlock, MacroPlan
    from swim_coach.store import FileStore

    store = FileStore(base_dir=tmp_path)
    athlete = Athlete(id=uuid.uuid4(), slug="a", name="A")
    store.save_athlete(athlete)
    block = MacroBlock(name="build", start_date=date(2026, 9, 28), end_date=date(2026, 11, 29),
                       weekly_volume_target_m=0, focus="x")
    store.save_macro("a", MacroPlan(id=uuid.uuid4(), athlete_id=athlete.id, event_id=uuid.uuid4(), blocks=[block]))
    a, b = _race(date(2026, 10, 3), curve={5: 600, 60: 400}), _race(date(2026, 10, 10), curve={5: 800, 60: 500})
    mtb = _race(date(2026, 10, 12), detail=MTB)
    cur = _race(date(2026, 10, 17))
    for w in (a, b, mtb, cur):
        w.kind_override = "race"  # the context re-derives `kind`; the override is what keeps a race a race
        store.save_workout("a", w)
    series = {"t_s": [float(i) for i in range(120)], "power_w": [300.0] * 120}
    ctx = build_analysis_context(store, "a", cur, series=series)
    out = analyze_workout(cur, ctx)
    assert out.prior_race_curve is not None
    assert out.prior_race_curve.basis == "plan" and out.prior_race_curve.count == 2

    ride = _race(date(2026, 10, 20))
    ride.kind = "free_ride"
    ctx2 = build_analysis_context(store, "a", ride, series=series)
    assert analyze_workout(ride, ctx2).prior_race_curve is None
