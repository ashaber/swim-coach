"""Power curve: stored with analytics, compared with earlier rides' bests, compact for the coach."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from swim_coach.analytics import compute_analytics
from swim_coach.models import PowerCurvePoint, Session, Workout, WorkoutAnalytics
from swim_coach.store import FileStore

from app import enrich
from app.context import render_focused_workout

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "ride_2026_10_10_starts_race_pace.json"


@pytest.fixture()
def ride() -> dict:
    return json.loads(FIXTURE.read_text())


def _workout(ride: dict) -> Workout:
    w = dict(ride["workout"])
    w["analytics"] = None
    w["planned_session_id"] = None
    return Workout.model_validate(w)


def _prior(ride: dict, days_before: int, watts_5s: int) -> Workout:
    base = _workout(ride)
    curve = [PowerCurvePoint(duration_s=5, watts=watts_5s, start_s=0), PowerCurvePoint(duration_s=1, watts=1, start_s=0)]
    return base.model_copy(
        update={
            "id": uuid4(),
            "date": base.date - timedelta(days=days_before),
            "analytics": WorkoutAnalytics(power_curve=curve),
        }
    )


def test_compute_analytics_stores_curve_for_every_power_ride(ride: dict) -> None:
    a = compute_analytics(
        laps=[], lengths=[], pauses=[], series=ride["series"], elapsed_min=None, moving_min=None, sport="bike"
    )
    assert a.power_curve and a.power_curve[0].duration_s == 1


def test_attach_planned_session_annotates_bests_against_earlier_curves(
    ride: dict, athletes_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FileStore(base_dir=athletes_dir)
    profile = store.load_athlete("renee").model_copy(update={"ftp_watts": 278.0, "home_elevation_m": 823.0})
    session = Session.model_validate(ride["planned_session"])
    monkeypatch.setattr(enrich, "find_planned_session", lambda *_a, **_k: session)
    w = _workout(ride)
    store.save_workout("renee", _prior(ride, 10, 900))   # inside 42 d
    store.save_workout("renee", _prior(ride, 60, 1000))  # inside 90 d only
    store.save_workout("renee", _prior(ride, 200, 5000))  # outside both
    store.save_workout("renee", w.model_copy(update={"id": uuid4(), "analytics": None}))  # no curve: skipped

    out = enrich.attach_planned_session(w, store=store, slug="renee", profile=profile, series=ride["series"])

    five = next(p for p in out.analytics.power_curve if p.duration_s == 5)
    assert (five.best_42d_w, five.is_best_42d) == (900, True)  # 956 W beats 900
    assert (five.best_90d_w, five.is_best_90d) == (1000, False)  # but not 1000
    sixty = next(p for p in out.analytics.power_curve if p.duration_s == 60)
    assert sixty.is_best_42d is None  # nobody has a 60 s value to compare against


def test_coach_gets_compact_curve_in_focused_workout(ride: dict, athletes_dir: Path) -> None:
    store = FileStore(base_dir=athletes_dir)
    profile = store.load_athlete("renee")
    a = compute_analytics(
        laps=[], lengths=[], pauses=[], series=ride["series"], elapsed_min=None, moving_min=None, sport="bike"
    )
    w = _workout(ride).model_copy(update={"analytics": a})
    text = render_focused_workout(w, athlete=profile, hr_max=None, wellness=[])
    assert '"power_curve"' in text and '"duration": "5s"' in text
    assert '"duration_s"' not in text.split('"power_curve"')[1].split("load_au")[0]  # compact, not the raw array
