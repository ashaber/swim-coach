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

from datetime import date
from typing import Any
from uuid import UUID

from swim_coach.models import (
    Athlete,
    Event,
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
