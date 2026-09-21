"""Once preferences are in the coach's context, the TOOLS must let it write the plan
(Andrew, 2026-09-21: "let the coach write the plan instead of excuses"). Every input below
used to be rejected with a raw validation dump or a bare error; each is now accepted and
normalized WITH A NOTE, or degraded with a warning. Only what genuinely cannot be
represented is an error, and then the message says what to do instead."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from swim_coach.models import Event
from swim_coach.plan import scaffold_macro
from swim_coach.store import FileStore

from app.context import PERSONA_AND_RULES
from app.tools import build_tool_handlers

D = "2026-07-09"
WEEK = "2026-W28"


def _h(athletes_dir):
    store = FileStore(base_dir=athletes_dir)
    return store, build_tool_handlers(store, slug="renee", expert_mode=False)


def _add(h, **ov):
    return h["patch_week_plan"]({"iso_week": WEEK, "session_overrides": [{"date": D, "add": True, **ov}]})


# --- 1. a session is written whatever it is called, and with whatever detail was given ----------


@pytest.mark.parametrize(
    "said, saved",
    [("kettlebell", "strength"), ("weights", "strength"), ("yoga", "recovery"), ("mobility", "recovery"),
     ("run", "cross_train"), ("hike", "cross_train"), ("swim", "swim_pool"), ("open water", "swim_ow"),
     ("cycling", "bike"), ("strength", "strength")],
)
def test_add_accepts_the_word_the_athlete_used_for_the_sport(athletes_dir, said, saved) -> None:
    store, h = _h(athletes_dir)
    day = "2026-07-10" if saved == "swim_ow" else D  # the fixture week already has an open-water swim on D
    result = h["patch_week_plan"]({"iso_week": WEEK, "session_overrides": [
        {"date": day, "add": True, "sport": said, "duration_min": 30, "purpose": "what the athlete asked for"}]})
    assert "error" not in result, result
    assert any(s["sport"] == saved and s["date"] == day for s in result["sessions"])


def test_an_unrecognised_sport_becomes_cross_training_with_a_note(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    result = _add(h, sport="curling", duration_min=60, purpose="league night")
    assert "error" not in result
    assert any(s["sport"] == "cross_train" for s in result["sessions"] if s["date"] == D)
    assert any("curling" in w for w in result["planning_warnings"])


def test_a_missing_duration_or_purpose_gets_a_default_and_a_note_never_an_error(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    no_duration = _add(h, sport="strength", purpose="KB EMOM")
    assert "error" not in no_duration and any("duration" in w for w in no_duration["planning_warnings"])
    store2, h2 = _h(athletes_dir)
    no_purpose = _add(h2, sport="strength", duration_min=30, structure="10 min EMOM: 12 swings / 8 goblet squats")
    assert "error" not in no_purpose
    added = next(s for s in no_purpose["sessions"] if s["date"] == D and s["sport"] == "strength")
    assert "EMOM" in added["purpose"]


def test_a_sport_word_also_matches_the_existing_session_when_modifying(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    existing = next(s for s in store.load_week("renee", WEEK).sessions if s.sport == "strength")
    result = h["patch_week_plan"]({"iso_week": WEEK, "session_overrides": [
        {"date": existing.date.isoformat(), "sport": "kettlebell", "purpose": "kettlebell circuit"}]})
    assert "error" not in result, result


# --- 2. authoring a workout never dead-ends on the internal IR ------------------------------------


KB_GUESS = {"items": [{"kind": "step", "label": "KB EMOM", "duration_value": 600, "notes": "12 swings then 8 goblet squats"}]}


def test_invalid_structured_content_is_kept_as_text_when_prose_was_given(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    result = _add(h, sport="strength", duration_min=30, purpose="KB", structure="10 min EMOM: 12 swings / 8 goblet squats",
                  structured=KB_GUESS)
    assert "error" not in result
    added = next(s for s in result["sessions"] if s["date"] == D and s["sport"] == "strength")
    assert added["has_structured"] is False
    assert any("structured" in w for w in result["planning_warnings"])


def test_invalid_structured_content_alone_is_salvaged_into_readable_text(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    result = _add(h, sport="strength", duration_min=30, purpose="KB", structured=KB_GUESS)
    assert "error" not in result
    draft = h["patch_week_plan"]({"iso_week": WEEK, "session_overrides": [
        {"date": D, "add": True, "sport": "strength", "duration_min": 30, "purpose": "KB", "structured": KB_GUESS}]})
    h["patch_week_plan"]({"iso_week": WEEK, "confirm": True, "draft_id": draft["draft_id"]})
    saved = next(s for s in store.load_week("renee", WEEK).sessions if s.date.isoformat() == D and s.sport == "strength")
    assert "KB EMOM" in saved.structure and "goblet squats" in saved.structure and saved.structured is None


def test_unsalvageable_structured_content_gives_an_actionable_message_not_a_validation_dump(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    result = _add(h, sport="strength", duration_min=30, purpose="KB", structured={"foo": 1})
    assert "error" in result
    assert "`structure`" in result["error"] and "plain text" in result["error"]
    assert "validation error" not in result["error"].lower()


# --- 3. an equipment/style preference with no matching library template still writes the week ----------


def test_a_template_preference_with_no_match_falls_back_to_the_default_rotation_with_a_warning(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    result = h["replace_week_plan"]({"iso_week": "2026-W29", "template_preference": {"equipment_any": ["kettlebell"]}})
    assert "error" not in result, result
    assert result["sessions"]
    assert any("default rotation" in w for w in result["planning_warnings"])


# --- 4. a preference sent to the profile tool is remembered, not rejected -------------------------------


def test_unknown_profile_fields_are_saved_as_notes_never_an_error(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    result = h["update_athlete_profile"]({"preferred_name": "Bob", "strength_equipment": "kettlebells"})
    assert "error" not in result and len(result["saved_as_notes"]) == 2
    texts = [n.text for n in store.load_athlete("renee").notes]
    assert any("Bob" in t for t in texts) and any("kettlebells" in t for t in texts)


def test_known_and_unknown_profile_fields_can_be_mixed(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    result = h["update_athlete_profile"]({"ftp_watts": 260, "likes": "flat pedals"})
    assert result["updated"] is True and result["ftp_watts"] == 260 and len(result["saved_as_notes"]) == 1
    assert store.load_athlete("renee").ftp_watts == 260


def test_a_profile_call_with_nothing_usable_still_says_what_to_do(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    result = h["update_athlete_profile"]({"favourite": {"nested": "thing"}})
    assert "error" in result and "save_athlete_note" in result["error"]


# --- 5. an export that cannot be built says why, in words ------------------------------------------------


def test_zwo_export_of_a_session_the_athlete_described_in_their_own_words_explains_itself(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    h["update_athlete_profile"]({"sports": ["bike"], "ftp_watts": 250.0})
    athlete = store.load_athlete("renee")
    start = date.today() - timedelta(days=date.today().weekday()) - timedelta(weeks=1)
    event = Event(id=uuid.uuid4(), athlete_id=athlete.id, name="CX", event_date=start + timedelta(weeks=24),
                  target_metric="duration_min", distance_m=None, target_value=300.0, primary_sport="bike", priority="A")
    macro = scaffold_macro(athlete, event, start, current_weekly_volume_m=200, peak_weekly_volume_m=600)
    store.save_events("renee", [event])
    store.save_macro("renee", macro)
    h["set_weekly_template"]({"template": {"tue": [{"kind": "bike", "role": "hard", "structure": "3 x 8 min over/unders"}]}, "confirm": True})
    ws = next(b for b in macro.blocks if b.name in ("build", "peak", "base")).start_date + timedelta(weeks=1)
    y, w, _ = ws.isocalendar()
    week = h["create_week_plan"]({"iso_week": f"{y}-W{w:02d}"})
    sid = store.load_week("renee", f"{y}-W{w:02d}").sessions[0].id

    result = h["export_zwo_workout"]({"session_id": str(sid)})

    assert "error" in result and "own words" in result["error"]


# --- 6. a fueling product the catalog lacks can be supplied from its label -------------------------------


FUEL = {"duration_min": 240, "intensity_class": "steady", "access": {"kind": "none"}}


def test_a_custom_product_from_its_label_is_accepted(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    result = h["compute_fueling_plan"]({**FUEL, "custom_product": {"label": "Homemade rice cakes", "carb_g_per_serving": 22, "sodium_mg_per_serving": 150}})
    assert "error" not in result, result
    assert "rice cakes" in str(result).lower()


def test_an_unknown_product_key_points_at_custom_product_instead_of_a_dead_end(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    result = h["compute_fueling_plan"]({**FUEL, "product_key": "skratch"})
    assert "error" in result and "custom_product" in result["error"]


def test_a_custom_product_with_nonsense_numbers_is_a_clear_error(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    result = h["compute_fueling_plan"]({**FUEL, "custom_product": {"label": "x", "carb_g_per_serving": -5}})
    assert "carb_g_per_serving" in result["error"]


# --- 7. the prompt: a research gap never stops the coach writing what the athlete asked for --------------


def test_the_prompt_says_a_research_gap_never_stops_the_coach_writing_the_plan() -> None:
    text = " ".join(PERSONA_AND_RULES.split())
    assert "A research gap NEVER stops you writing" in text
    assert "coach judgment" in text.lower()


# --- 8. safety-critical: an injury is always recordable, whatever body part was named -----------------------


@pytest.mark.parametrize(
    "said, region",
    [("neck", "head_neck"), ("hamstring", "hip"), ("calf", "ankle_foot"), ("wrist", "elbow_wrist"),
     ("lower back", "back"), ("flu", "illness_systemic"), ("knee", "knee"), ("spleen", "other")],
)
def test_a_health_status_is_recorded_whatever_body_part_was_named(athletes_dir, said, region) -> None:
    store, h = _h(athletes_dir)
    result = h["record_health_status"]({"description": f"sore {said}", "restriction": "light_only",
                                        "source": "self_reported", "body_region": said})
    assert "error" not in result and result["logged"] is True
    saved = store.list_health_status("renee")[-1]
    assert saved.body_region == region and said in saved.description  # the athlete's own words are kept


def test_a_reworded_body_region_is_reported_back_so_the_coach_can_say_so(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    result = h["record_health_status"]({"description": "tight hamstring", "restriction": "none",
                                        "source": "self_reported", "body_region": "hamstring"})
    assert any("hamstring" in w for w in result["warnings"])


# --- 9. an event in a sport the engine cannot periodize is remembered, not refused --------------------------


def test_an_event_in_an_unsupported_sport_is_kept_as_a_note_with_a_clear_explanation(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    result = h["create_event"]({"name": "Trail 50k", "event_date": "2027-05-01", "priority": "B", "primary_sport": "run",
                                "target_metric": "duration_min", "target_value": 480})
    assert "error" not in result and result["created"] is False
    assert "Trail 50k" in result["saved_as_note"] and "swim or bike" in result["warnings"][0]
    assert any("Trail 50k" in n.text for n in store.load_athlete("renee").notes)
