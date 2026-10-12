"""POST /api/workouts/{id}/kind -- the PWA's retag control. Shares `set_workout_kind`'s
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
        f"/api/workouts/{workout_id}/kind?athlete={athlete}", json=body, headers=headers or auth_headers()
    )


def test_kind_requires_auth(client, ride) -> None:
    response = client.post(f"/api/workouts/{ride.id}/kind?athlete=renee", json={"kind": "race"})
    assert response.status_code == 401


def test_retag_sets_the_override_and_reanalyses(client, ride, athletes_dir) -> None:
    response = _post(client, ride.id, {"kind": "race"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(ride.id) and body["kind_override"] == "race"
    assert "load_au" in body
    iv = body["analytics"]["intervals"]
    assert len(iv["starts"]) == 5 and iv["starts"][0]["trace_w"]  # re-analysed, stored
    saved = FileStore(base_dir=athletes_dir).get_workout("renee", ride.id)
    assert saved.kind_override == "race" and saved.analytics is not None


def test_retag_can_change_it_back(client, ride) -> None:
    assert _post(client, ride.id, {"kind": "free_ride"}).json()["kind_override"] == "free_ride"
    assert _post(client, ride.id, {"kind": "workout"}).json()["kind_override"] == "workout"


def test_invalid_kind_is_422(client, ride) -> None:
    response = _post(client, ride.id, {"kind": "interval"})
    assert response.status_code == 422 and "invalid session kind" in response.json()["error"]
    assert _post(client, ride.id, {}).status_code == 422


def test_unknown_workout_and_unknown_athlete_are_404(client, ride) -> None:
    assert _post(client, uuid.uuid4(), {"kind": "race"}).status_code == 404
    assert _post(client, ride.id, {"kind": "race"}, athlete="nobody").status_code == 404


def test_other_athletes_workout_is_not_reachable(client, ride, allowlist, google) -> None:
    token = client.post("/api/auth/google", json={"id_token": google_token_for(ANDREW_EMAIL)}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    # andrew's session is scoped to andrew: renee's workout id never resolves, and asking for
    # renee's tree is refused.
    assert _post(client, ride.id, {"kind": "race"}, athlete="andrew", headers=headers).status_code == 404
    assert _post(client, ride.id, {"kind": "race"}, athlete="renee", headers=headers).status_code in (401, 403)
