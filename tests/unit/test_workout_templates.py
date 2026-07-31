"""Tests for swim_coach.workout_templates: the data-driven main-set template
library (YAML files + pydantic validation + load-time semantic checks).

No LLM calls, no network access -- pure arithmetic + model validation.
"""

import pytest

from swim_coach import workout_templates
from swim_coach.workout_templates import (
    FORMAT_STRATEGIES,
    TEMPLATES_DIR,
    WorkoutTemplate,
    load_workout_templates,
    render_main_set,
)
from swim_coach.zones import zone_table

_VALID_YAML = (
    "schema_version: 1\n"
    "id: {id}\n"
    "applicable_blocks: [{blocks}]\n"
    "format_type: {format_type}\n"
    'narrative_template: "{narrative_template}"\n'
)


def _write(tmp_path, filename, content):
    path = tmp_path / filename
    path.write_text(content)
    return path


# --- real-file lint test ------------------------------------------------------
# Runs the FULL validation suite against every real *.yaml file currently
# shipped in engine/swim_coach/workout_templates/ -- so CI catches a bad
# future template addition without anyone touching plan.py.


def test_real_template_directory_loads_and_validates_cleanly():
    templates = load_workout_templates(TEMPLATES_DIR)
    assert len(templates) == 6
    ids = {t.id for t in templates}
    assert ids == {
        "base-0-straight",
        "base-1-broken-distance-lite",
        "build-0-descend",
        "build-1-pyramid",
        "build-2-ladder",
        "build-3-negative-split",
    }
    # Every format_type used by a shipped template is a real strategy.
    for t in templates:
        assert t.format_type in FORMAT_STRATEGIES


def test_real_template_directory_base_templates_only_apply_to_base():
    templates = load_workout_templates(TEMPLATES_DIR)
    base_templates = [t for t in templates if t.applicable_blocks == ["base"]]
    assert len(base_templates) == 2
    build_templates = [t for t in templates if set(t.applicable_blocks) == {"build", "peak", "taper"}]
    assert len(build_templates) == 4


# --- malformed YAML / schema errors --------------------------------------------


def test_load_workout_templates_rejects_malformed_yaml(tmp_path):
    _write(tmp_path, "broken.yaml", "id: [unterminated\n  - this is not valid: yaml: at all\n")
    with pytest.raises(ValueError, match=r"broken\.yaml.*malformed YAML"):
        load_workout_templates(tmp_path)


def test_load_workout_templates_rejects_empty_yaml_file(tmp_path):
    _write(tmp_path, "empty.yaml", "")
    with pytest.raises(ValueError, match=r"empty\.yaml.*empty YAML file"):
        load_workout_templates(tmp_path)


def test_load_workout_templates_rejects_invalid_applicable_block(tmp_path):
    _write(
        tmp_path,
        "bad_block.yaml",
        _VALID_YAML.format(
            id="bad-block",
            blocks="not_a_real_block",
            format_type="straight",
            narrative_template="Main set: {reps} x {rep}m @ Z2 ({z2_range}).",
        ),
    )
    with pytest.raises(ValueError, match=r"bad_block\.yaml.*invalid WorkoutTemplate schema"):
        load_workout_templates(tmp_path)


def test_load_workout_templates_rejects_unknown_format_type(tmp_path):
    _write(
        tmp_path,
        "unknown_format.yaml",
        _VALID_YAML.format(
            id="unknown-format",
            blocks="base",
            format_type="not_a_real_strategy",
            narrative_template="Main set: {reps} x {rep}m.",
        ),
    )
    with pytest.raises(ValueError, match=r"unknown_format\.yaml.*unknown format_type"):
        load_workout_templates(tmp_path)


def test_load_workout_templates_rejects_duplicate_ids(tmp_path):
    _write(
        tmp_path,
        "a_first.yaml",
        _VALID_YAML.format(
            id="dupe-id",
            blocks="base",
            format_type="straight",
            narrative_template="Main set: {reps} x {rep}m @ Z2 ({z2_range}).",
        ),
    )
    _write(
        tmp_path,
        "b_second.yaml",
        _VALID_YAML.format(
            id="dupe-id",
            blocks="base",
            format_type="straight",
            narrative_template="Main set: {reps} x {rep}m @ Z2 ({z2_range}), variant.",
        ),
    )
    with pytest.raises(ValueError, match=r"b_second\.yaml.*duplicate template id 'dupe-id'"):
        load_workout_templates(tmp_path)


# --- semantic validation: periodization-boundary + citation-cleanliness -------


def test_load_workout_templates_rejects_z3_z4_leak_in_base_template(tmp_path):
    # Reuse the real "descend" strategy (always renders Z3/Z4 language) but
    # mark it applicable to "base" -- the periodization-boundary violation
    # the loader must catch (base-block output must never contain Z3/Z4).
    _write(
        tmp_path,
        "leaky_base.yaml",
        _VALID_YAML.format(
            id="leaky-base",
            blocks="base",
            format_type="descend",
            narrative_template=(
                "Main set: {reps} x {rep}m broken-distance, descend 1-{reps} from Z3 "
                "({z3_range}) toward Z4 ({z4_range}) ({macro_block_name} block)."
            ),
        ),
    )
    with pytest.raises(ValueError, match=r"leaky_base\.yaml.*rendered Z3/Z4 language"):
        load_workout_templates(tmp_path)


def test_load_workout_templates_rejects_internal_library_citation(tmp_path):
    _write(
        tmp_path,
        "cites_library.yaml",
        _VALID_YAML.format(
            id="cites-library",
            blocks="base",
            format_type="straight",
            narrative_template=(
                "Main set: {reps} x {rep}m @ Z2 ({z2_range}) -- see "
                "library/14-swim-set-structure.md."
            ),
        ),
    )
    with pytest.raises(ValueError, match=r"cites_library\.yaml.*internal 'library/' path"):
        load_workout_templates(tmp_path)


def test_load_workout_templates_rejects_missing_placeholder(tmp_path):
    # narrative_template references a placeholder the "straight" strategy
    # never supplies -- a KeyError at render time, caught and re-raised with
    # a clear, file-identifying message.
    _write(
        tmp_path,
        "missing_placeholder.yaml",
        _VALID_YAML.format(
            id="missing-placeholder",
            blocks="base",
            format_type="straight",
            narrative_template="Main set: {reps} x {rep}m @ Z2 ({z2_range}), {nonexistent_key}.",
        ),
    )
    with pytest.raises(ValueError, match=r"missing_placeholder\.yaml.*placeholder not supplied"):
        load_workout_templates(tmp_path)


def test_load_workout_templates_rejects_sum_mismatch(tmp_path, monkeypatch):
    # Inject a deliberately-broken strategy (reports a _total_m that's 100m
    # short of what it actually renders) to prove the loader's warm-up +
    # main-set + cool-down == distance_m sweep actually catches a violation
    # -- the exact invariant PR #85's ladder/pyramid fixes protected.
    def _broken_strategy(reps, rep, z2, z3, z4, macro_block_name):
        return {
            "reps": reps,
            "rep": rep,
            "z2_range": "1:00-1:05/100m",
            "_total_m": reps * rep - 100,
        }

    monkeypatch.setitem(FORMAT_STRATEGIES, "_test_broken_sum", _broken_strategy)
    _write(
        tmp_path,
        "broken_sum.yaml",
        _VALID_YAML.format(
            id="broken-sum",
            blocks="base",
            format_type="_test_broken_sum",
            narrative_template="Main set: {reps} x {rep}m @ Z2 ({z2_range}).",
        ),
    )
    with pytest.raises(ValueError, match=r"broken_sum\.yaml.*expected distance_m"):
        load_workout_templates(tmp_path)


def test_load_workout_templates_rejects_strategy_that_raises(tmp_path, monkeypatch):
    def _raising_strategy(reps, rep, z2, z3, z4, macro_block_name):
        raise RuntimeError("boom")

    monkeypatch.setitem(FORMAT_STRATEGIES, "_test_raising", _raising_strategy)
    _write(
        tmp_path,
        "raises.yaml",
        _VALID_YAML.format(
            id="raises",
            blocks="base",
            format_type="_test_raising",
            narrative_template="Main set: {reps} x {rep}m.",
        ),
    )
    with pytest.raises(ValueError, match=r"raises\.yaml.*strategy raised"):
        load_workout_templates(tmp_path)


# --- WorkoutTemplate model ------------------------------------------------------


def test_workout_template_schema_version_defaults_to_1():
    t = WorkoutTemplate(
        id="t",
        applicable_blocks=["base"],
        format_type="straight",
        narrative_template="Main set: {reps} x {rep}m @ Z2 ({z2_range}).",
    )
    assert t.schema_version == 1
    assert t.source_note is None


# --- render_main_set: rotation determinism + variety ---------------------------


def test_render_main_set_is_deterministic():
    zones = zone_table(95.0)
    z2, z3, z4 = zones["Z2"], zones["Z3"], zones["Z4"]
    text_a = render_main_set("build", 5, 7, 200, z2, z3, z4)
    text_b = render_main_set("build", 5, 7, 200, z2, z3, z4)
    assert text_a == text_b

    base_a = render_main_set("base", 3, 5, 300, z2, z3, z4)
    base_b = render_main_set("base", 3, 5, 300, z2, z3, z4)
    assert base_a == base_b


def test_render_main_set_build_rotation_selects_all_four_templates():
    zones = zone_table(95.0)
    z2, z3, z4 = zones["Z2"], zones["Z3"], zones["Z4"]
    texts = [render_main_set("build", s, 7, 200, z2, z3, z4) for s in range(4)]
    assert len(set(texts)) == 4


def test_render_main_set_base_rotation_selects_both_templates():
    zones = zone_table(95.0)
    z2, z3, z4 = zones["Z2"], zones["Z3"], zones["Z4"]
    texts = [render_main_set("base", s, 5, 300, z2, z3, z4) for s in range(2)]
    assert len(set(texts)) == 2


def test_render_main_set_wraps_with_modulo():
    zones = zone_table(95.0)
    z2, z3, z4 = zones["Z2"], zones["Z3"], zones["Z4"]
    assert render_main_set("build", 0, 7, 200, z2, z3, z4) == render_main_set(
        "build", 4, 7, 200, z2, z3, z4
    )
    assert render_main_set("base", 0, 5, 300, z2, z3, z4) == render_main_set(
        "base", 2, 5, 300, z2, z3, z4
    )


def test_render_main_set_unknown_block_raises():
    zones = zone_table(95.0)
    z2, z3, z4 = zones["Z2"], zones["Z3"], zones["Z4"]
    with pytest.raises(ValueError, match="no workout templates registered"):
        render_main_set("not_a_real_block", 0, 5, 300, z2, z3, z4)


# --- FORMAT_STRATEGIES: direct coverage of the ported computation shapes ------


def test_pyramid_strategy_degenerate_case_has_no_pyramid_language():
    zones = zone_table(95.0)
    z2, z3, z4 = zones["Z2"], zones["Z3"], zones["Z4"]
    placeholders = FORMAT_STRATEGIES["pyramid"](1, 300, z2, z3, z4, "build")
    assert placeholders["pyramid_word"] == ""
    assert "and back down" not in placeholders["ramp_clause"]
    assert placeholders["_total_m"] == 300


def test_pyramid_strategy_normal_case_has_pyramid_language():
    zones = zone_table(95.0)
    z2, z3, z4 = zones["Z2"], zones["Z3"], zones["Z4"]
    placeholders = FORMAT_STRATEGIES["pyramid"](7, 200, z2, z3, z4, "build")
    assert placeholders["pyramid_word"] == " pyramid"
    assert "at rep 4 of 7" in placeholders["ramp_clause"]
    assert placeholders["_total_m"] == 1400


def test_ladder_strategy_total_matches_reps_times_rep():
    zones = zone_table(95.0)
    z2, z3, z4 = zones["Z2"], zones["Z3"], zones["Z4"]
    for reps, rep in [(7, 200), (4, 300), (1, 100), (10, 150)]:
        placeholders = FORMAT_STRATEGIES["ladder"](reps, rep, z2, z3, z4, "build")
        assert placeholders["_total_m"] == reps * rep
