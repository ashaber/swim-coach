"""GET /api/sessions/{id}/garmin.fit -- downloading a session's structured
workout as a real Garmin .FIT file. Real request/response through the
FastAPI TestClient (no mocking of the route itself); the produced bytes are
round-tripped through `fitdecode` (a genuinely independent FIT-reading
library) to confirm they're real, well-formed FIT, not just "200 OK with
some bytes".
"""

from __future__ import annotations

import uuid

import fitdecode
from fakes import auth_headers
from swim_coach.models import WorkoutStep, WorkoutStructure, WorkoutTarget
from swim_coach.store import FileStore


def _add_structured_session(athletes_dir, iso_week: str = "2026-W28"):
    """Append a real session with `structured` populated to an existing
    real week on file, save it, and return (session_id, sport, date_iso)."""
    store = FileStore(base_dir=athletes_dir)
    week = store.load_week("renee", iso_week)
    athlete_id = store.load_athlete("renee").id

    from datetime import date

    from swim_coach.models import Session

    session = Session(
        id=uuid.uuid4(),
        athlete_id=athlete_id,
        date=date(2026, 7, 8),
        sport="swim_pool",
        source="ai_coach",
        duration_min=30.0,
        distance_m=1000,
        intensity={"anchor": "css_pace", "zone": "Z3"},
        purpose="garmin export route test",
        structure="Main set: 4x200 @ Z3",
        structured=WorkoutStructure(
            items=[
                WorkoutStep(
                    label="4x200 @ Z3",
                    role="interval",
                    duration_kind="distance_m",
                    duration_value=800,
                    target=WorkoutTarget(basis="absolute", low=90.0, high=95.0),
                    modality="swim",
                ),
            ]
        ),
        status="planned",
    )
    week.sessions.append(session)
    store.save_week("renee", week)
    return session


def test_garmin_fit_requires_auth(client, athletes_dir) -> None:
    session = _add_structured_session(athletes_dir)
    response = client.get(f"/api/sessions/{session.id}/garmin.fit?athlete=renee")
    assert response.status_code == 401


def test_garmin_fit_download_is_valid_fit_bytes(client, athletes_dir) -> None:
    session = _add_structured_session(athletes_dir)
    response = client.get(
        f"/api/sessions/{session.id}/garmin.fit?athlete=renee", headers=auth_headers()
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/vnd.ant.fit"
    assert "attachment" in response.headers["content-disposition"]
    assert ".fit" in response.headers["content-disposition"]

    body = response.content
    assert body[8:12] == b".FIT"

    # Genuinely independent round-trip: parses cleanly, has real content.
    step_count = 0
    with fitdecode.FitReader(body) as fit:
        for frame in fit:
            if frame.frame_type == fitdecode.FIT_FRAME_DATA and frame.name == "workout_step":
                step_count += 1
    assert step_count == 1


def test_garmin_fit_exposes_content_disposition_for_cross_origin_fetch(client, athletes_dir) -> None:
    """`Content-Disposition` isn't a CORS "simple response header" -- a
    cross-origin browser `fetch` can't read it via `response.headers.get()`
    unless the server explicitly lists it in `Access-Control-Expose-
    Headers` (see app/main.py's CORSMiddleware `expose_headers`). Found via
    real-browser verification: `TestClient`/`curl` both see the header fine
    regardless (neither enforces CORS), so this test sends a real `Origin`
    header (matching an allowed origin) to actually exercise the
    CORS-header-exposure path Starlette's CORSMiddleware only applies when
    an `Origin` header is present.
    """
    session = _add_structured_session(athletes_dir)
    response = client.get(
        f"/api/sessions/{session.id}/garmin.fit?athlete=renee",
        headers={**auth_headers(), "Origin": "http://localhost:5173"},
    )
    assert response.status_code == 200
    exposed = response.headers.get("access-control-expose-headers", "")
    assert "Content-Disposition" in exposed


def test_garmin_fit_unknown_session_is_404(client) -> None:
    response = client.get(
        f"/api/sessions/{uuid.uuid4()}/garmin.fit?athlete=renee", headers=auth_headers()
    )
    assert response.status_code == 404
    assert "error" in response.json()


def test_garmin_fit_session_without_structured_is_404(client, athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    week = store.load_week("renee", "2026-W28")
    # Every pre-existing real session in the fixture predates `structured`
    # (it's a newer, additive field) -- pick the first one, which has
    # structured=None.
    unstructured_session = week.sessions[0]
    assert unstructured_session.structured is None

    response = client.get(
        f"/api/sessions/{unstructured_session.id}/garmin.fit?athlete=renee", headers=auth_headers()
    )
    assert response.status_code == 404
    assert "error" in response.json()


def test_garmin_fit_unsupported_sport_is_422(client, athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    week = store.load_week("renee", "2026-W28")
    athlete_id = store.load_athlete("renee").id

    from datetime import date

    from swim_coach.models import Session

    session = Session(
        id=uuid.uuid4(),
        athlete_id=athlete_id,
        date=date(2026, 7, 9),
        sport="recovery",
        source="ai_coach",
        duration_min=20.0,
        distance_m=None,
        intensity={"anchor": "rpe"},
        purpose="unsupported sport export test",
        structured=WorkoutStructure(
            items=[
                WorkoutStep(label="easy recovery", role="steady", duration_kind="open", modality="swim"),
            ]
        ),
        status="planned",
    )
    week.sessions.append(session)
    store.save_week("renee", week)

    response = client.get(
        f"/api/sessions/{session.id}/garmin.fit?athlete=renee", headers=auth_headers()
    )
    assert response.status_code == 422
    assert "error" in response.json()
