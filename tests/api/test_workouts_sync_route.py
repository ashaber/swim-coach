"""POST /api/workouts/sync -- the Log tab's primary "Sync from watch" button.

Shares its actual sync logic with the coach chat's `sync_workouts` tool (see
`app.sync.sync_on_demand`, exercised directly by test_tools.py) -- these
tests are route-level: auth, the not-configured 409, the unknown-athlete
404, and that a successful sync's counts come back over HTTP. No real
HTTP to intervals.icu (per Andrew's global "no network in tests" standard)
-- every intervals.icu call is served by an `httpx.MockTransport` handler,
forced the same way test_tools.py's `_force_mock_transport` does (the route
builds its own `IntervalsClient` with no injected transport, same as the
tool).
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fakes import auth_headers

REPO_ROOT = Path(__file__).resolve().parents[2]
FIT_FIXTURE = REPO_ROOT / "tests" / "unit" / "fixtures" / "fit" / "real_swim.fit"
_no_fit_fixture = pytest.mark.skipif(
    not FIT_FIXTURE.exists(), reason="no real .fit fixture at tests/unit/fixtures/fit/real_swim.fit"
)


def _activity(activity_id: str, **overrides) -> dict:
    data = {
        "id": activity_id,
        "start_date_local": "2026-03-14T06:00:00",
        "type": "Swim",
        "source": "GARMIN_CONNECT",
        "distance": 1623,
        "pool_length": 25,
    }
    data.update(overrides)
    return data


def _force_mock_transport(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    """See test_tools.py's `_force_mock_transport` -- the route (like the
    tool) builds its own `IntervalsClient` with `client=None`, so every
    `httpx.Client` app.sync constructs must be forced onto an
    `httpx.MockTransport`."""
    real_client_cls = httpx.Client

    def fake_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client_cls(*args, **kwargs)

    monkeypatch.setattr("app.sync.httpx.Client", fake_client)


def test_sync_route_requires_auth(client) -> None:
    response = client.post("/api/workouts/sync?athlete=renee")
    assert response.status_code == 401


def test_sync_route_unknown_athlete_is_404(client) -> None:
    response = client.post("/api/workouts/sync?athlete=nobody", headers=auth_headers())
    assert response.status_code == 404
    assert "error" in response.json()


def test_sync_route_not_configured_is_409(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INTERVALS_SYNC_CONFIG", raising=False)
    response = client.post("/api/workouts/sync?athlete=renee", headers=auth_headers())
    assert response.status_code == 409
    assert response.json() == {"error": "sync not configured for this athlete"}


def test_sync_route_athlete_not_in_config_is_409(client, monkeypatch: pytest.MonkeyPatch) -> None:
    # The env var itself is fine (andrew is configured) -- just not for the
    # athlete this request asks about.
    monkeypatch.setenv(
        "INTERVALS_SYNC_CONFIG",
        json.dumps([{"slug": "andrew", "intervals_athlete_id": "i-andrew", "api_key": "andrew-key"}]),
    )
    response = client.post("/api/workouts/sync?athlete=renee", headers=auth_headers())
    assert response.status_code == 409
    assert response.json() == {"error": "sync not configured for this athlete"}


@_no_fit_fixture
def test_sync_route_returns_counts_on_success(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "INTERVALS_SYNC_CONFIG",
        json.dumps([{"slug": "renee", "intervals_athlete_id": "i-renee", "api_key": "renee-key"}]),
    )
    fit_bytes = FIT_FIXTURE.read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/activities"):
            return httpx.Response(200, json=[_activity("i123")])
        if request.url.path == "/api/v1/activity/i123/file":
            return httpx.Response(200, content=fit_bytes)
        return httpx.Response(404, json={"error": "not found"})

    _force_mock_transport(monkeypatch, handler)

    response = client.post("/api/workouts/sync?athlete=renee", headers=auth_headers())

    assert response.status_code == 200
    assert response.json() == {"listed": 1, "new": 1, "saved": 1, "failed": 0}


def test_sync_route_nothing_new_returns_zero_counts(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "INTERVALS_SYNC_CONFIG",
        json.dumps([{"slug": "renee", "intervals_athlete_id": "i-renee", "api_key": "renee-key"}]),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/activities"):
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={"error": "not found"})

    _force_mock_transport(monkeypatch, handler)

    response = client.post("/api/workouts/sync?athlete=renee", headers=auth_headers())

    assert response.status_code == 200
    assert response.json() == {"listed": 0, "new": 0, "saved": 0, "failed": 0}
