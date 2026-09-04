"""FileStore: YAML-backed persistence for the swim-coach athlete data tree.

Behind a small interface (`StoreInterface`) so Phase 2 can swap in a
`DbStore` (same methods, Supabase-backed) without touching callers.
"""

from __future__ import annotations

import filecmp
import json
import shutil
from abc import ABC, abstractmethod
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import yaml
from pydantic import BaseModel

from swim_coach.models import (
    AllowedEmail,
    Athlete,
    AuthSession,
    CoachGrant,
    Event,
    Feedback,
    HealthStatus,
    MacroPlan,
    Sport,
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
    def list_workouts(self, slug: str, *, since: date | None = None) -> list[Workout]:
        """Every logged workout for this athlete, sorted by date. `since`,
        when given, restricts the result to workouts with `date >= since`
        (inclusive) -- implementations that back a real database MUST push
        this down into the query itself (a `WHERE date >= ...` clause), not
        just filter an already-fetched full result set in Python, since the
        whole point is bounding the underlying read for athletes with a
        long logged history. `since=None` (the default) returns full
        history, unchanged from this method's original unbounded
        contract."""
        ...

    @abstractmethod
    def save_workout(self, slug: str, workout: Workout) -> None: ...

    @abstractmethod
    def get_workout(self, slug: str, workout_id: UUID) -> Workout | None:
        """Single workout by id, scoped to this athlete slug -- None if no
        workout with that id exists, OR if it exists but belongs to a
        different athlete (a wrong-athlete id must never resolve; DbStore
        enforces this via its own slug+id join, no separate ownership
        check needed)."""
        ...

    @abstractmethod
    def list_wellness(self, slug: str) -> list[Wellness]: ...

    @abstractmethod
    def save_wellness(self, slug: str, wellness: Wellness) -> None: ...

    @abstractmethod
    def save_health_status(self, slug: str, entry: HealthStatus) -> None:
        """Append one durable health-status-log entry (see
        models.HealthStatus's own docstring for why this is a log, never a
        single mutable field). Never overwrites or deletes a previous
        entry -- a new status is always a NEW entry, even when it
        supersedes an earlier one; the only in-place mutation this log ever
        allows is flipping an existing entry's `resolved`/`resolved_at`
        (see `update_health_status` below), never body-content edits."""
        ...

    @abstractmethod
    def list_health_status(self, slug: str, *, since: date | None = None) -> list[HealthStatus]:
        """Every health-status entry for this athlete, most-recent-first by
        `reported_at` (ties broken by `id`, so a caller's own ordering is
        deterministic and identical across both `FileStore` and `DbStore`
        for the same underlying data) -- same ordering convention as
        `list_feedback`. ALL entries with `resolved=False` are currently
        active simultaneously -- nothing here (or anywhere) auto-resolves
        one just because another was logged later, so a caller must
        consider every unresolved entry, not just the first one in this
        list (see `backend/app/context.py`'s `_active_health_statuses` for
        the reference implementation, including why an early version of
        that logic that only looked at the single most-recent entry was a
        real bug). If none exist, no active restriction is on file (which
        is NOT the same as "definitely fine" -- see HealthStatus's
        docstring). `since`, when given, restricts the result to entries
        with `reported_at.date() >= since` (inclusive) -- same
        push-it-into-the-query contract `list_workouts`'s `since` documents;
        `since=None` (the default) returns full history."""
        ...

    @abstractmethod
    def update_health_status(
        self, slug: str, health_status_id: UUID, *, resolved: bool, resolved_at: datetime | None
    ) -> HealthStatus | None:
        """Marks one existing entry resolved/unresolved -- the one in-place
        mutation this log allows (see `save_health_status`'s docstring).
        Returns the updated entry, or None if `health_status_id` doesn't
        match any entry for this athlete."""
        ...

    @abstractmethod
    def save_feedback(self, entry: Feedback) -> None:
        """Append one durable feedback-log entry (coach research questions,
        athlete feature requests/comments/bugs -- see models.Feedback).
        Never overwrites or deletes a previous entry."""
        ...

    @abstractmethod
    def list_feedback(
        self, *, athlete: str | None = None, limit: int | None = None
    ) -> list[Feedback]:
        """Every feedback entry, most-recent-first. `athlete`, if given, must
        be a known athlete slug (raises FileNotFoundError otherwise, matching
        `load_athlete`) and restricts the list to entries tied to that
        athlete's id; omitted, every entry (across all athletes, plus any
        with no athlete_id) is returned. `limit` caps the number returned."""
        ...

    @abstractmethod
    def get_feedback(self, feedback_id: UUID) -> Feedback | None:
        """Single feedback entry by id (across all athletes), or None if no
        entry has that id."""
        ...

    @abstractmethod
    def update_feedback(
        self,
        feedback_id: UUID,
        *,
        status: str | None = None,
        context: dict | None = None,
        needs_human_review: bool | None = None,
        coach_athlete_id: UUID | None = None,
        coach_reply: str | None = None,
        coach_reply_at: datetime | None = None,
    ) -> Feedback | None:
        """Patch an existing feedback entry: `status`, if given, replaces the
        current value; `context`, if given, is shallow-merged into the
        existing context dict (new keys added, overlapping keys overwritten,
        untouched keys preserved) -- never a wholesale clobber.
        `needs_human_review`/`coach_athlete_id`/`coach_reply`/
        `coach_reply_at` are plain scalar fields, each independently
        settable: same "None means unchanged, given means replace" contract
        as `status` (NOT a merge like `context`). Returns the updated entry,
        or None if `feedback_id` doesn't match any entry."""
        ...

    # --- Coach grants (coach-mode Chunk A) --------------------------------

    @abstractmethod
    def create_coach_grant(
        self, *, coach_slug: str, athlete_slug: str, chat_visibility: str = "shared_only"
    ) -> CoachGrant:
        """Grant `coach_slug` coach access to `athlete_slug`'s data. Both
        slugs must be known athletes (raises FileNotFoundError otherwise,
        matching `load_athlete`'s contract). Raises ValueError if
        `coach_slug == athlete_slug` -- a grant to yourself is meaningless."""
        ...

    @abstractmethod
    def list_coach_grants(
        self,
        *,
        coach_slug: str | None = None,
        athlete_slug: str | None = None,
        status: str | None = None,
    ) -> list[CoachGrant]:
        """Every coach grant, filtered by any combination of `coach_slug`
        (grants where this athlete is the coach), `athlete_slug` (grants
        where this athlete is being coached), and `status` -- or all grants
        if none are given. Either slug given must be a known athlete (raises
        FileNotFoundError otherwise, same convention as
        `list_feedback(athlete=...)`)."""
        ...

    @abstractmethod
    def revoke_coach_grant(self, grant_id: UUID) -> CoachGrant | None:
        """Sets `status="revoked"` and `revoked_at=now()`. Returns the
        updated grant, or None if no grant has that id. Idempotent-safe:
        revoking an already-revoked grant just re-sets `revoked_at` again,
        no special-casing."""
        ...

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

    # --- Verified identity (Slice 1: allowed_emails + sessions) -----------

    @abstractmethod
    def add_allowed_email(
        self, email: str, *, athlete: str | None = None, note: str | None = None
    ) -> AllowedEmail:
        """Add (or re-invite -- upsert keyed by normalized email) a beta
        user. Raises FileNotFoundError if `athlete` is given and doesn't
        match a known athlete slug (same convention as every other
        slug-taking method here). `email` is normalized (stripped,
        lowercased) before storage; a second call with the same email (any
        casing/whitespace) updates the existing entry's athlete/note rather
        than creating a duplicate.

        `athlete=None` (the default) creates a PENDING/onboarding invite --
        an email allowlisted before any athlete exists for it (Slice 1 of
        self-service onboarding). Re-inviting the same email later with an
        `athlete` given upserts it from pending to athlete-bound -- the
        state transition IS this upsert, no separate "claim" step."""
        ...

    @abstractmethod
    def get_allowed_email(self, email: str) -> AllowedEmail | None:
        """Normalized-email lookup, or None if not allowlisted. Never
        raises -- an absent entry is an expected, athlete-facing "request
        access" state, not an error."""
        ...

    @abstractmethod
    def list_allowed_emails(self) -> list[AllowedEmail]:
        """Every allowlist entry, oldest-invited-first (ties broken by
        email) -- what `swim_coach.cli`'s `list-invites` prints."""
        ...

    @abstractmethod
    def remove_allowed_email(self, email: str) -> bool:
        """Revoke one invite. Returns True if an entry existed and was
        removed, False if the (normalized) email wasn't allowlisted."""
        ...

    @abstractmethod
    def create_session(
        self,
        token_hash: str,
        *,
        athlete: str | None = None,
        pending_email: str | None = None,
        expires_at: datetime,
    ) -> AuthSession:
        """Mint a new session row for an already-verified sign-in. Raises
        FileNotFoundError if `athlete` is given and doesn't match a known
        athlete. `token_hash` is the sha256 hex digest of the raw session
        token -- the raw token itself is never passed to or stored by the
        store.

        `athlete=None` (the default) mints an ONBOARDING session -- for an
        allowlisted email with no athlete behind it yet (Slice 1 of
        self-service onboarding). See `AuthSession.athlete_slug`'s
        docstring. `pending_email` (Slice 2 of self-service onboarding) is
        the verified email that onboarding session belongs to -- callers pass
        it only when `athlete` is None; see `AuthSession.pending_email`'s
        docstring."""
        ...

    @abstractmethod
    def get_session(self, token_hash: str) -> AuthSession | None:
        """Looks up a session by its token's sha256 hex digest, or None if
        no such session exists. Returned AS-IS -- expiry/revocation are
        deliberately NOT evaluated here (no notion of "now" at the store
        layer); `require_auth` (backend/app/auth.py) checks `expires_at`/
        `revoked_at` against the current time itself."""
        ...

    @abstractmethod
    def revoke_session(self, token_hash: str) -> bool:
        """Marks a session revoked (idempotent -- revoking an
        already-revoked session is a no-op success). Returns True if a
        session with that token_hash existed at all, False otherwise."""
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

    def list_workouts(self, slug: str, *, since: date | None = None) -> list[Workout]:
        directory = self._athlete_dir(slug) / "logs" / "workouts"
        if not directory.exists():
            return []
        workouts = []
        for path in sorted(directory.glob("*.yaml")):
            data = _read_yaml(path)
            if data is not None:
                workout = Workout.model_validate(data)
                # Filtered in Python, not by filename -- this is the
                # dev/test-only file-backed store (real production reads go
                # through DbStore.list_workouts, which pushes `since` into
                # the SQL `WHERE` clause instead; see StoreInterface's
                # docstring on this param).
                if since is not None and workout.date < since:
                    continue
                workouts.append(workout)
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

    def get_workout(self, slug: str, workout_id: UUID) -> Workout | None:
        # No id-indexed filename (see save_workout's naming scheme) -- scan
        # this athlete's own workouts. Dev/test-only file-backed store, same
        # tradeoff list_workouts already makes; a wrong-athlete id is
        # naturally excluded since we only ever scan `slug`'s own directory.
        for workout in self.list_workouts(slug):
            if workout.id == workout_id:
                return workout
        return None

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

    # --- Health status (durable injury/illness log) -------------------------

    def _health_status_path(self, slug: str, entry: HealthStatus) -> Path:
        # One file per entry (never one-per-date like wellness -- multiple
        # health-status entries can legitimately land the same day, e.g. an
        # athlete self-report followed later by a coach relaying practitioner
        # guidance). Mirrors save_workout's "date + short id" naming so two
        # same-day entries never collide.
        directory = self._athlete_dir(slug) / "logs" / "health-status"
        short_id = str(entry.id)[:8]
        return directory / f"{entry.reported_at.date().isoformat()}-{short_id}.yaml"

    def save_health_status(self, slug: str, entry: HealthStatus) -> None:
        _write_yaml(self._health_status_path(slug, entry), _dump_model(entry))

    def list_health_status(self, slug: str, *, since: date | None = None) -> list[HealthStatus]:
        directory = self._athlete_dir(slug) / "logs" / "health-status"
        if not directory.exists():
            return []
        entries = []
        for path in sorted(directory.glob("*.yaml")):
            data = _read_yaml(path)
            if data is not None:
                entry = HealthStatus.model_validate(data)
                if since is not None and entry.reported_at.date() < since:
                    continue
                entries.append(entry)
        # Two-pass STABLE sort (Python's sort() guarantees stability) so a
        # tie on identical `reported_at` breaks by `id` ascending, matching
        # DbStore.list_health_status's `order by h.reported_at desc, h.id`
        # exactly -- a real review finding: without an explicit, matching
        # tiebreak, FileStore fell back to filename/glob order for ties
        # while DbStore broke them by id, so which entry counted as "most
        # recent" (and therefore which one _active_health_statuses treats
        # as most-severe/most-recent among equally-timed entries) could
        # differ depending on which backend held the exact same data.
        entries.sort(key=lambda e: str(e.id))
        entries.sort(key=lambda e: e.reported_at, reverse=True)
        return entries

    def update_health_status(
        self, slug: str, health_status_id: UUID, *, resolved: bool, resolved_at: datetime | None
    ) -> HealthStatus | None:
        for entry in self.list_health_status(slug):
            if entry.id == health_status_id:
                updated = entry.model_copy(update={"resolved": resolved, "resolved_at": resolved_at})
                _write_yaml(self._health_status_path(slug, updated), _dump_model(updated))
                return updated
        return None

    # --- Feedback (durable, replaces research/open-questions.jsonl) --------

    def _feedback_path(self) -> Path:
        # Deliberately a single file directly under base_dir (a sibling of
        # every athlete's own slug directory), not per-athlete -- a
        # feedback entry may have no athlete_id at all (see models.Feedback),
        # and this is the local/dev analogue of DbStore's single `feedback`
        # table shared across all athletes.
        return self.base_dir / "feedback.jsonl"

    def save_feedback(self, entry: Feedback) -> None:
        path = self._feedback_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry.model_dump(mode="json")) + "\n")

    def list_feedback(
        self, *, athlete: str | None = None, limit: int | None = None
    ) -> list[Feedback]:
        path = self._feedback_path()
        entries: list[Feedback] = []
        if path.exists():
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        entries.append(Feedback.model_validate(json.loads(line)))

        if athlete is not None:
            athlete_id = self.load_athlete(athlete).id  # raises FileNotFoundError if unknown
            entries = [e for e in entries if e.athlete_id == athlete_id]

        entries.sort(key=lambda e: e.created_at, reverse=True)
        if limit is not None:
            entries = entries[:limit]
        return entries

    def _load_all_feedback(self) -> list[Feedback]:
        """Every feedback entry, file order (not sorted) -- the internal
        helper `get_feedback`/`update_feedback` use to avoid re-implementing
        the jsonl read loop `list_feedback` already has above."""
        path = self._feedback_path()
        entries: list[Feedback] = []
        if path.exists():
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        entries.append(Feedback.model_validate(json.loads(line)))
        return entries

    def get_feedback(self, feedback_id: UUID) -> Feedback | None:
        for entry in self._load_all_feedback():
            if entry.id == feedback_id:
                return entry
        return None

    def update_feedback(
        self,
        feedback_id: UUID,
        *,
        status: str | None = None,
        context: dict | None = None,
        needs_human_review: bool | None = None,
        coach_athlete_id: UUID | None = None,
        coach_reply: str | None = None,
        coach_reply_at: datetime | None = None,
    ) -> Feedback | None:
        entries = self._load_all_feedback()
        updated: Feedback | None = None
        for i, entry in enumerate(entries):
            if entry.id != feedback_id:
                continue
            new_status = status if status is not None else entry.status
            new_context = {**entry.context, **context} if context is not None else entry.context
            new_needs_human_review = (
                needs_human_review if needs_human_review is not None else entry.needs_human_review
            )
            new_coach_athlete_id = (
                coach_athlete_id if coach_athlete_id is not None else entry.coach_athlete_id
            )
            new_coach_reply = coach_reply if coach_reply is not None else entry.coach_reply
            new_coach_reply_at = (
                coach_reply_at if coach_reply_at is not None else entry.coach_reply_at
            )
            updated = entry.model_copy(
                update={
                    "status": new_status,
                    "context": new_context,
                    "needs_human_review": new_needs_human_review,
                    "coach_athlete_id": new_coach_athlete_id,
                    "coach_reply": new_coach_reply,
                    "coach_reply_at": new_coach_reply_at,
                }
            )
            entries[i] = updated
            break
        if updated is None:
            return None
        path = self._feedback_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for entry in entries:
                fh.write(json.dumps(entry.model_dump(mode="json")) + "\n")
        return updated

    # --- Coach grants (coach-mode Chunk A) ----------------------------------

    def _coach_grants_path(self) -> Path:
        # Deliberately a single file directly under base_dir (a sibling of
        # every athlete's own slug directory), not per-athlete -- a grant
        # belongs to two athletes at once (coach and coached), so it doesn't
        # fit the per-slug-directory convention most FileStore data uses.
        # Same rationale as `_feedback_path` above.
        return self.base_dir / "coach_grants.jsonl"

    def _load_all_coach_grants(self) -> list[CoachGrant]:
        """Every coach grant, file order (not sorted) -- the internal helper
        `list_coach_grants`/`revoke_coach_grant` use to avoid re-implementing
        the jsonl read loop, mirroring `_load_all_feedback`."""
        path = self._coach_grants_path()
        entries: list[CoachGrant] = []
        if path.exists():
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        entries.append(CoachGrant.model_validate(json.loads(line)))
        return entries

    def create_coach_grant(
        self, *, coach_slug: str, athlete_slug: str, chat_visibility: str = "shared_only"
    ) -> CoachGrant:
        if coach_slug == athlete_slug:
            raise ValueError(f"a grant to yourself is meaningless: {coach_slug!r}")
        coach_id = self.load_athlete(coach_slug).id  # raises FileNotFoundError if unknown
        athlete_id = self.load_athlete(athlete_slug).id  # raises FileNotFoundError if unknown
        grant = CoachGrant(
            id=uuid4(),
            coach_athlete_id=coach_id,
            athlete_id=athlete_id,
            chat_visibility=chat_visibility,
            granted_at=datetime.now(timezone.utc),
        )
        path = self._coach_grants_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(grant.model_dump(mode="json")) + "\n")
        return grant

    def list_coach_grants(
        self,
        *,
        coach_slug: str | None = None,
        athlete_slug: str | None = None,
        status: str | None = None,
    ) -> list[CoachGrant]:
        entries = self._load_all_coach_grants()

        if coach_slug is not None:
            coach_id = self.load_athlete(coach_slug).id  # raises FileNotFoundError if unknown
            entries = [g for g in entries if g.coach_athlete_id == coach_id]
        if athlete_slug is not None:
            athlete_id = self.load_athlete(athlete_slug).id  # raises FileNotFoundError if unknown
            entries = [g for g in entries if g.athlete_id == athlete_id]
        if status is not None:
            entries = [g for g in entries if g.status == status]

        return entries

    def revoke_coach_grant(self, grant_id: UUID) -> CoachGrant | None:
        entries = self._load_all_coach_grants()
        updated: CoachGrant | None = None
        for i, entry in enumerate(entries):
            if entry.id != grant_id:
                continue
            updated = entry.model_copy(
                update={"status": "revoked", "revoked_at": datetime.now(timezone.utc)}
            )
            entries[i] = updated
            break
        if updated is None:
            return None
        path = self._coach_grants_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for entry in entries:
                fh.write(json.dumps(entry.model_dump(mode="json")) + "\n")
        return updated

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

    # --- Series sidecar + raw file (.fit workout-analytics Slice 1) -----------

    def save_series(
        self, slug: str, day: date, sport: Sport, workout_id: UUID, series: dict
    ) -> str:
        """Write a workout's columnar time-series sidecar JSON and return its
        path. Filename mirrors save_workout's own naming convention
        (date-sport-id[:8]) so the two files are trivially pairable by eye.
        Unconditionally overwrites -- callers (cli.py's `ingest`/`analyze`)
        always re-derive the sidecar from a freshly parsed .fit, so there is
        no "don't clobber prior data" concern here the way there is for
        save_coach_text's verbatim human input."""
        path = self._athlete_dir(slug) / "logs" / "series" / f"{day.isoformat()}-{sport}-{str(workout_id)[:8]}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(series), encoding="utf-8")
        return str(path)

    def save_raw_file(self, slug: str, src_path: str | Path) -> str:
        """Copy a raw device export (.fit/.tcx/.csv) into
        athletes/<slug>/logs/files/<original filename>, and return the
        managed copy's path as `raw_ref`.

        Idempotent by content: re-ingesting the same file (same bytes) is a
        no-op. Raises FileExistsError if a *different* file already sits at
        that destination filename -- callers must not silently clobber a
        previously ingested raw file with same-named-but-different content
        (e.g. two different Garmin exports both named "ACTIVITY.fit")."""
        src_path = Path(src_path)
        directory = self._athlete_dir(slug) / "logs" / "files"
        directory.mkdir(parents=True, exist_ok=True)
        dest_path = directory / src_path.name
        if dest_path.exists():
            if filecmp.cmp(src_path, dest_path, shallow=False):
                return str(dest_path)
            raise FileExistsError(
                f"{dest_path} already exists with different content than {src_path}; "
                "refusing to silently overwrite a previously ingested raw file"
            )
        shutil.copyfile(src_path, dest_path)
        return str(dest_path)

    # --- Verified identity (Slice 1: allowed_emails + sessions) -----------
    #
    # Local/dev analogue of DbStore's two tables: a single JSON dict per
    # concern, directly under base_dir (siblings of every athlete's own slug
    # directory), same rationale as _feedback_path -- these aren't
    # per-athlete data, they're small cross-athlete lookup tables.

    def _allowed_emails_path(self) -> Path:
        return self.base_dir / "allowed_emails.json"

    def _read_json_dict(self, path: Path) -> dict:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json_dict(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    def add_allowed_email(
        self, email: str, *, athlete: str | None = None, note: str | None = None
    ) -> AllowedEmail:
        if athlete is not None:
            self.load_athlete(athlete)  # raises FileNotFoundError if unknown
        normalized = email.strip().lower()
        path = self._allowed_emails_path()
        data = self._read_json_dict(path)
        existing = data.get(normalized)
        created_at = (
            AllowedEmail.model_validate(existing).created_at
            if existing is not None
            else datetime.now(timezone.utc)
        )
        entry = AllowedEmail(
            email=normalized, athlete_slug=athlete, note=note, created_at=created_at
        )
        data[normalized] = entry.model_dump(mode="json")
        self._write_json_dict(path, data)
        return entry

    def get_allowed_email(self, email: str) -> AllowedEmail | None:
        normalized = email.strip().lower()
        row = self._read_json_dict(self._allowed_emails_path()).get(normalized)
        return AllowedEmail.model_validate(row) if row is not None else None

    def list_allowed_emails(self) -> list[AllowedEmail]:
        data = self._read_json_dict(self._allowed_emails_path())
        entries = [AllowedEmail.model_validate(row) for row in data.values()]
        entries.sort(key=lambda e: (e.created_at, e.email))
        return entries

    def remove_allowed_email(self, email: str) -> bool:
        normalized = email.strip().lower()
        path = self._allowed_emails_path()
        data = self._read_json_dict(path)
        if normalized not in data:
            return False
        del data[normalized]
        self._write_json_dict(path, data)
        return True

    def _sessions_path(self) -> Path:
        return self.base_dir / "sessions.json"

    def create_session(
        self,
        token_hash: str,
        *,
        athlete: str | None = None,
        pending_email: str | None = None,
        expires_at: datetime,
    ) -> AuthSession:
        if athlete is not None:
            self.load_athlete(athlete)  # raises FileNotFoundError if unknown
        path = self._sessions_path()
        data = self._read_json_dict(path)
        entry = AuthSession(
            token_hash=token_hash,
            athlete_slug=athlete,
            pending_email=pending_email,
            created_at=datetime.now(timezone.utc),
            expires_at=expires_at,
            revoked_at=None,
        )
        data[token_hash] = entry.model_dump(mode="json")
        self._write_json_dict(path, data)
        return entry

    def get_session(self, token_hash: str) -> AuthSession | None:
        row = self._read_json_dict(self._sessions_path()).get(token_hash)
        return AuthSession.model_validate(row) if row is not None else None

    def revoke_session(self, token_hash: str) -> bool:
        path = self._sessions_path()
        data = self._read_json_dict(path)
        row = data.get(token_hash)
        if row is None:
            return False
        row["revoked_at"] = datetime.now(timezone.utc).isoformat()
        data[token_hash] = row
        self._write_json_dict(path, data)
        return True
