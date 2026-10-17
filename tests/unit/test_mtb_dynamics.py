"""Garmin MTB dynamics (Grit / Flow / jumps): FIT parse, per-lap analytics, course sectors, coach view.

Fixture: `mtb_fit_builder` (synthetic, deterministic, GPS-free; three ~1 km laps with a slow
sector 5 and worsening flow) and its JSON export `fixtures/streams/mtb_dynamics_3laps.json`.
Grit/Flow algorithms are Garmin's and proprietary -- these tests pin plumbing and arithmetic only.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path

import pytest

import mtb_fit_builder as fx
from swim_coach.analysis import AnalysisContext, BIKE_FIELDS, analytics_for_coach
from swim_coach.models import DeviceDynamics, JumpRecord, Workout, WorkoutLap
from swim_coach.mtb_dynamics import GRIT_RECORD_SCALE, build_mtb_dynamics
from swim_coach.course_sectors import SECTOR_COUNT, build_course_sectors
from swim_coach.parse_files import parse_fit

FIXTURE_JSON = Path(__file__).parent / "fixtures" / "streams" / "mtb_dynamics_3laps.json"


def _laps() -> list[WorkoutLap]:
    return [
        WorkoutLap(index=i, start_offset_s=float(o), duration_s=float(n), distance_m=fx.LAP_M, avg_power_w=210.0)
        for i, (o, n) in enumerate(zip(fx.lap_starts(), fx.LAP_S))
    ]


def _device() -> DeviceDynamics:
    series = fx.build_series()
    nonzero = [f for f in series["flow"] if f]
    return DeviceDynamics(
        total_grit=round(sum(series["grit"]) / GRIT_RECORD_SCALE, 2),
        avg_flow=round(sum(nonzero) / len(nonzero), 2),
        jump_count=len(fx.JUMP_OFFSETS_S),
        jumps=[JumpRecord(**j) for j in fx.jumps()],
    )


def _workout(**kw) -> Workout:
    data = dict(
        id=uuid.uuid4(), athlete_id=uuid.uuid4(), date=date(2026, 10, 4), sport="bike", source="fit",
        distance_m=3000, duration_min=15.8, laps=_laps(), device_dynamics=_device(),
    )
    data.update(kw)
    return Workout(**data)


# --- fixture file stays in sync with the builder ------------------------------------------------


def test_json_fixture_matches_builder_and_has_no_gps():
    saved = json.loads(FIXTURE_JSON.read_text())
    assert saved["series"] == fx.build_series()
    assert not {"lat", "lng", "position_lat", "position_long"} & set(saved["series"])
    assert all("lat" not in j and "lng" not in j for j in saved["device_dynamics"]["jumps"])


# --- parse_fit ---------------------------------------------------------------------------------


def test_parse_fit_reads_grit_flow_channels_and_device_dynamics(tmp_path):
    draft = parse_fit(fx.write_fit(tmp_path / "ride.fit"))
    series = fx.build_series()
    assert draft.sport == "bike"
    assert draft.series["grit"] == series["grit"]
    assert draft.series["flow"] == series["flow"]
    dev = draft.device_dynamics
    assert dev.total_grit == pytest.approx(round(sum(series["grit"]) / 1000))
    assert dev.avg_flow == 4.0
    assert dev.jump_count == 6 and len(dev.jumps) == 6
    first = dev.jumps[0]
    assert first.offset_s == 40.0 and first.distance_m == 4.0 and first.height_m == 1.0
    assert first.hang_time_s == 1.0 and first.score == 40.0 and first.speed_mps == 6.0
    assert "lat" not in JumpRecord.model_fields and "position_lat" not in JumpRecord.model_fields


def test_real_garmin_mtb_fixtures_confirm_grit_scale():
    # Real device files already in the repo carry grit/flow: record grit sums to total_grit x 1000.
    for name, jumps in (("real_mtb_0709", 0), ("real_mtb_race", 95)):
        draft = parse_fit(Path(__file__).parent / "fixtures" / "fit" / f"{name}.fit")
        assert draft.device_dynamics.jump_count == jumps
        total = sum(g for g in draft.series["grit"] if g) / GRIT_RECORD_SCALE
        assert total == pytest.approx(draft.device_dynamics.total_grit, rel=1e-3)
        assert len(draft.device_dynamics.jumps) == jumps


def test_parse_fit_without_dynamics_has_none_and_no_channels():
    draft = parse_fit(Path(__file__).parent / "fixtures" / "fit" / "real_kayak.fit")
    assert draft.device_dynamics is None
    assert "grit" not in (draft.series or {}) and "flow" not in (draft.series or {})


def test_draft_carries_dynamics_to_workout(tmp_path):
    draft = parse_fit(fx.write_fit(tmp_path / "ride.fit"))
    assert draft.to_workout(athlete_id=uuid.uuid4()).device_dynamics == draft.device_dynamics


# --- mtb_dynamics -------------------------------------------------------------------------------


def test_lap_grit_is_record_sum_over_scale_and_ride_total_ties_to_device():
    series = fx.build_series()
    m = build_mtb_dynamics(_workout(), series)
    assert m.total_grit == _device().total_grit
    starts = fx.lap_starts() + [sum(fx.LAP_S)]
    for i, lap in enumerate(m.laps):
        expect = sum(series["grit"][starts[i]:starts[i + 1]]) / GRIT_RECORD_SCALE
        assert lap.grit == pytest.approx(expect, abs=0.01)
    assert sum(lap.grit for lap in m.laps) == pytest.approx(m.total_grit, abs=0.02)


def test_lap_flow_averages_moving_records_and_ride_average_ties_to_device():
    series = fx.build_series()
    m = build_mtb_dynamics(_workout(), series)
    s = fx.lap_starts()
    moving = [f for f, v in zip(series["flow"][s[0]:s[1]], series["speed_mps"][s[0]:s[1]]) if v > 1.0]
    assert m.laps[0].avg_flow == pytest.approx(sum(moving) / len(moving), abs=0.01)
    assert m.avg_flow == _device().avg_flow
    assert m.laps[0].avg_flow < m.laps[1].avg_flow < m.laps[2].avg_flow


def test_lap_flow_ignores_slow_records_even_when_flow_is_nonzero():
    series = fx.build_series()
    s = fx.lap_starts()
    series["speed_mps"] = list(series["speed_mps"])
    series["flow"] = list(series["flow"])
    for i in range(s[0], s[0] + 50):  # a stopped stretch that still reports a big flow value
        series["speed_mps"][i] = 0.2
        series["flow"][i] = 40.0
    m = build_mtb_dynamics(_workout(), series)
    assert m.laps[0].avg_flow < 10


def test_jumps_land_in_their_lap_and_are_summarised():
    m = build_mtb_dynamics(_workout(), fx.build_series())
    assert [lap.jumps for lap in m.laps] == [3, 2, 1]  # offsets 40/95/150 | 340/420 | 700
    assert m.jumps.count == 6 and m.jumps.max_height_m == 6.0 and m.jumps.max_hang_time_s == 6.0
    assert m.jumps.best_score == 45.0 and m.jumps.max_distance_m == 9.0


def test_totals_fall_back_to_the_series_without_session_totals():
    m = build_mtb_dynamics(_workout(device_dynamics=None), fx.build_series())
    assert m.total_grit == pytest.approx(sum(fx.build_series()["grit"]) / 1000, abs=0.01)
    assert m.jumps is None


def test_absent_when_no_data():
    series = {k: v for k, v in fx.build_series().items() if k not in ("grit", "flow")}
    assert build_mtb_dynamics(_workout(device_dynamics=None), series) is None
    assert build_mtb_dynamics(_workout(device_dynamics=None), None) is None


def test_session_totals_alone_still_yield_a_block_without_laps():
    m = build_mtb_dynamics(_workout(laps=[]), None)
    assert m.total_grit == _device().total_grit and m.laps == []


# --- course sectors -----------------------------------------------------------------------------


def test_course_sectors_loss_lands_in_the_slow_sector():
    cs = build_course_sectors(_workout(), fx.build_series())
    assert cs.sector_count == SECTOR_COUNT == 8
    assert [lap.lap for lap in cs.laps] == [1, 2, 3] and cs.best_lap == 1
    assert cs.laps[0].time_vs_best_s == 0 and cs.laps[2].time_vs_best_s > cs.laps[1].time_vs_best_s > 0
    assert cs.top_loss_sectors[0] == 5 and len(cs.top_loss_sectors) == 3
    worst = cs.sectors[4]
    assert worst.sector == 5 and worst.total_loss_s == max(s.total_loss_s for s in cs.sectors)
    assert cs.sectors[0].total_loss_s < worst.total_loss_s


def test_course_sectors_baseline_is_the_best_time_per_sector_not_the_best_lap():
    cs = build_course_sectors(_workout(), fx.build_series())
    cut = [lap.sector_times_s for lap in cs.laps]
    for k, sector in enumerate(cs.sectors):
        times = [t[k] for t in cut]
        assert sector.best_time_s == min(times)
        assert sector.total_loss_s == pytest.approx(sum(times) - len(times) * min(times), abs=0.02)
        assert sector.total_loss_s >= 0 and sector.mean_loss_s >= 0
        assert sector.spread_s == pytest.approx(max(times) - min(times), abs=0.01)
    assert cs.ideal_lap_s == pytest.approx(sum(s.best_time_s for s in cs.sectors), abs=0.05)
    assert cs.ideal_gap_s == pytest.approx(min(lap.time_s for lap in cs.laps) - cs.ideal_lap_s, abs=0.05)
    assert cs.ideal_gap_s >= 0


def test_course_sectors_negative_loss_is_impossible_when_another_lap_wins_a_sector():
    series = fx.build_series()
    cs = build_course_sectors(_workout(), series)
    assert all(t - cs.sectors[k].best_time_s >= -1e-9 for lap in cs.laps for k, t in enumerate(lap.sector_times_s))


def test_course_sectors_fade_reports_time_power_and_flow_trend():
    cs = build_course_sectors(_workout(), fx.build_series())
    assert cs.fade.time_change_pct == pytest.approx((336 - 300) / 300 * 100, abs=0.5)
    assert cs.fade.flow_change > 0 and cs.fade.flow_slope_per_lap > 0
    assert abs(cs.fade.power_change_pct) < 5


def test_course_sectors_need_two_similar_laps():
    one_lap = _workout(laps=_laps()[:1])
    assert build_course_sectors(one_lap, fx.build_series()) is None
    odd = _laps()
    odd[1] = odd[1].model_copy(update={"distance_m": 400.0})
    odd[2] = odd[2].model_copy(update={"distance_m": 2500.0})
    assert build_course_sectors(_workout(laps=odd), fx.build_series()) is None


def test_course_sectors_ignore_a_dissimilar_warmup_lap():
    series = fx.build_series()
    laps = _laps()
    laps[0] = laps[0].model_copy(update={"distance_m": 300.0})
    cs = build_course_sectors(_workout(laps=laps), series)
    assert [lap.lap for lap in cs.laps] == [2, 3]


def _with_gps(start_lng_by_lap: tuple[float, ...]) -> dict:
    """Fixture series plus SYNTHETIC coordinates: each lap sits at one fixed point."""
    series = fx.build_series()
    lng = []
    for lap, n in enumerate(fx.LAP_S):
        lng += [start_lng_by_lap[lap]] * n
    series["lat"] = [40.0] * len(lng)
    series["lng"] = lng
    return series


def test_course_sectors_drop_a_lap_that_did_not_start_at_the_line():
    # lap 2 starts ~250 m (0.003 deg of longitude at 40N) from the others
    cs = build_course_sectors(_workout(), _with_gps((-100.0, -99.997, -100.0)))
    assert [lap.lap for lap in cs.laps] == [1, 3]


def test_course_sectors_keep_laps_starting_within_the_radius():
    cs = build_course_sectors(_workout(), _with_gps((-100.0, -99.9998, -100.0)))  # ~17 m
    assert [lap.lap for lap in cs.laps] == [1, 2, 3]


def test_course_sectors_absent_without_distance_channel():
    series = {k: v for k, v in fx.build_series().items() if k != "dist_m"}
    assert build_course_sectors(_workout(), series) is None


# --- analyzer wiring + coach view ---------------------------------------------------------------


def test_bike_fields_own_the_new_blocks():
    assert {"mtb_dynamics", "course_sectors"} <= BIKE_FIELDS


@pytest.mark.parametrize("kind", ["race", "free_ride", "workout", "warmup"])
def test_bike_analyzer_fills_dynamics_for_every_kind(kind):
    a = _workout().analyze(AnalysisContext(kind=kind, series=fx.build_series()))
    assert a.mtb_dynamics is not None and a.mtb_dynamics.total_grit == _device().total_grit


@pytest.mark.parametrize("kind", ["race", "opener", "warmup", "free_ride", "workout"])  # workout with no session = unstructured
def test_course_sectors_for_races_and_unstructured_rides(kind):
    a = _workout().analyze(AnalysisContext(kind=kind, series=fx.build_series()))
    assert a.course_sectors is not None


def test_course_sectors_skip_structured_workouts_whose_laps_are_reps():
    from swim_coach.models import Session

    session = Session(
        id=uuid.uuid4(), athlete_id=uuid.uuid4(), date=date(2026, 10, 4), sport="bike", source="ai_coach",
        duration_min=60.0, distance_m=0, intensity={"zone": "Z4"}, purpose="intervals",
        structured={"schema_version": 1, "items": [{"kind": "step", "role": "interval", "label": "rep", "duration_kind": "time_s", "duration_s": 300}]},
    )
    a = _workout().analyze(AnalysisContext(kind="workout", session=session, series=fx.build_series()))
    assert a.course_sectors is None and a.mtb_dynamics is not None


def test_non_bike_workout_gets_no_blocks():
    swim = _workout(sport="swim_pool", laps=[], device_dynamics=None)
    a = swim.analyze(AnalysisContext(kind="workout", series=fx.build_series()))
    assert a.mtb_dynamics is None and a.course_sectors is None


def test_coach_view_is_compact_and_has_notes():
    ctx = AnalysisContext(kind="race", series=fx.build_series())
    view = analytics_for_coach(_workout().analyze(ctx), "bike")
    mtb, cs = view["mtb_dynamics"], view["course_sectors"]
    assert "lower flow is smoother" in mtb["coach_note"].lower() and "same course" in mtb["coach_note"].lower()
    assert mtb["total_grit"] == _device().total_grit and len(mtb["laps"]) == 3
    assert all(isinstance(line, str) for line in mtb["laps"])
    assert "Lap 1" in mtb["laps"][0] and "grit" in mtb["laps"][0].lower() and "flow" in mtb["laps"][0].lower()
    assert len(cs["top_loss_sectors"]) == 3 and "sector 5" in cs["top_loss_sectors"][0].lower()
    assert "which feature" in cs["coach_note"].lower()
    assert "own best time through that sector" in cs["coach_note"] and "what was different on the fast lap" in cs["coach_note"]
    assert cs["ideal_lap"].startswith("Ideal lap ") and "best lap" in cs["ideal_lap"]
    assert "vs best lap" not in cs["top_loss_sectors"][0] and "spread" in cs["top_loss_sectors"][0]
    assert len(json.dumps(view)) < 6000  # no per-record arrays leak
    assert "sectors" not in cs  # the full table stays in the stored analytics
    keys = list(view)
    assert keys.index("mtb_dynamics") < keys.index("course_sectors")


def test_device_dynamics_round_trips_through_the_db_row_mapping():
    from swim_coach.store_db import row_to_workout, workout_to_row

    w = _workout()
    row = workout_to_row(w)
    assert row_to_workout({"data": row["data"], "created_at": None}).device_dynamics == w.device_dynamics


# --- course track (low-fidelity map) -------------------------------------------------------------


def _loop_gps() -> dict:
    """Fixture series plus a SYNTHETIC circular course (centre 40.0, -100.0; ~160 m radius), each lap
    driving the same loop in proportion to its own distance."""
    import math

    series = fx.build_series()
    lat, lng = [], []
    for n, start in zip(fx.LAP_S, fx.lap_starts()):
        for i in range(n):
            a = 2 * math.pi * ((series["dist_m"][start + i] % fx.LAP_M) / fx.LAP_M)
            lat.append(40.0 + 0.0015 * math.sin(a))
            lng.append(-100.0 + 0.0015 * math.cos(a))
    series["lat"], series["lng"] = lat, lng
    return series


def test_track_is_projected_metres_centred_on_the_lap_with_eight_sector_polylines():
    cs = build_course_sectors(_workout(), _loop_gps())
    assert cs.track is not None and [t.sector for t in cs.track.sectors] == list(range(1, 9))
    pts = [p for t in cs.track.sectors for p in t.points]
    assert 150 <= len(pts) <= 260  # ~200 points for the lap (Coach judgment), plus shared joins
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    assert max(xs) - min(xs) == pytest.approx(2 * 0.0015 * 111_320 * 0.766, rel=0.05)  # east-west extent
    assert max(ys) - min(ys) == pytest.approx(2 * 0.0015 * 111_320, rel=0.05)  # north-south extent
    assert abs(sum(xs) / len(xs)) < 25 and abs(sum(ys) / len(ys)) < 25  # centred: no absolute position
    assert all(len(t.points) >= 2 and len(t.label) == 2 for t in cs.track.sectors)


def test_track_sectors_join_end_to_start_and_stores_no_raw_coordinates():
    cs = build_course_sectors(_workout(), _loop_gps())
    sectors = cs.track.sectors
    for a, b in zip(sectors, sectors[1:]):
        assert a.points[-1] == b.points[0]
    dumped = json.dumps(cs.model_dump(mode="json"))
    assert "lat" not in dumped and "lng" not in dumped
    assert all(abs(c) < 1000 and round(c, 1) == c for t in sectors for p in t.points for c in p)  # metres, not degrees


def test_track_absent_without_gps_but_sectors_still_built():
    cs = build_course_sectors(_workout(), fx.build_series())
    assert cs is not None and cs.track is None


def test_coach_view_strips_the_track():
    ctx = AnalysisContext(kind="race", series=_loop_gps())
    view = analytics_for_coach(_workout().analyze(ctx), "bike")
    assert "track" not in view["course_sectors"]
    assert "points" not in json.dumps(view)


# --- GPS-detected laps (races whose device laps were never pressed) ------------------------------


def test_course_sectors_from_gps_laps_when_there_are_no_native_laps():
    cs = build_course_sectors(_workout(laps=[]), _loop_gps(), prefer_gps=True)
    assert cs is not None and len(cs.laps) >= 2
    assert cs.track is not None and len(cs.track.sectors) == SECTOR_COUNT
    assert cs.laps[0].time_vs_best_s >= 0


def test_race_prefers_gps_laps_over_native_laps_but_other_kinds_prefer_native():
    one_native = _laps()[:1]  # a race with a single pressed lap
    race = build_course_sectors(_workout(laps=one_native), _loop_gps(), prefer_gps=True)
    assert race is not None and len(race.laps) >= 2
    native = build_course_sectors(_workout(), _loop_gps(), prefer_gps=False)
    assert [lap.lap for lap in native.laps] == [1, 2, 3]  # the device's own laps


def test_non_race_falls_back_to_gps_laps_when_native_laps_fail_the_filter():
    cs = build_course_sectors(_workout(laps=_laps()[:1]), _loop_gps(), prefer_gps=False)
    assert cs is not None and len(cs.laps) >= 2


def test_no_gps_and_no_native_laps_gives_no_sectors():
    assert build_course_sectors(_workout(laps=[]), fx.build_series(), prefer_gps=True) is None


def test_bike_analyzer_builds_sectors_for_an_unpressed_race():
    ctx = AnalysisContext(kind="race", series=_loop_gps())
    a = _workout(laps=[]).analyze(ctx)
    assert a.course_sectors is not None and a.course_sectors.track is not None
