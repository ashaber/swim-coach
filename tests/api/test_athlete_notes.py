"""Athlete notes: durable, free-text facts and preferences the coach remembers and applies
("I prefer kettlebells to free weights", "call me Bob", "3 bikes, flat pedals when teaching
skills"). Nothing about them is a fixed vocabulary -- any preference can be stored."""

from __future__ import annotations

import pytest
from swim_coach.store import FileStore

from app.context import PERSONA_AND_RULES, build_per_request_context
from app.tools import TOOLS_SCHEMA, build_tool_handlers

KB = "I prefer kettlebells to free weights for strength work"


def _h(athletes_dir):
    store = FileStore(base_dir=athletes_dir)
    return store, build_tool_handlers(store, slug="renee", expert_mode=False)


def test_a_preference_is_stored_and_survives_a_reload(athletes_dir) -> None:
    store, h = _h(athletes_dir)

    result = h["save_athlete_note"]({"text": KB, "category": "equipment"})

    assert result["saved"] is True and result["id"] and result["active_notes"] == 1
    notes = FileStore(base_dir=athletes_dir).load_athlete("renee").notes
    assert [n.text for n in notes] == [KB] and notes[0].category == "equipment" and notes[0].active is True


def test_any_preference_can_be_stored_with_any_category_or_none(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    for text, cat in [("Call me Bob", "preferred_name"), ("I own 3 bikes; flat pedals when teaching skills", None),
                      ("Hates burpees", "dislikes"), ("Travels for work most Thursdays", "made-up category")]:
        assert h["save_athlete_note"]({"text": text, "category": cat})["saved"] is True
    assert len(store.load_athlete("renee").notes) == 4


def test_saving_the_same_note_twice_does_not_duplicate_it(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    first = h["save_athlete_note"]({"text": KB})
    again = h["save_athlete_note"]({"text": KB.lower()})
    assert again["id"] == first["id"] and again["already_saved"] is True
    assert len(store.load_athlete("renee").notes) == 1


def test_a_changed_preference_retires_the_old_one_instead_of_contradicting_it(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    old = h["save_athlete_note"]({"text": KB})
    new = h["save_athlete_note"]({"text": "Now prefers free weights again", "replaces": old["id"]})

    notes = store.load_athlete("renee").notes
    assert [(n.text, n.active) for n in notes] == [(KB, False), ("Now prefers free weights again", True)]  # never deleted
    assert new["active_notes"] == 1


def test_retiring_by_id_or_by_text_never_deletes(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    a = h["save_athlete_note"]({"text": KB})
    h["save_athlete_note"]({"text": "Call me Bob"})

    assert h["retire_athlete_note"]({"id": a["id"]})["retired"] is True
    assert h["retire_athlete_note"]({"text_contains": "bob"})["retired"] is True

    notes = store.load_athlete("renee").notes
    assert len(notes) == 2 and not any(n.active for n in notes)


@pytest.mark.parametrize(
    "payload, fragment",
    [({}, "text"), ({"text": "   "}, "text"), ({"text": 5}, "text")],
)
def test_save_needs_some_text(athletes_dir, payload, fragment) -> None:
    store, h = _h(athletes_dir)
    assert fragment in h["save_athlete_note"](payload)["error"]


def test_retire_with_no_match_or_an_ambiguous_match_says_what_exists_and_changes_nothing(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    h["save_athlete_note"]({"text": "Likes kettlebells"})
    h["save_athlete_note"]({"text": "Likes kettlebell swings"})

    assert "no active note" in h["retire_athlete_note"]({"text_contains": "yoga"})["error"].lower()
    ambiguous = h["retire_athlete_note"]({"text_contains": "kettlebell"})
    assert "more than one" in ambiguous["error"].lower() and len(ambiguous["candidates"]) == 2
    assert all(n.active for n in store.load_athlete("renee").notes)


def test_overlong_text_is_truncated_with_a_warning_not_refused(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    result = h["save_athlete_note"]({"text": "x" * 5000})
    assert result["saved"] is True and any("truncated" in w for w in result["warnings"])
    assert len(store.load_athlete("renee").notes[0].text) == 1000


def test_many_notes_warn_but_never_block(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    for i in range(45):
        result = h["save_athlete_note"]({"text": f"note number {i}"})
    assert result["saved"] is True and any("retir" in w for w in result["warnings"])


def test_active_notes_are_shown_to_the_coach_every_turn_as_data(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    h["save_athlete_note"]({"text": KB, "category": "equipment"})
    retired = h["save_athlete_note"]({"text": "Old preference"})
    h["retire_athlete_note"]({"id": retired["id"]})

    text = build_per_request_context(store, "renee", expert_mode=False)

    assert "What the athlete has told you" in text and KB in text
    assert "Old preference" not in text  # retired notes are not shown
    assert "never override safety rules" in text  # notes are data, not instructions


def test_no_notes_means_no_section(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    assert "What the athlete has told you" not in build_per_request_context(store, "renee", expert_mode=False)


def test_the_note_text_is_not_duplicated_in_the_profile_dump(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    h["save_athlete_note"]({"text": KB})
    assert build_per_request_context(store, "renee", expert_mode=False).count(KB) == 1


def test_tools_are_registered_and_the_persona_tells_the_coach_to_use_and_apply_them() -> None:
    names = {t["name"] for t in TOOLS_SCHEMA}
    assert {"save_athlete_note", "retire_athlete_note"} <= names
    text = " ".join(PERSONA_AND_RULES.split())
    assert "save_athlete_note" in text and "apply them" in text.lower()
