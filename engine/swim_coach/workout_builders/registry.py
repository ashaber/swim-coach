"""Registry of workout builders, keyed by (stimulus sport group, archetype).

Sport-neutral: a builder declares its `sport_group` (a `stimulus.SportProfile.name`), the
`Session.sport` values it serves, the stimulus kind it delivers and which `WorkoutIntent` fields it
honours (with allowed ranges). Everything sport-specific lives in the registered builders.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from pydantic import BaseModel, Field

from swim_coach.models import Athlete, WorkoutStructure
from swim_coach.stimulus import PROFILES, StimulusKind, profile_for
from swim_coach.workout_builders.intent import WorkoutIntent

# Kinds that differ only by size: stimulus.classify_kind calls an all-easy session "long" once its work
# passes the profile's long threshold, so a builder declaring either delivers either.
KIND_FAMILIES: tuple[frozenset[str], ...] = (frozenset({"endurance", "long"}),)


@dataclass(frozen=True)
class ParamRange:
    """Allowed range of one honoured intent field (`None` bound = unbounded on that side)."""

    lo: float | None = None
    hi: float | None = None
    note: str = ""

    def clamp(self, name: str, value: float, adjustments: list[str]) -> float:
        """`value` held inside the range; any change is recorded, never silent."""
        fitted = value
        if self.lo is not None and fitted < self.lo:
            fitted = self.lo
        if self.hi is not None and fitted > self.hi:
            fitted = self.hi
        if fitted != value:
            adjustments.append(f"asked {name}={_num(value)}; built {_num(fitted)} (builder range {self.describe()})")
        return fitted

    def describe(self) -> str:
        return f"{_num(self.lo) if self.lo is not None else '..'}-{_num(self.hi) if self.hi is not None else '..'}"


def _num(value: float) -> str:
    return str(int(value)) if float(value) == int(value) else f"{value:g}"


class BuildResult(BaseModel):
    """What a builder returns: the structure, its session-level intensity, and every change it made."""

    structure: WorkoutStructure
    intensity: dict
    adjustments: list[str] = Field(default_factory=list)
    duration_min: float | None = None  # only when the structure alone cannot say (e.g. no CSS)


@dataclass(frozen=True)
class WorkoutBuilder:
    sport_group: str
    archetype: str
    kind: StimulusKind
    summary: str
    sports: frozenset[str]
    params: dict[str, ParamRange] = field(default_factory=dict)
    fn: Callable[[WorkoutIntent, Athlete], BuildResult] = field(default=None, repr=False)  # type: ignore[assignment]

    def build(self, intent: WorkoutIntent, athlete: Athlete) -> BuildResult:
        return self.fn(intent, athlete)

    def delivers(self, measured_kind: str | None) -> bool:
        return measured_kind == self.kind or any({self.kind, measured_kind} <= f for f in KIND_FAMILIES)

    def as_row(self) -> dict:
        params = {
            name: ([r.lo, r.hi] if r.note == "" else [r.lo, r.hi, r.note]) for name, r in self.params.items()
        }
        return {
            "sport": self.sport_group,
            "archetype": self.archetype,
            "kind": self.kind,
            "summary": self.summary,
            "sessions": sorted(self.sports),
            "params": params,
        }


_REGISTRY: dict[tuple[str, str], WorkoutBuilder] = {}
_LOADERS: list[Callable[[], None]] = []


def register_loader(loader: Callable[[], None]) -> None:
    """Defer registering builders that need heavy data (e.g. the template library) until first use."""
    _LOADERS.append(loader)


def _run_loaders() -> None:
    while _LOADERS:
        _LOADERS.pop(0)()


def register(builder: WorkoutBuilder) -> WorkoutBuilder:
    key = (builder.sport_group, builder.archetype)
    if key in _REGISTRY:
        raise ValueError(f"workout builder {key} is already registered")
    _REGISTRY[key] = builder
    return builder


def all_builders() -> list[WorkoutBuilder]:
    _run_loaders()
    return sorted(_REGISTRY.values(), key=lambda b: (b.sport_group, b.archetype))


def known_sports() -> list[str]:
    names = {p.name for p in PROFILES}
    sessions = {s for p in PROFILES for s in p.sports}
    return sorted(names | sessions)


def _group_of(sport: str) -> tuple[str, str | None]:
    """(profile name, session sport or None) for a session sport or a profile name."""
    profile = profile_for(sport)
    if profile is not None:
        return profile.name, sport
    if any(p.name == sport for p in PROFILES):
        return sport, None
    raise ValueError(f"unknown sport {sport!r}; sports with workout builders: {known_sports()}")


def builders_for(sport: str) -> list[WorkoutBuilder]:
    """Builders for a profile name (all its archetypes) or a session sport (those it can serve)."""
    group, session_sport = _group_of(sport)
    return [
        b
        for b in all_builders()
        if b.sport_group == group and (session_sport is None or session_sport in b.sports)
    ]


def get_builder(sport: str, archetype: str) -> WorkoutBuilder:
    candidates = builders_for(sport)
    for builder in candidates:
        if builder.archetype == archetype:
            return builder
    raise ValueError(
        f"unknown archetype {archetype!r} for sport {sport!r}; available: {[b.archetype for b in candidates]}"
    )


def list_archetypes(sport: str | None = None) -> list[dict]:
    """Compact rows describing what the coach can ask for (all sports, or one)."""
    builders = all_builders() if sport is None else builders_for(sport)
    return [b.as_row() for b in builders]
