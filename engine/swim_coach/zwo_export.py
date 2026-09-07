"""Export a resolved bike-modality `WorkoutStructure` (see models.py) as a
`.zwo` XML file -- the Zwift workout-file format also loaded by MyWhoosh,
for an INDOOR/trainer bike session (see `garmin_export.py`'s module
docstring for the sibling OUTDOOR path: a real Garmin `.FIT` workout file,
pushed to intervals.icu -> Garmin Connect -> the watch).

**Ported from a real, already-designed, already-working prompt-driven Claude
Code skill**: `/home/ashaber/projects/workout-to-zwo/SKILL.md` (a sibling
repo on this machine) converts TrainerRoad-style workout text into `.zwo`
files by having an LLM follow that file's parsing/mapping rules turn-by-turn.
This module ports ONLY its STRUCTURE -> ZWO-XML direction (element mapping,
warm-up/cool-down defaults, `IntervalsT` repeat encoding, 2-decimal power
formatting, the exact `<workout_file>` template) to deterministic Python --
per this project's own standing rule that the engine, not an LLM turn, owns
plan/export math (see CLAUDE.md, "Deterministic Python engine ... owns ALL
plan math"). The sibling skill's own TrainerRoad-TEXT -> structure parsing
half is deliberately NOT ported: this codebase already generates its own
structured `WorkoutStructure` internally (see `plan._bike_session_structure`)
-- there is no TrainerRoad free-text input anywhere in this project to parse.
Credit: the element mapping table, the warm-up/cool-down defaults (3 min,
40-60% / 30-55% FTP), the `IntervalsT` repeat-encoding rule ("all repeat
cycles in a single element, do not unroll"), and the exact `<workout_file>`
template below are all taken directly from that skill's Step 3-5 and its
worked "Carson" example -- reused here, not reinvented.

Input contract: a RESOLVED `WorkoutStructure` (`WorkoutTarget.basis` already
either `"power_w"` -- absolute watts, from `zones.bike_zone_table` via an
athlete's own FTP -- or `"zone"`, resolved against `ftp_watts` here the same
way `bike_zone_table` already does elsewhere in this engine). Every leaf
step's `duration_kind` must be `"time_s"` -- ZWO is fundamentally a
time-based format (matches the sibling skill's own "Duration values:
integers only" convention); a distance/rep/open duration raises a clear
`ValueError` rather than guessing at a conversion.

Cadence: the sibling skill supports `Cadence`/`CadenceLow`/`CadenceHigh`
attributes when a cadence target is stated. This engine's `WorkoutStep`/
`WorkoutTarget` models carry no cadence field at all today (no real content
this codebase generates sets one) -- honestly out of scope here rather than
inventing a model field with no real producer, matching this build's own
"model-level groundwork only where real content exists" convention (see
`models.WorkoutStep.modality`'s own comment). Add cadence support here once
a real cadence-bearing field exists on the model.
"""

from __future__ import annotations

from xml.sax.saxutils import escape as _xml_escape

from swim_coach.models import WorkoutRepeat, WorkoutStep, WorkoutStepOrRepeat, WorkoutStructure, WorkoutTarget
from swim_coach.zones import bike_zone_table

# --- defaults, ported verbatim from the sibling skill's Step 3 ---------------

_DEFAULT_WARMUP_DURATION_S = 180
_DEFAULT_WARMUP_POWER_LOW = 0.40
_DEFAULT_WARMUP_POWER_HIGH = 0.60

_DEFAULT_COOLDOWN_DURATION_S = 180
_DEFAULT_COOLDOWN_POWER_LOW = 0.30
_DEFAULT_COOLDOWN_POWER_HIGH = 0.55

_POWER_DECIMALS = 2
# "Power values: use 2 decimal places minimum" -- sibling skill, Step 5
# formatting rules.


def _fmt_power(fraction: float) -> str:
    return f"{fraction:.{_POWER_DECIMALS}f}"


def _fmt_duration(duration_s: float) -> str:
    # "Duration values: integers only, no decimal point." -- sibling skill,
    # Step 5 formatting rules.
    return str(int(round(duration_s)))


def _leaf_power_fractions(
    target: WorkoutTarget | None, ftp_watts: float
) -> tuple[float | None, float | None]:
    """Resolve one leaf `WorkoutStep.target` to a (low, high) fraction-of-FTP
    pair (0-1 scale, unrounded), or `(None, None)` for anything with no real
    power target -- the caller maps that to `<FreeRide>` (the sibling skill's
    own "use FreeRide when the block has no power target" rule).

    `basis="power_w"`: `target.low`/`target.high` are already absolute watts
    (see `models.WorkoutTarget`'s own `power_w` docstring) -- divide by
    `ftp_watts` directly. `basis="zone"`: resolved against `ftp_watts` here
    via `zones.bike_zone_table`'s %FTP bounds (the same table
    `plan._bike_step` uses when it DOESN'T already have absolute watts) --
    an open-ended upper zone bound (Z7 only) has no real ceiling to report,
    so both fractions collapse to the zone's own lower bound (a flat
    interpretation, documented here rather than silently guessing at an
    upper number). Every other basis (`percent_css`, `absolute`, `rpe`,
    `open`) has no power-target meaning for a bike step -- `(None, None)`.
    """
    if target is None:
        return None, None
    if target.basis == "power_w":
        low = target.low / ftp_watts if target.low is not None else None
        high = target.high / ftp_watts if target.high is not None else None
        return low, high
    if target.basis == "zone" and target.zone is not None:
        zone_row = bike_zone_table(ftp_watts)[target.zone]
        lo_frac = zone_row["lo_pct_ftp"] / 100.0
        hi_pct = zone_row["hi_pct_ftp"]
        hi_frac = hi_pct / 100.0 if hi_pct is not None else lo_frac
        return lo_frac, hi_frac
    return None, None


def _convert_leaf(step: WorkoutStep, ftp_watts: float) -> tuple[str, dict[str, str]]:
    """One leaf `WorkoutStep` -> (ZWO element tag, ordered attribute dict),
    per the sibling skill's Step 4 mapping table. Caller guarantees
    `step.role != "open"` (annotation/prose steps -- see module-level
    filtering in `to_zwo_workout`, same convention `garmin_export._flatten`
    already uses for the identical reason)."""
    if step.duration_kind != "time_s":
        raise ValueError(
            f"to_zwo_workout requires every leaf step's duration_kind to be "
            f"'time_s' (ZWO is a time-based format) -- got "
            f"{step.duration_kind!r} on step {step.label!r}"
        )
    duration_s = _fmt_duration(step.duration_value or 0.0)
    low, high = _leaf_power_fractions(step.target, ftp_watts)

    if low is None and high is None:
        return "FreeRide", {"Duration": duration_s}

    if high is None:
        high = low
    if low is None:
        low = high

    if step.role == "warmup":
        return "Warmup", {
            "Duration": duration_s,
            "PowerLow": _fmt_power(low),
            "PowerHigh": _fmt_power(high),
        }
    if step.role == "cooldown":
        # Cooldown ramps DOWN: PowerHigh is the starting (higher) power,
        # PowerLow the ending (lower) one -- sibling skill's own explicit
        # rule ("Always set PowerHigh > PowerLow for a smooth power
        # reduction"). `low`/`high` on the model are just the range's two
        # bounds (low <= high numerically, same convention every other
        # `WorkoutTarget` basis in this codebase uses) -- direction is a
        # property of the ELEMENT (role), not the stored numbers.
        return "Cooldown", {
            "Duration": duration_s,
            "PowerHigh": _fmt_power(high),
            "PowerLow": _fmt_power(low),
        }
    if low == high:
        return "SteadyState", {"Duration": duration_s, "Power": _fmt_power(low)}
    # A genuine range on a non-warmup/cooldown step is a mid-workout
    # progression -- sibling skill's `<Ramp>` element ("power progressions in
    # the body of the workout").
    return "Ramp", {
        "Duration": duration_s,
        "PowerLow": _fmt_power(low),
        "PowerHigh": _fmt_power(high),
    }


def _convert_repeat(repeat: WorkoutRepeat, ftp_watts: float) -> tuple[str, dict[str, str]]:
    """One `WorkoutRepeat` -> a single `<IntervalsT>` element -- "all repeat
    cycles are expressed in a single element -- do not unroll them into
    separate blocks" (sibling skill, Step 4's `IntervalsT`-specific rule).

    Only the on/off pair shape the sibling skill itself supports is handled:
    `repeat_mode == "count"` with exactly two leaf `WorkoutStep` children
    (on, then off). Anything else (a `for_duration`/`amrap` EMOM-shaped
    group, a nested repeat, or any child count other than two) raises a
    clear `ValueError` -- a real, documented limitation inherited from the
    skill being ported, not silently guessed at.
    """
    if repeat.repeat_mode != "count":
        raise ValueError(
            f"to_zwo_workout only supports repeat_mode='count' groups (ZWO's "
            f"IntervalsT has no EMOM/AMRAP primitive) -- got {repeat.repeat_mode!r}"
        )
    if len(repeat.steps) != 2 or not all(isinstance(s, WorkoutStep) for s in repeat.steps):
        raise ValueError(
            "to_zwo_workout only supports a WorkoutRepeat with exactly two leaf "
            "WorkoutStep children (an on/off interval pair) -- got "
            f"{len(repeat.steps)} child item(s)"
        )
    on_step, off_step = repeat.steps
    if on_step.duration_kind != "time_s" or off_step.duration_kind != "time_s":
        raise ValueError(
            "to_zwo_workout requires every leaf step's duration_kind to be "
            "'time_s' (ZWO is a time-based format)"
        )

    def _midpoint_fraction(step: WorkoutStep) -> float:
        low, high = _leaf_power_fractions(step.target, ftp_watts)
        if low is None and high is None:
            raise ValueError(
                f"to_zwo_workout requires a real power target on every "
                f"IntervalsT child step -- {step.label!r} has none"
            )
        if high is None:
            return low
        if low is None:
            return high
        # "use the midpoint as OnPower" -- sibling skill, Step 4's
        # IntervalsT-specific rule, also applied to OffPower for symmetry.
        return (low + high) / 2

    return "IntervalsT", {
        "Repeat": str(repeat.count if repeat.count is not None else 1),
        "OnDuration": _fmt_duration(on_step.duration_value or 0.0),
        "OffDuration": _fmt_duration(off_step.duration_value or 0.0),
        "OnPower": _fmt_power(_midpoint_fraction(on_step)),
        "OffPower": _fmt_power(_midpoint_fraction(off_step)),
    }


def _convert_item(item: WorkoutStepOrRepeat, ftp_watts: float) -> tuple[str, dict[str, str]]:
    if isinstance(item, WorkoutStep):
        return _convert_leaf(item, ftp_watts)
    return _convert_repeat(item, ftp_watts)


def _render_element(tag: str, attrib: dict[str, str]) -> str:
    attrs = " ".join(f'{key}="{value}"' for key, value in attrib.items())
    return f"    <{tag} {attrs} />"


def to_zwo_workout(
    structured: WorkoutStructure,
    *,
    ftp_watts: float,
    name: str,
    author: str = "",
    description: str | None = None,
) -> str:
    """Encode a RESOLVED bike-modality `WorkoutStructure` as a `.zwo` XML
    string, for MyWhoosh/Zwift's Workout Builder import -- see module
    docstring for the sibling skill this ports and the input contract.

    `role="open"` annotation steps (section headers / "Why: ..." prose, the
    same convention `garmin_export._flatten` already documents and skips for
    the identical reason -- there is no ZWO-native way to show inert prose
    on a trainer workout) are filtered out before conversion, never
    exported. A missing leading `Warmup`/trailing `Cooldown` element (after
    that filtering) gets the sibling skill's own 3-minute defaults
    prepended/appended -- an explicit, even very short (<3 min), warm-up or
    cool-down is used verbatim and never overridden (sibling skill's "Cadence
    not mentioned" sibling rule: "use the stated values -- do not override or
    extend them").

    Pure function -- no I/O, no network. Raises `ValueError` for a leaf step
    whose `duration_kind` isn't `"time_s"`, or a `WorkoutRepeat` outside the
    single on/off-pair, `repeat_mode="count"` shape this port supports (see
    `_convert_repeat`).
    """
    real_items = [item for item in structured.items if not (isinstance(item, WorkoutStep) and item.role == "open")]
    elements = [_convert_item(item, ftp_watts) for item in real_items]

    if not elements or elements[0][0] != "Warmup":
        elements.insert(
            0,
            (
                "Warmup",
                {
                    "Duration": str(_DEFAULT_WARMUP_DURATION_S),
                    "PowerLow": _fmt_power(_DEFAULT_WARMUP_POWER_LOW),
                    "PowerHigh": _fmt_power(_DEFAULT_WARMUP_POWER_HIGH),
                },
            ),
        )
    if elements[-1][0] != "Cooldown":
        elements.append(
            (
                "Cooldown",
                {
                    "Duration": str(_DEFAULT_COOLDOWN_DURATION_S),
                    "PowerLow": _fmt_power(_DEFAULT_COOLDOWN_POWER_LOW),
                    "PowerHigh": _fmt_power(_DEFAULT_COOLDOWN_POWER_HIGH),
                },
            ),
        )

    workout_lines = "\n".join(_render_element(tag, attrib) for tag, attrib in elements)
    description_text = description if description is not None else ""

    # Exact template from the sibling skill's Step 5 -- element names,
    # attribute casing, and 2-space/4-space indentation are all ported
    # verbatim (that skill's own docstring: "the format is case-sensitive").
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<workout_file>\n"
        f"  <n>{_xml_escape(name)}</n>\n"
        f"  <author>{_xml_escape(author)}</author>\n"
        f"  <description>{_xml_escape(description_text)}</description>\n"
        "  <sportType>bike</sportType>\n"
        f"  <ftpOverride>{int(round(ftp_watts))}</ftpOverride>\n"
        "  <workout>\n"
        f"{workout_lines}\n"
        "  </workout>\n"
        "</workout_file>"
    )
