"""Tests for swim_coach.gps_laps -- pure functions, no I/O, no LLM/network.

Motivating case: a real cyclocross race (Andrew, 2026-09-19) whose device
recorded exactly one native FIT lap for the whole 46.2-minute race (auto-lap
was mis-configured for the profile, and the one manual lap-key press didn't
register either). This module detects the REAL per-course-lap boundaries
from GPS position on a looped course, so a downstream per-lap efficiency
comparison (normalized power vs. speed) becomes possible even when the
device's own lap frames are useless.

Every synthetic GPS track below is built by hand from local-meter offsets
around a small starting lat/lng (see `_offset_latlng`), so expected lap
counts/boundaries are known independent of the code under test.
"""

from __future__ import annotations

import math

import pytest

from swim_coach.gps_laps import (
    GPS_LAP_MIN_AWAY_M,
    GPS_LAP_MIN_DURATION_S,
    GPS_LAP_PROXIMITY_M,
    GpsLap,
    analyze_gps_laps,
    detect_gps_laps,
    haversine_distance_m,
    lap_metrics,
    position_at_offset,
    start_finish_from_laps,
)

START_LAT = 45.0
START_LNG = -122.0
METERS_PER_DEG_LAT = 111_320.0


def _offset_latlng(dx_m: float, dy_m: float, *, lat0: float = START_LAT, lng0: float = START_LNG):
    """(lat, lng) for a point `dx_m` east / `dy_m` north of (lat0, lng0), on
    a local flat-earth approximation -- fine for the small (<1km) synthetic
    tracks these tests use; the code under test itself always uses real
    haversine distance, this is just test-fixture construction."""
    lat = lat0 + dy_m / METERS_PER_DEG_LAT
    meters_per_deg_lng = METERS_PER_DEG_LAT * math.cos(math.radians(lat0))
    lng = lng0 + dx_m / meters_per_deg_lng
    return lat, lng


def _interpolate_path(waypoints: list[tuple[float, float]], step_m: float):
    """Every point along the polyline through `waypoints` (meters offsets),
    spaced ~step_m apart, as a list of (dx_m, dy_m)."""
    points: list[tuple[float, float]] = [waypoints[0]]
    for (x0, y0), (x1, y1) in zip(waypoints, waypoints[1:]):
        seg_len = math.hypot(x1 - x0, y1 - y0)
        n_steps = max(1, round(seg_len / step_m))
        for i in range(1, n_steps + 1):
            f = i / n_steps
            points.append((x0 + (x1 - x0) * f, y0 + (y1 - y0) * f))
    return points


def _square_loop_series(
    n_laps: int,
    *,
    side_m: float = 150.0,
    speed_mps: float = 3.0,
    step_m: float = 6.0,
    extra_channels: bool = False,
):
    """A series dict tracing a `side_m` square loop `n_laps` times, starting
    and finishing each lap at the same corner (dx=dy=0). Perimeter is
    `4 * side_m` = 600m per lap by default; at 3 m/s that's a 200s lap --
    comfortably clear of GPS_LAP_MIN_DURATION_S (120s) and GPS_LAP_MIN_AWAY_M
    (50m, the square's own side length already clears that on the first
    edge)."""
    corners = [(0.0, 0.0), (side_m, 0.0), (side_m, side_m), (0.0, side_m), (0.0, 0.0)]
    one_lap = _interpolate_path(corners, step_m)
    # one_lap's last point duplicates its first (both (0,0)) -- drop the
    # duplicate when chaining laps together so t_s stays strictly increasing
    # and no sample is "at rest" on the line.
    full_path = one_lap[:]
    for _ in range(n_laps - 1):
        full_path.extend(one_lap[1:])

    dt = step_m / speed_mps
    t_s = [i * dt for i in range(len(full_path))]
    lat = []
    lng = []
    for dx, dy in full_path:
        la, lo = _offset_latlng(dx, dy)
        lat.append(la)
        lng.append(lo)

    series: dict = {"t_s": t_s, "lat": lat, "lng": lng}
    if extra_channels:
        series["speed_mps"] = [speed_mps] * len(t_s)
        series["power_w"] = [200.0] * len(t_s)
    return series


# --- haversine_distance_m ------------------------------------------------------------


def test_haversine_distance_zero_for_identical_points():
    assert haversine_distance_m(45.0, -122.0, 45.0, -122.0) == pytest.approx(0.0, abs=1e-6)


def test_haversine_distance_matches_local_offset_approximation():
    # A point ~100m east and ~100m north of the origin, per the same
    # flat-earth offset helper the other tests use -- haversine should agree
    # with that local approximation to within a meter or two at this scale.
    lat2, lng2 = _offset_latlng(100.0, 100.0)
    dist = haversine_distance_m(START_LAT, START_LNG, lat2, lng2)
    assert dist == pytest.approx(math.hypot(100.0, 100.0), abs=2.0)


# --- detect_gps_laps: scenario 1 -- a clear N-times loop --------------------------------


@pytest.mark.parametrize("n_laps", [1, 2, 3, 5])
def test_detect_gps_laps_counts_correct_number_of_loops(n_laps):
    series = _square_loop_series(n_laps)
    laps = detect_gps_laps(series)
    assert len(laps) == n_laps
    for lap in laps:
        assert isinstance(lap, GpsLap)


def test_detect_gps_laps_boundaries_land_near_expected_lap_duration():
    # 600m perimeter @ 3 m/s = 200s/lap.
    series = _square_loop_series(3, side_m=150.0, speed_mps=3.0, step_m=6.0)
    laps = detect_gps_laps(series)
    assert len(laps) == 3
    for lap in laps:
        assert lap.duration_s == pytest.approx(200.0, rel=0.1)
    # Laps are contiguous: each lap's end is the next lap's start.
    assert laps[0].end_s == pytest.approx(laps[1].start_s)
    assert laps[1].end_s == pytest.approx(laps[2].start_s)


def test_detect_gps_laps_indices_are_monotonic_and_in_range():
    series = _square_loop_series(4)
    laps = detect_gps_laps(series)
    n = len(series["t_s"])
    assert len(laps) == 4
    for lap in laps:
        assert 0 <= lap.start_idx < lap.end_idx < n
    for a, b in zip(laps, laps[1:]):
        assert a.end_idx == b.start_idx


# --- detect_gps_laps: scenario 2 -- single point-to-point track (no loop) ---------------


def test_detect_gps_laps_point_to_point_track_detects_zero_laps():
    # A straight line that moves away from the start and never returns --
    # e.g. a point-to-point route, or (Andrew's real motivating case before
    # this feature) a single-lap race read with no native lap boundaries.
    n = 200
    t_s = [float(i * 5) for i in range(n)]
    lat = []
    lng = []
    for i in range(n):
        la, lo = _offset_latlng(i * 20.0, 0.0)  # straight line east, 20m/sample
        lat.append(la)
        lng.append(lo)
    series = {"t_s": t_s, "lat": lat, "lng": lng}
    laps = detect_gps_laps(series)
    assert laps == []


def test_detect_gps_laps_never_leaves_start_area_detects_zero_laps():
    # Never clears GPS_LAP_MIN_AWAY_M -- e.g. a short warm-up spin in the
    # parking lot before the recording is stopped.
    n = 50
    t_s = [float(i * 2) for i in range(n)]
    lat = []
    lng = []
    for i in range(n):
        la, lo = _offset_latlng((i % 5) * 2.0, 0.0)  # wanders within ~8m
        lat.append(la)
        lng.append(lo)
    series = {"t_s": t_s, "lat": lat, "lng": lng}
    laps = detect_gps_laps(series)
    assert laps == []


# --- detect_gps_laps: scenario 3 -- missing/sparse GPS (None samples) -------------------


def test_detect_gps_laps_degrades_gracefully_with_sparse_gps():
    series = _square_loop_series(3)
    # Null out every 4th lat/lng sample (a dropped GPS fix), leaving t_s
    # (and every other channel) intact -- matches parse_files' real
    # convention of allowing per-channel gaps.
    lat = list(series["lat"])
    lng = list(series["lng"])
    for i in range(0, len(lat), 4):
        lat[i] = None
        lng[i] = None
    sparse_series = {"t_s": series["t_s"], "lat": lat, "lng": lng}

    laps = detect_gps_laps(sparse_series)  # must not raise
    assert isinstance(laps, list)
    # Still recovers all 3 laps -- plenty of surviving samples near each
    # crossing given a 4-in-5 dropout only.
    assert len(laps) == 3


def test_detect_gps_laps_too_few_points_returns_empty():
    series = {"t_s": [0.0, 1.0], "lat": [45.0, 45.0001], "lng": [-122.0, -122.0001]}
    assert detect_gps_laps(series) == []


def test_detect_gps_laps_all_none_gps_returns_empty():
    series = {"t_s": [0.0, 1.0, 2.0], "lat": [None, None, None], "lng": [None, None, None]}
    assert detect_gps_laps(series) == []


# --- detect_gps_laps: scenario 4 -- no GPS channel at all -------------------------------


def test_detect_gps_laps_no_lat_lng_channel_returns_empty_not_raises():
    series = {"t_s": [0.0, 60.0, 120.0], "power_w": [200.0, 210.0, 205.0]}
    assert detect_gps_laps(series) == []


def test_detect_gps_laps_empty_series_returns_empty():
    assert detect_gps_laps({}) == []


def test_detect_gps_laps_none_series_handled():
    # Defensive: a caller might pass through a workout with no series at all
    # (store.load_series returns None for that case) without guarding first.
    assert detect_gps_laps(None) == []


# --- detect_gps_laps: threshold behavior -------------------------------------------------


def test_detect_gps_laps_respects_min_lap_duration_rejects_noise_double_trigger():
    # A loop short enough in time that it's well under the default
    # GPS_LAP_MIN_DURATION_S floor -- must not be double-counted as many
    # tiny "laps" from GPS noise near the line.
    series = _square_loop_series(3, side_m=20.0, speed_mps=5.0, step_m=2.0)
    # Perimeter 80m @ 5 m/s = 16s/lap -- far under the 120s floor.
    laps = detect_gps_laps(series)
    assert laps == []


def test_detect_gps_laps_custom_thresholds_override_defaults():
    # A bigger loop than the noise-rejection test above (corners well
    # beyond GPS_LAP_PROXIMITY_M apart, so no interior-corner false
    # triggers) but still short enough in TIME that the default
    # GPS_LAP_MIN_DURATION_S floor (120s) can't resolve each real lap
    # individually: perimeter 400m @ 5 m/s = 80s/lap, so the default
    # rejects the first crossing (80s < 120s) and only confirms one at the
    # SECOND crossing (~156s in, since duration is measured from the last
    # CONFIRMED boundary) -- merging the first two real laps into one
    # detected lap rather than finding 3. An explicit shorter
    # min_lap_duration_s resolves all 3 real laps individually.
    series = _square_loop_series(3, side_m=100.0, speed_mps=5.0, step_m=2.0)
    assert len(detect_gps_laps(series)) != 3
    laps = detect_gps_laps(series, min_lap_duration_s=5.0)
    assert len(laps) == 3


def test_default_thresholds_are_the_documented_values():
    assert GPS_LAP_PROXIMITY_M == 20.0
    assert GPS_LAP_MIN_AWAY_M == 50.0
    assert GPS_LAP_MIN_DURATION_S == 120.0


# --- lap_metrics: scenario 5 -- known hand-constructed power/speed values --------------


def _hand_series():
    # 10 samples, 1 Hz. First 5 samples (lap 1): power alternates so NP
    # (4th-power mean, 4th root) differs materially from a plain average;
    # constant speed 3.0 m/s throughout lap 1. Last 5 samples (lap 2):
    # higher, perfectly flat power (so NP == avg power exactly) and higher
    # speed.
    t_s = list(range(10))
    power_w = [100.0, 300.0, 100.0, 300.0, 100.0, 250.0, 250.0, 250.0, 250.0, 250.0]
    speed_mps = [3.0] * 5 + [4.0] * 5
    return {"t_s": t_s, "power_w": power_w, "speed_mps": speed_mps}


def test_lap_metrics_normalized_power_and_avg_speed_and_efficiency_lap1():
    series = _hand_series()
    lap1 = GpsLap(n=1, start_idx=0, end_idx=4, start_s=0.0, end_s=4.0)
    m = lap_metrics(series, lap1)

    # NP over [100,300,100,300,100] with NP's own rolling-window algorithm
    # (POWER_ROLLING_WINDOW_S=30s >> this 5s span, so the "rolling average"
    # degenerates to each sample's own trailing mean-so-far) -- computed
    # independently here rather than re-deriving normalized_power_w's
    # internals, to actually pin the expected number:
    #   trailing means: 100, 200, 166.667, 200, 180
    #   4th powers:      1e8, 1.6e9, 7.7161728e8, 1.6e9, 1.04976e9
    #   mean of 4th powers -> 4th root
    trailing = [100.0, 200.0, 500.0 / 3, 200.0, 180.0]
    expected_np = (sum(v**4 for v in trailing) / len(trailing)) ** 0.25

    assert m.normalized_power_w == pytest.approx(expected_np, rel=1e-9)
    assert m.avg_speed_mps == pytest.approx(3.0)
    assert m.efficiency_mps_per_w == pytest.approx(3.0 / expected_np, rel=1e-9)
    assert m.lap_n == 1
    assert m.duration_s == pytest.approx(4.0)


def test_lap_metrics_flat_power_lap_normalized_power_equals_average():
    series = _hand_series()
    lap2 = GpsLap(n=2, start_idx=5, end_idx=9, start_s=5.0, end_s=9.0)
    m = lap_metrics(series, lap2)

    assert m.normalized_power_w == pytest.approx(250.0)
    assert m.avg_speed_mps == pytest.approx(4.0)
    assert m.efficiency_mps_per_w == pytest.approx(4.0 / 250.0)


def test_lap_metrics_lower_power_same_speed_is_more_efficient():
    # Andrew's own framing: lower NP for the same average speed = more
    # efficient. Two laps at identical speed, different power -> the
    # cheaper one has the higher efficiency_mps_per_w.
    series = {
        "t_s": list(range(10)),
        "power_w": [200.0] * 5 + [300.0] * 5,
        "speed_mps": [4.0] * 10,
    }
    cheap = lap_metrics(series, GpsLap(n=1, start_idx=0, end_idx=4, start_s=0.0, end_s=4.0))
    costly = lap_metrics(series, GpsLap(n=2, start_idx=5, end_idx=9, start_s=5.0, end_s=9.0))
    assert cheap.normalized_power_w < costly.normalized_power_w
    assert cheap.avg_speed_mps == pytest.approx(costly.avg_speed_mps)
    assert cheap.efficiency_mps_per_w > costly.efficiency_mps_per_w


def test_lap_metrics_no_power_channel_returns_none_np_and_efficiency():
    series = {"t_s": list(range(5)), "speed_mps": [3.0] * 5}
    lap = GpsLap(n=1, start_idx=0, end_idx=4, start_s=0.0, end_s=4.0)
    m = lap_metrics(series, lap)
    assert m.normalized_power_w is None
    assert m.avg_speed_mps == pytest.approx(3.0)
    assert m.efficiency_mps_per_w is None


def test_lap_metrics_falls_back_to_distance_over_duration_when_speed_sparse():
    # speed_mps present but entirely None (sparse/dropped channel) -- fall
    # back to dist_m coverage / duration.
    series = {
        "t_s": [0.0, 1.0, 2.0, 3.0, 4.0],
        "speed_mps": [None, None, None, None, None],
        "dist_m": [0.0, 2.0, 4.0, 6.0, 8.0],
        "power_w": [200.0] * 5,
    }
    lap = GpsLap(n=1, start_idx=0, end_idx=4, start_s=0.0, end_s=4.0)
    m = lap_metrics(series, lap)
    assert m.avg_speed_mps == pytest.approx(2.0)  # 8m over 4s


# --- total_work_kj / variability_index / coasting_s (Andrew's 3-metric build,
# --- 2026-09-20): different lenses on the same lap, deliberately not combined
# --- into one score -- see GpsLapMetrics's own docstring for the full framing.


def test_lap_metrics_total_work_kj_flat_power_lap():
    # avg_power * duration_s / 1000 -- flat 250W lap, duration 4.0s ->
    # 250 * 4 / 1000 = 1.0 kJ exactly (this IS the standard, exact
    # definition of work from average power -- not an approximation).
    series = _hand_series()
    lap2 = GpsLap(n=2, start_idx=5, end_idx=9, start_s=5.0, end_s=9.0)
    m = lap_metrics(series, lap2)
    assert m.total_work_kj == pytest.approx(1.0)


def test_lap_metrics_total_work_kj_spiky_lap_uses_average_not_normalized_power():
    # Lap 1: power alternates 100/300/100/300/100, avg_power = 180.0,
    # duration_s = 4.0 -> 180 * 4 / 1000 = 0.72 kJ. Must NOT equal
    # normalized_power-derived work (NP for this lap is higher than 180,
    # per the earlier NP test) -- total_work_kj is explicitly the
    # average-power-based ABSOLUTE energy cost, a different lens from NP.
    series = _hand_series()
    lap1 = GpsLap(n=1, start_idx=0, end_idx=4, start_s=0.0, end_s=4.0)
    m = lap_metrics(series, lap1)
    assert m.total_work_kj == pytest.approx(0.72)
    assert m.total_work_kj != pytest.approx(m.normalized_power_w * 4.0 / 1000)


def test_lap_metrics_variability_index_flat_power_is_one():
    # NP == average power exactly for a perfectly flat-power lap -> VI == 1.0.
    series = _hand_series()
    lap2 = GpsLap(n=2, start_idx=5, end_idx=9, start_s=5.0, end_s=9.0)
    m = lap_metrics(series, lap2)
    assert m.variability_index == pytest.approx(1.0)


def test_lap_metrics_variability_index_spiky_lap_is_above_one():
    # Real property of normalized_power_w's own algorithm, confirmed
    # directly before writing this test: for a span much SHORTER than the
    # 30s rolling window (POWER_ROLLING_WINDOW_S), the trailing average
    # degenerates into an expanding cumulative mean and NP can legitimately
    # fall BELOW the raw average -- `_hand_series()`'s 5-sample lap1 is
    # exactly that case (NP=178.9 < avg=180.0). A clean 50/50 square wave
    # doesn't reliably fix this either (confirmed directly: even a 90s/
    # three-cycle 100W/300W square wave still gave NP < average) --
    # a genuinely realistic profile is needed: SHORT sharp spikes against a
    # LONGER lower baseline (matching this codebase's own 2026-09-19
    # race-analysis research: real CX surges are ~3-10s against a much
    # longer lower-intensity baseline, not 50/50 blocks). Confirmed
    # directly before writing this assertion: 5s spikes to 400W every 30s
    # against a 100W baseline gives NP=196.5 > avg=150.0.
    t_s = list(range(180))
    power_w = [400.0 if (i % 30) < 5 else 100.0 for i in range(180)]
    series = {"t_s": [float(t) for t in t_s], "power_w": power_w}
    lap = GpsLap(n=1, start_idx=0, end_idx=179, start_s=0.0, end_s=179.0)
    m = lap_metrics(series, lap)
    assert m.normalized_power_w > 150.0  # avg is exactly 150.0
    assert m.variability_index > 1.1
    assert m.variability_index == pytest.approx(m.normalized_power_w / 150.0, rel=1e-9)


def test_lap_metrics_variability_index_none_when_no_power_channel():
    series = {"t_s": list(range(5)), "speed_mps": [3.0] * 5}
    lap = GpsLap(n=1, start_idx=0, end_idx=4, start_s=0.0, end_s=4.0)
    m = lap_metrics(series, lap)
    assert m.variability_index is None
    assert m.total_work_kj is None


def test_lap_metrics_total_work_kj_real_zero_when_avg_power_is_zero():
    # A real, valid 0.0 (all-zero power throughout, e.g. a fully-coasted
    # lap) is a genuine answer, distinct from None (no usable data at all).
    series = {"t_s": list(range(5)), "power_w": [0.0] * 5}
    lap = GpsLap(n=1, start_idx=0, end_idx=4, start_s=0.0, end_s=4.0)
    m = lap_metrics(series, lap)
    assert m.total_work_kj == pytest.approx(0.0)
    # But variability_index is undefined (0/0) -- correctly None, not a
    # fabricated 1.0 or a ZeroDivisionError.
    assert m.variability_index is None


def test_lap_metrics_coasting_s_counts_only_at_or_below_threshold():
    # power_w: 0, 0, 200, 200, 0 at t=0,1,2,3,4 (dt=1s each). Left-Riemann:
    # interval [0,1) at p=0 -> coasts; [1,2) at p=0 -> coasts; [2,3) at
    # p=200 -> not coasting; [3,4) at p=200 -> not coasting. The lap's
    # last sample (t=4) contributes no interval. Expected coasting_s = 2.0.
    series = {
        "t_s": [0.0, 1.0, 2.0, 3.0, 4.0],
        "power_w": [0.0, 0.0, 200.0, 200.0, 0.0],
    }
    lap = GpsLap(n=1, start_idx=0, end_idx=4, start_s=0.0, end_s=4.0)
    m = lap_metrics(series, lap)
    assert m.coasting_s == pytest.approx(2.0)


def test_lap_metrics_coasting_s_respects_threshold_not_just_exact_zero():
    # A small nonzero power at/below COASTING_POWER_THRESHOLD_W (5.0)
    # still counts as coasting (sensor noise allowance); power clearly
    # above it does not. power[0]=3.0 -> the [0,1) interval coasts;
    # power[1]=50.0 -> the [1,2) interval does not.
    series = {
        "t_s": [0.0, 1.0, 2.0],
        "power_w": [3.0, 50.0, 50.0],
    }
    lap = GpsLap(n=1, start_idx=0, end_idx=2, start_s=0.0, end_s=2.0)
    m = lap_metrics(series, lap)
    assert m.coasting_s == pytest.approx(1.0)  # only the [0,1) interval


def test_lap_metrics_coasting_s_none_when_no_power_channel():
    series = {"t_s": list(range(5)), "speed_mps": [3.0] * 5}
    lap = GpsLap(n=1, start_idx=0, end_idx=4, start_s=0.0, end_s=4.0)
    m = lap_metrics(series, lap)
    assert m.coasting_s is None


def test_lap_metrics_coasting_s_zero_when_never_coasting():
    # Real, valid 0.0 -- distinct from None -- when real data exists and
    # none of it qualifies as coasting.
    series = {"t_s": [0.0, 1.0, 2.0], "power_w": [200.0, 200.0, 200.0]}
    lap = GpsLap(n=1, start_idx=0, end_idx=2, start_s=0.0, end_s=2.0)
    m = lap_metrics(series, lap)
    assert m.coasting_s == pytest.approx(0.0)


# --- analyze_gps_laps: end-to-end orchestrator -------------------------------------------


def test_analyze_gps_laps_end_to_end_on_synthetic_loop():
    series = _square_loop_series(3, extra_channels=True)
    results = analyze_gps_laps(series)
    assert len(results) == 3
    for r in results:
        assert r.normalized_power_w == pytest.approx(200.0)
        assert r.avg_speed_mps == pytest.approx(3.0)
        assert r.efficiency_mps_per_w == pytest.approx(3.0 / 200.0)


def test_analyze_gps_laps_no_gps_returns_empty_list_not_raises():
    series = {"t_s": [0.0, 60.0], "power_w": [200.0, 210.0]}
    assert analyze_gps_laps(series) == []


# --- explicit start/finish anchor ---------------------------------------------------
# Real case: a race recording that BEGINS at the start chute, well away from
# the start/finish line the laps are actually counted at. The default
# (first-GPS-sample) reference then measures every crossing against the
# chute, not the line.

CHUTE_OFFSET = (-400.0, -250.0)  # meters east/north of the S/F corner


def _series_with_lead_in(n_laps: int, *, speed_mps: float = 3.0, step_m: float = 6.0) -> dict:
    """`_square_loop_series(n_laps)` preceded by a straight lead-in from the
    off-course chute point to the S/F corner (0, 0)."""
    loop = _square_loop_series(n_laps, speed_mps=speed_mps, step_m=step_m)
    lead = _interpolate_path([CHUTE_OFFSET, (0.0, 0.0)], step_m)[:-1]  # (0,0) is loop[0]
    dt = step_m / speed_mps
    lead_lat, lead_lng = zip(*(_offset_latlng(dx, dy) for dx, dy in lead))
    shift = len(lead) * dt
    return {
        "t_s": [i * dt for i in range(len(lead))] + [t + shift for t in loop["t_s"]],
        "lat": list(lead_lat) + loop["lat"],
        "lng": list(lead_lng) + loop["lng"],
    }


def test_start_finish_anchor_recovers_laps_when_recording_starts_off_the_line():
    series = _series_with_lead_in(3)
    laps = detect_gps_laps(series, start_finish=_offset_latlng(0.0, 0.0))
    assert len(laps) == 3
    for lap in laps:
        assert lap.duration_s == pytest.approx(200.0, abs=15.0)


def test_start_finish_anchor_first_lap_starts_at_first_crossing_not_recording_start():
    series = _series_with_lead_in(2)
    laps = detect_gps_laps(series, start_finish=_offset_latlng(0.0, 0.0))
    assert laps[0].start_idx > 0
    start_lat, start_lng = series["lat"][laps[0].start_idx], series["lng"][laps[0].start_idx]
    assert haversine_distance_m(start_lat, start_lng, *_offset_latlng(0.0, 0.0)) <= GPS_LAP_PROXIMITY_M


def test_default_reference_on_off_line_start_does_not_find_the_true_laps():
    # Documents the problem the anchor exists to solve.
    series = _series_with_lead_in(3)
    assert len(detect_gps_laps(series)) != 3


def test_start_finish_anchor_matches_default_when_recording_starts_on_the_line():
    series = _square_loop_series(3)
    assert detect_gps_laps(series, start_finish=_offset_latlng(0.0, 0.0)) == detect_gps_laps(series)


def test_start_finish_anchor_never_approached_detects_zero_laps():
    series = _square_loop_series(3)
    far = _offset_latlng(5_000.0, 5_000.0)
    assert detect_gps_laps(series, start_finish=far) == []


def test_start_finish_from_laps_returns_the_line_position():
    lat, lng = start_finish_from_laps(_square_loop_series(3))
    assert haversine_distance_m(lat, lng, *_offset_latlng(0.0, 0.0)) <= GPS_LAP_PROXIMITY_M


def test_start_finish_from_laps_none_when_no_laps():
    assert start_finish_from_laps(_series_with_lead_in(3)) is None
    assert start_finish_from_laps(None) is None


def test_position_at_offset_returns_position_of_nearest_sample():
    series = _square_loop_series(1)
    i = 10
    lat, lng = position_at_offset(series, series["t_s"][i])
    assert (lat, lng) == (series["lat"][i], series["lng"][i])


def test_position_at_offset_skips_dropped_gps_fixes():
    series = _square_loop_series(1)
    series["lat"][10] = None
    series["lng"][10] = None
    lat, lng = position_at_offset(series, series["t_s"][10])
    assert lat is not None and lng is not None


def test_position_at_offset_none_without_gps_or_beyond_the_recording():
    assert position_at_offset(None, 5.0) is None
    assert position_at_offset({"t_s": [0.0, 1.0]}, 0.5) is None
    assert position_at_offset(_square_loop_series(1), 10_000_000.0) is None
