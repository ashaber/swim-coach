"""Resolves "today" for a given `Athlete` -- the athlete-aware counterpart
to a bare `date.today()`.

**Why this module exists.** Before it, the backend had NO per-athlete
timezone concept anywhere: `date.today()` (server/process local time -- UTC
on Cloud Run in production) was used as a blind stand-in for "the athlete's
today" across every plan-math call site that needed one. That is silently
wrong for any athlete not physically in UTC -- an evening workout logged in
the athlete's own local time can land on the wrong calendar day
server-side, and a taper/event runway computed from server-UTC "today" can
read a day short right at a UTC day boundary. Confirmed, concrete case:
feedback entry ed20cbfb-d5a5-4716-9afd-87fbbc7cc810 (`propose_injury_
adapted_taper`, athlete `renee`) -- `tests/api/test_tools.py`'s two
`propose_injury_adapted_taper` runway tests passed in America/Denver
(UTC-6) but failed in GitHub Actions (UTC) purely from this.

**Engine owns ALL plan math (CLAUDE.md's standing rule) -- what counts as
"today" for that math is part of that ownership too**, so this resolver
lives in `engine/swim_coach/`, not `backend/app/`, even though most of its
callers today are backend request handlers.

**Zero-behavior-change posture for every existing athlete.** `Athlete.
timezone` is optional (`None` default, see that field's own comment in
`models.py`) -- 100% of real athletes as of this module's introduction have
no timezone set. `athlete_today` falls back to plain `date.today()` (server
time, byte-for-byte the prior behavior) whenever `athlete.timezone` is
unset, so this is a strict, opt-in addition: nothing changes for any
athlete until a human explicitly sets `Athlete.timezone` on their profile.
This module never guesses/auto-detects a timezone -- see `models.py`'s
`Athlete.timezone` comment for why that's deliberate.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from swim_coach.models import Athlete


def athlete_today(athlete: Athlete) -> date:
    """The calendar date "today" is, from this athlete's own point of view.

    Uses `athlete.timezone` (an IANA zone name, validated by `Athlete`'s
    own `_validate_timezone` field_validator -- never re-validated here) via
    `zoneinfo.ZoneInfo` + `datetime.now(tz).date()` when set. Falls back to
    plain `date.today()` -- exactly the prior, pre-this-module behavior --
    when `athlete.timezone` is `None`, which is every existing athlete's
    profile today and will stay true for any athlete who never sets one.
    """
    if not athlete.timezone:
        return date.today()
    return datetime.now(ZoneInfo(athlete.timezone)).date()
