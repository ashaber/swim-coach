"""Tests for swim_coach.athlete_time: resolving "today" for a given
Athlete, honoring an optional per-athlete IANA timezone.

No LLM calls, no network access -- pure date/timezone arithmetic, same
convention as test_models.py/test_taper_search.py.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

from swim_coach.athlete_time import athlete_today
from swim_coach.models import Athlete

ATHLETE_ID = uuid.uuid4()


def make_athlete(**overrides):
    data = dict(
        id=ATHLETE_ID,
        slug="wife",
        name="Jane Doe",
        css_pace_s_per_100m=95.0,
        zones={"Z1": [105, 999]},
        constraints={},
        pool_schedule=["mon", "wed"],
    )
    data.update(overrides)
    return Athlete(**data)


def test_athlete_today_falls_back_to_server_today_when_timezone_unset():
    # The critical zero-regression guarantee: 100% of existing athletes have
    # no `timezone` set, so this must be byte-for-byte the prior behavior
    # (plain `date.today()`), not a new computation that happens to usually
    # agree with it.
    athlete = make_athlete()
    assert athlete.timezone is None
    assert athlete_today(athlete) == date.today()


def test_athlete_today_resolves_to_the_athletes_own_local_date(monkeypatch):
    # Synthetic case where UTC and the athlete's own zone genuinely disagree
    # on the calendar day: 02:00 UTC on 2026-01-15 is already "tomorrow" in
    # UTC but still 19:00 the PRIOR evening (2026-01-14) in America/Denver
    # (UTC-7 in January, no DST). This is exactly the real, confirmed bug
    # (feedback entry ed20cbfb-d5a5-4716-9afd-87fbbc7cc810): server-UTC
    # `date.today()` reads a day ahead of the athlete's own real evening.
    fixed_instant = datetime(2026, 1, 15, 2, 0, tzinfo=ZoneInfo("UTC"))

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_instant.replace(tzinfo=None)
            return fixed_instant.astimezone(tz)

    monkeypatch.setattr("swim_coach.athlete_time.datetime", _FixedDatetime)

    athlete = make_athlete(timezone="America/Denver")

    # Sanity check the synthetic scenario is real before trusting the
    # assertion below: UTC and Denver must actually disagree here.
    assert fixed_instant.date() == date(2026, 1, 15)
    assert fixed_instant.astimezone(ZoneInfo("America/Denver")).date() == date(2026, 1, 14)

    resolved = athlete_today(athlete)

    # The LOCAL (Denver) date, never UTC's.
    assert resolved == date(2026, 1, 14)
    assert resolved != fixed_instant.date()


def test_athlete_today_uses_server_today_for_an_athlete_in_a_zone_that_agrees_with_utc():
    # An athlete whose zone happens to be UTC itself is a trivial
    # (non-adversarial) case worth covering too: the resolved date must
    # still come from the timezone-aware path (not silently short-circuit
    # back to the unset-timezone branch), and for UTC it should agree with
    # server date.today() in a real (unmocked) CI runner, which also runs
    # in UTC.
    athlete = make_athlete(timezone="UTC")
    assert athlete_today(athlete) == datetime.now(ZoneInfo("UTC")).date()
