"""Shared pytest fixtures for CLI and validate_all tests."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from swim_coach.models import Athlete, Event
from swim_coach.store import FileStore

FIXTURE_SLUG = "wife"


@pytest.fixture
def athlete_tree(tmp_path):
    """A realistic single-athlete tree under tmp_path, ready for CLI commands.

    css ~95s/100m, pool_schedule tue/thu/fri, one A event ~20 weeks out.
    (6000m current weekly volume is a CLI arg, not a persisted profile
    field -- callers pass it via --current-volume.)
    """
    store = FileStore(base_dir=tmp_path)
    athlete = Athlete(
        id=uuid.uuid4(),
        slug=FIXTURE_SLUG,
        name="Jane Doe",
        css_pace_s_per_100m=95.0,
        zones=None,
        constraints={},
        pool_schedule=["tue", "thu", "fri"],
    )
    store.save_athlete(athlete)

    event = Event(
        id=uuid.uuid4(),
        athlete_id=athlete.id,
        name="Catalina Channel",
        event_date=date.today() + timedelta(weeks=20),
        distance_m=20000,
        water_temp_c=18.0,
        wetsuit=False,
        priority="A",
    )
    store.save_events(FIXTURE_SLUG, [event])

    return {
        "base_dir": tmp_path,
        "slug": FIXTURE_SLUG,
        "athlete": athlete,
        "event": event,
        "store": store,
        "current_weekly_volume_m": 6000,
    }
