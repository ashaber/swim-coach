"""Race overview, the first 40 s, the finish sprint, and the previous-race pick.

Fixtures are the real 2026-10-17 (Saturday) and 2026-10-18 (Sunday) CX races, power and speed only (no GPS).
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path

import pytest

from swim_coach.bike_coach_view import race_view_lines
from swim_coach.models import CanonicalLap, RaceStartTrace, Workout, WorkoutAnalytics
from swim_coach.race_view import (
    build_finish_sprint,
    build_race_overview,
    build_race_start_trace,
    finish_s,
    pick_previous_race_start,
)

DATA = json.loads((Path(__file__).parent / "fixtures" / "race_view" / "start_finish.json").read_text())
SUN, SAT = DATA["race_1018.fit"], DATA["race_1017.fit"]


def _series(cut: dict) -> dict:
    n = len(cut["power_w"])
    return {"t_s": [cut["t0"] + i for i in range(n)], "power_w": cut["power_w"], "speed_mps": cut["speed_mps"]}


def test_sunday_start_matches_the_file() -> None:
    t = build_race_start_trace(_series(SUN["start"]), SUN["start_s"])
    assert t.power_w[:8] == [469, 933, 539, 573, 652, 702, 597, 242]
    assert (t.peak_w, t.peak_at_s) == (933, 1)
    assert t.mean_15s_w == pytest.approx(588, abs=1)
    assert t.top_speed_kmh == pytest.approx(37, abs=0.5) and t.top_speed_at_s == 13
    assert len(t.power_w) == len(t.speed_kmh) == 40
    assert t.dip is not None and (t.dip.at_s, t.dip.power_w) == (7, 242)  # 242 W < half of the 588 W 15 s mean
    assert t.previous is None


def test_saturday_start_has_no_dip() -> None:
    t = build_race_start_trace(_series(SAT["start"]), SAT["start_s"])
    assert t.mean_15s_w == pytest.approx(743, abs=1)
    assert t.top_speed_kmh == pytest.approx(40, abs=0.6)
    assert t.dip is None


def test_saturday_finishes_with_a_sprint_to_the_line() -> None:
    s = build_finish_sprint(_series(SAT["finish"]) | {"t_s": [SAT["finish_s"] - 60 + i for i in range(65)]}, SAT["finish_s"], SAT["np_w"])
    assert s is not None
    assert (s.duration_s, s.avg_w, s.peak_w) == (8, 801, 932)
    assert s.entry_speed_kmh == pytest.approx(10, abs=0.5) and s.exit_speed_kmh == pytest.approx(34, abs=0.5)
    assert len(s.power_w) == len(s.speed_kmh) == 15
    assert s.power_w[-1] == 699 and s.power_w[-2] == 776  # the last sample is the second that ends at the line


def test_sunday_has_no_finish_sprint() -> None:
    series = _series(SUN["finish"]) | {"t_s": [SUN["finish_s"] - 60 + i for i in range(65)]}
    assert build_finish_sprint(series, SUN["finish_s"], SUN["np_w"]) is None


def test_a_hard_effort_far_from_the_line_is_not_a_sprint() -> None:
    power = [200.0] * 120
    power[50:56] = [700.0] * 6  # 6 s at ~3x NP, but 60 s before the line
    series = {"t_s": [float(i) for i in range(120)], "power_w": power, "speed_mps": [8.0] * 120}
    assert build_finish_sprint(series, 120.0, 200) is None
    power[110:116] = [700.0] * 6
    assert build_finish_sprint(series, 120.0, 200) is not None


def test_overview_covers_only_the_race_window() -> None:
    n = 200
    series = {
        "t_s": [float(i) for i in range(n)],
        "power_w": [0.0] * 50 + [200.0] * 100 + [0.0] * 50,  # warm-up/wait, 100 s of racing, roll-out
        "hr": [100] * 50 + [150] * 100 + [90] * 50,
        "speed_mps": [0.0] * 50 + [6.0] * 100 + [1.0] * 50,
        "cadence_rpm": [0.0] * 50 + [80.0] * 90 + [0.0] * 10 + [0.0] * 50,
        "dist_m": [0.0] * 50 + [6.0 * i for i in range(100)] + [594.0] * 50,
        "grit": [0.0] * 50 + [1000.0] * 100 + [5000.0] * 50,
    }
    o = build_race_overview(series, 50.0, 150.0)
    assert (o.duration_s, o.avg_hr, o.max_hr, o.avg_power_w, o.max_power_w, o.work_kj) == (100.0, 150, 150, 200, 200, 20)
    assert o.avg_speed_kmh == pytest.approx(21.6) and o.avg_cadence_rpm == 80
    assert o.total_grit == pytest.approx(100.0) and o.distance_m == 594


def test_overview_leaves_missing_channels_null() -> None:
    o = build_race_overview({"t_s": [float(i) for i in range(100)], "power_w": [150.0] * 100}, 10.0, 90.0)
    assert o.avg_hr is None and o.avg_speed_kmh is None and o.total_grit is None and o.avg_power_w == 150


def _lap(n: int, a: float, b: float, comparable: bool) -> CanonicalLap:
    return CanonicalLap(n=n, start_s=a, end_s=b, duration_s=b - a, source="gps", comparable=comparable)


def test_the_finish_line_is_the_end_of_the_last_comparable_lap_not_a_trailing_fragment() -> None:
    laps = [_lap(1, 0, 150, False), _lap(2, 150, 500, True), _lap(3, 500, 850, True), _lap(4, 850, 881, False)]
    assert finish_s(laps) == 850
    assert finish_s([_lap(1, 0, 100, False)]) is None


def _race(day: int, detail: str, with_start: bool, started: bool = False) -> Workout:
    analytics = WorkoutAnalytics(race_start=RaceStartTrace(
        power_w=[500] * 40, speed_kmh=[30.0] * 40, peak_w=500, peak_at_s=0, mean_5s_w=500, mean_15s_w=480,
        top_speed_kmh=31.5, top_speed_at_s=10)) if with_start else WorkoutAnalytics()
    return Workout(id=uuid.uuid4(), athlete_id=uuid.uuid4(), date=date(2026, 10, day), sport="bike", source="fit",
                   kind="race", sport_detail=detail, analytics=analytics, distance_m=1000, duration_min=45)


def test_previous_race_start_is_the_latest_earlier_race_of_the_same_kind_with_a_start() -> None:
    current = _race(18, "cycling/cyclocross", True)
    older = _race(10, "cycling/cyclocross", True)
    sat = _race(17, "cycling/cyclocross", True)
    other_kind = _race(16, "cycling/road", True)
    no_start = _race(17, "cycling/cyclocross", False)
    later = _race(19, "cycling/cyclocross", True)
    prev = pick_previous_race_start([older, sat, other_kind, no_start, later, current], current)
    assert prev is not None and prev.workout_id == str(sat.id) and prev.date == date(2026, 10, 17)
    assert prev.mean_15s_w == 480 and len(prev.power_w) == 40 and prev.top_speed_kmh == 31.5
    assert pick_previous_race_start([later], current) is None


def test_coach_lines_are_terse_and_mention_the_dip_and_the_previous_race() -> None:
    t = build_race_start_trace(_series(SUN["start"]), SUN["start_s"])
    o = build_race_overview({"t_s": [float(i) for i in range(100)], "power_w": [200.0] * 100, "hr": [150] * 100}, 0.0, 100.0)
    lines = race_view_lines(o.model_dump(mode="json"), t.model_dump(mode="json"), None)
    assert "242 W at 7s" in lines["race_start_trace"] and "200 W" in lines["race_overview"]
    assert "finish_sprint" not in lines
    assert sum(len(v) for v in lines.values()) < 600
