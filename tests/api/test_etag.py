"""Weak ETag + 304 on the polled read endpoints (GET /api/workouts, /api/plan, /api/plan/load).

The PWA re-checks these on tab switch and app resume; an unchanged answer must cost a fingerprint
query, not a payload build. Exercised against the real FileStore (the `client` fixture's tmp copy
of the athlete tree); the DbStore fingerprint is covered by the shared store contract suite.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fakes import auth_headers
from swim_coach.store import FileStore

ENDPOINTS = ["/api/workouts", "/api/plan", "/api/plan/load"]


def _get(client, path: str, athlete: str = "renee", etag: str | None = None):
    headers = auth_headers()
    if etag is not None:
        headers["If-None-Match"] = etag
    return client.get(f"{path}?athlete={athlete}", headers=headers)


@pytest.mark.parametrize("path", ENDPOINTS)
def test_get_returns_weak_etag_and_no_cache(client, path) -> None:
    response = _get(client, path)
    assert response.status_code == 200
    assert response.headers["etag"].startswith('W/"')
    assert response.headers["cache-control"] == "private, no-cache"


@pytest.mark.parametrize("path", ENDPOINTS)
def test_matching_if_none_match_returns_304_without_body(client, path) -> None:
    etag = _get(client, path).headers["etag"]
    response = _get(client, path, etag=etag)
    assert response.status_code == 304
    assert response.content == b""
    assert response.headers["etag"] == etag


@pytest.mark.parametrize("path", ENDPOINTS)
def test_stale_if_none_match_returns_full_payload(client, path) -> None:
    response = _get(client, path, etag='W/"stale"')
    assert response.status_code == 200
    assert response.content


def test_etag_list_in_if_none_match_is_honoured(client) -> None:
    etag = _get(client, "/api/plan").headers["etag"]
    assert _get(client, "/api/plan", etag=f'W/"other", {etag}').status_code == 304


def test_saving_a_workout_changes_the_workouts_etag_but_not_the_plan_etag(client) -> None:
    workouts_before = _get(client, "/api/workouts").headers["etag"]
    plan_before = _get(client, "/api/plan").headers["etag"]
    created = client.post(
        "/api/workouts?athlete=renee",
        json={"date": "2026-07-07", "sport": "swim_pool", "distance_m": 3000, "duration_min": 60, "rpe": 6},
        headers=auth_headers(),
    )
    assert created.status_code == 200
    changed = _get(client, "/api/workouts", etag=workouts_before)
    assert changed.status_code == 200
    assert changed.headers["etag"] != workouts_before
    assert _get(client, "/api/plan", etag=plan_before).status_code == 304


def test_patching_a_plan_week_changes_the_plan_and_load_etags(client, app_env: Path) -> None:
    plan_before = _get(client, "/api/plan").headers["etag"]
    load_before = _get(client, "/api/plan/load").headers["etag"]
    store = FileStore(base_dir=app_env)
    week_id = store.list_week_ids("renee")[-1]
    week = store.load_week("renee", week_id)
    week.sessions[0].purpose = f"coach changed this {time.time_ns()}"
    store.save_week("renee", week)
    plan_after = _get(client, "/api/plan", etag=plan_before)
    assert plan_after.status_code == 200
    assert plan_after.headers["etag"] != plan_before
    assert _get(client, "/api/plan/load", etag=load_before).status_code == 200


def test_different_athletes_never_share_an_etag(client) -> None:
    for path in ENDPOINTS:
        renee = _get(client, path, "renee").headers["etag"]
        tim = _get(client, path, "tim").headers["etag"]
        assert renee != tim
        # Presenting one athlete's ETag for another's data must not yield a 304.
        assert _get(client, path, "tim", etag=renee).status_code == 200


def test_different_load_window_has_a_different_etag(client) -> None:
    short = client.get("/api/plan/load?athlete=renee&weeks=4", headers=auth_headers()).headers["etag"]
    long = client.get("/api/plan/load?athlete=renee&weeks=12", headers=auth_headers()).headers["etag"]
    assert short != long


@pytest.mark.parametrize("path", ENDPOINTS)
def test_unknown_athlete_is_still_404_not_304(client, path) -> None:
    response = _get(client, path, "nobody", etag='W/"anything"')
    assert response.status_code == 404


def test_cors_exposes_etag_and_allows_if_none_match(client) -> None:
    preflight = client.options(
        "/api/plan?athlete=renee",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "if-none-match,authorization",
        },
    )
    assert preflight.status_code == 200
    assert "if-none-match" in preflight.headers["access-control-allow-headers"].lower()
    actual = client.get(
        "/api/plan?athlete=renee", headers={**auth_headers(), "Origin": "http://localhost:5173"}
    )
    assert "etag" in actual.headers["access-control-expose-headers"].lower()
