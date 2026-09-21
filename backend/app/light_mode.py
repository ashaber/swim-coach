"""Light mode (IDEA 022 step 5): cheap conversational turns.

A full coach request carries ~24k tokens of tool schemas, a ~56k-token system
prompt (persona, INDEX, reference list), routed library files, and the whole
athlete context -- none of which "hey coach, finished my race today" needs.
A light turn sends a small standalone system prompt, ONE tool (`need_more`),
and a trimmed context (today, upcoming events, last 7 days of sessions).

Routing is deterministic and deliberately conservative (`is_light_turn`): any
topic keyword, health/pain word, data/analysis word or plan-action word sends
the turn to full mode. When routing guesses wrong the model itself calls
`need_more` and `ClaudeChat` re-runs the same question in full mode (see
`claude.ClaudeChat._run_turns`'s `escalate`).

Nothing here is used unless `Settings.light_mode` (COACH_LIGHT_MODE) is on.
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

from swim_coach.athlete_time import athlete_today

from app import context as context_module
from app.context import HistoryTurn, StoreInterface

NEED_MORE_TOOL_NAME = "need_more"

# Anything longer or deeper than this is more likely to be actionable.
LIGHT_MAX_MESSAGE_CHARS = 240
LIGHT_MAX_HISTORY_MESSAGES = 8
LIGHT_RECENT_SESSION_DAYS = 7

# Coach judgment: word lists tuned to send anything ambiguous to full mode --
# a wrong "full" costs tokens, a wrong "light" costs answer quality. The
# `need_more` escape hatch covers what these miss.
_HEALTH_WORDS = (
    "pain", "hurt", "hurts", "injur", "injury", "sore", "soreness", "ache", "aching", "sick", "ill",
    "illness", "dizzy", "dizziness", "chest", "faint", "fainted", "palpitation", "palpitations",
    "cramp", "cramps", "shiver", "shivering", "hypothermia", "heatstroke", "numb", "numbness",
    "swollen", "swelling", "sprain", "sprained", "strain", "strained", "fever", "nausea", "nauseous",
    "vomit", "breathe", "breathing", "doctor", "physio", "surgery", "concussion", "tweak", "tweaked",
    "niggle", "knee", "shoulder", "ankle", "medication", "medical",
)
_DATA_WORDS = (
    "review", "analyze", "analyse", "analysis", "pacing", "paced", "laps", "lap", "power", "watts",
    "hr", "heart", "data", "numbers", "compare", "compared", "why", "should", "recommend", "advice",
    "tss", "ctl", "atl", "tsb", "rpe", "score", "stats", "metrics", "efficiency", "fade", "faded",
    "how did", "how much", "how many", "how long", "what should", "what is", "what's", "when should",
)
_ACTION_WORDS = (
    "plan", "week", "schedule", "session", "workout", "move", "swap", "change", "adjust",
    "reschedule", "skip", "cancel", "log", "record", "add", "remove", "delete", "sync", "upload",
    "generate", "create", "update", "edit", "propose", "confirm", "athlete profile", "ftp",
)


def _word_pattern(words: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(re.escape(w) for w in words) + r")\b", re.IGNORECASE)


_HEALTH_RE = _word_pattern(_HEALTH_WORDS)
_DATA_RE = _word_pattern(_DATA_WORDS)
_ACTION_RE = _word_pattern(_ACTION_WORDS)


def is_light_turn(
    message: str,
    *,
    history_len: int,
    focused: bool = False,
    expert_mode: bool = False,
) -> bool:
    """True when `message` can be answered conversationally with no tools,
    library or full context. Conservative: see the module docstring."""
    if focused or expert_mode:
        return False
    if history_len > LIGHT_MAX_HISTORY_MESSAGES or len(message) > LIGHT_MAX_MESSAGE_CHARS:
        return False
    lowered = message.lower()
    if any(keyword in lowered for keyword in context_module._KEYWORD_ROUTES):
        return False
    return not (_HEALTH_RE.search(message) or _DATA_RE.search(message) or _ACTION_RE.search(message))


LIGHT_TOOLS: list[dict[str, Any]] = [
    {
        "name": NEED_MORE_TOOL_NAME,
        "description": (
            "Call this INSTEAD of answering whenever the athlete's message needs anything you "
            "don't have in this light mode: their plan, their training data or numbers, the "
            "research library, a plan change, logging something, advice, or ANY mention of "
            "pain, injury, illness or symptoms. It hands the same message to the full coach. "
            "Write no text before calling it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"reason": {"type": "string", "description": "One short phrase: what is needed."}},
            "required": ["reason"],
            "additionalProperties": False,
        },
    }
]

LIGHT_SYSTEM_PROMPT = f"""\
You are the swim-coach AI coach, in a light conversational mode.

The athlete is just talking -- greeting you, sharing how a session or race went, or thinking out
loud. Respond like a warm, attentive human coach would: brief, natural, and curious. When they
share something (a finished race, a hard week), reflect it back and ask one to three open
follow-up questions -- what went well, what was hard, how the body feels, how fueling went --
so the picture builds up over a few messages. Use the short athlete context below for names,
dates and what they recently did; never invent details it doesn't contain.

In this mode you have NO training plan, NO detailed data, NO research library and NO tools other
than `{NEED_MORE_TOOL_NAME}`. So do NOT give training advice, paces, numbers, fueling amounts,
plan changes, or medical guidance, and never claim to have looked at their data.

If the athlete asks for anything beyond conversation -- a review of the numbers, advice, a plan
question or change, logging something -- or mentions ANY pain, injury, illness or symptom
(however minor), call `{NEED_MORE_TOOL_NAME}` immediately with no text before it. If they
describe acute distress (chest pain, fainting, palpitations, confusion), call it at once.
"""


def build_light_system() -> list[dict[str, Any]]:
    """The small, byte-stable light system prompt (one cacheable block)."""
    return [{"type": "text", "text": LIGHT_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]


def build_light_context(store: StoreInterface, slug: str) -> str:
    """Trimmed per-request context: today, upcoming events, and the last
    `LIGHT_RECENT_SESSION_DAYS` days of sessions (each with its own sport).
    No plan, zones, load rollup, wellness or library."""
    athlete = store.load_athlete(slug)
    today = athlete_today(athlete)
    events = store.load_events(slug)
    workouts = store.list_workouts(slug)
    span_start = today - timedelta(days=LIGHT_RECENT_SESSION_DAYS)
    parts = [
        "## Light athlete context (short summary -- not the full plan or data)",
        f"Athlete: {athlete.name}",
        f"Today: {today.isoformat()}",
        "",
        "### Upcoming events",
        context_module._render_upcoming_events_pinned(events, today),
        "",
        f"### Sessions logged in the last {LIGHT_RECENT_SESSION_DAYS} days",
        context_module._render_recent_sessions(workouts, span_start, today),
    ]
    return "\n".join(parts)


def build_light_messages(
    store: StoreInterface,
    slug: str,
    *,
    message: str,
    history: list[HistoryTurn],
) -> list[dict[str, Any]]:
    """History verbatim, then the newest message with the light context merged
    in -- same shape and reasoning as `context.build_messages`."""
    messages: list[dict[str, Any]] = [{"role": t["role"], "content": t["content"]} for t in history]
    context_text = build_light_context(store, slug)
    messages.append({"role": "user", "content": f"{context_text}\n\n---\n\n{message}"})
    return messages
