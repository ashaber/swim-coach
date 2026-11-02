"""The race-window power curve: a race recorded after a warm-up in one file (`analytics.race_power_curve`)."""

from __future__ import annotations

import uuid
from datetime import date

from swim_coach.analysis import AnalysisContext
from swim_coach.models import PowerCurvePoint, Workout, WorkoutAnalytics
from swim_coach.power_curve import power_curve
from swim_coach.race_curve_compare import prior_race_curve

CX = "cycling/cyclocross"
PLAN = (date(2026, 9, 28), date(2026, 11, 29))
START = 1800


def _series(warm_w: int = 400, race_w: int = 250, pause: tuple[int, int] | None = None) -> dict:
    """Idle at 100 W to t=1200, a 600 s warm-up effort at `warm_w` W, then a 1200 s race at `race_w` W.
    `pause` = (after_i, seconds): the timer stops, so t_s jumps while riding time does not."""
    t, p, jump = [], [], 0
    for i in range(START + 1200):
        if pause and i == pause[0]:
            jump += pause[1]
        t.append(i + jump)
        p.append(100 if i < 1200 else warm_w if i < START else race_w)
    return {"t_s": t, "power_w": p}


def _bike(day: date = date(2026, 10, 17)) -> Workout:
    return Workout(id=uuid.uuid4(), athlete_id=uuid.uuid4(), date=day, sport="bike", source="fit", kind="race",
                   sport_detail=CX, duration_min=50, distance_m=1000, analytics=WorkoutAnalytics())


def _analyze(series: dict, start: float | None = START, prior: tuple = ()) -> WorkoutAnalytics:
    ctx = AnalysisContext(kind="race", series=series, race_start_s=start, prior_workouts=prior)
    return _bike().analyze(ctx)


def _by(curve) -> dict[int, int]:
    return {p.duration_s: p.watts for p in curve}


def test_warmup_effort_is_out_of_the_race_curve_but_stays_in_the_whole_file_curve() -> None:
    a = _analyze(_series())
    race, whole = _by(a.race_power_curve), _by(a.power_curve)
    assert race[600] == 250 and whole[600] == 400
    assert all(p.start_s >= START for p in a.race_power_curve)


def test_duration_longer_than_the_race_window_is_absent() -> None:
    a = _analyze(_series())
    assert 1800 in _by(a.power_curve) and 1800 not in _by(a.race_power_curve)


def test_race_only_file_race_curve_equals_whole_file_curve() -> None:
    series = {"t_s": list(range(1200)), "power_w": [200 + (i % 50) for i in range(1200)]}
    a = _analyze(series, start=0)
    key = lambda c: [(p.duration_s, p.watts, p.start_s) for p in c]
    assert key(a.race_power_curve) == key(a.power_curve)


def test_no_start_means_no_race_curve_and_unchanged_whole_curve() -> None:
    a = _analyze(_series(), start=None)
    assert a.race_power_curve is None and a.power_curve
    assert _by(a.power_curve) == _by(power_curve(_series()))


def test_race_curve_uses_the_same_time_base_as_the_overview_across_a_pause() -> None:
    series = _series(pause=(1500, 3000))  # a long stop in the warm-up: the race starts at t_s 4800
    a = _analyze(series, start=START + 3000)
    assert a.race_overview.start_s == START + 3000
    assert _by(a.race_power_curve)[600] == 250 and _by(a.power_curve)[600] == 400
    assert all(p.start_s >= START + 3000 for p in a.race_power_curve)
    assert max(_by(a.race_power_curve)) <= 1200


def test_race_curve_is_annotated_with_42_day_bests_from_earlier_whole_file_curves() -> None:
    earlier = _bike(date(2026, 10, 10)).model_copy(update={"analytics": WorkoutAnalytics(
        power_curve=[PowerCurvePoint(duration_s=600, watts=240, start_s=0.0)])})
    a = _analyze(_series(), prior=(earlier,))
    p = next(p for p in a.race_power_curve if p.duration_s == 600)
    assert (p.best_42d_w, p.is_best_42d) == (240, True)
    assert next(p for p in a.power_curve if p.duration_s == 600).best_42d_w == 240  # whole-file bests unchanged


def test_old_rows_without_the_field_validate() -> None:
    assert WorkoutAnalytics.model_validate({}).race_power_curve is None


def _stored(day: date, whole: dict[int, int], race: dict[int, int] | None) -> Workout:
    mk = lambda d: [PowerCurvePoint(duration_s=k, watts=v, start_s=0.0) for k, v in d.items()]
    return _bike(day).model_copy(update={"analytics": WorkoutAnalytics(power_curve=mk(whole), race_power_curve=mk(race) if race else None)})


def test_prior_average_uses_race_curves_with_whole_file_fallback_and_says_so() -> None:
    a = _stored(date(2026, 10, 3), {600: 400}, {600: 250})
    b = _stored(date(2026, 10, 10), {600: 300}, None)  # no detected start: whole file
    r = prior_race_curve(_bike(), [a, b], PLAN)
    assert {p.duration_s: p.watts for p in r.points} == {600: 275}
    assert r.left_out == ["1 earlier CX race(s) averaged from the whole file (no race start detected)"]


def test_prior_average_unchanged_when_no_race_has_a_window_curve() -> None:
    a = _stored(date(2026, 10, 3), {600: 400}, None)
    b = _stored(date(2026, 10, 10), {600: 300}, None)
    r = prior_race_curve(_bike(), [a, b], PLAN)
    assert r.points[0].watts == 350
    assert r.left_out == ["2 earlier CX race(s) averaged from the whole file (no race start detected)"]
