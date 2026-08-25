"""POST/GET/PATCH /api/grants -- athlete-side coach-grant management
(coach-mode Phase 1). Self-access gated via `resolve_athlete` (same as
routes/feedback.py's `?athlete=` routes), backed by
`store.create_coach_grant`/`list_coach_grants`/`revoke_coach_grant`
(engine/swim_coach/store.py, merged on main).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fakes import auth_headers, google_token_for
from swim_coach.store import FileStore

ANDREW_EMAIL = "andrewshaber@gmail.com"
RENEE_EMAIL = "kline.renee@gmail.com"
TIM_EMAIL = "curry.mtb@gmail.com"


@pytest.fixture
def store(app_env: Path) -> FileStore:
    return FileStore(base_dir=app_env)


@pytest.fixture
def allowlist(store: FileStore) -> FileStore:
    store.add_allowed_email(ANDREW_EMAIL, athlete="andrew")
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


def _renee_headers(client, allowlist, google) -> dict:
    token = _sign_in(client, RENEE_EMAIL).json()["token"]
    return _bearer(token)


# --- POST /api/grants --------------------------------------------------------


def test_create_grant_requires_auth(client) -> None:
    response = client.post("/api/grants?athlete=renee", json={"coach_slug": "tim"})
    assert response.status_code == 401


def test_create_grant_happy_path_service_token(client, allowlist) -> None:
    response = client.post(
        "/api/grants?athlete=renee", json={"coach_slug": "tim"}, headers=auth_headers()
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "active"
    assert body["chat_visibility"] == "shared_only"
    assert body["id"]
    assert body["granted_at"]


def test_create_grant_happy_path_athlete_session(client, allowlist, google) -> None:
    headers = _renee_headers(client, allowlist, google)
    response = client.post("/api/grants?athlete=renee", json={"coach_slug": "tim"}, headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "active"


def test_create_grant_missing_coach_slug_is_422(client, allowlist) -> None:
    response = client.post("/api/grants?athlete=renee", json={}, headers=auth_headers())
    assert response.status_code == 422
    assert "error" in response.json()


def test_create_grant_wrong_type_coach_slug_is_422(client, allowlist) -> None:
    response = client.post(
        "/api/grants?athlete=renee", json={"coach_slug": 123}, headers=auth_headers()
    )
    assert response.status_code == 422
    assert "error" in response.json()


def test_create_grant_self_grant_is_422(client, allowlist) -> None:
    response = client.post(
        "/api/grants?athlete=renee", json={"coach_slug": "renee"}, headers=auth_headers()
    )
    assert response.status_code == 422
    assert "error" in response.json()


def test_create_grant_unknown_coach_slug_is_404(client, allowlist) -> None:
    response = client.post(
        "/api/grants?athlete=renee", json={"coach_slug": "nobody"}, headers=auth_headers()
    )
    assert response.status_code == 404
    assert "error" in response.json()


def test_create_grant_cross_athlete_denied(client, allowlist, google) -> None:
    # A tim session may not create a grant on renee's behalf by passing a
    # different ?athlete=.
    token = _sign_in(client, TIM_EMAIL).json()["token"]
    response = client.post(
        "/api/grants?athlete=renee", json={"coach_slug": "andrew"}, headers=_bearer(token)
    )
    assert response.status_code == 403


# --- GET /api/grants ----------------------------------------------------------


def test_list_grants_requires_auth(client) -> None:
    response = client.get("/api/grants?athlete=renee")
    assert response.status_code == 401


def test_list_grants_returns_grants_where_athlete_is_coached(client, allowlist) -> None:
    client.post("/api/grants?athlete=renee", json={"coach_slug": "tim"}, headers=auth_headers())
    client.post("/api/grants?athlete=andrew", json={"coach_slug": "tim"}, headers=auth_headers())

    response = client.get("/api/grants?athlete=renee", headers=auth_headers())
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1


def test_list_grants_cross_athlete_denied(client, allowlist, google) -> None:
    token = _sign_in(client, TIM_EMAIL).json()["token"]
    response = client.get("/api/grants?athlete=renee", headers=_bearer(token))
    assert response.status_code == 403


# --- PATCH /api/grants/{grant_id} ---------------------------------------------


def test_revoke_grant_requires_auth(client, allowlist) -> None:
    created = client.post(
        "/api/grants?athlete=renee", json={"coach_slug": "tim"}, headers=auth_headers()
    ).json()
    response = client.patch(f"/api/grants/{created['id']}?athlete=renee", json={})
    assert response.status_code == 401


def test_revoke_grant_happy_path(client, allowlist) -> None:
    created = client.post(
        "/api/grants?athlete=renee", json={"coach_slug": "tim"}, headers=auth_headers()
    ).json()
    response = client.patch(
        f"/api/grants/{created['id']}?athlete=renee", json={}, headers=auth_headers()
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == created["id"]
    assert body["status"] == "revoked"
    assert body["revoked_at"]


def test_revoke_grant_by_non_owner_is_404(client, allowlist) -> None:
    # A grant made by renee cannot be revoked by naming ?athlete=andrew.
    created = client.post(
        "/api/grants?athlete=renee", json={"coach_slug": "tim"}, headers=auth_headers()
    ).json()
    response = client.patch(
        f"/api/grants/{created['id']}?athlete=andrew", json={}, headers=auth_headers()
    )
    assert response.status_code == 404


def test_revoke_grant_unknown_id_is_404(client, allowlist) -> None:
    response = client.patch(
        "/api/grants/00000000-0000-0000-0000-000000000000?athlete=renee",
        json={},
        headers=auth_headers(),
    )
    assert response.status_code == 404


def test_revoke_grant_cross_athlete_denied_style_regression(client, allowlist, google) -> None:
    # renee creates a grant; a tim SESSION must not be able to revoke it by
    # passing ?athlete=renee (cross-athlete guarantee, mirrors
    # test_auth_identity.py's cross-athlete-denied regression test).
    created = client.post(
        "/api/grants?athlete=renee", json={"coach_slug": "tim"}, headers=auth_headers()
    ).json()

    token = _sign_in(client, TIM_EMAIL).json()["token"]
    response = client.patch(
        f"/api/grants/{created['id']}?athlete=renee", json={}, headers=_bearer(token)
    )
    assert response.status_code == 403

    # And an athlete may not list another athlete's grants by swapping the
    # query param either.
    response2 = client.get("/api/grants?athlete=renee", headers=_bearer(token))
    assert response2.status_code == 403
