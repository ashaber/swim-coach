"""Deterministic guard against a coach reply that claims a save nothing made.

Real incident, prod 2026-10-10 (athlete andrew, week 2026-W41): the coach
answered "Persisted and verified -- Option 2 is locked in" in a turn where it
made NO tool call, so nothing was saved. This module is advisory only: when the
final text of a turn claims a plan/profile write and no persisting write tool
succeeded in the same turn, the caller appends a visible warning line.

Conservative on purpose: a sentence only counts as a claim if it matches a
named claim phrase AND carries no negation/future/conditional/draft hedge.
"""

from __future__ import annotations

import re
from typing import Any

UNVERIFIED_SAVE_NOTICE = (
    "\n\n⚠️ Check: no change was saved in this reply. "
    "Nothing on your plan changed; ask me to save it."
)

# Tools whose success persists something, mapped to their success key. A
# `persisted: True` result always counts (draft-only results carry
# `persisted: False`); tools with another success shape name their key here.
WRITE_TOOLS: dict[str, str] = {
    "author_macro_plan": "persisted",
    "draft_macro_plan": "persisted",
    "draft_season_macro_plan": "persisted",
    "replace_macro_plan": "persisted",
    "author_week_plan": "persisted",
    "replace_week_plan": "persisted",
    "patch_week_plan": "persisted",
    "merge_week_plan": "persisted",
    "propose_adaptation": "persisted",
    "propose_session_adjustment": "persisted",
    "propose_injury_adapted_taper": "persisted",
    "set_event_active_status": "persisted",
    "set_pool_coach_status": "persisted",
    "set_weekly_template": "persisted",
    "reschedule_session": "persisted",
    "create_week_plan": "created",
    "create_event": "created",
    "update_athlete_profile": "updated",
    "record_threshold_test": "logged",
    "record_health_status": "logged",
    "save_athlete_note": "saved",
    "save_race_debrief": "saved",
    "retire_athlete_note": "retired",
}

_CLAIM = re.compile(
    r"\bpersisted\b|\bsaved\b|\blocked in\b|\bnow on your plan\b|\bwritten to\b"
    r"|\bupdated your (?:plan|profile|week|schedule)\b",
    re.IGNORECASE,
)
# "your saved notes", "already saved" etc. describe earlier state, not a write.
_NOT_A_WRITE = re.compile(
    r"\b(?:your|the|any|previously|already|earlier|those|these)\s+saved\b|\bsaved\s+(?:notes?|plans?|drafts?)\b",
    re.IGNORECASE,
)
_HEDGE = re.compile(
    r"\bnot\b|n't\b|n’t\b|\bnothing\b|\bnone\b|\bno change\b|\byet\b|\bdraft\b|\bonce\b|\bif\b"
    r"|\bwill\b|\bwould\b|\bcan\b|\bcould\b|\bshall\b|\bbefore\b|\buntil\b|\bunless\b"
    r"|\bconfirm\b|\bready to\b|\bwant me\b|\bshould i\b|\bto persist\b|\bto save\b|\bgoing to\b"
    r"|\bi'll\b|\bi’ll\b|\bpropos",
    re.IGNORECASE,
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def claims_a_save(text: str) -> bool:
    """True if some sentence of `text` asserts a write happened (unhedged)."""
    for sentence in _SENTENCE_SPLIT.split(text or ""):
        claims = _CLAIM.findall(sentence)
        if not claims:
            continue
        if len(_NOT_A_WRITE.findall(sentence)) >= len(claims):
            continue
        if _HEDGE.search(sentence):
            continue
        return True
    return False


def write_succeeded(tool: str, result: Any) -> bool:
    """True if `result` from `tool` is the success shape of a persisting write."""
    key = WRITE_TOOLS.get(tool)
    if key is None or not isinstance(result, dict) or "error" in result:
        return False
    if result.get("persisted") is True:
        return True
    if key == "updated":
        return bool(result.get("updated")) or bool(result.get("saved_as_notes"))
    return key != "persisted" and result.get(key) is True
