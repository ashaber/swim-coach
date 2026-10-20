"""The section drill-down: 1 Hz passes, equal-distance pieces and their efficiency verdicts."""

from __future__ import annotations

import pytest

from swim_coach.section_detail import build_section_detail, classify_piece, piece_count
from test_course_sectors_race_view import _build, _series


@pytest.mark.parametrize("duration,expected", [(4.0, 1), (9.0, 1), (16.0, 2), (23.0, 2), (57.0, 6), (300.0, 8)])
def test_pieces_are_about_ten_seconds_long_between_one_and_eight(duration: float, expected: int) -> None:
    assert piece_count(duration) == expected


OTHERS = [(10.0, 200.0), (10.2, 200.0), (9.8, 200.0)]


@pytest.mark.parametrize(
    "time_s,power_w,expected",
    [
        (9.3, 190.0, "free"),      # faster by more than the noise, on no more watts
        (9.3, 230.0, "bought"),    # faster on 30 W more
        (10.7, 150.0, "saved"),    # slower on 50 W less
        (10.7, 200.0, "lost"),     # slower on the same watts
        (10.7, 230.0, "lost"),     # slower on more watts
        (10.1, 100.0, "par"),      # inside the timing noise
    ],
)
def test_piece_verdicts(time_s: float, power_w: float, expected: str) -> None:
    assert classify_piece(time_s, power_w, OTHERS, sigma_s=0.4) == expected


@pytest.fixture(scope="module")
def detail():
    laps, cs = _build(section_splits={"C1": 2})
    return cs, build_section_detail(_series(), laps, cs)


def test_outline_is_a_short_list_of_xy_pairs(detail) -> None:
    _, d = detail
    assert 2 < len(d["outline"]) <= 400 and all(len(p) == 2 for p in d["outline"])


def test_sections_are_keyed_by_label_including_split_labels(detail) -> None:
    cs, d = detail
    assert list(d["sections"]) == [s.label for s in cs.sectors]
    assert "C1a" in d["sections"] and "C1b" in d["sections"]


def test_every_lap_has_points_and_graded_pieces(detail) -> None:
    cs, d = detail
    for label, sec in d["sections"].items():
        x0, y0, x1, y1 = sec["bbox"]
        assert set(sec["laps"]) == {str(l.lap) for l in cs.laps}
        for lap in sec["laps"].values():
            assert all(len(p) == 4 and x0 <= p[0] <= x1 and y0 <= p[1] <= y1 for p in lap["points"])
            for piece in lap["pieces"]:
                assert 0 <= piece["from_i"] <= piece["to_i"] < len(lap["points"])
                assert piece["eff"] in {"free", "bought", "saved", "lost", "par"}
                assert piece["loss_s"] >= 0 and isinstance(piece["within_noise"], bool)


def test_piece_times_add_up_to_the_pass_and_one_lap_is_fastest_on_each_piece(detail) -> None:
    cs, d = detail
    for label, sec in d["sections"].items():
        k = [s.label for s in cs.sectors].index(label)
        n = len(next(iter(sec["laps"].values()))["pieces"])
        for lap in cs.laps:
            pieces = sec["laps"][str(lap.lap)]["pieces"]
            assert sum(p["time_s"] for p in pieces) == pytest.approx(lap.sector_times_s[k], abs=0.1)
        for i in range(n):
            assert min(l["pieces"][i]["loss_s"] for l in sec["laps"].values()) == 0


def test_points_are_one_second_padded_samples(detail) -> None:
    cs, d = detail
    k = 0
    lap = cs.laps[1]
    points = d["sections"][cs.sectors[k].label]["laps"][str(lap.lap)]["points"]
    assert len(points) == pytest.approx(lap.sector_times_s[k] + 2, abs=1.01)


def test_no_gps_no_detail() -> None:
    laps, cs = _build()
    series = {k: v for k, v in _series().items() if k not in ("lat", "lng")}
    assert build_section_detail(series, laps, cs) is None
