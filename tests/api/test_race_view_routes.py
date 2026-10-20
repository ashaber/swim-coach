"""Section splits (POST), section notes (PATCH) and the lazy section drill-down (GET) for a race.

The ride is the synthetic course of tests/unit (made-up coordinates), saved as a race with its series."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from fakes import auth_headers
from swim_coach.store import FileStore

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))
import test_course_sectors_race_view as course  # noqa: E402


@pytest.fixture
def race(athletes_dir: Path):
    store = FileStore(base_dir=athletes_dir)
    series = course._series(5)
    workout = course._workout(5, series)
    store.save_workout("renee", workout)
    store.save_series("renee", workout.date, workout.sport, workout.id, series)
    return workout


@pytest.fixture
def analysed(client, race):
    assert client.post(f"/api/workouts/{race.id}/kind?athlete=renee", json={"kind": "race"}, headers=auth_headers()).status_code == 200
    return race


def _splits(client, wid, body, **kw):
    return client.post(f"/api/workouts/{wid}/section-splits?athlete=renee", json=body, headers=kw.get("headers", auth_headers()))


def test_section_splits_require_auth(client, analysed) -> None:
    assert client.post(f"/api/workouts/{analysed.id}/section-splits?athlete=renee", json={"splits": {}}).status_code == 401


def test_splits_replace_the_stored_map_and_rerun_the_analysis(client, analysed, athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    body = _splits(client, analysed.id, {"splits": {"C1": 2}}).json()
    assert body["section_splits"] == {"C1": 2}
    cs = store.get_workout("renee", analysed.id).analytics.course_sectors
    assert cs.splits == {"C1": 2} and [s.label for s in cs.sectors][:4] == ["S1", "C1a", "C1b", "S2"]

    body = _splits(client, analysed.id, {"splits": {"C2": 3}}).json()
    assert body["section_splits"] == {"C2": 3}  # replaced, not merged
    cs = store.get_workout("renee", analysed.id).analytics.course_sectors
    assert cs.splits == {"C2": 3} and "C1a" not in [s.label for s in cs.sectors]

    assert _splits(client, analysed.id, {"splits": {}}).json()["section_splits"] == {}
    cs = store.get_workout("renee", analysed.id).analytics.course_sectors
    assert cs.splits == {} and "C2a" not in [s.label for s in cs.sectors]


def test_splits_reject_bad_input_and_unknown_workout(client, analysed) -> None:
    assert _splits(client, analysed.id, {"splits": {"C1": 9}}).status_code == 422
    assert _splits(client, analysed.id, {"splits": {"C1": 1}}).status_code == 422
    assert _splits(client, analysed.id, {"splits": {"C1": "3"}}).status_code == 422
    assert _splits(client, analysed.id, {"splits": ["C1"]}).status_code == 422
    assert _splits(client, uuid.uuid4(), {"splits": {}}).status_code == 404


def test_section_notes_are_patchable_and_limited_to_280_chars(client, analysed, athletes_dir) -> None:
    patch = lambda notes: client.patch(f"/api/workouts/{analysed.id}?athlete=renee", json={"section_notes": notes}, headers=auth_headers())
    assert patch({"C3": "sand, run it"}).status_code == 200
    assert FileStore(base_dir=athletes_dir).get_workout("renee", analysed.id).section_notes == {"C3": "sand, run it"}
    assert patch({"C3": "x" * 281}).status_code == 422
    assert patch({"C3": "x" * 280}).status_code == 200
    assert patch({"C3": "  "}).json()["section_notes"] == {}  # blank deletes


def test_sections_endpoint_returns_outline_and_graded_pieces(client, analysed) -> None:
    _splits(client, analysed.id, {"splits": {"C1": 2}})
    r = client.get(f"/api/workouts/{analysed.id}/sections?athlete=renee", headers=auth_headers())
    assert r.status_code == 200
    body = r.json()
    assert 2 < len(body["outline"]) <= 400 and all(len(p) == 2 for p in body["outline"])
    assert "C1a" in body["sections"] and "C1b" in body["sections"]
    lap = next(iter(body["sections"]["C1a"]["laps"].values()))
    assert all(len(p) == 4 for p in lap["points"])
    assert {"from_i", "to_i", "time_s", "power_w", "loss_s", "eff", "within_noise"} <= set(lap["pieces"][0])
    assert len(body["sections"]["C1a"]["bbox"]) == 4


def test_sections_endpoint_needs_auth_and_reports_errors_like_pacing(client, analysed, race) -> None:
    assert client.get(f"/api/workouts/{analysed.id}/sections?athlete=renee").status_code == 401
    assert client.get(f"/api/workouts/{uuid.uuid4()}/sections?athlete=renee", headers=auth_headers()).status_code == 404


def test_sections_endpoint_is_422_for_a_workout_without_sections(client, race) -> None:
    r = client.get(f"/api/workouts/{race.id}/sections?athlete=renee", headers=auth_headers())  # never analysed
    assert r.status_code == 422 and "course sections" in r.text
