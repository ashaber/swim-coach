"""GET /api/workouts/{workout_id}/pacing -- the PWA's read of the same GPS-lap/race-phase
analysis the coach's own `get_ride_pacing` chat tool returns (Andrew, 2026-09-22: visible on the
race activity's own detail view, not only through chat). Thin wiring test: the full lap-detection
math is already covered by tests/api/test_ride_pacing_tool.py's synthetic-GPS-loop fixtures --
these tests only prove the route delegates to that handler and maps its errors to the right
status codes."""

from __future__ import annotations

import uuid

import pytest
from fakes import auth_headers


def _bike_payload(**overrides) -> dict:
    payload = {
        "date": "2026-09-19",
        "sport": "bike",
        "distance_m": 20000,
        "duration_min": 45,
        "rpe": 8,
    }
    payload.update(overrides)
    return payload


def test_pacing_requires_auth(client) -> None:
    response = client.get(f"/api/workouts/{uuid.uuid4()}/pacing?athlete=renee")
    assert response.status_code == 401


def test_pacing_404s_for_an_unknown_workout_id(client) -> None:
    response = client.get(f"/api/workouts/{uuid.uuid4()}/pacing?athlete=renee", headers=auth_headers())
    assert response.status_code == 404
    assert "no workout matching id" in response.json()["error"]


def test_pacing_422s_for_a_non_bike_workout(client) -> None:
    created = client.post(
        "/api/workouts?athlete=renee",
        json={"date": "2026-09-19", "sport": "swim_pool", "distance_m": 2000, "duration_min": 40, "rpe": 5},
        headers=auth_headers(),
    ).json()
    response = client.get(f"/api/workouts/{created['id']}/pacing?athlete=renee", headers=auth_headers())
    assert response.status_code == 422
    assert "only runs on bike rides" in response.json()["error"]


def test_pacing_422s_for_a_bike_workout_with_no_series_data(client) -> None:
    created = client.post(
        "/api/workouts?athlete=renee", json=_bike_payload(), headers=auth_headers()
    ).json()
    response = client.get(f"/api/workouts/{created['id']}/pacing?athlete=renee", headers=auth_headers())
    assert response.status_code == 422
    assert "no time-series data" in response.json()["error"]
