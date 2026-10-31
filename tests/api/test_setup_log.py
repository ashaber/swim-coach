"""Setup log: durable record of tires/pressure/clothing outcomes, temperature from the device."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from swim_coach.models import Athlete, SetupLogEntry, Workout
from swim_coach.store import FileStore

from app.context import PERSONA_AND_RULES, build_per_request_context
from app.router_triage import HAIKU_TOOL_ALLOWLIST
from app.save_claims import WRITE_TOOLS
from app.tools import TOOLS_SCHEMA, build_tool_handlers

DAY = date(2026, 10, 3)


def _h(athletes_dir):
    store = FileStore(base_dir=athletes_dir)
    return store, build_tool_handlers(store, slug="renee", expert_mode=False)


def _ride(store, *, lo=None, hi=None, detail="cycling/mountain", day=DAY) -> Workout:
    aid = store.load_athlete("renee").id
    w = Workout(
        id=uuid.uuid4(), athlete_id=aid, date=day, sport="cross_train", source="fit", distance_m=1000,
        duration_min=60.0, sport_detail=detail, min_temp_c=lo, max_temp_c=hi,
        avg_temp_c=None if lo is None else (lo + hi) / 2,
    )
    store.save_workout("renee", w)
    return w


def test_stated_fahrenheit_is_converted_by_the_engine(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    res = h["save_setup_note"]({"kind": "clothing", "text": "knee warmers and vest, perfect", "temp_f": 50,
                                "outcome": "worked", "date": DAY.isoformat()})
    assert res["saved"] is True
    e = store.load_athlete("renee").setup_log[0]
    assert (e.temp_c_low, e.temp_c_high, e.temp_source, e.outcome) == (10.0, 10.0, "athlete", "worked")


def test_device_temperature_fills_from_the_linked_workout(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    w = _ride(store, lo=8.0, hi=15.0)
    h["save_setup_note"]({"kind": "clothing", "text": "jacket, too warm by the end", "date": DAY.isoformat(),
                          "outcome": "too_hot"})
    e = store.load_athlete("renee").setup_log[0]
    assert (e.temp_c_low, e.temp_c_high, e.temp_source, e.workout_id) == (8.0, 15.0, "device", w.id)


def test_indoor_session_temperature_is_ignored(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    _ride(store, lo=21.0, hi=24.0, detail="cycling/indoor_cycling")
    res = h["save_setup_note"]({"kind": "tires", "text": "trainer tire", "date": DAY.isoformat()})
    assert res["saved"] is True and "error" not in res
    e = store.load_athlete("renee").setup_log[0]
    assert e.temp_c_low is None and e.temp_source is None


def test_non_ride_session_with_a_temperature_is_ignored(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    aid = store.load_athlete("renee").id
    store.save_workout("renee", Workout(  # real row shape: Yoga, trainer null, 30C
        id=uuid.uuid4(), athlete_id=aid, date=DAY, sport="recovery", source="fit", distance_m=0, duration_min=30.0,
        sport_detail="training/yoga", min_temp_c=30.0, max_temp_c=30.0, avg_temp_c=30.0))
    h["save_setup_note"]({"kind": "clothing", "text": "jersey", "date": DAY.isoformat()})
    e = store.load_athlete("renee").setup_log[0]
    assert e.temp_c_low is None and e.temp_source is None


def test_nothing_available_saves_null_temperature_without_error(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    res = h["save_setup_note"]({"kind": "tires", "text": "ran 24 psi front, grippy", "pressure_front_psi": 24,
                                "pressure_rear_psi": 26, "conditions": "dry hardpack", "date": DAY.isoformat()})
    assert res["saved"] is True and "error" not in res
    e = store.load_athlete("renee").setup_log[0]
    assert e.temp_c_low is None and e.temp_c_high is None and e.temp_source is None
    assert e.outcome == "unknown" and e.pressure_front_psi == 24 and e.conditions == "dry hardpack"


def test_text_is_required_and_kind_validated(athletes_dir) -> None:
    _, h = _h(athletes_dir)
    assert "error" in h["save_setup_note"]({"kind": "clothing"})
    assert "error" in h["save_setup_note"]({"kind": "hat", "text": "x"})


def _seed_log(store) -> None:
    a = store.load_athlete("renee")
    def mk(d, kind, lo, hi, text):
        return SetupLogEntry(id=uuid.uuid4(), date=d, kind=kind, text=text, temp_c_low=lo, temp_c_high=hi,
                             temp_source=None if lo is None else "device")
    a.setup_log = [
        mk(date(2026, 3, 1), "clothing", 4.0, 9.0, "cold-march"),
        mk(date(2026, 6, 1), "clothing", 24.0, 30.0, "hot-june"),
        mk(date(2026, 4, 1), "clothing", 9.0, 14.0, "mild-april"),
        mk(date(2026, 4, 2), "tires", 9.0, 14.0, "tires-april"),
        mk(date(2026, 5, 1), "clothing", None, None, "no-temp"),
    ]
    store.save_athlete(a)


def test_lookup_window_overlap_and_newest_first(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    _seed_log(store)
    res = h["get_setup_log"]({"kind": "clothing", "temp_c": 12})  # window 7..17
    assert [e["text"] for e in res["entries"]] == ["mild-april", "cold-march"]  # 4-9 overlaps 7..17
    first = res["entries"][0]
    assert first["temp_f_low"] == pytest.approx(48.2) and first["temp_c_high"] == 14.0


def test_lookup_in_fahrenheit_and_unfiltered_cap(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    _seed_log(store)
    assert [e["text"] for e in h["get_setup_log"]({"temp_f": 80})["entries"]] == ["hot-june"]
    a = store.load_athlete("renee")
    a.setup_log += [SetupLogEntry(id=uuid.uuid4(), date=date(2025, 1, i + 1), kind="tires", text=f"t{i}")
                    for i in range(15)]
    store.save_athlete(a)
    assert len(h["get_setup_log"]({})["entries"]) == 10


def test_setup_log_is_not_in_the_per_request_context(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    _seed_log(store)
    text = build_per_request_context(store, "renee", expert_mode=False)
    assert "cold-march" not in text and "setup_log" not in text


def test_old_athlete_data_validates_with_empty_log(athletes_dir) -> None:
    athlete = FileStore(base_dir=athletes_dir).load_athlete("renee")  # on-disk profile has no setup_log key
    assert athlete.setup_log == []
    dumped = athlete.model_dump(mode="json")
    dumped.pop("setup_log")
    assert Athlete.model_validate(dumped).setup_log == []


def test_classification_matches_save_athlete_note(athletes_dir) -> None:
    assert WRITE_TOOLS["save_setup_note"] == WRITE_TOOLS["save_athlete_note"]
    assert "get_setup_log" in HAIKU_TOOL_ALLOWLIST
    names = {t["name"] for t in TOOLS_SCHEMA}
    assert {"save_setup_note", "get_setup_log"} <= names


def test_prompt_guidance_present_and_short() -> None:
    assert "get_setup_log" in PERSONA_AND_RULES and "save_setup_note" in PERSONA_AND_RULES
    assert "follow-up" in PERSONA_AND_RULES
