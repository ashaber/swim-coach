"""The weekly template must never block a coach from WRITING a legitimate week (Andrew,
2026-09-21: "hard codes that block writing"). Any kind of session is accepted -- engine
content where the engine has it, the athlete's own text otherwise -- and anything unusual
is normalized WITH A NOTE instead of rejected. Only input that cannot be placed at all
(a non-weekday key, a slot with no kind) is an error."""

from __future__ import annotations

import sys
import uuid
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parent))

from swim_coach.models import Athlete  # noqa: E402
from swim_coach.plan import _template_week_sessions, template_normalization_notes  # noqa: E402

WS = date(2026, 9, 21)  # a Monday


def athlete(template) -> Athlete:
    return Athlete(id=uuid.uuid4(), slug="x", name="X", css_pace_s_per_100m=95.0, zones=None, constraints={},
                   pool_schedule=[], sports=["bike"], weekly_template=template)


def sessions(template, minutes=300.0):
    a = athlete(template)
    return _template_week_sessions(a, WS, minutes, 250.0), a


# --- any kind of session can be written -----------------------------------------------------


def test_a_swim_slot_is_written_with_the_athletes_own_text() -> None:
    out, _ = sessions({"thu": [{"kind": "swim", "duration_min": 45, "purpose": "technique drills, catch focus"}]})
    s = out[0]
    assert s.sport == "swim_pool" and s.duration_min == 45 and s.purpose == "technique drills, catch focus"


def test_open_water_swim_and_explicit_sport_are_honoured() -> None:
    out, _ = sessions({"sat": [{"kind": "open water swim", "duration_min": 60}], "sun": [{"kind": "row", "sport": "cross_train"}]})
    assert {s.sport for s in out} == {"swim_ow", "cross_train"}


def test_an_unknown_kind_becomes_a_generic_cross_training_session_never_an_error() -> None:
    out, _ = sessions({"wed": [{"kind": "hike", "label": "Bear Peak", "duration_min": 120}]})
    s = out[0]
    assert s.sport == "cross_train" and s.duration_min == 120 and "Bear Peak" in s.purpose


def test_kettlebell_and_weights_are_strength_and_carry_the_athletes_own_content() -> None:
    out, _ = sessions({"tue": [{"kind": "kettlebell", "purpose": "KB EMOM", "structure": "10 min EMOM: 12 swings / 8 goblet squats"}]})
    s = out[0]
    assert s.sport == "strength" and s.purpose == "KB EMOM"
    assert s.structure == "10 min EMOM: 12 swings / 8 goblet squats"


def test_slot_structure_replaces_engine_prose_on_a_bike_ride_without_leaving_stale_intervals() -> None:
    out, _ = sessions({"tue": [{"kind": "bike", "role": "hard", "structure": "3 x 8 min over/unders, 4 min easy"}]})
    s = out[0]
    assert s.structure == "3 x 8 min over/unders, 4 min easy" and s.structured is None


# --- unusual input is normalized WITH A NOTE, not rejected ---------------------------------------


def test_a_bike_slot_with_no_role_is_an_endurance_ride() -> None:
    a = athlete({"mon": [{"kind": "bike"}]})
    assert a.weekly_template["mon"][0]["role"] == "endurance"
    assert any("role" in n for n in template_normalization_notes(a.weekly_template))


@pytest.mark.parametrize("word", ["tempo", "intervals", "vo2", "threshold", "sweet spot"])
def test_hard_ride_words_map_to_hard(word) -> None:
    assert athlete({"mon": [{"kind": "bike", "role": word}]}).weekly_template["mon"][0]["role"] == "hard"


@pytest.mark.parametrize("word", ["easy", "z2", "long", "group", "social"])
def test_easy_ride_words_map_to_endurance(word) -> None:
    assert athlete({"mon": [{"kind": "bike", "role": word}]}).weekly_template["mon"][0]["role"] == "endurance"


def test_an_unknown_role_is_an_endurance_ride_with_a_note() -> None:
    a = athlete({"mon": [{"kind": "bike", "role": "medium"}]})
    assert a.weekly_template["mon"][0]["role"] == "endurance"
    assert any("medium" in n for n in template_normalization_notes(a.weekly_template))


def test_a_role_on_a_non_bike_slot_is_ignored_with_a_note() -> None:
    a = athlete({"mon": [{"kind": "yoga", "role": "hard"}]})
    assert "role" not in a.weekly_template["mon"][0]
    assert template_normalization_notes(a.weekly_template)


def test_overlong_text_is_truncated_with_a_note_not_rejected() -> None:
    a = athlete({"mon": [{"kind": "yoga", "label": "x" * 500, "purpose": "y" * 5000, "structure": "z" * 20000}]})
    slot = a.weekly_template["mon"][0]
    assert len(slot["label"]) == 200 and len(slot["purpose"]) == 1500 and len(slot["structure"]) == 6000
    note = " ".join(template_normalization_notes(a.weekly_template))
    assert "label truncated" in note and "purpose truncated" in note and "structure truncated" in note


def test_out_of_range_durations_are_clamped_with_a_note() -> None:
    a = athlete({"mon": [{"kind": "yoga", "duration_min": 2}], "tue": [{"kind": "bike", "role": "endurance", "duration_min": 5000}]})
    assert a.weekly_template["mon"][0]["duration_min"] == 5 and a.weekly_template["tue"][0]["duration_min"] == 900
    assert len(template_normalization_notes(a.weekly_template)) == 2


def test_an_invalid_sport_or_a_non_string_field_is_dropped_with_a_note() -> None:
    a = athlete({"mon": [{"kind": "hike", "sport": "flying", "purpose": 5}]})
    slot = a.weekly_template["mon"][0]
    assert "sport" not in slot and "purpose" not in slot
    note = " ".join(template_normalization_notes(a.weekly_template))
    assert "sport" in note and "purpose dropped" in note


def test_a_clean_template_has_no_notes() -> None:
    a = athlete({"tue": [{"kind": "bike", "role": "hard"}], "wed": [{"kind": "yoga"}]})
    assert template_normalization_notes(a.weekly_template) == []


# --- only what cannot be placed at all is an error --------------------------------------------


@pytest.mark.parametrize(
    "template",
    [{"someday": [{"kind": "yoga"}]}, {"mon": "yoga"}, {"mon": ["yoga"]}, {"mon": [{"label": "no kind"}]}, {"mon": [{"kind": ""}]}],
)
def test_only_unplaceable_input_is_rejected(template) -> None:
    with pytest.raises(ValidationError):
        athlete(template)
