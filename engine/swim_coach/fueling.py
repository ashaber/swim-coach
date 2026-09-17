"""Deterministic fueling-plan calculator.

Andrew's own hand-computation of Renee's Skopelos in-swim fueling (duration
-> target g/h band -> product concentration -> serving cadence) was redone
three times in chat and got it wrong twice along the way before landing
somewhere solid -- exactly the failure mode CLAUDE.md's "never hand-compute
plan math in chat" rule exists to prevent. This module makes that math
deterministic engine code, generalized across the real range of event shapes
this project's athletes actually race, not re-derived per event:

1. A multi-day ultra swim (Skopelos) -- several days, discrete legs,
   *irregular* external access (support boat, 2.5-5km spacing).
2. A lap-based ultra MTB -- *regular, predictable* external access every
   lap (a pit stop).
3. A short, self-carried-only race (CX) -- *zero* external access during
   the race itself; short but high-intensity, with real total exposure
   including the warmup beforehand.
4. A long point-to-point race with sparse aid stations -- *irregular,
   sparse* external access, a different irregular shape than #1.

The generic job: given an event's total duration/intensity and a generic
description of external-feed-access pattern (`NoAccess` / `FixedIntervalAccess`
/ `IrregularAccess`), compute what must be self-carried between any two
consecutive access points (or across the whole event, if there is none) to
hit the target g/h band -- the "work backward from constraints" math done by
hand, generalized instead of re-derived per event.

**Design invariant: the target g/h band is a function of the event's TOTAL
duration/intensity, computed ONCE (`target_band_g_per_hr`) -- never
re-derived per access segment.** A segment's own (typically much shorter)
duration only determines how many grams of that SAME rate must be packaged
into that segment; it must never cause a different, shorter-duration band to
be looked up per segment (a short inter-access gap inside a long steady
event is not itself a short steady event). See `compute_fueling_plan`.

All research-grounded constants cite `library/08-ultra-feeding.md` (which
this build extends with a new bike/CX section -- see that file's own
citations for the underlying papers, verified by direct fetch, not from
training-data memory). Product facts (`PRODUCTS` below) are commercial
label data, not research claims, so they aren't library/ citations -- see
each `ProductFuel`'s own `notes` for how/when each was verified, including a
real, live discrepancy this build's own research pass caught (Formula 369's
sodium figure -- see that entry).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal
from uuid import UUID, uuid4

from swim_coach.models import Session

IntensityClass = Literal["steady", "high_intensity_intermittent"]

# --- Carbohydrate dose bands (g/h), by TOTAL event duration -----------------
# Source: library/08-ultra-feeding.md "In-session carbohydrate feeding" --
# `Jeukendrup (2014)`/`Shaw et al. (2014)`: "~30 g/h for 1-2h efforts, ~60
# g/h for 2-3h, up to 90 g/h for >2.5-3h" from multiple-transportable
# carbohydrate sources. The source prose gives overlapping ranges rather
# than crisp tier cutoffs; the 3-tier table below is a Coach-judgment
# reading of it (2h/3h boundaries, with the middle tier spanning 45-60 g/h
# to bridge "~60 g/h for 2-3h" against the top tier's own ">2.5-3h" start),
# not a literal transcription. (upper_bound_h, low_g_per_hr, high_g_per_hr) --
# first row whose upper bound is >= the event's own duration_h wins.
STEADY_BAND_BY_DURATION_H: tuple[tuple[float, float, float], ...] = (
    (2.0, 30.0, 30.0),
    (3.0, 45.0, 60.0),
    (float("inf"), 60.0, 90.0),
)

DEFAULT_CARB_TOLERANCE_G_PER_HR = 60.0
# library/08-ultra-feeding.md: 60 g/h is the single-transportable-
# carbohydrate gut-absorption ceiling (`Jeukendrup (2014)`) and the
# literature's own floor for its long-duration band -- the safe, untrained-
# tolerance default `compute_fueling_plan` falls back to when
# `Athlete.carb_tolerance_g_per_hr` is unset, per this build's brief:
# "falling back to the research-grounded ~60g/h baseline when unset."
# `library/08`'s "90 g/h is a trained capacity, not a starting one"
# (`Miall et al. (2018)`) is exactly why this fallback sits at the BAND'S
# FLOOR, not its ceiling -- see `target_band_g_per_hr`'s clamping behavior
# in `compute_fueling_plan`.


def target_band_g_per_hr(duration_min: float, intensity_class: IntensityClass) -> tuple[float, float]:
    """The event's target carbohydrate g/h band, from its TOTAL duration and
    intensity class -- see this module's docstring for why this must only
    ever be called once per event, against the event's own total duration,
    never per access segment.

    `intensity_class="high_intensity_intermittent"` always returns the top
    (60-90 g/h) band regardless of duration -- library/08's new bike/CX
    section: `Essén (1978)` shows intermittent high-intensity work recruits
    and depletes fast-twitch (type II) muscle fibres in addition to the
    slow-twitch depletion continuous submaximal work produces, and
    `Romijn et al. (1993)` shows glycogen oxidation rate itself scales with
    relative exercise intensity, not just duration -- so a short (<90min)
    but genuinely high-intensity-intermittent exposure (this build's real
    CX test case: 45min warmup + 45min race) is treated as needing at least
    the literature's long-duration steady-state band, never the naive
    <2h/30g-h row a duration-only lookup would otherwise return.
    """
    if intensity_class == "high_intensity_intermittent":
        return STEADY_BAND_BY_DURATION_H[-1][1], STEADY_BAND_BY_DURATION_H[-1][2]
    duration_h = duration_min / 60.0
    for upper_h, lo, hi in STEADY_BAND_BY_DURATION_H:
        if duration_h <= upper_h:
            return lo, hi
    return STEADY_BAND_BY_DURATION_H[-1][1], STEADY_BAND_BY_DURATION_H[-1][2]


HEAT_WARNING = (
    "Heat does NOT raise the carbohydrate g/h target above. Heat stress "
    "increases muscle glycogen oxidation by ~25% while REDUCING the "
    "oxidation rate of ingested carbohydrate (`Jentjens et al. (2002)`, "
    "real cyclists, 16.4C vs 35.4C at matched power output -- see "
    "library/08-ultra-feeding.md's new bike/CX section) -- so pushing g/h "
    "higher on a hot day raises GI-distress risk for reduced benefit, not "
    "more. The real heat-day lever is fluid/sodium, not more carbohydrate "
    "-- see library/08-ultra-feeding.md's rehydration and EAH safety-rail "
    "sections; this calculator does not re-derive that math."
)


# --- Product facts (commercial label data, not research claims) ------------


@dataclass(frozen=True)
class ProductFuel:
    key: str
    label: str
    carb_g_per_serving: float
    sodium_mg_per_serving: float | None
    serving_label: str  # e.g. "scoop", "gel"
    is_drink_mix: bool
    mix_guidance: str | None
    notes: str


PRODUCTS: dict[str, ProductFuel] = {
    "formula_369": ProductFuel(
        key="formula_369",
        label="Formula 369 Endurance Fuel",
        carb_g_per_serving=30.0,
        sodium_mg_per_serving=200.0,
        serving_label="scoop",
        is_drink_mix=True,
        mix_guidance="1-3 scoops per 22-26oz bottle, scaling with effort/heat.",
        notes=(
            "30g carbohydrate/scoop (1:1 glucose:fructose, maltodextrin + "
            "fructose) confirmed consistently across formula369.com and "
            "fuelgoods.com product pages, direct-fetch verified this build. "
            "**SODIUM IS UNRESOLVED, flagged rather than guessed:** direct "
            "fetches of formula369.com/fuelgoods.com marketing copy "
            "consistently say 500mg sodium/scoop, but fuelgoods.com's own "
            "product-specific page (the one page whose content was "
            "specifically framed as a 'nutrition facts' panel, not ad "
            "prose) gave 200mg/scoop for a 31g serving -- a real, live "
            "discrepancy this research pass caught, not resolved by "
            "picking whichever number is more convenient. 500mg/scoop is "
            "independently, consistently confirmed for Formula 369's "
            "SEPARATE 'Electrolyte Booster' add-in product (sold alongside "
            "Endurance Fuel, e.g. the 'Carb and Electrolyte Bundle'), which "
            "raises real suspicion the 500mg figure widely repeated for "
            "'Endurance Fuel' itself is bundle-confused marketing copy, not "
            "the base product's own label. This module uses the LOWER "
            "(200mg), more conservative figure as the default -- "
            "understating rather than overstating delivered sodium is the "
            "safer direction for a hydration-adjacent number -- but this is "
            "genuinely unresolved. The athlete/coach should confirm the "
            "real per-scoop sodium figure from their own product's physical "
            "label before race day; compute_fueling_plan surfaces this as a "
            "standing warning, not a silently-trusted constant."
        ),
    ),
    "maurten_gel_100": ProductFuel(
        key="maurten_gel_100",
        label="Maurten Gel 100",
        carb_g_per_serving=25.0,
        sodium_mg_per_serving=20.0,
        serving_label="gel",
        is_drink_mix=False,
        mix_guidance=None,
        notes=(
            "25g carbohydrate/sachet (0.8:1 fructose:glucose hydrogel), "
            "direct-fetch verified this build across maurten.com and "
            "independent retailer pages -- consistent. Sodium content is "
            "LOW CONFIDENCE: sources found in the 20-50mg/sachet range with "
            "no single authoritative figure verified directly from "
            "Maurten's own nutrition-facts panel; 20mg used here as the "
            "lower/more conservative estimate. Gels are a carbohydrate-"
            "delivery product, not this athlete's primary sodium source --"
            "pair with a separate electrolyte source for sodium, don't "
            "read this figure as sufficient sodium dosing on its own."
        ),
    ),
    "tailwind": ProductFuel(
        key="tailwind",
        label="Tailwind Nutrition Endurance Fuel",
        carb_g_per_serving=25.0,
        sodium_mg_per_serving=310.0,
        serving_label="scoop",
        is_drink_mix=True,
        mix_guidance=(
            "1 scoop per 16-24oz for 1-2h moderate efforts; 2-3 scoops per "
            "16-24oz per hour for efforts over 2h (per tailwindnutrition.com's "
            "own FAQ)."
        ),
        notes=(
            "25g carbohydrate + 310mg sodium per scoop (dextrose + sucrose), "
            "direct-fetch verified this build via two independent sources "
            "(tailwindnutrition.com's own product page describing a 2-scoop "
            "'serving' as 50g carb/620mg sodium -- consistent with 25g/"
            "310mg per single scoop -- and thefeed.com's retailer listing). "
            "Andrew's real second-choice fuel product after Formula 369, "
            "per this build's brief -- NOT Tailwind CSS; no UI/framework "
            "decision is any part of this module."
        ),
    ),
}


def _product(product_key: str) -> ProductFuel:
    if product_key not in PRODUCTS:
        raise ValueError(f"unknown product_key {product_key!r}; known products: {sorted(PRODUCTS)}")
    return PRODUCTS[product_key]


# --- External feed-access pattern -------------------------------------------


@dataclass(frozen=True)
class NoAccess:
    """No external feed access at all during the event -- fully
    self-carried (e.g. a CX race: everything carried on the bike/body,
    nothing handed up)."""

    kind: Literal["none"] = "none"


@dataclass(frozen=True)
class FixedIntervalAccess:
    """Regular, predictable external access every `interval_min` minutes
    (e.g. a lap-based ultra MTB's pit stop each lap)."""

    interval_min: float
    kind: Literal["fixed_interval"] = "fixed_interval"

    def __post_init__(self) -> None:
        if self.interval_min <= 0:
            raise ValueError(f"interval_min must be > 0, got {self.interval_min!r}")


@dataclass(frozen=True)
class IrregularAccess:
    """An explicit list of external access points, at given
    offset-from-event-start minutes -- irregular spacing (e.g. Skopelos's
    support boat at 2.5-5km intervals, or a 100-mile MTB's 5 aid stations
    1-2.5h apart). Order/duplicates don't matter -- sorted and de-duplicated
    internally."""

    access_points_min: tuple[float, ...]
    kind: Literal["irregular"] = "irregular"


FeedAccess = NoAccess | FixedIntervalAccess | IrregularAccess


def _segment_boundaries_min(duration_min: float, access: FeedAccess) -> list[float]:
    if isinstance(access, NoAccess):
        return [0.0, duration_min]
    if isinstance(access, FixedIntervalAccess):
        points: list[float] = []
        t = access.interval_min
        while t < duration_min:
            points.append(t)
            t += access.interval_min
        return [0.0, *points, duration_min]
    if isinstance(access, IrregularAccess):
        points = sorted({p for p in access.access_points_min if 0 < p < duration_min})
        return [0.0, *points, duration_min]
    raise TypeError(f"unknown access type {type(access)!r}")  # pragma: no cover


# --- Feed timing within a segment -------------------------------------------

FEED_CADENCE_MIN = 30.0
# Coach judgment, not a new evidence claim: a generic, event-agnostic
# feed-spacing default inside library/08-ultra-feeding.md's already-cited
# practitioner cadence range ("A feed every 20-30 min ... well under 1% of
# total swim time" -- that section is written for swim bottle-feeds
# specifically). Here it only sets how many discrete `feed_timestamps_min`
# this calculator distributes a segment's own total carb target across --
# not an independent claim about optimal cadence for every sport.


def _feed_timestamps_within_segment(start_min: float, end_min: float) -> tuple[float, ...]:
    duration = end_min - start_min
    if duration <= 0:
        return (start_min,)
    n = max(1, round(duration / FEED_CADENCE_MIN))
    step = duration / n
    return tuple(start_min + i * step for i in range(n))


# --- Result shapes -----------------------------------------------------------


@dataclass(frozen=True)
class FuelingSegment:
    start_min: float
    end_min: float
    duration_min: float
    target_g_per_hr_low: float
    target_g_per_hr_high: float
    target_carb_g_low: float
    target_carb_g_high: float
    servings_low: float
    servings_high: float
    sodium_mg_at_servings_low: float | None
    sodium_mg_at_servings_high: float | None
    feed_timestamps_min: tuple[float, ...]


@dataclass(frozen=True)
class FuelingPlan:
    duration_min: float
    intensity_class: IntensityClass
    product_key: str
    carb_tolerance_g_per_hr: float
    carb_tolerance_source: Literal["athlete_set", "default_fallback"]
    heat: bool
    access_kind: str
    segments: tuple[FuelingSegment, ...]
    total_carb_g_low: float
    total_carb_g_high: float
    warnings: tuple[str, ...]


def compute_fueling_plan(
    *,
    duration_min: float,
    intensity_class: IntensityClass,
    access: FeedAccess,
    product_key: str,
    carb_tolerance_g_per_hr: float | None = None,
    heat: bool = False,
) -> FuelingPlan:
    """The generic calculator: event duration/intensity + access pattern +
    product -> a target g/h band, per-access-segment serving counts, and
    offset-from-event-start feed timestamps (reusable by a future
    to-the-minute timeline feature -- not building one here, per this
    build's own explicitly-deferred scope).

    `carb_tolerance_g_per_hr` should come from `Athlete.carb_tolerance_g_per_hr`
    when the caller has one; `None` falls back to `DEFAULT_CARB_TOLERANCE_G_PER_HR`
    (60 g/h) -- per this build's brief, verbatim from Andrew: the fallback
    mechanism IS the "when did you train at this rate?" question, surfaced by
    the caller (`backend/app/tools.py`'s `compute_fueling_plan` tool), not a
    silently-assumed number. Either way, the resolved value CLAMPS the
    target band's low/high down to never exceed it -- this calculator never
    prescribes above a demonstrated (or conservatively assumed) tolerance,
    per library/08's "90 g/h is a trained capacity, not a starting one."
    """
    if duration_min <= 0:
        raise ValueError(f"duration_min must be > 0, got {duration_min!r}")
    product = _product(product_key)

    if carb_tolerance_g_per_hr is None:
        resolved_tolerance = DEFAULT_CARB_TOLERANCE_G_PER_HR
        tolerance_source: Literal["athlete_set", "default_fallback"] = "default_fallback"
    else:
        if carb_tolerance_g_per_hr <= 0:
            raise ValueError(
                f"carb_tolerance_g_per_hr must be > 0, got {carb_tolerance_g_per_hr!r}"
            )
        resolved_tolerance = carb_tolerance_g_per_hr
        tolerance_source = "athlete_set"

    natural_low, natural_high = target_band_g_per_hr(duration_min, intensity_class)
    low = min(natural_low, resolved_tolerance)
    high = min(natural_high, resolved_tolerance)

    warnings: list[str] = []
    if resolved_tolerance < natural_low:
        warnings.append(
            f"carb_tolerance_g_per_hr ({resolved_tolerance:g} g/h) is below the "
            f"literature-driven band for this event ({natural_low:g}-{natural_high:g} "
            "g/h) -- the target has been clamped down to the athlete's own "
            "tolerance rather than prescribing above it; consider gut-training "
            "before race day (library/08-ultra-feeding.md: 2+ weeks of repeated "
            "in-session carbohydrate exposure improves tolerance -- "
            "`Miall et al. (2018)`)."
        )
    if heat:
        warnings.append(HEAT_WARNING)
    if product.sodium_mg_per_serving is None:
        warnings.append(
            f"{product.label} has no verified sodium figure -- pair with a "
            "separate, confirmed electrolyte source; do not assume this "
            "product alone covers sodium need."
        )

    boundaries = _segment_boundaries_min(duration_min, access)
    segments: list[FuelingSegment] = []
    total_low = 0.0
    total_high = 0.0
    for start, end in zip(boundaries[:-1], boundaries[1:]):
        seg_duration_min = end - start
        seg_hours = seg_duration_min / 60.0
        carb_g_low = low * seg_hours
        carb_g_high = high * seg_hours
        servings_low = carb_g_low / product.carb_g_per_serving
        servings_high = carb_g_high / product.carb_g_per_serving
        sodium_low = (
            servings_low * product.sodium_mg_per_serving
            if product.sodium_mg_per_serving is not None
            else None
        )
        sodium_high = (
            servings_high * product.sodium_mg_per_serving
            if product.sodium_mg_per_serving is not None
            else None
        )
        segments.append(
            FuelingSegment(
                start_min=start,
                end_min=end,
                duration_min=seg_duration_min,
                target_g_per_hr_low=low,
                target_g_per_hr_high=high,
                target_carb_g_low=carb_g_low,
                target_carb_g_high=carb_g_high,
                servings_low=servings_low,
                servings_high=servings_high,
                sodium_mg_at_servings_low=sodium_low,
                sodium_mg_at_servings_high=sodium_high,
                feed_timestamps_min=_feed_timestamps_within_segment(start, end),
            )
        )
        total_low += carb_g_low
        total_high += carb_g_high

    return FuelingPlan(
        duration_min=duration_min,
        intensity_class=intensity_class,
        product_key=product_key,
        carb_tolerance_g_per_hr=resolved_tolerance,
        carb_tolerance_source=tolerance_source,
        heat=heat,
        access_kind=access.kind,
        segments=tuple(segments),
        total_carb_g_low=total_low,
        total_carb_g_high=total_high,
        warnings=tuple(warnings),
    )


# --- Pre-event nutrition as a Session-shaped plan entry (deliverable 5) ----

PRE_EVENT_NUTRITION_SESSION_MIN = 15.0
# A nominal, non-exercise duration for this reminder-shaped Session -- same
# "small placeholder duration" posture `taper_search.py`'s
# `RECOVERY_SESSION_MIN`-style rest-day sessions already use (not
# re-imported from `plan.py` to avoid a needless cross-module coupling for
# one constant).


def render_fueling_plan_summary(plan: FuelingPlan, product_label: str) -> str:
    """Human-readable prose summary of a `FuelingPlan` -- used both for the
    pre-event nutrition Session's `structure` field and by the
    `compute_fueling_plan` coach tool's response."""
    lines = [
        f"Fueling plan: {plan.duration_min:g} min total exposure, "
        f"{plan.intensity_class.replace('_', ' ')} intensity, {product_label}.",
        f"Carb tolerance used: {plan.carb_tolerance_g_per_hr:g} g/h "
        f"({'athlete-confirmed' if plan.carb_tolerance_source == 'athlete_set' else 'default fallback -- confirm training-recency before race day'}).",
        f"Access pattern: {plan.access_kind} ({len(plan.segments)} segment(s)).",
    ]
    for i, seg in enumerate(plan.segments, start=1):
        lines.append(
            f"  Segment {i} ({seg.start_min:g}-{seg.end_min:g} min, "
            f"{seg.duration_min:g} min): target {seg.target_g_per_hr_low:g}-"
            f"{seg.target_g_per_hr_high:g} g/h -> {seg.target_carb_g_low:g}-"
            f"{seg.target_carb_g_high:g} g carb -> "
            f"{seg.servings_low:.1f}-{seg.servings_high:.1f} servings; "
            f"feed at {', '.join(f'{t:g}' for t in seg.feed_timestamps_min)} min"
        )
    if plan.warnings:
        lines.append("Warnings:")
        lines.extend(f"  - {w}" for w in plan.warnings)
    return "\n".join(lines)


def build_pre_event_nutrition_session(
    *,
    athlete_id: UUID,
    event_date: date,
    plan: FuelingPlan,
    product_label: str,
    days_before: int = 1,
) -> Session:
    """Builds (does NOT persist) a `Session`-shaped pre-event nutrition plan
    entry, per this build's brief: "a carb-load / day-before nutrition item
    can be represented the same way a workout already is -- a Session-shaped
    entry ... placed on the calendar day(s) before the event, reusing
    existing WeekPlan/session infrastructure rather than a new system."

    Deliberately distinct from `plan._race_week_checklist`'s existing
    `carb_load` `RaceWeekChecklistItem` (a generic "begin carbohydrate
    loading 10-12 g/kg/day" reminder, days out) -- this Session instead
    carries the ACTUAL computed race-day fueling numbers from `plan` (what
    product, how many servings, when to feed), for the final pack-and-mix
    prep the day before. The two are complementary, not duplicative.

    The caller (`backend/app/tools.py`'s `compute_fueling_plan` tool)
    persists this via the same generic `session_overrides` "add" path
    `replace_week_plan` already exposes, finding/creating the WeekPlan that
    covers `event_date - days_before` -- this function only builds the
    `Session` object itself, matching the rest of this module's pure-
    calculator posture (no store/persistence dependency here).
    """
    session_date = event_date - timedelta(days=days_before)
    structure = render_fueling_plan_summary(plan, product_label)
    return Session(
        id=uuid4(),
        athlete_id=athlete_id,
        date=session_date,
        sport="recovery",
        source="ai_coach",
        duration_min=PRE_EVENT_NUTRITION_SESSION_MIN,
        distance_m=None,
        intensity={"anchor": "rpe"},
        purpose=(
            f"Pre-event fueling prep: pack and mix race-day nutrition "
            f"({product_label}) per the computed fueling plan below."
        ),
        structure=structure,
        status="planned",
    )
