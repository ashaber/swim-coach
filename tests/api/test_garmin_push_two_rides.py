"""Garmin push by session id on a day with two same-sport sessions: only the named one is pushed, and
the coach tool accepts the short id the plan context shows."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from swim_coach.models import WorkoutStep, WorkoutStructure, WorkoutTarget
from swim_coach.store import FileStore

from app.tools import build_tool_handlers
from test_garmin_push import ISO_WEEK, _add_session, _bulk_ok_handler, _force_mock_transport, _session

STRUCTURE = WorkoutStructure(
    items=[
        WorkoutStep(
            label="Z2", role="steady", duration_kind="time_s", duration_value=1800,
            target=WorkoutTarget(basis="power_w", low=140.0, high=190.0), modality="bike",
        )
    ]
)


def _two_rides(athletes_dir: Path):
    store = FileStore(base_dir=athletes_dir)
    athlete_id = store.load_athlete("renee").id
    warm = _session(athlete_id, sport="bike", structured=STRUCTURE, purpose="warm-up")
    race = _session(athlete_id, sport="bike", structured=STRUCTURE, purpose="race")
    _add_session(athletes_dir, warm)
    _add_session(athletes_dir, race)
    return store, warm, race


@pytest.fixture
def sync_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "INTERVALS_SYNC_CONFIG",
        json.dumps([{"slug": "renee", "intervals_athlete_id": "i999", "api_key": "k"}]),
    )


def test_push_by_id_sends_only_that_session(athletes_dir, monkeypatch, sync_config) -> None:
    store, warm, race = _two_rides(athletes_dir)
    captured: list = []
    _force_mock_transport(monkeypatch, _bulk_ok_handler(captured))
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    result = handlers["push_to_garmin"]({"session_id": str(race.id)})

    assert result["pushed"] == 1
    assert [e["external_id"] for e in captured] == [str(race.id)]


def test_push_accepts_the_short_id_from_context(athletes_dir, monkeypatch, sync_config) -> None:
    store, warm, race = _two_rides(athletes_dir)
    captured: list = []
    _force_mock_transport(monkeypatch, _bulk_ok_handler(captured))
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    result = handlers["push_to_garmin"]({"session_id": str(warm.id)[:8]})

    assert result["pushed"] == 1
    assert [e["external_id"] for e in captured] == [str(warm.id)]


def test_push_unknown_id_is_a_clear_error(athletes_dir, monkeypatch, sync_config) -> None:
    store, _warm, _race = _two_rides(athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    assert "no session with id" in handlers["push_to_garmin"]({"session_id": "deadbeef"})["error"]


def test_a_week_push_sends_both_same_day_sessions(athletes_dir, monkeypatch, sync_config) -> None:
    store, warm, race = _two_rides(athletes_dir)
    captured: list = []
    _force_mock_transport(monkeypatch, _bulk_ok_handler(captured))
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)

    handlers["push_to_garmin"]({"iso_week": ISO_WEEK})

    assert {e["external_id"] for e in captured} >= {str(warm.id), str(race.id)}
