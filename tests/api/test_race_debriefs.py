"""Race debriefs: durable post-race (or post-key-session) interview history (see RaceDebrief /
save_race_debrief). Andrew, 2026-09-22: reading a transcript from a second coaching tool whose
plan was visibly better-targeted off exactly this kind of interview -- the conclusion gets written
down once and read back on every later planning turn, instead of re-derived from raw logs."""

from __future__ import annotations

from swim_coach.store import FileStore

from app.context import PERSONA_AND_RULES, build_per_request_context
from app.tools import TOOLS_SCHEMA, build_tool_handlers


def _h(athletes_dir):
    store = FileStore(base_dir=athletes_dir)
    return store, build_tool_handlers(store, slug="renee", expert_mode=False)


def test_a_debrief_is_saved_and_survives_a_reload(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    result = h["save_race_debrief"]({
        "event_name": "Wafflecross",
        "event_date": "2026-09-19",
        "result": "3rd, 26s back",
        "went_well": "Held pace, no fade",
        "work_on": "The start -- lost time in lap 1 traffic",
        "data_findings": ["lap 1 cost 22 of the 26s gap", "laps 2-5 flat, no real fade"],
        "training_implication": "add short start-reps into the existing Saturday hard day",
        "tactical_note": "stage further forward if allowed, proposal only",
    })
    assert result["saved"] is True and result["id"] and result["warnings"] == []

    debriefs = FileStore(base_dir=athletes_dir).load_athlete("renee").race_debriefs
    assert len(debriefs) == 1
    d = debriefs[0]
    assert d.event_name == "Wafflecross" and d.event_date.isoformat() == "2026-09-19"
    assert d.went_well and d.work_on and d.training_implication and d.tactical_note
    assert d.data_findings == ["lap 1 cost 22 of the 26s gap", "laps 2-5 flat, no real fade"]


def test_only_event_name_and_date_are_required_everything_else_is_optional(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    result = h["save_race_debrief"]({"event_name": "Warm Lake Fall Breeze 3K", "event_date": "2026-09-26"})
    assert result["saved"] is True
    d = store.load_athlete("renee").race_debriefs[0]
    assert d.went_well is None and d.work_on is None and d.data_findings == []


def test_missing_event_name_or_bad_date_is_a_clear_error_not_a_crash(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    missing_name = h["save_race_debrief"]({"event_date": "2026-09-19"})
    assert "error" in missing_name and "event_name" in missing_name["error"]

    bad_date = h["save_race_debrief"]({"event_name": "Wafflecross", "event_date": "not-a-date"})
    assert "error" in bad_date and "event_date" in bad_date["error"]
    assert store.load_athlete("renee").race_debriefs == []


def test_a_bad_event_id_does_not_block_the_save_it_just_warns(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    result = h["save_race_debrief"]({
        "event_name": "Wafflecross", "event_date": "2026-09-19", "event_id": "not-a-uuid",
    })
    assert result["saved"] is True and any("event_id" in w for w in result["warnings"])
    assert store.load_athlete("renee").race_debriefs[0].event_id is None


def test_over_long_text_is_truncated_with_a_warning_never_an_error(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    result = h["save_race_debrief"]({
        "event_name": "Wafflecross", "event_date": "2026-09-19",
        "went_well": "x" * 5000,
        "data_findings": [f"finding {i}" for i in range(20)],
    })
    assert result["saved"] is True
    assert any("went_well" in w for w in result["warnings"])
    assert any("data_findings" in w for w in result["warnings"])
    d = store.load_athlete("renee").race_debriefs[0]
    assert len(d.went_well) == 2000 and len(d.data_findings) == 12


def test_get_race_debriefs_reads_back_most_recent_first(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    h["save_race_debrief"]({"event_name": "Wafflecross", "event_date": "2026-09-19"})
    h["save_race_debrief"]({"event_name": "Warm Lake Fall Breeze 3K", "event_date": "2026-09-26"})

    result = h["get_race_debriefs"]({})
    assert result["total"] == 2
    assert [d["event_name"] for d in result["debriefs"]] == ["Warm Lake Fall Breeze 3K", "Wafflecross"]


def test_get_race_debriefs_respects_limit(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    for i in range(3):
        h["save_race_debrief"]({"event_name": f"Race {i}", "event_date": f"2026-09-{10 + i}"})
    assert len(h["get_race_debriefs"]({"limit": 1})["debriefs"]) == 1


def test_recent_debriefs_are_shown_to_the_coach_every_turn_as_data(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    h["save_race_debrief"]({
        "event_name": "Wafflecross", "event_date": "2026-09-19",
        "went_well": "Held pace, no fade", "work_on": "The start",
        "training_implication": "add short start-reps into the existing Saturday hard day",
        "tactical_note": "stage further forward if allowed",
    })
    text = build_per_request_context(store, "renee", expert_mode=False)
    assert "Recent race-debrief history" in text
    assert "Held pace, no fade" in text and "add short start-reps" in text
    assert "proposal the athlete still has to confirm" in text  # tactical vs training split is stated, not implied


def test_only_the_two_most_recent_debriefs_render_older_ones_are_counted_not_dumped(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    for i in range(3):
        h["save_race_debrief"]({"event_name": f"Race {i}", "event_date": f"2026-08-0{i + 1}"})
    text = build_per_request_context(store, "renee", expert_mode=False)
    assert "Race 2" in text and "Race 1" in text  # the two most recent
    assert "Race 0" not in text
    assert "1 older debrief" in text


def test_the_debrief_text_is_not_duplicated_in_the_profile_dump(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    h["save_race_debrief"]({"event_name": "Wafflecross", "event_date": "2026-09-19", "went_well": "Held pace, no fade"})
    assert build_per_request_context(store, "renee", expert_mode=False).count("Held pace, no fade") == 1


def test_no_debriefs_means_no_section(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    assert "Recent race-debrief history" not in build_per_request_context(store, "renee", expert_mode=False)


def test_tools_are_registered_and_the_persona_describes_the_interview_protocol() -> None:
    names = {t["name"] for t in TOOLS_SCHEMA}
    assert {"save_race_debrief", "get_race_debriefs"} <= names
    text = " ".join(PERSONA_AND_RULES.split())
    assert "save_race_debrief" in text
    assert "what did you do well" in text.lower() or "what went well" in text.lower()
    assert "what would you like to work on" in text.lower()
    assert "one new thing per turn" in text.lower() or "never a checklist" in text.lower()
