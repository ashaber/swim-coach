"""POST/GET /api/workouts -- logging and listing completed workouts.

Exercises the real `FileStore` (via the `client` fixture's isolated
`ATHLETES_DIR` tmp copy of `athletes/renee`) rather than a fake, so these
tests also prove the `make_store` seam end-to-end: a logged workout is
immediately visible to a subsequent GET, exactly like it would be against
`DbStore` in production.
"""

from __future__ import annotations

from fakes import auth_headers


def _valid_payload(**overrides) -> dict:
    payload = {
        "date": "2026-07-07",
        "sport": "swim_pool",
        "distance_m": 3000,
        "duration_min": 60,
        "rpe": 6,
        "notes": "felt smooth",
    }
    payload.update(overrides)
    return payload


def test_create_workout_requires_auth(client) -> None:
    response = client.post("/api/workouts?athlete=renee", json=_valid_payload())
    assert response.status_code == 401


def test_list_workouts_requires_auth(client) -> None:
    response = client.get("/api/workouts?athlete=renee")
    assert response.status_code == 401


def test_create_workout_persists_and_returns_created_object(client) -> None:
    response = client.post(
        "/api/workouts?athlete=renee", json=_valid_payload(), headers=auth_headers()
    )
    assert response.status_code == 200
    body = response.json()
    assert body["date"] == "2026-07-07"
    assert body["sport"] == "swim_pool"
    assert body["distance_m"] == 3000
    assert body["duration_min"] == 60
    assert body["rpe"] == 6
    assert body["notes"] == "felt smooth"
    assert body["source"] == "manual"
    assert body["schema_version"] == 1
    # Server-assigned fields.
    assert body["id"]
    assert body["athlete_id"]


def test_create_workout_rejects_invalid_input(client) -> None:
    response = client.post(
        "/api/workouts?athlete=renee",
        json=_valid_payload(sport="not_a_real_sport"),
        headers=auth_headers(),
    )
    assert response.status_code == 422
    assert "error" in response.json()


def test_create_workout_rejects_missing_required_field(client) -> None:
    payload = _valid_payload()
    del payload["distance_m"]
    response = client.post(
        "/api/workouts?athlete=renee", json=payload, headers=auth_headers()
    )
    assert response.status_code == 422
    assert "error" in response.json()


def test_create_workout_unknown_athlete_is_404(client) -> None:
    response = client.post(
        "/api/workouts?athlete=nobody", json=_valid_payload(), headers=auth_headers()
    )
    assert response.status_code == 404
    assert "error" in response.json()


def test_list_workouts_returns_what_was_saved(client) -> None:
    created = []
    for distance in (2000, 4000):
        response = client.post(
            "/api/workouts?athlete=renee",
            json=_valid_payload(distance_m=distance),
            headers=auth_headers(),
        )
        assert response.status_code == 200
        created.append(response.json())

    response = client.get("/api/workouts?athlete=renee", headers=auth_headers())
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    created_ids = {w["id"] for w in created}
    returned_ids = {w["id"] for w in body}
    assert created_ids.issubset(returned_ids)


def test_list_workouts_unknown_athlete_is_404(client) -> None:
    response = client.get("/api/workouts?athlete=nobody", headers=auth_headers())
    assert response.status_code == 404
    assert "error" in response.json()


# --- client-settable `source` (Phase 3: the confirm step of the two-step
# .fit/.tcx/.csv upload -- see routes/workouts.py's ingest_workout -- saves
# through this same endpoint with the draft's real source, not a fabricated
# "manual") -----------------------------------------------------------------


def test_create_workout_accepts_fit_source(client) -> None:
    response = client.post(
        "/api/workouts?athlete=renee",
        json=_valid_payload(source="fit"),
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert response.json()["source"] == "fit"


def test_create_workout_accepts_tcx_and_csv_source(client) -> None:
    for source in ("tcx", "csv"):
        response = client.post(
            "/api/workouts?athlete=renee",
            json=_valid_payload(source=source),
            headers=auth_headers(),
        )
        assert response.status_code == 200
        assert response.json()["source"] == source


def test_create_workout_rejects_coach_text_source(client) -> None:
    # coach_text is still CLI/skill-only (see engine/swim_coach/cli.py's
    # `_cmd_ingest`) -- a client of this JSON endpoint can't claim it, even
    # though Workout.source's Literal type would otherwise accept it.
    response = client.post(
        "/api/workouts?athlete=renee",
        json=_valid_payload(source="coach_text"),
        headers=auth_headers(),
    )
    assert response.status_code == 422
    assert "error" in response.json()


def test_create_workout_rejects_bogus_source(client) -> None:
    response = client.post(
        "/api/workouts?athlete=renee",
        json=_valid_payload(source="not_a_real_source"),
        headers=auth_headers(),
    )
    assert response.status_code == 422
    assert "error" in response.json()


# --- PATCH /api/workouts/{workout_id} (A5: correcting rpe/notes after the fact) -----


def _create(client, **overrides) -> dict:
    response = client.post(
        "/api/workouts?athlete=renee", json=_valid_payload(**overrides), headers=auth_headers()
    )
    assert response.status_code == 200
    return response.json()


def test_patch_workout_requires_auth(client) -> None:
    created = _create(client)
    response = client.patch(
        f"/api/workouts/{created['id']}?athlete=renee", json={"rpe": 9}
    )
    assert response.status_code == 401


def test_patch_workout_updates_rpe(client) -> None:
    created = _create(client, rpe=6)
    response = client.patch(
        f"/api/workouts/{created['id']}?athlete=renee",
        json={"rpe": 9},
        headers=auth_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["rpe"] == 9
    assert body["id"] == created["id"]

    # persisted -- a subsequent GET reflects the correction
    listed = client.get("/api/workouts?athlete=renee", headers=auth_headers()).json()
    matching = [w for w in listed if w["id"] == created["id"]]
    assert len(matching) == 1
    assert matching[0]["rpe"] == 9


def test_patch_workout_updates_notes(client) -> None:
    created = _create(client, notes="original")
    response = client.patch(
        f"/api/workouts/{created['id']}?athlete=renee",
        json={"notes": "corrected after the fact"},
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert response.json()["notes"] == "corrected after the fact"


def test_patch_workout_leaves_untouched_fields_alone(client) -> None:
    created = _create(client, distance_m=3000, duration_min=60, rpe=6, notes="felt smooth")
    response = client.patch(
        f"/api/workouts/{created['id']}?athlete=renee",
        json={"rpe": 8},
        headers=auth_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["rpe"] == 8
    assert body["distance_m"] == 3000
    assert body["duration_min"] == 60
    assert body["notes"] == "felt smooth"
    assert body["sport"] == created["sport"]
    assert body["date"] == created["date"]


def test_patch_workout_ignores_disallowed_fields_silently(client) -> None:
    created = _create(client, distance_m=3000)
    response = client.patch(
        f"/api/workouts/{created['id']}?athlete=renee",
        json={"rpe": 7, "distance_m": 99999, "sport": "cross_train"},
        headers=auth_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["rpe"] == 7
    # distance_m/sport are not in the {"rpe", "notes"} allowlist -- silently
    # ignored, not a 422 or an error.
    assert body["distance_m"] == 3000
    assert body["sport"] == created["sport"]


def test_patch_workout_rejects_rpe_out_of_range(client) -> None:
    created = _create(client)
    response = client.patch(
        f"/api/workouts/{created['id']}?athlete=renee",
        json={"rpe": 11},
        headers=auth_headers(),
    )
    assert response.status_code == 422
    assert "error" in response.json()


def test_patch_workout_accepts_rpe_zero(client) -> None:
    created = _create(client)
    response = client.patch(
        f"/api/workouts/{created['id']}?athlete=renee",
        json={"rpe": 0},
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert response.json()["rpe"] == 0


def test_patch_workout_unknown_id_is_404(client) -> None:
    response = client.patch(
        "/api/workouts/00000000-0000-0000-0000-000000000000?athlete=renee",
        json={"rpe": 5},
        headers=auth_headers(),
    )
    assert response.status_code == 404
    assert "error" in response.json()


def test_patch_workout_unknown_athlete_is_404(client) -> None:
    created = _create(client)
    response = client.patch(
        f"/api/workouts/{created['id']}?athlete=nobody",
        json={"rpe": 5},
        headers=auth_headers(),
    )
    assert response.status_code == 404
    assert "error" in response.json()


def test_patch_workout_wrong_athlete_id_is_404(client) -> None:
    # renee's workout id, patched against a real but different athlete
    # (andrew) -- must never resolve, matching get_workout's slug+id
    # scoping contract.
    created = _create(client)
    response = client.patch(
        f"/api/workouts/{created['id']}?athlete=andrew",
        json={"rpe": 5},
        headers=auth_headers(),
    )
    assert response.status_code == 404
    assert "error" in response.json()
