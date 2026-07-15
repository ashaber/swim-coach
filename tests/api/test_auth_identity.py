"""Server-side verified identity: POST /api/auth/google, GET /api/me, and
principal-aware athlete scoping (Slice 1 of the auth plan).

Google's real token verification is never exercised here (no network in
tests -- hard repo rule): `get_google_verifier` is overridden with
`fake_google_verify` (see fakes.py), which accepts a `valid:<email>` token
and raises ValueError for anything else, mirroring google-auth's own
ValueError-on-any-failure contract.

The regression test that must never go red lives here:
`test_cross_athlete_denied_on_every_scoped_route` -- a Tim session asking for
?athlete=renee is 403 on every athlete-scoped route. Its counterpart,
`test_service_token_reaches_any_athlete_on_every_route`, is the "nothing
breaks" guarantee: the legacy shared API_TOKEN still reaches any athlete.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fakes import (
    auth_headers,
    fake_google_verify,
    google_token_for,
    make_final_message,
    make_text_block,
)
from swim_coach.store import FileStore

# The three seeded beta users (mirrors the migration's seed + web/src/
# identity.js's EMAIL_IDENTITY_MAP).
ANDREW_EMAIL = "andrewshaber@gmail.com"
RENEE_EMAIL = "kline.renee@gmail.com"
TIM_EMAIL = "curry.mtb@gmail.com"


@pytest.fixture
def store(app_env: Path) -> FileStore:
    """A FileStore over the SAME tmp athletes tree the app uses
    (settings.athletes_dir == app_env), so entries added here (allowed
    emails, sessions) are visible to the running app and vice versa."""
    return FileStore(base_dir=app_env)


@pytest.fixture
def allowlist(store: FileStore) -> FileStore:
    """Seed the three beta users into the allowlist, the way the migration
    seeds them in prod."""
    store.add_allowed_email("andrew", ANDREW_EMAIL)
    store.add_allowed_email("renee", RENEE_EMAIL)
    store.add_allowed_email("tim", TIM_EMAIL)
    return store


@pytest.fixture
def google(app):
    """Override the app's Google verifier with the offline fake."""
    from app.google_auth import get_google_verifier

    app.dependency_overrides[get_google_verifier] = lambda: fake_google_verify
    yield
    app.dependency_overrides.pop(get_google_verifier, None)


@pytest.fixture
def any_chat(app):
    """Override get_claude_chat so /api/chat never builds a real Anthropic
    client (no network in tests). A FRESH single-turn fake is returned per
    request, so any number of chat calls works."""
    from app.claude import ClaudeChat
    from app.routes.chat import get_claude_chat
    from fakes import FakeAnthropicClient

    def fresh() -> ClaudeChat:
        final = make_final_message([make_text_block("ok")], stop_reason="end_turn")
        return ClaudeChat(app.state.settings, client=FakeAnthropicClient([(["ok"], final)]))

    app.dependency_overrides[get_claude_chat] = fresh
    yield
    app.dependency_overrides.pop(get_claude_chat, None)


def _sign_in(client, email: str) -> dict:
    """POST /api/auth/google with a fake-verifiable token for `email`."""
    return client.post("/api/auth/google", json={"id_token": google_token_for(email)})


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --- POST /api/auth/google -------------------------------------------------


def test_google_sign_in_allowlisted_mints_session(client, allowlist, google):
    resp = _sign_in(client, TIM_EMAIL)
    assert resp.status_code == 200
    body = resp.json()
    assert body["athlete"] == "tim"
    assert body["name"] == "Tim"
    assert body["role"] == "athlete"
    assert "expires_at" in body
    token = body["token"]
    assert isinstance(token, str) and token
    # The minted token immediately resolves via /api/me.
    me = client.get("/api/me", headers=_bearer(token))
    assert me.status_code == 200
    assert me.json()["athlete"] == "tim"


def test_tampered_token_is_401(client, allowlist, google):
    # Not a `valid:` token -> fake verifier raises -> 401 (stands in for a
    # bad signature / wrong signing key).
    resp = client.post("/api/auth/google", json={"id_token": "tampered.jwt.value"})
    assert resp.status_code == 401
    assert "error" in resp.json()


def test_wrong_audience_or_expired_is_401(client, allowlist, google, app):
    # Simulate google-auth rejecting audience/expiry: the verifier raises
    # ValueError regardless of the specific reason -> the route maps every
    # verification failure to 401.
    from app.google_auth import get_google_verifier

    def always_reject(_raw: str) -> dict:
        raise ValueError("Token has wrong audience / Token expired")

    app.dependency_overrides[get_google_verifier] = lambda: always_reject
    resp = client.post("/api/auth/google", json={"id_token": "valid:" + RENEE_EMAIL})
    assert resp.status_code == 401


def test_non_allowlisted_email_is_403_and_creates_nothing(client, store, google):
    # store fixture seeds NO allowlist entries.
    before_sessions = store.get_session  # sanity: method exists
    assert before_sessions is not None

    resp = _sign_in(client, "stranger@example.com")
    assert resp.status_code == 403
    assert resp.json() == {"error": "request access"}

    # No session row and no athlete were created for the stranger.
    assert store.list_allowed_emails() == []
    # sessions.json must not have been created with any entry.
    sessions_file = store.base_dir / "sessions.json"
    if sessions_file.exists():
        import json

        assert json.loads(sessions_file.read_text()) == {}
    # The stranger's email did not become an athlete directory.
    assert not (store.base_dir / "stranger@example.com").exists()


# --- GET /api/me -----------------------------------------------------------


def test_me_with_service_token_is_403(client, allowlist):
    # A service credential (legacy shared API_TOKEN) has no single athlete
    # identity to report.
    resp = client.get("/api/me", headers=auth_headers())
    assert resp.status_code == 403


def test_me_without_auth_is_401(client):
    assert client.get("/api/me").status_code == 401


def test_revoked_session_is_401(client, allowlist, store, google):
    token = _sign_in(client, RENEE_EMAIL).json()["token"]
    assert client.get("/api/me", headers=_bearer(token)).status_code == 200

    # Revoke it directly in the store (mirrors an admin/CLI revoke).
    from app.auth import hash_token

    assert store.revoke_session(hash_token(token)) is True
    assert client.get("/api/me", headers=_bearer(token)).status_code == 401


def test_expired_session_is_401(client, allowlist, store, google):
    from datetime import datetime, timedelta, timezone

    from app.auth import hash_token

    token = _sign_in(client, RENEE_EMAIL).json()["token"]
    # Re-write the session with a past expiry (simulate the clock advancing
    # past session_ttl_days without waiting).
    import json

    sessions_file = store.base_dir / "sessions.json"
    data = json.loads(sessions_file.read_text())
    th = hash_token(token)
    data[th]["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    sessions_file.write_text(json.dumps(data))

    assert client.get("/api/me", headers=_bearer(token)).status_code == 401


def test_unknown_bearer_token_is_401(client, allowlist):
    assert client.get("/api/me", headers=_bearer("not-a-real-session-token")).status_code == 401


# --- cross-athlete denial (THE regression guarantee) -----------------------

# Every athlete-scoped route, expressed as a request that names ?athlete=renee
# (or, for chat, athlete=renee in the body). A tim session must get 403 on
# each; a service token must NOT get 403 on any.
def _scoped_requests(client, headers: dict, target: str = "renee"):
    """Yield (label, response) for each athlete-scoped route, asking for
    `target`'s data. Bodies are the minimal valid shape so the request
    reaches the handler's scoping check rather than 422-ing on body
    validation first."""
    dummy_file = {"file": ("swim.csv", b"not,a,real,file\n", "text/csv")}
    yield "GET /api/athlete", client.get(f"/api/athlete?athlete={target}", headers=headers)
    yield "PATCH /api/athlete", client.patch(
        f"/api/athlete?athlete={target}", json={}, headers=headers
    )
    yield "GET /api/workouts", client.get(f"/api/workouts?athlete={target}", headers=headers)
    yield "POST /api/workouts", client.post(
        f"/api/workouts?athlete={target}", json={}, headers=headers
    )
    yield "POST /api/workouts/sync", client.post(
        f"/api/workouts/sync?athlete={target}", headers=headers
    )
    yield "POST /api/workouts/ingest", client.post(
        f"/api/workouts/ingest?athlete={target}", files=dummy_file, headers=headers
    )
    yield "GET /api/wellness", client.get(f"/api/wellness?athlete={target}", headers=headers)
    yield "POST /api/wellness", client.post(
        f"/api/wellness?athlete={target}", json={}, headers=headers
    )
    yield "GET /api/plan", client.get(f"/api/plan?athlete={target}", headers=headers)
    yield "GET /api/feedback", client.get(f"/api/feedback?athlete={target}", headers=headers)
    yield "POST /api/feedback", client.post(
        f"/api/feedback?athlete={target}", json={}, headers=headers
    )
    yield "POST /api/chat", client.post(
        "/api/chat",
        json={"message": "hi", "history": [], "athlete": target, "expert_mode": False},
        headers=headers,
    )


def test_cross_athlete_denied_on_every_scoped_route(client, allowlist, google, any_chat):
    # any_chat ensures /api/chat doesn't build a real client even though
    # scoping must 403 before any streaming begins.
    token = _sign_in(client, TIM_EMAIL).json()["token"]
    headers = _bearer(token)

    failures = []
    for label, resp in _scoped_requests(client, headers, target="renee"):
        if resp.status_code != 403:
            failures.append(f"{label} -> {resp.status_code} (expected 403)")
    assert not failures, "cross-athlete access was NOT denied on:\n" + "\n".join(failures)


def test_own_athlete_allowed_for_session(client, allowlist, google):
    # The same session asking for its OWN athlete is never a scoping 403.
    token = _sign_in(client, TIM_EMAIL).json()["token"]
    headers = _bearer(token)
    resp = client.get("/api/workouts?athlete=tim", headers=headers)
    assert resp.status_code == 200
    # Omitting ?athlete= entirely resolves to the session's athlete (what the
    # future frontend relies on).
    resp2 = client.get("/api/workouts", headers=headers)
    assert resp2.status_code == 200


def test_service_token_reaches_any_athlete_on_every_route(client, allowlist, any_chat):
    # The "nothing breaks" guarantee: the legacy shared token is a SERVICE
    # principal and must never be scoped-denied, for ANY athlete.
    headers = auth_headers()
    # One target keeps chat calls within CHAT_RATE_PER_MIN (app_env sets 3);
    # the scoping logic is identical across athletes, so one is sufficient to
    # prove the service token is never scope-denied.
    for label, resp in _scoped_requests(client, headers, target="tim"):
        assert resp.status_code != 403, f"service token WRONGLY denied at {label}"
        assert resp.status_code != 401, f"service token WRONGLY rejected at {label}"


# --- daily chat cap --------------------------------------------------------


def test_daily_chat_cap_returns_429_for_athlete_session(
    allowlist, monkeypatch
):
    # Rebuild the app with a tiny daily cap and a generous per-minute limit so
    # the DAILY cap is what trips (not the per-minute limiter).
    monkeypatch.setenv("CHAT_DAILY_CAP_PER_ATHLETE", "2")
    monkeypatch.setenv("CHAT_RATE_PER_MIN", "100")
    from app.main import create_app

    capped_app = create_app()

    from app.google_auth import get_google_verifier

    capped_app.dependency_overrides[get_google_verifier] = lambda: fake_google_verify

    from app.claude import ClaudeChat
    from app.routes.chat import get_claude_chat
    from fakes import FakeAnthropicClient

    def fresh_chat():
        final = make_final_message([make_text_block("ok")], stop_reason="end_turn")
        return ClaudeChat(capped_app.state.settings, client=FakeAnthropicClient([(["ok"], final)]))

    capped_app.dependency_overrides[get_claude_chat] = fresh_chat

    from fastapi.testclient import TestClient

    with TestClient(capped_app) as capped_client:
        token = _sign_in(capped_client, TIM_EMAIL).json()["token"]
        headers = _bearer(token)

        def chat():
            return capped_client.post(
                "/api/chat",
                json={"message": "hi", "history": [], "athlete": "tim", "expert_mode": False},
                headers=headers,
            )

        statuses = [chat().status_code for _ in range(3)]

    assert statuses[:2] == [200, 200]
    assert statuses[2] == 429
