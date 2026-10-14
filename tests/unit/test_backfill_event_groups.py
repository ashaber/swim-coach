"""scripts/backfill_event_groups.py: explicit-args grouping, dry run by default, idempotent."""

from __future__ import annotations

import importlib.util
import uuid
from datetime import date
from pathlib import Path

import pytest

from swim_coach.event_groups import effective_target, groups
from swim_coach.models import Event

_SPEC = importlib.util.spec_from_file_location(
    "backfill_event_groups", Path(__file__).resolve().parents[2] / "scripts" / "backfill_event_groups.py"
)
script = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(script)

D1, D2 = date(2026, 10, 17), date(2026, 10, 18)


def _source() -> Event:
    return Event(
        id=uuid.uuid4(), athlete_id=uuid.uuid4(), name="Peak Weekend", event_date=D1, target_metric="duration_min",
        target_value=60.0, priority="A", primary_sport="bike",
    )


def test_missing_member_is_created_as_a_copy_and_group_defaults_to_first_race():
    src = _source()
    events, lines = script.plan_group(
        [src], group_name="Peak Weekend", group_type="double_header", source_event="Peak Weekend", race_dates=[D1, D2]
    )
    assert len(events) == 2 and any("create member" in line for line in lines)
    g = groups(events)[0]
    assert g.peak_event_id == src.id and (g.first_date, g.last_date) == (D1, D2)
    assert effective_target(events[1], events).id == src.id


def test_rerun_is_idempotent_and_peak_override_applies():
    src = _source()
    args = dict(group_name="G", group_type="double_header", source_event="Peak Weekend", race_dates=[D1, D2])
    once, _ = script.plan_group([src], **args)
    twice, lines = script.plan_group(once, **args, peak_date=D2)
    assert len(twice) == 2 and not any("create member" in line for line in lines)
    assert effective_target(twice[0], twice).event_date == D2


def test_bad_input_is_a_value_error():
    src = _source()
    with pytest.raises(ValueError):
        script.plan_group([src], group_name="G", group_type="omnium", source_event="nope", race_dates=[D1, D2])
    with pytest.raises(ValueError):
        script.plan_group([src], group_name="G", group_type="omnium", source_event="Peak Weekend", race_dates=[D2])
    with pytest.raises(ValueError):
        script.plan_group(
            [src], group_name="G", group_type="omnium", source_event="Peak Weekend", race_dates=[D1, D2],
            peak_date=date(2026, 1, 1),
        )
