"""Intent vocabulary shared by light mode (app.light_mode) and the Haiku router (app.router_rules):
what counts as a write/plan action, a data/analysis request, or a short "yes/no" to the assistant's
last turn. One definition so the two routers cannot drift. (Health language lives in the engine:
swim_coach.health_vocab.)

Coach judgment: word lists are tuned to over-match -- every word here only ever sends a message to
the bigger model.
"""

from __future__ import annotations

import re

# --- write / plan actions ---------------------------------------------------------------------

WRITE_VERBS: tuple[str, ...] = (
    "create", "build", "make", "draft", "write", "author", "generate", "set up", "setup", "schedule",
    "reschedule", "move", "swap", "switch", "change", "adjust", "update", "edit", "modify", "add", "insert",
    "remove", "delete", "drop", "cancel", "skip", "replace", "shift", "bump", "extend", "shorten",
    "lengthen", "redo", "rebuild", "rework", "regenerate",
)
PLAN_OBJECTS: tuple[str, ...] = (
    "session", "sessions", "workout", "workouts", "plan", "plans", "week", "weeks", "ride", "rides", "swim",
    "swims", "run", "runs", "strength", "day", "days", "template", "schedule", "calendar", "block", "phase",
    "taper", "race", "event", "interval", "intervals", "set", "sets", "warmup", "warm-up", "cooldown",
    "cool-down",
)
# Light mode's net: every write verb plus the plan nouns an athlete uses when asking for a change.
# (Not "race"/"swim"/"ride": "finished my race today" is exactly the conversation light mode is for.)
ACTION_WORDS: tuple[str, ...] = tuple(
    dict.fromkeys(
        (*WRITE_VERBS, "plan", "plans", "week", "weeks", "schedule", "session", "sessions", "workout",
         "workouts", "log", "record", "sync", "upload", "propose", "confirm", "athlete profile", "ftp")
    )
)

# --- data / analysis requests -----------------------------------------------------------------

DATA_WORDS: tuple[str, ...] = (
    "review", "analyze", "analyse", "analysis", "pacing", "paced", "laps", "lap", "power", "watts", "hr",
    "heart", "data", "numbers", "compare", "compared", "why", "should", "recommend", "advice", "tss", "ctl",
    "atl", "tsb", "rpe", "score", "stats", "metrics", "efficiency", "fade", "faded", "how did", "how much",
    "how many", "how long", "what should", "what is", "what's", "when should",
)
# Large-analysis regexes (the router forces these to the big model).
ANALYSIS_PATTERNS: tuple[str, ...] = (
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

# --- short affirmations / declines ------------------------------------------------------------

AFFIRMATION_PHRASES: tuple[str, ...] = (
    "yes", "yeah", "yep", "yup", "ya", "ok", "okay", "k", "kk", "sure", "sure thing", "absolutely",
    "definitely", "do it", "go ahead", "go for it", "sounds good", "sounds great", "sounds perfect",
    "looks good", "looks great", "lgtm", "confirm", "confirmed", "approve", "approved", "please do",
    "let's do it", "lets do it", "let's go", "lets go", "that works", "works for me", "perfect", "great",
    "good", "fine", "agreed", "correct", "right", "exactly",
    "no", "nope", "nah", "don't", "dont", "do not", "cancel", "never mind", "nevermind", "not that",
    "not now", "hold off", "wait", "stop", "actually",
)
# "good" opens plenty of greetings; these are not answers to a proposal.
NOT_AFFIRMATION_PREFIXES: tuple[str, ...] = ("good morning", "good afternoon", "good evening", "good night", "good day")
AFFIRMATION_MAX_WORDS = 10

_phrase_alt = "|".join(re.escape(p) for p in sorted(AFFIRMATION_PHRASES, key=len, reverse=True))
_not_alt = "|".join(re.escape(p) for p in NOT_AFFIRMATION_PREFIXES)
AFFIRMATION_RE = re.compile(rf"^\W*(?!(?:{_not_alt})\b)(?:{_phrase_alt})\b", re.IGNORECASE)


def is_short_affirmation(message: str) -> bool:
    """A short reply that opens with an affirmation/decline phrase ("yes, go ahead", "no leave it")."""
    return len(message.split()) <= AFFIRMATION_MAX_WORDS and bool(AFFIRMATION_RE.search(message))


def word_pattern(words: tuple[str, ...]) -> re.Pattern[str]:
    """`\\b(?:w1|w2|...)\\b`, case-insensitive."""
    return re.compile(r"\b(?:" + "|".join(re.escape(w) for w in words) + r")\b", re.IGNORECASE)
