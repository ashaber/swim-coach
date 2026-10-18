"""POST /api/workouts/{id}/race-start -- the PWA's race-start override. Shares `set_race_start`'s
implementation (override + re-run analysis) and returns the updated workout."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from fakes import auth_headers, google_token_for
from swim_coach.models import Session, Workout
from swim_coach.store import FileStore

from app import tools

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "ride_2026_10_10_starts_race_pace.json"
RENEE_EMAIL = "kline.renee@gmail.com"
ANDREW_EMAIL = "andrewshaber@gmail.com"


@pytest.fixture
def allowlist(app_env):
    store = FileStore(base_dir=app_env)
    store.add_allowed_email(RENEE_EMAIL, athlete="renee")
    store.add_allowed_email(ANDREW_EMAIL, athlete="andrew")
    return store


@pytest.fixture
def google(app):
    from app.google_auth import get_google_verifier
    from fakes import fake_google_verify

    app.dependency_overrides[get_google_verifier] = lambda: fake_google_verify
    yield
    app.dependency_overrides.pop(get_google_verifier, None)


@pytest.fixture
def ride(athletes_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Workout:
    data = json.loads(FIXTURE.read_text())
    store = FileStore(base_dir=athletes_dir)
    profile = store.load_athlete("renee").model_copy(update={"ftp_watts": 278.0, "home_elevation_m": 823.0})
    store.save_athlete(profile)
    session = Session.model_validate(data["planned_session"])
    monkeypatch.setattr(tools, "find_planned_session", lambda *_a, **_k: session)
    w = dict(data["workout"])
    w["analytics"] = None
    w["planned_session_id"] = None
    workout = Workout.model_validate(w)
    store.save_workout("renee", workout)
    store.save_series("renee", workout.date, workout.sport, workout.id, data["series"])
    return workout


def _post(client, workout_id, body, *, athlete="renee", headers=None):
    return client.post(
        f"/api/workouts/{workout_id}/race-start?athlete={athlete}", json=body, headers=headers or auth_headers()
    )


def test_race_start_requires_auth(client, ride) -> None:
    response = client.post(f"/api/workouts/{ride.id}/race-start?athlete=renee", json={"race_start": "10:00"})
    assert response.status_code == 401


def test_race_start_sets_clears_and_reanalyses(client, ride, athletes_dir) -> None:
    assert client.post(
        f"/api/workouts/{ride.id}/kind?athlete=renee", json={"kind": "race"}, headers=auth_headers()
    ).status_code == 200
    body = _post(client, ride.id, {"race_start": "10:00"}).json()
    assert body["race_start_s"] == 600.0
    saved = FileStore(base_dir=athletes_dir).get_workout("renee", ride.id)
    assert saved.race_start_s == 600.0 and saved.analytics is not None
    rs = saved.analytics.intervals.race_start
    assert rs is None or (rs.source == "override" and abs(rs.start_s - 600.0) <= 1)
    assert _post(client, ride.id, {"race_start": 725}).json()["race_start_s"] == 725.0
    assert _post(client, ride.id, {"race_start": None}).json()["race_start_s"] is None


def test_race_start_rejects_bad_input_and_unknown_workout(client, ride) -> None:
    assert _post(client, ride.id, {"race_start": "soon"}).status_code == 422
    assert _post(client, ride.id, {"race_start": -5}).status_code == 422
    assert _post(client, uuid.uuid4(), {"race_start": 60}).status_code == 404
