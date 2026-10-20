"""Deterministic pre-rules for the Haiku coach router.

A pre-rule hit FORCES Sonnet and skips the Haiku call entirely (even in shadow mode); the hit is
logged by category and rule id. Pure and engine-free: the rules are DATA (`PRE_RULES`, a table of
patterns tagged with a category), evaluated in order, first hit wins.

Design lessons from IDEAS.md IDEA 022 "PR #215 review conclusions" (light mode, app/light_mode.py):
  * Confirmations ("yes, go ahead", "ok do it", "sounds good, thanks") must never be answered by the
    cheap model: it has no write tools and would claim "Done!". Every short affirmation/decline that
    follows an assistant turn goes to Sonnet, whether or not that turn visibly proposed something
    (a conservative superset of "a prior assistant turn proposed an action"), and any message at all
    goes to Sonnet while a plan draft is pending.
  * Health detection was a keyword list with holes ("blacked out", "coming down with something",
    "headache", "scratchy throat" all went light). The list here is broad on purpose and also
    covers body regions, illness and medication words. Repo safety rail: any pain report ->
    stop-and-assess -> Sonnet. A wrong "Sonnet" costs tokens; a wrong "Haiku" on a symptom is the
    failure that matters.
  * An ACTIVE health status already on file (read from the athlete context) forces Sonnet for every
    message, because every training question is then also a health-aware question.

Coach judgment: patterns are tuned to over-match. This module only ever sends MORE traffic to
Sonnet; it can never route anything to Haiku.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from swim_coach.health_vocab import health_group_matches

from app.intent_vocab import (
    AFFIRMATION_MAX_WORDS,
    AFFIRMATION_RE,
    ANALYSIS_PATTERNS,
    PLAN_OBJECTS,
    WRITE_VERBS,
)

CATEGORY_CONFIRMATION = "pending_confirmation"
CATEGORY_HEALTH = "health_safety"
CATEGORY_WRITE_INTENT = "write_intent"
CATEGORY_LARGE_ANALYSIS = "large_analysis"



@dataclass(frozen=True)
class PreRule:
    """One row of the table. `needs_history`: only applies when an assistant turn precedes."""

    id: str
    category: str
    pattern: re.Pattern[str] | None = None  # a regex row...
    health_group: str | None = None  # ...or a swim_coach.health_vocab term group
    needs_history: bool = False
    max_words: int | None = None


@dataclass(frozen=True)
class PreRuleHit:
    """What fired. Deliberately carries no message text (never logged)."""

    category: str
    rule_id: str


PRE_RULES: tuple[PreRule, ...] = (
    # health first: safety outranks every other category. Terms live in swim_coach.health_vocab;
    # each row names the term group it checks (the "sport" group is the athlete's own sports).
    PreRule("health_pain_words", CATEGORY_HEALTH, health_group="pain"),
    PreRule("health_body_region", CATEGORY_HEALTH, health_group="anatomy"),
    PreRule("health_illness_words", CATEGORY_HEALTH, health_group="illness"),
    PreRule("health_acute_words", CATEGORY_HEALTH, health_group="acute"),
    PreRule("health_medical_words", CATEGORY_HEALTH, health_group="medical"),
    PreRule("health_sport_terms", CATEGORY_HEALTH, health_group="sport"),
    PreRule(
        "affirmation_after_assistant",
        CATEGORY_CONFIRMATION,
        AFFIRMATION_RE,
        needs_history=True,
        max_words=AFFIRMATION_MAX_WORDS,
    ),
    PreRule(
        "write_verb_plan_object",
        CATEGORY_WRITE_INTENT,
        re.compile(
            r"\b(?:" + "|".join(re.escape(v) for v in WRITE_VERBS) + r")\b[^.?!\n]{0,60}\b(?:"
            + "|".join(re.escape(o) for o in PLAN_OBJECTS) + r")\b",
            re.IGNORECASE,
        ),
    ),
    PreRule(
        "write_push_to_device",
        CATEGORY_WRITE_INTENT,
        re.compile(
            r"\bpush(?:ed|ing)?\b[^.?!\n]{0,40}\b(?:garmin|watch|intervals|zwift|device|calendar|it|this|that)\b",
            re.IGNORECASE,
        ),
    ),
    PreRule(
        "write_save_or_log",
        CATEGORY_WRITE_INTENT,
        re.compile(
            r"\b(?:save|log|record|store|remember|note down)\b[^.?!\n]{0,40}\b(?:this|that|it|my|today|"
            r"the|a|note|swim|ride|run|workout|session|test|result)\b",
            re.IGNORECASE,
        ),
    ),
    PreRule(
        "write_update_profile_value",
        CATEGORY_WRITE_INTENT,
        re.compile(
            r"\b(?:update|set|change|correct)\b[^.?!\n]{0,30}\b(?:ftp|css|lthr|threshold|profile|weight|zones?|timezone)\b",
            re.IGNORECASE,
        ),
    ),
    PreRule("analysis_phrases", CATEGORY_LARGE_ANALYSIS, re.compile("|".join(ANALYSIS_PATTERNS), re.IGNORECASE)),
)


def _words(text: str) -> int:
    return len(text.split())


def match_pre_rule(
    message: str,
    *,
    history: Sequence[dict[str, Any]],
    has_pending_draft: bool,
    has_active_health_status: bool,
    sports: Iterable[str] | None = None,
) -> PreRuleHit | None:
    """The first rule that fires for this turn, or None (then Haiku may triage it).

    `history` is the conversation before `message` (any non-empty history means an assistant turn
    exists, since turns alternate). `sports` (the athlete's effective sports) selects the
    sport-specific health terms. The two flags come from the athlete context the request already
    built (see app.router_shadow.context_flags)."""
    if has_pending_draft:
        return PreRuleHit(CATEGORY_CONFIRMATION, "pending_draft")
    if has_active_health_status:
        return PreRuleHit(CATEGORY_HEALTH, "active_health_status")
    words = _words(message)
    groups = health_group_matches(message, sports)
    for rule in PRE_RULES:
        if rule.needs_history and not history:
            continue
        if rule.max_words is not None and words > rule.max_words:
            continue
        if rule.health_group is not None:
            matched = groups.get(rule.health_group, False)
        else:
            matched = rule.pattern is not None and bool(rule.pattern.search(message))
        if matched:
            return PreRuleHit(rule.category, rule.id)
    return None
