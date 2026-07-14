"""POST/GET /api/feedback -- the durable feedback log (IDEA 005 generalized:
coach research questions plus athlete feature requests/comments/bugs).

Same conventions as test_workouts_route.py / test_wellness_route.py -- the
real FileStore (via the `client`/`athletes_dir` fixtures) is exercised here,
not a fake.
"""

from __future__ import annotations

from fakes import auth_headers


def _valid_payload(**overrides) -> dict:
    payload = {"type": "feature_request", "body": "Please add a pace calculator."}
    payload.update(overrides)
    return payload


def test_create_feedback_requires_auth(client) -> None:
    response = client.post("/api/feedback?athlete=renee", json=_valid_payload())
    assert response.status_code == 401


def test_list_feedback_requires_auth(client) -> None:
    response = client.get("/api/feedback?athlete=renee")
    assert response.status_code == 401


def test_create_feedback_persists_and_returns_created_object(client) -> None:
    response = client.post(
        "/api/feedback?athlete=renee", json=_valid_payload(), headers=auth_headers()
    )
    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "feature_request"
    assert body["source"] == "athlete"
    assert body["body"] == "Please add a pace calculator."
    assert body["status"] == "open"
    assert body["schema_version"] == 1
    assert body["id"]
    assert body["athlete_id"]
    assert body["created_at"]


def test_create_feedback_accepts_comment_and_bug(client) -> None:
    for feedback_type in ("comment", "bug"):
        response = client.post(
            "/api/feedback?athlete=renee",
            json=_valid_payload(type=feedback_type, body=f"a {feedback_type}"),
            headers=auth_headers(),
        )
        assert response.status_code == 200
        assert response.json()["type"] == feedback_type


def test_create_feedback_rejects_research_question(client) -> None:
    response = client.post(
        "/api/feedback?athlete=renee",
        json=_valid_payload(type="research_question", body="is taper research swim-specific?"),
        headers=auth_headers(),
    )
    assert response.status_code == 422
    assert "error" in response.json()


def test_create_feedback_rejects_missing_body(client) -> None:
    payload = _valid_payload()
    del payload["body"]
    response = client.post(
        "/api/feedback?athlete=renee", json=payload, headers=auth_headers()
    )
    assert response.status_code == 422
    assert "error" in response.json()


def test_create_feedback_rejects_invalid_type(client) -> None:
    response = client.post(
        "/api/feedback?athlete=renee",
        json=_valid_payload(type="not-a-real-type"),
        headers=auth_headers(),
    )
    assert response.status_code == 422
    assert "error" in response.json()


def test_create_feedback_unknown_athlete_is_404(client) -> None:
    response = client.post(
        "/api/feedback?athlete=nobody", json=_valid_payload(), headers=auth_headers()
    )
    assert response.status_code == 404
    assert "error" in response.json()


def test_create_feedback_ignores_client_supplied_server_fields(client) -> None:
    response = client.post(
        "/api/feedback?athlete=renee",
        json=_valid_payload(
            id="00000000-0000-0000-0000-000000000000",
            athlete_id="00000000-0000-0000-0000-000000000000",
            source="coach",
            status="resolved",
        ),
        headers=auth_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] != "00000000-0000-0000-0000-000000000000"
    assert body["athlete_id"] != "00000000-0000-0000-0000-000000000000"
    assert body["source"] == "athlete"
    assert body["status"] == "open"


def test_list_feedback_returns_what_was_saved_most_recent_first(client) -> None:
    created = []
    for body in ("first one", "second one"):
        response = client.post(
            "/api/feedback?athlete=renee",
            json=_valid_payload(body=body),
            headers=auth_headers(),
        )
        assert response.status_code == 200
        created.append(response.json())

    response = client.get("/api/feedback?athlete=renee", headers=auth_headers())
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    created_ids = {f["id"] for f in created}
    returned_ids = {f["id"] for f in body}
    assert created_ids.issubset(returned_ids)


def test_list_feedback_unknown_athlete_is_404(client) -> None:
    response = client.get("/api/feedback?athlete=nobody", headers=auth_headers())
    assert response.status_code == 404
    assert "error" in response.json()


def _create(client, **overrides) -> dict:
    response = client.post(
        "/api/feedback?athlete=renee",
        json=_valid_payload(**overrides),
        headers=auth_headers(),
    )
    assert response.status_code == 200
    return response.json()


def test_patch_feedback_requires_auth(client) -> None:
    created = _create(client)
    response = client.patch(f"/api/feedback/{created['id']}", json={"status": "resolved"})
    assert response.status_code == 401


def test_patch_feedback_updates_status(client) -> None:
    created = _create(client)
    response = client.patch(
        f"/api/feedback/{created['id']}",
        json={"status": "resolved"},
        headers=auth_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == created["id"]
    assert body["status"] == "resolved"


def test_patch_feedback_merges_context_without_clobbering(client) -> None:
    created = _create(
        client,
        type="comment",
        body="taper research question",
        context={"topic": "taper", "n": 1},
    )
    response = client.patch(
        f"/api/feedback/{created['id']}",
        json={"status": "resolved", "context": {"n": 2, "resolution": "see 03-periodization.md"}},
        headers=auth_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "resolved"
    assert body["context"] == {
        "topic": "taper",
        "n": 2,
        "resolution": "see 03-periodization.md",
    }


def test_patch_feedback_unknown_id_is_404(client) -> None:
    response = client.patch(
        "/api/feedback/00000000-0000-0000-0000-000000000000",
        json={"status": "resolved"},
        headers=auth_headers(),
    )
    assert response.status_code == 404
    assert "error" in response.json()


def test_patch_feedback_invalid_status_type_is_422(client) -> None:
    created = _create(client)
    response = client.patch(
        f"/api/feedback/{created['id']}",
        json={"status": 12345},
        headers=auth_headers(),
    )
    assert response.status_code == 422
    assert "error" in response.json()


def test_patch_feedback_does_not_disturb_other_entries(client) -> None:
    keep = _create(client, body="leave me alone")
    target = _create(client, body="patch me")
    response = client.patch(
        f"/api/feedback/{target['id']}",
        json={"status": "resolved"},
        headers=auth_headers(),
    )
    assert response.status_code == 200

    listing = client.get("/api/feedback?athlete=renee", headers=auth_headers())
    by_id = {f["id"]: f for f in listing.json()}
    assert by_id[keep["id"]]["status"] == "open"
    assert by_id[target["id"]]["status"] == "resolved"
