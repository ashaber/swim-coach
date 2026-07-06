"""Tests for swim_coach.models and swim_coach.store.

No LLM calls, no network access — pure pydantic validation and filesystem
round-trips against tmp_path.
"""

import uuid
from datetime import date

import pytest
import yaml
from pydantic import ValidationError

from swim_coach.models import (
    Athlete,
    Event,
    MacroBlock,
    MacroPlan,
    Session,
    Wellness,
    WeekPlan,
    Workout,
    WorkoutSet,
)
from swim_coach.store import FileStore

ATHLETE_ID = uuid.uuid4()


def make_athlete(**overrides):
    data = dict(
        id=ATHLETE_ID,
        slug="wife",
        name="Jane Doe",
        css_pace_s_per_100m=95.0,
        zones={"Z1": [105, 999]},
        constraints={"max_pool_days": 5},
        pool_schedule=["mon", "wed", {"day": "fri", "note": "masters"}],
    )
    data.update(overrides)
    return Athlete(**data)


def make_event(**overrides):
    data = dict(
        id=uuid.uuid4(),
        athlete_id=ATHLETE_ID,
        name="Catalina Channel",
        event_date=date(2026, 8, 15),
        distance_m=33000,
        water_temp_c=18.5,
        wetsuit=False,
        priority="A",
    )
    data.update(overrides)
    return Event(**data)


def make_session(**overrides):
    data = dict(
        id=uuid.uuid4(),
        athlete_id=ATHLETE_ID,
        date=date(2026, 7, 6),
        sport="swim_pool",
        source="pool_coach",
        duration_min=60.0,
        distance_m=3000,
        intensity={"zone": "Z2", "anchor": "css_pace"},
        purpose="aerobic base",
        structure="10x300 @ css+6",
        status="planned",
    )
    data.update(overrides)
    return Session(**data)


def make_week(**overrides):
    data = dict(
        id=uuid.uuid4(),
        athlete_id=ATHLETE_ID,
        iso_week="2026-W28",
        meso_block="base",
        focus="aerobic volume",
        target_volume_m=12000,
        sessions=[make_session()],
        adaptation_rationale=None,
        draft=False,
    )
    data.update(overrides)
    return WeekPlan(**data)


def make_macro(**overrides):
    data = dict(
        id=uuid.uuid4(),
        athlete_id=ATHLETE_ID,
        event_id=uuid.uuid4(),
        blocks=[
            MacroBlock(
                name="base",
                start_date=date(2026, 1, 5),
                end_date=date(2026, 3, 30),
                weekly_volume_target_m=15000,
                focus="aerobic base",
            )
        ],
    )
    data.update(overrides)
    return MacroPlan(**data)


def make_workout(**overrides):
    data = dict(
        id=uuid.uuid4(),
        athlete_id=ATHLETE_ID,
        date=date(2026, 7, 6),
        sport="swim_pool",
        source="manual",
        distance_m=3000,
        duration_min=58.0,
        avg_pace_s_per_100m=96.5,
        rpe=6,
        sets=[WorkoutSet(distance_m=300, reps=10, interval="5:00")],
        planned_session_id=None,
        raw_ref=None,
        notes="felt good",
    )
    data.update(overrides)
    return Workout(**data)


def make_wellness(**overrides):
    data = dict(
        id=uuid.uuid4(),
        athlete_id=ATHLETE_ID,
        date=date(2026, 7, 6),
        sleep_quality=4,
        sleep_hours=7.5,
        stress=2,
        soreness=2,
        motivation=4,
        resting_hr=52,
        hrv=65.0,
        notes=None,
    )
    data.update(overrides)
    return Wellness(**data)


# --- validation failure tests ---


def test_session_rejects_bad_zone():
    with pytest.raises(ValidationError):
        make_session(intensity={"zone": "Z9", "anchor": "css_pace"})


def test_session_rejects_bad_anchor():
    with pytest.raises(ValidationError):
        make_session(intensity={"zone": "Z2", "anchor": "power_meter"})


def test_session_rejects_bad_sport():
    with pytest.raises(ValidationError):
        make_session(sport="cycling")


def test_workout_rejects_rpe_out_of_range():
    with pytest.raises(ValidationError):
        make_workout(rpe=11)
    with pytest.raises(ValidationError):
        make_workout(rpe=0)


def test_workout_rejects_negative_distance():
    with pytest.raises(ValidationError):
        make_workout(distance_m=-100)


def test_event_rejects_negative_distance():
    with pytest.raises(ValidationError):
        make_event(distance_m=-1)


def test_event_rejects_bad_distance_type():
    with pytest.raises(ValidationError):
        make_event(distance_m="a lot")


def test_event_format_defaults_to_single_day():
    event = make_event()
    assert event.event_format == "single_day"


def test_event_format_accepts_multi_day_stage():
    event = make_event(event_format="multi_day_stage")
    assert event.event_format == "multi_day_stage"


def test_event_rejects_bad_event_format():
    with pytest.raises(ValidationError):
        make_event(event_format="two_day_sprint")


def test_event_format_omitted_from_dict_still_defaults():
    # Backward compatibility: a YAML file written before event_format existed
    # (no key at all) must still validate, defaulting to "single_day".
    data = dict(
        id=uuid.uuid4(),
        athlete_id=ATHLETE_ID,
        name="Legacy Event",
        event_date=date(2026, 8, 15),
        distance_m=10000,
        water_temp_c=18.0,
        wetsuit=False,
        priority="A",
    )
    event = Event(**data)
    assert event.event_format == "single_day"


def test_week_plan_rejects_bad_iso_week():
    with pytest.raises(ValidationError):
        make_week(iso_week="not-a-week")


def test_wellness_rejects_out_of_range_scale():
    with pytest.raises(ValidationError):
        make_wellness(sleep_quality=6)
    with pytest.raises(ValidationError):
        make_wellness(sleep_quality=0)


def test_macro_block_requires_known_name():
    with pytest.raises(ValidationError):
        MacroBlock(
            name="peak-shmeak",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 2, 1),
            weekly_volume_target_m=1000,
            focus="x",
        )


def test_session_status_default_is_planned():
    session = make_session()
    assert session.status == "planned"


def test_week_plan_draft_defaults_false():
    week = make_week()
    assert week.draft is False


# --- schema_version + athlete_id presence ---


@pytest.mark.parametrize(
    "factory",
    [make_event, make_session, make_week, make_macro, make_workout, make_wellness],
)
def test_entities_carry_athlete_id_and_schema_version(factory):
    entity = factory()
    assert entity.athlete_id == ATHLETE_ID
    assert entity.schema_version == 1


def test_athlete_carries_schema_version():
    athlete = make_athlete()
    assert athlete.schema_version == 1


# --- round-trip tests: model -> yaml -> model ---


@pytest.mark.parametrize(
    "factory",
    [
        make_athlete,
        make_event,
        make_session,
        make_week,
        make_macro,
        make_workout,
        make_wellness,
    ],
)
def test_round_trip_through_yaml(factory):
    original = factory()
    dumped = yaml.safe_dump(original.model_dump(mode="json"))
    loaded_data = yaml.safe_load(dumped)
    restored = type(original).model_validate(loaded_data)
    assert restored == original
    # UUIDs and dates must serialize as plain strings, not python objects
    assert isinstance(loaded_data["id"], str)


# --- FileStore tests ---


def test_file_store_athlete_round_trip(tmp_path):
    store = FileStore(base_dir=tmp_path)
    athlete = make_athlete()
    store.save_athlete(athlete)
    expected_path = tmp_path / "wife" / "profile.yaml"
    assert expected_path.exists()
    loaded = store.load_athlete("wife")
    assert loaded == athlete


def test_file_store_events_round_trip(tmp_path):
    store = FileStore(base_dir=tmp_path)
    store.save_athlete(make_athlete())
    events = [make_event(), make_event(name="Second Event")]
    store.save_events("wife", events)
    expected_path = tmp_path / "wife" / "events.yaml"
    assert expected_path.exists()
    loaded = store.load_events("wife")
    assert loaded == events


def test_file_store_macro_round_trip(tmp_path):
    store = FileStore(base_dir=tmp_path)
    macro = make_macro()
    store.save_macro("wife", macro)
    expected_path = tmp_path / "wife" / "plan" / "macro.yaml"
    assert expected_path.exists()
    loaded = store.load_macro("wife")
    assert loaded == macro


def test_file_store_week_round_trip(tmp_path):
    store = FileStore(base_dir=tmp_path)
    week = make_week()
    store.save_week("wife", week)
    expected_path = tmp_path / "wife" / "plan" / "weeks" / "2026-W28.yaml"
    assert expected_path.exists()
    loaded = store.load_week("wife", "2026-W28")
    assert loaded == week


def test_file_store_workout_round_trip(tmp_path):
    store = FileStore(base_dir=tmp_path)
    workout = make_workout()
    store.save_workout("wife", workout)
    expected_path = (
        tmp_path
        / "wife"
        / "logs"
        / "workouts"
        / f"2026-07-06-swim_pool-{str(workout.id)[:8]}.yaml"
    )
    assert expected_path.exists()
    loaded = store.list_workouts("wife")
    assert loaded == [workout]


def test_file_store_wellness_round_trip(tmp_path):
    store = FileStore(base_dir=tmp_path)
    wellness = make_wellness()
    store.save_wellness("wife", wellness)
    expected_path = tmp_path / "wife" / "logs" / "wellness" / "2026-07-06.yaml"
    assert expected_path.exists()
    loaded = store.list_wellness("wife")
    assert loaded == [wellness]


def test_file_store_two_same_sport_same_date_workouts_both_persist(tmp_path):
    # Double pool days: two swim_pool workouts logged on the same date must
    # not overwrite each other. Filename includes the first 8 chars of the
    # workout id precisely to disambiguate this case.
    store = FileStore(base_dir=tmp_path)
    morning = make_workout(notes="morning session")
    afternoon = make_workout(id=uuid.uuid4(), notes="afternoon session")
    store.save_workout("wife", morning)
    store.save_workout("wife", afternoon)
    directory = tmp_path / "wife" / "logs" / "workouts"
    yaml_files = sorted(p.name for p in directory.glob("*.yaml"))
    assert yaml_files == sorted(
        [
            f"2026-07-06-swim_pool-{str(morning.id)[:8]}.yaml",
            f"2026-07-06-swim_pool-{str(afternoon.id)[:8]}.yaml",
        ]
    )
    loaded = store.list_workouts("wife")
    assert len(loaded) == 2
    assert {w.notes for w in loaded} == {"morning session", "afternoon session"}


def test_file_store_resaving_same_workout_id_overwrites_its_own_file(tmp_path):
    # Idempotence: re-saving a workout with the same id overwrites only that
    # workout's own file (not a sibling same-day/same-sport workout) — this
    # is desired behavior, e.g. correcting a logged workout's notes/rpe.
    store = FileStore(base_dir=tmp_path)
    workout = make_workout(notes="first pass", rpe=5)
    store.save_workout("wife", workout)
    corrected = make_workout(id=workout.id, notes="corrected", rpe=6)
    store.save_workout("wife", corrected)
    directory = tmp_path / "wife" / "logs" / "workouts"
    yaml_files = list(directory.glob("*.yaml"))
    assert len(yaml_files) == 1
    loaded = store.list_workouts("wife")
    assert len(loaded) == 1
    assert loaded[0].notes == "corrected"
    assert loaded[0].rpe == 6


def test_file_store_load_missing_athlete_raises(tmp_path):
    store = FileStore(base_dir=tmp_path)
    with pytest.raises(FileNotFoundError):
        store.load_athlete("nobody")


def test_file_store_load_missing_week_returns_none(tmp_path):
    store = FileStore(base_dir=tmp_path)
    store.save_athlete(make_athlete())
    assert store.load_week("wife", "2099-W01") is None


def test_file_store_load_missing_macro_returns_none(tmp_path):
    store = FileStore(base_dir=tmp_path)
    store.save_athlete(make_athlete())
    assert store.load_macro("wife") is None
