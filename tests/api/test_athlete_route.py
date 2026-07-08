"""GET/PATCH /api/athlete -- self-service profile read/edit.

Same conventions as test_workouts_route.py / test_wellness_route.py: exercises
the real `FileStore` (via the `client` fixture's isolated `ATHLETES_DIR` tmp
copy of `athletes/renee`), not a fake, so these tests also prove the
`make_store` seam end-to-end.
"""

from __future__ import annotations

import yaml

from fakes import auth_headers


def test_get_athlete_requires_auth(client) -> None:
    response = client.get("/api/athlete?athlete=renee")
    assert response.status_code == 401


def test_patch_athlete_requires_auth(client) -> None:
    response = client.patch("/api/athlete?athlete=renee", json={"name": "Renee K"})
    assert response.status_code == 401


def test_get_athlete_returns_profile(client) -> None:
    response = client.get("/api/athlete?athlete=renee", headers=auth_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == "renee"
    assert body["name"] == "Renee"
    assert body["css_pace_s_per_100m"] == 90.0
    assert "zones" in body


def test_get_athlete_unknown_athlete_is_404(client) -> None:
    response = client.get("/api/athlete?athlete=nobody", headers=auth_headers())
    assert response.status_code == 404
    assert "error" in response.json()


def test_patch_athlete_updates_editable_fields_and_persists(client, athletes_dir) -> None:
    response = client.patch(
        "/api/athlete?athlete=renee",
        json={
            "name": "Renee Kline",
            "dob": "1980-02-15",
            "sex": "female",
            "height_cm": 168.0,
            "weight_kg": 60.0,
        },
        headers=auth_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Renee Kline"
    assert body["dob"] == "1980-02-15"
    assert body["sex"] == "female"
    assert body["height_cm"] == 168.0
    assert body["weight_kg"] == 60.0

    on_disk = yaml.safe_load((athletes_dir / "renee" / "profile.yaml").read_text())
    assert on_disk["name"] == "Renee Kline"
    assert on_disk["dob"] == "1980-02-15"


def test_patch_athlete_recomputes_zones_when_css_pace_changes(client) -> None:
    get_response = client.get("/api/athlete?athlete=renee", headers=auth_headers())
    original_zones = get_response.json()["zones"]

    response = client.patch(
        "/api/athlete?athlete=renee",
        json={"css_pace_s_per_100m": 85.0},
        headers=auth_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["css_pace_s_per_100m"] == 85.0
    assert body["zones"] != original_zones
    # Zone table is derived from the engine's own zone_table(), not hand
    # computed here -- spot check one anchor: Z4 lo offset is -1.0 (see
    # engine/swim_coach/zones.py).
    assert body["zones"]["Z4"]["pace_lo_s"] == 84.0


def test_patch_athlete_does_not_recompute_zones_when_css_pace_unchanged(client) -> None:
    get_response = client.get("/api/athlete?athlete=renee", headers=auth_headers())
    original_zones = get_response.json()["zones"]

    response = client.patch(
        "/api/athlete?athlete=renee",
        json={"name": "Renee Kline"},
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert response.json()["zones"] == original_zones


def test_patch_athlete_strips_server_assigned_fields(client) -> None:
    get_response = client.get("/api/athlete?athlete=renee", headers=auth_headers())
    original = get_response.json()

    response = client.patch(
        "/api/athlete?athlete=renee",
        json={
            "id": "11111111-1111-1111-1111-111111111111",
            "slug": "not-renee",
            "schema_version": 99,
            "zones": {"fake": True},
            "name": "Renee Kline",
        },
        headers=auth_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == original["id"]
    assert body["slug"] == "renee"
    assert body["schema_version"] == 1
    assert body["zones"] != {"fake": True}
    assert body["name"] == "Renee Kline"


def test_patch_athlete_rejects_invalid_input(client) -> None:
    response = client.patch(
        "/api/athlete?athlete=renee",
        json={"sex": "not_a_real_sex"},
        headers=auth_headers(),
    )
    assert response.status_code == 422
    assert "error" in response.json()


def test_patch_athlete_rejects_invalid_height(client) -> None:
    response = client.patch(
        "/api/athlete?athlete=renee",
        json={"height_cm": -5},
        headers=auth_headers(),
    )
    assert response.status_code == 422
    assert "error" in response.json()


def test_patch_athlete_unknown_athlete_is_404(client) -> None:
    response = client.patch(
        "/api/athlete?athlete=nobody", json={"name": "X"}, headers=auth_headers()
    )
    assert response.status_code == 404
    assert "error" in response.json()


def test_patch_athlete_can_update_pool_schedule(client) -> None:
    response = client.patch(
        "/api/athlete?athlete=renee",
        json={"pool_schedule": ["monday", "wednesday"]},
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert response.json()["pool_schedule"] == ["monday", "wednesday"]
