"""Planned-zone wiring (enrich -> analyzer) and coach visibility of the ride altitude note,
on the real 10/7 steady Z2 club ride (no `structured` on the planned session)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from swim_coach.models import Session, Workout
from swim_coach.store import FileStore

from app import enrich
from app.context import render_focused_workout

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "ride_2026_10_07_endurance_altitude.json"


@pytest.fixture()
def ride() -> dict:
    return json.loads(FIXTURE.read_text())


def _workout(ride: dict) -> Workout:
    w = dict(ride["workout"])
    w["analytics"] = None
    w["planned_session_id"] = None
    return Workout.model_validate(w)


def test_attach_planned_session_runs_analyzer_for_unstructured_session(
    ride: dict, athletes_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FileStore(base_dir=athletes_dir)
    profile = store.load_athlete("renee").model_copy(update={"ftp_watts": 278.0, "home_elevation_m": 823.0})
    session = Session.model_validate(ride["planned_session"])
    assert session.structured is None
    monkeypatch.setattr(enrich, "find_planned_session", lambda *_a, **_k: session)

    out = enrich.attach_planned_session(
        _workout(ride), store=store, slug="renee", profile=profile, series=ride["series"]
    )

    assert out.planned_session_id == session.id
    iv = out.analytics.intervals
    assert iv.decoupling_tightened_pct is not None
    assert "all-interval" not in (iv.decoupling_note or "")
    assert iv.ride_altitude_note and "not adjusted" in iv.ride_altitude_note


def test_coach_focused_workout_context_carries_ride_altitude_note(
    ride: dict, athletes_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FileStore(base_dir=athletes_dir)
    profile = store.load_athlete("renee").model_copy(update={"ftp_watts": 278.0, "home_elevation_m": 823.0})
    session = Session.model_validate(ride["planned_session"])
    monkeypatch.setattr(enrich, "find_planned_session", lambda *_a, **_k: session)
    out = enrich.attach_planned_session(
        _workout(ride), store=store, slug="renee", profile=profile, series=ride["series"]
    )

    text = render_focused_workout(out, athlete=profile, hr_max=None, wellness=[])

    assert "ride_altitude_note" in text
    assert out.analytics.intervals.ride_altitude_note in text
