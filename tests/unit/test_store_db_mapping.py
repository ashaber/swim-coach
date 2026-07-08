"""Row<->model mapping round-trips for DbStore.

These test the PURE mapping functions in swim_coach.store_db -- no psycopg, no
connection. They assert two things per entity:
  1. round-trip: row_to_X(X_to_row(model)) == model
  2. promoted columns agree with the JSON payload (the columns are a
     denormalization of `data`, never a second source of truth).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from swim_coach.models import (
    Athlete,
    Event,
    Feedback,
    MacroBlock,
    MacroPlan,
    Session,
    Wellness,
    WeekPlan,
    Workout,
)
from swim_coach.store_db import (
    athlete_to_row,
    coach_text_storage_key,
    event_to_row,
    feedback_to_row,
    macro_to_row,
    row_to_athlete,
    row_to_event,
    row_to_feedback,
    row_to_macro,
    row_to_week,
    row_to_wellness,
    row_to_workout,
    week_to_row,
    wellness_to_row,
    workout_to_row,
)

AID = uuid.uuid4()


def _athlete() -> Athlete:
    return Athlete(
        id=AID,
        slug="renee",
        name="Renee Example",
        css_pace_s_per_100m=90.0,
        zones={"Z2": {"low": 96, "high": 102}},
        constraints={"pool_days": ["mon", "wed", "fri"]},
        pool_schedule=["mon", "wed", "fri"],
    )


def _event() -> Event:
    return Event(
        id=uuid.uuid4(),
        athlete_id=AID,
        name="UltraSwim 33.3",
        event_date=date(2026, 9, 18),
        distance_m=33300,
        water_temp_c=24.0,
        wetsuit=False,
        priority="A",
    )


def test_athlete_mapping_round_trip():
    a = _athlete()
    row = athlete_to_row(a)
    assert row["athlete_id"] == a.id
    assert row["slug"] == a.slug
    assert row["schema_version"] == a.schema_version
    assert row_to_athlete(row) == a


def test_event_mapping_round_trip():
    e = _event()
    row = event_to_row(e)
    assert row["id"] == e.id
    assert row["athlete_id"] == e.athlete_id
    assert row["event_date"] == e.event_date
    assert row_to_event(row) == e


def test_macro_mapping_round_trip():
    e = _event()
    m = MacroPlan(
        id=uuid.uuid4(),
        athlete_id=AID,
        event_id=e.id,
        blocks=[
            MacroBlock(
                name="base",
                start_date=date(2026, 7, 1),
                end_date=date(2026, 8, 1),
                weekly_volume_target_m=18000,
                focus="aerobic base",
            )
        ],
    )
    row = macro_to_row(m)
    assert row["athlete_id"] == m.athlete_id
    assert row["id"] == m.id
    assert row["event_id"] == m.event_id
    assert row_to_macro(row) == m


def test_week_mapping_round_trip_including_nested_sessions():
    session = Session(
        id=uuid.uuid4(),
        athlete_id=AID,
        date=date(2026, 7, 6),
        sport="swim_ow",
        source="ai_coach",
        duration_min=120.0,
        distance_m=6000,
        intensity={"zone": "Z2", "anchor": "css_pace"},
        purpose="long swim",
    )
    w = WeekPlan(
        id=uuid.uuid4(),
        athlete_id=AID,
        iso_week="2026-W28",
        meso_block="base",
        focus="aerobic base",
        target_volume_m=18000,
        sessions=[session],
    )
    row = week_to_row(w)
    assert row["id"] == w.id
    assert row["iso_week"] == w.iso_week
    restored = row_to_week(row)
    assert restored == w
    # nested sessions survive the JSON round-trip
    assert restored.sessions[0] == session


def test_workout_mapping_round_trip():
    w = Workout(
        id=uuid.uuid4(),
        athlete_id=AID,
        date=date(2026, 7, 6),
        sport="swim_pool",
        source="manual",
        distance_m=4000,
        duration_min=75.0,
        rpe=6,
    )
    row = workout_to_row(w)
    assert row["id"] == w.id
    assert row["date"] == w.date
    assert row["sport"] == w.sport
    assert row_to_workout(row) == w


def test_wellness_mapping_round_trip():
    w = Wellness(
        id=uuid.uuid4(),
        athlete_id=AID,
        date=date(2026, 7, 6),
        sleep_quality=4,
        sleep_hours=7.5,
        stress=2,
        soreness=2,
        motivation=4,
    )
    row = wellness_to_row(w)
    assert row["id"] == w.id
    assert row["date"] == w.date
    assert row_to_wellness(row) == w


def _feedback(**overrides) -> Feedback:
    data: dict = dict(
        id=uuid.uuid4(),
        athlete_id=AID,
        type="feature_request",
        source="athlete",
        body="add a pace calculator",
        context={"screen": "log"},
        status="open",
        created_at=datetime(2026, 7, 7, 12, 0, 0, tzinfo=timezone.utc),
    )
    data.update(overrides)
    return Feedback(**data)


def test_feedback_mapping_round_trip():
    f = _feedback()
    row = feedback_to_row(f)
    assert row["id"] == f.id
    assert row["athlete_id"] == f.athlete_id
    assert row["type"] == f.type
    assert row["source"] == f.source
    assert row["body"] == f.body
    assert row["context"] == f.context
    assert row["status"] == f.status
    assert row["created_at"] == f.created_at
    assert row_to_feedback(row) == f


def test_feedback_mapping_round_trip_with_null_athlete_id():
    f = _feedback(athlete_id=None, type="research_question", source="coach")
    row = feedback_to_row(f)
    assert row["athlete_id"] is None
    assert row_to_feedback(row) == f


def test_coach_text_storage_key_shape():
    key = coach_text_storage_key("renee", date(2026, 7, 6))
    assert key == "db://coach_texts/renee/2026-07-06"


def test_data_column_is_json_serializable_primitives():
    # `data` must be pure JSON types (str/int/float/list/dict/None) so it can
    # go straight into a JSONB column -- no UUID/date objects lurking inside.
    row = athlete_to_row(_athlete())
    assert isinstance(row["data"], dict)
    assert isinstance(row["data"]["id"], str)  # UUID serialized to str
    event_row = event_to_row(_event())
    assert isinstance(event_row["data"]["event_date"], str)  # date serialized to str
