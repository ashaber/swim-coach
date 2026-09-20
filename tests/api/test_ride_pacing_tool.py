"""Handler tests for the `get_ride_pacing` coach tool -- surfaces the
engine's GPS-lap detection + per-lap efficiency metrics (`gps_laps`) and
race-phase pacing split (`race_phases`) to the coach, which had no way to
see either (they're computed on demand from the stored series, never
persisted onto the Workout).

Series are synthetic and hand-built (a square GPS loop ridden at known
constant power per lap) so every expected number is known independent of
the code under test.
"""

from __future__ import annotations

import math
import uuid
from datetime import date

import pytest
from swim_coach.models import Workout
from swim_coach.store import FileStore

from app.tools import RIDE_PACING_LAPS_CAP, build_tool_handlers

RIDE_DATE = date(2026, 9, 19)
SIDE_M = 150.0
PERIMETER_M = 4 * SIDE_M
SPEED_MPS = 3.0
LAP_S = int(PERIMETER_M / SPEED_MPS)  # 200s

START_LAT = 45.0
START_LNG = -122.0
M_PER_DEG_LAT = 111_320.0


def _corner_position(dist_along_m: float) -> tuple[float, float]:
    """(dx_m east, dy_m north) `dist_along_m` around the square loop."""
    d = dist_along_m % PERIMETER_M
    if d < SIDE_M:
        return d, 0.0
    if d < 2 * SIDE_M:
        return SIDE_M, d - SIDE_M
    if d < 3 * SIDE_M:
        return SIDE_M - (d - 2 * SIDE_M), SIDE_M
    return 0.0, SIDE_M - (d - 3 * SIDE_M)


def _loop_series(lap_powers: list[float], *, with_gps: bool = True) -> dict:
    """1 Hz series: one square loop per entry in `lap_powers`, ridden at a
    constant SPEED_MPS and that lap's constant power."""
    t_s: list[float] = []
    speed: list[float] = []
    power: list[float] = []
    lat: list[float] = []
    lng: list[float] = []
    m_per_deg_lng = M_PER_DEG_LAT * math.cos(math.radians(START_LAT))
    total_s = LAP_S * len(lap_powers)
    for t in range(total_s + 1):
        lap_idx = min(t // LAP_S, len(lap_powers) - 1)
        dx, dy = _corner_position(SPEED_MPS * t)
        t_s.append(float(t))
        speed.append(SPEED_MPS)
        power.append(float(lap_powers[lap_idx]))
        lat.append(START_LAT + dy / M_PER_DEG_LAT)
        lng.append(START_LNG + dx / m_per_deg_lng)
    series: dict = {"t_s": t_s, "speed_mps": speed, "power_w": power}
    if with_gps:
        series["lat"] = lat
        series["lng"] = lng
    return series


def _seed(
    store: FileStore,
    series: dict | None,
    *,
    sport: str = "bike",
) -> Workout:
    profile = store.load_athlete("renee")
    duration_min = (series["t_s"][-1] / 60) if series else 30.0
    w = Workout(
        id=uuid.uuid4(),
        athlete_id=profile.id,
        date=RIDE_DATE,
        sport=sport,
        source="fit",
        distance_m=int(SPEED_MPS * (series["t_s"][-1] if series else 1800)),
        duration_min=duration_min,
    )
    store.save_workout("renee", w)
    if series is not None:
        store.save_series("renee", w.date, w.sport, w.id, series)
    return w


def _handlers(store: FileStore):
    return build_tool_handlers(store, slug="renee", expert_mode=False)


def test_returns_detected_laps_with_per_lap_metrics(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    w = _seed(store, _loop_series([200, 180, 160]))

    res = _handlers(store)["get_ride_pacing"]({"workout_id": str(w.id)})

    assert "error" not in res
    assert res["workout_id"] == str(w.id)
    assert res["date"] == RIDE_DATE.isoformat()
    laps = res["gps_laps"]["laps"]
    assert res["gps_laps"]["detected"] == 3
    assert [lap["lap_n"] for lap in laps] == [1, 2, 3]
    assert [lap["normalized_power_w"] for lap in laps] == pytest.approx([200, 180, 160], abs=3)  # 30s NP window bleeds across lap edges
    # constant power => VI 1.0, and kJ = W * s / 1000 exactly
    assert laps[0]["variability_index"] == pytest.approx(1.0, abs=0.01)
    assert laps[0]["total_work_kj"] == pytest.approx(200 * LAP_S / 1000, abs=2)  # boundary fires within 20m of start, ~7s early
    assert laps[0]["avg_speed_mps"] == pytest.approx(SPEED_MPS, abs=0.05)
    # efficiency rises as power falls at constant speed -- and the response
    # must carry the caveat that this alone can't tell fade from improvement
    assert laps[2]["efficiency_mps_per_w"] > laps[0]["efficiency_mps_per_w"]
    assert "fade" in res["interpretation"].lower()


def test_returns_race_phases_with_significance_vs_first_phase(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    # Power falls 200 -> 140 across three laps: later phases must read as a
    # significant drop versus phase_1.
    w = _seed(store, _loop_series([200, 170, 140]))

    res = _handlers(store)["get_ride_pacing"]({"workout_id": str(w.id)})

    phases = res["race_phases"]["phases"]
    assert [p["name"] for p in phases] == ["start", "phase_1", "phase_2", "phase_3"]
    assert res["race_phases"]["significance_threshold_pct"] == 5.0
    assert phases[1]["vs_phase_1_significant"] is None  # phase_1 is the baseline
    assert phases[3]["normalized_power_w"] < phases[1]["normalized_power_w"]
    assert phases[3]["vs_phase_1_significant"] is True
    assert phases[3]["vs_phase_1_pct"] < -5.0


def test_flat_power_reads_as_not_significant(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    w = _seed(store, _loop_series([200, 200, 200]))

    res = _handlers(store)["get_ride_pacing"]({"workout_id": str(w.id)})

    phases = res["race_phases"]["phases"]
    assert phases[3]["vs_phase_1_significant"] is False


def test_no_gps_channel_still_returns_phases(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    w = _seed(store, _loop_series([200, 180, 160], with_gps=False))

    res = _handlers(store)["get_ride_pacing"]({"workout_id": str(w.id)})

    assert "error" not in res
    assert res["gps_laps"]["detected"] == 0
    assert res["gps_laps"]["laps"] == []
    assert "gps" in res["gps_laps"]["note"].lower()
    assert len(res["race_phases"]["phases"]) == 4


def test_lap_list_is_capped_and_flags_truncation(athletes_dir, monkeypatch) -> None:
    store = FileStore(base_dir=athletes_dir)
    w = _seed(store, _loop_series([200, 190, 180, 170]))
    monkeypatch.setattr("app.tools.RIDE_PACING_LAPS_CAP", 2)

    res = _handlers(store)["get_ride_pacing"]({"workout_id": str(w.id)})

    assert res["gps_laps"]["detected"] == 4
    assert len(res["gps_laps"]["laps"]) == 2
    assert res["gps_laps"]["truncated"] is True


def test_laps_cap_constant_is_sane() -> None:
    assert RIDE_PACING_LAPS_CAP >= 20


def test_is_read_only(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    w = _seed(store, _loop_series([200, 180, 160]))
    before = store.list_workouts("renee")

    _handlers(store)["get_ride_pacing"]({"workout_id": str(w.id)})

    after = store.list_workouts("renee")
    assert [x.model_dump(mode="json") for x in before] == [x.model_dump(mode="json") for x in after]


def test_unknown_workout_id_errors(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    res = _handlers(store)["get_ride_pacing"]({"workout_id": str(uuid.uuid4())})
    assert "no workout matching" in res["error"]


def test_missing_workout_id_errors(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    res = _handlers(store)["get_ride_pacing"]({})
    assert res["error"] == "workout_id is required"


def test_non_bike_workout_errors(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    w = _seed(store, _loop_series([200, 180, 160]), sport="swim_ow")
    res = _handlers(store)["get_ride_pacing"]({"workout_id": str(w.id)})
    assert "bike" in res["error"]


def test_no_series_points_at_pull_activity_stream(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    w = _seed(store, None)
    res = _handlers(store)["get_ride_pacing"]({"workout_id": str(w.id)})
    assert "no time-series data" in res["error"]
    assert "pull_activity_stream" in res["error"]
