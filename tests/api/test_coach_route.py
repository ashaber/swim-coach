"""GET /api/coach/athletes, GET .../workouts, GET .../feedback, PATCH
.../feedback/{id} -- coach-side view (coach-mode Phase 1), gated via
`resolve_coach_athlete` (backend/app/auth.py, merged on main) rather than
`resolve_athlete`.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from fakes import auth_headers, google_token_for, make_workout
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


def _tim_headers(client, allowlist, google) -> dict:
    token = _sign_in(client, TIM_EMAIL).json()["token"]
    return _bearer(token)


# --- GET /api/coach/athletes --------------------------------------------------


def test_list_coached_athletes_requires_auth(client) -> None:
    response = client.get("/api/coach/athletes")
    assert response.status_code == 401


def test_list_coached_athletes_reflects_coach_for(client, allowlist, store, google) -> None:
    store.create_coach_grant(coach_slug="tim", athlete_slug="renee")
    store.create_coach_grant(coach_slug="tim", athlete_slug="andrew")
    headers = _tim_headers(client, allowlist, google)

    response = client.get("/api/coach/athletes", headers=headers)
    assert response.status_code == 200
    body = response.json()
    slugs = {a["slug"] for a in body}
    assert slugs == {"andrew", "renee"}
    for entry in body:
        assert "name" in entry


def test_list_coached_athletes_empty_with_no_grants(client, allowlist, google) -> None:
    headers = _tim_headers(client, allowlist, google)
    response = client.get("/api/coach/athletes", headers=headers)
    assert response.status_code == 200
    assert response.json() == []


def test_list_coached_athletes_service_principal_gets_empty_list_not_error(
    client, allowlist
) -> None:
    response = client.get("/api/coach/athletes", headers=auth_headers())
    assert response.status_code == 200
    assert response.json() == []


# --- GET /api/coach/athletes/{slug}/workouts ----------------------------------


def _save_workout_for(store: FileStore, slug: str, **overrides) -> None:
    profile = store.load_athlete(slug)
    workout = make_workout(athlete_id=profile.id, **overrides)
    store.save_workout(slug, workout)


def test_coach_view_workouts_requires_auth(client) -> None:
    response = client.get("/api/coach/athletes/renee/workouts")
    assert response.status_code == 401


def test_coach_view_workouts_403_without_grant(client, allowlist, google) -> None:
    headers = _tim_headers(client, allowlist, google)
    response = client.get("/api/coach/athletes/renee/workouts", headers=headers)
    assert response.status_code == 403


def test_coach_view_workouts_includes_quality_per_item(
    client, allowlist, store, google
) -> None:
    # Relative to `date.today()`, not a hardcoded absolute date -- this test
    # must keep passing however far in the future it's actually run (see
    # test_load_route.py's `test_athlete_load_returns_ctl_atl_tsb_shape`
    # comment for the same reasoning), and now that this route has a
    # trailing-window default, an absolute date would eventually fall
    # outside it and start failing for reasons unrelated to the test.
    store.create_coach_grant(coach_slug="tim", athlete_slug="renee")
    _save_workout_for(store, "renee", date=date.today() - timedelta(days=1))
    _save_workout_for(store, "renee", date=date.today())

    headers = _tim_headers(client, allowlist, google)
    response = client.get("/api/coach/athletes/renee/workouts", headers=headers)
    assert response.status_code == 200
    body = response.json()
    # >= 2: the seeded renee fixture tree may already carry its own workouts
    # in addition to the two saved by this test.
    assert len(body) >= 2
    for entry in body:
        assert "quality" in entry
        assert "matched" in entry["quality"]
        assert "intensity_match" in entry["quality"]

    # most-recent-first
    dates = [entry["date"] for entry in body]
    assert dates == sorted(dates, reverse=True)


def test_coach_view_workouts_service_token_passes(client, allowlist, store) -> None:
    _save_workout_for(store, "renee", date=date.today())
    response = client.get("/api/coach/athletes/renee/workouts", headers=auth_headers())
    assert response.status_code == 200


# --- GET /api/coach/athletes/{slug}/workouts windowing (days param) ----------


def test_coach_view_workouts_excludes_workouts_older_than_default_window(
    client, allowlist, store, google
) -> None:
    from app.routes.coach import COACH_WORKOUTS_DEFAULT_DAYS

    store.create_coach_grant(coach_slug="tim", athlete_slug="renee")
    too_old = date.today() - timedelta(days=COACH_WORKOUTS_DEFAULT_DAYS + 1)
    recent = date.today()
    _save_workout_for(store, "renee", date=too_old, rpe=9)
    _save_workout_for(store, "renee", date=recent, rpe=3)

    headers = _tim_headers(client, allowlist, google)
    response = client.get("/api/coach/athletes/renee/workouts", headers=headers)
    assert response.status_code == 200
    dates = [entry["date"] for entry in response.json()]
    assert recent.isoformat() in dates
    assert too_old.isoformat() not in dates


def test_coach_view_workouts_boundary_day_is_included(
    client, allowlist, store, google
) -> None:
    """A workout logged exactly `days` ago is on the inclusive edge of the
    window (`since = today - timedelta(days=days)`, filtered with `>=`)."""
    store.create_coach_grant(coach_slug="tim", athlete_slug="renee")
    boundary = date.today() - timedelta(days=30)
    _save_workout_for(store, "renee", date=boundary, rpe=5)

    headers = _tim_headers(client, allowlist, google)
    response = client.get(
        "/api/coach/athletes/renee/workouts?days=30", headers=headers
    )
    assert response.status_code == 200
    dates = [entry["date"] for entry in response.json()]
    assert boundary.isoformat() in dates


def test_coach_view_workouts_respects_days_query_param(
    client, allowlist, store, google
) -> None:
    store.create_coach_grant(coach_slug="tim", athlete_slug="renee")
    outside_short_window = date.today() - timedelta(days=20)
    _save_workout_for(store, "renee", date=outside_short_window, rpe=5)

    headers = _tim_headers(client, allowlist, google)
    response = client.get(
        "/api/coach/athletes/renee/workouts?days=10", headers=headers
    )
    assert response.status_code == 200
    dates = [entry["date"] for entry in response.json()]
    assert outside_short_window.isoformat() not in dates


def test_coach_view_workouts_days_out_of_bounds_is_422(
    client, allowlist, google
) -> None:
    headers = _tim_headers(client, allowlist, google)
    too_small = client.get(
        "/api/coach/athletes/renee/workouts?days=0", headers=headers
    )
    too_large = client.get(
        "/api/coach/athletes/renee/workouts?days=10000", headers=headers
    )
    assert too_small.status_code == 422
    assert too_large.status_code == 422


# --- GET /api/coach/athletes/{slug}/feedback ----------------------------------


def test_coach_view_feedback_requires_auth(client) -> None:
    response = client.get("/api/coach/athletes/renee/feedback")
    assert response.status_code == 401


def test_coach_view_feedback_403_without_grant(client, allowlist, google) -> None:
    headers = _tim_headers(client, allowlist, google)
    response = client.get("/api/coach/athletes/renee/feedback", headers=headers)
    assert response.status_code == 403


def test_coach_view_feedback_returns_athletes_entries(client, allowlist, store, google) -> None:
    store.create_coach_grant(coach_slug="tim", athlete_slug="renee")
    client.post(
        "/api/feedback?athlete=renee",
        json={"type": "comment", "body": "shoulder feels off"},
        headers=auth_headers(),
    )

    headers = _tim_headers(client, allowlist, google)
    response = client.get("/api/coach/athletes/renee/feedback", headers=headers)
    assert response.status_code == 200
    bodies = [e["body"] for e in response.json()]
    assert "shoulder feels off" in bodies


# --- PATCH /api/coach/athletes/{slug}/feedback/{feedback_id} -----------------


def _create_feedback(client, slug: str, **overrides) -> dict:
    payload = {"type": "comment", "body": "how should I fuel a 4hr swim?"}
    payload.update(overrides)
    response = client.post(
        f"/api/feedback?athlete={slug}", json=payload, headers=auth_headers()
    )
    assert response.status_code == 200
    return response.json()


def test_coach_reply_requires_auth(client, allowlist) -> None:
    entry = _create_feedback(client, "renee")
    response = client.patch(
        f"/api/coach/athletes/renee/feedback/{entry['id']}", json={"coach_reply": "eat gels"}
    )
    assert response.status_code == 401


def test_coach_reply_403_without_grant(client, allowlist, google) -> None:
    entry = _create_feedback(client, "renee")
    headers = _tim_headers(client, allowlist, google)
    response = client.patch(
        f"/api/coach/athletes/renee/feedback/{entry['id']}",
        json={"coach_reply": "eat gels"},
        headers=headers,
    )
    assert response.status_code == 403


def test_coach_reply_missing_coach_reply_is_422(client, allowlist, store, google) -> None:
    store.create_coach_grant(coach_slug="tim", athlete_slug="renee")
    entry = _create_feedback(client, "renee")
    headers = _tim_headers(client, allowlist, google)
    response = client.patch(
        f"/api/coach/athletes/renee/feedback/{entry['id']}", json={}, headers=headers
    )
    assert response.status_code == 422


def test_coach_reply_wrong_type_coach_reply_is_422(client, allowlist, store, google) -> None:
    store.create_coach_grant(coach_slug="tim", athlete_slug="renee")
    entry = _create_feedback(client, "renee")
    headers = _tim_headers(client, allowlist, google)
    response = client.patch(
        f"/api/coach/athletes/renee/feedback/{entry['id']}",
        json={"coach_reply": 12345},
        headers=headers,
    )
    assert response.status_code == 422


def test_coach_reply_sets_fields(client, allowlist, store, google) -> None:
    store.create_coach_grant(coach_slug="tim", athlete_slug="renee")
    entry = _create_feedback(client, "renee")
    headers = _tim_headers(client, allowlist, google)

    response = client.patch(
        f"/api/coach/athletes/renee/feedback/{entry['id']}",
        json={"coach_reply": "60-90g carbs/hr, start early."},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["coach_reply"] == "60-90g carbs/hr, start early."
    assert body["coach_reply_at"]
    tim_id = store.load_athlete("tim").id
    assert body["coach_athlete_id"] == str(tim_id)


def test_coach_reply_404_on_feedback_belonging_to_different_athlete(
    client, allowlist, store, google
) -> None:
    store.create_coach_grant(coach_slug="tim", athlete_slug="renee")
    store.create_coach_grant(coach_slug="tim", athlete_slug="andrew")
    # entry actually belongs to andrew, not renee.
    entry = _create_feedback(client, "andrew")
    headers = _tim_headers(client, allowlist, google)

    response = client.patch(
        f"/api/coach/athletes/renee/feedback/{entry['id']}",
        json={"coach_reply": "wrong athlete"},
        headers=headers,
    )
    assert response.status_code == 404


def test_coach_reply_unknown_feedback_id_is_404(client, allowlist, store, google) -> None:
    store.create_coach_grant(coach_slug="tim", athlete_slug="renee")
    headers = _tim_headers(client, allowlist, google)
    response = client.patch(
        "/api/coach/athletes/renee/feedback/00000000-0000-0000-0000-000000000000",
        json={"coach_reply": "no such entry"},
        headers=headers,
    )
    assert response.status_code == 404


def test_coach_reply_service_principal_is_403(client, allowlist, store) -> None:
    entry = _create_feedback(client, "renee")
    response = client.patch(
        f"/api/coach/athletes/renee/feedback/{entry['id']}",
        json={"coach_reply": "no single coach identity"},
        headers=auth_headers(),
    )
    assert response.status_code == 403
