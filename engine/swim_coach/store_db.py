"""DbStore: Supabase/Postgres-backed implementation of StoreInterface.

Same 14-method contract as FileStore (store.py), so callers swap between them
via the backend's `make_store` factory without any other change (the seam
built in Phase 1).

Two layers live here:

  1. Pure row<->model mapping functions (`*_to_row` / `row_to_*`). These have
     NO psycopg dependency and are unit-tested without a live connection
     (tests/unit/test_store_db_mapping.py). Each model's full JSON goes in the
     `data` column; query-relevant fields are also promoted to real columns.

  2. `DbStore`, which wires those mappers to SQL. **psycopg is imported lazily**
     (inside `__init__`) so that `import swim_coach.store_db` -- and, more
     importantly, `import swim_coach.store` and the CLI -- work with psycopg
     NOT installed. psycopg is an optional extra: `pip install swim-coach-engine[db]`.

Connection strategy: one short-lived connection per operation (open -> work ->
commit/rollback -> close), via psycopg's own connection context manager. This
low-traffic, single-athlete app does not need a pool; correctness and
simplicity win. A pool can be dropped in behind `_connect` later if needed.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from swim_coach.models import (
    AllowedEmail,
    Athlete,
    AuthSession,
    Event,
    Feedback,
    MacroPlan,
    Wellness,
    WeekPlan,
    Workout,
)
from swim_coach.store import StoreInterface

# --------------------------------------------------------------------------
# Pure row <-> model mapping (no psycopg needed -- unit-tested standalone).
#
# `data` always holds the full model_dump(mode="json"); row_to_* reconstructs
# purely from that column. The extra columns are denormalized for querying and
# are asserted to agree with `data` by the mapping round-trip tests.
# --------------------------------------------------------------------------


def athlete_to_row(athlete: Athlete) -> dict[str, Any]:
    return {
        "athlete_id": athlete.id,
        "slug": athlete.slug,
        "schema_version": athlete.schema_version,
        "data": athlete.model_dump(mode="json"),
    }


def row_to_athlete(row: dict[str, Any]) -> Athlete:
    return Athlete.model_validate(row["data"])


def event_to_row(event: Event) -> dict[str, Any]:
    return {
        "id": event.id,
        "athlete_id": event.athlete_id,
        "event_date": event.event_date,
        "schema_version": event.schema_version,
        "data": event.model_dump(mode="json"),
    }


def row_to_event(row: dict[str, Any]) -> Event:
    return Event.model_validate(row["data"])


def macro_to_row(macro: MacroPlan) -> dict[str, Any]:
    return {
        "athlete_id": macro.athlete_id,
        "id": macro.id,
        "event_id": macro.event_id,
        "schema_version": macro.schema_version,
        "data": macro.model_dump(mode="json"),
    }


def row_to_macro(row: dict[str, Any]) -> MacroPlan:
    return MacroPlan.model_validate(row["data"])


def week_to_row(week: WeekPlan) -> dict[str, Any]:
    return {
        "id": week.id,
        "athlete_id": week.athlete_id,
        "iso_week": week.iso_week,
        "schema_version": week.schema_version,
        "data": week.model_dump(mode="json"),
    }


def row_to_week(row: dict[str, Any]) -> WeekPlan:
    return WeekPlan.model_validate(row["data"])


def workout_to_row(workout: Workout) -> dict[str, Any]:
    return {
        "id": workout.id,
        "athlete_id": workout.athlete_id,
        "date": workout.date,
        "sport": workout.sport,
        "schema_version": workout.schema_version,
        "data": workout.model_dump(mode="json"),
    }


def row_to_workout(row: dict[str, Any]) -> Workout:
    return Workout.model_validate(row["data"])


def wellness_to_row(wellness: Wellness) -> dict[str, Any]:
    return {
        "id": wellness.id,
        "athlete_id": wellness.athlete_id,
        "date": wellness.date,
        "schema_version": wellness.schema_version,
        "data": wellness.model_dump(mode="json"),
    }


def row_to_wellness(row: dict[str, Any]) -> Wellness:
    return Wellness.model_validate(row["data"])


def feedback_to_row(feedback: Feedback) -> dict[str, Any]:
    """Unlike the other `*_to_row` mappers, `feedback` has no `data` JSONB
    blob -- every Feedback field maps directly onto its own column (the
    migration's literal spec), so `row_to_feedback` reconstructs the model
    from those columns rather than from a single JSON payload."""
    return {
        "id": feedback.id,
        "athlete_id": feedback.athlete_id,
        "type": feedback.type,
        "source": feedback.source,
        "body": feedback.body,
        "context": feedback.context,
        "status": feedback.status,
        "created_at": feedback.created_at,
    }


def row_to_feedback(row: dict[str, Any]) -> Feedback:
    return Feedback(
        schema_version=1,
        id=row["id"],
        athlete_id=row["athlete_id"],
        type=row["type"],
        source=row["source"],
        body=row["body"],
        context=row["context"] or {},
        status=row["status"],
        created_at=row["created_at"],
    )


def row_to_allowed_email(row: dict[str, Any]) -> AllowedEmail:
    """Unlike the other `row_to_*` mappers, this expects a JOINED row (`ae.*`
    + `a.slug as athlete_slug`) -- `allowed_emails` itself only has an
    `athlete_id` FK column, never the slug. See DbStore.get_allowed_email/
    list_allowed_emails, the only callers that build such a row.

    `row["athlete_slug"]` is None for a PENDING/onboarding invite (Slice 1
    self-service onboarding) -- DbStore's join is a LEFT JOIN precisely so a
    row with `athlete_id IS NULL` still comes back (an INNER JOIN would drop
    it silently)."""
    return AllowedEmail(
        email=row["email"],
        athlete_slug=row["athlete_slug"],
        note=row["note"],
        created_at=row["created_at"],
    )


def row_to_auth_session(row: dict[str, Any]) -> AuthSession:
    """Same joined-row (LEFT JOIN) convention as row_to_allowed_email above
    (`s.*` + `a.slug as athlete_slug`) -- `auth_sessions` itself only has an
    `athlete_id` FK. `row["athlete_slug"]` is None for an onboarding
    session; `row["pending_email"]` (Slice 2 of self-service onboarding) is
    a plain column on `auth_sessions` itself, no join needed -- set only for
    an onboarding session, always None for an athlete-bound one."""
    return AuthSession(
        token_hash=row["token_hash"],
        athlete_slug=row["athlete_slug"],
        pending_email=row["pending_email"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        revoked_at=row["revoked_at"],
    )


def coach_text_storage_key(slug: str, day: date) -> str:
    """Location string returned by save_coach_text (DbStore's analogue of
    FileStore's on-disk path)."""
    return f"db://coach_texts/{slug}/{day.isoformat()}"


# --------------------------------------------------------------------------
# DbStore
# --------------------------------------------------------------------------


class DbStore(StoreInterface):
    """Postgres/Supabase-backed store. psycopg imported lazily so the engine
    core imports fine without it."""

    def __init__(self, dsn: str) -> None:
        if not dsn:
            raise ValueError("DbStore requires a non-empty DSN (DATABASE_URL)")
        self._dsn = dsn
        # Lazy import: keeps `import swim_coach.store`/CLI working when psycopg
        # is not installed. Only constructing a DbStore requires the extra.
        try:
            import psycopg  # noqa: F401
            from psycopg.rows import dict_row  # noqa: F401
            from psycopg.types.json import Jsonb  # noqa: F401
        except ImportError as exc:  # pragma: no cover - exercised via extra-absent path
            raise ImportError(
                "DbStore requires the optional 'db' extra. Install with "
                "`pip install swim-coach-engine[db]` (or `pip install psycopg[binary]`)."
            ) from exc
        self._psycopg = psycopg
        self._dict_row = dict_row
        self._Jsonb = Jsonb

    # --- connection -----------------------------------------------------

    def _connect(self):
        """A fresh connection whose context manager commits on success,
        rolls back on exception, and closes on exit (psycopg3 semantics).

        `prepare_threshold=None` DISABLES server-side prepared statements. This
        is required to run against Supabase's pgbouncer transaction pooler
        (port 6543): in transaction pooling mode a client connection is not
        pinned to one server backend, so a prepared statement created on one
        backend is absent on the next and the query fails. (Note: psycopg's
        `prepare_threshold=0` means "prepare on first use" -- the opposite of
        what's wanted here; `None` is the disable value.)"""
        return self._psycopg.connect(
            self._dsn,
            row_factory=self._dict_row,
            prepare_threshold=None,
        )

    def _athlete_id(self, cur, slug: str) -> UUID:
        cur.execute("select athlete_id from athletes where slug = %s", (slug,))
        row = cur.fetchone()
        if row is None:
            raise FileNotFoundError(f"no athlete with slug {slug!r}")
        return row["athlete_id"]

    # --- Athlete --------------------------------------------------------

    def load_athlete(self, slug: str) -> Athlete:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("select data from athletes where slug = %s", (slug,))
            row = cur.fetchone()
        if row is None:
            raise FileNotFoundError(f"no athlete profile for slug {slug!r}")
        return row_to_athlete(row)

    def save_athlete(self, athlete: Athlete) -> None:
        row = athlete_to_row(athlete)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                insert into athletes (athlete_id, slug, schema_version, data)
                values (%(athlete_id)s, %(slug)s, %(schema_version)s, %(data)s)
                on conflict (athlete_id) do update set
                    slug = excluded.slug,
                    schema_version = excluded.schema_version,
                    data = excluded.data,
                    updated_at = now()
                """,
                {**row, "data": self._Jsonb(row["data"])},
            )

    # --- Events ---------------------------------------------------------

    def load_events(self, slug: str) -> list[Event]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                select e.data from events e
                join athletes a on a.athlete_id = e.athlete_id
                where a.slug = %s
                order by e.event_date, e.id
                """,
                (slug,),
            )
            rows = cur.fetchall()
        return [row_to_event(r) for r in rows]

    def save_events(self, slug: str, events: list[Event]) -> None:
        # Mirror FileStore's wholesale rewrite of events.yaml: replace the
        # athlete's entire event set atomically.
        with self._connect() as conn, conn.cursor() as cur:
            athlete_id = self._athlete_id(cur, slug)
            cur.execute("delete from events where athlete_id = %s", (athlete_id,))
            for event in events:
                row = event_to_row(event)
                cur.execute(
                    """
                    insert into events (id, athlete_id, event_date, schema_version, data)
                    values (%(id)s, %(athlete_id)s, %(event_date)s, %(schema_version)s, %(data)s)
                    """,
                    {**row, "data": self._Jsonb(row["data"])},
                )

    # --- Macro plan -----------------------------------------------------

    def load_macro(self, slug: str) -> MacroPlan | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                select m.data from macro_plans m
                join athletes a on a.athlete_id = m.athlete_id
                where a.slug = %s
                """,
                (slug,),
            )
            row = cur.fetchone()
        return row_to_macro(row) if row is not None else None

    def save_macro(self, slug: str, macro: MacroPlan) -> None:
        row = macro_to_row(macro)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                insert into macro_plans (athlete_id, id, event_id, schema_version, data)
                values (%(athlete_id)s, %(id)s, %(event_id)s, %(schema_version)s, %(data)s)
                on conflict (athlete_id) do update set
                    id = excluded.id,
                    event_id = excluded.event_id,
                    schema_version = excluded.schema_version,
                    data = excluded.data,
                    updated_at = now()
                """,
                {**row, "data": self._Jsonb(row["data"])},
            )

    # --- Week plans -----------------------------------------------------

    def load_week(self, slug: str, iso_week: str) -> WeekPlan | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                select w.data from week_plans w
                join athletes a on a.athlete_id = w.athlete_id
                where a.slug = %s and w.iso_week = %s
                """,
                (slug, iso_week),
            )
            row = cur.fetchone()
        return row_to_week(row) if row is not None else None

    def save_week(self, slug: str, week: WeekPlan) -> None:
        row = week_to_row(week)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                insert into week_plans (id, athlete_id, iso_week, schema_version, data)
                values (%(id)s, %(athlete_id)s, %(iso_week)s, %(schema_version)s, %(data)s)
                on conflict (athlete_id, iso_week) do update set
                    id = excluded.id,
                    schema_version = excluded.schema_version,
                    data = excluded.data,
                    updated_at = now()
                """,
                {**row, "data": self._Jsonb(row["data"])},
            )

    def list_week_ids(self, slug: str) -> list[str]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                select w.iso_week from week_plans w
                join athletes a on a.athlete_id = w.athlete_id
                where a.slug = %s
                order by w.iso_week
                """,
                (slug,),
            )
            rows = cur.fetchall()
        return [r["iso_week"] for r in rows]

    # --- Workouts -------------------------------------------------------

    def list_workouts(self, slug: str) -> list[Workout]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                select w.data from workouts w
                join athletes a on a.athlete_id = w.athlete_id
                where a.slug = %s
                order by w.date, w.sport, w.id
                """,
                (slug,),
            )
            rows = cur.fetchall()
        return [row_to_workout(r) for r in rows]

    def save_workout(self, slug: str, workout: Workout) -> None:
        # PK is the workout's own id -> re-saving the same id upserts (correct
        # a previously logged workout); a different id on the same date/sport
        # is a distinct row (double pool days).
        row = workout_to_row(workout)
        with self._connect() as conn, conn.cursor() as cur:
            athlete_id = self._athlete_id(cur, slug)
            row = {**row, "athlete_id": athlete_id, "data": self._Jsonb(row["data"])}
            cur.execute(
                """
                insert into workouts (id, athlete_id, date, sport, schema_version, data)
                values (%(id)s, %(athlete_id)s, %(date)s, %(sport)s, %(schema_version)s, %(data)s)
                on conflict (id) do update set
                    athlete_id = excluded.athlete_id,
                    date = excluded.date,
                    sport = excluded.sport,
                    schema_version = excluded.schema_version,
                    data = excluded.data,
                    updated_at = now()
                """,
                row,
            )

    # --- Wellness -------------------------------------------------------

    def list_wellness(self, slug: str) -> list[Wellness]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                select c.data from wellness_checkins c
                join athletes a on a.athlete_id = c.athlete_id
                where a.slug = %s
                order by c.date, c.id
                """,
                (slug,),
            )
            rows = cur.fetchall()
        return [row_to_wellness(r) for r in rows]

    def save_wellness(self, slug: str, wellness: Wellness) -> None:
        # One per (athlete, date): re-saving the same date overwrites (matches
        # FileStore's <date>.yaml single-file-per-day behavior).
        row = wellness_to_row(wellness)
        with self._connect() as conn, conn.cursor() as cur:
            athlete_id = self._athlete_id(cur, slug)
            row = {**row, "athlete_id": athlete_id, "data": self._Jsonb(row["data"])}
            cur.execute(
                """
                insert into wellness_checkins (id, athlete_id, date, schema_version, data)
                values (%(id)s, %(athlete_id)s, %(date)s, %(schema_version)s, %(data)s)
                on conflict (athlete_id, date) do update set
                    id = excluded.id,
                    schema_version = excluded.schema_version,
                    data = excluded.data,
                    updated_at = now()
                """,
                row,
            )

    # --- Feedback (durable, replaces research/open-questions.jsonl) -----

    def save_feedback(self, entry: Feedback) -> None:
        row = feedback_to_row(entry)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                insert into feedback (id, athlete_id, type, source, body, context, status, created_at)
                values (%(id)s, %(athlete_id)s, %(type)s, %(source)s, %(body)s, %(context)s, %(status)s, %(created_at)s)
                """,
                {**row, "context": self._Jsonb(row["context"])},
            )

    def list_feedback(
        self, *, athlete: str | None = None, limit: int | None = None
    ) -> list[Feedback]:
        with self._connect() as conn, conn.cursor() as cur:
            params: list[Any] = []
            query = "select * from feedback"
            if athlete is not None:
                athlete_id = self._athlete_id(cur, athlete)  # raises FileNotFoundError if unknown
                query += " where athlete_id = %s"
                params.append(athlete_id)
            query += " order by created_at desc"
            if limit is not None:
                query += " limit %s"
                params.append(limit)
            cur.execute(query, params)
            rows = cur.fetchall()
        return [row_to_feedback(r) for r in rows]

    def get_feedback(self, feedback_id: UUID) -> Feedback | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("select * from feedback where id = %s", [feedback_id])
            row = cur.fetchone()
        return row_to_feedback(row) if row is not None else None

    def update_feedback(
        self, feedback_id: UUID, *, status: str | None = None, context: dict | None = None
    ) -> Feedback | None:
        # `context = context || %(context)s` is Postgres jsonb's shallow-merge
        # operator -- new keys added, overlapping keys take the new value,
        # everything else in the existing context is preserved. Matches
        # StoreInterface.update_feedback's documented "merge, never clobber"
        # contract.
        sets = []
        params: dict[str, Any] = {"id": feedback_id}
        if status is not None:
            sets.append("status = %(status)s")
            params["status"] = status
        if context is not None:
            sets.append("context = coalesce(context, '{}'::jsonb) || %(context)s")
            params["context"] = self._Jsonb(context)
        with self._connect() as conn, conn.cursor() as cur:
            if sets:
                cur.execute(
                    f"update feedback set {', '.join(sets)} where id = %(id)s returning *",
                    params,
                )
            else:
                cur.execute("select * from feedback where id = %(id)s", params)
            row = cur.fetchone()
        return row_to_feedback(row) if row is not None else None

    # --- Coach texts (verbatim, saved BEFORE parsing) -------------------

    def coach_text_exists(self, slug: str, day: date) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                select 1 from coach_texts c
                join athletes a on a.athlete_id = c.athlete_id
                where a.slug = %s and c.day = %s
                """,
                (slug, day),
            )
            return cur.fetchone() is not None

    def save_coach_text(self, slug: str, day: date, text: str, *, force: bool = False) -> str:
        import uuid

        key = coach_text_storage_key(slug, day)
        with self._connect() as conn, conn.cursor() as cur:
            athlete_id = self._athlete_id(cur, slug)
            cur.execute(
                "select id from coach_texts where athlete_id = %s and day = %s",
                (athlete_id, day),
            )
            existing = cur.fetchone()
            if existing is not None and not force:
                raise FileExistsError(
                    f"coach text already exists for {slug} on {day.isoformat()}; "
                    "pass force=True to overwrite"
                )
            if existing is not None:
                cur.execute(
                    """
                    update coach_texts set body = %s, storage_key = %s, updated_at = now()
                    where id = %s
                    """,
                    (text, key, existing["id"]),
                )
            else:
                cur.execute(
                    """
                    insert into coach_texts (id, athlete_id, day, body, storage_key)
                    values (%s, %s, %s, %s, %s)
                    """,
                    (uuid.uuid4(), athlete_id, day, text, key),
                )
        return key

    # --- Verified identity (Slice 1: allowed_emails + auth_sessions) -----
    #
    # Both tables store only an `athlete_id` FK (see supabase/migrations/
    # 20260714000000_identity.sql) -- every read here joins back to
    # `athletes` to resolve the slug the rest of StoreInterface works in,
    # same join pattern `list_week_ids`/`list_workouts`/etc. already use.

    def add_allowed_email(
        self, email: str, *, athlete: str | None = None, note: str | None = None
    ) -> AllowedEmail:
        normalized = email.strip().lower()
        with self._connect() as conn, conn.cursor() as cur:
            athlete_id = self._athlete_id(cur, athlete) if athlete is not None else None
            cur.execute(
                """
                insert into allowed_emails (email, athlete_id, note)
                values (%s, %s, %s)
                on conflict (email) do update set
                    athlete_id = excluded.athlete_id,
                    note = excluded.note
                returning created_at
                """,
                (normalized, athlete_id, note),
            )
            row = cur.fetchone()
        return AllowedEmail(
            email=normalized, athlete_slug=athlete, note=note, created_at=row["created_at"]
        )

    def get_allowed_email(self, email: str) -> AllowedEmail | None:
        # LEFT JOIN -- a pending/onboarding invite (athlete_id IS NULL) must
        # still come back, not be silently dropped by an INNER JOIN.
        normalized = email.strip().lower()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                select ae.email, a.slug as athlete_slug, ae.note, ae.created_at
                from allowed_emails ae
                left join athletes a on a.athlete_id = ae.athlete_id
                where ae.email = %s
                """,
                (normalized,),
            )
            row = cur.fetchone()
        return row_to_allowed_email(row) if row is not None else None

    def list_allowed_emails(self) -> list[AllowedEmail]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                select ae.email, a.slug as athlete_slug, ae.note, ae.created_at
                from allowed_emails ae
                left join athletes a on a.athlete_id = ae.athlete_id
                order by ae.created_at, ae.email
                """
            )
            rows = cur.fetchall()
        return [row_to_allowed_email(r) for r in rows]

    def remove_allowed_email(self, email: str) -> bool:
        normalized = email.strip().lower()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "delete from allowed_emails where email = %s returning email", (normalized,)
            )
            row = cur.fetchone()
        return row is not None

    def create_session(
        self,
        token_hash: str,
        *,
        athlete: str | None = None,
        pending_email: str | None = None,
        expires_at: datetime,
    ) -> AuthSession:
        with self._connect() as conn, conn.cursor() as cur:
            athlete_id = self._athlete_id(cur, athlete) if athlete is not None else None
            cur.execute(
                """
                insert into auth_sessions (token_hash, athlete_id, pending_email, expires_at)
                values (%s, %s, %s, %s)
                returning created_at
                """,
                (token_hash, athlete_id, pending_email, expires_at),
            )
            row = cur.fetchone()
        return AuthSession(
            token_hash=token_hash,
            athlete_slug=athlete,
            pending_email=pending_email,
            created_at=row["created_at"],
            expires_at=expires_at,
            revoked_at=None,
        )

    def get_session(self, token_hash: str) -> AuthSession | None:
        # LEFT JOIN -- an onboarding session (athlete_id IS NULL) must still
        # resolve, not be silently dropped by an INNER JOIN.
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                select s.token_hash, a.slug as athlete_slug, s.pending_email,
                       s.created_at, s.expires_at, s.revoked_at
                from auth_sessions s
                left join athletes a on a.athlete_id = s.athlete_id
                where s.token_hash = %s
                """,
                (token_hash,),
            )
            row = cur.fetchone()
        return row_to_auth_session(row) if row is not None else None

    def revoke_session(self, token_hash: str) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "update auth_sessions set revoked_at = now() where token_hash = %s "
                "returning token_hash",
                (token_hash,),
            )
            row = cur.fetchone()
        return row is not None
