"""Tests for swim_coach.workout_templates: the data-driven main-set template
library (YAML files + pydantic validation + load-time semantic checks).

No LLM calls, no network access -- pure arithmetic + model validation.
"""

import uuid

import pytest
import yaml

from swim_coach import workout_templates
from swim_coach.models import Athlete, WorkoutLoad, WorkoutRepeat, WorkoutStep, WorkoutStructure, WorkoutTarget
from swim_coach.workout_templates import (
    FORMAT_STRATEGIES,
    TEMPLATES_DIR,
    TemplateFacets,
    TemplatePreference,
    WorkoutTemplate,
    build_main_set_step,
    clear_template_cache,
    compute_facets,
    facets_from_structure,
    find_templates,
    load_template_facets,
    load_workout_templates,
    render_main_set,
    render_prose,
    resolve_template,
)
from swim_coach.zones import zone_table

# `purpose: aerobic_base` is a hardcoded literal (not a `{}` placeholder) so
# every existing `_VALID_YAML.format(...)` call below keeps working
# unchanged now that `WorkoutTemplate.purpose` is required -- these tests
# exercise loader/validation behavior unrelated to `purpose` itself, so a
# fixed, always-valid value is the right choice (see the dedicated `purpose`/
# `tags` tests further down for field-specific coverage).
_VALID_YAML = (
    "schema_version: 1\n"
    "id: {id}\n"
    "purpose: aerobic_base\n"
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
    assert len(templates) == 18
    ids = {t.id for t in templates}
    assert ids == {
        "base-0-straight",
        "base-1-broken-distance-lite",
        "build-0-descend",
        "build-1-pyramid",
        "build-2-ladder",
        "build-3-negative-split",
        # PR #87 ETL: 9 researched pool workouts reusing existing strategies.
        "build-a-descend-whos-in-pool",
        "build-b-straight-ultra-short-race-pace",
        "build-c-pyramid-breathing",
        "build-d-descend-freestyle-focus",
        "build-e-descend-beast-training",
        "build-f-straight-repeat-sprints",
        "build-g-straight-kick-and-swim-sprints",
        "build-h-descend-to-sprint",
        "build-i-straight-broken-200",
        # New descending_ladder strategy templates.
        "build-j-descending-ladder-pull",
        "build-k-descending-ladder-kick",
        "build-l-descending-ladder-breathing-filler",
    }
    # Every format_type used by a shipped template is a real strategy.
    for t in templates:
        assert t.format_type in FORMAT_STRATEGIES


def test_real_template_directory_base_templates_only_apply_to_base():
    templates = load_workout_templates(TEMPLATES_DIR)
    base_templates = [t for t in templates if t.applicable_blocks == ["base"]]
    assert len(base_templates) == 2
    build_templates = [t for t in templates if set(t.applicable_blocks) == {"build", "peak", "taper"}]
    # 4 original (PR #85) + 9 researched-workout ETL + 3 descending_ladder.
    assert len(build_templates) == 16


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
        purpose="aerobic_base",
    )
    assert t.schema_version == 1
    assert t.source_note is None
    assert t.tags == []


def test_workout_template_purpose_is_required():
    with pytest.raises(Exception):  # noqa: B017 -- pydantic ValidationError
        WorkoutTemplate(
            id="t",
            applicable_blocks=["base"],
            format_type="straight",
            narrative_template="Main set: {reps} x {rep}m @ Z2 ({z2_range}).",
        )


def test_workout_template_rejects_unknown_purpose_value():
    with pytest.raises(Exception):  # noqa: B017 -- pydantic ValidationError
        WorkoutTemplate(
            id="t",
            applicable_blocks=["base"],
            format_type="straight",
            narrative_template="Main set: {reps} x {rep}m @ Z2 ({z2_range}).",
            purpose="not_a_real_purpose",
        )


def test_workout_template_tags_defaults_empty_and_accepts_list():
    t = WorkoutTemplate(
        id="t",
        applicable_blocks=["base"],
        format_type="straight",
        narrative_template="Main set: {reps} x {rep}m @ Z2 ({z2_range}).",
        purpose="aerobic_base",
        tags=["long-tail-label"],
    )
    assert t.tags == ["long-tail-label"]


def test_real_template_directory_every_template_has_a_valid_purpose():
    # `purpose` is the one hand-authored, subjective field (per the Opus
    # consultation) -- confirm every real shipped template actually has one,
    # and that the real library uses more than one value (i.e. this isn't
    # just a rubber-stamped default copy-pasted onto every file).
    templates = load_workout_templates(TEMPLATES_DIR)
    valid_purposes = {
        "aerobic_base", "threshold", "race_pace", "technique", "sprint_power",
        "recovery", "strength_endurance", "max_strength", "posterior_chain",
    }
    purposes_seen = {t.purpose for t in templates}
    assert purposes_seen.issubset(valid_purposes)
    assert len(purposes_seen) >= 4


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


def test_render_main_set_build_rotation_selects_all_sixteen_templates():
    # 4 original (PR #85) + 9 researched-workout ETL + 3 descending_ladder
    # templates == 16 distinct build/peak/taper candidates as of this ETL.
    zones = zone_table(95.0)
    z2, z3, z4 = zones["Z2"], zones["Z3"], zones["Z4"]
    texts = [render_main_set("build", s, 7, 200, z2, z3, z4) for s in range(16)]
    assert len(set(texts)) == 16


def test_render_main_set_base_rotation_selects_both_templates():
    zones = zone_table(95.0)
    z2, z3, z4 = zones["Z2"], zones["Z3"], zones["Z4"]
    texts = [render_main_set("base", s, 5, 300, z2, z3, z4) for s in range(2)]
    assert len(set(texts)) == 2


def test_render_main_set_wraps_with_modulo():
    zones = zone_table(95.0)
    z2, z3, z4 = zones["Z2"], zones["Z3"], zones["Z4"]
    assert render_main_set("build", 0, 7, 200, z2, z3, z4) == render_main_set(
        "build", 16, 7, 200, z2, z3, z4
    )
    assert render_main_set("base", 0, 5, 300, z2, z3, z4) == render_main_set(
        "base", 2, 5, 300, z2, z3, z4
    )


def test_render_main_set_new_researched_workout_template_appears_in_rotation():
    # Sanity check that the ETL'd researched-workout templates are actually
    # reachable via the real rotation path, not just load-time valid --
    # build-a (index 4, sorted by id) is "Who's in the Pool?".
    zones = zone_table(95.0)
    z2, z3, z4 = zones["Z2"], zones["Z3"], zones["Z4"]
    text = render_main_set("build", 4, 7, 200, z2, z3, z4)
    assert "Who's in the Pool" in text


def test_render_main_set_new_descending_ladder_template_appears_in_rotation():
    # build-j (index 13, sorted by id) is the first descending_ladder
    # template -- confirm the new strategy's output actually reaches the
    # real rotation, not just direct FORMAT_STRATEGIES unit coverage.
    zones = zone_table(95.0)
    z2, z3, z4 = zones["Z2"], zones["Z3"], zones["Z4"]
    text = render_main_set("build", 13, 7, 200, z2, z3, z4)
    assert "descending-distance pull ladder" in text
    assert "library/" not in text


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


# --- descending_ladder strategy: one-directional ladder, exact-sum invariant --


@pytest.mark.parametrize("css_pace_s", [80.0, 95.0, 110.0])
@pytest.mark.parametrize(
    "reps,rep",
    [
        (7, 200),
        (4, 300),
        (1, 100),  # smallest realistic production floor (build rep=100, reps=1)
        (10, 150),
        (2, 100),
        (3, 333),  # deliberately not a round number -- stresses leftover arithmetic
        (1, 1),  # degenerate: total_m=1, triggers the unit==0 collapse branch
    ],
)
def test_descending_ladder_strategy_total_matches_reps_times_rep(reps, rep, css_pace_s):
    zones = zone_table(css_pace_s)
    z2, z3, z4 = zones["Z2"], zones["Z3"], zones["Z4"]
    placeholders = FORMAT_STRATEGIES["descending_ladder"](reps, rep, z2, z3, z4, "build")
    assert placeholders["_total_m"] == reps * rep


def test_descending_ladder_strategy_rungs_are_strictly_non_increasing():
    zones = zone_table(95.0)
    z2, z3, z4 = zones["Z2"], zones["Z3"], zones["Z4"]
    for reps, rep in [(7, 200), (4, 300), (10, 150), (3, 333), (2, 100)]:
        placeholders = FORMAT_STRATEGIES["descending_ladder"](reps, rep, z2, z3, z4, "build")
        rungs = [int(tok.rstrip("m")) for tok in placeholders["rung_list"].split(", ")]
        assert rungs == sorted(rungs, reverse=True)
        assert all(r > 0 for r in rungs)
        assert sum(rungs) == reps * rep


def test_descending_ladder_strategy_normal_case_has_four_rungs():
    zones = zone_table(95.0)
    z2, z3, z4 = zones["Z2"], zones["Z3"], zones["Z4"]
    placeholders = FORMAT_STRATEGIES["descending_ladder"](7, 200, z2, z3, z4, "build")
    assert placeholders["num_rungs"] == 4
    assert placeholders["rung_list"] == "560m, 420m, 280m, 140m"
    assert placeholders["_total_m"] == 1400


def test_descending_ladder_strategy_degenerate_small_total_collapses_to_one_rung():
    # total_m=1 -> unit = 1 // 10 == 0 -> the zero-rung guard collapses to a
    # single rep-length "ladder" of just the top rung, avoiding zero-length
    # rungs (same class of edge case as the pyramid's reps<=2 fallback).
    zones = zone_table(95.0)
    z2, z3, z4 = zones["Z2"], zones["Z3"], zones["Z4"]
    placeholders = FORMAT_STRATEGIES["descending_ladder"](1, 1, z2, z3, z4, "build")
    assert placeholders["num_rungs"] == 1
    assert placeholders["rung_list"] == "1m"
    assert placeholders["_total_m"] == 1


def test_descending_ladder_strategy_is_deterministic():
    zones = zone_table(92.0)
    z2, z3, z4 = zones["Z2"], zones["Z3"], zones["Z4"]
    a = FORMAT_STRATEGIES["descending_ladder"](7, 200, z2, z3, z4, "peak")
    b = FORMAT_STRATEGIES["descending_ladder"](7, 200, z2, z3, z4, "peak")
    assert a == b


def test_descending_ladder_strategy_reports_macro_block_name():
    zones = zone_table(95.0)
    z2, z3, z4 = zones["Z2"], zones["Z3"], zones["Z4"]
    for block in ("build", "peak", "taper"):
        placeholders = FORMAT_STRATEGIES["descending_ladder"](7, 200, z2, z3, z4, block)
        assert placeholders["macro_block_name"] == block


def test_descending_ladder_is_build_peak_taper_only_in_the_real_template_directory():
    # Design choice (per this ETL's brief): the descending_ladder shape is
    # race-pace-adjacent by nature in every real source workout it was
    # drawn from (#2, #3, #11, #17 in library/researched-masters-pool-
    # workouts.md), so no shipped descending_ladder template is base-
    # applicable -- confirmed directly against the real template directory.
    templates = load_workout_templates(TEMPLATES_DIR)
    descending_ladder_templates = [t for t in templates if t.format_type == "descending_ladder"]
    assert len(descending_ladder_templates) == 3
    for t in descending_ladder_templates:
        assert "base" not in t.applicable_blocks
        assert set(t.applicable_blocks) == {"build", "peak", "taper"}


# --- build_main_set_step: byte-identical parity vs. render_main_set ------------
# The whole WorkoutStructure migration hinges on this: render_prose(build_main_
# set_step(...)) must equal render_main_set(...) EXACTLY (minus the "Main set: "
# prefix, which render_prose's role->prefix mapping adds back), for every real
# template + selector this repo ships -- same regression-proof discipline as
# PR #86's prose-migration parity tests.

_ALL_BLOCKS = ("base", "build", "peak", "taper")


def _candidate_count(macro_block_name: str) -> int:
    templates = load_workout_templates(TEMPLATES_DIR)
    return len([t for t in templates if macro_block_name in t.applicable_blocks])


@pytest.mark.parametrize("css_pace_s", [80.0, 95.0, 110.0])
@pytest.mark.parametrize("reps,rep", [(7, 200), (4, 300), (1, 100), (10, 150)])
@pytest.mark.parametrize("macro_block_name", _ALL_BLOCKS)
def test_build_main_set_step_matches_render_main_set_for_every_real_template(
    macro_block_name, reps, rep, css_pace_s
):
    zones = zone_table(css_pace_s)
    z2, z3, z4 = zones["Z2"], zones["Z3"], zones["Z4"]
    for selector in range(_candidate_count(macro_block_name)):
        expected = render_main_set(macro_block_name, selector, reps, rep, z2, z3, z4)
        step = build_main_set_step(macro_block_name, selector, reps, rep, z2, z3, z4)
        got = render_prose(WorkoutStructure(items=[step]))
        assert got == expected


def test_build_main_set_step_covers_all_eighteen_real_templates_across_blocks():
    # Sanity check that the parametrized sweep above actually walks every
    # real shipped template at least once (2 base + 16 build/peak/taper),
    # not just a subset -- guards against a future template addition
    # silently falling outside the parity sweep's selector range. Tracked by
    # template `id` (not rendered label) since the same build/peak/taper
    # template renders different text per macro_block_name (the narrative
    # embeds "(build block)"/"(peak block)"/"(taper block)").
    seen_ids: set[str] = set()
    for macro_block_name in _ALL_BLOCKS:
        for selector in range(_candidate_count(macro_block_name)):
            template = workout_templates._select_main_set_template(macro_block_name, selector)
            seen_ids.add(template.id)
    templates = load_workout_templates(TEMPLATES_DIR)
    assert seen_ids == {t.id for t in templates}
    assert len(seen_ids) == 18


def _selector_for(macro_block_name: str, template_id: str) -> int:
    templates = load_workout_templates(TEMPLATES_DIR)
    candidates = sorted(
        (t for t in templates if macro_block_name in t.applicable_blocks), key=lambda t: t.id
    )
    return next(i for i, t in enumerate(candidates) if t.id == template_id)


def test_build_main_set_step_target_zone_reflects_narrative_template_content():
    zones = zone_table(95.0)
    z2, z3, z4 = zones["Z2"], zones["Z3"], zones["Z4"]

    # base-0-straight is Z2-anchored.
    base_selector = _selector_for("base", "base-0-straight")
    base_step = build_main_set_step("base", base_selector, 5, 300, z2, z3, z4)
    assert base_step.target.basis == "zone"
    assert base_step.target.zone == "Z2"

    # build-0-descend ramps to Z4; build_main_set_step tags the peak zone
    # reached.
    descend_selector = _selector_for("build", "build-0-descend")
    descend_step = build_main_set_step("build", descend_selector, 7, 200, z2, z3, z4)
    assert descend_step.target.basis == "zone"
    assert descend_step.target.zone == "Z4"

    # build-f-straight-repeat-sprints (a fins-assisted sprint set) references
    # no zone-range placeholder at all -- honestly left untargeted rather
    # than guessed from format_type alone.
    sprint_selector = _selector_for("build", "build-f-straight-repeat-sprints")
    sprint_step = build_main_set_step("build", sprint_selector, 7, 200, z2, z3, z4)
    assert sprint_step.target is None


# --- render_prose: generic role-driven rendering -------------------------------


def test_render_prose_renders_warmup_interval_cooldown_with_prefixes():
    structured = WorkoutStructure(
        items=[
            WorkoutStep(label="700m easy.", role="warmup", duration_kind="distance_m", duration_value=700),
            WorkoutStep(label="main set text.", role="interval", duration_kind="distance_m", duration_value=1600),
            WorkoutStep(label="300m easy.", role="cooldown", duration_kind="distance_m", duration_value=300),
            WorkoutStep(label="Why: reasons.", role="open", duration_kind="open"),
        ]
    )
    assert render_prose(structured) == (
        "Warm-up: 700m easy.\nMain set: main set text.\nCool-down: 300m easy.\nWhy: reasons."
    )


def test_render_prose_renders_repeat_steps_as_bullets():
    repeat = WorkoutRepeat(
        repeat_mode="count",
        count=2,
        steps=[
            WorkoutStep(label="exercise A", role="steady", duration_kind="reps", duration_value=10),
            WorkoutStep(label="exercise B", role="steady", duration_kind="reps", duration_value=10),
        ],
    )
    structured = WorkoutStructure(
        items=[
            WorkoutStep(label="Header:", role="open", duration_kind="open"),
            repeat,
        ]
    )
    assert render_prose(structured) == "Header:\n  - exercise A\n  - exercise B"


# --- resolve_template: the one place relative -> absolute resolution happens --


def test_resolve_template_zone_basis_resolves_to_absolute_pace_from_css():
    athlete = Athlete(id=uuid.uuid4(), slug="t", name="T", css_pace_s_per_100m=95.0)
    step = WorkoutStep(
        label="warm", role="warmup", duration_kind="distance_m", duration_value=500,
        target=WorkoutTarget(basis="zone", zone="Z2"),
    )
    resolved = resolve_template(WorkoutStructure(items=[step]), athlete)
    z2 = zone_table(95.0)["Z2"]
    resolved_target = resolved.items[0].target
    assert resolved_target.basis == "absolute"
    assert resolved_target.low == z2["pace_lo_s"]
    assert resolved_target.high == z2["pace_hi_s"]
    # original template is untouched -- resolve_template never mutates.
    assert step.target.basis == "zone"


@pytest.mark.parametrize("css_pace_s", [80.0, 95.0, 110.0, 130.0])
@pytest.mark.parametrize("zone", ["Z1", "Z2", "Z3", "Z4", "Z5"])
def test_resolve_template_zone_basis_matches_zone_table_across_css_range(css_pace_s, zone):
    athlete = Athlete(id=uuid.uuid4(), slug="t", name="T", css_pace_s_per_100m=css_pace_s)
    step = WorkoutStep(
        label="x", role="steady", duration_kind="distance_m", duration_value=100,
        target=WorkoutTarget(basis="zone", zone=zone),
    )
    resolved = resolve_template(WorkoutStructure(items=[step]), athlete)
    expected = zone_table(css_pace_s)[zone]
    assert resolved.items[0].target.low == expected["pace_lo_s"]
    assert resolved.items[0].target.high == expected["pace_hi_s"]


@pytest.mark.parametrize("css_pace_s", [80.0, 100.0, 120.0])
def test_resolve_template_percent_css_basis_resolves_relative_to_css(css_pace_s):
    athlete = Athlete(id=uuid.uuid4(), slug="t", name="T", css_pace_s_per_100m=css_pace_s)
    step = WorkoutStep(
        label="x", role="interval", duration_kind="distance_m", duration_value=100,
        target=WorkoutTarget(basis="percent_css", low=135, high=140),
    )
    resolved = resolve_template(WorkoutStructure(items=[step]), athlete)
    resolved_target = resolved.items[0].target
    assert resolved_target.basis == "absolute"
    assert resolved_target.low == pytest.approx(css_pace_s * 1.35)
    assert resolved_target.high == pytest.approx(css_pace_s * 1.40)


def test_resolve_template_falls_back_to_default_css_when_athlete_has_none():
    from swim_coach.plan import DEFAULT_CSS_PACE_S_PER_100M

    athlete = Athlete(id=uuid.uuid4(), slug="t", name="T", css_pace_s_per_100m=None)
    step = WorkoutStep(
        label="x", role="warmup", duration_kind="distance_m", duration_value=100,
        target=WorkoutTarget(basis="zone", zone="Z2"),
    )
    resolved = resolve_template(WorkoutStructure(items=[step]), athlete)
    z2 = zone_table(DEFAULT_CSS_PACE_S_PER_100M)["Z2"]
    assert resolved.items[0].target.low == z2["pace_lo_s"]


@pytest.mark.parametrize("one_rm_kg", [40.0, 60.0, 100.0])
@pytest.mark.parametrize("percent", [50.0, 70.0, 100.0])
def test_resolve_template_percent_1rm_basis_resolves_via_athlete_constraints(percent, one_rm_kg):
    athlete = Athlete(
        id=uuid.uuid4(), slug="t", name="T",
        constraints={"one_rm_kg": {"goblet squat": one_rm_kg}},
    )
    step = WorkoutStep(
        label="goblet squat", role="steady", duration_kind="reps", duration_value=10,
        exercise_name="goblet squat", load=WorkoutLoad(basis="percent_1rm", value=percent),
        modality="strength",
    )
    resolved = resolve_template(WorkoutStructure(items=[step]), athlete)
    resolved_load = resolved.items[0].load
    assert resolved_load.basis == "absolute"
    assert resolved_load.value == pytest.approx(one_rm_kg * percent / 100)


def test_resolve_template_percent_1rm_without_matching_athlete_data_passes_through_unresolved():
    athlete = Athlete(id=uuid.uuid4(), slug="t", name="T")
    step = WorkoutStep(
        label="bench press", role="steady", duration_kind="reps", duration_value=10,
        exercise_name="bench press", load=WorkoutLoad(basis="percent_1rm", value=70),
        modality="strength",
    )
    resolved = resolve_template(WorkoutStructure(items=[step]), athlete)
    assert resolved.items[0].load.basis == "percent_1rm"
    assert resolved.items[0].load.value == 70


def test_resolve_template_bodyweight_and_rpe_bases_pass_through_unchanged():
    athlete = Athlete(id=uuid.uuid4(), slug="t", name="T")
    step = WorkoutStep(
        label="x", role="steady", duration_kind="reps", duration_value=10,
        load=WorkoutLoad(basis="bodyweight"),
    )
    resolved = resolve_template(WorkoutStructure(items=[step]), athlete)
    assert resolved.items[0].load == WorkoutLoad(basis="bodyweight")


def test_resolve_template_resolves_nested_steps_inside_a_repeat():
    athlete = Athlete(id=uuid.uuid4(), slug="t", name="T", css_pace_s_per_100m=90.0)
    inner = WorkoutStep(
        label="x", role="steady", duration_kind="distance_m", duration_value=100,
        target=WorkoutTarget(basis="zone", zone="Z3"),
    )
    repeat = WorkoutRepeat(repeat_mode="count", count=3, steps=[inner])
    resolved = resolve_template(WorkoutStructure(items=[repeat]), athlete)
    resolved_inner = resolved.items[0].steps[0]
    z3 = zone_table(90.0)["Z3"]
    assert resolved_inner.target.basis == "absolute"
    assert resolved_inner.target.low == z3["pace_lo_s"]


def test_resolve_template_none_target_and_load_pass_through():
    athlete = Athlete(id=uuid.uuid4(), slug="t", name="T")
    step = WorkoutStep(label="x", role="open", duration_kind="open")
    resolved = resolve_template(WorkoutStructure(items=[step]), athlete)
    assert resolved.items[0].target is None
    assert resolved.items[0].load is None


# --- TemplateFacets: facets_from_structure (pure, structure-only) -------------
# No template/YAML/FORMAT_STRATEGIES involvement at all -- exercised directly
# against hand-built synthetic `WorkoutStructure` trees, including EMOM/AMRAP
# `WorkoutRepeat` shapes no real shipped template uses yet (see
# `compute_facets`'s own tests further down for the real-template path).


def test_facets_from_structure_no_repeat_is_straight_interval_style():
    structure = WorkoutStructure(
        items=[
            WorkoutStep(label="a", role="interval", duration_kind="distance_m", duration_value=200),
        ]
    )
    facets = facets_from_structure(structure)
    assert facets.interval_style == "straight"


def test_facets_from_structure_count_mode_repeat_is_intervals():
    repeat = WorkoutRepeat(
        repeat_mode="count",
        count=3,
        steps=[WorkoutStep(label="rep", role="interval", duration_kind="distance_m", duration_value=100)],
    )
    facets = facets_from_structure(WorkoutStructure(items=[repeat]))
    assert facets.interval_style == "intervals"


def test_facets_from_structure_for_duration_mode_is_emom():
    # Synthetic EMOM-shaped template: a new round starts every interval_s
    # regardless of how long the round took -- no real shipped template uses
    # this repeat_mode yet (see this module's `compute_facets` tests), so the
    # derivation is proven here against a hand-built structure standing in
    # for what an EMOM-shaped template's built structure would look like.
    emom_repeat = WorkoutRepeat(
        repeat_mode="for_duration",
        duration_s=600,
        interval_s=60,
        steps=[
            WorkoutStep(
                label="kettlebell swing", role="steady", duration_kind="reps", duration_value=15,
                exercise_name="kettlebell swing", modality="strength", equipment=["kettlebell"],
            )
        ],
    )
    facets = facets_from_structure(WorkoutStructure(items=[emom_repeat]))
    assert facets.interval_style == "emom"
    # The window itself is the duration contribution -- inner rounds are
    # open-ended (round count depends on how fast each round completes), so
    # inner-step reps are NOT multiplied into a distance/duration total.
    assert facets.approx_duration_s == 600
    assert facets.approx_distance_m is None
    assert facets.equipment == ["kettlebell"]
    assert facets.modality == "strength"


def test_facets_from_structure_amrap_mode_is_amrap():
    # Synthetic AMRAP-shaped template: as many rounds/reps as possible within
    # a fixed window -- same "no real shipped template uses this yet" note as
    # the EMOM test above.
    amrap_repeat = WorkoutRepeat(
        repeat_mode="amrap",
        duration_s=900,
        steps=[
            WorkoutStep(label="burpees", role="steady", duration_kind="reps", duration_value=10, modality="strength"),
            WorkoutStep(label="air squats", role="steady", duration_kind="reps", duration_value=20, modality="strength"),
        ],
    )
    facets = facets_from_structure(WorkoutStructure(items=[amrap_repeat]))
    assert facets.interval_style == "amrap"
    assert facets.approx_duration_s == 900
    assert facets.approx_distance_m is None


def test_facets_from_structure_count_mode_distance_is_multiplied_by_count():
    # 3 x 100m must total 300m, not 100m -- a `count`-mode repeat's inner
    # total is multiplied by `count`, unlike for_duration/amrap.
    repeat = WorkoutRepeat(
        repeat_mode="count",
        count=3,
        steps=[WorkoutStep(label="rep", role="interval", duration_kind="distance_m", duration_value=100)],
    )
    facets = facets_from_structure(WorkoutStructure(items=[repeat]))
    assert facets.approx_distance_m == 300


def test_facets_from_structure_derives_equipment_across_the_tree():
    structure = WorkoutStructure(
        items=[
            WorkoutStep(
                label="a", role="steady", duration_kind="reps", duration_value=10,
                equipment=["paddles"], modality="swim",
            ),
            WorkoutRepeat(
                repeat_mode="count", count=2,
                steps=[
                    WorkoutStep(
                        label="b", role="steady", duration_kind="reps", duration_value=10,
                        equipment=["fins", "paddles"], modality="swim",
                    )
                ],
            ),
        ]
    )
    facets = facets_from_structure(structure)
    assert facets.equipment == ["fins", "paddles"]


def test_facets_from_structure_is_medley_true_for_explicit_im_stroke():
    step = WorkoutStep(label="a", role="interval", duration_kind="distance_m", duration_value=200, stroke="im")
    facets = facets_from_structure(WorkoutStructure(items=[step]))
    assert facets.is_medley is True
    assert facets.strokes == ["im"]


def test_facets_from_structure_is_medley_true_for_mixed_stroke():
    step = WorkoutStep(label="a", role="interval", duration_kind="distance_m", duration_value=200, stroke="mixed")
    facets = facets_from_structure(WorkoutStructure(items=[step]))
    assert facets.is_medley is True


def test_facets_from_structure_is_medley_true_for_multiple_real_strokes_without_im_label():
    # Stroke rotation across the set (e.g. free then back) without an
    # explicit "im"/"mixed" label still reads as medley-ish -- derived from
    # actually seeing >1 distinct real stroke, not just a single tag.
    structure = WorkoutStructure(
        items=[
            WorkoutStep(label="a", role="interval", duration_kind="distance_m", duration_value=100, stroke="free"),
            WorkoutStep(label="b", role="interval", duration_kind="distance_m", duration_value=100, stroke="back"),
        ]
    )
    facets = facets_from_structure(structure)
    assert facets.is_medley is True
    assert facets.strokes == ["back", "free"]


def test_facets_from_structure_is_medley_false_for_single_stroke():
    step = WorkoutStep(label="a", role="interval", duration_kind="distance_m", duration_value=200, stroke="free")
    facets = facets_from_structure(WorkoutStructure(items=[step]))
    assert facets.is_medley is False
    assert facets.strokes == ["free"]


def test_facets_from_structure_no_stroke_no_equipment_defaults_empty():
    step = WorkoutStep(label="a", role="interval", duration_kind="distance_m", duration_value=200)
    facets = facets_from_structure(WorkoutStructure(items=[step]))
    assert facets.equipment == []
    assert facets.strokes == []
    assert facets.is_medley is False


def test_facets_from_structure_all_strength_steps_is_strength_modality():
    step = WorkoutStep(
        label="a", role="steady", duration_kind="reps", duration_value=10, modality="strength",
        exercise_name="goblet squat",
    )
    facets = facets_from_structure(WorkoutStructure(items=[step]))
    assert facets.modality == "strength"


# --- TemplateFacets: compute_facets (real templates via representative structure) --


def test_compute_facets_every_real_template_is_straight_swim_with_positive_estimates():
    # Every real template today ships zero equipment/stroke tagging and
    # `build_main_set_step` never emits a `WorkoutRepeat` -- so every real
    # template's computed facets should be "straight"/"swim"/no equipment/no
    # strokes, with a positive approximate distance and duration. This is the
    # honest, expected real-content baseline (see EMOM/AMRAP tests above for
    # proof the derivation mechanism itself works).
    templates = load_workout_templates(TEMPLATES_DIR)
    for template in templates:
        facets = compute_facets(template)
        assert facets.interval_style == "straight", template.id
        assert facets.modality == "swim", template.id
        assert facets.equipment == [], template.id
        assert facets.strokes == [], template.id
        assert facets.is_medley is False, template.id
        assert facets.approx_distance_m is not None and facets.approx_distance_m > 0, template.id
        assert facets.approx_duration_s is not None and facets.approx_duration_s > 0, template.id


def test_load_template_facets_matches_compute_facets_for_every_real_template():
    templates = load_workout_templates(TEMPLATES_DIR)
    facets_by_id = load_template_facets(TEMPLATES_DIR)
    assert set(facets_by_id) == {t.id for t in templates}
    for template in templates:
        assert facets_by_id[template.id] == compute_facets(template)


# --- module-level cache: load_workout_templates / load_template_facets -------


def test_load_workout_templates_caches_across_repeated_calls(tmp_path, monkeypatch):
    _write(
        tmp_path, "cached.yaml",
        _VALID_YAML.format(
            id="cached-template", blocks="base", format_type="straight",
            narrative_template="Main set: {reps} x {rep}m @ Z2 ({z2_range}).",
        ),
    )
    clear_template_cache()

    real_safe_load = yaml.safe_load
    call_count = {"n": 0}

    def _counting_safe_load(*args, **kwargs):
        call_count["n"] += 1
        return real_safe_load(*args, **kwargs)

    monkeypatch.setattr(workout_templates.yaml, "safe_load", _counting_safe_load)

    first = load_workout_templates(tmp_path)
    assert call_count["n"] == 1
    second = load_workout_templates(tmp_path)
    assert call_count["n"] == 1  # no re-read on the second call
    assert first == second


def test_clear_template_cache_forces_a_fresh_reload(tmp_path, monkeypatch):
    _write(
        tmp_path, "cached.yaml",
        _VALID_YAML.format(
            id="cached-template-2", blocks="base", format_type="straight",
            narrative_template="Main set: {reps} x {rep}m @ Z2 ({z2_range}).",
        ),
    )
    clear_template_cache()

    real_safe_load = yaml.safe_load
    call_count = {"n": 0}

    def _counting_safe_load(*args, **kwargs):
        call_count["n"] += 1
        return real_safe_load(*args, **kwargs)

    monkeypatch.setattr(workout_templates.yaml, "safe_load", _counting_safe_load)

    load_workout_templates(tmp_path)
    assert call_count["n"] == 1
    clear_template_cache()
    load_workout_templates(tmp_path)
    assert call_count["n"] == 2


def test_different_dir_paths_get_independent_cache_entries(tmp_path):
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    _write(
        dir_a, "t.yaml",
        _VALID_YAML.format(
            id="only-in-a", blocks="base", format_type="straight",
            narrative_template="Main set: {reps} x {rep}m @ Z2 ({z2_range}).",
        ),
    )
    _write(
        dir_b, "t.yaml",
        _VALID_YAML.format(
            id="only-in-b", blocks="base", format_type="straight",
            narrative_template="Main set: {reps} x {rep}m @ Z2 ({z2_range}).",
        ),
    )
    clear_template_cache()
    a_templates = load_workout_templates(dir_a)
    b_templates = load_workout_templates(dir_b)
    assert {t.id for t in a_templates} == {"only-in-a"}
    assert {t.id for t in b_templates} == {"only-in-b"}


# --- find_templates: real query function over templates + facets ------------


def test_find_templates_filters_by_purpose():
    threshold_templates = find_templates(purpose="threshold")
    assert len(threshold_templates) == 7
    assert all(t.purpose == "threshold" for t in threshold_templates)


def test_find_templates_filters_by_block():
    base_templates = find_templates(block="base")
    assert {t.id for t in base_templates} == {"base-0-straight", "base-1-broken-distance-lite"}


def test_find_templates_filters_by_modality():
    assert len(find_templates(modality="swim")) == 18
    assert find_templates(modality="strength") == []


def test_find_templates_filters_by_interval_style():
    # Every real template is structurally "straight" (see compute_facets test
    # above) -- interval_style filtering is proven functionally correct here
    # (matches everything / matches nothing), with the EMOM/AMRAP derivation
    # itself proven separately against synthetic structures.
    assert len(find_templates(interval_style="straight")) == 18
    assert find_templates(interval_style="emom") == []
    assert find_templates(interval_style="amrap") == []


def test_find_templates_filters_by_equipment_any():
    # Honest current-content limitation (see TEMPLATE_PREFERENCE_SCHEMA's own
    # doc note in backend/app/tools.py): no real template carries structured
    # equipment yet, so this legitimately matches nothing today -- proves the
    # filter runs without erroring, not that it currently returns anything.
    assert find_templates(equipment_any=["paddles", "kettlebell"]) == []


def test_find_templates_filters_by_max_duration_s():
    # base templates' representative distance budget yields a slightly
    # larger approx_duration_s (1425s) than every build/peak/taper template
    # (1330s) -- see this module's compute_facets tests. A threshold between
    # the two proves the filter actually excludes some but not all templates.
    within_build_budget = find_templates(max_duration_s=1400)
    assert len(within_build_budget) == 16
    assert all(t.applicable_blocks != ["base"] for t in within_build_budget)

    within_everything = find_templates(max_duration_s=2000)
    assert len(within_everything) == 18

    within_nothing = find_templates(max_duration_s=1)
    assert within_nothing == []


def test_find_templates_combination_purpose_and_block():
    sprint_build_templates = find_templates(purpose="sprint_power", block="build")
    assert [t.id for t in sprint_build_templates] == [
        "build-f-straight-repeat-sprints",
        "build-g-straight-kick-and-swim-sprints",
        "build-i-straight-broken-200",
        "build-k-descending-ladder-kick",
    ]


def test_find_templates_no_match_returns_empty_list_not_an_error():
    assert find_templates(purpose="max_strength") == []


def test_find_templates_results_are_sorted_by_id():
    results = find_templates(purpose="threshold")
    assert [t.id for t in results] == sorted(t.id for t in results)


# --- TemplatePreference + _select_main_set_template / build_main_set_step ---


def test_template_preference_is_set_false_when_all_fields_none():
    assert TemplatePreference().is_set() is False


def test_template_preference_is_set_true_when_any_field_given():
    assert TemplatePreference(purpose="threshold").is_set() is True
    assert TemplatePreference(equipment_any=["paddles"]).is_set() is True
    assert TemplatePreference(interval_style="emom").is_set() is True


def test_select_main_set_template_with_preference_narrows_rotation():
    default_pick = workout_templates._select_main_set_template("build", 0)
    assert default_pick.id == "build-0-descend"

    preferred_pick = workout_templates._select_main_set_template(
        "build", 0, TemplatePreference(purpose="sprint_power")
    )
    assert preferred_pick.id == "build-f-straight-repeat-sprints"
    assert preferred_pick.id != default_pick.id


def test_select_main_set_template_preference_matching_nothing_raises():
    with pytest.raises(ValueError, match="no workout templates match"):
        workout_templates._select_main_set_template(
            "base", 0, TemplatePreference(purpose="max_strength")
        )


def test_select_main_set_template_none_preference_behaves_like_no_preference():
    a = workout_templates._select_main_set_template("build", 2, None)
    b = workout_templates._select_main_set_template("build", 2, TemplatePreference())
    assert a.id == b.id


def test_build_main_set_step_with_preference_selects_the_matching_template():
    zones = zone_table(95.0)
    z2, z3, z4 = zones["Z2"], zones["Z3"], zones["Z4"]
    step = build_main_set_step("build", 0, 7, 200, z2, z3, z4, TemplatePreference(purpose="sprint_power"))
    assert "fins-assisted" in step.label
