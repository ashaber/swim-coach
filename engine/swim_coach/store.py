"""FileStore: YAML-backed persistence for the swim-coach athlete data tree.

Behind a small interface (`StoreInterface`) so Phase 2 can swap in a
`DbStore` (same methods, Supabase-backed) without touching callers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel

from swim_coach.models import (
    Athlete,
    Event,
    MacroPlan,
    Wellness,
    WeekPlan,
    Workout,
)


def _dump_model(model: BaseModel) -> str:
    return yaml.safe_dump(model.model_dump(mode="json"), sort_keys=False)


def _dump_models(models: list[BaseModel]) -> str:
    return yaml.safe_dump([m.model_dump(mode="json") for m in models], sort_keys=False)


def _write_yaml(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _read_yaml(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


class StoreInterface(ABC):
    """Swappable persistence seam.

    `FileStore` implements this against a YAML tree today; Phase 2's
    `DbStore` implements the same interface against Supabase.
    """

    @abstractmethod
    def load_athlete(self, slug: str) -> Athlete: ...

    @abstractmethod
    def save_athlete(self, athlete: Athlete) -> None: ...

    @abstractmethod
    def load_events(self, slug: str) -> list[Event]: ...

    @abstractmethod
    def save_events(self, slug: str, events: list[Event]) -> None: ...

    @abstractmethod
    def load_macro(self, slug: str) -> MacroPlan | None: ...

    @abstractmethod
    def save_macro(self, slug: str, macro: MacroPlan) -> None: ...

    @abstractmethod
    def load_week(self, slug: str, iso_week: str) -> WeekPlan | None: ...

    @abstractmethod
    def save_week(self, slug: str, week: WeekPlan) -> None: ...

    @abstractmethod
    def list_week_ids(self, slug: str) -> list[str]:
        """Every ISO-week id (e.g. "2026-W28") this athlete has a week plan
        for, sorted chronologically. Enumerating weeks is a first-class
        store capability -- callers (e.g. the plan exporter) must not reach
        past this interface to a filesystem to discover them."""
        ...

    @abstractmethod
    def list_workouts(self, slug: str) -> list[Workout]: ...

    @abstractmethod
    def save_workout(self, slug: str, workout: Workout) -> None: ...

    @abstractmethod
    def list_wellness(self, slug: str) -> list[Wellness]: ...

    @abstractmethod
    def save_wellness(self, slug: str, wellness: Wellness) -> None: ...

    @abstractmethod
    def coach_text_exists(self, slug: str, day: date) -> bool: ...

    @abstractmethod
    def save_coach_text(self, slug: str, day: date, text: str, *, force: bool = False) -> str:
        """Persist the verbatim coach text and return its location (a path
        string for FileStore; Phase 2's DbStore would return a storage
        key). Raises FileExistsError if one already exists for this date
        and `force` is False -- callers must not silently clobber a
        previously logged coach text."""
        ...


class FileStore(StoreInterface):
    """Reads/writes the athletes/<slug>/ YAML tree described in ROADMAP.md.

    Layout (rooted at `base_dir`, default "athletes/"):
        <slug>/profile.yaml
        <slug>/events.yaml
        <slug>/plan/macro.yaml
        <slug>/plan/weeks/<iso_week>.yaml
        <slug>/logs/workouts/<date>-<sport>-<workout id[:8]>.yaml
        <slug>/logs/wellness/<date>.yaml
        <slug>/logs/coach-texts/<date>.md (verbatim, Markdown not YAML)
    """

    def __init__(self, base_dir: str | Path = "athletes") -> None:
        self.base_dir = Path(base_dir)

    def _athlete_dir(self, slug: str) -> Path:
        return self.base_dir / slug

    # --- Athlete ---------------------------------------------------------

    def load_athlete(self, slug: str) -> Athlete:
        path = self._athlete_dir(slug) / "profile.yaml"
        data = _read_yaml(path)
        if data is None:
            raise FileNotFoundError(f"no athlete profile at {path}")
        return Athlete.model_validate(data)

    def save_athlete(self, athlete: Athlete) -> None:
        path = self._athlete_dir(athlete.slug) / "profile.yaml"
        _write_yaml(path, _dump_model(athlete))

    # --- Events ------------------------------------------------------------

    def load_events(self, slug: str) -> list[Event]:
        path = self._athlete_dir(slug) / "events.yaml"
        data = _read_yaml(path)
        if data is None:
            return []
        return [Event.model_validate(item) for item in data]

    def save_events(self, slug: str, events: list[Event]) -> None:
        path = self._athlete_dir(slug) / "events.yaml"
        _write_yaml(path, _dump_models(events))

    # --- Macro plan ----------------------------------------------------------

    def load_macro(self, slug: str) -> MacroPlan | None:
        path = self._athlete_dir(slug) / "plan" / "macro.yaml"
        data = _read_yaml(path)
        if data is None:
            return None
        return MacroPlan.model_validate(data)

    def save_macro(self, slug: str, macro: MacroPlan) -> None:
        path = self._athlete_dir(slug) / "plan" / "macro.yaml"
        _write_yaml(path, _dump_model(macro))

    # --- Week plans ----------------------------------------------------------

    def load_week(self, slug: str, iso_week: str) -> WeekPlan | None:
        path = self._athlete_dir(slug) / "plan" / "weeks" / f"{iso_week}.yaml"
        data = _read_yaml(path)
        if data is None:
            return None
        return WeekPlan.model_validate(data)

    def save_week(self, slug: str, week: WeekPlan) -> None:
        path = self._athlete_dir(slug) / "plan" / "weeks" / f"{week.iso_week}.yaml"
        _write_yaml(path, _dump_model(week))

    def list_week_ids(self, slug: str) -> list[str]:
        weeks_dir = self._athlete_dir(slug) / "plan" / "weeks"
        if not weeks_dir.exists():
            return []
        # Filename stem is the iso_week ("2026-W28.yaml" -> "2026-W28"); the
        # "YYYY-Wnn" format sorts lexicographically into chronological order.
        return sorted(path.stem for path in weeks_dir.glob("*.yaml"))

    # --- Workouts ------------------------------------------------------------

    def list_workouts(self, slug: str) -> list[Workout]:
        directory = self._athlete_dir(slug) / "logs" / "workouts"
        if not directory.exists():
            return []
        workouts = []
        for path in sorted(directory.glob("*.yaml")):
            data = _read_yaml(path)
            if data is not None:
                workouts.append(Workout.model_validate(data))
        return workouts

    def save_workout(self, slug: str, workout: Workout) -> None:
        # Filename includes the first 8 chars of the workout id so that two
        # same-sport workouts logged on the same date (double pool days are
        # common) don't overwrite each other. `list_workouts` globs
        # `*.yaml` so no read-side change is needed.
        #
        # Idempotence note: re-saving a workout with the *same* id overwrites
        # only that workout's own file — this is desired (e.g. correcting a
        # previously logged workout's notes/rpe), not a collision.
        directory = self._athlete_dir(slug) / "logs" / "workouts"
        short_id = str(workout.id)[:8]
        path = directory / f"{workout.date.isoformat()}-{workout.sport}-{short_id}.yaml"
        _write_yaml(path, _dump_model(workout))

    # --- Wellness ------------------------------------------------------------

    def list_wellness(self, slug: str) -> list[Wellness]:
        directory = self._athlete_dir(slug) / "logs" / "wellness"
        if not directory.exists():
            return []
        entries = []
        for path in sorted(directory.glob("*.yaml")):
            data = _read_yaml(path)
            if data is not None:
                entries.append(Wellness.model_validate(data))
        return entries

    def save_wellness(self, slug: str, wellness: Wellness) -> None:
        directory = self._athlete_dir(slug) / "logs" / "wellness"
        path = directory / f"{wellness.date.isoformat()}.yaml"
        _write_yaml(path, _dump_model(wellness))

    # --- Coach texts (verbatim Markdown, saved BEFORE parsing) --------------------

    def _coach_text_path(self, slug: str, day: date) -> Path:
        return self._athlete_dir(slug) / "logs" / "coach-texts" / f"{day.isoformat()}.md"

    def coach_text_exists(self, slug: str, day: date) -> bool:
        return self._coach_text_path(slug, day).exists()

    def save_coach_text(self, slug: str, day: date, text: str, *, force: bool = False) -> str:
        path = self._coach_text_path(slug, day)
        if path.exists() and not force:
            raise FileExistsError(
                f"coach text already exists at {path}; pass --force to overwrite"
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return str(path)
