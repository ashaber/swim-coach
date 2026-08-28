"""Shared never-overwrite-existing-nonnull-with-null merge policy for
`Wellness` rows.

Two callers hit the same hazard and share this one function:
- `backend/app/sync.py`'s intervals.icu wellness ingest -- the endpoint can
  return `null` for a field on a day its wearable hasn't caught up yet
  (confirmed live: a wellness pull for the last 2-3 days can come back fully
  null while older days already have real data). A naive "always overwrite
  with whatever intervals.icu returns" would clobber a good existing value
  (an earlier sync, or a manual check-in) with a fresh null.
- `backend/app/routes/wellness.py`'s manual check-in route -- the check-in
  form always sends `resting_hr`/`hrv` as `null` unless the athlete
  explicitly types a value, which would otherwise silently erase
  sync-derived data the next time the athlete checks in for that day.

Rule: a non-`None` incoming value always wins; a `None` incoming value never
overwrites an existing non-`None` stored value.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

from swim_coach.models import Wellness


def merge_wellness(
    existing: Wellness | None,
    updates: dict,
    *,
    athlete_id: UUID,
    date: date,
    source: str | None = None,
) -> Wellness:
    base = (
        existing.model_dump()
        if existing is not None
        else {"id": uuid4(), "athlete_id": athlete_id, "date": date, "schema_version": 1}
    )
    for field, value in updates.items():
        if value is not None:
            base[field] = value
    if source is not None:
        base["source"] = source
    return Wellness.model_validate(base)
