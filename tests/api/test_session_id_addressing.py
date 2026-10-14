"""Sessions are addressed by id; (date, sport) is only a fallback, rejected when a day holds two
same-sport sessions (a warm-up ride + the race)."""

from __future__ import annotations

from swim_coach.store import FileStore

from app.tools import build_tool_handlers

WEEK = "2026-W28"
DAY = "2026-07-10"

WARM = {"date": DAY, "sport": "bike", "add": True, "kind": "warmup", "duration_min": 30, "purpose": "Warm-up spin"}
RACE = {"date": DAY, "sport": "bike", "add": True, "kind": "race", "duration_min": 90, "purpose": "Road race"}


def _h(athletes_dir):
    store = FileStore(base_dir=athletes_dir)
    return store, build_tool_handlers(store, slug="renee", expert_mode=False)


def _race_day(athletes_dir):
    """The week persisted with a warm-up ride and a race ride on DAY; returns (store, handlers, warm, race)."""
    store, h = _h(athletes_dir)
    draft = h["patch_week_plan"]({"iso_week": WEEK, "session_overrides": [WARM, RACE]})
    assert "error" not in draft, draft
    done = h["patch_week_plan"]({"iso_week": WEEK, "confirm": True, "draft_id": draft["draft_id"]})
    assert done["persisted"] is True, done
    rides = [s for s in store.load_week("renee", WEEK).sessions if s.date.isoformat() == DAY and s.sport == "bike"]
    assert len(rides) == 2
    warm = next(s for s in rides if s.kind == "warmup")
    race = next(s for s in rides if s.kind == "race")
    return store, h, warm, race


def _bike_on_day(store):
    return {s.kind: s for s in store.load_week("renee", WEEK).sessions if s.date.isoformat() == DAY and s.sport == "bike"}


def test_a_second_same_sport_session_can_be_added_to_a_day(athletes_dir) -> None:
    store, _h2, warm, race = _race_day(athletes_dir)
    assert warm.duration_min == 30 and race.duration_min == 90 and warm.id != race.id


def test_patch_by_id_edits_only_that_session(athletes_dir) -> None:
    store, h, warm, race = _race_day(athletes_dir)
    draft = h["patch_week_plan"]({"iso_week": WEEK, "session_overrides": [{"session_id": str(race.id), "duration_min": 100}]})
    assert "error" not in draft, draft
    h["patch_week_plan"]({"iso_week": WEEK, "confirm": True, "draft_id": draft["draft_id"]})
    after = _bike_on_day(store)
    assert after["race"].duration_min == 100 and after["race"].id == race.id
    assert after["warmup"].duration_min == 30


def test_patch_by_short_id_prefix(athletes_dir) -> None:
    store, h, warm, _race = _race_day(athletes_dir)
    draft = h["patch_week_plan"]({"iso_week": WEEK, "session_overrides": [{"session_id": str(warm.id)[:8], "duration_min": 25}]})
    h["patch_week_plan"]({"iso_week": WEEK, "confirm": True, "draft_id": draft["draft_id"]})
    assert _bike_on_day(store)["warmup"].duration_min == 25


def test_date_and_sport_on_a_two_session_day_is_an_ambiguity_error(athletes_dir) -> None:
    store, h, warm, race = _race_day(athletes_dir)
    result = h["patch_week_plan"]({"iso_week": WEEK, "session_overrides": [{"date": DAY, "sport": "bike", "duration_min": 55}]})
    assert "error" in result
    assert str(warm.id)[:8] in result["error"] and str(race.id)[:8] in result["error"]
    assert "session_id" in result["error"]


def test_remove_by_id_removes_one(athletes_dir) -> None:
    store, h, warm, race = _race_day(athletes_dir)
    draft = h["patch_week_plan"]({"iso_week": WEEK, "session_overrides": [{"session_id": str(warm.id), "remove": True}]})
    assert "error" not in draft, draft
    h["patch_week_plan"]({"iso_week": WEEK, "confirm": True, "draft_id": draft["draft_id"]})
    assert list(_bike_on_day(store)) == ["race"]


def test_unknown_id_is_a_clear_error(athletes_dir) -> None:
    _store, h, _warm, _race = _race_day(athletes_dir)
    result = h["patch_week_plan"]({"iso_week": WEEK, "session_overrides": [{"session_id": "deadbeef", "duration_min": 5}]})
    assert "error" in result and "deadbeef" in result["error"]


def test_reschedule_by_id_moves_only_that_session(athletes_dir) -> None:
    store, h, warm, race = _race_day(athletes_dir)
    result = h["reschedule_session"]({"iso_week": WEEK, "session_id": str(warm.id), "new_date": "2026-07-09"})
    assert result.get("rescheduled") is True, result
    moved = next(s for s in store.load_week("renee", WEEK).sessions if s.id == warm.id)
    assert moved.date.isoformat() == "2026-07-09"
    assert next(s for s in store.load_week("renee", WEEK).sessions if s.id == race.id).date.isoformat() == DAY


def test_reschedule_by_date_sport_on_two_session_day_is_rejected(athletes_dir) -> None:
    _store, h, warm, race = _race_day(athletes_dir)
    result = h["reschedule_session"]({"iso_week": WEEK, "current_date": DAY, "sport": "bike", "new_date": "2026-07-09"})
    assert "error" in result and str(warm.id)[:8] in result["error"] and str(race.id)[:8] in result["error"]


def test_get_week_plan_by_session_id(athletes_dir) -> None:
    _store, h, _warm, race = _race_day(athletes_dir)
    result = h["get_week_plan"]({"iso_week": WEEK, "session_id": str(race.id)})
    assert [s["id"] for s in result["sessions"]] == [str(race.id)]


def test_get_week_plan_by_date_returns_every_session_that_day(athletes_dir) -> None:
    _store, h, _warm, _race = _race_day(athletes_dir)
    result = h["get_week_plan"]({"iso_week": WEEK, "session_date": DAY, "sport": "bike"})
    assert len(result["sessions"]) == 2


def test_propose_session_adjustment_by_id(athletes_dir) -> None:
    _store, h, _warm, race = _race_day(athletes_dir)
    result = h["propose_session_adjustment"](
        {"iso_week": WEEK, "session_id": str(race.id), "direction": "reduce", "reason": "tired"}
    )
    assert "error" not in result, result
    assert result["session"]["id"] == str(race.id)


def test_propose_session_adjustment_ambiguous_date_sport(athletes_dir) -> None:
    _store, h, warm, race = _race_day(athletes_dir)
    result = h["propose_session_adjustment"](
        {"iso_week": WEEK, "date": DAY, "sport": "bike", "direction": "reduce", "reason": "tired"}
    )
    assert "error" in result and str(warm.id)[:8] in result["error"]


def test_generator_still_keeps_one_session_per_sport_day_for_normal_weeks(athletes_dir) -> None:
    store, _h2 = _h(athletes_dir)
    sessions = store.load_week("renee", WEEK).sessions
    keys = [(s.date, s.sport) for s in sessions]
    assert len(keys) == len(set(keys))
