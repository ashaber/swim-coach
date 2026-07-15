"""Reusable StoreInterface contract suite.

`StoreContractTests` is a mixin base (its name does NOT start with `Test`, so
pytest does not collect it directly). Concrete test classes subclass it and
supply a `store` fixture returning a fresh, empty StoreInterface:

    class TestFileStoreContract(StoreContractTests):
        @pytest.fixture
        def store(self, tmp_path):
            return FileStore(base_dir=tmp_path)

The SAME suite runs against FileStore (tests/unit, always) and DbStore
(tests/integration, gated on a real throwaway DB) -- proving both backends
honor identical semantics.

The `store` fixture must arrive EMPTY. `save_*` on child entities may require
the athlete row to exist first (DbStore enforces the athlete FK); every test
here saves the athlete before its children, so that requirement is satisfied.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

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

SLUG = "renee"


def _athlete() -> Athlete:
    return Athlete(
        id=uuid.uuid4(),
        slug=SLUG,
        name="Renee Example",
        css_pace_s_per_100m=90.0,
        zones={"Z2": {"low_s_per_100m": 96, "high_s_per_100m": 102}},
        constraints={"pool_days": ["mon", "wed", "fri"]},
        pool_schedule=["mon", "wed", "fri"],
    )


def _event(athlete_id: uuid.UUID) -> Event:
    return Event(
        id=uuid.uuid4(),
        athlete_id=athlete_id,
        name="UltraSwim 33.3 Greece",
        event_date=date(2026, 9, 18),
        distance_m=33300,
        water_temp_c=24.0,
        wetsuit=False,
        priority="A",
        event_format="single_day",
    )


def _macro(athlete_id: uuid.UUID, event_id: uuid.UUID) -> MacroPlan:
    return MacroPlan(
        id=uuid.uuid4(),
        athlete_id=athlete_id,
        event_id=event_id,
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


def _session(athlete_id: uuid.UUID, d: date) -> Session:
    return Session(
        id=uuid.uuid4(),
        athlete_id=athlete_id,
        date=d,
        sport="swim_ow",
        source="ai_coach",
        duration_min=120.0,
        distance_m=6000,
        intensity={"zone": "Z2", "anchor": "css_pace"},
        purpose="long swim",
    )


def _week(athlete_id: uuid.UUID, iso_week: str) -> WeekPlan:
    return WeekPlan(
        id=uuid.uuid4(),
        athlete_id=athlete_id,
        iso_week=iso_week,
        meso_block="base",
        focus="aerobic base",
        target_volume_m=18000,
        sessions=[_session(athlete_id, date(2026, 7, 6))],
    )


def _workout(athlete_id: uuid.UUID, d: date, sport: str = "swim_pool") -> Workout:
    return Workout(
        id=uuid.uuid4(),
        athlete_id=athlete_id,
        date=d,
        sport=sport,
        source="manual",
        distance_m=4000,
        duration_min=75.0,
        rpe=6,
    )


def _feedback(athlete_id: uuid.UUID | None, **overrides) -> Feedback:
    data: dict = dict(
        id=uuid.uuid4(),
        athlete_id=athlete_id,
        type="feature_request",
        source="athlete",
        body="Would love a swim-cap-color-coded interval clock.",
        context={},
        status="open",
        created_at=datetime.now(timezone.utc),
    )
    data.update(overrides)
    return Feedback(**data)


def _wellness(athlete_id: uuid.UUID, d: date) -> Wellness:
    return Wellness(
        id=uuid.uuid4(),
        athlete_id=athlete_id,
        date=d,
        sleep_quality=4,
        sleep_hours=7.5,
        stress=2,
        soreness=2,
        motivation=4,
    )


class StoreContractTests:
    """Behaviors every StoreInterface implementation must honor."""

    # --- athlete ---------------------------------------------------------

    def test_athlete_round_trip(self, store):
        athlete = _athlete()
        store.save_athlete(athlete)
        loaded = store.load_athlete(SLUG)
        assert loaded == athlete

    def test_load_missing_athlete_raises(self, store):
        with pytest.raises(FileNotFoundError):
            store.load_athlete("nobody")

    def test_save_athlete_is_idempotent_upsert(self, store):
        athlete = _athlete()
        store.save_athlete(athlete)
        updated = athlete.model_copy(update={"name": "Renee Updated"})
        store.save_athlete(updated)
        loaded = store.load_athlete(SLUG)
        assert loaded.name == "Renee Updated"
        assert loaded.id == athlete.id

    # --- events ----------------------------------------------------------

    def test_events_round_trip(self, store):
        athlete = _athlete()
        store.save_athlete(athlete)
        events = [_event(athlete.id), _event(athlete.id)]
        store.save_events(SLUG, events)
        loaded = store.load_events(SLUG)
        assert {e.id for e in loaded} == {e.id for e in events}
        assert len(loaded) == 2

    def test_load_events_empty_when_none(self, store):
        store.save_athlete(_athlete())
        assert store.load_events(SLUG) == []

    def test_save_events_replaces_whole_set(self, store):
        athlete = _athlete()
        store.save_athlete(athlete)
        first = [_event(athlete.id), _event(athlete.id)]
        store.save_events(SLUG, first)
        replacement = [_event(athlete.id)]
        store.save_events(SLUG, replacement)
        loaded = store.load_events(SLUG)
        assert {e.id for e in loaded} == {e.id for e in replacement}

    # --- macro -----------------------------------------------------------

    def test_macro_round_trip(self, store):
        athlete = _athlete()
        store.save_athlete(athlete)
        event = _event(athlete.id)
        macro = _macro(athlete.id, event.id)
        store.save_macro(SLUG, macro)
        assert store.load_macro(SLUG) == macro

    def test_load_macro_none_when_absent(self, store):
        store.save_athlete(_athlete())
        assert store.load_macro(SLUG) is None

    def test_save_macro_is_upsert(self, store):
        athlete = _athlete()
        store.save_athlete(athlete)
        event = _event(athlete.id)
        macro = _macro(athlete.id, event.id)
        store.save_macro(SLUG, macro)
        macro2 = macro.model_copy(update={"blocks": []})
        store.save_macro(SLUG, macro2)
        assert store.load_macro(SLUG).blocks == []

    # --- weeks -----------------------------------------------------------

    def test_week_round_trip(self, store):
        athlete = _athlete()
        store.save_athlete(athlete)
        week = _week(athlete.id, "2026-W28")
        store.save_week(SLUG, week)
        assert store.load_week(SLUG, "2026-W28") == week

    def test_load_week_none_when_absent(self, store):
        store.save_athlete(_athlete())
        assert store.load_week(SLUG, "2026-W28") is None

    def test_save_week_is_upsert_per_iso_week(self, store):
        athlete = _athlete()
        store.save_athlete(athlete)
        week = _week(athlete.id, "2026-W28")
        store.save_week(SLUG, week)
        week2 = week.model_copy(update={"focus": "sharpen"})
        store.save_week(SLUG, week2)
        assert store.load_week(SLUG, "2026-W28").focus == "sharpen"
        # a different iso_week is a distinct row
        store.save_week(SLUG, _week(athlete.id, "2026-W29"))
        assert store.load_week(SLUG, "2026-W28") is not None
        assert store.load_week(SLUG, "2026-W29") is not None

    def test_list_week_ids_empty_when_none(self, store):
        store.save_athlete(_athlete())
        assert store.list_week_ids(SLUG) == []

    def test_list_week_ids_returns_saved_weeks_sorted(self, store):
        athlete = _athlete()
        store.save_athlete(athlete)
        # save out of order -- list_week_ids must return them chronologically
        store.save_week(SLUG, _week(athlete.id, "2026-W29"))
        store.save_week(SLUG, _week(athlete.id, "2026-W28"))
        assert store.list_week_ids(SLUG) == ["2026-W28", "2026-W29"]

    # --- workouts --------------------------------------------------------

    def test_workout_round_trip(self, store):
        athlete = _athlete()
        store.save_athlete(athlete)
        w = _workout(athlete.id, date(2026, 7, 6))
        store.save_workout(SLUG, w)
        loaded = store.list_workouts(SLUG)
        assert len(loaded) == 1
        assert loaded[0] == w

    def test_list_workouts_empty_when_none(self, store):
        store.save_athlete(_athlete())
        assert store.list_workouts(SLUG) == []

    def test_list_workouts_ordered_by_date(self, store):
        athlete = _athlete()
        store.save_athlete(athlete)
        days = [date(2026, 7, 6), date(2026, 7, 1), date(2026, 7, 4)]
        for d in days:
            store.save_workout(SLUG, _workout(athlete.id, d))
        loaded = store.list_workouts(SLUG)
        assert [w.date for w in loaded] == sorted(days)

    def test_same_id_workout_upserts(self, store):
        athlete = _athlete()
        store.save_athlete(athlete)
        w = _workout(athlete.id, date(2026, 7, 6))
        store.save_workout(SLUG, w)
        corrected = w.model_copy(update={"rpe": 9})
        store.save_workout(SLUG, corrected)
        loaded = store.list_workouts(SLUG)
        assert len(loaded) == 1
        assert loaded[0].rpe == 9

    def test_same_date_sport_different_id_coexist(self, store):
        athlete = _athlete()
        store.save_athlete(athlete)
        d = date(2026, 7, 6)
        store.save_workout(SLUG, _workout(athlete.id, d))
        store.save_workout(SLUG, _workout(athlete.id, d))
        assert len(store.list_workouts(SLUG)) == 2

    # --- wellness --------------------------------------------------------

    def test_wellness_round_trip(self, store):
        athlete = _athlete()
        store.save_athlete(athlete)
        w = _wellness(athlete.id, date(2026, 7, 6))
        store.save_wellness(SLUG, w)
        loaded = store.list_wellness(SLUG)
        assert len(loaded) == 1
        assert loaded[0] == w

    def test_list_wellness_empty_when_none(self, store):
        store.save_athlete(_athlete())
        assert store.list_wellness(SLUG) == []

    def test_list_wellness_ordered_by_date(self, store):
        athlete = _athlete()
        store.save_athlete(athlete)
        days = [date(2026, 7, 6), date(2026, 7, 1), date(2026, 7, 4)]
        for d in days:
            store.save_wellness(SLUG, _wellness(athlete.id, d))
        loaded = store.list_wellness(SLUG)
        assert [w.date for w in loaded] == sorted(days)

    def test_same_date_wellness_overwrites(self, store):
        athlete = _athlete()
        store.save_athlete(athlete)
        d = date(2026, 7, 6)
        store.save_wellness(SLUG, _wellness(athlete.id, d))
        second = _wellness(athlete.id, d).model_copy(update={"motivation": 1})
        store.save_wellness(SLUG, second)
        loaded = store.list_wellness(SLUG)
        assert len(loaded) == 1
        assert loaded[0].motivation == 1

    # --- feedback ----------------------------------------------------------

    def test_feedback_round_trip(self, store):
        athlete = _athlete()
        store.save_athlete(athlete)
        entry = _feedback(athlete.id, body="please add a pace calculator")
        store.save_feedback(entry)
        loaded = store.list_feedback(athlete=SLUG)
        assert len(loaded) == 1
        assert loaded[0] == entry

    def test_list_feedback_empty_when_none(self, store):
        store.save_athlete(_athlete())
        assert store.list_feedback(athlete=SLUG) == []

    def test_list_feedback_most_recent_first(self, store):
        athlete = _athlete()
        store.save_athlete(athlete)
        older = _feedback(
            athlete.id, body="older", created_at=datetime(2026, 7, 1, tzinfo=timezone.utc)
        )
        newer = _feedback(
            athlete.id, body="newer", created_at=datetime(2026, 7, 5, tzinfo=timezone.utc)
        )
        store.save_feedback(older)
        store.save_feedback(newer)
        loaded = store.list_feedback(athlete=SLUG)
        assert [f.body for f in loaded] == ["newer", "older"]

    def test_list_feedback_filters_by_athlete(self, store):
        athlete = _athlete()
        store.save_athlete(athlete)
        other = Athlete(id=uuid.uuid4(), slug="other-athlete", name="Other")
        store.save_athlete(other)
        store.save_feedback(_feedback(athlete.id, body="for renee"))
        store.save_feedback(_feedback(other.id, body="for other"))
        loaded = store.list_feedback(athlete=SLUG)
        assert [f.body for f in loaded] == ["for renee"]

    def test_list_feedback_respects_limit(self, store):
        athlete = _athlete()
        store.save_athlete(athlete)
        for i in range(3):
            store.save_feedback(
                _feedback(
                    athlete.id,
                    body=f"entry {i}",
                    created_at=datetime(2026, 7, 1 + i, tzinfo=timezone.utc),
                )
            )
        loaded = store.list_feedback(athlete=SLUG, limit=2)
        assert len(loaded) == 2
        assert loaded[0].body == "entry 2"

    def test_list_feedback_unknown_athlete_raises(self, store):
        with pytest.raises(FileNotFoundError):
            store.list_feedback(athlete="nobody")

    def test_save_feedback_allows_null_athlete_id(self, store):
        entry = _feedback(None, type="research_question", source="coach", body="taper research?")
        store.save_feedback(entry)
        loaded = store.list_feedback()
        assert any(f.id == entry.id for f in loaded)

    def test_get_feedback_returns_matching_entry(self, store):
        athlete = _athlete()
        store.save_athlete(athlete)
        entry = _feedback(athlete.id, body="please add a pace calculator")
        store.save_feedback(entry)
        found = store.get_feedback(entry.id)
        assert found == entry

    def test_get_feedback_returns_none_for_unknown_id(self, store):
        store.save_athlete(_athlete())
        assert store.get_feedback(uuid.uuid4()) is None

    def test_update_feedback_status_only(self, store):
        athlete = _athlete()
        store.save_athlete(athlete)
        entry = _feedback(athlete.id, body="mark this resolved", context={"topic": "taper"})
        store.save_feedback(entry)
        updated = store.update_feedback(entry.id, status="resolved")
        assert updated is not None
        assert updated.status == "resolved"
        assert updated.context == {"topic": "taper"}  # untouched
        assert store.get_feedback(entry.id).status == "resolved"

    def test_update_feedback_merges_context_without_clobbering(self, store):
        athlete = _athlete()
        store.save_athlete(athlete)
        entry = _feedback(athlete.id, body="taper question", context={"topic": "taper", "n": 1})
        store.save_feedback(entry)
        updated = store.update_feedback(
            entry.id, status="resolved", context={"n": 2, "resolution": "see 03-periodization.md"}
        )
        assert updated is not None
        assert updated.status == "resolved"
        # "topic" survives, "n" is overwritten, "resolution" is added.
        assert updated.context == {
            "topic": "taper",
            "n": 2,
            "resolution": "see 03-periodization.md",
        }

    def test_update_feedback_returns_none_for_unknown_id(self, store):
        store.save_athlete(_athlete())
        assert store.update_feedback(uuid.uuid4(), status="resolved") is None

    def test_update_feedback_does_not_disturb_other_entries(self, store):
        athlete = _athlete()
        store.save_athlete(athlete)
        keep = _feedback(athlete.id, body="leave me alone")
        target = _feedback(athlete.id, body="patch me")
        store.save_feedback(keep)
        store.save_feedback(target)
        store.update_feedback(target.id, status="resolved")
        untouched = store.get_feedback(keep.id)
        assert untouched == keep

    # --- coach texts -----------------------------------------------------

    def test_coach_text_save_and_exists(self, store):
        store.save_athlete(_athlete())
        day = date(2026, 7, 6)
        assert store.coach_text_exists(SLUG, day) is False
        key = store.save_coach_text(SLUG, day, "8x100 @ 1:30")
        assert isinstance(key, str) and key
        assert store.coach_text_exists(SLUG, day) is True

    def test_coach_text_raises_without_force(self, store):
        store.save_athlete(_athlete())
        day = date(2026, 7, 6)
        store.save_coach_text(SLUG, day, "original")
        with pytest.raises(FileExistsError):
            store.save_coach_text(SLUG, day, "clobber")

    def test_coach_text_force_overwrites(self, store):
        store.save_athlete(_athlete())
        day = date(2026, 7, 6)
        store.save_coach_text(SLUG, day, "original")
        key = store.save_coach_text(SLUG, day, "revised", force=True)
        assert isinstance(key, str) and key
        assert store.coach_text_exists(SLUG, day) is True

    def test_coach_text_distinct_days_independent(self, store):
        store.save_athlete(_athlete())
        d1 = date(2026, 7, 6)
        d2 = date(2026, 7, 7)
        store.save_coach_text(SLUG, d1, "monday")
        store.save_coach_text(SLUG, d2, "tuesday")
        assert store.coach_text_exists(SLUG, d1) is True
        assert store.coach_text_exists(SLUG, d2) is True

    # --- allowed_emails (Slice 1: verified identity) ----------------------

    def test_add_and_get_allowed_email(self, store):
        store.save_athlete(_athlete())
        entry = store.add_allowed_email(SLUG, "Renee@Example.COM", note="beta")
        assert entry.email == "renee@example.com"  # normalized
        assert entry.athlete_slug == SLUG
        assert entry.note == "beta"
        found = store.get_allowed_email("  Renee@Example.com ")
        assert found is not None
        assert found.email == "renee@example.com"
        assert found.created_at == entry.created_at

    def test_get_allowed_email_returns_none_when_absent(self, store):
        store.save_athlete(_athlete())
        assert store.get_allowed_email("nobody@example.com") is None

    def test_add_allowed_email_unknown_athlete_raises(self, store):
        with pytest.raises(FileNotFoundError):
            store.add_allowed_email("nobody", "someone@example.com")

    def test_add_allowed_email_upserts_by_normalized_email(self, store):
        store.save_athlete(_athlete())
        other = Athlete(id=uuid.uuid4(), slug="other-athlete", name="Other")
        store.save_athlete(other)

        first = store.add_allowed_email(SLUG, "person@example.com", note="first")
        second = store.add_allowed_email("other-athlete", "PERSON@example.com", note="second")

        assert second.athlete_slug == "other-athlete"
        assert second.note == "second"
        # created_at is preserved across the upsert, not reset
        assert second.created_at == first.created_at
        entries = store.list_allowed_emails()
        assert len(entries) == 1

    def test_list_allowed_emails_sorted_oldest_first(self, store):
        store.save_athlete(_athlete())
        store.add_allowed_email(SLUG, "b@example.com")
        store.add_allowed_email(SLUG, "a@example.com")
        entries = store.list_allowed_emails()
        assert [e.email for e in entries] == ["b@example.com", "a@example.com"]

    def test_list_allowed_emails_empty_when_none(self, store):
        store.save_athlete(_athlete())
        assert store.list_allowed_emails() == []

    def test_remove_allowed_email(self, store):
        store.save_athlete(_athlete())
        store.add_allowed_email(SLUG, "gone@example.com")
        assert store.remove_allowed_email("GONE@example.com") is True
        assert store.get_allowed_email("gone@example.com") is None
        assert store.list_allowed_emails() == []

    def test_remove_allowed_email_returns_false_when_absent(self, store):
        store.save_athlete(_athlete())
        assert store.remove_allowed_email("nobody@example.com") is False

    # --- sessions (Slice 1: verified identity) ----------------------------

    def test_create_and_get_session(self, store):
        store.save_athlete(_athlete())
        expires = datetime(2026, 8, 6, tzinfo=timezone.utc)
        created = store.create_session(SLUG, "hash-abc123", expires_at=expires)
        assert created.athlete_slug == SLUG
        assert created.expires_at == expires
        assert created.revoked_at is None

        found = store.get_session("hash-abc123")
        assert found is not None
        assert found.athlete_slug == SLUG
        assert found.expires_at == expires
        assert found.revoked_at is None

    def test_get_session_returns_none_when_absent(self, store):
        store.save_athlete(_athlete())
        assert store.get_session("no-such-hash") is None

    def test_create_session_unknown_athlete_raises(self, store):
        with pytest.raises(FileNotFoundError):
            store.create_session(
                "nobody", "hash-xyz", expires_at=datetime(2026, 8, 6, tzinfo=timezone.utc)
            )

    def test_revoke_session_marks_revoked(self, store):
        store.save_athlete(_athlete())
        store.create_session(
            SLUG, "hash-revoke-me", expires_at=datetime(2026, 8, 6, tzinfo=timezone.utc)
        )
        assert store.revoke_session("hash-revoke-me") is True
        found = store.get_session("hash-revoke-me")
        assert found is not None
        assert found.revoked_at is not None

    def test_revoke_session_returns_false_when_absent(self, store):
        store.save_athlete(_athlete())
        assert store.revoke_session("no-such-hash") is False

    def test_two_sessions_for_same_athlete_are_independent(self, store):
        store.save_athlete(_athlete())
        expires = datetime(2026, 8, 6, tzinfo=timezone.utc)
        store.create_session(SLUG, "hash-one", expires_at=expires)
        store.create_session(SLUG, "hash-two", expires_at=expires)
        store.revoke_session("hash-one")
        assert store.get_session("hash-one").revoked_at is not None
        assert store.get_session("hash-two").revoked_at is None
