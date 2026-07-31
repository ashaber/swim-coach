"""Data-driven main-set workout template library.

Splits "how the numbers are computed" (fixed, code-reviewed Python -- this
is where PR #85's independent review caught two real bugs: the pyramid's
`reps<=2` self-contradiction and the ladder's exact-sum arithmetic) from
"what the sentence says" (data -- `engine/swim_coach/workout_templates/
*.yaml`, freely addable without a code change).

ETL workflow for future workout research (e.g. classifying 20-50 researched
masters workouts): classify the workout's main-set *shape* against
`FORMAT_STRATEGIES`' keys (straight, broken_lite, descend, pyramid, ladder,
negative_split, descending_ladder). If one fits, author a new YAML file here -- no code change,
no Python review needed, just the YAML lint test in
`tests/unit/test_workout_templates.py` (which runs the same load-time
validation below against every real file). If none fits -- the workout's
underlying math is a genuinely new shape -- that's a new strategy function
in `FORMAT_STRATEGIES`, a small, reviewed Python change, same rigor as any
other engine logic change. Keep that path rare by reusing an existing
strategy wherever a researched workout's math genuinely matches one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError

from swim_coach.models import (
    Athlete,
    WorkoutRepeat,
    WorkoutStep,
    WorkoutStepOrRepeat,
    WorkoutStructure,
    WorkoutTarget,
)

TEMPLATES_DIR = Path(__file__).parent / "workout_templates"

# The one genuinely subjective, non-derivable WorkoutTemplate field (see this
# module's docstring's Opus-consultation note carried over from the planning
# session): coaching INTENT, not shape -- an 8x200 straight set could be
# aerobic-base or a threshold test; only the template's author knows which.
# Finalized against the real template library's actual content (18 files as
# of this pass): every real `build`/`peak`/`taper` template's Z3->Z4 numeric
# progression reads as either the core threshold-building work (descend/
# pyramid/ladder/negative_split/descending_ladder shapes with no other
# gimmick), an explicitly race-pace-named set, a technique-constrained set
# (breathing pattern, single-stroke focus), or a sprint/power set (fins,
# kick-sprint, explicit "sprint" framing) -- so those four values are all
# real today. `recovery`/`strength_endurance`/`max_strength`/`posterior_chain`
# have no real template yet (no strength WorkoutTemplate/YAML exists in this
# pass -- strength sessions are still authored directly in `plan.py`'s
# `_strength_session_structure_template`), but are kept in the enum since
# they're the plan's own named future categories for that content, not a
# guess -- adding a real strength template later needs no enum-widening PR.
TemplatePurpose = Literal[
    "aerobic_base",
    "threshold",
    "race_pace",
    "technique",
    "sprint_power",
    "recovery",
    "strength_endurance",
    "max_strength",
    "posterior_chain",
]

# Representative sweep used by `load_workout_templates`'s load-time semantic
# validation (see `_validate_template_semantics`) -- covers small/large
# distances (including ones that hit the "not enough budget" rep-length
# fallback branches) and a few CSS paces, for every macro block a template
# claims to apply to.
_VALIDATION_DISTANCES_M = (1000, 1200, 1500, 2000, 2500, 3000, 4000)
_VALIDATION_CSS_PACES_S = (80.0, 95.0, 110.0)
_VALIDATION_SELECTORS = (0, 1, 2, 3, 4, 5)


class WorkoutTemplate(BaseModel):
    """One main-set template: which macro blocks it applies to, which
    computation shape (`format_type`, a `FORMAT_STRATEGIES` key) supplies its
    numbers, and the athlete-facing wording (`narrative_template`) those
    numbers get formatted into.

    `narrative_template` is a plain `str.format()`-style template using ONLY
    the placeholder names its `format_type`'s strategy function guarantees to
    supply -- primitives only (str/int), never evaluated as code.

    `source_note` is informal, free-text provenance (e.g. "adapted from
    researched masters workout: ..."), distinct from `library/`'s formal
    evidence-tagging discipline, which still governs the plan's `Why:` line
    exactly as it does today (unchanged by this module).
    """

    schema_version: int = 1
    id: str
    applicable_blocks: list[Literal["base", "build", "peak", "taper"]]
    format_type: str
    narrative_template: str
    source_note: str | None = None
    purpose: TemplatePurpose
    # `tags` is a narrow escape hatch for long-tail labels that don't fit
    # `purpose`'s coarse coaching-intent categories (e.g. "fins",
    # "usms-sourced") -- NOT the primary query mechanism. `find_templates`
    # only exposes real, mechanically-derived facets (equipment/strokes/
    # interval_style, computed from structure) plus `purpose` as first-class
    # filters; `tags` isn't in `find_templates`' signature on purpose, so it
    # can't silently become the lazy flat-bag answer the Opus consultation
    # rejected -- authors can still tag freely, it just doesn't drive search.
    tags: list[str] = Field(default_factory=list)


def _format_pace_s(pace_s: float) -> str:
    """Format a seconds-per-100m pace as M:SS (e.g. 92.3 -> '1:32').

    Duplicated from `plan.py`'s private helper of the same name: this module
    must not import `plan.py` at module load time (see `_validate_template_
    semantics`'s docstring for why the reverse dependency is deferred/local
    instead), and this formatter is a trivial, stable one-liner with zero
    citation/review weight -- not worth a shared-utils module for.
    """
    total = int(round(pace_s))
    minutes, seconds = divmod(total, 60)
    return f"{minutes}:{seconds:02d}"


def _zone_range(zone: dict) -> str:
    return f"{_format_pace_s(zone['pace_lo_s'])}-{_format_pace_s(zone['pace_hi_s'])}/100m"


# --- FORMAT_STRATEGIES --------------------------------------------------------
# Ported directly from PR #85's `_additional_swim_structure` if/elif branches.
# Each strategy takes the shared preamble's already-computed (reps, rep, zone
# tables, macro_block_name) and returns exactly the placeholder values its
# matching format_type's narrative_template(s) reference, PLUS a reserved
# `_total_m` key (leading underscore -- never referenced by a narrative_
# template, `str.format` silently ignores unused kwargs) reporting the actual
# main-set distance the returned placeholders describe. `_validate_template_
# semantics` uses `_total_m` to verify warm-up + main-set + cool-down sums to
# distance_m for every template, generically, without needing per-format_type
# knowledge of how each shape's numbers reconstruct a total -- this is the
# same invariant PR #85's ladder/pyramid fixes protected.
#
# This is where the real math lives -- keep it fixed, reviewed Python, never
# YAML: PR #85's independent review caught two genuine bugs here (the
# pyramid's reps<=2 self-contradiction, the ladder's exact-sum arithmetic).


def _straight(reps: int, rep: int, z2: dict, z3: dict, z4: dict, macro_block_name: str) -> dict:
    return {"reps": reps, "rep": rep, "z2_range": _zone_range(z2), "_total_m": reps * rep}


def _broken_lite(reps: int, rep: int, z2: dict, z3: dict, z4: dict, macro_block_name: str) -> dict:
    segment = rep // 2
    return {
        "reps": reps,
        "segment": segment,
        "z2_range": _zone_range(z2),
        "_total_m": reps * (segment * 2),
    }


def _descend(reps: int, rep: int, z2: dict, z3: dict, z4: dict, macro_block_name: str) -> dict:
    return {
        "reps": reps,
        "rep": rep,
        "z3_range": _zone_range(z3),
        "z4_range": _zone_range(z4),
        "macro_block_name": macro_block_name,
        "_total_m": reps * rep,
    }


def _pyramid(reps: int, rep: int, z2: dict, z3: dict, z4: dict, macro_block_name: str) -> dict:
    z3_range = _zone_range(z3)
    z4_range = _zone_range(z4)
    if reps <= 2:
        # Degenerate case (independent-review fix carried over from PR #85):
        # a true pyramid needs a rep AFTER the peak to ease back on. With
        # reps<=2, the general `mid = reps // 2 + 1` formula makes `mid`
        # equal to `reps` itself (the peak IS the final rep), which made
        # "ramps up ... and back down to Z3 by the final rep" self-
        # contradictory (the final rep can't be both the peak and the
        # down-ramp). Reachable in production: `NO_COACH_POOL_SESSION_
        # FLOOR_M` yields reps in {1, 2} for build/peak/taper at small
        # distances. Fall back to a simple build-to-peak framing, no
        # "pyramid" language at all.
        pyramid_word = ""
        ramp_clause = (
            f"building from Z3 ({z3_range}) to Z4 ({z4_range}) by the final rep, "
            "each repeat negative-split"
        )
    else:
        mid = reps // 2 + 1
        pyramid_word = " pyramid"
        ramp_clause = (
            f"effort ramps from Z3 ({z3_range}) up to Z4 ({z4_range}) at rep {mid} "
            f"of {reps} and back down to Z3 by the final rep, each repeat negative-split"
        )
    return {
        "reps": reps,
        "rep": rep,
        "pyramid_word": pyramid_word,
        "ramp_clause": ramp_clause,
        "macro_block_name": macro_block_name,
        "_total_m": reps * rep,
    }


def _ladder(reps: int, rep: int, z2: dict, z3: dict, z4: dict, macro_block_name: str) -> dict:
    # Exact by construction: num_pairs*(rep_short+rep_long) + leftover*rep ==
    # num_pairs*2*rep + leftover*rep == reps*rep, since rep_short + rep_long
    # == 2*rep and num_pairs*2 + leftover == reps.
    num_pairs, leftover = divmod(reps, 2)
    rep_short = rep // 2
    rep_long = rep + rep_short
    tail = f", plus 1 x {rep}m capstone rep to finish" if leftover else ""
    total_m = num_pairs * (rep_short + rep_long) + (rep if leftover else 0)
    return {
        "num_pairs": num_pairs,
        "rep_short": rep_short,
        "rep_long": rep_long,
        "tail": tail,
        "z3_range": _zone_range(z3),
        "z4_range": _zone_range(z4),
        "macro_block_name": macro_block_name,
        "_total_m": total_m,
    }


def _negative_split(reps: int, rep: int, z2: dict, z3: dict, z4: dict, macro_block_name: str) -> dict:
    return {
        "reps": reps,
        "rep": rep,
        "z3_range": _zone_range(z3),
        "z4_range": _zone_range(z4),
        "macro_block_name": macro_block_name,
        "_total_m": reps * rep,
    }


def _descending_ladder(reps: int, rep: int, z2: dict, z3: dict, z4: dict, macro_block_name: str) -> dict:
    """A ONE-DIRECTIONAL (monotonically decreasing) ladder of rep lengths --
    e.g. 400m, 300m, 200m, 100m -- distinct from `_ladder` above, which pairs
    a short + long rep per "rung" (100+300, 200+200, ...). Added for PR
    #86's researched-workout ETL: this was the single most-recurring novel
    shape found across real published masters workouts (4 independent
    occurrences -- see `workout_templates/build-j-*`, `build-k-*`, `build-l-*`
    yaml files' `source_note`s), not covered by any existing strategy.

    Fixed 4-rung arithmetic ladder [4u+leftover, 3u, 2u, u], exact by
    construction: 10u + leftover == total_m always (same "exact by
    construction" discipline as `_ladder`'s num_pairs/leftover arithmetic).
    `leftover` is folded into the top (largest) rung, which never disturbs
    the strictly-decreasing order since leftover < 10 <= u whenever u >= 10,
    and even when leftover >= u (small totals), 4u+leftover is still >= 3u
    for any leftover >= 0 -- the sequence stays non-increasing either way.

    Degenerate small-total guard (same class of edge case as `_pyramid`'s
    reps<=2 fallback): if `total_m` is too small to form 4 positive,
    strictly-decreasing rungs (unit == total_m // 10 == 0), collapse to a
    single rep-length "ladder" of just the top rung == total_m, rather than
    emitting zero-length rungs. Reachable in principle at very small
    `NO_COACH_POOL_SESSION_FLOOR_M`-derived budgets, though the real
    production rep floor (100m) keeps total_m >= 100 in practice, well
    above this guard's threshold (total_m < 10).
    """
    total_m = reps * rep
    unit = total_m // 10
    if unit == 0:
        rungs = [total_m] if total_m > 0 else []
    else:
        leftover = total_m - unit * 10
        rungs = [4 * unit + leftover, 3 * unit, 2 * unit, unit]
    rung_list = ", ".join(f"{r}m" for r in rungs)
    return {
        "rung_list": rung_list,
        "num_rungs": len(rungs),
        "z3_range": _zone_range(z3),
        "z4_range": _zone_range(z4),
        "macro_block_name": macro_block_name,
        "_total_m": sum(rungs),
    }


FORMAT_STRATEGIES: dict[str, Callable[[int, int, dict, dict, dict, str], dict]] = {
    "straight": _straight,
    "broken_lite": _broken_lite,
    "descend": _descend,
    "pyramid": _pyramid,
    "ladder": _ladder,
    "negative_split": _negative_split,
    "descending_ladder": _descending_ladder,
}


def _validate_template_semantics(template: WorkoutTemplate, file_path: Path) -> None:
    """Load-time semantic validation standing in for what human/agent review
    caught by hand in PR #85. Renders `template` across a representative
    sweep of `(macro_block_name, distance_m, css_pace_s)` inputs (one per
    `applicable_blocks` entry) and asserts:

    - warm-up + main-set + cool-down sums to `distance_m` exactly, every
      time (the invariant PR #85's ladder/pyramid fixes protected) -- via
      each strategy's reserved `_total_m` key (see `FORMAT_STRATEGIES`'s
      docstring), so this check stays fully generic across format_types.
    - no rendered output contains "Z3"/"Z4" if `"base"` is in
      `applicable_blocks` (the periodization-boundary check).
    - no rendered output contains the substring "library/" (the citation-
      cleanliness rule from PR #83/#84).

    The warm-up/cool-down/rep-length preamble reproduced below mirrors
    `plan.py`'s `_additional_swim_structure` preamble byte-for-byte (import
    of the underlying constants is deferred to call time -- a function-local
    import here, executed well after both modules have fully loaded in every
    real call path, so it never triggers a circular-import error at module
    load time -- see this module's own docstring for the reverse dependency
    plan.py has on this module already).
    """
    from swim_coach.plan import (
        ADDITIONAL_SWIM_BASE_BLOCK_REP_M,
        ADDITIONAL_SWIM_BUILD_BLOCK_REP_M,
        ADDITIONAL_SWIM_COOL_DOWN_SHARE,
        ADDITIONAL_SWIM_MIN_COOL_DOWN_M,
        ADDITIONAL_SWIM_MIN_WARM_UP_M,
        ADDITIONAL_SWIM_WARM_UP_SHARE,
        _round_100,
    )
    from swim_coach.zones import zone_table

    strategy = FORMAT_STRATEGIES[template.format_type]

    for macro_block_name in template.applicable_blocks:
        for distance_m in _VALIDATION_DISTANCES_M:
            for css_pace_s in _VALIDATION_CSS_PACES_S:
                zones = zone_table(css_pace_s)
                z2, z3, z4 = zones["Z2"], zones["Z3"], zones["Z4"]

                warm_up = max(
                    ADDITIONAL_SWIM_MIN_WARM_UP_M,
                    _round_100(distance_m * ADDITIONAL_SWIM_WARM_UP_SHARE),
                )
                cool_down_budget_estimate = max(
                    ADDITIONAL_SWIM_MIN_COOL_DOWN_M,
                    _round_100(distance_m * ADDITIONAL_SWIM_COOL_DOWN_SHARE),
                )
                main_set_budget = max(0, distance_m - warm_up - cool_down_budget_estimate)

                if macro_block_name == "base":
                    rep = ADDITIONAL_SWIM_BASE_BLOCK_REP_M if main_set_budget >= 1200 else 200
                else:
                    rep = ADDITIONAL_SWIM_BUILD_BLOCK_REP_M if main_set_budget >= 800 else 100
                reps = max(1, round(main_set_budget / rep))

                remaining_for_cool_down = distance_m - warm_up - reps * rep
                while (
                    reps > 1
                    and remaining_for_cool_down < ADDITIONAL_SWIM_MIN_COOL_DOWN_M
                    and remaining_for_cool_down + rep >= ADDITIONAL_SWIM_MIN_COOL_DOWN_M
                ):
                    reps -= 1
                    remaining_for_cool_down += rep
                cool_down = max(0, remaining_for_cool_down)

                try:
                    placeholders = strategy(reps, rep, z2, z3, z4, macro_block_name)
                except Exception as exc:  # noqa: BLE001 -- fail fast, name the file
                    raise ValueError(
                        f"{file_path}: format_type {template.format_type!r} strategy raised "
                        f"{exc!r} for block={macro_block_name!r} distance_m={distance_m} "
                        f"css_pace_s={css_pace_s}"
                    ) from exc

                try:
                    rendered = template.narrative_template.format(**placeholders)
                except (KeyError, IndexError) as exc:
                    raise ValueError(
                        f"{file_path}: narrative_template references a placeholder not "
                        f"supplied by format_type {template.format_type!r}: {exc}"
                    ) from exc

                total_m = placeholders["_total_m"]
                total = warm_up + total_m + cool_down
                if total != distance_m:
                    raise ValueError(
                        f"{file_path}: warm-up({warm_up}) + main-set({total_m}) + "
                        f"cool-down({cool_down}) == {total}, expected distance_m == "
                        f"{distance_m} (block={macro_block_name!r}, css_pace_s={css_pace_s})"
                    )

                if macro_block_name == "base" and ("Z3" in rendered or "Z4" in rendered):
                    raise ValueError(
                        f"{file_path}: base-applicable template rendered Z3/Z4 language: "
                        f"{rendered!r}"
                    )
                if "library/" in rendered:
                    raise ValueError(
                        f"{file_path}: rendered output contains internal 'library/' path: "
                        f"{rendered!r}"
                    )


# Module-level cache: `load_workout_templates()` used to re-read + re-validate
# every YAML file on every single call (including every call inside
# `_select_main_set_template`, i.e. every session `generate_week` builds) --
# fine at 6-18 files, real waste once the library grows. Keyed by the
# resolved directory path (not the raw `dir_path` argument, which may be a
# `str` or a relative `Path`) so the real `TEMPLATES_DIR` and any test's own
# `tmp_path` fixture each get their own independent cache entry -- tests that
# build a fresh temp directory per test never see another test's cached
# templates. Facets (see `TemplateFacets` below) are computed once alongside
# the templates themselves and cached in the same entry, never persisted to
# disk (recomputed from the template's structure every time the cache is
# (re)built, per the Opus-consultation "never hand-authored, never persisted"
# rule).
_TEMPLATE_CACHE: dict[Path, tuple[list[WorkoutTemplate], dict[str, "TemplateFacets"]]] = {}


def clear_template_cache() -> None:
    """Test-only escape hatch: drops every cached `(templates, facets)`
    entry so a subsequent `load_workout_templates()`/`load_template_facets()`
    call re-reads from disk. Production code never needs this -- the
    template library is a git-versioned, redeployed-to-pick-up-changes asset,
    not runtime-mutable content (see this module's docstring)."""
    _TEMPLATE_CACHE.clear()


def load_workout_templates(dir_path: Path | str = TEMPLATES_DIR) -> list[WorkoutTemplate]:
    """Parse every `*.yaml` file in `dir_path`, validate via `WorkoutTemplate`,
    then run `_validate_template_semantics` on each -- fails fast with a
    clear, file-identifying error on any violation (malformed YAML, unknown
    `format_type`, a base-applicable template that leaks Z3/Z4 language, a
    template whose strategy doesn't sum to `distance_m`, an internal
    `library/` citation, or a duplicate `id`). Cached per resolved `dir_path`
    after the first call -- see `_TEMPLATE_CACHE` above.
    """
    return _load_templates_and_facets(dir_path)[0]


def load_template_facets(dir_path: Path | str = TEMPLATES_DIR) -> dict[str, "TemplateFacets"]:
    """Every loaded template's computed `TemplateFacets`, keyed by template
    `id`. Same load-and-cache path as `load_workout_templates` (same cache
    entry, so calling both for the same `dir_path` never re-reads/re-computes
    twice)."""
    return _load_templates_and_facets(dir_path)[1]


def _load_templates_and_facets(
    dir_path: Path | str,
) -> tuple[list[WorkoutTemplate], dict[str, "TemplateFacets"]]:
    cache_key = Path(dir_path).resolve()
    cached = _TEMPLATE_CACHE.get(cache_key)
    if cached is not None:
        return cached

    dir_path = Path(dir_path)
    templates: list[WorkoutTemplate] = []
    seen_ids: dict[str, Path] = {}

    for file_path in sorted(dir_path.glob("*.yaml")):
        try:
            raw = yaml.safe_load(file_path.read_text())
        except yaml.YAMLError as exc:
            raise ValueError(f"{file_path}: malformed YAML: {exc}") from exc

        if raw is None:
            raise ValueError(f"{file_path}: empty YAML file")

        try:
            template = WorkoutTemplate.model_validate(raw)
        except ValidationError as exc:
            raise ValueError(f"{file_path}: invalid WorkoutTemplate schema: {exc}") from exc

        if template.format_type not in FORMAT_STRATEGIES:
            raise ValueError(
                f"{file_path}: unknown format_type {template.format_type!r}, must be one "
                f"of {sorted(FORMAT_STRATEGIES)}"
            )

        if template.id in seen_ids:
            raise ValueError(
                f"{file_path}: duplicate template id {template.id!r} (already used by "
                f"{seen_ids[template.id]})"
            )
        seen_ids[template.id] = file_path

        _validate_template_semantics(template, file_path)
        templates.append(template)

    facets = {t.id: compute_facets(t) for t in templates}
    _TEMPLATE_CACHE[cache_key] = (templates, facets)
    return templates, facets


def _select_main_set_template(
    macro_block_name: str,
    selector: int,
    preference: "TemplatePreference | None" = None,
) -> WorkoutTemplate:
    """Shared candidate-selection logic for `render_main_set` and
    `build_main_set_step` -- filter loaded templates to `macro_block_name in
    applicable_blocks`, pick one via `selector % len(candidates)`.

    Candidates are sorted by `id` before the modulo pick -- NOT by YAML
    filesystem/glob order (unstable across platforms) -- so `(macro_block_
    name, selector)` deterministically picks the same template forever, as
    long as `id`s are stable. The shipped ids (`base-0-straight`, `base-1-
    broken-distance-lite`, `build-0-descend`, `build-1-pyramid`, `build-2-
    ladder`, `build-3-negative-split`) are deliberately numbered so their
    alphabetical sort order matches PR #85's original selector->template
    mapping exactly (see `tests/unit/test_plan.py`'s byte-identical
    regression tests).

    `preference` (optional): narrows the candidate pool via `find_templates`
    BEFORE the deterministic `selector % len` rotation applies, so a coach
    request like "more kettlebell work" or "give me a threshold set" can
    actually change which template gets picked instead of only ever landing
    on whatever the blind rotation lands on (see `backend/app/tools.py`'s
    `create_week_plan`/`replace_week_plan` wiring). Raises if the preference
    matches zero templates for this block -- a silent fallback to the
    unfiltered rotation would make an honored-sounding request quietly do
    nothing, which is worse than a clear error.
    """
    if preference is not None and preference.is_set():
        candidates = find_templates(
            block=macro_block_name,
            purpose=preference.purpose,
            equipment_any=preference.equipment_any,
            interval_style=preference.interval_style,
        )
        if not candidates:
            raise ValueError(
                f"no workout templates match {preference!r} for macro block "
                f"{macro_block_name!r}"
            )
        return candidates[selector % len(candidates)]

    templates = load_workout_templates()
    candidates = sorted(
        (t for t in templates if macro_block_name in t.applicable_blocks),
        key=lambda t: t.id,
    )
    if not candidates:
        raise ValueError(f"no workout templates registered for macro block {macro_block_name!r}")
    return candidates[selector % len(candidates)]


def render_main_set(
    macro_block_name: str,
    selector: int,
    reps: int,
    rep: int,
    z2: dict,
    z3: dict,
    z4: dict,
) -> str:
    """Pick a template via `_select_main_set_template`, render it, and return
    the resulting "Main set: ..." line. Unchanged behavior/output from
    before the `WorkoutStructure` migration -- still the direct prose path
    used by `plan.py`'s `_additional_swim_structure`. See `build_main_set_step`
    for the structural (`Session.structured`) counterpart, which reuses this
    exact same selection/rendering so the two can never drift apart.
    """
    template = _select_main_set_template(macro_block_name, selector)
    strategy = FORMAT_STRATEGIES[template.format_type]
    placeholders = strategy(reps, rep, z2, z3, z4, macro_block_name)
    return template.narrative_template.format(**placeholders)


def _build_step_for_template(
    template: WorkoutTemplate,
    macro_block_name: str,
    reps: int,
    rep: int,
    z2: dict,
    z3: dict,
    z4: dict,
) -> WorkoutStep:
    """Render a SPECIFIC, already-selected `template` into the `WorkoutStep`
    representing a swim session's main set. Factored out of
    `build_main_set_step` so `compute_facets` can render a template's
    representative structure directly (a fixed template, not a rotation
    pick) via the exact same, already-reviewed rendering logic -- see that
    function's docstring.

    `target`'s zone anchor is derived structurally from which zone-range
    placeholder `template.narrative_template` actually references
    (`{z4_range}` -> Z4, else `{z3_range}` -> Z3, else `{z2_range}` -> Z2,
    else left untargeted) rather than guessed from `format_type`/
    `macro_block_name` alone: some build-block `straight`/`broken_lite`-
    shaped templates (e.g. `build-f-straight-repeat-sprints`, a fins-assisted
    sprint set) reference no zone range at all, so tagging them Z2 (the
    format_type's OTHER, base-block use) would be actively wrong. This is
    intentionally an approximate, single-zone summary of what may be a
    multi-zone progression (e.g. `descend`'s Z3->Z4 ramp across reps) --
    full per-rep zone fidelity is out of scope for this pass (see module
    docstring's ETL-workflow note and ROADMAP.md's Phase A scoping).
    """
    strategy = FORMAT_STRATEGIES[template.format_type]
    placeholders = strategy(reps, rep, z2, z3, z4, macro_block_name)
    rendered = template.narrative_template.format(**placeholders)
    label = rendered.removeprefix("Main set: ")

    if "{z4_range}" in template.narrative_template:
        target = WorkoutTarget(basis="zone", zone="Z4")
    elif "{z3_range}" in template.narrative_template:
        target = WorkoutTarget(basis="zone", zone="Z3")
    elif "{z2_range}" in template.narrative_template:
        target = WorkoutTarget(basis="zone", zone="Z2")
    else:
        target = None

    return WorkoutStep(
        label=label,
        role="interval",
        duration_kind="distance_m",
        duration_value=placeholders["_total_m"],
        target=target,
        modality="swim",
    )


def build_main_set_step(
    macro_block_name: str,
    selector: int,
    reps: int,
    rep: int,
    z2: dict,
    z3: dict,
    z4: dict,
    preference: "TemplatePreference | None" = None,
) -> WorkoutStep:
    """Build the `WorkoutStep` representing a swim session's main set, for
    `Session.structured`. Reuses `_select_main_set_template` +
    `_build_step_for_template` -- the exact same, already-reviewed machinery
    `render_main_set` uses -- so this step's `label` is guaranteed
    byte-identical to `render_main_set`'s output (minus the "Main set: "
    prefix, which `render_prose`'s role->prefix mapping adds back at render
    time). See `tests/unit/test_workout_templates.py`'s byte-identical
    parity proof.

    `preference`: see `_select_main_set_template`'s docstring -- passed
    straight through, narrows the rotation's candidate pool before the
    `selector % len` pick.
    """
    template = _select_main_set_template(macro_block_name, selector, preference)
    return _build_step_for_template(template, macro_block_name, reps, rep, z2, z3, z4)


# --- TemplateFacets: mechanically-derived, never-hand-authored metadata ------
# Per the Opus-consultation writeup (module docstring / plan file): equipment,
# stroke(s)/medley-ness, and interval shape (including EMOM/AMRAP) are all
# read directly off a `WorkoutStructure` tree instead of hand-typed --
# hand-tagging them would duplicate data that can (and will) drift from the
# template's actual content. Computed at load time (`load_template_facets`,
# cached alongside `load_workout_templates`), NEVER persisted to disk --
# recomputed from the template's structure every time the cache is rebuilt.


class TemplateFacets(BaseModel):
    """Computed, never-hand-authored metadata derived from a
    `WorkoutTemplate`'s REPRESENTATIVE `WorkoutStructure` (see
    `compute_facets`) -- the queryable "shape" dimensions `find_templates`
    filters on, distinct from `purpose` (the one hand-authored, subjective
    field) and `tags` (the narrow escape hatch).

    `approx_distance_m`/`approx_duration_s` are deliberately approximate: a
    template's real reps/rep are parametric, resolved only against one
    athlete's actual session budget at `generate_week()` time (see
    `resolve_template`) -- these facets are computed from ONE fixed
    representative `(macro_block_name, distance_m, css_pace_s)` input per
    template (see `_FACET_REPRESENTATIVE_*` below), suitable for a coarse
    filtering band (`find_templates`' `max_duration_s`), not exact-minute
    matching -- exact filtering only makes sense on a *resolved* workout.
    """

    schema_version: int = 1
    modality: Literal["swim", "strength"] = "swim"
    equipment: list[str] = Field(default_factory=list)
    strokes: list[str] = Field(default_factory=list)
    is_medley: bool = False
    # Derived from `WorkoutRepeat.repeat_mode`, NOT `format_type` -- the
    # "narrow enum wall" finding: `format_type` is an authoring-time
    # computation hint, and the masters-workout research already found real
    # shapes it can't name; `interval_style` derived from the actual
    # structure tree doesn't hit that wall. "straight" means no
    # `WorkoutRepeat` appears anywhere in the structure at all (every real
    # template shipped in this pass -- `build_main_set_step` emits a single
    # flat `WorkoutStep`, never a repeat wrapper).
    interval_style: Literal["straight", "intervals", "emom", "amrap"] = "straight"
    approx_distance_m: float | None = None
    approx_duration_s: float | None = None


class TemplatePreference(BaseModel):
    """Optional coach-driven override for `_select_main_set_template`'s
    default blind `selector % len` rotation -- the tool-layer's way of
    honoring a request like "give me more kettlebell work" or "a threshold
    set this week" instead of only ever getting whatever the rotation lands
    on. All fields optional and AND-combined via `find_templates` (same
    semantics as that function's own params) -- `modality`/`block`/
    `max_duration_s` are deliberately NOT exposed here: modality is always
    "swim" for this call path, block is already known internally
    (`macro_block_name`), and duration doesn't make sense as a preference
    mid-generation (distance/duration are athlete- and budget-driven, not a
    coach dial). See `backend/app/tools.py`'s `create_week_plan`/
    `replace_week_plan` wiring for the actual tool-facing surface.
    """

    schema_version: int = 1
    purpose: TemplatePurpose | None = None
    equipment_any: list[str] | None = None
    interval_style: Literal["straight", "intervals", "emom", "amrap"] | None = None

    def is_set(self) -> bool:
        """True if at least one filter is actually populated -- lets
        `_select_main_set_template` treat an all-`None` `TemplatePreference`
        exactly like `preference=None` (fall through to the unfiltered
        rotation) rather than needlessly routing through `find_templates`.
        """
        return self.purpose is not None or self.equipment_any is not None or self.interval_style is not None


def _walk_steps(items: list[WorkoutStepOrRepeat]) -> list[WorkoutStep]:
    """Flatten a `WorkoutStructure`'s top-level `items` into every leaf
    `WorkoutStep`, descending into `WorkoutRepeat.steps` recursively (nested
    repeats are allowed, if rarely used -- see `WorkoutRepeat`'s own
    docstring)."""
    steps: list[WorkoutStep] = []
    for item in items:
        if isinstance(item, WorkoutStep):
            steps.append(item)
        else:
            steps.extend(_walk_steps(item.steps))
    return steps


def _top_level_repeat_modes(items: list[WorkoutStepOrRepeat]) -> list[str]:
    """Every `repeat_mode` used by a top-level (or one-level-nested, per
    `WorkoutRepeat`'s "nested loops allowed, rarely used" note) `WorkoutRepeat`
    in `items` -- drives `interval_style`'s derivation. Deliberately does NOT
    recurse arbitrarily deep: a genuinely multi-level-nested repeat structure
    is out of scope for this pass's real content (every real template ships
    zero repeats at all; the EMOM/AMRAP derivation is proven against
    synthetic structures -- see `tests/unit/test_workout_templates.py`)."""
    modes: list[str] = []
    for item in items:
        if isinstance(item, WorkoutRepeat):
            modes.append(item.repeat_mode)
            modes.extend(inner.repeat_mode for inner in item.steps if isinstance(inner, WorkoutRepeat))
    return modes


# Representative pace used only to convert a distance-based step's meters
# into an approximate seconds estimate for `TemplateFacets.approx_duration_s`
# (so `find_templates`' `max_duration_s` filter has something meaningful to
# compare against even though every real template today is authored in
# distance_m, not time_s) -- Coach judgment, a mid-pack CSS pace, not tied to
# any specific athlete (this is a template-level, not athlete-level, estimate;
# see `resolve_template` for the real per-athlete resolution).
_FACET_REPRESENTATIVE_CSS_PACE_S = 95.0
_FACET_REPRESENTATIVE_DISTANCE_M = 2000


def facets_from_structure(structure: WorkoutStructure) -> TemplateFacets:
    """Pure derivation of `TemplateFacets` from an already-built
    `WorkoutStructure` -- no template/YAML/FORMAT_STRATEGIES involvement at
    all, so this is directly testable against hand-built synthetic
    structures (including EMOM/AMRAP-shaped `WorkoutRepeat` trees no real
    shipped template uses yet -- see this repo's test suite). `compute_facets`
    below is the only production caller, feeding it a template's
    representative structure.

    Repeat-count-aware distance/duration aggregation: a `count`-mode
    repeat's inner total is multiplied by its `count` (e.g. 3x100m is 300m,
    not 100m); a `for_duration`/`amrap` repeat's contribution is just its own
    fixed `duration_s` window, NOT its inner steps multiplied by anything --
    the number of rounds inside is genuinely open-ended (AMRAP by definition;
    EMOM's round count depends on how fast each round is actually completed),
    so summing/multiplying inner-step distances for those two modes would
    invent a number nothing in the model actually claims.
    """
    steps = _walk_steps(structure.items)

    equipment = sorted({e for s in steps for e in s.equipment})
    strokes = sorted({s.stroke for s in steps if s.stroke is not None})
    real_strokes = {s for s in strokes if s in ("free", "back", "breast", "fly")}
    is_medley = "im" in strokes or "mixed" in strokes or len(real_strokes) > 1

    repeat_modes = _top_level_repeat_modes(structure.items)
    if "amrap" in repeat_modes:
        interval_style: Literal["straight", "intervals", "emom", "amrap"] = "amrap"
    elif "for_duration" in repeat_modes:
        # for_duration + interval_s is the classic EMOM signature ("every
        # minute on the minute") -- for_duration without an explicit
        # interval_s is still round-per-fixed-window shaped, not a plain
        # count repeat, so it's grouped under the same "emom" facet value
        # rather than adding a rarely-useful fifth interval_style value.
        interval_style = "emom"
    elif "count" in repeat_modes:
        interval_style = "intervals"
    else:
        interval_style = "straight"

    modalities = {s.modality for s in steps}
    modality: Literal["swim", "strength"] = "strength" if modalities == {"strength"} else "swim"

    distance_m, duration_s = _aggregate_distance_and_duration(structure.items)
    # Convert any pure-distance contribution into an additional duration
    # estimate at the representative pace, so distance-authored templates
    # (every real one, today) still get a meaningful approx_duration_s.
    duration_s += (distance_m / 100.0) * _FACET_REPRESENTATIVE_CSS_PACE_S

    return TemplateFacets(
        modality=modality,
        equipment=equipment,
        strokes=strokes,
        is_medley=is_medley,
        interval_style=interval_style,
        approx_distance_m=distance_m or None,
        approx_duration_s=duration_s or None,
    )


def _aggregate_distance_and_duration(items: list[WorkoutStepOrRepeat]) -> tuple[float, float]:
    """Repeat-count-aware (distance_m, duration_s) totals for `items` -- see
    `facets_from_structure`'s docstring for the count-vs-for_duration/amrap
    distinction."""
    distance_m = 0.0
    duration_s = 0.0
    for item in items:
        if isinstance(item, WorkoutStep):
            if item.duration_kind == "distance_m" and item.duration_value:
                distance_m += item.duration_value
            elif item.duration_kind == "time_s" and item.duration_value:
                duration_s += item.duration_value
        else:
            if item.repeat_mode == "count":
                inner_distance, inner_duration = _aggregate_distance_and_duration(item.steps)
                count = item.count or 1
                distance_m += inner_distance * count
                duration_s += inner_duration * count
            else:
                # for_duration/amrap: the window itself is the contribution,
                # inner rounds are genuinely open-ended (see docstring above).
                duration_s += item.duration_s or 0.0
    return distance_m, duration_s


def compute_facets(template: WorkoutTemplate) -> TemplateFacets:
    """Build a template's ONE representative `WorkoutStructure` (a fixed
    `(macro_block_name, distance_m, css_pace_s)` input -- see
    `_FACET_REPRESENTATIVE_*` -- since a template's real reps/rep are only
    known once resolved against an athlete's actual session budget) and
    derive its `TemplateFacets` from that. `macro_block_name` is the
    template's own `applicable_blocks[0]` (representative -- every real
    template's block-set doesn't change the shape it renders, only the
    wording's "(build block)"/"(peak block)"/"(taper block)" suffix and the
    base-vs-build/peak/taper rep-length constants, so any one applicable
    block is a fair representative).

    Duplicates the warm-up/cool-down/main-set-budget preamble already
    duplicated (deliberately, per this module's own docstring on the
    deferred-import reasoning) by `_validate_template_semantics` and
    `plan.py`'s `_additional_swim_structure_template` -- same reasoning
    applies a third time here: importing `plan.py` at module load time would
    be circular (`plan.py` imports this module), so the import is deferred
    to call time, same as those two existing call sites.
    """
    from swim_coach.plan import (
        ADDITIONAL_SWIM_BASE_BLOCK_REP_M,
        ADDITIONAL_SWIM_BUILD_BLOCK_REP_M,
        ADDITIONAL_SWIM_COOL_DOWN_SHARE,
        ADDITIONAL_SWIM_MIN_COOL_DOWN_M,
        ADDITIONAL_SWIM_MIN_WARM_UP_M,
        ADDITIONAL_SWIM_WARM_UP_SHARE,
        _round_100,
    )
    from swim_coach.zones import zone_table

    macro_block_name = template.applicable_blocks[0]
    distance_m = _FACET_REPRESENTATIVE_DISTANCE_M
    css_pace_s = _FACET_REPRESENTATIVE_CSS_PACE_S
    zones = zone_table(css_pace_s)
    z2, z3, z4 = zones["Z2"], zones["Z3"], zones["Z4"]

    warm_up = max(ADDITIONAL_SWIM_MIN_WARM_UP_M, _round_100(distance_m * ADDITIONAL_SWIM_WARM_UP_SHARE))
    cool_down_budget_estimate = max(
        ADDITIONAL_SWIM_MIN_COOL_DOWN_M, _round_100(distance_m * ADDITIONAL_SWIM_COOL_DOWN_SHARE)
    )
    main_set_budget = max(0, distance_m - warm_up - cool_down_budget_estimate)

    if macro_block_name == "base":
        rep = ADDITIONAL_SWIM_BASE_BLOCK_REP_M if main_set_budget >= 1200 else 200
    else:
        rep = ADDITIONAL_SWIM_BUILD_BLOCK_REP_M if main_set_budget >= 800 else 100
    reps = max(1, round(main_set_budget / rep))

    step = _build_step_for_template(template, macro_block_name, reps, rep, z2, z3, z4)
    return facets_from_structure(WorkoutStructure(items=[step]))


def find_templates(
    *,
    purpose: str | None = None,
    modality: str | None = None,
    block: str | None = None,
    max_duration_s: float | None = None,
    equipment_any: list[str] | None = None,
    interval_style: str | None = None,
) -> list[WorkoutTemplate]:
    """The coach's real query hook over the loaded template library +
    computed `TemplateFacets` (DOD: "coach can find these workouts and apply
    to right place in macro/week") -- replaces the previous
    "nothing lets the chat layer ask for a specific kind of workout, only
    blind `selector % count` rotation" gap.

    Every parameter is optional and AND-combined (omit a param to not filter
    on it); returns `[]` if nothing matches rather than raising -- callers
    that need "no match" to be an error (e.g. `_select_main_set_template`
    honoring an explicit `TemplatePreference`) check for an empty result
    themselves. Results are sorted by `id` (same deterministic order
    `_select_main_set_template` already relies on for its rotation).

    - `purpose`: exact match against `WorkoutTemplate.purpose`.
    - `modality`: exact match against the template's representative
      `TemplateFacets.modality` (every real template today is "swim" -- no
      strength `WorkoutTemplate`/YAML exists yet).
    - `block`: `block in template.applicable_blocks`.
    - `max_duration_s`: keep templates whose `TemplateFacets.approx_duration_s`
      is populated and `<= max_duration_s` (an approximate band -- see
      `TemplateFacets`' own caveat; a template with no computed duration
      estimate is excluded rather than assumed to pass).
    - `equipment_any`: keep templates whose `TemplateFacets.equipment` shares
      at least one item with `equipment_any`.
    - `interval_style`: exact match against `TemplateFacets.interval_style`.
    """
    templates = load_workout_templates()
    facets_by_id = load_template_facets()

    results = []
    for template in templates:
        if purpose is not None and template.purpose != purpose:
            continue
        if block is not None and block not in template.applicable_blocks:
            continue

        facets = facets_by_id[template.id]
        if modality is not None and facets.modality != modality:
            continue
        if max_duration_s is not None and (
            facets.approx_duration_s is None or facets.approx_duration_s > max_duration_s
        ):
            continue
        if equipment_any and not (set(equipment_any) & set(facets.equipment)):
            continue
        if interval_style is not None and facets.interval_style != interval_style:
            continue

        results.append(template)

    return sorted(results, key=lambda t: t.id)


_ROLE_LINE_PREFIX: dict[str, str] = {
    "warmup": "Warm-up: ",
    "interval": "Main set: ",
    "cooldown": "Cool-down: ",
}
# Athlete-facing line prefixes for `render_prose` -- covers every role a real
# swim session step uses today. Any other role (e.g. "open" section headers/
# "Why:" lines, or a bare strength exercise) falls through to render_prose's
# own generic handling below -- this map is intentionally NOT exhaustive over
# the full WorkoutStep.role Literal.


def _render_step_line(step: WorkoutStep) -> str:
    """One rendered line for a single `WorkoutStep`, used both for a
    top-level step and for a step nested inside a `WorkoutRepeat` (see
    `render_prose`). `role="open"` steps render their `label` verbatim (used
    for section headers and the trailing "Why: ..." line -- text that isn't
    really "workout structure," just athlete-facing prose carried on the
    step so the whole session's text lives in one place); a role with a
    prefix in `_ROLE_LINE_PREFIX` (warmup/interval/cooldown) gets that
    prefix; anything else (e.g. a strength exercise's `role="steady"`)
    renders as a "  - " bullet, matching `_strength_session_structure`'s
    original bullet-list formatting exactly.
    """
    if step.role == "open":
        return step.label
    prefix = _ROLE_LINE_PREFIX.get(step.role, "")
    if prefix:
        return f"{prefix}{step.label}"
    return f"  - {step.label}"


def render_prose(structured: WorkoutStructure) -> str:
    """Render a `WorkoutStructure` (template or resolved workout -- prose
    rendering doesn't depend on a target/load's `basis`) into the exact same
    "Warm-up: ...\\nMain set: ...\\nCool-down: ...\\nWhy: ..." (swim) or
    header + bulleted-exercise-list (strength) prose shape today's hardcoded
    `plan.py` functions produce -- see `tests/unit/test_workout_templates.py`
    and `tests/unit/test_plan.py`'s byte-identical parity proofs.

    Deliberately generic: driven entirely by each step's `role` via
    `_render_step_line`, never by `format_type` or any other per-template
    knowledge -- `render_prose` has zero awareness of `FORMAT_STRATEGIES`/
    `narrative_template`. All of that bespoke-wording complexity is baked
    into each step's `label` once, at template-build time (see
    `build_main_set_step` / `plan.py`'s `_strength_session_structure_template`),
    which is what keeps this renderer simple and reusable across both
    modalities instead of needing a parallel per-format_type branch here too.

    A top-level `WorkoutRepeat` renders each of its inner steps as its own
    line (one level of nesting -- real templates this pass ships never nest
    a `WorkoutRepeat` inside a `WorkoutRepeat`); a section header for a
    repeat (e.g. "Rotator-cuff / scapular-stability core (2 sets x 10 reps
    each):") is its own preceding `role="open"` step, not part of the repeat
    itself (`WorkoutRepeat` has no label/title field -- see models.py).
    """
    lines: list[str] = []
    for item in structured.items:
        if isinstance(item, WorkoutStep):
            lines.append(_render_step_line(item))
        else:
            for inner in item.steps:
                lines.append(_render_step_line(inner))
    return "\n".join(lines)


def resolve_template(structured: WorkoutStructure, athlete: Athlete) -> WorkoutStructure:
    """The ONE place a `WorkoutStructure` template's relative targets get
    resolved into an athlete-specific workout's absolute ones -- reuses
    `zones.zone_table` (the same CSS-anchored zone math `zones.py` already
    used to resolve Z1-Z5 into absolute pace, made explicit/uniform here)
    for `WorkoutTarget.basis in ("zone", "percent_css")`, and an optional
    per-exercise 1RM lookup (`athlete.constraints["one_rm_kg"]`, a `dict[str,
    float]` keyed by `WorkoutStep.exercise_name` -- `constraints` is already
    a free-form per-athlete dict, so this needs no `Athlete` model change)
    for `WorkoutLoad.basis == "percent_1rm"`.

    No real template this pass ships uses `percent_1rm` -- every strength
    exercise in `plan.py`'s `_strength_session_structure_template` is
    `basis="bodyweight"` (band/bodyweight rotator-cuff and full-body work,
    no per-exercise 1RM data collected anywhere yet) -- so that branch is a
    documented no-op on real production content today, exercised directly by
    synthetic unit tests instead (see `tests/unit/test_workout_templates.py`).

    Non-relative bases (`absolute`, `rpe`, `rpe_only`, `open`, `bodyweight`)
    and `None` targets/loads pass through unchanged. Returns a new
    `WorkoutStructure` (via `model_copy`) -- never mutates `structured`.
    """
    # Deferred import: DEFAULT_CSS_PACE_S_PER_100M lives in plan.py, which
    # imports render_main_set/build_main_set_step from this module at load
    # time -- a top-level import here would be circular. Same pattern
    # already used by `_validate_template_semantics` above.
    from swim_coach.plan import DEFAULT_CSS_PACE_S_PER_100M
    from swim_coach.zones import zone_table

    css = athlete.css_pace_s_per_100m or DEFAULT_CSS_PACE_S_PER_100M
    zones = zone_table(css)
    one_rm_kg: dict = athlete.constraints.get("one_rm_kg") or {}

    def _resolve_target(target: WorkoutTarget | None) -> WorkoutTarget | None:
        if target is None:
            return None
        if target.basis == "zone":
            z = zones[target.zone]
            return target.model_copy(
                update={"basis": "absolute", "low": z["pace_lo_s"], "high": z["pace_hi_s"]}
            )
        if target.basis == "percent_css":
            low = css * (target.low / 100) if target.low is not None else None
            high = css * (target.high / 100) if target.high is not None else None
            return target.model_copy(update={"basis": "absolute", "low": low, "high": high})
        return target

    def _resolve_load(load, exercise_name: str | None):
        if load is None or load.basis != "percent_1rm":
            return load
        base = one_rm_kg.get(exercise_name) if exercise_name else None
        if base is None or load.value is None:
            return load
        return load.model_copy(update={"basis": "absolute", "value": base * (load.value / 100)})

    def _resolve_item(item: WorkoutStep | WorkoutRepeat) -> WorkoutStep | WorkoutRepeat:
        if isinstance(item, WorkoutStep):
            return item.model_copy(
                update={
                    "target": _resolve_target(item.target),
                    "load": _resolve_load(item.load, item.exercise_name),
                }
            )
        return item.model_copy(update={"steps": [_resolve_item(s) for s in item.steps]})

    return structured.model_copy(update={"items": [_resolve_item(i) for i in structured.items]})
