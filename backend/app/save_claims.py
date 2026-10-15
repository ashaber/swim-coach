"""Deterministic guard against a coach reply that claims a save nothing made.

Real incident, prod 2026-10-10 (athlete andrew, week 2026-W41): the coach
answered "Persisted and verified -- Option 2 is locked in" in a turn where it
made NO tool call, so nothing was saved. This module is advisory only: when the
final text of a turn claims a plan/profile write and no persisting write tool
succeeded in the same turn, the caller appends a visible warning line.

A sentence counts as a claim if it matches a named claim phrase (formal:
"persisted", "saved", "locked in"...; plain-language: "is set", "Done",
"now has", "I've moved...") AND carries no negation/future/conditional/draft
hedge. Past-tense "confirmed"/"verified" are assertions, not hedges.

Tradeoff, decided: false positives are accepted over misses. The appended
line says "in this reply", so a true recap of an earlier turn ("I've updated
the plan", "the week is set") merely gets a harmless reminder. Known accepted
false positives: "I've added a rationale below", "the alarm is set". Excluded
on purpose: "is set at/to <value>" (a value, e.g. "threshold is set at 278 W").
"""

from __future__ import annotations

import re
from typing import Any

UNVERIFIED_SAVE_NOTICE = (
    "\n\n⚠️ Check: no change was saved in this reply. "
    "Nothing on your plan changed; ask me to save it."
)

UNVERIFIED_DRAFT_NOTICE = (
    "\n\n⚠️ Check: no draft was made in this reply. "
    "Nothing was proposed to your plan."
)

# Tools whose success persists plan/profile data, mapped to the success key
# their handler returns (each verified against the handler's return in
# app/tools.py). A `persisted: True` result always counts (draft-only results
# carry `persisted: False`). `update_athlete_profile` also counts when it only
# saved notes.
WRITE_TOOLS: dict[str, str] = {
    "author_macro_plan": "persisted",
    "author_week_plan": "persisted",
    "patch_week_plan": "persisted",
    "merge_week_plan": "persisted",
    "propose_session_adjustment": "persisted",
    "propose_injury_adapted_taper": "persisted",
    "compute_fueling_plan": "persisted",
    "set_weekly_template": "persisted",
    "set_event_active_status": "updated",
    "set_pool_coach_status": "updated",
    "update_athlete_profile": "updated",
    "create_event": "created",
    "set_event_group": "updated",
    "record_threshold_test": "logged",
    "record_health_status": "logged",
    "save_athlete_note": "saved",
    "save_race_debrief": "saved",
    "retire_athlete_note": "retired",
    "reschedule_session": "rescheduled",
    "set_workout_kind": "updated",
    "set_race_week_checklist": "persisted",
    "update_race_checklist": "updated",
}

# Every other real tool: reads, drafts that never persist (propose_adaptation
# always returns persisted: false), or writes to workout analytics / feedback
# rather than the plan or profile. tests/api/test_write_tools_registry.py
# fails when a real tool is in neither set.
NON_PLAN_OR_READ_ONLY: frozenset[str] = frozenset({
    "propose_adaptation",
    "get_plan_summary",
    "get_week_plan",
    "flag_for_coach_review",
    "log_app_feedback",
    "lookup_reference",
    "get_race_debriefs",
    "get_event_groups",
    "get_race_checklist",
    "get_workouts",
    "reanalyze_workout",
    "get_ride_pacing",
    "set_workout_chat_muted",
    "pull_activity_stream",
    "sync_workouts",
    "push_to_garmin",
    "export_zwo_workout",
    "check_plan",
    "render_plan_table",
})

_CLAIM = re.compile(
    r"\bpersisted\b|\bsaved\b|\blocked in\b|\bnow on your plan\b|\bwritten to\b"
    r"|\bupdated your (?:plan|profile|week|schedule)\b"
    r"|\b(?:is|are)\s+(?:now\s+)?set\b(?!\s+(?:at|to|by)\b)"
    r"|^\W*done\b|[—–-]\s*done\b"
    r"|\bnow has\b"
    r"|\b(?:i'?ve|i’ve|i have)\s+(?:now\s+)?(?:added|moved|updated|changed|swapped|removed|replaced)\b"
    r"|\b(?:added|moved|swapped)\s+(?:it|that|them|this)?\s*to your (?:plan|week)\b",
    re.IGNORECASE,
)
# "your saved notes", "already saved" etc. describe earlier state, not a write.
_NOT_A_WRITE = re.compile(
    r"\b(?:your|the|any|previously|already|earlier|those|these)\s+saved\b|\bsaved\s+(?:notes?|plans?|drafts?)\b",
    re.IGNORECASE,
)
# Hedges only in future/imperative/negated form: "confirm" but not "confirmed",
# "nothing" only when it negates a write ("nothing saved"), not "nothing dropped".
_HEDGE = re.compile(
    r"\bnot\b|n't\b|n’t\b"
    r"|\bnothing\b[^.]{0,25}\b(?:persisted|saved|written|locked|changed|updated|set)\b"
    r"|\bnone\b|\bno change\b|\byet\b|\bdraft\b|\bonce\b|\bif\b|\bwhether\b"
    r"|\bwill\b|\bwould\b|\bcan\b|\bcould\b|\bshall\b|\bbefore\b|\buntil\b|\bunless\b"
    r"|\bconfirm\b|\bconfirming\b|\bready to\b|\bwant me\b|\bshould i\b|\bto persist\b|\bto save\b"
    r"|\bgoing to\b|\bi'll\b|\bi’ll\b|\bpropos|\?",
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


# Any tool that drafts or writes plan data. A turn that called none of these has
# no draft to claim (prod 2026-10-15: "Draft is clean, no planning warnings"
# with ZERO tool calls). `propose_adaptation` and `check_plan` draft/check
# without persisting, so they are not in WRITE_TOOLS.
DRAFT_TOOLS: frozenset[str] = frozenset(WRITE_TOOLS) | {"propose_adaptation", "check_plan"}

# Tight on purpose: only phrasings that assert a draft/check result exists.
_DRAFT_CLAIM = re.compile(
    r"\bdraft\s+(?:is|looks)\s+(?:clean|ready|good)\b"
    r"|\bno\s+planning\s+warnings?\b"
    r"|\b(?:i'?ve|i’ve|i have|i)\s+(?:now\s+)?drafted\b"
    r"|\b(?:confirm|say the word|say go)\b[^.]{0,30}\bi(?:'|’)ll\s+(?:persist|save|lock)\b",
    re.IGNORECASE,
)
_DRAFT_HEDGE = re.compile(r"\bnot\b|n't\b|n’t\b|\bif\b|\bwhether\b|\bonce\b|\?", re.IGNORECASE)


def claims_a_draft(text: str) -> bool:
    """True if some sentence of `text` asserts a plan draft/check result exists."""
    for sentence in _SENTENCE_SPLIT.split(text or ""):
        if _DRAFT_CLAIM.search(sentence) and not _DRAFT_HEDGE.search(sentence):
            return True
    return False


def write_succeeded(tool: str, result: Any) -> bool:
    """True if `result` from `tool` is the success shape of a persisting write."""
    key = WRITE_TOOLS.get(tool)
    if key is None or not isinstance(result, dict) or "error" in result:
        return False
    if result.get("persisted") is True:
        return True
    if tool == "update_athlete_profile" and result.get("saved_as_notes"):
        return True
    return key != "persisted" and result.get(key) is True
