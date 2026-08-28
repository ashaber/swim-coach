"""Tests for backend.app.wellness_merge.merge_wellness -- the shared
never-overwrite-existing-nonnull-with-null policy used by both the
intervals.icu sync (backend/app/sync.py) and the manual check-in route
(backend/app/routes/wellness.py).

No LLM calls, no network access -- pure data merging + pydantic validation.
"""

from __future__ import annotations

import sys
import uuid
from datetime import date
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from swim_coach.models import Wellness

from app.wellness_merge import merge_wellness

ATHLETE_ID = uuid.uuid4()
DATE = date(2026, 8, 20)


def test_merge_wellness_creates_new_row_when_no_existing():
    result = merge_wellness(
        None, {"resting_hr": 50, "hrv": 60.0}, athlete_id=ATHLETE_ID, date=DATE, source="intervals_sync"
    )
    assert result.athlete_id == ATHLETE_ID
    assert result.date == DATE
    assert result.resting_hr == 50
    assert result.hrv == 60.0
    assert result.source == "intervals_sync"
    assert result.schema_version == 1
    assert result.sleep_quality is None


def test_merge_wellness_preserves_existing_nonnull_when_update_is_null():
    existing = Wellness(
        id=uuid.uuid4(),
        athlete_id=ATHLETE_ID,
        date=DATE,
        resting_hr=48,
        hrv=65.0,
        source="manual",
    )
    result = merge_wellness(
        existing, {"resting_hr": None, "hrv": None}, athlete_id=ATHLETE_ID, date=DATE
    )
    # A None incoming value never overwrites an existing non-None value.
    assert result.resting_hr == 48
    assert result.hrv == 65.0
    assert result.id == existing.id


def test_merge_wellness_fills_existing_null_field():
    existing = Wellness(
        id=uuid.uuid4(),
        athlete_id=ATHLETE_ID,
        date=DATE,
        resting_hr=None,
        hrv=None,
    )
    result = merge_wellness(
        existing, {"resting_hr": 52, "hrv": 61.2}, athlete_id=ATHLETE_ID, date=DATE
    )
    assert result.resting_hr == 52
    assert result.hrv == 61.2
    assert result.id == existing.id


def test_merge_wellness_explicit_source_overrides_existing():
    existing = Wellness(
        id=uuid.uuid4(),
        athlete_id=ATHLETE_ID,
        date=DATE,
        source="intervals_sync",
    )
    result = merge_wellness(existing, {}, athlete_id=ATHLETE_ID, date=DATE, source="manual")
    assert result.source == "manual"


def test_merge_wellness_no_source_arg_keeps_existing_source():
    existing = Wellness(
        id=uuid.uuid4(),
        athlete_id=ATHLETE_ID,
        date=DATE,
        source="intervals_sync",
    )
    result = merge_wellness(existing, {"resting_hr": 55}, athlete_id=ATHLETE_ID, date=DATE)
    assert result.source == "intervals_sync"
    assert result.resting_hr == 55
