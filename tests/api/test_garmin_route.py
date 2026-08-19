"""GET /api/sessions/{id}/garmin.fit -- downloading a session's structured
workout as a real Garmin .FIT file. Real request/response through the
FastAPI TestClient (no mocking of the route itself); the produced bytes are
round-tripped through `fitdecode` (a genuinely independent FIT-reading
library) to confirm they're real, well-formed FIT, not just "200 OK with
some bytes".

Also covers POST /api/sessions/{id}/push-intervals -- the Garmin-push
feature's route, same router (see that route's own docstring / app/
garmin_push.py). No real HTTP to intervals.icu: every `IntervalsClient` the
route builds is forced onto an `httpx.MockTransport`, same
`_force_mock_transport` convention as tests/api/test_workouts_sync_route.py
(the route -- like `app.sync.sync_on_demand` -- builds its own client with
no injected transport).
"""

from __future__ import annotations

import base64
import json
import uuid

import fitdecode
import httpx
import pytest
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


# --- POST /api/sessions/{id}/push-intervals ---------------------------------


def _force_mock_transport(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    """See test_workouts_sync_route.py's identically-named helper -- the
    route builds its own `IntervalsClient` with no injected transport, so
    every `httpx.Client` app.sync constructs must be forced onto an
    `httpx.MockTransport`."""
    real_client_cls = httpx.Client

    def fake_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client_cls(*args, **kwargs)

    monkeypatch.setattr("app.sync.httpx.Client", fake_client)


def _bulk_ok_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/events/bulk"):
        body = json.loads(request.content)
        return httpx.Response(200, json=[{"id": i} for i in range(len(body))])
    return httpx.Response(404, json={"error": "not found"})


def test_push_intervals_requires_auth(client, athletes_dir) -> None:
    session = _add_structured_session(athletes_dir)
    response = client.post(f"/api/sessions/{session.id}/push-intervals?athlete=renee")
    assert response.status_code == 401


def test_push_intervals_unknown_session_is_404(client) -> None:
    response = client.post(
        f"/api/sessions/{uuid.uuid4()}/push-intervals?athlete=renee", headers=auth_headers()
    )
    assert response.status_code == 404
    assert "error" in response.json()


def test_push_intervals_session_without_structured_is_404(client, athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    week = store.load_week("renee", "2026-W28")
    unstructured_session = week.sessions[0]
    assert unstructured_session.structured is None

    response = client.post(
        f"/api/sessions/{unstructured_session.id}/push-intervals?athlete=renee", headers=auth_headers()
    )
    assert response.status_code == 404
    assert "error" in response.json()


def test_push_intervals_unsupported_sport_is_422(client, athletes_dir) -> None:
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
        purpose="unsupported sport push test",
        structured=WorkoutStructure(
            items=[
                WorkoutStep(label="easy recovery", role="steady", duration_kind="open", modality="swim"),
            ]
        ),
        status="planned",
    )
    week.sessions.append(session)
    store.save_week("renee", week)

    response = client.post(
        f"/api/sessions/{session.id}/push-intervals?athlete=renee", headers=auth_headers()
    )
    assert response.status_code == 422
    assert "error" in response.json()


def test_push_intervals_not_configured_is_a_clean_error(
    client, athletes_dir, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("INTERVALS_SYNC_CONFIG", raising=False)
    session = _add_structured_session(athletes_dir)

    response = client.post(
        f"/api/sessions/{session.id}/push-intervals?athlete=renee", headers=auth_headers()
    )
    from app.sync import SYNC_NOT_CONFIGURED_ERROR

    assert response.status_code == 409
    assert response.json() == {"error": SYNC_NOT_CONFIGURED_ERROR}


def test_push_intervals_success_returns_summary(
    client, athletes_dir, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "INTERVALS_SYNC_CONFIG",
        json.dumps([{"slug": "renee", "intervals_athlete_id": "i-renee", "api_key": "renee-key"}]),
    )
    _force_mock_transport(monkeypatch, _bulk_ok_handler)
    session = _add_structured_session(athletes_dir)

    response = client.post(
        f"/api/sessions/{session.id}/push-intervals?athlete=renee", headers=auth_headers()
    )

    assert response.status_code == 200
    assert response.json() == {
        "pushed": True,
        "session_id": str(session.id),
        "date": session.date.isoformat(),
        "type": "Swim",
    }


# Local, scoped-to-this-file session-token machinery for the cross-athlete
# 403 test below -- mirrors test_auth_identity.py's own `store`/`allowlist`/
# `google`/`_sign_in`/`_bearer` fixtures exactly (that file's own
# `_scoped_requests` helper only covers athlete-level routes with no
# path-embedded session id, so it doesn't already exercise this one -- see
# this task's final report for that correction).

RENEE_EMAIL = "kline.renee@gmail.com"
TIM_EMAIL = "curry.mtb@gmail.com"


@pytest.fixture
def _session_store(app_env) -> FileStore:
    return FileStore(base_dir=app_env)


@pytest.fixture
def _allowlist(_session_store: FileStore) -> FileStore:
    _session_store.add_allowed_email(RENEE_EMAIL, athlete="renee")
    _session_store.add_allowed_email(TIM_EMAIL, athlete="tim")
    return _session_store


@pytest.fixture
def _google(app):
    from app.google_auth import get_google_verifier
    from fakes import fake_google_verify

    app.dependency_overrides[get_google_verifier] = lambda: fake_google_verify
    yield
    app.dependency_overrides.pop(get_google_verifier, None)


def _sign_in(client, email: str) -> dict:
    from fakes import google_token_for

    return client.post("/api/auth/google", json={"id_token": google_token_for(email)})


def test_push_intervals_cross_athlete_session_is_403(
    client, athletes_dir, _allowlist, _google
) -> None:
    session = _add_structured_session(athletes_dir)
    tim_token = _sign_in(client, TIM_EMAIL).json()["token"]

    response = client.post(
        f"/api/sessions/{session.id}/push-intervals?athlete=renee",
        headers={"Authorization": f"Bearer {tim_token}"},
    )
    assert response.status_code == 403
