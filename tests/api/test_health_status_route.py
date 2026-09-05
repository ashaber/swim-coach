"""POST/GET /api/health-status -- the athlete's OWN self-service health
status logging (web/coach-health-nav-and-athlete-self-log).

Same shape/conventions as test_wellness_route.py -- see that file's module
docstring for why the real `FileStore` (not a fake) is exercised here.
Cross-athlete session-scoping denial is proven centrally by
test_auth_identity.py's `test_cross_athlete_denied_on_every_scoped_route`
(this route is registered in its `_scoped_requests` list); this file adds
the shape/validation/linked-Feedback assertions specific to this route,
plus a slug-isolation check mirroring test_workouts_route.py's
`test_patch_workout_wrong_athlete_id_is_404` pattern (a service token, two
real athlete slugs, proving one athlete's entries never leak into another's
list).
"""

from __future__ import annotations

from fakes import auth_headers
from swim_coach.store import FileStore


def _valid_payload(**overrides) -> dict:
    payload = {
        "description": "Sharp right shoulder pain on catch-up drills since Tuesday.",
        "restriction": "light_only",
        "source": "self_reported",
    }
    payload.update(overrides)
    return payload


def test_create_health_status_requires_auth(client) -> None:
    response = client.post("/api/health-status?athlete=renee", json=_valid_payload())
    assert response.status_code == 401


def test_list_health_status_requires_auth(client) -> None:
    response = client.get("/api/health-status?athlete=renee")
    assert response.status_code == 401


def test_create_health_status_persists_and_returns_created_object(client) -> None:
    response = client.post(
        "/api/health-status?athlete=renee", json=_valid_payload(), headers=auth_headers()
    )
    assert response.status_code == 200
    body = response.json()
    assert body["description"] == "Sharp right shoulder pain on catch-up drills since Tuesday."
    assert body["restriction"] == "light_only"
    assert body["source"] == "self_reported"
    # The athlete logged this about herself directly -- reported_by must be
    # "athlete", NEVER "coach" (this route has no coach-relaying concept at
    # all; every entry it creates is, by construction, the athlete's own).
    assert body["reported_by"] == "athlete"
    assert body["resolved"] is False
    assert body["id"]
    assert body["athlete_id"]
    assert body["schema_version"] == 1


def test_create_health_status_creates_linked_needs_human_review_feedback(
    client, athletes_dir
) -> None:
    response = client.post(
        "/api/health-status?athlete=renee", json=_valid_payload(), headers=auth_headers()
    )
    assert response.status_code == 200
    body = response.json()
    assert body["feedback_id"]
    assert "notify_error" not in body

    store = FileStore(base_dir=athletes_dir)
    feedback_entries = [
        f for f in store.list_feedback(athlete="renee") if str(f.id) == body["feedback_id"]
    ]
    assert len(feedback_entries) == 1
    feedback = feedback_entries[0]
    assert feedback.needs_human_review is True
    assert feedback.type == "coach_review"
    assert feedback.body == "Sharp right shoulder pain on catch-up drills since Tuesday."
    assert feedback.context["health_status_id"] == body["id"]

    # The linked Feedback row is independently discoverable via the
    # existing GET /api/feedback route too, not just the store directly.
    feedback_response = client.get("/api/feedback?athlete=renee", headers=auth_headers())
    assert feedback_response.status_code == 200
    assert any(f["id"] == body["feedback_id"] for f in feedback_response.json())


def test_create_health_status_rejects_missing_description(client) -> None:
    payload = _valid_payload()
    del payload["description"]
    response = client.post(
        "/api/health-status?athlete=renee", json=payload, headers=auth_headers()
    )
    assert response.status_code == 422
    assert "error" in response.json()


def test_create_health_status_rejects_invalid_restriction(client) -> None:
    response = client.post(
        "/api/health-status?athlete=renee",
        json=_valid_payload(restriction="not-a-real-value"),
        headers=auth_headers(),
    )
    assert response.status_code == 422
    assert "error" in response.json()


def test_create_health_status_rejects_invalid_source(client) -> None:
    response = client.post(
        "/api/health-status?athlete=renee",
        json=_valid_payload(source="not-a-real-value"),
        headers=auth_headers(),
    )
    assert response.status_code == 422
    assert "error" in response.json()


def test_create_health_status_rejects_invalid_body_region(client) -> None:
    response = client.post(
        "/api/health-status?athlete=renee",
        json=_valid_payload(body_region="not-a-real-region"),
        headers=auth_headers(),
    )
    assert response.status_code == 422
    assert "error" in response.json()


def test_create_health_status_rejects_invalid_onset(client) -> None:
    response = client.post(
        "/api/health-status?athlete=renee",
        json=_valid_payload(onset="not-a-real-onset"),
        headers=auth_headers(),
    )
    assert response.status_code == 422
    assert "error" in response.json()


def test_create_health_status_rejects_invalid_severity(client) -> None:
    response = client.post(
        "/api/health-status?athlete=renee",
        json=_valid_payload(severity="not-a-real-severity"),
        headers=auth_headers(),
    )
    assert response.status_code == 422
    assert "error" in response.json()


def test_create_health_status_rejects_invalid_expected_review_date(client) -> None:
    response = client.post(
        "/api/health-status?athlete=renee",
        json=_valid_payload(expected_review_date="not-a-date"),
        headers=auth_headers(),
    )
    assert response.status_code == 422
    assert "error" in response.json()


def test_create_health_status_rejects_invalid_related_status_id(client) -> None:
    response = client.post(
        "/api/health-status?athlete=renee",
        json=_valid_payload(related_status_id="not-a-uuid"),
        headers=auth_headers(),
    )
    assert response.status_code == 422
    assert "error" in response.json()


def test_create_health_status_unknown_athlete_is_404(client) -> None:
    response = client.post(
        "/api/health-status?athlete=nobody", json=_valid_payload(), headers=auth_headers()
    )
    assert response.status_code == 404
    assert "error" in response.json()


def test_create_health_status_accepts_optional_second_iteration_fields(client) -> None:
    response = client.post(
        "/api/health-status?athlete=renee",
        json=_valid_payload(
            body_region="shoulder", onset="acute", severity="mild",
            expected_review_date="2026-09-13",
        ),
        headers=auth_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["body_region"] == "shoulder"
    assert body["onset"] == "acute"
    assert body["severity"] == "mild"
    assert body["expected_review_date"] == "2026-09-13"


def test_list_health_status_returns_what_was_saved_most_recent_first(client) -> None:
    first = client.post(
        "/api/health-status?athlete=renee",
        json=_valid_payload(description="older entry"),
        headers=auth_headers(),
    ).json()
    second = client.post(
        "/api/health-status?athlete=renee",
        json=_valid_payload(description="newer entry"),
        headers=auth_headers(),
    ).json()

    response = client.get("/api/health-status?athlete=renee", headers=auth_headers())
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    ids = [e["id"] for e in body]
    assert first["id"] in ids
    assert second["id"] in ids
    # Most-recent-first: the second (newer) entry's index precedes the
    # first (older) entry's.
    assert ids.index(second["id"]) < ids.index(first["id"])


def test_list_health_status_unknown_athlete_is_404(client) -> None:
    response = client.get("/api/health-status?athlete=nobody", headers=auth_headers())
    assert response.status_code == 404
    assert "error" in response.json()


def test_health_status_entries_scoped_to_the_athlete_that_created_them(client) -> None:
    # Same shape as test_workouts_route.py's
    # test_patch_workout_wrong_athlete_id_is_404: a service token can name
    # any athlete via ?athlete=, so this proves store-level slug isolation
    # rather than session-based scoping (that guarantee lives centrally in
    # test_auth_identity.py's test_cross_athlete_denied_on_every_scoped_route).
    created = client.post(
        "/api/health-status?athlete=renee",
        json=_valid_payload(description="renee-only entry"),
        headers=auth_headers(),
    ).json()

    andrew_response = client.get("/api/health-status?athlete=andrew", headers=auth_headers())
    assert andrew_response.status_code == 200
    andrew_ids = [e["id"] for e in andrew_response.json()]
    assert created["id"] not in andrew_ids
