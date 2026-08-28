"""POST/GET /api/wellness -- logging and listing daily wellness check-ins.

Same shape/conventions as test_workouts_route.py -- see that file's module
docstring for why the real `FileStore` (not a fake) is exercised here.
"""

from __future__ import annotations

import uuid
from datetime import date

from fakes import auth_headers
from swim_coach.models import Wellness
from swim_coach.store import FileStore


def _valid_payload(**overrides) -> dict:
    payload = {
        "date": "2026-07-07",
        "sleep_quality": 4,
        "sleep_hours": 7.5,
        "stress": 2,
        "soreness": 3,
        "motivation": 4,
        "resting_hr": 52,
        "hrv": 61.2,
        "notes": "felt good today",
    }
    payload.update(overrides)
    return payload


def test_create_wellness_requires_auth(client) -> None:
    response = client.post("/api/wellness?athlete=renee", json=_valid_payload())
    assert response.status_code == 401


def test_list_wellness_requires_auth(client) -> None:
    response = client.get("/api/wellness?athlete=renee")
    assert response.status_code == 401


def test_create_wellness_persists_and_returns_created_object(client) -> None:
    response = client.post(
        "/api/wellness?athlete=renee", json=_valid_payload(), headers=auth_headers()
    )
    assert response.status_code == 200
    body = response.json()
    assert body["date"] == "2026-07-07"
    assert body["sleep_quality"] == 4
    assert body["sleep_hours"] == 7.5
    assert body["stress"] == 2
    assert body["soreness"] == 3
    assert body["motivation"] == 4
    assert body["resting_hr"] == 52
    assert body["hrv"] == 61.2
    assert body["notes"] == "felt good today"
    assert body["schema_version"] == 1
    assert body["id"]
    assert body["athlete_id"]


def test_create_wellness_rejects_out_of_range_score(client) -> None:
    response = client.post(
        "/api/wellness?athlete=renee",
        json=_valid_payload(sleep_quality=9),
        headers=auth_headers(),
    )
    assert response.status_code == 422
    assert "error" in response.json()


def test_create_wellness_rejects_missing_required_field(client) -> None:
    payload = _valid_payload()
    del payload["sleep_hours"]
    response = client.post(
        "/api/wellness?athlete=renee", json=payload, headers=auth_headers()
    )
    assert response.status_code == 422
    assert "error" in response.json()


def test_create_wellness_unknown_athlete_is_404(client) -> None:
    response = client.post(
        "/api/wellness?athlete=nobody", json=_valid_payload(), headers=auth_headers()
    )
    assert response.status_code == 404
    assert "error" in response.json()


def test_list_wellness_returns_what_was_saved(client) -> None:
    created = []
    for date in ("2026-07-06", "2026-07-07"):
        response = client.post(
            "/api/wellness?athlete=renee",
            json=_valid_payload(date=date),
            headers=auth_headers(),
        )
        assert response.status_code == 200
        created.append(response.json())

    response = client.get("/api/wellness?athlete=renee", headers=auth_headers())
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    created_ids = {w["id"] for w in created}
    returned_ids = {w["id"] for w in body}
    assert created_ids.issubset(returned_ids)


def test_list_wellness_unknown_athlete_is_404(client) -> None:
    response = client.get("/api/wellness?athlete=nobody", headers=auth_headers())
    assert response.status_code == 404
    assert "error" in response.json()


# --- clobber-bug fix: check-in must merge, never blindly overwrite ---------


def _seed_synced_wellness(athletes_dir, *, day: str, resting_hr: int, hrv: float) -> Wellness:
    store = FileStore(base_dir=athletes_dir)
    profile = store.load_athlete("renee")
    wellness = Wellness(
        id=uuid.uuid4(),
        athlete_id=profile.id,
        date=date.fromisoformat(day),
        resting_hr=resting_hr,
        hrv=hrv,
        source="intervals_sync",
    )
    store.save_wellness("renee", wellness)
    return wellness


def test_checkin_with_no_resting_hr_hrv_preserves_existing_synced_value(client, athletes_dir) -> None:
    _seed_synced_wellness(athletes_dir, day="2026-07-08", resting_hr=48, hrv=65.0)

    payload = _valid_payload(date="2026-07-08")
    del payload["resting_hr"]
    del payload["hrv"]
    response = client.post(
        "/api/wellness?athlete=renee", json=payload, headers=auth_headers()
    )
    assert response.status_code == 200
    body = response.json()
    assert body["resting_hr"] == 48
    assert body["hrv"] == 65.0
    assert body["sleep_quality"] == 4  # the manual check-in's own fields still land


def test_checkin_explicit_resting_hr_overwrites_synced_value(client, athletes_dir) -> None:
    _seed_synced_wellness(athletes_dir, day="2026-07-09", resting_hr=48, hrv=65.0)

    response = client.post(
        "/api/wellness?athlete=renee",
        json=_valid_payload(date="2026-07-09", resting_hr=55, hrv=70.0),
        headers=auth_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    # Manual correction wins over the previously synced value.
    assert body["resting_hr"] == 55
    assert body["hrv"] == 70.0


def test_checkin_always_sets_source_manual_even_over_synced_row(client, athletes_dir) -> None:
    _seed_synced_wellness(athletes_dir, day="2026-07-10", resting_hr=48, hrv=65.0)

    response = client.post(
        "/api/wellness?athlete=renee",
        json=_valid_payload(date="2026-07-10"),
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert response.json()["source"] == "manual"
