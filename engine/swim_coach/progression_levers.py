"""Lever-based interval progression: shapes, the lever policy, candidate next sessions and move reads.

A quality session in a zone is a `SessionShape`: sets, reps per set, rep size, rest, set rest. Total
work in the zone follows from those. Progression moves ONE lever one step from the last session the
athlete completed cleanly (`next_shapes`). Which levers exist, their step rules and bounds, the
per-session ceilings, where to go at the top of a zone and what a threshold change does are DATA in
`templates/progression_levers.yaml` (`LeverPolicy`), overridable per athlete with a dict. Nothing in
this module branches on the sport: sport differences come from `stimulus.SportProfile` (unit, anchor)
and the compiler's registered rung builder.

Evidence: ceilings cite the tested protocols they come from; lever order, step sizes, entry shapes
and the rebase rule are Coach judgment (library/48-stimulus-progression.md "Lever model"). No study
compares the levers as progression steps.
"""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal, Sequence

import yaml
from pydantic import BaseModel, BeforeValidator, Field, ValidationError, model_validator

from swim_coach.models import Athlete, WorkoutRepeat, WorkoutStructure
from swim_coach.stimulus import (
    KIND_RANK,
    REST_ROLES,
    WORK_ROLES,
    Leaf,
    SportProfile,
    profile_for,
    profile_named,
    zone_rank,
)
from swim_coach.workout_builders import WorkoutIntent, builders_for, describe_rung, parse_rung

if TYPE_CHECKING:
    from swim_coach.progression import StimulusRecord

DEFAULT_POLICY_PATH = Path(__file__).parent / "templates" / "progression_levers.yaml"
SCHEMA_VERSION = 1
ZONES = ("Z3", "Z4", "Z5")
Zone = Literal["Z3", "Z4", "Z5"]
LeverName = Literal["rep_size", "rest", "reps", "sets", "consolidate"]
Verdict = Literal["progress", "repeat", "reduce", "rebuild", "insufficient_data"]

# Coach judgment (library/48): executed reps are "regular" when within this share of their median.
REP_REGULARITY = 0.10
# Coach judgment (library/48): two rests are "the same" within this share (or REST_TOLERANCE_S).
REST_REGULARITY = 0.15
REST_TOLERANCE_S = 5.0
# Coach judgment (library/48): derived sizes snap to this grid so a rung reads cleanly.
SNAP_SHORT_S, SNAP_LONG_S, SNAP_LONG_FROM_S, SNAP_M = 5.0, 30.0, 120.0, 25.0
MAX_EXPANDED_STEPS = 600
# Coach judgment (library/48): executed efforts with no more than this gap between them are one rep.
MERGE_GAP_S = 1.0
# Coach judgment (library/48): the block of equal reps must carry this share of all the quality work;
# the rest are primers or extras, ignored for the shape.
DOMINANT_MIN_SHARE = 0.75
CEILING_TOLERANCE = 0.005
GRID_STEPS_MAX = 60


# --- amounts and formatting --------------------------------------------------------------------


def parse_amount(value: Any) -> float:
    """"8 min" -> 480, "15 s" -> 15, "100 m" -> 100; a bare number is returned as is."""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower()
    for suffix, factor in (("min", 60.0), ("s", 1.0), ("m", 1.0)):
        if text.endswith(suffix) and text[: -len(suffix)].strip().replace(".", "", 1).isdigit():
            return float(text[: -len(suffix)]) * factor
    raise ValueError(f"not an amount: {value!r}; write e.g. '8 min', '15 s', '100 m' or a number")


Amount = Annotated[float, BeforeValidator(parse_amount)]


def snap(value: float, unit: str) -> float:
    """`value` on the profile's practical grid: metres to 25; seconds to 5 under 2 min, else to 30."""
    if unit == "m":
        return max(SNAP_M, round(value / SNAP_M) * SNAP_M)
    grid = SNAP_SHORT_S if value < SNAP_LONG_FROM_S else SNAP_LONG_S
    return max(grid, round(value / grid) * grid)


def fmt_seconds(seconds: float) -> str:
    """"4 min", "7.5 min", "90 s"."""
    if seconds % 60 == 0 and seconds >= 60:
        return f"{int(seconds // 60)} min"
    if seconds >= 120 and seconds % 30 == 0:
        return f"{seconds / 60:g} min"
    return f"{seconds:g} s"


def fmt_size(value: float, unit: str) -> str:
    return f"{value:g} m" if unit == "m" else fmt_seconds(value)


def fmt_delta(delta: float, unit: str) -> str:
    return ("+" if delta > 0 else "-") + fmt_size(abs(delta), unit)


# --- the shape of one session ------------------------------------------------------------------


def _rung_builder(group: str) -> Any:
    for builder in builders_for(group):
        if builder.rung:
            return builder
    raise ValueError(f"no rung builder registered for sport group {group!r}")


def _unit_of(group: str) -> str:
    profile = profile_named(group)
    if profile is None:
        raise ValueError(f"unknown sport group {group!r}")
    return profile.unit


class SessionShape(BaseModel):
    """One quality session in a zone: `sets` x (`reps` x `rep_size` / `rest_s`) / `set_rest_s`.
    `rep_size` is seconds or metres per the sport group's unit; rest is always seconds. A set of one
    rep is the flat rung it reads as (2 sets of 1 x 10 min is 2 x 10 min)."""

    sport_group: str
    zone: Zone
    sets: int = Field(default=1, ge=1)
    reps: int = Field(ge=1)
    rep_size: float = Field(gt=0)
    rest_s: float = Field(ge=0)
    set_rest_s: float | None = Field(default=None, ge=0)

    @model_validator(mode="before")
    @classmethod
    def _flatten_single_rep_sets(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("sets", 1) > 1 and data.get("reps") == 1:
            data = {**data, "reps": data["sets"], "sets": 1, "rest_s": data.get("set_rest_s", data.get("rest_s")),
                    "set_rest_s": None}
        return data

    @model_validator(mode="after")
    def _check_rests(self) -> "SessionShape":
        if self.sets == 1:
            self.set_rest_s = None
            self.rest_s = self.rest_s if self.reps > 1 else 0.0  # nothing follows a lone rep
        elif self.set_rest_s is None or self.set_rest_s < self.rest_s:
            raise ValueError("a shape with several sets needs set_rest_s at or above rest_s")
        return self

    @property
    def unit(self) -> str:
        return _unit_of(self.sport_group)

    def work(self) -> float:
        """Total work in the zone, in the group's unit (seconds or metres)."""
        return self.sets * self.reps * self.rep_size

    def rest_between_s(self) -> float:
        """Rest seconds between consecutive reps: in-set rests plus the rests between sets."""
        return self.sets * (self.reps - 1) * self.rest_s + (self.sets - 1) * (self.set_rest_s or 0.0)

    def density(self) -> float | None:
        """Work / (work + rest between reps) for a time-based unit; None for a distance unit."""
        if self.unit != "s":
            return None
        return self.work() / (self.work() + self.rest_between_s())

    def to_intent(self) -> WorkoutIntent:
        """The compiler request that builds this shape, with every rest stated."""
        builder = _rung_builder(self.sport_group)
        fields: dict[str, Any] = {
            "sport": sorted(builder.sports)[0], "archetype": builder.archetype, "reps": self.reps,
            "rest_s": self.rest_s, "target_zone": self.zone, "sets": self.sets if self.sets > 1 else None,
            "set_rest_s": self.set_rest_s,
        }
        fields["rep_distance_m" if self.unit == "m" else "rep_duration_s"] = (
            int(self.rep_size) if self.unit == "m" else self.rep_size
        )
        return WorkoutIntent(**fields)

    def describe(self) -> str:
        """The canonical rung text, e.g. "2x(3x3 min/1 min)/5 min Z4"."""
        return describe_rung(self.to_intent())

    @classmethod
    def from_intent(cls, intent: WorkoutIntent) -> "SessionShape":
        """The shape of a rung intent, with the builder's default rests filled in."""
        profile = profile_for(intent.sport) or profile_named(intent.sport)
        builder = _rung_builder(profile.name)
        rest_s, set_rest_s = builder.rest_defaults(intent)
        sets = intent.sets or 1
        return cls(
            sport_group=profile.name, zone=intent.target_zone, sets=sets, reps=intent.reps,
            rep_size=float(intent.rep_distance_m or intent.rep_duration_s), rest_s=rest_s,
            set_rest_s=set_rest_s if sets > 1 else None,
        )

    @classmethod
    def from_structure(
        cls, structure: WorkoutStructure, athlete: Athlete, sport: str | None = None
    ) -> "SessionShape | None":
        """The dominant regular block of a planned structure (see `shape_from_structure`), else None."""
        return shape_from_structure(structure, athlete, sport)[0]

    @classmethod
    def from_executed(cls, record: "StimulusRecord") -> "SessionShape | None":
        """The dominant regular block of an executed quality session (see `shape_from_executed`), else None."""
        return shape_from_executed(record)[0]


def shape_from_structure(
    structure: WorkoutStructure, athlete: Athlete, sport: str | None = None
) -> "tuple[SessionShape | None, str | None]":
    """(shape, note) of a planned structure: the dominant block of reps (see `_dominant`), where work
    steps with no rest between them form one rep. `sport` (a session sport or sport group) defaults to
    the steps' own modality. The note says how many other reps were ignored."""
    steps = _expand(structure.items)
    profile = _profile_of(sport, steps) if steps else None
    if profile is None:
        return None, None
    reps, gaps = _structure_reps(steps, athlete, profile)
    return _dominant(profile.name, reps, gaps)


def shape_from_executed(record: "StimulusRecord") -> "tuple[SessionShape | None, str | None]":
    """(shape, note) of an executed quality session from its per-rep detail; efforts with no gap between
    them are one rep. The zone is the record's kind (tempo Z3, threshold Z4, vo2 Z5)."""
    dose, rank = record.executed.dose, KIND_RANK.get(record.kind)
    profile = profile_for(record.sport)
    if rank is None or profile is None or not dose.rep_sizes or (len(dose.rep_sizes) > 1 and dose.rest_gaps_s is None):
        return None, None
    reps: list[tuple[float, int]] = []
    gaps: list[float] = []
    for index, size in enumerate(dose.rep_sizes):
        before = dose.rest_gaps_s[index - 1] if index else None
        if index and before is not None and before <= MERGE_GAP_S:
            reps[-1] = (reps[-1][0] + size, rank)
        else:
            gaps.extend([before] if index else [])
            reps.append((size, rank))
    return _dominant(profile.name, reps, gaps)


def _rank(step: Any, athlete: Athlete) -> int | None:
    return zone_rank(step, ftp_watts=athlete.ftp_watts, css_pace_s_per_100m=athlete.css_pace_s_per_100m)


def _expand(items: list, budget: list[int] | None = None) -> list | None:
    """The structure's timed steps in order with repeats unrolled; None past `MAX_EXPANDED_STEPS`."""
    out: list = []
    for item in items:
        if isinstance(item, WorkoutRepeat) or getattr(item, "kind", None) == "repeat":
            inner = _expand(item.steps)
            if inner is None or len(out) + len(inner) * (item.count or 1) > MAX_EXPANDED_STEPS:
                return None
            out.extend(inner * (item.count or 1))
        elif item.duration_kind in ("time_s", "distance_m") and item.duration_value:
            out.append(item)
    return out


def _structure_reps(steps: list, athlete: Athlete, profile: SportProfile) -> tuple[list[tuple[float, int]], list[float]]:
    """(reps as (size, zone rank), rest seconds between them) of the work at zone 3 and above. Work steps
    with nothing between them merge into one rep, whose zone is the one carrying most of its time."""
    reps: list[tuple[float, dict[int, float]]] = []
    gaps: list[float] = []
    pending, adjacent = 0.0, False
    for step in steps:
        rank = min(_rank(step, athlete) or 0, 5)
        value = _step_value(step, athlete, profile) if step.role in WORK_ROLES and rank >= 3 else None
        if value is not None:
            if not adjacent:
                gaps.extend([pending] if reps else [])
                reps.append((0.0, {}))
            size, by_rank = reps[-1]
            by_rank[rank] = by_rank.get(rank, 0.0) + (_step_seconds(step, athlete, profile) or value)
            reps[-1] = (size + value, by_rank)
            pending, adjacent = 0.0, True
        elif step.role in REST_ROLES or step.role in WORK_ROLES:
            pending, adjacent = pending + (_step_seconds(step, athlete, profile) or 0.0), False
        else:
            adjacent = False
    return [(size, max(by, key=lambda r: (by[r], r))) for size, by in reps], gaps


def _clusters(reps: Sequence[tuple[float, int]]) -> list[list[int]]:
    """Indices of reps grouped by zone and size (within `REP_REGULARITY` of the group's smallest)."""
    order = sorted(range(len(reps)), key=lambda i: (reps[i][1], reps[i][0]))
    groups: list[list[int]] = []
    for i in order:
        first = groups[-1][0] if groups else None
        if first is not None and reps[first][1] == reps[i][1] and _equal(reps[i][0], reps[first][0], REP_REGULARITY):
            groups[-1].append(i)
        else:
            groups.append([i])
    return [sorted(g) for g in groups]


def _is_shape_sized(group: str, zone: int, indices: list[int], reps: Sequence[tuple[float, int]]) -> bool:
    """A block needs two reps, or one rep at least as long as the zone's entry rep."""
    if len(indices) >= 2:
        return True
    policy = default_policy()
    if not policy.has_zone(group, f"Z{zone}"):
        return True
    return reps[indices[0]][0] >= policy.entry(group, f"Z{zone}").rep_size


def _dominant(
    group: str, reps: Sequence[tuple[float, int]], gaps: Sequence[float]
) -> "tuple[SessionShape | None, str | None]":
    """The regular shape of the block of equal reps carrying the most work, with a note on the reps
    ignored (primers, extras). None when no block carries `DOMINANT_MIN_SHARE` of all the work, is
    contiguous, is big enough, or is regular."""
    if not reps or len(gaps) != len(reps) - 1 or any(g is None or g < 0 for g in gaps):
        return None, None
    best = max(_clusters(reps), key=lambda c: (sum(reps[i][0] for i in c), -c[0]))
    zone = reps[best[0]][1]
    if sum(reps[i][0] for i in best) < DOMINANT_MIN_SHARE * sum(size for size, _ in reps):
        return None, None
    if best != list(range(best[0], best[-1] + 1)) or not 3 <= zone <= 5 or not _is_shape_sized(group, zone, best, reps):
        return None, None
    shape = _shape_from_reps(group, f"Z{zone}", [reps[i][0] for i in best], gaps[best[0]:best[-1]])
    ignored = len(reps) - len(best)
    note = f"ignored {ignored} primer rep{'s' if ignored != 1 else ''}" if ignored else None
    return (shape, note) if shape else (None, None)


def _profile_of(sport: str | None, steps: list) -> SportProfile | None:
    """The profile for `sport`, else for the first step that names a modality."""
    names = [sport] if sport else [getattr(s, "modality", None) for s in steps]
    return next((p for n in names if n and (p := profile_for(n) or profile_named(n)) is not None), None)


def _leaf(step: Any, athlete: Athlete) -> Leaf:
    seconds = float(step.duration_value) if step.duration_kind == "time_s" else None
    metres = float(step.duration_value) if step.duration_kind == "distance_m" else None
    return Leaf(_rank(step, athlete), seconds, metres, 1, step.role)


def _step_value(step: Any, athlete: Athlete, profile: SportProfile) -> float | None:
    seconds, metres = profile.leaf_work(_leaf(step, athlete), athlete)
    return seconds if profile.unit == "s" else metres


def _step_seconds(step: Any, athlete: Athlete, profile: SportProfile) -> float | None:
    return profile.leaf_work(_leaf(step, athlete), athlete)[0]


def _equal(a: float, b: float, tolerance: float, floor: float = 0.0) -> bool:
    return abs(a - b) <= max(floor, tolerance * max(abs(a), abs(b)))


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def _shape_from_reps(group: str, zone: str, sizes: Sequence[float], gaps: Sequence[float]) -> "SessionShape | None":
    """The regular shape of reps with `sizes` and the `gaps` between them, None when irregular."""
    unit = _unit_of(group)
    if not sizes or len(gaps) != len(sizes) - 1 or any(g is None or g < 0 for g in gaps):
        return None
    mid = _median(sizes)
    if any(not _equal(s, mid, REP_REGULARITY) for s in sizes):
        return None
    layout = _layout(gaps)
    if layout is None:
        return None
    sets, reps, rest, set_rest = layout
    if len(sizes) != sets * reps:
        return None
    return SessionShape(sport_group=group, zone=zone, sets=sets, reps=reps, rep_size=snap(mid, unit),
                        rest_s=snap(rest, "s") if rest else 0.0, set_rest_s=snap(set_rest, "s") if set_rest else None)


def _layout(gaps: Sequence[float]) -> tuple[int, int, float, float] | None:
    """(sets, reps per set, in-set rest, set rest) from the gaps between consecutive reps."""
    if not gaps:
        return 1, 1, 0.0, 0.0
    base = min(gaps)
    big = [i for i, g in enumerate(gaps) if not _equal(g, base, REST_REGULARITY, REST_TOLERANCE_S)]
    if not big:
        return 1, len(gaps) + 1, _median(gaps), 0.0
    reps = big[0] + 1
    sets = len(big) + 1
    if big != [reps * k - 1 for k in range(1, sets)]:
        return None
    set_gaps = [gaps[i] for i in big]
    if any(not _equal(g, set_gaps[0], REST_REGULARITY, REST_TOLERANCE_S) for g in set_gaps) or set_gaps[0] <= base:
        return None
    inner = [g for i, g in enumerate(gaps) if i not in big]
    return sets, reps, _median(inner) if inner else set_gaps[0], _median(set_gaps)


# --- policy ------------------------------------------------------------------------------------


class Step(BaseModel):
    """How far one move goes: a fixed `add`, a `mul`tiplier, or the ordered allowed `values`."""

    add: Amount | None = None
    mul: float | None = Field(default=None, gt=1)
    values: list[Amount] | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "Step":
        if sum(x is not None for x in (self.add, self.mul, self.values)) != 1:
            raise ValueError("step needs exactly one of add, mul, values")
        if self.values is not None and self.values != sorted(set(self.values)):
            raise ValueError("step values must be strictly increasing")
        return self

    def next(self, current: float, up: bool) -> float | None:
        """The value one step above (`up`) or below `current`, None when the grid ends."""
        if self.values is not None:
            pool = [v for v in self.values if (v > current + 1e-9 if up else v < current - 1e-9)]
            return (min(pool) if up else max(pool)) if pool else None
        if self.add is not None:
            return current + self.add if up else current - self.add
        return current * self.mul if up else current / self.mul


class LeverRule(BaseModel):
    """One lever in the policy: its step rule and the bounds its value must stay inside."""

    lever: LeverName
    direction: Literal["up", "down"] | None = None
    step: Step | None = None
    min: Amount | None = None
    max: Amount | None = None
    set_rest: Amount | None = None
    max_work_gain_pct: float | None = Field(default=None, gt=0)  # a move may add at most this much work
    basis: str

    @model_validator(mode="after")
    def _check(self) -> "LeverRule":
        if self.lever != "consolidate" and self.step is None:
            raise ValueError(f"lever {self.lever} needs a step")
        if self.lever == "sets" and self.set_rest is None:
            raise ValueError("lever sets needs set_rest, the recovery put between sets when a second set is added")
        self.direction = self.direction or ("down" if self.lever == "rest" else "up")
        return self

    def in_bounds(self, value: float) -> bool:
        return (self.min is None or value >= self.min - 1e-9) and (self.max is None or value <= self.max + 1e-9)

    def move(self, current: float, forward: bool) -> float | None:
        """`current` one step toward progress (`forward`) or away from it, inside the bounds."""
        value = self.step.next(current, up=(self.direction == "up") == forward) if self.step else None
        if value is None:
            return None
        if self.lever in ("reps", "sets"):
            value = float(round(value))
        return value if self.in_bounds(value) and value > 0 else None


class CeilingBand(BaseModel):
    """Max work per session; `rep_size_up_to` limits the band to reps no longer than that."""

    work: Amount
    rep_size_up_to: Amount | None = None
    source: str


class Promote(BaseModel):
    """What to suggest at the top of a zone."""

    zone: Zone | None = None
    retest_threshold: bool = False


class RebaseRule(BaseModel):
    min_change_pct: float = Field(gt=0)
    steps_per_pct: float = Field(gt=0)
    basis: str


class ZonePolicy(BaseModel):
    entry: str
    levers: list[LeverRule]
    ceiling: list[CeilingBand] = Field(min_length=1)
    max_rep_size: Amount | None = None
    promote_to: Promote = Field(default_factory=Promote)
    rebase: RebaseRule | None = None

    def rule(self, lever: str) -> LeverRule | None:
        return next((r for r in self.levers if r.lever == lever), None)

    def band_for(self, rep_size: float) -> CeilingBand:
        """The ceiling band that applies to reps of `rep_size`: the first whose limit covers it, else the last."""
        for band in self.ceiling:
            if band.rep_size_up_to is None or rep_size <= band.rep_size_up_to + 1e-9:
                return band
        return self.ceiling[-1]


class GroupPolicy(BaseModel):
    zones: dict[Zone, ZonePolicy]
    rebase: RebaseRule
    retest_archetypes: list[str] = Field(default_factory=list)


class LeverPolicy(BaseModel):
    """The lever policy for every sport group: data loaded from YAML, validated on load."""

    schema_version: int
    groups: dict[str, GroupPolicy]

    @model_validator(mode="after")
    def _check(self) -> "LeverPolicy":
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"schema_version {self.schema_version} is not supported (expected {SCHEMA_VERSION})")
        for group, gp in self.groups.items():
            if profile_named(group) is None:
                raise ValueError(f"unknown sport group {group!r}")
            for zone, zp in gp.zones.items():
                self._check_zone(group, zone, zp)
        return self

    @staticmethod
    def _check_zone(group: str, zone: str, zp: ZonePolicy) -> None:
        try:
            entry = SessionShape.from_intent(parse_rung(zp.entry, group))
        except (ValueError, ValidationError) as exc:
            raise ValueError(f"{group} {zone} entry {zp.entry!r}: {exc}") from exc
        if entry.zone != zone:
            raise ValueError(f"{group} {zone} entry {zp.entry!r} is a {entry.zone} rung; entry must be in {zone}")
        if zp.rule("consolidate") and zp.rule("rep_size") is None:
            raise ValueError(f"{group} {zone}: lever consolidate needs a rep_size lever to round to")

    @classmethod
    def load(cls, path: Path | None = None, *, overrides: dict | None = None) -> "LeverPolicy":
        """Load and validate the policy file; `overrides` is deep-merged over it first (dicts merge,
        lists and scalars replace), so a coach can adjust one number for one athlete."""
        raw = yaml.safe_load((path or DEFAULT_POLICY_PATH).read_text())
        return cls.model_validate(_merge(raw, overrides or {}))

    def zone(self, group: str, zone: str) -> ZonePolicy:
        try:
            return self.groups[group].zones[zone]
        except KeyError:
            raise KeyError(f"no lever policy for {group} {zone}") from None

    def entry(self, group: str, zone: str) -> SessionShape:
        """The starting shape for an athlete with no history in the zone."""
        return SessionShape.from_intent(parse_rung(self.zone(group, zone).entry, group))

    def has_zone(self, group: str, zone: str) -> bool:
        return group in self.groups and zone in self.groups[group].zones

    def rebase_rule(self, group: str, zone: str) -> RebaseRule:
        return self.zone(group, zone).rebase or self.groups[group].rebase


@lru_cache(maxsize=1)
def default_policy() -> LeverPolicy:
    """The shipped policy, loaded once. Treat it as read-only; use `LeverPolicy.load(overrides=...)` to adjust."""
    return LeverPolicy.load()


def _merge(base: dict, patch: dict) -> dict:
    out = dict(base)
    for key, value in patch.items():
        out[key] = _merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


# --- candidates --------------------------------------------------------------------------------


class Candidate(BaseModel):
    """One suggested next session: the current shape with one lever moved, or a promotion / retest."""

    shape: SessionShape | None
    rung: str
    lever: str
    change: str
    direction: Literal["up", "down", "repeat", "entry", "promote", "retest", "rebase"]
    work_delta_pct: float | None = None
    density_delta: float | None = None
    basis: str
    archetypes: list[str] = Field(default_factory=list)


def _with(shape: SessionShape, **changes: Any) -> SessionShape | None:
    try:
        return SessionShape(**{**shape.model_dump(), **changes})
    except ValueError:
        return None


def _move_value_lever(shape: SessionShape, rule: LeverRule, zp: ZonePolicy, forward: bool) -> SessionShape | None:
    field = {"rep_size": "rep_size", "rest": "rest_s", "reps": "reps"}[rule.lever]
    value = rule.move(getattr(shape, field), forward)
    if value is None or (field == "rep_size" and zp.max_rep_size and value > zp.max_rep_size + 1e-9):
        return None
    if rule.lever in ("rep_size", "rest"):
        value = snap(value, shape.unit if rule.lever == "rep_size" else "s") if value else 0.0
    return _with(shape, **{field: int(value) if field == "reps" else value})


def _move_sets(shape: SessionShape, rule: LeverRule, zp: ZonePolicy, forward: bool) -> SessionShape | None:
    value = rule.move(float(shape.sets), forward)
    if value is None:
        return None
    return _with(shape, sets=int(value), set_rest_s=(shape.set_rest_s or rule.set_rest) if value > 1 else None)


def _move_consolidate(shape: SessionShape, rule: LeverRule, zp: ZonePolicy, forward: bool) -> SessionShape | None:
    sizes = zp.rule("rep_size")
    if not forward or shape.reps < 2 or sizes is None or sizes.step is None:
        return None
    reps = math.ceil(shape.reps / 2)
    target = shape.reps * shape.rep_size / reps
    size = _grid_ceil(sizes, target)
    if size is None or (zp.max_rep_size and size > zp.max_rep_size + 1e-9):
        return None
    return _with(shape, reps=reps, rep_size=size)


def _grid_ceil(rule: LeverRule, target: float) -> float | None:
    """The smallest value on the rule's grid at or above `target`, inside its bounds."""
    step = rule.step
    if step.values is not None:
        pool = [v for v in step.values if v >= target - 1e-9 and rule.in_bounds(v)]
        return min(pool) if pool else None
    if step.add:
        value = math.ceil(target / step.add - 1e-9) * step.add
        return value if rule.in_bounds(value) else None
    return target if rule.in_bounds(target) else None


_MOVES = {
    "rep_size": _move_value_lever, "rest": _move_value_lever, "reps": _move_value_lever,
    "sets": _move_sets, "consolidate": _move_consolidate,
}


def _within_ceiling(shape: SessionShape, zp: ZonePolicy) -> bool:
    band = zp.band_for(shape.rep_size)
    too_long = zp.max_rep_size is not None and shape.rep_size > zp.max_rep_size + 1e-9
    return shape.work() <= band.work * (1 + CEILING_TOLERANCE) and not too_long


def is_at_ceiling(shape: SessionShape, policy: LeverPolicy) -> bool:
    """True when the shape's work has reached its band's ceiling, or no lever can progress it."""
    if not policy.has_zone(shape.sport_group, shape.zone):
        return False
    zp = policy.zone(shape.sport_group, shape.zone)
    if shape.work() >= zp.band_for(shape.rep_size).work * (1 - CEILING_TOLERANCE):
        return True
    return not _moves(shape, zp, forward=True)


def _moves(shape: SessionShape, zp: ZonePolicy, *, forward: bool) -> list[tuple[LeverRule, SessionShape]]:
    """Every one-lever move in policy order (reversed when stepping down), deduplicated; forward moves
    stay under the ceiling."""
    rules = zp.levers if forward else list(reversed(zp.levers))
    found: list[tuple[LeverRule, SessionShape]] = []
    for rule in rules:
        moved = _MOVES[rule.lever](shape, rule, zp, forward)
        if moved is None or moved == shape or any(moved == m for _, m in found):
            continue
        if forward and not _within_ceiling(moved, zp):
            continue
        if forward and rule.max_work_gain_pct and moved.work() > shape.work() * (1 + rule.max_work_gain_pct / 100):
            continue
        found.append((rule, moved))
    return found


def describe_change(before: SessionShape, after: SessionShape) -> str:
    """"rep 8 min -> 10 min", "reps 2 -> 3"; several changes are joined with ", "."""
    unit, parts = before.unit, []
    if after.rep_size != before.rep_size:
        parts.append(f"rep {fmt_size(before.rep_size, unit)} -> {fmt_size(after.rep_size, unit)}")
    if after.rest_s != before.rest_s:
        parts.append(f"rest {fmt_seconds(before.rest_s)} -> {fmt_seconds(after.rest_s)}")
    if after.reps != before.reps:
        parts.append(f"reps {before.reps} -> {after.reps}")
    if after.sets != before.sets:
        extra = f" ({fmt_seconds(after.set_rest_s)} between)" if after.set_rest_s and after.sets > before.sets else ""
        parts.append(f"sets {before.sets} -> {after.sets}{extra}")
    return ", ".join(parts) or "no change"


def _candidate(before: SessionShape | None, after: SessionShape, lever: str, direction: str, basis: str) -> Candidate:
    delta = None if before is None or not before.work() else (after.work() / before.work() - 1) * 100.0
    dens = None if before is None or before.density() is None else after.density() - before.density()
    change = describe_change(before, after) if before is not None else f"start at {after.describe()}"
    return Candidate(shape=after, rung=after.describe(), lever=lever, change=change, direction=direction,
                     work_delta_pct=delta, density_delta=dens, basis=basis)


def last_lever_moved(shapes: Sequence[SessionShape]) -> str | None:
    """The lever the latest of `shapes` (oldest first) changed against the one before it, None when
    that was not exactly one lever of the same zone."""
    if len(shapes) < 2 or shapes[-1].zone != shapes[-2].zone:
        return None
    before, after = shapes[-2], shapes[-1]
    changed = [
        name for name, differs in (
            ("rep_size", before.rep_size != after.rep_size), ("rest", before.rest_s != after.rest_s),
            ("reps", before.reps != after.reps), ("sets", before.sets != after.sets),
        ) if differs
    ]
    return changed[0] if len(changed) == 1 else None


def _retest_candidate(group: str, zone: str, policy: LeverPolicy, label: str) -> Candidate:
    names = policy.groups[group].retest_archetypes
    rung = " or ".join(names) if names else f"{label} test"
    return Candidate(shape=None, rung=rung, lever="retest_threshold", direction="retest",
                     change=f"top of {zone}: retest {label} before adding more volume",
                     basis=f"Coach judgment: {zone} ceiling reached", archetypes=list(names))


def _promotions(shape: SessionShape, policy: LeverPolicy) -> list[Candidate]:
    zp = policy.zone(shape.sport_group, shape.zone)
    label = profile_named(shape.sport_group).anchor_label
    out: list[Candidate] = []
    if zp.promote_to.zone and policy.has_zone(shape.sport_group, zp.promote_to.zone):
        harder = policy.entry(shape.sport_group, zp.promote_to.zone)
        out.append(Candidate(
            shape=harder, rung=harder.describe(), lever="promote_zone", direction="promote",
            change=f"{shape.zone} ceiling reached: start {harder.zone} at its entry",
            basis=zp.band_for(shape.rep_size).source,
        ))
    if zp.promote_to.retest_threshold:
        out.append(_retest_candidate(shape.sport_group, shape.zone, policy, label))
    return out


def next_shapes(
    current: SessionShape | None,
    policy: LeverPolicy,
    *,
    verdict: Verdict,
    history: Sequence[SessionShape] = (),
    group: str | None = None,
    zone: str | None = None,
) -> list[Candidate]:
    """Candidate next sessions for `verdict`, in a deterministic order.

    No `current` shape (no history in the zone; pass `group` and `zone`) gives the zone's entry shape.
    `progress` gives the current shape with exactly one lever moved one step (policy order), under the
    ceiling; at the ceiling it gives the policy's promotions (harder zone entry, threshold retest)
    instead. `repeat` gives the current shape only. `reduce` and `rebuild` give one-step-down moves,
    the most recently moved lever (from `history`, oldest first) first, else the policy order reversed.
    `insufficient_data` gives nothing."""
    if current is None:
        if group is None or zone is None or not policy.has_zone(group, zone):
            return []
        entry = policy.entry(group, zone)
        return [_candidate(None, entry, "entry", "entry", "Coach judgment: the zone's entry shape")]
    if verdict == "insufficient_data" or not policy.has_zone(current.sport_group, current.zone):
        return []
    zp = policy.zone(current.sport_group, current.zone)
    if verdict == "repeat":
        return [Candidate(shape=current, rung=current.describe(), lever="repeat", change="repeat this session",
                          direction="repeat", work_delta_pct=0.0, density_delta=0.0,
                          basis="Coach judgment: completed marginally; repeat the dose")]
    if verdict == "progress":
        return _progress(current, policy, zp)
    return _regress(current, zp, last_lever_moved([*history, current]))


def _progress(current: SessionShape, policy: LeverPolicy, zp: ZonePolicy) -> list[Candidate]:
    if is_at_ceiling(current, policy):
        return _promotions(current, policy)
    return [_candidate(current, moved, rule.lever, "up", rule.basis) for rule, moved in _moves(current, zp, forward=True)]


def _regress(current: SessionShape, zp: ZonePolicy, recent: str | None) -> list[Candidate]:
    moves = _moves(current, zp, forward=False)
    moves.sort(key=lambda m: m[0].lever != recent)  # stable: the most recent lever first
    return [_candidate(current, moved, rule.lever, "down", rule.basis) for rule, moved in moves]


# --- reading a planned move --------------------------------------------------------------------


class MoveRead(BaseModel):
    """What a planned session changed against the last reference, and which rules that breaks.
    `levers` maps each changed lever to its signed step count (positive = progressing)."""

    levers: dict[str, int] = Field(default_factory=dict)
    summary: str = ""
    same_zone: bool = True
    consolidated: bool = False
    multi_lever: bool = False
    oversized_step: bool = False
    over_ceiling: bool = False
    harder_zone_without_base: bool = False
    ceiling_source: str | None = None


def _steps_between(rule: LeverRule | None, before: float, after: float) -> int:
    """Signed grid steps from `before` to `after` along the rule (positive = progressing)."""
    if after == before:
        return 0
    if rule is None or rule.step is None:
        return 1 if (after > before) else -1
    wants_up = after > before
    forward = (rule.direction == "up") == wants_up
    count, value = 0, before
    for _ in range(GRID_STEPS_MAX):
        nxt = rule.step.next(value, up=wants_up)
        if nxt is None:
            break
        count += 1
        value = nxt
        if (value >= after - 1e-9) if wants_up else (value <= after + 1e-9):
            break
    return count if forward else -count


def _aligned(a: SessionShape, b: SessionShape) -> tuple[SessionShape, SessionShape]:
    """Both shapes in the same layout: a flat rung is read as sets of one rep against a set-based one."""
    def spread(flat: SessionShape, other: SessionShape) -> SessionShape:
        data = {**flat.model_dump(), "sets": flat.reps, "reps": 1, "set_rest_s": flat.rest_s, "rest_s": other.rest_s}
        return SessionShape.model_construct(**data)
    if a.sets > 1 and b.sets == 1 and b.reps > 1:
        return a, spread(b, a)
    if b.sets > 1 and a.sets == 1 and a.reps > 1:
        return spread(a, b), b
    return a, b


def _lever_deltas(prev: SessionShape, plan: SessionShape) -> list[tuple[str, float, float, float]]:
    """(lever, before, after, signed delta) for each lever that changed."""
    pairs = [("sets", prev.sets, plan.sets), ("reps", prev.reps, plan.reps), ("rep_size", prev.rep_size, plan.rep_size),
             ("rest", prev.rest_s, plan.rest_s)]
    return [(n, float(x), float(y), float(y - x)) for n, x, y in pairs if x != y and not (n == "rest" and 1 in (prev.reps, plan.reps))]


def _delta_text(name: str, delta: float, unit: str) -> str:
    if name in ("sets", "reps"):
        return f"{name} {delta:+g}"
    return f"{'rep' if name == 'rep_size' else name} {fmt_delta(delta, 's' if name == 'rest' else unit)}"


def classify_move(
    previous: SessionShape, planned: SessionShape, policy: LeverPolicy, *, easier_best: SessionShape | None = None
) -> MoveRead:
    """Describe `planned` against the `previous` reference: signed step counts per lever, a text summary
    and the flags `multi_lever`, `oversized_step`, `over_ceiling` and `harder_zone_without_base` (the
    planned zone is harder and `easier_best`, default `previous`, has not reached its promotion point).
    Description only; severity is the caller's."""
    read = MoveRead(same_zone=previous.zone == planned.zone)
    if planned.sport_group == previous.sport_group and policy.has_zone(planned.sport_group, planned.zone):
        _flag_ceiling(read, planned, policy.zone(planned.sport_group, planned.zone))
    if not read.same_zone:
        easier = easier_best or previous
        read.harder_zone_without_base = planned.zone > previous.zone and not is_at_ceiling(easier, policy)
        return read
    zp = policy.zone(planned.sport_group, planned.zone) if policy.has_zone(planned.sport_group, planned.zone) else None
    prev, plan = _aligned(previous, planned)
    deltas = _lever_deltas(prev, plan)
    read.summary = ", ".join(_delta_text(n, d, previous.unit) for n, _, _, d in deltas)
    _count_levers(read, deltas, zp, prev)
    progressing = [n for n, s in read.levers.items() if s > 0]
    read.multi_lever = len(progressing) > 1
    read.oversized_step = any(s > 1 for s in read.levers.values())
    return read


def _flag_ceiling(read: MoveRead, planned: SessionShape, zp: ZonePolicy) -> None:
    band = zp.band_for(planned.rep_size)
    if planned.work() > band.work * (1 + CEILING_TOLERANCE) or (zp.max_rep_size and planned.rep_size > zp.max_rep_size):
        read.over_ceiling, read.ceiling_source = True, band.source


def _count_levers(read: MoveRead, deltas: list, zp: ZonePolicy | None, prev: SessionShape) -> None:
    by_name = {n: (x, y) for n, x, y, _ in deltas}
    if "reps" in by_name and "rep_size" in by_name and by_name["reps"][1] < by_name["reps"][0] \
            and by_name["rep_size"][1] > by_name["rep_size"][0]:
        read.consolidated = True
        after = by_name["reps"][1]
        read.levers["consolidate"] = 1 if after >= math.ceil(by_name["reps"][0] / 2) else 2
        by_name.pop("reps"), by_name.pop("rep_size")
    for name, (before, after) in by_name.items():
        rule = zp.rule(name) if zp else None
        read.levers[name] = _steps_between(rule, before, after)


# --- threshold change (the on-ramp) ------------------------------------------------------------


class RebaseRead(BaseModel):
    """What a threshold change does to the reference shape."""

    shape: SessionShape
    rebased: bool
    steps_down: int = 0
    change_pct: float | None = None
    anchor_then: float | None = None
    anchor_now: float | None = None
    threshold_fell: bool = False
    reason: str


def _step_down(shape: SessionShape, zp: ZonePolicy, floor_work: float) -> SessionShape | None:
    """The first one-step-down shape (policy order reversed) that stays at or above `floor_work`; none
    once `shape` is itself at that floor."""
    if shape.work() <= floor_work + 1e-9:
        return None
    return next((m for _, m in _moves(shape, zp, forward=False) if m.work() >= floor_work - 1e-9), None)


def rebase_for_threshold_change(
    reference_shape: SessionShape, *, anchor_then: float | None, anchor_now: float | None, policy: LeverPolicy
) -> RebaseRead:
    """Restart the progression lower when the threshold rose since the reference session.

    A rise of at least the policy's `min_change_pct` steps the shape down `steps_per_pct` x the percent
    rise levers (rounded, at least 1), never below the zone's entry shape. A fall is noted and does not
    rebase upward; an unknown earlier threshold does not rebase."""
    profile = profile_named(reference_shape.sport_group)
    keep = RebaseRead(shape=reference_shape, rebased=False, anchor_then=anchor_then, anchor_now=anchor_now, reason="")
    if not anchor_then or not anchor_now:
        keep.reason = f"{profile.anchor_label} history before this session is unknown, so the progression is not restarted."
        return keep
    pct = profile.anchor_gain_pct(anchor_then, anchor_now)
    keep.change_pct = pct
    rule = policy.rebase_rule(reference_shape.sport_group, reference_shape.zone)
    moved = f"{anchor_then:g} -> {anchor_now:g} {profile.anchor_unit_label}"
    if pct <= -rule.min_change_pct:
        keep.threshold_fell, keep.reason = True, f"{profile.anchor_label} fell {abs(pct):.0f}% ({moved}) since this session; the progression is not restarted."
        return keep
    if pct < rule.min_change_pct:
        keep.reason = f"{profile.anchor_label} changed {pct:+.1f}% ({moved}), under the {rule.min_change_pct:g}% that restarts the progression."
        return keep
    return _rebased(reference_shape, policy, rule, pct, keep, f"{profile.anchor_label} {profile.anchor_gain_word} {pct:.0f}% ({moved}) since this session")


def _rebased(shape: SessionShape, policy: LeverPolicy, rule: RebaseRule, pct: float, keep: RebaseRead, lead: str) -> RebaseRead:
    zp = policy.zone(shape.sport_group, shape.zone)
    floor = policy.entry(shape.sport_group, shape.zone).work()
    wanted = max(1, round(rule.steps_per_pct * pct))
    current, taken = shape, 0
    for _ in range(wanted):
        lower = _step_down(current, zp, floor)
        if lower is None:
            break
        current, taken = lower, taken + 1
    if taken == 0:
        keep.reason = f"{lead}, but this session is already at the {shape.zone} entry level; no lower step exists."
        return keep
    plural = "step" if taken == 1 else "steps"
    short = f" (asked {wanted}; stopped at the entry level)" if taken < wanted else ""
    return keep.model_copy(update={"shape": current, "rebased": True, "steps_down": taken,
                                   "reason": f"{lead}; restarting {taken} {plural} lower{short}."})
