"""Tests for swim_coach.ow_session_templates: the open-water session-content
template library (feed-window practice, negative-split pacing, chop/wind
adaptation, sighting, breathing-pattern variation, back-to-back stage
simulation, taper activation, race dress rehearsal).

No LLM calls, no network access -- pure arithmetic + model validation, same
convention as test_plan.py/test_workout_templates.py.
"""

from __future__ import annotations

import pytest

from swim_coach.models import WorkoutRepeat, WorkoutStep
from swim_coach.ow_session_templates import (
    BACK_TO_BACK_MIN_DURATION_MIN,
    BREATHING_PATTERN_MIN_DISTANCE_M,
    CHOP_WIND_MIN_DISTANCE_M,
    FEED_WINDOW_MIN_DURATION_MIN,
    NEG_SPLIT_MIN_DISTANCE_M,
    OW_SESSION_TEMPLATES,
    RACE_REHEARSAL_MIN_DURATION_MIN,
    SIGHTING_MIN_DISTANCE_M,
    TAPER_ACTIVATION_MAX_DISTANCE_M,
    build_back_to_back_stage_simulation_template,
    build_breathing_pattern_variation_template,
    build_chop_wind_adaptation_template,
    build_feed_window_practice_template,
    build_negative_split_ow_template,
    build_ow_session,
    build_race_dress_rehearsal_template,
    build_sighting_drill_template,
    build_taper_activation_template,
    list_ow_session_templates,
)

CSS_PACE_S = 90.0  # Renee's real CSS, used purely as a representative test value


def _total_distance(structured) -> int:
    """Sum every distance_m leaf across the structure (including inside
    repeats), same accounting `test_plan.py`'s sum-parity tests use."""
    total = 0

    def _walk(items):
        nonlocal total
        for item in items:
            if isinstance(item, WorkoutStep):
                if item.duration_kind == "distance_m" and item.duration_value:
                    total += item.duration_value
            elif isinstance(item, WorkoutRepeat):
                count = item.count or 1
                total += count * sum(
                    s.duration_value or 0
                    for s in item.steps
                    if isinstance(s, WorkoutStep) and s.duration_kind == "distance_m"
                )

    _walk(structured.items)
    return total


# --- feed-window practice ----------------------------------------------------


def test_feed_window_practice_sums_to_requested_distance():
    structured = build_feed_window_practice_template(6000, CSS_PACE_S)
    assert _total_distance(structured) == 6000


def test_feed_window_practice_has_feed_stop_rest_steps():
    structured = build_feed_window_practice_template(6000, CSS_PACE_S)
    repeat = next(item for item in structured.items if isinstance(item, WorkoutRepeat))
    rest_steps = [s for s in repeat.steps if s.role == "rest"]
    assert len(rest_steps) == 1
    assert rest_steps[0].duration_kind == "time_s"
    assert "feed stop" in rest_steps[0].label.lower()


def test_feed_window_practice_below_floor_raises():
    # At CSS_PACE_S=90s/100m, 1000m implies 15 min -- well under the floor.
    with pytest.raises(ValueError, match="feed-window practice"):
        build_feed_window_practice_template(1000, CSS_PACE_S)


def test_feed_window_practice_floor_constant_is_documented_and_positive():
    assert FEED_WINDOW_MIN_DURATION_MIN > 0


def test_feed_window_practice_no_persona_framing():
    structured = build_feed_window_practice_template(6000, CSS_PACE_S)
    prose = " ".join(
        s.label
        for item in structured.items
        for s in ([item] if isinstance(item, WorkoutStep) else item.steps)
    ).lower()
    for banned in ("dr.", "panel", "advisory", "boredom tolerance", "sensory-deprivation"):
        assert banned not in prose


# --- negative split -----------------------------------------------------------


def test_negative_split_sums_to_requested_distance():
    structured = build_negative_split_ow_template(4000, CSS_PACE_S)
    assert _total_distance(structured) == 4000


def test_negative_split_back_leg_faster_than_out_leg():
    structured = build_negative_split_ow_template(4000, CSS_PACE_S)
    steps = [item for item in structured.items if isinstance(item, WorkoutStep) and item.role == "interval"]
    assert len(steps) == 2
    out_step, back_step = steps
    assert out_step.target.zone == "Z2"
    assert back_step.target.zone == "Z3"


def test_negative_split_below_min_distance_raises():
    with pytest.raises(ValueError, match="negative-split"):
        build_negative_split_ow_template(NEG_SPLIT_MIN_DISTANCE_M - 200, CSS_PACE_S)


# --- chop / wind adaptation ----------------------------------------------------


def test_chop_wind_adaptation_sums_to_requested_distance():
    structured = build_chop_wind_adaptation_template(3000, CSS_PACE_S)
    assert _total_distance(structured) == 3000


def test_chop_wind_adaptation_below_min_distance_raises():
    with pytest.raises(ValueError, match="chop/wind"):
        build_chop_wind_adaptation_template(CHOP_WIND_MIN_DISTANCE_M - 200, CSS_PACE_S)


def test_chop_wind_adaptation_mentions_bilateral_breathing():
    structured = build_chop_wind_adaptation_template(3000, CSS_PACE_S)
    labels = " ".join(s.label for s in structured.items if isinstance(s, WorkoutStep)).lower()
    assert "bilateral" in labels


# --- sighting drill -------------------------------------------------------------


def test_sighting_drill_sums_to_requested_distance():
    structured = build_sighting_drill_template(2000, CSS_PACE_S)
    assert _total_distance(structured) == 2000


def test_sighting_drill_below_min_distance_raises():
    with pytest.raises(ValueError, match="sighting"):
        build_sighting_drill_template(SIGHTING_MIN_DISTANCE_M - 100, CSS_PACE_S)


def test_sighting_drill_has_no_eyes_closed_drift_step():
    # Deliberate safety-motivated deviation from the source idea -- see the
    # module docstring/registry source_note. Must never reappear.
    structured = build_sighting_drill_template(2000, CSS_PACE_S)
    labels = " ".join(s.label for s in structured.items if isinstance(s, WorkoutStep)).lower()
    assert "eyes closed" not in labels
    assert "eyes-closed" not in labels


# --- breathing-pattern variation -------------------------------------------------


def test_breathing_pattern_variation_sums_to_requested_distance():
    structured = build_breathing_pattern_variation_template(2000, CSS_PACE_S)
    assert _total_distance(structured) == 2000


def test_breathing_pattern_variation_below_min_distance_raises():
    with pytest.raises(ValueError, match="breathing-pattern"):
        build_breathing_pattern_variation_template(BREATHING_PATTERN_MIN_DISTANCE_M - 100, CSS_PACE_S)


def test_breathing_pattern_variation_alternates_bilateral_and_unilateral():
    structured = build_breathing_pattern_variation_template(2000, CSS_PACE_S)
    repeat = next(item for item in structured.items if isinstance(item, WorkoutRepeat))
    assert len(repeat.steps) == 2
    labels = [s.label.lower() for s in repeat.steps]
    assert any("bilateral" in label for label in labels)
    assert any("unilateral" in label for label in labels)


# --- back-to-back stage simulation ----------------------------------------------


@pytest.mark.parametrize("day", ["day_1", "day_2"])
def test_back_to_back_stage_simulation_sums_to_requested_distance(day):
    structured = build_back_to_back_stage_simulation_template(day, 6000, CSS_PACE_S)
    assert _total_distance(structured) == 6000


def test_back_to_back_stage_simulation_invalid_day_raises():
    with pytest.raises(ValueError, match="day"):
        build_back_to_back_stage_simulation_template("day_3", 6000, CSS_PACE_S)  # type: ignore[arg-type]


def test_back_to_back_stage_simulation_below_floor_raises():
    with pytest.raises(ValueError, match="back-to-back"):
        build_back_to_back_stage_simulation_template("day_1", 1000, CSS_PACE_S)


def test_back_to_back_day2_framing_mentions_fatigue_not_day1_framing():
    day1 = build_back_to_back_stage_simulation_template("day_1", 6000, CSS_PACE_S)
    day2 = build_back_to_back_stage_simulation_template("day_2", 6000, CSS_PACE_S)
    day1_why = next(s.label for s in day1.items if isinstance(s, WorkoutStep) and s.role == "open")
    day2_why = next(s.label for s in day2.items if isinstance(s, WorkoutStep) and s.role == "open")
    assert "day 1" in day1_why.lower()
    assert "day 2" in day2_why.lower()
    assert "fatigue" in day2_why.lower()
    assert day1_why != day2_why


def test_back_to_back_min_duration_constant_is_documented_and_positive():
    assert BACK_TO_BACK_MIN_DURATION_MIN > 0


# --- taper activation ------------------------------------------------------------


def test_taper_activation_sums_to_requested_distance():
    structured = build_taper_activation_template(1200, CSS_PACE_S)
    assert _total_distance(structured) == 1200


def test_taper_activation_above_max_distance_raises():
    with pytest.raises(ValueError, match="taper activation"):
        build_taper_activation_template(TAPER_ACTIVATION_MAX_DISTANCE_M + 500, CSS_PACE_S)


def test_taper_activation_includes_race_pace_and_acceleration_work():
    structured = build_taper_activation_template(1200, CSS_PACE_S)
    zones_used = {
        s.target.zone
        for item in structured.items
        if isinstance(item, WorkoutRepeat)
        for s in item.steps
        if isinstance(s, WorkoutStep) and s.target is not None
    }
    assert "Z4" in zones_used or "Z5" in zones_used


# --- race dress rehearsal ---------------------------------------------------------


def test_race_dress_rehearsal_sums_to_requested_distance():
    structured = build_race_dress_rehearsal_template(6000, CSS_PACE_S)
    assert _total_distance(structured) == 6000


def test_race_dress_rehearsal_below_floor_raises():
    with pytest.raises(ValueError, match="race dress rehearsal"):
        build_race_dress_rehearsal_template(1000, CSS_PACE_S)


def test_race_dress_rehearsal_mentions_race_kit():
    structured = build_race_dress_rehearsal_template(6000, CSS_PACE_S)
    labels = " ".join(s.label for s in structured.items if isinstance(s, WorkoutStep)).lower()
    assert "race kit" in labels


# --- registry / dispatcher --------------------------------------------------------


def test_registry_scaling_matches_expected_categories():
    expected_endurance_floor = {
        "feed_window_practice",
        "back_to_back_stage_day1",
        "back_to_back_stage_day2",
        "race_dress_rehearsal",
    }
    expected_skill_scalable = {
        "negative_split",
        "chop_wind_adaptation",
        "sighting_drill",
        "breathing_pattern_variation",
        "taper_activation",
    }
    assert set(OW_SESSION_TEMPLATES) == expected_endurance_floor | expected_skill_scalable
    for template_id in expected_endurance_floor:
        assert OW_SESSION_TEMPLATES[template_id].scaling == "endurance_floor"
        assert OW_SESSION_TEMPLATES[template_id].min_duration_min is not None
    for template_id in expected_skill_scalable:
        assert OW_SESSION_TEMPLATES[template_id].scaling == "skill_scalable"


def test_list_ow_session_templates_exposes_every_registry_entry():
    listed = list_ow_session_templates()
    assert {entry["id"] for entry in listed} == set(OW_SESSION_TEMPLATES)
    for entry in listed:
        assert set(entry) == {"id", "label", "scaling", "min_duration_min", "max_distance_m"}


def test_build_ow_session_dispatches_by_id():
    structured = build_ow_session("negative_split", 4000, CSS_PACE_S)
    assert _total_distance(structured) == 4000


def test_build_ow_session_unknown_id_raises():
    with pytest.raises(ValueError, match="unknown ow_template id"):
        build_ow_session("not_a_real_template", 4000, CSS_PACE_S)


def test_build_ow_session_propagates_template_specific_floor_error():
    with pytest.raises(ValueError, match="feed-window practice"):
        build_ow_session("feed_window_practice", 500, CSS_PACE_S)


@pytest.mark.parametrize("template_id", sorted(OW_SESSION_TEMPLATES))
def test_every_template_is_generic_across_athletes_not_hardcoded_css(template_id):
    """Same template_id at two different CSS paces must resolve to different
    absolute pace ranges in its labels -- proves the templates are truly
    parameterized by whatever athlete is passed in, not hardcoded to one
    athlete's numbers."""
    template = OW_SESSION_TEMPLATES[template_id]
    # Endurance-floor templates need enough distance to clear their duration
    # floor even at the FASTEST test CSS pace used below (70 s/100m) --
    # 9000m clears every real floor here (max is 90 min: 9000m @ 70s/100m
    # implies 105 min).
    distance = max(9000 if template.min_duration_min else 4000, NEG_SPLIT_MIN_DISTANCE_M)
    if template.max_distance_m is not None:
        distance = min(distance, int(template.max_distance_m))
    structured_fast = template.build(distance, 70.0)
    structured_slow = template.build(distance, 110.0)

    def _labels(structured):
        out = []
        for item in structured.items:
            if isinstance(item, WorkoutStep):
                out.append(item.label)
            else:
                out.extend(s.label for s in item.steps if isinstance(s, WorkoutStep))
        return out

    assert _labels(structured_fast) != _labels(structured_slow)
