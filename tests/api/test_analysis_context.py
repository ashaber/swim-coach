"""`app.enrich.build_analysis_context`: what the analyzer is told about a workout beyond its
stream (athlete thresholds, kind from the matched session or a same-day same-sport event,
the plan lookup)."""

from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path

from swim_coach.models import Event, Session, Workout
from swim_coach.store import FileStore

from app.enrich import build_analysis_context

DAY = date(2026, 9, 19)


def _session(athlete_id, purpose: str, **kw) -> Session:
    return Session(
        id=uuid.uuid4(), athlete_id=athlete_id, date=DAY, sport="bike", source="ai_coach",
        duration_min=60.0, distance_m=0, intensity={"zone": "Z4"}, purpose=purpose, **kw,
    )


def _workout(athlete_id, sport: str = "bike") -> Workout:
    return Workout(
        id=uuid.uuid4(), athlete_id=athlete_id, date=DAY, sport=sport, source="fit", distance_m=0, duration_min=60.0
    )


def _event(athlete_id, sport: str = "bike") -> Event:
    return Event(
        id=uuid.uuid4(), athlete_id=athlete_id, name="CX race", event_date=DAY, target_metric="duration_min",
        distance_m=None, target_value=45.0, primary_sport=sport, priority="B",
    )


def test_context_carries_the_athlete_and_the_session_kind(athletes_dir: Path) -> None:
    store = FileStore(base_dir=athletes_dir)
    athlete = store.load_athlete("renee")
    w = _workout(athlete.id)
    ctx = build_analysis_context(
        store, "renee", w, series=None, session=_session(athlete.id, "RACE — cross opener", structure="barrier", kind="race")
    )
    assert ctx.kind == "race" and w.kind == "race"
    assert ctx.athlete.lthr_bpm == athlete.lthr_bpm and ctx.athlete.ftp_watts == athlete.ftp_watts


def test_unmatched_ride_is_a_free_ride_unless_an_event_is_that_day(athletes_dir: Path) -> None:
    store = FileStore(base_dir=athletes_dir)
    athlete = store.load_athlete("renee")
    assert build_analysis_context(store, "renee", _workout(athlete.id), series=None).kind == "free_ride"
    store.save_events("renee", [_event(athlete.id)])
    assert build_analysis_context(store, "renee", _workout(athlete.id), series=None).kind == "race"
    # an event in another sport is not this workout's race
    assert build_analysis_context(store, "renee", _workout(athlete.id, "swim_pool"), series=None).kind == "free_ride"


def test_matched_training_session_keeps_its_own_kind_on_an_event_day(athletes_dir: Path) -> None:
    store = FileStore(base_dir=athletes_dir)
    athlete = store.load_athlete("renee")
    store.save_events("renee", [_event(athlete.id)])
    ctx = build_analysis_context(
        store, "renee", _workout(athlete.id), series=None, session=_session(athlete.id, "tempo", kind="workout")
    )
    assert ctx.kind == "workout"


def test_override_wins_in_the_context(athletes_dir: Path) -> None:
    store = FileStore(base_dir=athletes_dir)
    athlete = store.load_athlete("renee")
    w = _workout(athlete.id)
    w.kind_override = "warmup"
    assert build_analysis_context(store, "renee", w, series=None).kind == "warmup"
    assert w.kind == "free_ride"
