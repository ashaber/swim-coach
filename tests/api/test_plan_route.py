"""GET /api/plan -- reuses scripts/export_plan_json.export_athlete."""

from __future__ import annotations

from fakes import auth_headers


def test_plan_requires_auth(client) -> None:
    response = client.get("/api/plan?athlete=renee")
    assert response.status_code == 401


def test_plan_returns_exported_shape(client) -> None:
    response = client.get("/api/plan?athlete=renee", headers=auth_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == "renee"
    assert body["name"] == "Renee"
    assert "athlete" in body
    assert "events" in body
    assert "macro" in body
    assert "weeks" in body
    assert len(body["weeks"]) >= 1


def test_plan_unknown_athlete_is_404(client) -> None:
    response = client.get("/api/plan?athlete=nobody", headers=auth_headers())
    assert response.status_code == 404
    assert "error" in response.json()
