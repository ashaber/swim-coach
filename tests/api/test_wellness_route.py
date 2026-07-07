"""POST/GET /api/wellness -- logging and listing daily wellness check-ins.

Same shape/conventions as test_workouts_route.py -- see that file's module
docstring for why the real `FileStore` (not a fake) is exercised here.
"""

from __future__ import annotations

from fakes import auth_headers


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
