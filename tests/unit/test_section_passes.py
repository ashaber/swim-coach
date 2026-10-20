"""Per-pass efficiency of a repeated course section: terrain, who spent extra watts, free speed."""

from __future__ import annotations

import pytest

from swim_coach.models import SectorPass
from swim_coach.section_passes import (
    FREE_SPEED_MAX,
    efficiency_applies,
    free_speed,
    pass_extras,
    terrain_of,
)


@pytest.mark.parametrize("dalt,expected", [(-3.6, "descent"), (-2.0, "descent"), (-1.9, "flat"), (0.0, "flat"), (1.99, "flat"), (2.0, "climb"), (6.0, "climb")])
def test_terrain_from_net_altitude_change(dalt: float, expected: str) -> None:
    assert terrain_of(dalt) == expected


def test_terrain_is_flat_without_altitude() -> None:
    assert terrain_of(None) == "flat"


@pytest.mark.parametrize(
    "kind,terrain,mean_time,expected",
    [
        ("corners", "flat", 20.0, True),
        ("corners", "climb", 20.0, True),
        ("straight", "descent", 10.0, True),
        ("straight", "descent", 9.9, False),
        ("straight", "climb", 30.0, False),
        ("straight", "flat", 30.0, False),
    ],
)
def test_efficiency_applies(kind: str, terrain: str, mean_time: float, expected: bool) -> None:
    assert efficiency_applies(kind, terrain, mean_time) is expected


def test_extra_watts_is_power_over_the_cheapest_pass_at_least_as_fast() -> None:
    # (time, power): the 16.0 s pass is the fastest and cheapest -> 0 extra; slower passes on more
    # watts than every faster pass pay the difference; a slower pass that is cheaper pays 0.
    passes = [(16.0, 134.0), (16.4, 170.0), (16.9, 183.0), (17.3, 120.0)]
    assert pass_extras(passes, 0.15) == [0.0, 36.0, 49.0, 0.0]


def test_a_pass_within_the_tolerance_counts_as_equally_fast() -> None:
    # 16.1 is within 0.15 s of 16.0, so the 100 W pass is its benchmark; the reverse also holds.
    assert pass_extras([(16.0, 100.0), (16.1, 130.0)], 0.15) == [0.0, 30.0]
    assert pass_extras([(16.0, 130.0), (16.1, 100.0)], 0.15) == [30.0, 0.0]
    # 0.2 s apart: the slower pass is no benchmark for the faster one.
    assert pass_extras([(16.0, 130.0), (16.2, 100.0)], 0.15) == [0.0, 0.0]


def test_extra_watts_none_without_power() -> None:
    assert pass_extras([(16.0, None), (16.5, 100.0)], 0.15) == [None, 0.0]


TOL = {f"C{i}": 0.4 for i in range(1, 7)}  # the section timing sigma


def _p(lap: int, t: float, w: float) -> SectorPass:
    return SectorPass(lap=lap, time_s=t, avg_power_w=w)


def test_free_speed_pairs_a_pass_with_the_costliest_one_it_matched_on_time() -> None:
    passes = {
        "C4": [_p(4, 16.2, 183.0), _p(5, 16.0, 134.0), _p(8, 16.1, 183.0)],
        "C6": [_p(2, 22.9, 260.0), _p(3, 22.7, 190.0)],
        "C1": [_p(3, 23.0, 140.0), _p(5, 23.1, 177.0)],
        "C2": [_p(2, 5.0, 100.0), _p(3, 5.1, 120.0)],  # only 20 W: below the 30 W bar
    }
    found = free_speed(passes, TOL)
    assert [f.label for f in found] == ["C6", "C4", "C1"]
    assert found[1].lap == 5 and found[1].vs_lap == 4  # ties on watts go to the lowest lap number
    assert found[1].watts_saved == pytest.approx(49.0)
    assert found[0].watts_saved == pytest.approx(70.0)
    assert len(found) <= FREE_SPEED_MAX


def test_free_speed_requires_the_pass_to_be_as_fast() -> None:
    # 0.3 s slower than the costly pass: a slower pass on fewer watts is not free speed.
    assert free_speed({"C1": [_p(1, 10.0, 200.0), _p(2, 10.3, 100.0)]}, {"C1": 0.25}) == []


def test_free_speed_caps_at_three_largest_first() -> None:
    passes = {f"C{i}": [_p(1, 10.0, 100.0 + 10 * i), _p(2, 10.0, 100.0)] for i in range(1, 7)}
    found = free_speed(passes, TOL)
    assert [f.label for f in found] == ["C6", "C5", "C4"]


def test_free_speed_skips_short_sections_and_caps_the_time_tolerance() -> None:
    short = [_p(1, 8.0, 180.0), _p(2, 8.1, 60.0)]  # median 8 s: too short to judge
    assert free_speed({"C2": short}, {"C2": 0.4}) == []
    long = [_p(1, 16.0, 200.0), _p(2, 16.35, 120.0)]  # 0.35 s slower: inside sigma 0.5 but over the 0.3 s cap
    assert free_speed({"C4": long}, {"C4": 0.5}) == []
    assert len(free_speed({"C4": [_p(1, 16.0, 200.0), _p(2, 16.25, 120.0)]}, {"C4": 0.5})) == 1
