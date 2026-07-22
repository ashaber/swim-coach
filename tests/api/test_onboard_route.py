"""POST /api/onboard -- Slice 2 of self-service in-app onboarding.

Lets an ONBOARDING session (Slice 1: a live session for an allowlisted email
with no athlete yet, see test_auth_identity.py) provision its own athlete and
upgrade to an athlete-bound session in one call. Reuses
`swim_coach.provision.provision_athlete` -- these tests assert the HTTP-layer
behavior (auth gating, body validation, the session upgrade + old-token
revocation, the pending-row completion), not the engine math provision_athlete
itself already covers in tests/unit/test_provision.py.

Mirrors test_auth_identity.py's fixtures (`store`, `google`, `_sign_in`,
`_bearer`, a pending-invite helper) so the onboarding-session lifecycle stays
consistent across both test modules.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from fakes import auth_headers, fake_google_verify, google_token_for
from swim_coach.store import FileStore

ONBOARDING_EMAIL = "future.athlete@example.com"
# Far enough out that scaffold_macro always has enough runway regardless of
# which day the suite runs on (mirrors tests/unit/test_provision.py's own
# margin).
EVENT_DATE = (date.today() + timedelta(weeks=30)).isoformat()


@pytest.fixture
def store(app_env: Path) -> FileStore:
    return FileStore(base_dir=app_env)


@pytest.fixture
def google(app):
    from app.google_auth import get_google_verifier

    app.dependency_overrides[get_google_verifier] = lambda: fake_google_verify
    yield
    app.dependency_overrides.pop(get_google_verifier, None)


@pytest.fixture
def pending_invite(store: FileStore) -> FileStore:
    """Seed a PENDING (email-only, no athlete) allowlist entry -- the state
    `cli invite <email>` (no --athlete) creates."""
    store.add_allowed_email(ONBOARDING_EMAIL, note="self-service beta")
    return store


@pytest.fixture
def allowlist(store: FileStore) -> FileStore:
    """Seed the seeded 'renee' athlete's allowlist entry, for the
    athlete-bound-session-rejected and slug-collision tests (mirrors
    test_auth_identity.py's own `allowlist` fixture, just for one athlete --
    the 'renee' athlete tree already exists in athletes/, see conftest's
    athletes_dir fixture)."""
    store.add_allowed_email("kline.renee@gmail.com", athlete="renee")
    return store


def _sign_in(client, email: str) -> dict:
    return client.post("/api/auth/google", json={"id_token": google_token_for(email)})


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _onboarding_token(client, pending_invite, google) -> str:
    return _sign_in(client, ONBOARDING_EMAIL).json()["token"]


def _valid_body(**overrides) -> dict:
    body = {
        "name": "New Athlete",
        "css_pace_s_per_100m": 95.0,
        "sex": "female",
        "height_cm": 165.0,
        "weight_kg": 60.0,
        "dob": "1990-01-01",
        "pool_schedule": ["tue", "thu", "fri"],
        "events": [
            {
                "name": "Catalina Channel",
                "event_date": EVENT_DATE,
                "distance_m": 20000,
                "priority": "A",
            }
        ],
        "current_volume_m": 6000,
        "peak_volume_m": 15000,
    }
    body.update(overrides)
    return body


# --- happy path --------------------------------------------------------------


def test_onboard_happy_path_provisions_and_upgrades_session(client, pending_invite, google):
    old_token = _onboarding_token(client, pending_invite, google)

    resp = client.post(
        "/api/onboard", json=_valid_body(), headers=_bearer(old_token)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == "athlete"
    assert body["name"] == "New Athlete"
    assert "expires_at" in body
    new_slug = body["athlete"]
    assert isinstance(new_slug, str) and new_slug
    new_token = body["token"]
    assert isinstance(new_token, str) and new_token
    assert new_token != old_token

    # The athlete now exists, fully provisioned.
    store = pending_invite
    saved = store.load_athlete(new_slug)
    assert saved.name == "New Athlete"
    assert saved.zones is not None
    saved_events = store.load_events(new_slug)
    assert len(saved_events) == 1
    assert store.load_macro(new_slug) is not None

    # The pending allowed_emails row now has athlete_id set -- NOT a
    # duplicate row -- and its original note (set by whoever invited this
    # email) survives the upsert.
    assert len(store.list_allowed_emails()) == 1
    entry = store.get_allowed_email(ONBOARDING_EMAIL)
    assert entry is not None
    assert entry.athlete_slug == new_slug
    assert entry.note == "self-service beta"

    # The new token reaches its OWN athlete...
    own = client.get(f"/api/workouts?athlete={new_slug}", headers=_bearer(new_token))
    assert own.status_code == 200
    # ...and still 403s another athlete.
    cross = client.get("/api/workouts?athlete=renee", headers=_bearer(new_token))
    assert cross.status_code == 403

    # The OLD onboarding token is now revoked.
    old_check = client.get("/api/me", headers=_bearer(old_token))
    assert old_check.status_code == 401

    # GET /api/me on the new token reports the athlete, not onboarding.
    me = client.get("/api/me", headers=_bearer(new_token))
    assert me.status_code == 200
    me_body = me.json()
    assert me_body["athlete"] == new_slug
    assert "onboarding" not in me_body or me_body.get("onboarding") is not True


def test_onboard_css_from_test_times(client, pending_invite, google):
    token = _onboarding_token(client, pending_invite, google)
    body = _valid_body()
    del body["css_pace_s_per_100m"]
    body["test_400"] = "6:40"
    body["test_200"] = "3:00"

    resp = client.post("/api/onboard", json=body, headers=_bearer(token))
    assert resp.status_code == 200
    slug = resp.json()["athlete"]
    saved = pending_invite.load_athlete(slug)
    # CSS = (400s - 200s) / 2 = (400 - 180) / 2 = 110
    assert saved.css_pace_s_per_100m == 110.0


def test_onboard_without_events_still_provisions_bare_athlete(client, pending_invite, google):
    token = _onboarding_token(client, pending_invite, google)
    body = _valid_body()
    del body["events"]
    del body["current_volume_m"]
    del body["peak_volume_m"]

    resp = client.post("/api/onboard", json=body, headers=_bearer(token))
    assert resp.status_code == 200
    slug = resp.json()["athlete"]
    assert pending_invite.load_athlete(slug) is not None
    assert pending_invite.load_macro(slug) is None


# --- auth rejections -----------------------------------------------------


def test_onboard_requires_auth(client):
    resp = client.post("/api/onboard", json=_valid_body())
    assert resp.status_code == 401


def test_onboard_rejects_service_token(client, allowlist):
    resp = client.post("/api/onboard", json=_valid_body(), headers=auth_headers())
    assert resp.status_code == 403


def test_onboard_rejects_athlete_bound_session(client, allowlist, google):
    token = _sign_in(client, "kline.renee@gmail.com").json()["token"]
    resp = client.post("/api/onboard", json=_valid_body(), headers=_bearer(token))
    assert resp.status_code == 403


# --- body validation -------------------------------------------------------


def test_onboard_malformed_body_missing_name_is_422(client, pending_invite, google):
    token = _onboarding_token(client, pending_invite, google)
    body = _valid_body()
    del body["name"]
    resp = client.post("/api/onboard", json=body, headers=_bearer(token))
    assert resp.status_code == 422


def test_onboard_missing_css_and_test_times_is_422(client, pending_invite, google):
    token = _onboarding_token(client, pending_invite, google)
    body = _valid_body()
    del body["css_pace_s_per_100m"]
    resp = client.post("/api/onboard", json=body, headers=_bearer(token))
    assert resp.status_code == 422


def test_onboard_multiple_events_without_target_is_422(client, pending_invite, google):
    token = _onboarding_token(client, pending_invite, google)
    body = _valid_body()
    body["events"] = [
        {
            "name": "Catalina Channel",
            "event_date": EVENT_DATE,
            "distance_m": 20000,
            "priority": "A",
        },
        {
            "name": "English Channel",
            "event_date": EVENT_DATE,
            "distance_m": 34000,
            "priority": "A",
        },
    ]
    resp = client.post("/api/onboard", json=body, headers=_bearer(token))
    assert resp.status_code == 422


def test_onboard_multiple_events_with_target_event_resolves(client, pending_invite, google):
    token = _onboarding_token(client, pending_invite, google)
    body = _valid_body()
    body["events"] = [
        {
            "name": "Catalina Channel",
            "event_date": EVENT_DATE,
            "distance_m": 20000,
            "priority": "A",
        },
        {
            "name": "English Channel",
            "event_date": EVENT_DATE,
            "distance_m": 34000,
            "priority": "B",
        },
    ]
    body["target_event"] = "English Channel"
    resp = client.post("/api/onboard", json=body, headers=_bearer(token))
    assert resp.status_code == 200
    slug = resp.json()["athlete"]
    macro = pending_invite.load_macro(slug)
    assert macro is not None
    assert macro.event_id == [
        e for e in pending_invite.load_events(slug) if e.name == "English Channel"
    ][0].id


# --- slug collision ----------------------------------------------------------


def test_onboard_slug_collision_is_409(client, allowlist, pending_invite, google):
    token = _onboarding_token(client, pending_invite, google)
    body = _valid_body(slug="renee")  # "renee" already exists in athletes/
    resp = client.post("/api/onboard", json=body, headers=_bearer(token))
    assert resp.status_code == 409


# --- pending-row / stale-session edge cases ---------------------------------


def test_onboard_revoked_invite_is_403(client, pending_invite, google):
    token = _onboarding_token(client, pending_invite, google)
    assert pending_invite.remove_allowed_email(ONBOARDING_EMAIL) is True
    resp = client.post("/api/onboard", json=_valid_body(), headers=_bearer(token))
    assert resp.status_code == 403


def test_onboard_with_already_claimed_invite_is_409(client, pending_invite, google):
    # Two separate onboarding sessions for the SAME pending email (e.g. two
    # browser tabs). The first completes onboarding (claims the pending
    # row); the second token is still live (not revoked) but its underlying
    # invite is no longer pending -- must not silently re-provision or
    # clobber the first athlete.
    token_a = _sign_in(client, ONBOARDING_EMAIL).json()["token"]
    token_b = _sign_in(client, ONBOARDING_EMAIL).json()["token"]
    assert token_a != token_b

    first = client.post("/api/onboard", json=_valid_body(), headers=_bearer(token_a))
    assert first.status_code == 200

    second = client.post(
        "/api/onboard", json=_valid_body(name="Second Attempt"), headers=_bearer(token_b)
    )
    assert second.status_code == 409
