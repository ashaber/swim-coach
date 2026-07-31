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
from pydantic import BaseModel, ValidationError

TEMPLATES_DIR = Path(__file__).parent / "workout_templates"

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


def load_workout_templates(dir_path: Path | str = TEMPLATES_DIR) -> list[WorkoutTemplate]:
    """Parse every `*.yaml` file in `dir_path`, validate via `WorkoutTemplate`,
    then run `_validate_template_semantics` on each -- fails fast with a
    clear, file-identifying error on any violation (malformed YAML, unknown
    `format_type`, a base-applicable template that leaks Z3/Z4 language, a
    template whose strategy doesn't sum to `distance_m`, an internal
    `library/` citation, or a duplicate `id`).
    """
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

    return templates


def render_main_set(
    macro_block_name: str,
    selector: int,
    reps: int,
    rep: int,
    z2: dict,
    z3: dict,
    z4: dict,
) -> str:
    """Filter loaded templates to `macro_block_name in applicable_blocks`,
    pick one via `selector % len(candidates)`, render it, and return the
    resulting "Main set: ..." line.

    Candidates are sorted by `id` before the modulo pick -- NOT by YAML
    filesystem/glob order (unstable across platforms) -- so `(macro_block_
    name, selector)` deterministically picks the same template forever, as
    long as `id`s are stable. The shipped ids (`base-0-straight`, `base-1-
    broken-distance-lite`, `build-0-descend`, `build-1-pyramid`, `build-2-
    ladder`, `build-3-negative-split`) are deliberately numbered so their
    alphabetical sort order matches PR #85's original selector->template
    mapping exactly (see `tests/unit/test_plan.py`'s byte-identical
    regression tests).
    """
    templates = load_workout_templates()
    candidates = sorted(
        (t for t in templates if macro_block_name in t.applicable_blocks),
        key=lambda t: t.id,
    )
    if not candidates:
        raise ValueError(f"no workout templates registered for macro block {macro_block_name!r}")

    template = candidates[selector % len(candidates)]
    strategy = FORMAT_STRATEGIES[template.format_type]
    placeholders = strategy(reps, rep, z2, z3, z4, macro_block_name)
    return template.narrative_template.format(**placeholders)
