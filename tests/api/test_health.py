"""GET /health -- no auth required, used as the Kubernetes/Cloud Run
liveness probe."""

from __future__ import annotations


def test_health_ok(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
