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
from dataclasses import dataclass
from typing import Any, Sequence

CATEGORY_CONFIRMATION = "pending_confirmation"
CATEGORY_HEALTH = "health_safety"
CATEGORY_WRITE_INTENT = "write_intent"
CATEGORY_LARGE_ANALYSIS = "large_analysis"

# A short reply this long (in words) or shorter that STARTS with an affirmation/decline phrase is
# treated as answering the assistant's last turn.
AFFIRMATION_MAX_WORDS = 10


@dataclass(frozen=True)
class PreRule:
    """One row of the table. `needs_history`: only applies when an assistant turn precedes."""

    id: str
    category: str
    pattern: re.Pattern[str]
    needs_history: bool = False
    max_words: int | None = None


@dataclass(frozen=True)
class PreRuleHit:
    """What fired. Deliberately carries no message text (never logged)."""

    category: str
    rule_id: str


def _rx(*alternatives: str) -> re.Pattern[str]:
    return re.compile("|".join(alternatives), re.IGNORECASE)


# --- health and safety ------------------------------------------------------------------------
# Word stems are matched with a leading \b only where a suffix is expected (injur -> injury/injured).
_PAIN_WORDS = (
    r"\b(?:pain|painful|hurt|hurts|hurting|ache|aches|aching|sore|soreness|tender|twinge|twinges|"
    r"niggle|niggles|tweak|tweaked|pulled|strain|strained|sprain|sprained|swollen|swelling|bruis\w*|"
    r"inflam\w*|tendin\w*|tendon|fractur\w*|cramp\w*|stiff|numb\w*|tingl\w*|burning)\b|\binjur\w*"
)
_BODY_REGIONS = (
    r"\b(?:knee|knees|shoulder|shoulders|hip|hips|neck|elbow|wrist|ankle|foot|feet|heel|calf|calves|"
    r"hamstring|quad|quads|achilles|groin|shin|shins|glute|lower back|upper back|back pain|rotator|"
    r"lat|lats|rib|ribs|spine|tendonitis)\b"
)
_ILLNESS = (
    r"\b(?:sick|ill|illness|flu|covid|fever|feverish|cough\w*|sniffl\w*|congest\w*|sore throat|"
    r"scratchy throat|headache|migraine|nausea|nauseous|vomit\w*|diarrh\w*|infection|infected|rash|"
    r"virus|viral|bug|stomach bug|food poisoning|dehydrat\w*|hypotherm\w*|heatstroke|heat stroke|"
    r"cold and|a cold|head cold|chest cold)\b"
    r"|\bcoming down with\b|\bunder the weather\b|\bfeel(?:ing)? (?:off|unwell|rough|awful|terrible|weird|faint)\b"
)
_ACUTE = (
    r"\b(?:dizzy|dizziness|light-?headed|faint\w*|black(?:ed|ing)? out|passed out|palpitation\w*|"
    r"short(?:ness)? of breath|can'?t breathe|breathless|chest|heart racing|racing heart|irregular heartbeat|"
    r"confus\w*|disorient\w*|concussion|seiz\w*|bleed\w*|blood)\b"
)
_MEDICAL = (
    r"\b(?:doctor|physio|physiotherapist|gp|surgeon|surgery|medical|medication|meds|antibiotic\w*|"
    r"prescri\w*|diagnos\w*|mri|x-?ray|scan|symptom\w*|asthma|inhaler)\b"
)

# --- explicit write / plan intent -------------------------------------------------------------
_WRITE_VERBS = (
    r"create|build|make|draft|write|author|generate|set up|setup|schedule|reschedule|move|swap|switch|"
    r"change|adjust|update|edit|modify|add|insert|remove|delete|drop|cancel|skip|replace|shift|bump|"
    r"extend|shorten|lengthen|redo|rebuild|rework|regenerate"
)
_PLAN_OBJECTS = (
    r"sessions?|workouts?|plan|plans|week|weeks|rides?|swims?|runs?|strength|day|days|template|"
    r"schedule|calendar|block|phase|taper|race|event|intervals?|set|sets|warm-?up|cool-?down"
)

# --- large analysis ---------------------------------------------------------------------------
_ANALYSIS = (
    r"\bwhy did i (?:fade|faded|slow|slowed|die|bonk|blow|crack|fall off|lose)\b",
    r"\bwhy (?:did|was|were) (?:my|the) (?:\w+ ){0,3}(?:fade|faded|slow|slower|worse|drop|dropped|pacing)\b",
    r"\brace (?:analysis|analyses|debrief|review|report|recap|post-?mortem)\b",
    r"\b(?:debrief|post-?race|post-?mortem)\b",
    r"\banaly[sz]e (?:my|the|this|that|our)\b",
    r"\bhow did (?:my|the) (?:race|ride|event|swim|season|build|block)\b",
    r"\bseason (?:plan|planning|macro|outline|structure)\b",
    r"\bplan (?:my|the|a|this) season\b",
    r"\bmacro(?:cycle| ?plan| ?planning)?\b",
    r"\bperiodi[sz]ation\b",
    r"\b(?:structure|plan|design|build) (?:the|my|a) taper\b",
    r"\b(?:pacing|lap|power|split) (?:analysis|breakdown|comparison)\b",
    r"\blap[- ]by[- ]lap\b",
    r"\bcompare (?:my|the|this|these) (?:race|races|laps|rides|seasons?|blocks?)\b",
)

_AFFIRMATIONS = (
    r"^\W*(?:yes|yeah|yep|yup|ya|ok|okay|k|kk|sure|sure thing|absolutely|definitely|do it|go ahead|"
    r"go for it|sounds good|sounds great|sounds perfect|looks good|looks great|lgtm|confirm|confirmed|"
    r"approve|approved|please do|let'?s do it|let'?s go|that works|works for me|perfect|great|good(?! (?:morning|afternoon|evening|night|day))|"
    r"fine|agreed|correct|right|exactly|no|nope|nah|don'?t|do not|cancel|never ?mind|not that|"
    r"not now|hold off|wait|stop|actually)\b"
)

PRE_RULES: tuple[PreRule, ...] = (
    # health first: safety outranks every other category
    PreRule("health_pain_words", CATEGORY_HEALTH, _rx(_PAIN_WORDS)),
    PreRule("health_body_region", CATEGORY_HEALTH, _rx(_BODY_REGIONS)),
    PreRule("health_illness_words", CATEGORY_HEALTH, _rx(_ILLNESS)),
    PreRule("health_acute_words", CATEGORY_HEALTH, _rx(_ACUTE)),
    PreRule("health_medical_words", CATEGORY_HEALTH, _rx(_MEDICAL)),
    PreRule(
        "affirmation_after_assistant",
        CATEGORY_CONFIRMATION,
        _rx(_AFFIRMATIONS),
        needs_history=True,
        max_words=AFFIRMATION_MAX_WORDS,
    ),
    PreRule(
        "write_verb_plan_object",
        CATEGORY_WRITE_INTENT,
        _rx(rf"\b(?:{_WRITE_VERBS})\b[^.?!\n]{{0,60}}\b(?:{_PLAN_OBJECTS})\b"),
    ),
    PreRule(
        "write_push_to_device",
        CATEGORY_WRITE_INTENT,
        _rx(r"\bpush(?:ed|ing)?\b[^.?!\n]{0,40}\b(?:garmin|watch|intervals|zwift|device|calendar|it|this|that)\b"),
    ),
    PreRule(
        "write_save_or_log",
        CATEGORY_WRITE_INTENT,
        _rx(
            r"\b(?:save|log|record|store|remember|note down)\b[^.?!\n]{0,40}\b(?:this|that|it|my|today|"
            r"the|a|note|swim|ride|run|workout|session|test|result)\b",
        ),
    ),
    PreRule(
        "write_update_profile_value",
        CATEGORY_WRITE_INTENT,
        _rx(r"\b(?:update|set|change|correct)\b[^.?!\n]{0,30}\b(?:ftp|css|lthr|threshold|profile|weight|zones?|timezone)\b"),
    ),
    PreRule("analysis_phrases", CATEGORY_LARGE_ANALYSIS, _rx(*_ANALYSIS)),
)


def _words(text: str) -> int:
    return len(text.split())


def match_pre_rule(
    message: str,
    *,
    history: Sequence[dict[str, Any]],
    has_pending_draft: bool,
    has_active_health_status: bool,
) -> PreRuleHit | None:
    """The first rule that fires for this turn, or None (then Haiku may triage it).

    `history` is the conversation before `message` (any non-empty history means an assistant turn
    exists, since turns alternate). The two flags come from the athlete context the request already
    built (see app.router_shadow.context_flags)."""
    if has_pending_draft:
        return PreRuleHit(CATEGORY_CONFIRMATION, "pending_draft")
    if has_active_health_status:
        return PreRuleHit(CATEGORY_HEALTH, "active_health_status")
    words = _words(message)
    for rule in PRE_RULES:
        if rule.needs_history and not history:
            continue
        if rule.max_words is not None and words > rule.max_words:
            continue
        if rule.pattern.search(message):
            return PreRuleHit(rule.category, rule.id)
    return None
