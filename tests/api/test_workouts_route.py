"""POST/GET /api/workouts -- logging and listing completed workouts.

Exercises the real `FileStore` (via the `client` fixture's isolated
`ATHLETES_DIR` tmp copy of `athletes/renee`) rather than a fake, so these
tests also prove the `make_store` seam end-to-end: a logged workout is
immediately visible to a subsequent GET, exactly like it would be against
`DbStore` in production.
"""

from __future__ import annotations

from fakes import auth_headers


def _valid_payload(**overrides) -> dict:
    payload = {
        "date": "2026-07-07",
        "sport": "swim_pool",
        "distance_m": 3000,
        "duration_min": 60,
        "rpe": 6,
        "notes": "felt smooth",
    }
    payload.update(overrides)
    return payload


def test_create_workout_requires_auth(client) -> None:
    response = client.post("/api/workouts?athlete=renee", json=_valid_payload())
    assert response.status_code == 401


def test_list_workouts_requires_auth(client) -> None:
    response = client.get("/api/workouts?athlete=renee")
    assert response.status_code == 401


def test_create_workout_persists_and_returns_created_object(client) -> None:
    response = client.post(
        "/api/workouts?athlete=renee", json=_valid_payload(), headers=auth_headers()
    )
    assert response.status_code == 200
    body = response.json()
    assert body["date"] == "2026-07-07"
    assert body["sport"] == "swim_pool"
    assert body["distance_m"] == 3000
    assert body["duration_min"] == 60
    assert body["rpe"] == 6
    assert body["notes"] == "felt smooth"
    assert body["source"] == "manual"
    assert body["schema_version"] == 1
    # Server-assigned fields.
    assert body["id"]
    assert body["athlete_id"]


def test_create_workout_rejects_invalid_input(client) -> None:
    response = client.post(
        "/api/workouts?athlete=renee",
        json=_valid_payload(sport="not_a_real_sport"),
        headers=auth_headers(),
    )
    assert response.status_code == 422
    assert "error" in response.json()


def test_create_workout_rejects_missing_required_field(client) -> None:
    payload = _valid_payload()
    del payload["distance_m"]
    response = client.post(
        "/api/workouts?athlete=renee", json=payload, headers=auth_headers()
    )
    assert response.status_code == 422
    assert "error" in response.json()


def test_create_workout_unknown_athlete_is_404(client) -> None:
    response = client.post(
        "/api/workouts?athlete=nobody", json=_valid_payload(), headers=auth_headers()
    )
    assert response.status_code == 404
    assert "error" in response.json()


def test_list_workouts_returns_what_was_saved(client) -> None:
    created = []
    for distance in (2000, 4000):
        response = client.post(
            "/api/workouts?athlete=renee",
            json=_valid_payload(distance_m=distance),
            headers=auth_headers(),
        )
        assert response.status_code == 200
        created.append(response.json())

    response = client.get("/api/workouts?athlete=renee", headers=auth_headers())
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    created_ids = {w["id"] for w in created}
    returned_ids = {w["id"] for w in body}
    assert created_ids.issubset(returned_ids)


def test_list_workouts_unknown_athlete_is_404(client) -> None:
    response = client.get("/api/workouts?athlete=nobody", headers=auth_headers())
    assert response.status_code == 404
    assert "error" in response.json()
