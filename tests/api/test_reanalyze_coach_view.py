"""`reanalyze_workout` hands the coach the same compact analytics view `get_workouts` does
(prod incident: the coach read the 5 s warm-up builds as starts 1-2 and missed the power curve)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from swim_coach.models import Session, Workout
from swim_coach.store import FileStore

from app import tools
from app.tools import build_tool_handlers

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "ride_2026_10_10_starts_race_pace.json"


@pytest.fixture()
def reanalysed(athletes_dir: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[dict, dict]:
    ride = json.loads(FIXTURE.read_text())
    store = FileStore(base_dir=athletes_dir)
    profile = store.load_athlete("renee").model_copy(update={"ftp_watts": 278.0, "home_elevation_m": 823.0})
    store.save_athlete(profile)
    session = Session.model_validate(ride["planned_session"])
    monkeypatch.setattr(tools, "find_planned_session", lambda *_a, **_k: session)
    w = dict(ride["workout"])
    w["analytics"] = None
    w["planned_session_id"] = None
    workout = Workout.model_validate(w)
    store.save_workout("renee", workout)
    store.save_series("renee", workout.date, workout.sport, workout.id, ride["series"])
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    res = handlers["reanalyze_workout"]({"workout_id": str(workout.id)})
    listed = handlers["get_workouts"]({"start_date": workout.date.isoformat()})
    return res, listed


def test_reanalyze_returns_the_power_curve_and_starts_before_efforts(reanalysed) -> None:
    res, _ = reanalysed
    view = res["analytics"]
    five = next(p for p in view["power_curve"] if p["duration"] == "5s")
    assert five["watts"] == pytest.approx(956, abs=2)
    iv = view["intervals"]
    assert len(iv["starts"]) == 5 and iv["starts"][0]["best_5s_w"] == pytest.approx(956, abs=2)
    assert iv["starts_flag"] and iv["starts_note"]
    keys = list(iv)
    assert keys.index("starts") < keys.index("efforts") and keys.index("starts_flag") < keys.index("efforts")
    assert list(view).index("power_curve") < list(view).index("intervals")


def test_reanalyze_view_matches_get_workouts(reanalysed) -> None:
    res, listed = reanalysed
    assert listed["workouts"][0]["analytics"] == res["analytics"]


def test_warmup_builds_are_not_presented_as_starts(reanalysed) -> None:
    efforts = reanalysed[0]["analytics"]["intervals"]["efforts"]
    assert not any("no clear burst found" in e["verdict"] for e in efforts)
    assert not any(round(e["avg_w"] or 0) in (161, 131) and e["duration_s"] <= 5 for e in efforts)


def test_starts_live_in_the_starts_table_not_in_efforts(reanalysed) -> None:
    iv = reanalysed[0]["analytics"]["intervals"]
    assert len(iv["starts"]) == 5 and iv["starts"][0]["trace_w"]
    assert [e["n"] for e in iv["efforts"]] == list(range(1, len(iv["efforts"]) + 1))
    assert all(e["start_s"] not in {s["burst_start_s"] for s in iv["starts"]} for e in iv["efforts"])
    assert "161.2" not in json.dumps(reanalysed[0]["analytics"])
