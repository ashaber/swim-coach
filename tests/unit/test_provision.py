"""Tests for swim_coach.provision.provision_athlete.

Drives the real FileStore (a tmp_path tree) -- no LLM calls, no network, no
mocking of the engine math it reuses (zone_table/scaffold_macro/
generate_week): these tests assert those functions were APPLIED (an athlete
ends up with zones; a macro/week end up persisted and internally
consistent), not their internal arithmetic (that's test_zones.py's/
test_plan.py's job).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from swim_coach.models import Athlete, Event
from swim_coach.provision import ProvisionResult, provision_athlete
from swim_coach.store import FileStore

def make_profile(**overrides) -> Athlete:
    data = dict(
        id=uuid.uuid4(),
        slug="newathlete",
        name="New Athlete",
        css_pace_s_per_100m=95.0,
        zones=None,
        constraints={},
        pool_schedule=["tue", "thu", "fri"],
    )
    data.update(overrides)
    return Athlete(**data)


def make_event(athlete_id, **overrides) -> Event:
    data = dict(
        id=uuid.uuid4(),
        athlete_id=athlete_id,
        name="Catalina Channel",
        # Relative to "today" (not the fixed START constant) so this stays
        # far enough out regardless of what "today" is when the suite runs.
        event_date=date.today() + timedelta(weeks=24),
        distance_m=20000,
        water_temp_c=18.0,
        wetsuit=False,
        priority="A",
    )
    data.update(overrides)
    return Event(**data)


@pytest.fixture
def store(tmp_path) -> FileStore:
    return FileStore(base_dir=tmp_path)


# --- happy path: full inputs ------------------------------------------------


def test_provision_full_inputs_creates_everything(store):
    profile = make_profile()
    event = make_event(profile.id)

    result = provision_athlete(
        store,
        profile=profile,
        events=[event],
        email="Athlete@Example.COM",
        note="first tester",
        target_event=event,
        current_volume_m=6000,
    )

    assert isinstance(result, ProvisionResult)
    assert result.skipped == []

    # athlete persisted with zones computed via zone_table -- assert it was
    # APPLIED (a full Z1-Z5 table keyed to the profile's css pace), not its
    # internal offset arithmetic.
    saved_athlete = store.load_athlete("newathlete")
    assert saved_athlete.css_pace_s_per_100m == 95.0
    assert saved_athlete.zones is not None
    assert set(saved_athlete.zones.keys()) == {"Z1", "Z2", "Z3", "Z4", "Z5"}
    assert result.athlete.zones == saved_athlete.zones

    # events persisted
    saved_events = store.load_events("newathlete")
    assert len(saved_events) == 1
    assert saved_events[0].id == event.id

    # macro persisted, scaffolded via the real scaffold_macro (4 blocks)
    saved_macro = store.load_macro("newathlete")
    assert saved_macro is not None
    assert result.macro is not None
    assert [b.name for b in saved_macro.blocks] == ["base", "build", "peak", "taper"]

    # first week persisted, generated via the real generate_week, for the
    # macro's first block's start date
    assert result.week is not None
    iso_week = result.week.iso_week
    saved_week = store.load_week("newathlete", iso_week)
    assert saved_week is not None
    assert len(saved_week.sessions) > 0
    first_block = saved_macro.blocks[0]
    year, week, _ = first_block.start_date.isocalendar()
    assert iso_week == f"{year}-W{week:02d}"

    # allowlist entry persisted, normalized
    assert result.allowed_email is not None
    assert result.allowed_email.email == "athlete@example.com"
    entry = store.get_allowed_email("athlete@example.com")
    assert entry is not None
    assert entry.athlete_slug == "newathlete"
    assert entry.note == "first tester"


def test_provision_write_order_is_fk_safe(store):
    """Athlete must exist before add_allowed_email is called -- FileStore's
    add_allowed_email raises FileNotFoundError if the slug isn't already
    known, so a successful run here is itself proof of the FK-safe order."""
    profile = make_profile(slug="orderslug")
    result = provision_athlete(
        store, profile=profile, email="x@example.com", current_volume_m=None
    )
    assert result.allowed_email is not None
    assert store.load_athlete("orderslug") is not None


# --- degraded input: no target event / no current volume -------------------


def test_provision_without_target_event_skips_macro_and_week(store):
    profile = make_profile(slug="noevent")
    result = provision_athlete(
        store, profile=profile, email="x@example.com", current_volume_m=6000
    )
    assert result.macro is None
    assert result.week is None
    assert len(result.skipped) == 1
    assert "no target event given" in result.skipped[0]

    # athlete + zones + allowlist still fully created
    saved = store.load_athlete("noevent")
    assert saved.zones is not None
    assert store.get_allowed_email("x@example.com") is not None
    assert store.load_macro("noevent") is None


def test_provision_without_current_volume_skips_macro_and_week(store):
    profile = make_profile(slug="novolume")
    event = make_event(profile.id)
    result = provision_athlete(
        store,
        profile=profile,
        events=[event],
        email="x@example.com",
        target_event=event,
        current_volume_m=None,
    )
    assert result.macro is None
    assert result.week is None
    assert "no current_volume_m given" in result.skipped[0]
    assert store.load_athlete("novolume").zones is not None
    assert store.get_allowed_email("x@example.com") is not None


def test_provision_without_events_still_creates_athlete_and_allowlist(store):
    profile = make_profile(slug="bare")
    result = provision_athlete(store, profile=profile, email="bare@example.com")
    assert result.events == []
    assert result.macro is None
    assert result.week is None
    assert store.load_events("bare") == []
    assert store.get_allowed_email("bare@example.com") is not None


# --- missing CSS pace: hard error, not a degrade ----------------------------


def test_provision_without_css_pace_raises_value_error(store):
    profile = make_profile(css_pace_s_per_100m=None)
    with pytest.raises(ValueError, match="css_pace_s_per_100m"):
        provision_athlete(store, profile=profile, email="x@example.com")

    # nothing was written -- the precondition check runs before any store
    # write.
    with pytest.raises(FileNotFoundError):
        store.load_athlete(profile.slug)


# --- runway too short: hard error (present-but-invalid input, not absent) --


def test_provision_insufficient_runway_raises_and_leaves_athlete_provisioned(store):
    profile = make_profile(slug="tooclose")
    event = make_event(profile.id, event_date=date.today() + timedelta(weeks=3))

    with pytest.raises(ValueError, match="weeks available"):
        provision_athlete(
            store,
            profile=profile,
            events=[event],
            email="x@example.com",
            target_event=event,
            current_volume_m=6000,
        )

    # athlete/events/allowlist writes happen BEFORE the macro scaffold call,
    # so those already landed -- a caller fixes the event/volume and
    # re-runs (every write here is an upsert; see provision.py docstring).
    assert store.load_athlete("tooclose") is not None


# --- idempotency: re-running upserts rather than duplicating ---------------


def test_provision_rerun_same_profile_upserts(store):
    profile = make_profile(slug="rerun")
    event = make_event(profile.id)

    provision_athlete(
        store,
        profile=profile,
        events=[event],
        email="a@example.com",
        target_event=event,
        current_volume_m=6000,
    )
    # Re-run with a changed name and a different email -- must update in
    # place, not error or duplicate.
    updated_profile = profile.model_copy(update={"name": "Renamed"})
    result = provision_athlete(
        store,
        profile=updated_profile,
        events=[event],
        email="b@example.com",
        target_event=event,
        current_volume_m=6000,
    )
    assert result.athlete.name == "Renamed"
    assert store.load_athlete("rerun").name == "Renamed"
    # both allowlist entries persist (upsert is per-email, not per-athlete)
    assert store.get_allowed_email("a@example.com").athlete_slug == "rerun"
    assert store.get_allowed_email("b@example.com").athlete_slug == "rerun"
