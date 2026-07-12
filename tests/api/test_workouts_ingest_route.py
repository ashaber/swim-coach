"""POST /api/workouts/ingest -- athlete-facing .fit/.tcx/.csv upload.

Phase 3: the parsers in `swim_coach.parse_files` previously had no
athlete-reachable path (CLI-only, on Andrew's machine). This route lets the
PWA's Log tab upload a watch export, get back a parsed `WorkoutDraft`
(including any `warnings`), and review it before a *separate* confirm step
saves a `Workout` record via the existing `POST /api/workouts`. This
endpoint itself never saves a `Workout` -- it's parse-and-return, so several
tests below assert both "the draft looks right" and "no Workout was saved as
a side effect." It DOES, however, run the same enrichment `swim_coach.cli`'s
`ingest --save` does (durable raw-file copy, series sidecar, analytics) --
see `backend/app/routes/workouts.py`'s module docstring for why that happens
here rather than at confirm time, and the real-fixture tests below for
coverage of it.

Boundary-validation tests (extension allowlist, size cap, parse failure,
auth) matter more here than deep parser-correctness -- that's
`tests/unit/test_parse_files.py`'s job. This module double-checks the wiring
plus the real-file cases (mirroring that module's own
`FIT_FIXTURE.exists()` skip pattern) since a real .fit is the file type most
likely to surprise the route (multipart handling, tempfile round-trip, and
now the raw-file/series-sidecar enrichment) -- `real_swim.fit` (a pool swim,
no continuous series -- see `tests/unit/test_cli.py`'s
`test_ingest_fit_pool_swim_has_lengths_and_no_sidecar`) and `real_kayak.fit`
(cross_train, has a continuous HR series) between them exercise both the
with-series and without-series enrichment paths.
"""

from __future__ import annotations

from pathlib import Path

from fakes import auth_headers

REPO_ROOT = Path(__file__).resolve().parents[2]
FIT_FIXTURE = REPO_ROOT / "tests" / "unit" / "fixtures" / "fit" / "real_swim.fit"
FIT_KAYAK_FIXTURE = REPO_ROOT / "tests" / "unit" / "fixtures" / "fit" / "real_kayak.fit"
TCX_FIXTURE = REPO_ROOT / "tests" / "unit" / "fixtures" / "tcx" / "sample_pool_swim.tcx"
CSV_FIXTURE = REPO_ROOT / "tests" / "unit" / "fixtures" / "csv" / "sample_garmin_export.csv"


def _upload(client, path: Path, *, filename: str | None = None, athlete: str = "renee", headers=None, content_type="application/octet-stream"):
    data = path.read_bytes()
    return client.post(
        f"/api/workouts/ingest?athlete={athlete}",
        files={"file": (filename or path.name, data, content_type)},
        headers=headers if headers is not None else auth_headers(),
    )


def test_ingest_requires_auth(client) -> None:
    response = client.post(
        "/api/workouts/ingest?athlete=renee",
        files={"file": ("swim.tcx", TCX_FIXTURE.read_bytes(), "application/octet-stream")},
    )
    assert response.status_code == 401


def test_ingest_unknown_athlete_is_404(client) -> None:
    response = _upload(client, TCX_FIXTURE, athlete="nobody")
    assert response.status_code == 404
    assert "error" in response.json()


def test_ingest_rejects_unsupported_extension(client) -> None:
    response = _upload(client, TCX_FIXTURE, filename="workout.gpx")
    assert response.status_code == 415
    body = response.json()
    assert "error" in body
    assert "gpx" in body["error"].lower()


def test_ingest_rejects_oversized_file(client) -> None:
    huge = b"0" * (11 * 1024 * 1024)  # over the 10 MB cap
    response = client.post(
        "/api/workouts/ingest?athlete=renee",
        files={"file": ("huge.csv", huge, "text/csv")},
        headers=auth_headers(),
    )
    assert response.status_code == 413
    assert "error" in response.json()


def test_ingest_rejects_empty_file(client) -> None:
    response = client.post(
        "/api/workouts/ingest?athlete=renee",
        files={"file": ("empty.csv", b"", "text/csv")},
        headers=auth_headers(),
    )
    assert response.status_code == 400
    assert "error" in response.json()


def test_ingest_parse_failure_returns_clean_json_error_not_500(client) -> None:
    # A .fit extension but garbage bytes -- fitdecode must choke on this.
    # The route must turn that into a clean 4xx JSON error, never a raw
    # traceback and never an unhandled-exception 500.
    response = _upload(client, Path(__file__), filename="corrupt.fit")  # this .py file's own bytes, mislabeled .fit
    assert response.status_code in (400, 422)
    body = response.json()
    assert "error" in body
    assert "Traceback" not in body["error"]


def test_ingest_parses_tcx_and_does_not_save(client) -> None:
    before = client.get("/api/workouts?athlete=renee", headers=auth_headers())
    assert before.status_code == 200
    count_before = len(before.json())

    response = _upload(client, TCX_FIXTURE)
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "tcx"
    assert body["distance_m"] == 600
    assert "warnings" in body
    assert isinstance(body["warnings"], list)
    # Never persisted server-side -- ingest is parse-only.
    assert "id" not in body

    after = client.get("/api/workouts?athlete=renee", headers=auth_headers())
    assert after.status_code == 200
    assert len(after.json()) == count_before


def test_ingest_parses_csv(client) -> None:
    response = _upload(client, CSV_FIXTURE)
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "csv"
    assert body["distance_m"] == 2500


def test_ingest_extension_match_is_case_insensitive(client) -> None:
    response = _upload(client, TCX_FIXTURE, filename="SWIM.TCX")
    assert response.status_code == 200
    assert response.json()["source"] == "tcx"


def _fit_missing() -> bool:
    return not FIT_FIXTURE.exists()


def _fit_kayak_missing() -> bool:
    return not FIT_KAYAK_FIXTURE.exists()


def test_ingest_parses_real_fit_fixture(client, athletes_dir) -> None:
    if _fit_missing():
        import pytest

        pytest.skip("no real .fit fixture at tests/unit/fixtures/fit/real_swim.fit")
    response = _upload(client, FIT_FIXTURE, content_type="application/octet-stream")
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "fit"
    assert body["distance_m"] > 0
    assert body["duration_min"] > 0

    # Enrichment (mirrors swim_coach.cli's `ingest --save`, see the module
    # docstring): a durable raw-file copy always happens, even for a fixture
    # like this one whose parse produces no continuous series.
    assert "series" not in body  # never sent over the wire (see the route)
    assert body["raw_ref"] is not None
    raw_path = Path(body["raw_ref"])
    assert raw_path.exists()
    assert raw_path == athletes_dir / "renee" / "logs" / "files" / FIT_FIXTURE.name
    assert body["series_ref"] is None  # pool swim -- no continuous series
    assert body["analytics"] is not None
    assert len(body["lengths"]) > 0


def test_ingest_real_fit_kayak_fixture_gets_series_and_analytics(client, athletes_dir) -> None:
    if _fit_kayak_missing():
        import pytest

        pytest.skip("no real .fit fixture at tests/unit/fixtures/fit/real_kayak.fit")
    response = _upload(client, FIT_KAYAK_FIXTURE, content_type="application/octet-stream")
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "fit"
    assert body["sport"] == "cross_train"

    assert "id" not in body  # still never persisted as a Workout here

    raw_path = Path(body["raw_ref"])
    assert raw_path.exists()
    assert raw_path == athletes_dir / "renee" / "logs" / "files" / FIT_KAYAK_FIXTURE.name

    assert body["series_ref"] is not None
    series_path = Path(body["series_ref"])
    assert series_path.exists()
    import json as _json

    series = _json.loads(series_path.read_text(encoding="utf-8"))
    assert "hr" in series

    assert body["analytics"] is not None
    assert body["analytics"]["pause_count"] == 0

    # Never persisted server-side -- ingest is still parse-and-enrich-only,
    # not save (see module docstring); confirming is a separate
    # POST /api/workouts call.
    after = client.get("/api/workouts?athlete=renee", headers=auth_headers())
    assert after.status_code == 200
    assert all(w.get("raw_ref") != body["raw_ref"] for w in after.json())


def test_ingest_with_store_lacking_raw_file_support_skips_refs_but_computes_analytics(client, monkeypatch) -> None:
    """A db-backed deploy (STORE_BACKEND=db) has no save_raw_file/save_series
    until Phase 2.5's Supabase Storage lands -- the route must skip both refs,
    warn the athlete in the draft, and still compute analytics, never 500.
    (The first production upload died on exactly this AttributeError: every
    other test here runs against FileStore, which has the extra methods.)"""
    if _fit_kayak_missing():
        import pytest

        pytest.skip("real_kayak.fit fixture not present")

    import app.routes.workouts as workouts_module

    real_make_store = workouts_module.make_store

    class _StoreInterfaceOnly:
        """Proxy hiding FileStore's raw-file/series extras, like DbStore."""

        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            if name in ("save_raw_file", "save_series"):
                raise AttributeError(name)
            return getattr(self._inner, name)

    monkeypatch.setattr(
        workouts_module, "make_store", lambda settings: _StoreInterfaceOnly(real_make_store(settings))
    )

    response = _upload(client, FIT_KAYAK_FIXTURE)
    assert response.status_code == 200
    body = response.json()
    assert body["raw_ref"] is None
    assert body["series_ref"] is None
    assert body["analytics"] is not None
    assert body["analytics"]["cardiac_drift_pct"] is not None
    assert any("doesn't retain the original file" in w for w in body["warnings"])
