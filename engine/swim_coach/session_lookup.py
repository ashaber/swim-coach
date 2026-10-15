"""The ONE place a planned `Session` is resolved from a coach/athlete reference.

A session is addressed by its `Session.id` (a full UUID or a unique hex prefix, see
`SHORT_ID_LEN`). `(date, sport)` is only a fallback, accepted when it names exactly one
session; when a day holds several same-sport sessions (a warm-up ride plus the race, a road
race plus a crit) it is rejected with `AmbiguousSession`, whose message lists every candidate's
id, title and kind so the caller can retry with `session_id`.

Ordering: `day_order` sorts a day's sessions the way they happen -- warm-up/opener before the
race -- which is the display order and the matching order for workouts (`quality`).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date as Date
from typing import TYPE_CHECKING
from uuid import UUID

from swim_coach.models import Session

if TYPE_CHECKING:
    from swim_coach.store import StoreInterface

# Compact id shown in coach context: 8 hex chars is unique within any realistic athlete-week
# and cheap in tokens; `find_session` accepts any unique prefix of at least MIN_PREFIX_LEN.
SHORT_ID_LEN = 8
MIN_PREFIX_LEN = 4

# Chronological tendency of a session kind within one day. Coach judgment: a warm-up/opener
# precedes the main effort and a race is the day's last planned item.
KIND_RANK = {"warmup": 0, "opener": 1, "workout": 2, "free_ride": 3, "race": 4}


class SessionLookupError(LookupError):
    """No single planned session could be resolved from the reference."""


class SessionNotFound(SessionLookupError):
    pass


class AmbiguousSession(SessionLookupError):
    """More than one session fits the reference. `candidates` are those sessions."""

    def __init__(self, message: str, candidates: list[Session]) -> None:
        super().__init__(message)
        self.candidates = candidates


def short_id(session: Session) -> str:
    return str(session.id)[:SHORT_ID_LEN]


def day_order(session: Session) -> tuple[Date, int]:
    """Sort key placing a day's sessions in the order they happen (kind, stable otherwise)."""
    return session.date, KIND_RANK.get(session.effective_kind, KIND_RANK["workout"])


def describe(session: Session) -> str:
    label = session.title or session.purpose
    return f"{short_id(session)} {session.sport} {session.date.isoformat()} kind={session.effective_kind} {label!r}"


def describe_all(sessions: Iterable[Session]) -> str:
    return "; ".join(describe(s) for s in sessions)


def _parse_date(value: Date | str | None) -> Date | None:
    if value is None or isinstance(value, Date):
        return value
    try:
        return Date.fromisoformat(value)
    except ValueError as exc:
        raise SessionNotFound(f"invalid date {value!r}; expected 'YYYY-MM-DD'") from exc


def _by_id(sessions: list[Session], ref: str | UUID) -> Session:
    text = str(ref).strip().lower()
    if len(text) < MIN_PREFIX_LEN:
        raise SessionNotFound(f"session_id {ref!r} is too short; pass the id shown in the plan")
    hits = [s for s in sessions if str(s.id).startswith(text)]
    if not hits:
        raise SessionNotFound(f"no session with id {ref!r}; sessions: {describe_all(sessions)}")
    if len(hits) > 1:
        raise AmbiguousSession(f"session_id {ref!r} matches several sessions: {describe_all(hits)}", hits)
    return hits[0]


def candidates_on(sessions: Iterable[Session], *, date: Date | str | None, sport: str | None = None) -> list[Session]:
    """Sessions on `date` (and of `sport` when given), in the order they happen."""
    target = _parse_date(date)
    hits = [s for s in sessions if s.date == target and (sport is None or s.sport == sport)]
    return sorted(hits, key=day_order)


def find_session(
    sessions: Iterable[Session],
    *,
    session_id: str | UUID | None = None,
    date: Date | str | None = None,
    sport: str | None = None,
) -> Session:
    """Resolve exactly one session. `session_id` wins outright; otherwise `date` (+ optional
    `sport`) must name a single session. Raises `SessionNotFound` / `AmbiguousSession`."""
    pool = list(sessions)
    if session_id:
        return _by_id(pool, session_id)
    if date is None:
        raise SessionNotFound("pass session_id, or date (+ sport)")
    hits = candidates_on(pool, date=date, sport=sport)
    if not hits:
        same_day = candidates_on(pool, date=date)
        raise SessionNotFound(
            f"found 0 sessions on {date}" + (f" with sport {sport!r}" if sport else "")
            + (f"; sessions that day: {describe_all(same_day)}" if same_day else "")
        )
    if len(hits) > 1:
        raise AmbiguousSession(
            f"found {len(hits)} sessions on {date}" + (f" with sport {sport!r}" if sport else "")
            + f" -- pass session_id to disambiguate: {describe_all(hits)}",
            hits,
        )
    return hits[0]


def find_in_store(store: StoreInterface, athlete: str, session_id: UUID) -> Session | None:
    """The session with exactly this id in any of `athlete`'s weeks (`StoreInterface` has no by-id
    lookup -- weeks are the unit of storage -- so this scans `list_week_ids`)."""
    for iso_week in store.list_week_ids(athlete):
        week = store.load_week(athlete, iso_week)
        for session in week.sessions if week is not None else []:
            if session.id == session_id:
                return session
    return None


def resolve_in_store(store: StoreInterface, athlete: str, ref: str | UUID) -> Session:
    """`find_session(session_id=ref)` across every week on file -- accepts the full id or the unique
    short prefix the plan context shows. Raises `SessionNotFound` / `AmbiguousSession`."""
    pool: list[Session] = []
    for iso_week in store.list_week_ids(athlete):
        week = store.load_week(athlete, iso_week)
        if week is not None:
            pool.extend(week.sessions)
    return find_session(pool, session_id=ref)
