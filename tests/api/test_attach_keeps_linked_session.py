"""Re-analysing a workout that is ALREADY linked to a planned session must analyse it with that
session (kind, prescription) -- not skip it. Prod 2026-10-17: reanalyzing the 9/20 race (already
linked to its race session, no athlete event that day) left it tagged free_ride."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from swim_coach.models import Session, Workout
from swim_coach.store import FileStore

from app import enrich

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "ride_2026_10_07_endurance_altitude.json"


@pytest.fixture()
def ride() -> dict:
    return json.loads(FIXTURE.read_text())


def test_already_linked_workout_is_reanalysed_with_its_session(
    ride: dict, athletes_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FileStore(base_dir=athletes_dir)
    session = Session.model_validate({**ride["planned_session"], "kind": "race"})
    monkeypatch.setattr(enrich, "find_planned_session", lambda *_a, **_k: session)
    w = dict(ride["workout"])
    w["analytics"] = None
    w["kind"] = "free_ride"
    w["planned_session_id"] = str(session.id)
    workout = Workout.model_validate(w)

    out = enrich.attach_planned_session(workout, store=store, slug="renee", series=ride["series"])

    assert out.planned_session_id == session.id
    assert out.kind == "race"
    assert out.analytics is not None


def test_an_existing_link_is_never_replaced(
    ride: dict, athletes_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FileStore(base_dir=athletes_dir)
    other = Session.model_validate(ride["planned_session"])
    monkeypatch.setattr(enrich, "find_planned_session", lambda *_a, **_k: other)
    w = dict(ride["workout"])
    w["planned_session_id"] = "00000000-0000-0000-0000-000000000001"
    workout = Workout.model_validate(w)

    out = enrich.attach_planned_session(workout, store=store, slug="renee", series=ride["series"])

    assert str(out.planned_session_id) == "00000000-0000-0000-0000-000000000001"
