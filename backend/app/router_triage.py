"""Haiku triage for the coach router: what Haiku sees, what it may call, and what it decides.

Pure of any HTTP framework. `run_triage` takes an injectable client (anything with
`messages.create` / `messages.count_tokens`) so tests never touch the network.

Hard constraints this module enforces (Anthropic pricing, verified 2026-10-20):
  * claude-haiku-5-5 costs $0.10/MTok input, $0.50/MTok output, cache reads $0.01, 5m cache writes
    $0.125, 1h cache writes $0.20 for a request whose prompt is <= 100,000 tokens. ABOVE 100,000
    prompt tokens (cache reads and writes count) every Haiku price is 5x, and each request is priced
    on its own. So every Haiku request must stay under the step: `TARGET_TOKENS` is the trim target
    and `CEILING_TOKENS` the hard limit past which the call is skipped (`over_budget`).
  * Each tool-loop iteration re-sends the whole prompt, so the budget is re-measured (free
    `count_tokens`) before EVERY call and the loop is capped at `HAIKU_MAX_ITERATIONS`.
  * Haiku gets an explicit allowlist of read-only tools plus the `triage` output tool. Nothing that
    writes, pushes, saves or drafts.

The decision object (`TriageDecision`) is what the later enable PR and the PWA gauge consume:
`route`, `complexity` (0-1, 0.5 = the Sonnet threshold mark), `confidence`, `category`, `reason`,
`reply`; `would_answer(threshold)` is the single predicate on-mode will use.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import anthropic
import httpx

from app.claude import with_loop_breakpoint
from app.logging_config import get_logger
from app.model_prices import split_cache_writes, usage_cost
from app.tool_errors import internal_tool_error
from app.tools import TOOLS_SCHEMA, ToolHandler

log = get_logger(__name__)

TRIAGE_TOOL_NAME = "triage"

# Read-only coach tools Haiku may call, verified one by one against their handlers in app/tools.py
# (none writes; each is also absent from save_claims.WRITE_TOOLS/DRAFT_TOOLS). Chosen conservatively:
#   get_plan_summary / get_week_plan  -- plan reads
#   get_workouts / get_ride_pacing    -- logged-workout reads (pacing is computed on demand, persisted nowhere)
#   get_race_debriefs / get_race_checklist / get_event_groups -- race reads
#   lookup_reference                  -- library reference-list lookup (the library topic files themselves
#                                        already ride the prompt; there is no separate read-file tool)
# Deliberately NOT here: reanalyze_workout and pull_activity_stream (write workout analytics/series),
# sync_workouts, push_to_garmin, export_zwo_workout (side effects), check_plan, render_plan_table,
# propose_adaptation (draft/analysis tools), flag_for_coach_review, log_app_feedback (write feedback).
HAIKU_TOOL_ALLOWLIST: tuple[str, ...] = (
    "get_plan_summary",
    "get_week_plan",
    "get_workouts",
    "get_ride_pacing",
    "get_race_debriefs",
    "get_race_checklist",
    "get_event_groups",
    "lookup_reference",
)

TRIAGE_CATEGORIES: tuple[str, ...] = (
    "greeting/thanks",
    "plan lookup",
    "workout question",
    "general training question",
    "health",
    "planning",
    "race analysis",
    "research",
    "other",
)

HAIKU_MAX_ITERATIONS = 3
# Output cap per Haiku call: adaptive thinking + the tool call (which carries the reply). Far above
# a normal triage; a runaway is bounded and costs $0.50/MTok.
HAIKU_MAX_OUTPUT_TOKENS = 6000

# Token budget (see module docstring). Coach judgment: the target leaves ~20k of headroom under the
# price step for tool results and the reply; the ceiling leaves ~5k for count_tokens drift.
TARGET_TOKENS = 78_000
CEILING_TOKENS = 95_000
PRICE_STEP_TOKENS = 100_000
# Session-history windows (days) the athlete context is re-rendered with, in order, when trimming
# "the oldest workout detail" (the default context carries 28 days).
SESSION_DAYS_LADDER: tuple[int, ...] = (14, 7)

ESTIMATE_CHARS_PER_TOKEN = 3.5  # conservative fallback when count_tokens is unavailable

HAIKU_INSTRUCTIONS = f"""\
## ROUTER MODE -- these instructions override the persona and tool rules above

You are the cheap first-line triage for this coach. Your job is to decide whether you can answer
the athlete's latest message yourself, or whether it must go to the full coach (a larger model with
write tools). You finish EVERY turn by calling the `{TRIAGE_TOOL_NAME}` tool exactly once.

You can only READ: the athlete context and library above, plus the read-only tools you were given.
You CANNOT save, change, log, push, draft or schedule anything, and the persona's rules about calling
write tools (record_health_status, author_week_plan, ...) do not apply to you.

route = "answer" ONLY when ALL are true: you are confident; the answer needs nothing beyond the
context above and your read-only tools; nothing about the plan or profile would change; there is no
health concern. Then put the full reply for the athlete in `reply`, in the coach's voice, concise,
using only facts from the context or tool results (never invent numbers, dates or sessions).

route = "escalate" for: anything that would create, change, move, swap, save, log or push a plan or
profile item; any pain, injury, illness, symptom or other health concern (however minor); deep or
multi-step analysis (race debriefs, why-did-I-fade, season or macro planning); advice you are not
sure of; a short "yes/ok/do it" reply to a proposal; anything where you are uncertain. When you
escalate, `reply` is not needed. Never claim to have saved, changed, logged or pushed anything.

Also set: `complexity` 0-1 (0 = trivial lookup or greeting, 0.5 = the line above which the full
coach is warranted, 1 = deep multi-step analysis); `confidence` 0-1 in your route decision;
`category`; and a short `reason` (one phrase, no personal details).
"""

TRIAGE_TOOL: dict[str, Any] = {
    "name": TRIAGE_TOOL_NAME,
    "description": (
        "Your required final output for this turn: decide whether you answer the athlete yourself "
        "(route=answer, with the full reply) or hand the message to the full coach (route=escalate)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "route": {"type": "string", "enum": ["answer", "escalate"]},
            "complexity": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "0 trivial .. 1 deep analysis; 0.5 is the threshold above which the full coach is warranted.",
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1, "description": "Confidence in this route decision."},
            "category": {"type": "string", "enum": list(TRIAGE_CATEGORIES)},
            "reason": {"type": "string", "description": "One short phrase. No personal or health details."},
            "reply": {"type": "string", "description": "The full reply for the athlete. Required when route=answer."},
        },
        "required": ["route", "complexity", "confidence", "category", "reason"],
        "additionalProperties": False,
    },
}


def build_haiku_tools() -> list[dict[str, Any]]:
    """The allowlisted read-only tool schemas (copied from TOOLS_SCHEMA, so they never drift from the
    handlers) followed by the `triage` output tool. Order is fixed: it is part of the cached prefix."""
    by_name = {t["name"]: t for t in TOOLS_SCHEMA}
    return [by_name[name] for name in HAIKU_TOOL_ALLOWLIST] + [TRIAGE_TOOL]


# --- decision ----------------------------------------------------------------------------------


def _unit_interval(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, max(0.0, number))


@dataclass(frozen=True)
class TriageDecision:
    """Haiku's parsed, validated routing decision. `invalid` marks a malformed tool call that was
    coerced to escalate (an `answer` with no reply, an unknown route)."""

    route: str  # "answer" | "escalate"
    complexity: float
    confidence: float
    category: str
    reason: str
    reply: str | None
    invalid: bool = False

    @classmethod
    def from_tool_input(cls, data: dict[str, Any]) -> "TriageDecision":
        route = data.get("route")
        category = data.get("category")
        reply = data.get("reply")
        reply = reply.strip() if isinstance(reply, str) and reply.strip() else None
        invalid = False
        if route not in ("answer", "escalate"):
            route, invalid = "escalate", True
        elif route == "answer" and reply is None:
            route, invalid = "escalate", True
        return cls(
            route=route,
            complexity=_unit_interval(data.get("complexity")),
            confidence=_unit_interval(data.get("confidence")),
            category=category if category in TRIAGE_CATEGORIES else "other",
            reason=str(data.get("reason") or "")[:200],
            reply=reply if route == "answer" else None,
            invalid=invalid,
        )

    def would_answer(self, confidence_threshold: float, complexity_threshold: float = 0.5) -> bool:
        """The enable-time predicate: Haiku's answer would be shown. The later PR/gauge use this."""
        return (
            self.route == "answer"
            and not self.invalid
            and self.confidence >= confidence_threshold
            and self.complexity < complexity_threshold
        )


# --- cost --------------------------------------------------------------------------------------


def estimate_cost_usd(
    *, input_tokens: int, cache_read: int, cache_write_5m: int, cache_write_1h: int, output: int,
    model: str = "claude-haiku-5-5",
) -> float:
    """USD for ONE request (prices live in app.model_prices; Haiku's 5x step above 100k is there)."""
    cost = usage_cost(
        model, input_tokens=input_tokens, cache_read=cache_read, cache_write_5m=cache_write_5m,
        cache_write_1h=cache_write_1h, output=output,
    )["est_cost_usd"]
    return float(cost or 0.0)


def _usage_cost(usage: Any, model: str, default_write_ttl: str) -> tuple[int, int, int, float]:
    """(prompt_tokens, cache_read, output, cost_usd) for one response's usage."""
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
    output = int(getattr(usage, "output_tokens", 0) or 0)
    write_5m, write_1h = split_cache_writes(usage, default_write_ttl)
    cost = estimate_cost_usd(
        input_tokens=input_tokens, cache_read=cache_read, cache_write_5m=write_5m, cache_write_1h=write_1h,
        output=output, model=model,
    )
    return input_tokens + cache_read + write_5m + write_1h, cache_read, output, cost


# --- Haiku's context ---------------------------------------------------------------------------


@dataclass
class HaikuContext:
    """The Haiku variant of a chat request, built from the SAME pieces the Sonnet request uses:
    block A (persona/conventions/INDEX), block C (athlete context), block B (routed library topic
    files), the conversation history and the newest question -- plus Haiku's own instructions after
    them. Same cache_control breakpoints and TTLs, so Haiku's prefix caches too.

    `trim()` shrinks it in a fixed order, only as far as asked: (1) the routed library topic files,
    (2) the oldest history turns, (3) the oldest workout detail (block C re-rendered with a shorter
    recent-sessions window via `rebuild_block_c(days)`)."""

    block_a: list[dict[str, Any]]
    block_c: list[dict[str, Any]]
    block_b: list[dict[str, Any]]
    history: list[dict[str, Any]]
    question: str
    cache_ttl: str
    rebuild_block_c: Callable[[int], list[dict[str, Any]]] | None = None
    # mutable trim state
    routed_included: bool = True
    history_dropped: int = 0
    session_step: int = 0
    extra_messages: list[dict[str, Any]] = field(default_factory=list)

    def system(self) -> list[dict[str, Any]]:
        blocks = [*self.block_a, *self.block_c]
        if self.routed_included:
            blocks += self.block_b
        return [*blocks, {"type": "text", "text": HAIKU_INSTRUCTIONS}]

    def messages(self) -> list[dict[str, Any]]:
        return [
            *self.history[self.history_dropped :],
            {"role": "user", "content": self.question},
            *self.extra_messages,
        ]

    def _drop_history(self, excess_chars: float) -> str | None:
        remaining = self.history[self.history_dropped :]
        if not remaining:
            return None
        dropped_chars = 0
        count = 0
        while count < len(remaining) and (count == 0 or dropped_chars < excess_chars):
            dropped_chars += len(json.dumps(remaining[count]["content"], default=str))
            count += 1
        # Whole user+assistant pairs only: what is left must still start with a user turn.
        while count < len(remaining) and remaining[count]["role"] != "user":
            count += 1
        self.history_dropped += count
        return f"history:{count}"

    def trim(self, excess_chars: float) -> str | None:
        """Apply the NEXT trim step; returns its label, or None when nothing is left to trim."""
        if self.routed_included and self.block_b:
            self.routed_included = False
            return "routed_library"
        label = self._drop_history(excess_chars)
        if label is not None:
            return label
        if self.rebuild_block_c is not None and self.session_step < len(SESSION_DAYS_LADDER):
            days = SESSION_DAYS_LADDER[self.session_step]
            self.session_step += 1
            self.block_c = self.rebuild_block_c(days)
            return f"sessions:{days}d"
        return None


# --- running the triage ------------------------------------------------------------------------


@dataclass
class TriageOutcome:
    """Everything one triage run produced; `run_shadow` turns this into the log line."""

    status: str = "no_triage"  # "ok" | "no_triage" | "over_budget"
    decision: TriageDecision | None = None
    iterations: int = 0
    prompt_tokens: int = 0  # largest single-request prompt (the number Haiku prices the step on)
    cached_tokens: int = 0  # cache reads, summed over iterations
    output_tokens: int = 0
    cost_usd: float = 0.0
    measured_tokens: list[int] = field(default_factory=list)
    count_method: str = "count_tokens"  # "estimate" if count_tokens was ever unavailable
    trimmed: list[str] = field(default_factory=list)
    tools_called: list[str] = field(default_factory=list)

    @property
    def over_budget(self) -> bool:
        return self.status == "over_budget"


def _measure(
    client: Any, model: str, system: list[dict[str, Any]], messages: list[dict[str, Any]],
    tools: list[dict[str, Any]], outcome: TriageOutcome,
) -> int:
    """Exact prompt tokens via the free count_tokens endpoint; a chars/3.5 estimate if it fails."""
    try:
        result = client.messages.count_tokens(model=model, system=system, messages=messages, tools=tools)
        return int(result.input_tokens)
    except (anthropic.APIError, httpx.HTTPError):
        log.warn("router count_tokens failed, estimating", exc_info=True)
        outcome.count_method = "estimate"
        chars = len(json.dumps([system, messages, tools], default=str))
        return int(chars / ESTIMATE_CHARS_PER_TOKEN)


def _fit_budget(
    client: Any, model: str, ctx: HaikuContext, tools: list[dict[str, Any]], outcome: TriageOutcome
) -> int | None:
    """Trim `ctx` until the measured request is within TARGET_TOKENS; returns the final measured
    size, or None when it still exceeds CEILING_TOKENS with nothing left to trim."""
    while True:
        system = ctx.system()
        messages = with_loop_breakpoint(system, ctx.messages(), tools, ctx.cache_ttl)
        measured = _measure(client, model, system, messages, tools, outcome)
        if measured <= TARGET_TOKENS:
            return measured
        chars = len(json.dumps([system, messages, tools], default=str))
        excess_chars = (measured - TARGET_TOKENS) * (chars / max(measured, 1))
        step = ctx.trim(excess_chars)
        if step is None:
            return measured if measured <= CEILING_TOKENS else None
        outcome.trimmed.append(step)


def _execute_read_tool(name: str, tool_input: Any, handlers: dict[str, ToolHandler]) -> dict[str, Any]:
    if name not in HAIKU_TOOL_ALLOWLIST or name not in handlers:
        return {"error": f"tool {name!r} is not available in router mode"}
    try:
        return handlers[name](tool_input if isinstance(tool_input, dict) else {})
    except Exception as exc:  # noqa: BLE001 - a tool bug must not break the triage; reported to the model
        log.error("router tool execution failed", tool=name, exc_info=True)
        return internal_tool_error(name, exc)


def run_triage(
    client: Any, *, model: str, context: HaikuContext, handlers: dict[str, ToolHandler]
) -> TriageOutcome:
    """One Haiku triage: at most HAIKU_MAX_ITERATIONS calls, budget re-measured before each.

    Raises anthropic.APIError / httpx.HTTPError from `messages.create` -- the caller (run_shadow)
    owns catching them so a failure can never reach the athlete."""
    tools = build_haiku_tools()
    outcome = TriageOutcome()
    for _ in range(HAIKU_MAX_ITERATIONS):
        measured = _fit_budget(client, model, context, tools, outcome)
        if measured is None:
            outcome.status = "over_budget"
            return outcome
        outcome.measured_tokens.append(measured)
        system = context.system()
        messages = with_loop_breakpoint(system, context.messages(), tools, context.cache_ttl)
        response = client.messages.create(
            model=model,
            max_tokens=HAIKU_MAX_OUTPUT_TOKENS,
            system=system,
            messages=messages,
            tools=tools,
            thinking={"type": "adaptive"},
        )
        outcome.iterations += 1
        prompt, cache_read, output, cost = _usage_cost(response.usage, model, context.cache_ttl)
        outcome.prompt_tokens = max(outcome.prompt_tokens, prompt)
        outcome.cached_tokens += cache_read
        outcome.output_tokens += output
        outcome.cost_usd += cost

        tool_uses = [b for b in response.content if getattr(b, "type", None) == "tool_use"]
        triage = next((b for b in tool_uses if b.name == TRIAGE_TOOL_NAME), None)
        if triage is not None:
            outcome.decision = TriageDecision.from_tool_input(
                triage.input if isinstance(triage.input, dict) else {}
            )
            outcome.status = "ok"
            return outcome
        if not tool_uses or response.stop_reason != "tool_use":
            return outcome  # text-only / refusal / max_tokens: no decision

        context.extra_messages.append(
            {"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in response.content]}
        )
        results = []
        for block in tool_uses:
            outcome.tools_called.append(block.name)
            result = _execute_read_tool(block.name, block.input, handlers)
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(result, default=str)})
        context.extra_messages.append({"role": "user", "content": results})
    return outcome


def timed(fn: Callable[[], TriageOutcome]) -> tuple[TriageOutcome, int]:
    """Run `fn`, returning its outcome and wall-clock milliseconds."""
    started = time.monotonic()
    outcome = fn()
    return outcome, int((time.monotonic() - started) * 1000)
