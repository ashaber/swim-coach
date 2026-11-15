"""Swim workout builders: the shared warm-up / main-set / cool-down frame and the registered archetypes."""

from __future__ import annotations

import uuid
from typing import Callable

from swim_coach.formatting import format_pace_s, round_100
from swim_coach.models import Athlete, WorkoutRepeat, WorkoutStep, WorkoutStructure, WorkoutTarget
from swim_coach.ow_session_templates import build_ow_session, list_ow_session_templates
from swim_coach.stimulus import StimulusKind, profile_for
from swim_coach.workout_builders.compile import measure_dose, structure_totals
from swim_coach.workout_builders.intent import WorkoutIntent
from swim_coach.workout_builders.registry import BuildResult, ParamRange, WorkoutBuilder, register, register_loader
from swim_coach.workout_templates import (
    TemplatePreference,
    build_main_set_step,
    find_templates,
    load_workout_templates,
    resolve_template,
)
from swim_coach.zones import zone_table

ADDITIONAL_SWIM_WARM_UP_SHARE = 0.2
ADDITIONAL_SWIM_COOL_DOWN_SHARE = 0.1
ADDITIONAL_SWIM_MIN_WARM_UP_M = 200
ADDITIONAL_SWIM_MIN_COOL_DOWN_M = 100
# Coach judgment / practitioner convention -- library/14-swim-set-structure.md
# ("Session skeleton" section) is explicit that no citable source fixes a
# warm-up or cool-down proportion; McGowan et al. (2015) grounds only that a
# warm-up is worthwhile, not its size. This governs ONLY the "additional"
# pool-independent swim_ow session below -- the Saturday long-swim session
# (library/06-long-swim-progression.md) stays continuous/negative-split and
# is untouched by these constants.

ADDITIONAL_SWIM_BASE_BLOCK_REP_M = 300
ADDITIONAL_SWIM_BUILD_BLOCK_REP_M = 200
# Coach judgment -- main-set rep length for the two main-set formats below.
# library/14-swim-set-structure.md's "Main-set format menu" section is
# explicit that no source ranks these formats; the base-vs-build/peak/taper
# *emphasis* shift itself is [EVIDENCE: swim] (González-Ravé et al. 2021;
# Pla et al. 2019), the concrete rep length is not.

# The size of each block-category's main-set format menu (base: 2, build/
# peak/taper: 4, as of this writing) is no longer a fixed constant here --
# it's however many templates `engine/swim_coach/workout_templates/*.yaml`
# ships for that block, read by `swim_coach.workout_templates.
# render_main_set` at render time. All format *choices* are Coach judgment
# per library/14-swim-set-structure.md's "Main-set format menu" section
# ("straight aerobic repeats, descending sets, broken-distance/pyramid sets,
# and negative-split segments are the shared vocabulary of pool coaching ...
# offered as legitimate, standard coaching options" -- that file is explicit
# no source ranks one format as superior). `_additional_swim_structure`'s
# `selector` picks among the applicable templates via `selector % <count>`,
# deterministically -- same block + same selector always yields the same
# template, forever (no random/global state), which is what makes this
# rotation safe to unit-test and audit.


def _additional_swim_structure_template(
    macro_block_name: str,
    distance_m: int,
    css_pace_s: float,
    selector: int = 0,
    template_preference: TemplatePreference | None = None,
) -> WorkoutStructure:
    """Build the `WorkoutStructure` TEMPLATE for the "additional"
    pool-independent aerobic swim_ow session -- the structural counterpart
    to `_additional_swim_structure`'s prose (see that function's own
    docstring for the full warm-up/cool-down/main-set-format-menu rationale
    and citations, which is unchanged here). Callers must guard
    `distance_m <= 0` themselves (mirroring `_additional_swim_structure`'s
    own early return) -- there's no meaningful `WorkoutStructure` for "no
    additional volume this week."

    The warm-up/cool-down steps' `label`s are built here using the SAME
    concrete, already-CSS-resolved `z2`/`z3`/`z4` zone dicts as the legacy
    prose function (every real call site already has the athlete's CSS
    available at this point -- see `generate_week`) -- this is what
    guarantees byte-identical prose without duplicating the warm-up/
    cool-down text-formatting logic a second time. Each step's `target`
    field nonetheless stays the relative `basis="zone"` marker (not the
    resolved pace numbers already reflected in its label) until
    `workout_templates.resolve_template` is called -- `render_prose` never
    reads `target`, so this doesn't affect the prose parity proof, and it
    keeps the model's relative/resolved distinction real for any consumer
    (e.g. a future Garmin export) that DOES read `target`.
    """
    zones = zone_table(css_pace_s)
    z2, z3, z4 = zones["Z2"], zones["Z3"], zones["Z4"]

    warm_up = max(
        ADDITIONAL_SWIM_MIN_WARM_UP_M, round_100(distance_m * ADDITIONAL_SWIM_WARM_UP_SHARE)
    )
    # Sized only to choose a sensible rep length / rep count below -- the
    # actual cool-down (and therefore the session's true total) is
    # reconciled after reps are picked, so warm-up + main set + cool-down
    # always sums exactly to `distance_m` instead of drifting by a rep's
    # worth of rounding (a real bug in an earlier version of this function:
    # rounding `main_set_total / rep` to the nearest rep, without feeding
    # that rounding back into the cool-down, could over- or under-state the
    # printed session total by up to one rep length relative to distance_m).
    cool_down_budget_estimate = max(
        ADDITIONAL_SWIM_MIN_COOL_DOWN_M, round_100(distance_m * ADDITIONAL_SWIM_COOL_DOWN_SHARE)
    )
    main_set_budget = max(0, distance_m - warm_up - cool_down_budget_estimate)

    z2_range = f"{format_pace_s(z2['pace_lo_s'])}-{format_pace_s(z2['pace_hi_s'])}/100m"
    warmup_step = WorkoutStep(
        label=f"{warm_up}m easy, building to Z2 pace ({z2_range}) by the end.",
        role="warmup",
        duration_kind="distance_m",
        duration_value=warm_up,
        target=WorkoutTarget(basis="zone", zone="Z2"),
        modality="swim",
    )

    if macro_block_name == "base":
        rep = ADDITIONAL_SWIM_BASE_BLOCK_REP_M if main_set_budget >= 1200 else 200
    else:
        rep = ADDITIONAL_SWIM_BUILD_BLOCK_REP_M if main_set_budget >= 800 else 100
    reps = max(1, round(main_set_budget / rep))

    remaining_for_cool_down = distance_m - warm_up - reps * rep
    # If rounding pushed the main set to consume (almost) everything,
    # give back one rep so the cool-down doesn't collapse toward 0m.
    while (
        reps > 1
        and remaining_for_cool_down < ADDITIONAL_SWIM_MIN_COOL_DOWN_M
        and remaining_for_cool_down + rep >= ADDITIONAL_SWIM_MIN_COOL_DOWN_M
    ):
        reps -= 1
        remaining_for_cool_down += rep
    cool_down = max(0, remaining_for_cool_down)

    # Template menu selection + rendering is fully data-driven -- see
    # `swim_coach.workout_templates` (the `WorkoutTemplate` YAML library,
    # `FORMAT_STRATEGIES`, and `build_main_set_step`'s deterministic
    # `selector % <template count>` rotation, same contract as before this
    # migration).
    main_set_step = build_main_set_step(
        macro_block_name, selector, reps, rep, z2, z3, z4, template_preference
    )

    cooldown_step = WorkoutStep(
        label=f"{cool_down}m easy choice of stroke.",
        role="cooldown",
        duration_kind="distance_m",
        duration_value=cool_down,
        modality="swim",
    )

    if macro_block_name == "base":
        why_label = "Why: continuous aerobic-volume emphasis (base-block phase)."
    else:
        why_label = (
            "Why: race-pace-adjacent, broken-distance emphasis -- evidence-based "
            "phase shift (González-Ravé et al. 2021; Pla et al. 2019)."
        )
    why_step = WorkoutStep(label=why_label, role="open", duration_kind="open", modality="swim")

    return WorkoutStructure(items=[warmup_step, main_set_step, cooldown_step, why_step])


# --- registered archetypes (the workout compiler's swim builders) ---------------------------------
#
# Ranges and the css_threshold default rest are Coach judgment (library/14-swim-set-structure.md,
# "Workout compiler: explicit-reps ranges"); targets always resolve through `resolve_template`.
SWIM_POOL_DISTANCE_RANGE = ParamRange(1000, 10000, "metres")
SWIM_OW_DISTANCE_RANGE = ParamRange(500, 30000, "metres")
SWIM_TOTAL_MIN_RANGE = ParamRange(10, 600, "minutes")
SWIM_REPS_RANGE = ParamRange(1, 40)
SWIM_REP_DISTANCE_RANGE = ParamRange(25, 1600, "metres")
SWIM_REST_S_RANGE = ParamRange(0, 300, "seconds")
SWIM_ENDURANCE_ZONE_RANGE = ParamRange(1, 2, "Z1-Z2")
CSS_THRESHOLD_ZONE = "Z4"
CSS_THRESHOLD_DEFAULT_REST_S = 20.0
_PURPOSE_FALLBACK_ZONE = {"sprint_power": "Z5"}
_SWIM_POOL = frozenset({"swim_pool"})
_SWIM_OW = frozenset({"swim_ow"})
_SWIM_BOTH = _SWIM_POOL | _SWIM_OW


def _default_css() -> float:
    from swim_coach.plan import DEFAULT_CSS_PACE_S_PER_100M

    return DEFAULT_CSS_PACE_S_PER_100M


def _css_for(athlete: Athlete, adj: list[str]) -> float:
    """The athlete's CSS, or the engine default with a note (targets then stay zone-only)."""
    if athlete.css_pace_s_per_100m:
        return athlete.css_pace_s_per_100m
    css = _default_css()
    adj.append(
        f"no CSS on file: targets are zone-only (Z1-Z5, no pace numbers); step labels and the duration "
        f"estimate use a default CSS of {css:g} s/100m"
    )
    return css


def _finish(structure: WorkoutStructure, athlete: Athlete, css: float, intensity: dict, adj: list[str]) -> BuildResult:
    """Resolve zone targets against CSS (when known) and estimate the duration when it is not."""
    from swim_coach.workout_templates import resolve_template

    if athlete.css_pace_s_per_100m:
        return BuildResult(structure=resolve_template(structure, athlete), intensity=intensity, adjustments=adj)
    probe = athlete.model_copy(update={"css_pace_s_per_100m": css})
    minutes, _ = structure_totals(structure, probe, profile_for("swim_pool"))
    return BuildResult(structure=structure, intensity=intensity, adjustments=adj, duration_min=minutes)


def _size_distance(intent: WorkoutIntent, css: float, rng: ParamRange, adj: list[str]) -> int | None:
    """Total metres: as asked, or sized from a duration at Z2 pace (recorded), clamped into `rng`."""
    if intent.total_distance_m:
        return int(rng.clamp("total_distance_m", intent.total_distance_m, adj))
    if not intent.total_duration_min:
        return None
    z2 = zone_table(css)["Z2"]
    pace = (z2["pace_lo_s"] + z2["pace_hi_s"]) / 2
    metres = round_100(intent.total_duration_min * 60 / pace * 100)
    adj.append(f"total_duration_min={intent.total_duration_min:g} sized to {metres} m at Z2 pace")
    return int(rng.clamp("total_distance_m", metres, adj))


def _main_zone(structure: WorkoutStructure, fallback: str) -> str:
    for item in structure.items:
        if isinstance(item, WorkoutStep) and item.role == "interval" and item.target and item.target.zone:
            return item.target.zone
    return fallback


def _intensity(zone: str) -> dict:
    return {"zone": zone, "anchor": "css_pace"}


def _pool_template_builder(template_id: str, purpose: str, block: str) -> Callable[[WorkoutIntent, Athlete], BuildResult]:
    def build(intent: WorkoutIntent, athlete: Athlete) -> BuildResult:
        adj: list[str] = []
        css = _css_for(athlete, adj)
        distance = _size_distance(intent, css, SWIM_POOL_DISTANCE_RANGE, adj)
        if distance is None:
            raise ValueError(f"swim archetype {intent.archetype!r} needs total_distance_m or total_duration_min")
        selector = [t.id for t in find_templates(block=block)].index(template_id)
        structure = _additional_swim_structure_template(block, distance, css, selector)
        zone = _main_zone(structure, _PURPOSE_FALLBACK_ZONE.get(purpose, "Z2"))
        return _finish(structure, athlete, css, _intensity(zone), adj)

    return build


def _nearest_valid_ow(template_id: str, distance_m: int, css: float) -> tuple[WorkoutStructure, int]:
    """The OW structure at `distance_m`, or at the nearest distance (50 m steps) the template accepts."""
    for step in range(0, 241):
        for d in (distance_m + step * 50, distance_m - step * 50):
            if d <= 0:
                continue
            try:
                return build_ow_session(template_id, d, css), d
            except ValueError:
                continue
    raise ValueError(f"no valid distance found for open-water template {template_id!r} near {distance_m} m")


def _ow_builder(template_id: str) -> Callable[[WorkoutIntent, Athlete], BuildResult]:
    def build(intent: WorkoutIntent, athlete: Athlete) -> BuildResult:
        adj: list[str] = []
        css = _css_for(athlete, adj)
        asked = _size_distance(intent, css, SWIM_OW_DISTANCE_RANGE, adj)
        if asked is None:
            raise ValueError(f"swim archetype {intent.archetype!r} needs total_distance_m or total_duration_min")
        structure, built = _nearest_valid_ow(template_id, asked, css)
        if built != asked:
            adj.append(
                f"asked {asked} m; built {built} m (nearest distance this open-water template accepts; "
                "see its duration floor / ceiling)"
            )
        return _finish(structure, athlete, css, _intensity(_main_zone(structure, "Z2")), adj)

    return build


def _build_css_threshold(intent: WorkoutIntent, athlete: Athlete) -> BuildResult:
    adj: list[str] = []
    css = _css_for(athlete, adj)
    total = _size_distance(intent, css, SWIM_POOL_DISTANCE_RANGE, adj)
    rep = int(SWIM_REP_DISTANCE_RANGE.clamp("rep_distance_m", intent.rep_distance_m or ADDITIONAL_SWIM_BUILD_BLOCK_REP_M, adj))
    rest = SWIM_REST_S_RANGE.clamp("rest_s", intent.rest_s if intent.rest_s is not None else CSS_THRESHOLD_DEFAULT_REST_S, adj)
    warm = cool = None
    if total:
        warm = max(ADDITIONAL_SWIM_MIN_WARM_UP_M, round_100(total * ADDITIONAL_SWIM_WARM_UP_SHARE))
        cool = max(ADDITIONAL_SWIM_MIN_COOL_DOWN_M, round_100(total * ADDITIONAL_SWIM_COOL_DOWN_SHARE))
    if intent.reps:
        reps = int(SWIM_REPS_RANGE.clamp("reps", intent.reps, adj))
    elif total:
        reps = int(SWIM_REPS_RANGE.clamp("reps", max(1, round((total - warm - cool) / rep)), adj))
    else:
        raise ValueError("swim archetype 'css_threshold' needs reps, or a total_distance_m / total_duration_min")
    if warm is None:
        warm = max(ADDITIONAL_SWIM_MIN_WARM_UP_M, round_100(reps * rep * 0.3))
        cool = max(ADDITIONAL_SWIM_MIN_COOL_DOWN_M, round_100(reps * rep * 0.15))
    standard_cool = cool
    cool = max(cool, (total - warm - reps * rep) if total else cool)
    if cool > standard_cool:
        adj.append(f"cool-down lengthened to {cool} m (standard {standard_cool} m) so the session reaches the asked {total} m")
    return _finish(_css_threshold_structure(warm, cool, reps, rep, rest), athlete, css, _intensity(CSS_THRESHOLD_ZONE), adj)


def _css_threshold_structure(warm: int, cool: int, reps: int, rep: int, rest: float) -> WorkoutStructure:
    work = WorkoutStep(
        label=f"{rep}m at CSS pace (Z4)", role="interval", duration_kind="distance_m", duration_value=rep,
        target=WorkoutTarget(basis="zone", zone=CSS_THRESHOLD_ZONE), modality="swim",
    )
    steps: list = [work]
    if rest > 0:
        steps.append(WorkoutStep(label=f"{rest:g}s rest", role="rest", duration_kind="time_s", duration_value=rest, modality="swim"))
    return WorkoutStructure(items=[
        WorkoutStep(label=f"{warm}m easy, building to Z2 pace.", role="warmup", duration_kind="distance_m",
                    duration_value=warm, target=WorkoutTarget(basis="zone", zone="Z2"), modality="swim"),
        WorkoutRepeat(repeat_mode="count", count=reps, steps=steps),
        WorkoutStep(label=f"{cool}m easy choice of stroke.", role="cooldown", duration_kind="distance_m",
                    duration_value=cool, modality="swim"),
    ])


def _build_swim_endurance(intent: WorkoutIntent, athlete: Athlete) -> BuildResult:
    adj: list[str] = []
    css = _css_for(athlete, adj)
    distance = _size_distance(intent, css, SWIM_OW_DISTANCE_RANGE, adj)
    if distance is None:
        raise ValueError("swim archetype 'endurance' needs total_distance_m or total_duration_min")
    zone = f"Z{int(SWIM_ENDURANCE_ZONE_RANGE.clamp('target_zone', int(intent.target_zone[1:]), adj))}" if intent.target_zone else "Z2"
    step = WorkoutStep(
        label=f"{distance}m continuous aerobic swim at {zone} pace", role="steady", duration_kind="distance_m",
        duration_value=distance, target=WorkoutTarget(basis="zone", zone=zone), modality="swim",
    )
    return _finish(WorkoutStructure(items=[step]), athlete, css, _intensity(zone), adj)


def _probe_kind(structure: WorkoutStructure, intensity: dict, sport: str) -> StimulusKind:
    """The kind a builder's reference structure measures as (declared once, at registration)."""
    probe = Athlete(id=uuid.UUID(int=0), slug="probe", name="probe", css_pace_s_per_100m=_default_css())
    resolved = resolve_template(structure, probe)
    minutes, metres = structure_totals(resolved, probe, profile_for(sport))
    return measure_dose(resolved, intensity, minutes, metres, sport, probe).kind


def _register_pool_templates() -> None:
    for template in load_workout_templates():
        block = template.applicable_blocks[0]
        selector = [t.id for t in find_templates(block=block)].index(template.id)
        structure = _additional_swim_structure_template(block, 3000, _default_css(), selector)
        zone = _main_zone(structure, _PURPOSE_FALLBACK_ZONE.get(template.purpose, "Z2"))
        kind = _probe_kind(structure, _intensity(zone), "swim_pool")
        name = "pool_" + template.id.replace("-", "_")
        summary = f"Pool main set '{template.id}' ({template.format_type}, {template.purpose}) with warm-up and cool-down."
        params = {"total_distance_m": SWIM_POOL_DISTANCE_RANGE, "total_duration_min": SWIM_TOTAL_MIN_RANGE}
        register(WorkoutBuilder("swim", name, kind, summary, _SWIM_POOL, params,
                                _pool_template_builder(template.id, template.purpose, block)))


def _register_ow_templates() -> None:
    for row in list_ow_session_templates():
        structure, _ = _nearest_valid_ow(row["id"], 3000, _default_css())
        intensity = _intensity(_main_zone(structure, "Z2"))
        summary = f"Open-water: {row['label']} ({row['scaling']})."
        params = {"total_distance_m": SWIM_OW_DISTANCE_RANGE, "total_duration_min": SWIM_TOTAL_MIN_RANGE}
        register(WorkoutBuilder("swim", "ow_" + row["id"], _probe_kind(structure, intensity, "swim_ow"), summary,
                                _SWIM_OW, params, _ow_builder(row["id"])))


def _register_template_builders() -> None:
    _register_pool_templates()
    _register_ow_templates()


def _register_swim_builders() -> None:
    register_loader(_register_template_builders)
    both = {"total_distance_m": SWIM_OW_DISTANCE_RANGE, "total_duration_min": SWIM_TOTAL_MIN_RANGE}
    register(WorkoutBuilder("swim", "endurance", "endurance", "Continuous aerobic swim (default Z2), sized by distance or time.",
                            _SWIM_BOTH, {**both, "target_zone": SWIM_ENDURANCE_ZONE_RANGE}, _build_swim_endurance))
    css_params = {
        "total_distance_m": SWIM_POOL_DISTANCE_RANGE, "total_duration_min": SWIM_TOTAL_MIN_RANGE,
        "reps": SWIM_REPS_RANGE, "rep_distance_m": SWIM_REP_DISTANCE_RANGE, "rest_s": SWIM_REST_S_RANGE,
    }
    register(WorkoutBuilder("swim", "css_threshold", "threshold", "Reps x distance at CSS pace (Z4) with timed rest.",
                            _SWIM_POOL, css_params, _build_css_threshold))


_register_swim_builders()
