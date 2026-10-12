"""One-time classifier for sessions that predate `Session.kind` (used only by
`scripts/backfill_session_kind.py`; nothing at runtime reads purpose text for a kind).

Proposes `race` for "RACE -- ...", "RACE — ...", "RACE: ..." (any dash/colon after the word; NOT
"race-week ..."), `warmup` for pre-race primers, openers and race-day warm-ups, and nothing
otherwise (an untagged session already reads as "workout")."""

from __future__ import annotations

import re

from swim_coach.models import SessionKind

_RACE = re.compile(r"^\s*RACE\b\s*(?:—|–|--|:)|^\s*RACE\s+-\s", re.IGNORECASE)
_WARMUP = re.compile(r"^\s*(?:PRE-RACE PRIMER|OPENERS?|RACE-DAY WARM-?UP|WARM-?UP)\b", re.IGNORECASE)


def propose_kind(*texts: str | None) -> SessionKind | None:
    """The proposed kind from a session's purpose (then title), or None to leave it untagged."""
    for text in texts:
        if not text:
            continue
        if _WARMUP.match(text):
            return "warmup"
        if _RACE.match(text):
            return "race"
    return None
