"""GET /api/library/cards, GET /api/library/files/{name}, POST
/api/library/reviews -- the Resources tab's research-library reviewer.

Exercises the real repo `library/` tree (read-only, via the shared
`library_dir` fixture) and a real `FileStore` (via `athletes_dir`/`client`),
same convention as test_feedback_route.py / test_grants_route.py.
"""

from __future__ import annotations

import pytest
from fakes import auth_headers, google_token_for

RENEE_EMAIL = "kline.renee@gmail.com"
ANDREW_EMAIL = "andrewshaber@gmail.com"

# A real, currently-pending (UNREVIEWED) section: 13-reds-energy-availability.md
# is still under a file-level marker, and this section carries EVIDENCE/ADAPTED
# tagged claims.
PENDING_FILE = "13-reds-energy-availability.md"
PENDING_SECTION = "swimming-is-not-osteogenic-the-highest-value-swim-specific-finding-here"

# A real, already-Human-reviewed section (no active marker) with no tagged
# claims of its own -- 07-strength-dryland.md's "Session duration" section.
REVIEWED_FILE = "07-strength-dryland.md"
REVIEWED_SECTION = "session-duration-45-minutes"

# A real bike-scoped file -- must never appear for a swim-only athlete.
BIKE_FILE = "23-cycling-training.md"


@pytest.fixture
def app_env(app_env, monkeypatch):
    """Overrides conftest.py's `app_env` to also configure `andrew` as a
    library admin -- every fixture/test that depends on `app_env` (`app`,
    `client`) picks this up automatically via pytest's fixture-override
    resolution."""
    monkeypatch.setenv("LIBRARY_ADMINS", "andrew")
    return app_env


@pytest.fixture
def allowlist(app_env):
    from swim_coach.store import FileStore

    store = FileStore(base_dir=app_env)
    store.add_allowed_email(RENEE_EMAIL, athlete="renee")
    store.add_allowed_email(ANDREW_EMAIL, athlete="andrew")
    return store


@pytest.fixture
def google(app):
    from app.google_auth import get_google_verifier
    from fakes import fake_google_verify

    app.dependency_overrides[get_google_verifier] = lambda: fake_google_verify
    yield
    app.dependency_overrides.pop(get_google_verifier, None)


def _sign_in(client, email: str) -> dict:
    return client.post("/api/auth/google", json={"id_token": google_token_for(email)}).json()


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _renee_headers(client, allowlist, google) -> dict:
    return _bearer(_sign_in(client, RENEE_EMAIL)["token"])


def _andrew_headers(client, allowlist, google) -> dict:
    return _bearer(_sign_in(client, ANDREW_EMAIL)["token"])


# --- GET /api/library/cards ---------------------------------------------------


def test_list_cards_requires_auth(client) -> None:
    response = client.get("/api/library/cards?athlete=renee")
    assert response.status_code == 401


# web/resources-hotfix fix 4: GET /api/library/cards is now admin-only (see
# require_library_admin), so every test below that only cares about card
# shape/content -- not about who may read them -- uses `athlete=andrew` (the
# configured admin, see this file's own `app_env` override) rather than
# `renee`. andrew's profile carries no `sports` override by default, same as
# renee's, so the sport-scope assertions (e.g. BIKE_FILE exclusion) still
# hold unchanged. The "who may read them" question itself is covered
# separately below (see "Admin-only access" section).


def test_list_cards_returns_every_in_scope_file(client, allowlist) -> None:
    response = client.get("/api/library/cards?athlete=andrew", headers=auth_headers())
    assert response.status_code == 200
    cards = response.json()
    assert len(cards) > 100  # 158 authored across 28 files
    files = {c["file"] for c in cards}
    assert REVIEWED_FILE in files
    assert PENDING_FILE in files


def test_list_cards_shape_and_derived_fields_for_a_pending_section(client, allowlist) -> None:
    response = client.get("/api/library/cards?athlete=andrew", headers=auth_headers())
    cards = {(c["file"], c["section"]): c for c in response.json()}
    card = cards[(PENDING_FILE, PENDING_SECTION)]

    assert card["heading"]
    assert card["summary"]
    assert card["recommendation"]
    assert card["reviewed"] is False  # still under 13's file-level UNREVIEWED marker
    assert card["stale"] is False  # freshly authored, hash matches
    assert card["confidence"] is not None
    assert card["source_count"] >= 1
    assert card["latest_review"] is None


def test_list_cards_reviewed_section_has_no_active_marker(client, allowlist) -> None:
    response = client.get("/api/library/cards?athlete=andrew", headers=auth_headers())
    cards = {(c["file"], c["section"]): c for c in response.json()}
    card = cards[(REVIEWED_FILE, REVIEWED_SECTION)]
    assert card["reviewed"] is True


def test_list_cards_excludes_bike_files_for_swim_only_athlete(client, allowlist) -> None:
    response = client.get("/api/library/cards?athlete=andrew", headers=auth_headers())
    files = {c["file"] for c in response.json()}
    assert BIKE_FILE not in files


def test_list_cards_includes_bike_files_for_an_athlete_with_bike_sport(
    client, allowlist, app_env
) -> None:
    import yaml

    profile_path = app_env / "andrew" / "profile.yaml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["sports"] = ["bike"]
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")

    response = client.get("/api/library/cards?athlete=andrew", headers=auth_headers())
    assert response.status_code == 200
    files = {c["file"] for c in response.json()}
    assert BIKE_FILE in files


def test_list_cards_non_admin_athlete_session_403s(client, allowlist, google) -> None:
    # web/resources-hotfix fix 4: renee is allowlisted but not configured as
    # a library admin (only 'andrew' is, per this file's app_env override),
    # so even a real signed-in athlete session reading their OWN implicit
    # scope (no ?athlete= override needed) is now refused -- the privacy
    # stopgap applies to every non-admin, not just cross-athlete access.
    headers = _renee_headers(client, allowlist, google)
    response = client.get("/api/library/cards", headers=headers)
    assert response.status_code == 403


def test_list_cards_admin_athlete_session_200s(client, allowlist, google) -> None:
    headers = _andrew_headers(client, allowlist, google)
    response = client.get("/api/library/cards", headers=headers)
    assert response.status_code == 200
    assert len(response.json()) > 100


def test_list_cards_athlete_session_cannot_read_another_athletes_cards(
    client, allowlist, google
) -> None:
    headers = _renee_headers(client, allowlist, google)
    response = client.get("/api/library/cards?athlete=andrew", headers=headers)
    assert response.status_code == 403


def test_latest_review_reflected_after_a_decision(client, allowlist, google) -> None:
    andrew_headers = _andrew_headers(client, allowlist, google)
    cards = client.get(
        "/api/library/cards?athlete=andrew", headers=andrew_headers
    ).json()
    card = next(c for c in cards if c["file"] == PENDING_FILE and c["section"] == PENDING_SECTION)

    review_response = client.post(
        "/api/library/reviews?athlete=andrew",
        json={
            "file": PENDING_FILE,
            "section": PENDING_SECTION,
            "content_hash": card["stale"] and "x" or "irrelevant-for-this-check",
            "decision": "accepted",
        },
        headers=andrew_headers,
    )
    # content_hash isn't validated against the real hash server-side (the
    # apply step does that) -- any non-empty string round-trips.
    assert review_response.status_code == 200

    cards_after = client.get("/api/library/cards?athlete=andrew", headers=andrew_headers).json()
    updated = next(
        c for c in cards_after if c["file"] == PENDING_FILE and c["section"] == PENDING_SECTION
    )
    assert updated["latest_review"]["decision"] == "accepted"


# --- GET /api/library/files/{name} --------------------------------------------


def test_get_library_file_requires_auth(client) -> None:
    response = client.get(f"/api/library/files/{REVIEWED_FILE}?athlete=renee")
    assert response.status_code == 401


# Same fix-4 admin-only gate as GET /api/library/cards above -- every test
# below that only cares about file-serving behavior (not "who may read
# it") uses `athlete=andrew` for the same reasons as that section's own
# comment.


def test_get_library_file_returns_markdown(client, allowlist) -> None:
    response = client.get(
        f"/api/library/files/{REVIEWED_FILE}?athlete=andrew", headers=auth_headers()
    )
    assert response.status_code == 200
    body = response.json()
    assert body["file"] == REVIEWED_FILE
    assert "Strength" in body["content"] or "strength" in body["content"]


def test_get_library_file_unknown_name_404s(client, allowlist) -> None:
    response = client.get(
        "/api/library/files/does-not-exist.md?athlete=andrew", headers=auth_headers()
    )
    assert response.status_code == 404


def test_get_library_file_rejects_path_traversal(client, allowlist) -> None:
    response = client.get(
        "/api/library/files/..%2F..%2Fpyproject.toml?athlete=andrew", headers=auth_headers()
    )
    assert response.status_code == 404


def test_get_library_file_sport_scoped_file_404s_for_swim_only_athlete(
    client, allowlist
) -> None:
    response = client.get(
        f"/api/library/files/{BIKE_FILE}?athlete=andrew", headers=auth_headers()
    )
    assert response.status_code == 404


def test_get_library_file_excludes_meta_files(client, allowlist) -> None:
    response = client.get(
        "/api/library/files/INDEX.md?athlete=andrew", headers=auth_headers()
    )
    assert response.status_code == 404


def test_get_library_file_non_admin_403s(client, allowlist) -> None:
    response = client.get(
        f"/api/library/files/{REVIEWED_FILE}?athlete=renee", headers=auth_headers()
    )
    assert response.status_code == 403


def test_get_library_file_admin_athlete_session_200s(client, allowlist, google) -> None:
    headers = _andrew_headers(client, allowlist, google)
    response = client.get(f"/api/library/files/{REVIEWED_FILE}", headers=headers)
    assert response.status_code == 200


# --- POST /api/library/reviews ------------------------------------------------


def _review_payload(**overrides) -> dict:
    payload = {
        "file": PENDING_FILE,
        "section": PENDING_SECTION,
        "content_hash": "a" * 64,
        "decision": "accepted",
    }
    payload.update(overrides)
    return payload


def test_create_review_requires_auth(client) -> None:
    response = client.post("/api/library/reviews?athlete=andrew", json=_review_payload())
    assert response.status_code == 401


def test_create_review_requires_athlete_query_for_service_token(client, allowlist) -> None:
    response = client.post(
        "/api/library/reviews", json=_review_payload(), headers=auth_headers()
    )
    assert response.status_code == 422


def test_create_review_service_token_with_admin_athlete_succeeds(client, allowlist) -> None:
    response = client.post(
        "/api/library/reviews?athlete=andrew", json=_review_payload(), headers=auth_headers()
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "accepted"
    assert body["file"] == PENDING_FILE
    assert body["section"] == PENDING_SECTION
    assert body["id"]
    assert body["created_at"]


def test_create_review_non_admin_athlete_session_403s(client, allowlist, google) -> None:
    headers = _renee_headers(client, allowlist, google)
    response = client.post(
        "/api/library/reviews?athlete=renee", json=_review_payload(), headers=headers
    )
    assert response.status_code == 403


def test_create_review_admin_athlete_session_succeeds(client, allowlist, google) -> None:
    headers = _andrew_headers(client, allowlist, google)
    response = client.post(
        "/api/library/reviews?athlete=andrew", json=_review_payload(), headers=headers
    )
    assert response.status_code == 200


def test_create_review_athlete_session_cannot_claim_another_athlete(
    client, allowlist, google
) -> None:
    headers = _renee_headers(client, allowlist, google)
    response = client.post(
        "/api/library/reviews?athlete=andrew", json=_review_payload(), headers=headers
    )
    assert response.status_code == 403


def test_create_review_onboarding_session_403s(client, allowlist, google) -> None:
    from swim_coach.store import FileStore

    # A pending (onboarding) allowlist entry -- no athlete slug yet.
    store = FileStore(base_dir=allowlist.base_dir)
    store.add_allowed_email("pending@example.com", athlete=None)
    token = _sign_in(client, "pending@example.com")["token"]
    response = client.post(
        "/api/library/reviews?athlete=andrew",
        json=_review_payload(),
        headers=_bearer(token),
    )
    assert response.status_code == 403


def test_create_review_flagged_requires_note(client, allowlist) -> None:
    response = client.post(
        "/api/library/reviews?athlete=andrew",
        json=_review_payload(decision="flagged"),
        headers=auth_headers(),
    )
    assert response.status_code == 422


def test_create_review_invalid_decision_422s(client, allowlist) -> None:
    response = client.post(
        "/api/library/reviews?athlete=andrew",
        json=_review_payload(decision="maybe"),
        headers=auth_headers(),
    )
    assert response.status_code == 422


def test_create_review_unknown_file_404s(client, allowlist) -> None:
    response = client.post(
        "/api/library/reviews?athlete=andrew",
        json=_review_payload(file="does-not-exist.md"),
        headers=auth_headers(),
    )
    assert response.status_code == 404


def test_create_review_unknown_section_404s(client, allowlist) -> None:
    response = client.post(
        "/api/library/reviews?athlete=andrew",
        json=_review_payload(section="not-a-real-section"),
        headers=auth_headers(),
    )
    assert response.status_code == 404


def test_create_review_flagged_also_creates_feedback(client, allowlist) -> None:
    from swim_coach.store import FileStore

    response = client.post(
        "/api/library/reviews?athlete=andrew",
        json=_review_payload(decision="flagged", note="the Manske citation looks off"),
        headers=auth_headers(),
    )
    assert response.status_code == 200

    # A library-review flag isn't tied to any one athlete's training data
    # (athlete_id=None), so it's read straight from the store rather than
    # through the ?athlete=-scoped /api/feedback route.
    store = FileStore(base_dir=allowlist.base_dir)
    matching = [f for f in store.list_feedback() if f.type == "research_question"]
    assert len(matching) == 1
    entry = matching[0]
    assert entry.athlete_id is None
    assert entry.source == "coach"
    assert entry.body == "the Manske citation looks off"
    assert entry.context["topic"] == "library-review"
    assert entry.context["file"] == PENDING_FILE
    assert entry.context["section"] == PENDING_SECTION


def test_create_review_accepted_does_not_create_feedback(client, allowlist) -> None:
    from swim_coach.store import FileStore

    response = client.post(
        "/api/library/reviews?athlete=andrew", json=_review_payload(), headers=auth_headers()
    )
    assert response.status_code == 200
    store = FileStore(base_dir=allowlist.base_dir)
    assert not [f for f in store.list_feedback() if f.type == "research_question"]


def test_create_review_is_append_only(client, allowlist) -> None:
    client.post(
        "/api/library/reviews?athlete=andrew",
        json=_review_payload(decision="flagged", note="first pass"),
        headers=auth_headers(),
    )
    client.post(
        "/api/library/reviews?athlete=andrew", json=_review_payload(), headers=auth_headers()
    )
    from swim_coach.store import FileStore

    store = FileStore(base_dir=allowlist.base_dir)
    reviews = store.list_library_reviews(file=PENDING_FILE, section=PENDING_SECTION)
    assert len(reviews) == 2
    assert reviews[0].decision == "accepted"  # most recent first
    assert reviews[1].decision == "flagged"


# --- GET /api/me / POST /api/auth/google carry is_library_admin --------------


def test_me_reports_is_library_admin_true_for_configured_admin(
    client, allowlist, google
) -> None:
    headers = _andrew_headers(client, allowlist, google)
    response = client.get("/api/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["is_library_admin"] is True


def test_me_reports_is_library_admin_false_for_non_admin(client, allowlist, google) -> None:
    headers = _renee_headers(client, allowlist, google)
    response = client.get("/api/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["is_library_admin"] is False


def test_google_sign_in_reports_is_library_admin(client, allowlist, google) -> None:
    body = _sign_in(client, ANDREW_EMAIL)
    assert body["is_library_admin"] is True
