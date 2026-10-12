"""`app.enrich.analysis_context`: what the analyzer is told about a ride beyond its stream
(LTHR, race flag from a RACE session or a same-day bike event, the plan's own wording)."""

from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path

from swim_coach.models import Event, Session
from swim_coach.store import FileStore

from app.enrich import analysis_context

DAY = date(2026, 9, 19)


def _session(athlete_id, purpose: str, structure: str | None = None) -> Session:
    return Session(
        id=uuid.uuid4(), athlete_id=athlete_id, date=DAY, sport="bike", source="ai_coach",
        duration_min=60.0, distance_m=0, intensity={"zone": "Z4"}, purpose=purpose, structure=structure,
    )


def test_race_session_purpose_marks_the_ride_a_race(athletes_dir: Path) -> None:
    store = FileStore(base_dir=athletes_dir)
    athlete_id = store.load_athlete("renee").id
    ctx = analysis_context(
        store, "renee", ride_date=DAY, sport="bike", lthr_bpm=172,
        session=_session(athlete_id, "RACE — cross opener", "barrier + remount"),
    )
    assert ctx == {"lthr_bpm": 172, "race": True, "session_text": "RACE — cross opener barrier + remount"}


def test_training_session_is_not_a_race_unless_an_event_is_that_day(athletes_dir: Path) -> None:
    store = FileStore(base_dir=athletes_dir)
    athlete = store.load_athlete("renee")
    ctx = analysis_context(
        store, "renee", ride_date=DAY, sport="bike", lthr_bpm=None, session=_session(athlete.id, "tempo")
    )
    assert ctx["race"] is False and ctx["lthr_bpm"] is None
    store.save_events(
        "renee",
        [Event(id=uuid.uuid4(), athlete_id=athlete.id, name="CX race", event_date=DAY,
               target_metric="duration_min", distance_m=None, target_value=45.0, primary_sport="bike", priority="B")],
    )
    assert analysis_context(store, "renee", ride_date=DAY, sport="bike", lthr_bpm=None, session=None)["race"] is True
    # a swim on the event's date is not the race
    assert analysis_context(store, "renee", ride_date=DAY, sport="swim", lthr_bpm=None, session=None)["race"] is False
