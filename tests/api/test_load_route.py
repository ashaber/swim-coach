"""GET /api/plan/load (athlete self-access) and
GET /api/coach/athletes/{slug}/load (coach access) -- surfaces
`context.summarize_rollup`'s `ctl_atl_tsb` Banister CTL/ATL/TSB series
directly to the frontend, so the PWA can render a chart without going
through the coach-chat `get_plan_summary` tool.

Follows `test_plan_route.py`'s pattern for the self-access route and
`test_coach_route.py`'s pattern (fakes' `_sign_in`/`allowlist`/`google`
fixtures, `resolve_coach_athlete` 403-without-grant check) for the coach
route.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from fakes import auth_headers, google_token_for, make_workout
from swim_coach.store import FileStore

RENEE_EMAIL = "kline.renee@gmail.com"
TIM_EMAIL = "curry.mtb@gmail.com"


@pytest.fixture
def store(app_env: Path) -> FileStore:
    return FileStore(base_dir=app_env)


@pytest.fixture
def allowlist(store: FileStore) -> FileStore:
    store.add_allowed_email(RENEE_EMAIL, athlete="renee")
    store.add_allowed_email(TIM_EMAIL, athlete="tim")
    return store


@pytest.fixture
def google(app):
    from app.google_auth import get_google_verifier
    from fakes import fake_google_verify

    app.dependency_overrides[get_google_verifier] = lambda: fake_google_verify
    yield
    app.dependency_overrides.pop(get_google_verifier, None)


def _sign_in(client, email: str) -> dict:
    return client.post("/api/auth/google", json={"id_token": google_token_for(email)})


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _headers_for(client, allowlist, google, email: str) -> dict:
    token = _sign_in(client, email).json()["token"]
    return _bearer(token)


def _save_workout_for(store: FileStore, slug: str, **overrides) -> None:
    profile = store.load_athlete(slug)
    workout = make_workout(athlete_id=profile.id, **overrides)
    store.save_workout(slug, workout)


# --- GET /api/plan/load (athlete self-access) --------------------------------


def test_athlete_load_requires_auth(client) -> None:
    response = client.get("/api/plan/load?athlete=renee")
    assert response.status_code == 401


def test_athlete_load_returns_ctl_atl_tsb_shape(client, store) -> None:
    # A workout dated "today" so it lands inside any reasonable trailing
    # window regardless of what today's real date happens to be when this
    # test runs.
    _save_workout_for(store, "renee", date=date.today(), rpe=6, duration_min=60.0)

    response = client.get("/api/plan/load?athlete=renee", headers=auth_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["athlete"] == "renee"
    assert "weeks" in body
    assert isinstance(body["weeks"], int)
    assert "ctl_atl_tsb" in body
    series = body["ctl_atl_tsb"]
    assert isinstance(series, list)
    assert len(series) >= 1
    for point in series:
        assert len(point) == 4
        iso_date, ctl, atl, tsb = point
        date.fromisoformat(iso_date)  # doesn't raise
        assert isinstance(ctl, (int, float))
        assert isinstance(atl, (int, float))
        assert isinstance(tsb, (int, float))


def test_athlete_load_empty_history_returns_empty_series(client) -> None:
    # No workouts saved beyond whatever the seeded renee fixture tree
    # already ships with (which may be none/old) -- either way, this must
    # not error; an empty/short series is a valid, honest response, not a
    # failure (see `ctl_atl_tsb_series`'s cold-start docstring caveat).
    response = client.get("/api/plan/load?athlete=renee&weeks=1", headers=auth_headers())
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["ctl_atl_tsb"], list)


def test_athlete_load_respects_weeks_query_param(client, store) -> None:
    _save_workout_for(store, "renee", date=date.today(), rpe=6, duration_min=60.0)
    response = client.get("/api/plan/load?athlete=renee&weeks=2", headers=auth_headers())
    assert response.status_code == 200
    assert response.json()["weeks"] == 2


def test_athlete_load_default_weeks_window_is_longer_than_summary_default(client) -> None:
    # get_plan_summary's own default is 4 weeks (too short to read a CTL
    # trend against its 42-day time constant) -- this route's default
    # should be longer, per the task's "the CTL/ATL series benefits from a
    # longer window" judgment call.
    response = client.get("/api/plan/load?athlete=renee", headers=auth_headers())
    assert response.status_code == 200
    assert response.json()["weeks"] > 4


def test_athlete_load_unknown_athlete_is_404(client) -> None:
    response = client.get("/api/plan/load?athlete=nobody", headers=auth_headers())
    assert response.status_code == 404
    assert "error" in response.json()


def test_athlete_session_cannot_read_another_athletes_load(
    client, allowlist, google
) -> None:
    headers = _headers_for(client, allowlist, google, RENEE_EMAIL)
    response = client.get("/api/plan/load?athlete=tim", headers=headers)
    assert response.status_code == 403


# --- GET /api/coach/athletes/{slug}/load (coach access) -----------------------


def test_coach_load_requires_auth(client) -> None:
    response = client.get("/api/coach/athletes/renee/load")
    assert response.status_code == 401


def test_coach_load_403_without_grant(client, allowlist, google) -> None:
    headers = _headers_for(client, allowlist, google, TIM_EMAIL)
    response = client.get("/api/coach/athletes/renee/load", headers=headers)
    assert response.status_code == 403


def test_coach_load_returns_ctl_atl_tsb_for_granted_athlete(
    client, allowlist, store, google
) -> None:
    store.create_coach_grant(coach_slug="tim", athlete_slug="renee")
    _save_workout_for(store, "renee", date=date.today(), rpe=6, duration_min=60.0)

    headers = _headers_for(client, allowlist, google, TIM_EMAIL)
    response = client.get("/api/coach/athletes/renee/load", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["athlete"] == "renee"
    assert isinstance(body["ctl_atl_tsb"], list)
    assert len(body["ctl_atl_tsb"]) >= 1


def test_coach_load_service_token_passes(client, allowlist, store) -> None:
    _save_workout_for(store, "renee", date=date.today(), rpe=6, duration_min=60.0)
    response = client.get("/api/coach/athletes/renee/load", headers=auth_headers())
    assert response.status_code == 200
