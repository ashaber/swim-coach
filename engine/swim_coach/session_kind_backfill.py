"""One-time classifier for sessions that predate `Session.kind` (used only by
`scripts/backfill_session_kind.py`; nothing at runtime reads purpose text for a kind).

The wording only NOMINATES a kind; context confirms it:
  race    -- "RACE -- ...", "RACE — ...", "RACE: ..." (NOT "race-week ...")
  opener  -- "OPENERS ...", "PRE-RACE PRIMER ..." and only if a race session of the same sport is
             on the NEXT day (else it stays an ordinary workout, e.g. a race-week sharpener)
  warmup  -- "WARM-UP ...", "RACE-DAY WARM-UP ..." and only if a race session of the same sport
             is on the SAME day
Sessions that already carry an explicit kind are never changed (explicit races still anchor)."""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Sequence
from uuid import UUID

from swim_coach.models import Session, SessionKind

_RACE = re.compile(r"^\s*RACE\b\s*(?:—|–|--|:)|^\s*RACE\s+-\s", re.IGNORECASE)
_OPENER = re.compile(r"^\s*(?:PRE-RACE PRIMER|OPENERS?)\b", re.IGNORECASE)
_WARMUP = re.compile(r"^\s*(?:RACE-DAY WARM-?UP|WARM-?UP)\b", re.IGNORECASE)


def wording_kind(*texts: str | None) -> SessionKind | None:
    """The kind the purpose (then title) wording nominates, before any context check."""
    for text in texts:
        if not text:
            continue
        for pattern, kind in ((_RACE, "race"), (_OPENER, "opener"), (_WARMUP, "warmup")):
            if pattern.match(text):
                return kind
    return None


def propose_kinds(sessions: Sequence[Session]) -> dict[UUID, SessionKind]:
    """`{session id: proposed kind}` for the untagged sessions of ONE athlete (pass every live
    week's sessions together so a race in the adjacent week is seen)."""
    wording = {s.id: wording_kind(s.purpose, s.title) for s in sessions if s.kind is None}
    races = {(s.date, s.sport) for s in sessions if s.kind == "race" or wording.get(s.id) == "race"}
    out: dict[UUID, SessionKind] = {}
    for s in sessions:
        nominated = wording.get(s.id)
        if nominated == "race":
            out[s.id] = "race"
        elif nominated == "opener" and (s.date + timedelta(days=1), s.sport) in races:
            out[s.id] = "opener"
        elif nominated == "warmup" and (s.date, s.sport) in races:
            out[s.id] = "warmup"
    return out
