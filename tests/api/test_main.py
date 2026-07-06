"""Global exception handling: an unhandled exception in a route must
become a structured `{"error": ...}` 500, never a bare traceback/HTML."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_unhandled_exception_returns_structured_500(app) -> None:
    @app.get("/__boom_for_test__")
    def boom():  # pragma: no cover - trivial
        raise RuntimeError("kaboom")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/__boom_for_test__")

    assert response.status_code == 500
    assert response.json() == {"error": "internal server error"}
