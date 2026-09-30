"""One short, consumer-facing title per session (Andrew, 2026-09-29).

Regression: the coach-authored 40/20 VO2 ride showed as
"3 rounds of [6 x (40s Z5 hard / 20s Z1 easy)]" in the PWA and as "Build" on
intervals.icu (purpose "Build — 40/20s VO2 intervals" split on its em dash gave
the macro phase name).
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from swim_coach.models import Session, WorkoutStructure
from swim_coach.session_title import derive_title, resolve_title, session_title

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "ride_2026_09_29_vo2_40_20.json"


def _session(**overrides) -> Session:
    data = dict(
        id=uuid.uuid4(), athlete_id=uuid.uuid4(), date=date(2026, 9, 29), sport="bike",
        source="ai_coach", duration_min=60.0, intensity={"zone": "Z2"}, purpose="Base — aerobic ride",
    )
    data.update(overrides)
    return Session(**data)


def _step(role: str, dur: float, zone: str, label: str = "s") -> dict:
    return {
        "kind": "step", "role": role, "label": label, "duration_kind": "time_s", "duration_value": dur,
        "modality": "bike", "target": {"basis": "zone", "zone": zone},
    }


def _structured(*items: dict) -> WorkoutStructure:
    return WorkoutStructure.model_validate({"items": list(items)})


def _repeat(count: int, *steps: dict) -> dict:
    return {"kind": "repeat", "count": count, "steps": list(steps)}


@pytest.fixture(scope="module")
def fixture_session() -> Session:
    return Session.model_validate(json.loads(FIXTURE.read_text())["planned_session"])


def test_fixture_session_derives_3x6_40_20_vo2(fixture_session):
    assert derive_title(fixture_session) == "3x6 40/20 VO2"
    assert session_title(fixture_session) == "3x6 40/20 VO2"


def test_explicit_title_wins_and_is_cleaned(fixture_session):
    s = fixture_session.model_copy(update={"title": "  3x6 VO2 [40/20]  "})
    assert session_title(s) == "3x6 VO2 40/20"


def test_title_field_rejects_overlong_titles():
    with pytest.raises(ValidationError):
        _session(title="x" * 60)


def test_single_repeat_of_short_reps():
    s = _session(structured=_structured(
        _step("warmup", 600, "Z2"), _repeat(8, _step("interval", 30, "Z5"), _step("recovery", 30, "Z1")),
        _step("cooldown", 300, "Z1"),
    ))
    assert derive_title(s) == "8x30/30 VO2"


def test_long_reps_use_minutes_and_zone_name():
    s = _session(structured=_structured(
        _step("warmup", 900, "Z2"), _repeat(3, _step("interval", 720, "Z4"), _step("recovery", 300, "Z1")),
    ))
    assert derive_title(s) == "3x12' Threshold"


def test_no_intervals_yields_no_structured_title():
    s = _session(structured=_structured(_step("steady", 3600, "Z2")))
    assert derive_title(s) is None


def test_fallback_to_purpose_never_uses_phase_name():
    assert session_title(_session(purpose="Build — 40/20s VO2 intervals")) == "40/20s VO2 intervals"
    assert session_title(_session(purpose="Base")) == "Base"  # nothing better exists
    assert session_title(_session(purpose="Heinous club ride — endurance")) == "Heinous club ride"


def test_fallback_never_contains_brackets():
    s = _session(purpose="3 rounds of [6 x (40s Z5 hard / 20s Z1 easy)]")
    title = session_title(s)
    assert "[" not in title and "]" not in title


def test_resolve_title_is_none_when_only_purpose_is_available():
    assert resolve_title(_session(purpose="Heinous club ride — endurance")) is None
