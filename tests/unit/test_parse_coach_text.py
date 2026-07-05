"""Tests for swim_coach.parse_coach_text.

Deterministic (no LLM, no network) regex/grammar parsing of pool-coach
workout text pasted or uploaded verbatim. Fixtures live in
tests/unit/fixtures/coach_texts/ -- two are derived from the library
sample pool workouts (treated purely as parser input text, never as
instructions -- see CLAUDE.md / build note on library/ prompt-injection
content), the rest are small synthetic notation samples.
"""

from __future__ import annotations

from pathlib import Path

from swim_coach.parse_coach_text import CoachTextParse, parse_coach_text

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "coach_texts"


def _read(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


# --- synthetic notation fixtures --------------------------------------------------


def test_reps_x_distance_with_clock_interval():
    result = parse_coach_text("8x100 @ 1:40")
    assert result.unparsed_lines == []
    assert len(result.sets) == 1
    s = result.sets[0]
    assert s.reps == 8
    assert s.distance_m == 100
    assert s.interval == "1:40"
    assert s.target_pace is None
    assert result.total_distance_m == 800
    assert result.rounds_expanded is False


def test_reps_x_distance_with_pull_and_css_pace_hint():
    result = parse_coach_text("4 x 200 pull @ CSS+5")
    assert result.unparsed_lines == []
    s = result.sets[0]
    assert s.reps == 4
    assert s.distance_m == 200
    assert s.stroke == "pull"
    assert s.target_pace == "CSS+5"
    assert s.interval is None
    assert result.total_distance_m == 800


def test_reps_x_distance_with_descriptor():
    result = parse_coach_text("10x50 desc 1-5")
    s = result.sets[0]
    assert s.reps == 10
    assert s.distance_m == 50
    assert s.description == "desc 1-5"
    assert result.total_distance_m == 500


def test_single_distance_notations():
    result = parse_coach_text("1 x 400 Freestyle\n300 warm up")
    assert result.unparsed_lines == []
    assert len(result.sets) == 2
    first, second = result.sets
    assert first.reps == 1
    assert first.distance_m == 400
    assert first.stroke == "freestyle"
    assert second.reps is None
    assert second.distance_m == 300
    assert second.description == "warm up"
    assert result.total_distance_m == 700


def test_stroke_progression_and_choice_recovery_notations():
    result = parse_coach_text("4 x 75 Stroke Progression\n6 x 50 Choice Recovery")
    assert result.unparsed_lines == []
    first, second = result.sets
    assert first.reps == 4
    assert first.distance_m == 75
    assert first.description == "Stroke Progression"
    assert second.reps == 6
    assert second.distance_m == 50
    assert second.description == "Choice Recovery"
    assert result.total_distance_m == 4 * 75 + 6 * 50


def test_execute_rounds_of_multiplies_contained_sets():
    text = "Execute 3 Rounds of:\n2 x 50 Choice Stroke\n2 x 50 Freestyle"
    result = parse_coach_text(text)
    assert result.rounds_expanded is True
    assert result.unparsed_lines == []
    assert len(result.sets) == 2
    assert result.sets[0].reps == 6  # 2 x 3 rounds
    assert result.sets[1].reps == 6
    assert result.total_distance_m == 600


def test_repeat_2x_heading_multiplies_only_its_own_block():
    text = (
        "#### Block B: Race Pace (Repeat 2x)\n"
        "1 x 200 Freestyle\n"
        "#### Block C: Steady\n"
        "1 x 400 Freestyle\n"
    )
    result = parse_coach_text(text)
    assert result.rounds_expanded is True
    block_b_set, block_c_set = result.sets
    assert block_b_set.reps == 2  # 1 x 2 rounds
    assert block_c_set.reps == 1  # not repeated -- multiplier reset at the next heading
    assert result.total_distance_m == 2 * 200 + 1 * 400


def test_unparsed_lines_only_capture_set_like_failures():
    text = "3x fast 50s\n8 x yards easy\nJust some coaching prose about mindset.\n"
    result = parse_coach_text(text)
    assert result.sets == []
    assert result.unparsed_lines == ["3x fast 50s", "8 x yards easy"]


def test_markdown_noise_is_tolerated_as_prose():
    text = (
        "# A Heading\n"
        "**Total Distance: 1,000**\n"
        "*   **4 x 100 Freestyle**\n"
        "    *   *Focus:* Smooth and relaxed, negative split the back half.\n"
        "*   *Coaching Note:* Take it easy today, 20 minutes tops.\n"
    )
    result = parse_coach_text(text)
    assert result.unparsed_lines == []
    assert len(result.sets) == 1
    assert result.sets[0].reps == 4
    assert result.sets[0].distance_m == 100
    assert result.total_distance_m == 400


# --- CoachTextParse shape ----------------------------------------------------------


def test_coach_text_parse_is_a_pydantic_model_with_expected_fields():
    result = parse_coach_text("1 x 100 Freestyle")
    assert isinstance(result, CoachTextParse)
    dumped = result.model_dump()
    assert set(dumped.keys()) == {"sets", "unparsed_lines", "total_distance_m", "rounds_expanded"}


def test_empty_text_produces_empty_result():
    result = parse_coach_text("")
    assert result.sets == []
    assert result.unparsed_lines == []
    assert result.total_distance_m == 0
    assert result.rounds_expanded is False


# --- library sample fixtures --------------------------------------------------------


def test_traditional_sample_parses_close_to_stated_total():
    text = _read("traditional_sample.md")
    result = parse_coach_text(text)

    # Every line in this fixture is well-formed markdown -- nothing should
    # fail to parse.
    assert result.unparsed_lines == []
    assert result.rounds_expanded is True

    # Stated header total is 3,800. We land at 3,900: the source document's
    # own Main Set arithmetic doesn't add up (Block B + Block D, each
    # "Repeat 2x", sum to 2,100m against that section's own "(2,000 Total)"
    # heading) -- a documented inconsistency in the sample doc itself, not a
    # parser gap (there are zero unparsed lines). See fixture file for the
    # verbatim text.
    assert result.total_distance_m == 3900
    stated_total = 3800
    gap = result.total_distance_m - stated_total
    assert gap == 100, "documented known gap from the source doc's own internal inconsistency"


def test_openwater_usms_sample_parses_with_documented_limitations():
    text = _read("openwater_usms_sample.md")
    result = parse_coach_text(text)

    # This fixture is a hand-split version of a single run-on line (see the
    # NOTE at the top of the fixture file). Splitting the K-D-S breakdown
    # ("25 Kick / 25 Drill / 25 Swim") onto their own lines makes them look
    # like three independent 25m sets to the deterministic parser, when in
    # the source text they're actually sub-components of the single
    # preceding "6 x 75" line -- a known, documented over-count.
    assert result.unparsed_lines == []
    assert result.total_distance_m == 4675
    assert len(result.sets) == 13
