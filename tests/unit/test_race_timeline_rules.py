"""Race-day timeline rules (not_later_than / not_earlier_than / only_if_start_*). The vectors in
tests/fixtures/race_timeline_vectors.json are shared with web/tests/unit/raceDay.test.js so the
engine and the PWA cannot drift."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from swim_coach.models import RaceChecklistTemplate, TimelineEntry
from swim_coach.race_day import new_plan_from_template, timeline_clock

ROOT = Path(__file__).resolve().parents[2]
VECTORS = json.loads((ROOT / "tests" / "fixtures" / "race_timeline_vectors.json").read_text())


def _clock(entries: list[TimelineEntry], start: str | None) -> dict[str, str | None]:
    template = RaceChecklistTemplate(timeline=entries)
    plan = new_plan_from_template(template, race_date=date(2026, 10, 17), start_time=start)
    return {c["id"]: c["time"] for c in timeline_clock(plan)}


def test_vector_timeline_matches_shipped_andrew_template() -> None:
    template = json.loads((ROOT / "athletes" / "andrew" / "race-checklist-template.json").read_text())
    assert VECTORS["timeline"] == template["timeline"]


@pytest.mark.parametrize("case", VECTORS["cases"], ids=lambda c: c["name"])
def test_shared_timeline_vectors(case) -> None:
    template = RaceChecklistTemplate(timeline=[TimelineEntry(**e) for e in VECTORS["timeline"]])
    plan = new_plan_from_template(template, race_date=date(2026, 10, 17), start_time=case["start_time"])
    clock = timeline_clock(plan)
    by_id = {c["id"]: c["time"] for c in clock}
    for entry_id, expected in case["expect"].items():
        assert by_id[entry_id] == expected, entry_id
    for entry_id in case["absent"]:
        assert entry_id not in by_id
    timed = [c["abs_min"] for c in clock if c["abs_min"] is not None]
    assert timed == sorted(timed)


def test_not_earlier_than_floors_and_only_if_start_before() -> None:
    entries = [
        TimelineEntry(id="w", label="Wake", offset_min=-300, not_earlier_than="05:00"),
        TimelineEntry(id="early", label="Early only", offset_min=-60, only_if_start_before="09:00"),
        TimelineEntry(id="s", label="Start", offset_min=0, is_start=True),
    ]
    eight = _clock(entries, "08:00")
    assert eight["w"] == "05:00" and eight["early"] == "07:00"
    nine = _clock(entries, "09:00")
    assert "early" not in nine and nine["w"] == "05:00"


def test_plain_offset_entries_still_work() -> None:
    entries = [TimelineEntry(id="w", label="Wake", offset_min=-315), TimelineEntry(id="s", label="Start", offset_min=0)]
    assert _clock(entries, "09:00") == {"w": "03:45", "s": "09:00"}


def test_rule_fields_validate_hhmm() -> None:
    with pytest.raises(ValidationError):
        TimelineEntry(id="x", label="x", offset_min=-5, not_later_than="7am")
