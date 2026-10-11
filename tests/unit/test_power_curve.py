"""Mean-maximal power curve: ground truth from intervals.icu on the real 10/10 ride."""

from __future__ import annotations

import json
from pathlib import Path

from swim_coach.models import PowerCurvePoint
from swim_coach.power_curve import annotate_bests, power_curve, standard_durations

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "ride_2026_10_10_starts_race_pace.json"

# intervals.icu best mean power, nulls as 0.
GROUND_TRUTH = {1: 1100, 2: 1069, 5: 956, 10: 845, 15: 794, 20: 737, 30: 624, 60: 353, 180: 281}


def _curve(power: list, t_s: list | None = None):
    n = len(power)
    return power_curve({"t_s": t_s if t_s is not None else list(range(n)), "power_w": power})


def test_matches_intervals_icu_ground_truth_on_real_ride():
    curve = {p.duration_s: p for p in power_curve(json.loads(FIX.read_text())["series"])}
    for dur, watts in GROUND_TRUTH.items():
        assert abs(curve[dur].watts - watts) <= 2, (dur, curve[dur].watts, watts)
    assert 1430 <= curve[1].start_s <= 2520  # the best second is inside the starts block


def test_no_power_channel_returns_none():
    assert power_curve(None) is None
    assert power_curve({"t_s": [0, 1, 2], "hr": [100, 100, 100]}) is None
    assert power_curve({"t_s": [0, 1, 2], "power_w": [None, None, None]}) is None


def test_durations_skip_those_longer_than_ride():
    c = _curve([200.0] * 100)
    assert [p.duration_s for p in c] == [1, 2, 5, 10, 15, 20, 30, 60]


def test_standard_duration_set_extends_every_30_min():
    d = standard_durations(3 * 3600)
    assert d[-3:] == [7200, 9000, 10800]
    assert 5400 in d and 3600 in d and 9000 in d


def test_nulls_count_as_zero():
    c = _curve([300.0, None, 300.0, None])
    assert {p.duration_s: p.watts for p in c} == {1: 300, 2: 150}


def test_best_window_start_offset():
    c = _curve([100.0] * 10 + [500.0] * 5 + [100.0] * 10)
    five = next(p for p in c if p.duration_s == 5)
    assert (five.watts, five.start_s) == (500, 10.0)


def test_short_gap_filled_with_zero_long_gap_is_a_pause():
    # gap of 4 s (dropout) -> three zeros counted as riding: samples at 0,1,2,3,4,5.
    c = _curve([400.0, 400.0, 400.0], t_s=[0, 1, 5])
    assert next(p for p in c if p.duration_s == 5).watts == 160  # best 5 s = (400+400+0+0+0)/5
    # 600 s gap (timer pause) -> collapsed: 400 W both sides joins into a 4 s block.
    c = _curve([400.0, 400.0, 400.0, 400.0], t_s=[0, 1, 601, 602])
    four = {p.duration_s: p.watts for p in c}
    assert four[2] == 400 and 5 not in four  # only 4 s of riding time exist


def test_annotate_bests_flags_and_unknowns():
    cur = [PowerCurvePoint(duration_s=5, watts=900, start_s=0), PowerCurvePoint(duration_s=60, watts=300, start_s=0)]
    prior = [
        (10, [PowerCurvePoint(duration_s=5, watts=950, start_s=0)]),
        (60, [PowerCurvePoint(duration_s=5, watts=800, start_s=0), PowerCurvePoint(duration_s=60, watts=250, start_s=0)]),
        (120, [PowerCurvePoint(duration_s=5, watts=2000, start_s=0)]),  # outside 90 d
    ]
    out = {p.duration_s: p for p in annotate_bests(cur, prior)}
    assert (out[5].best_42d_w, out[5].is_best_42d) == (950, False)
    assert (out[5].best_90d_w, out[5].is_best_90d) == (950, False)
    assert (out[60].best_42d_w, out[60].is_best_42d) == (None, None)
    assert (out[60].best_90d_w, out[60].is_best_90d) == (250, True)
    assert annotate_bests(cur, []) [0].is_best_90d is None
