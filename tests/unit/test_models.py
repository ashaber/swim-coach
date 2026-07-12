"""Tests for swim_coach.models and swim_coach.store.

No LLM calls, no network access — pure pydantic validation and filesystem
round-trips against tmp_path.
"""

import uuid
from datetime import date, datetime, timezone

import pytest
import yaml
from pydantic import ValidationError

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
    WorkoutAnalytics,
    WorkoutLap,
    WorkoutLength,
    WorkoutPause,
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


def make_feedback(**overrides):
    data = dict(
        id=uuid.uuid4(),
        athlete_id=ATHLETE_ID,
        type="feature_request",
        source="athlete",
        body="Would love a swim-cap-color-coded interval clock.",
        context={},
        status="open",
        created_at=datetime(2026, 7, 7, 12, 0, 0, tzinfo=timezone.utc),
    )
    data.update(overrides)
    return Feedback(**data)


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


def test_workout_accepts_cross_train_sport():
    # non-swim logged activity (kayak, run, ride) imported from a .fit file
    workout = make_workout(sport="cross_train", distance_m=11494, duration_min=303.0)
    assert workout.sport == "cross_train"


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


# --- Feedback ---------------------------------------------------------------


def test_feedback_carries_schema_version_and_defaults():
    feedback = make_feedback()
    assert feedback.schema_version == 1
    assert feedback.status == "open"
    assert feedback.context == {}


def test_feedback_athlete_id_may_be_none():
    # A coach research question or general feedback may not be tied to a
    # specific athlete's row.
    feedback = make_feedback(athlete_id=None)
    assert feedback.athlete_id is None


def test_feedback_rejects_bad_type():
    with pytest.raises(ValidationError):
        make_feedback(type="not-a-real-type")


def test_feedback_rejects_bad_source():
    with pytest.raises(ValidationError):
        make_feedback(source="pool_coach")


def test_feedback_accepts_all_valid_types():
    for feedback_type in ("research_question", "feature_request", "comment", "bug"):
        feedback = make_feedback(type=feedback_type)
        assert feedback.type == feedback_type


def test_feedback_context_carries_arbitrary_dict():
    feedback = make_feedback(context={"topic": "taper", "expert_mode": True})
    assert feedback.context == {"topic": "taper", "expert_mode": True}


def test_feedback_round_trip_through_yaml():
    original = make_feedback()
    dumped = yaml.safe_dump(original.model_dump(mode="json"))
    loaded_data = yaml.safe_load(dumped)
    restored = Feedback.model_validate(loaded_data)
    assert restored == original
    assert isinstance(loaded_data["id"], str)


@pytest.mark.parametrize(
    "factory",
    [make_event, make_session, make_week, make_macro, make_workout, make_wellness],
)
def test_entities_carry_athlete_id_and_schema_version(factory):
    entity = factory()
    assert entity.athlete_id == ATHLETE_ID
    assert entity.schema_version == 1


# --- Workout analytics fields (additive, .fit workout-analytics Slice 1) ----


def test_workout_analytics_fields_default_empty():
    # Existing-style Workout YAML (manual/tcx/csv logs with none of these
    # keys) must keep validating unchanged -- additive, no schema_version bump.
    workout = make_workout()
    assert workout.avg_hr is None
    assert workout.max_hr is None
    assert workout.laps == []
    assert workout.lengths == []
    assert workout.pauses == []
    assert workout.analytics is None
    assert workout.series_ref is None


def test_workout_external_id_defaults_to_none():
    # Existing-style Workout YAML (manual/tcx/csv/fit logs predating the
    # intervals.icu sync job) carries no external_id key -- must keep
    # validating unchanged, no schema_version bump.
    workout = make_workout()
    assert workout.external_id is None


def test_workout_external_id_round_trip_through_yaml():
    workout = make_workout(source="fit", external_id="intervals:i132013445")
    dumped = yaml.safe_dump(workout.model_dump(mode="json"))
    loaded_data = yaml.safe_load(dumped)
    restored = Workout.model_validate(loaded_data)
    assert restored == workout
    assert restored.external_id == "intervals:i132013445"


def test_file_store_workout_external_id_round_trip(tmp_path):
    store = FileStore(base_dir=tmp_path)
    workout = make_workout(source="fit", external_id="intervals:i132013445")
    store.save_workout("wife", workout)
    loaded = store.list_workouts("wife")
    assert loaded == [workout]
    assert loaded[0].external_id == "intervals:i132013445"


def test_workout_lap_requires_only_index_and_duration():
    lap = WorkoutLap(index=0, duration_s=120.5)
    assert lap.start_offset_s is None
    assert lap.distance_m is None
    assert lap.avg_hr is None


def test_workout_length_swolf_and_defaults():
    length = WorkoutLength(index=0, duration_s=25.0, strokes=11, stroke="freestyle")
    assert length.swolf is None  # caller computes swolf, not the model
    assert length.lap_index is None


def test_workout_pause_rejects_bad_source():
    with pytest.raises(ValidationError):
        WorkoutPause(start_offset_s=10.0, duration_s=5.0, source="nap")


def test_workout_pause_accepts_all_sources():
    for source in ("timer", "gap", "idle_length"):
        pause = WorkoutPause(start_offset_s=0.0, duration_s=1.0, source=source)
        assert pause.source == source


def test_workout_analytics_split_label_rejects_bad_value():
    with pytest.raises(ValidationError):
        WorkoutAnalytics(split_label="sideways")


def test_workout_with_full_analytics_round_trip_through_yaml():
    workout = make_workout(
        avg_hr=132,
        max_hr=161,
        laps=[
            WorkoutLap(
                index=0,
                start_offset_s=0.0,
                duration_s=1800.0,
                distance_m=1500.0,
                avg_hr=130,
                max_hr=155,
                avg_pace_s_per_100m=120.0,
                stroke="freestyle",
                num_lengths=60,
            )
        ],
        lengths=[
            WorkoutLength(index=0, lap_index=0, duration_s=25.0, strokes=11, stroke="freestyle", swolf=36.0)
        ],
        pauses=[WorkoutPause(start_offset_s=900.0, duration_s=45.0, source="timer")],
        analytics=WorkoutAnalytics(
            cardiac_drift_pct=4.2,
            split_label="negative",
            first_half_pace_s_per_100m=121.0,
            second_half_pace_s_per_100m=119.0,
            elapsed_min=58.0,
            moving_min=57.2,
            pause_total_min=0.75,
            pause_count=1,
            swolf_first_quarter=35.0,
            swolf_last_quarter=38.0,
            swolf_degradation_pct=8.6,
        ),
        series_ref="athletes/wife/logs/series/2026-07-06-swim_pool-abcd1234.json",
    )
    dumped = yaml.safe_dump(workout.model_dump(mode="json"))
    loaded_data = yaml.safe_load(dumped)
    restored = Workout.model_validate(loaded_data)
    assert restored == workout


def test_file_store_workout_with_analytics_round_trip(tmp_path):
    store = FileStore(base_dir=tmp_path)
    workout = make_workout(
        avg_hr=140,
        laps=[WorkoutLap(index=0, duration_s=600.0)],
        analytics=WorkoutAnalytics(cardiac_drift_pct=3.1),
    )
    store.save_workout("wife", workout)
    loaded = store.list_workouts("wife")
    assert loaded == [workout]
    assert loaded[0].analytics.cardiac_drift_pct == 3.1


def test_athlete_carries_schema_version():
    athlete = make_athlete()
    assert athlete.schema_version == 1


def test_athlete_demographic_fields_default_to_none():
    # Existing-style profiles (Renee's, Andrew's) carry none of these keys --
    # must keep validating unchanged.
    athlete = make_athlete()
    assert athlete.dob is None
    assert athlete.sex is None
    assert athlete.height_cm is None
    assert athlete.weight_kg is None


def test_athlete_demographic_fields_round_trip_when_set():
    athlete = make_athlete(
        dob=date(1969, 3, 14),
        sex="female",
        height_cm=168.0,
        weight_kg=63.5,
    )
    assert athlete.dob == date(1969, 3, 14)
    assert athlete.sex == "female"
    assert athlete.height_cm == 168.0
    assert athlete.weight_kg == 63.5


def test_athlete_rejects_bad_sex():
    with pytest.raises(ValidationError):
        make_athlete(sex="nonbinary-typo")


def test_athlete_rejects_non_positive_height():
    with pytest.raises(ValidationError):
        make_athlete(height_cm=0)


def test_athlete_rejects_non_positive_weight():
    with pytest.raises(ValidationError):
        make_athlete(weight_kg=-5)


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


def test_file_store_athlete_round_trip_with_demographics(tmp_path):
    store = FileStore(base_dir=tmp_path)
    athlete = make_athlete(
        dob=date(1969, 3, 14), sex="female", height_cm=168.0, weight_kg=63.5
    )
    store.save_athlete(athlete)
    loaded = store.load_athlete("wife")
    assert loaded == athlete
    assert loaded.dob == date(1969, 3, 14)


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


# --- FileStore.save_series / save_raw_file (.fit workout-analytics Slice 1) --------


def test_file_store_save_series_writes_json(tmp_path):
    store = FileStore(base_dir=tmp_path)
    workout = make_workout()
    series = {"t_s": [0.0, 1.0, 2.0], "hr": [100, 101, 102]}
    ref = store.save_series("wife", workout.date, workout.sport, workout.id, series)
    expected_path = (
        tmp_path
        / "wife"
        / "logs"
        / "series"
        / f"2026-07-06-swim_pool-{str(workout.id)[:8]}.json"
    )
    assert expected_path.exists()
    assert ref == str(expected_path)
    import json

    assert json.loads(expected_path.read_text(encoding="utf-8")) == series


def test_file_store_save_raw_file_copies_into_files_dir(tmp_path):
    store = FileStore(base_dir=tmp_path)
    src = tmp_path / "incoming.fit"
    src.write_bytes(b"fake-fit-bytes")

    ref = store.save_raw_file("wife", src)
    expected_path = tmp_path / "wife" / "logs" / "files" / "incoming.fit"
    assert expected_path.exists()
    assert expected_path.read_bytes() == b"fake-fit-bytes"
    assert ref == str(expected_path)


def test_file_store_save_raw_file_is_noop_if_identical(tmp_path):
    store = FileStore(base_dir=tmp_path)
    src = tmp_path / "incoming.fit"
    src.write_bytes(b"fake-fit-bytes")

    ref1 = store.save_raw_file("wife", src)
    ref2 = store.save_raw_file("wife", src)
    assert ref1 == ref2


def test_file_store_save_raw_file_refuses_silent_overwrite_of_different_content(tmp_path):
    store = FileStore(base_dir=tmp_path)
    src1 = tmp_path / "incoming.fit"
    src1.write_bytes(b"version-one")
    store.save_raw_file("wife", src1)

    src2 = tmp_path / "other" / "incoming.fit"
    src2.parent.mkdir()
    src2.write_bytes(b"version-two-different-bytes")
    with pytest.raises(FileExistsError):
        store.save_raw_file("wife", src2)


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
