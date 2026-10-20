"""Shadow-mode execution of the Haiku coach router (COACH_ROUTER_MODE=shadow).

For each eligible chat message: evaluate the deterministic pre-rules (app.router_rules); if none
fires, run Haiku's triage on a background thread CONCURRENTLY with the normal Sonnet turn. The
athlete still gets Sonnet's answer exactly as before -- the Sonnet stream is passed through
byte-for-byte; this module only watches it. One structured `router shadow` log line per message
joins Haiku's decision to what Sonnet actually did (tools called, write tools, output tokens).

Why a thread, not an asyncio task: the chat stream is a synchronous generator that Starlette runs
in a worker thread, and the Anthropic client used here is the synchronous one, so a daemon thread
is the honest concurrency primitive; it adds no latency to the stream and nothing it does can reach
the athlete (every failure is caught and logged).

Privacy: the log line never carries message text, Haiku's reason/reply, or health details. For the
athletes in COACH_ROUTER_CAPTURE_ATHLETES only, the question, Haiku's reply and Sonnet's reply are
stored in the router_shadow_captures table for a human to compare -- never in logs.

Seam for COACH_ROUTER_MODE=on (not implemented): `ShadowSession` exposes the finished decision;
the enable PR would await it BEFORE the Sonnet call and, when `TriageDecision.would_answer(...)`,
stream `reply` instead. Pre-rules and the budget logic are already shared.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from swim_coach.models import RouterShadowCapture
from swim_coach.store import StoreInterface

from app.claude import TurnStats
from app.config import Settings
from app.context import build_messages, build_routed_block, build_system_blocks
from app.logging_config import get_logger
from app.model_prices import price_for
from app.router_rules import CATEGORY_HEALTH, PreRuleHit, match_pre_rule
from app.router_triage import HaikuContext, TriageOutcome, run_triage
from app.save_claims import DRAFT_ONLY_TOOLS, SIDE_EFFECT_TOOLS, WRITE_TOOLS
from app.tools import ToolHandler

log = get_logger(__name__)

# Substrings of the per-request athlete context (system block C) that say an unconfirmed draft is
# waiting. Kept next to its producer by a test (tests/api/test_router_shadow.py asserts the real
# renderer still emits it).
PENDING_DRAFTS_MARKER = "Drafts waiting for the athlete's yes"

_THREADS: set[threading.Thread] = set()
_THREADS_LOCK = threading.Lock()


def join_shadow_threads(timeout: float = 5.0) -> None:
    """Wait for in-flight shadow workers (tests; also a clean-shutdown hook)."""
    with _THREADS_LOCK:
        threads = list(_THREADS)
    for thread in threads:
        thread.join(timeout)


def has_pending_draft(context_block: Sequence[dict[str, Any]]) -> bool:
    """Whether the already-built athlete context says a draft is waiting for the athlete's yes."""
    text = "".join(str(b.get("text", "")) for b in context_block)
    return PENDING_DRAFTS_MARKER in text


def sonnet_tool_flags(tools: Sequence[str]) -> dict[str, Any]:
    """How Sonnet's tool use compares with what a read-only router answer could have done."""
    return {
        "sonnet_tools": list(tools),
        "sonnet_write_tool": any(t in WRITE_TOOLS or t in SIDE_EFFECT_TOOLS for t in tools),
        "sonnet_draft_tool": any(t in DRAFT_ONLY_TOOLS for t in tools),
    }


@dataclass
class ShadowInputs:
    """Everything the router needs from one chat request (built by routes/chat.py)."""

    settings: Settings
    client: Any  # anything with messages.create / messages.count_tokens
    store: StoreInterface
    request_id: str
    athlete_slug: str
    athlete_id: str
    message: str  # the effective message Sonnet is asked
    history: list[dict[str, Any]]
    context_block: list[dict[str, Any]]  # block C exactly as Sonnet got it
    athlete_sports: list[str]
    # Re-renders block C with a shorter recent-sessions window (token-budget trim step 3).
    rebuild_context_block: Callable[[int], list[dict[str, Any]]]
    # Fresh read-only-capable tool handlers (only the allowlisted ones are ever executed).
    build_handlers: Callable[[], dict[str, ToolHandler]]


@dataclass
class _Recorder:
    """Joins Haiku's result and Sonnet's result and emits the single log line (and capture) once
    both are in, from whichever thread finishes last."""

    base: dict[str, Any]
    expects_haiku: bool
    question: str
    capture: Callable[[dict[str, Any]], None] | None
    started: float = field(default_factory=time.monotonic)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _haiku: dict[str, Any] | None = None
    _haiku_reply: str | None = None
    _sonnet: dict[str, Any] | None = None
    _sonnet_reply: str | None = None
    _emitted: bool = False

    def __post_init__(self) -> None:
        if not self.expects_haiku:
            self._haiku = {}

    def set_haiku(self, fields: dict[str, Any], reply: str | None) -> None:
        with self._lock:
            self._haiku, self._haiku_reply = fields, reply
        self._maybe_emit()

    def set_sonnet(self, stats: TurnStats, reply_text: str) -> None:
        fields = {
            **sonnet_tool_flags(stats.tools),
            "sonnet_wrote": stats.wrote,
            "sonnet_output_tokens": stats.output_tokens,
            "sonnet_completed": stats.completed,
            "sonnet_latency_ms": int((time.monotonic() - self.started) * 1000),
        }
        with self._lock:
            self._sonnet, self._sonnet_reply = fields, reply_text
        self._maybe_emit()

    def _maybe_emit(self) -> None:
        with self._lock:
            if self._emitted or self._haiku is None or self._sonnet is None:
                return
            self._emitted = True
            fields = {**self.base, **self._haiku, **self._sonnet}
            haiku_reply, sonnet_reply = self._haiku_reply, self._sonnet_reply
        if fields.get("pre_rule"):
            fields["route"] = "escalate"  # a pre-rule decides; a probe's Haiku answer is never used
        fields["disagree_write"] = bool(
            not fields.get("pre_rule")
            and fields.get("haiku_route") == "answer"
            and (fields["sonnet_write_tool"] or fields["sonnet_draft_tool"])
        )
        log.info("router shadow", **fields)
        if self.capture is not None:
            try:
                self.capture(
                    {"fields": fields, "question": self.question, "haiku_reply": haiku_reply,
                     "sonnet_reply": sonnet_reply}
                )
            except Exception:  # noqa: BLE001 - capture is best-effort; never affects the athlete
                log.error("router capture failed", request_id=fields.get("request_id"), exc_info=True)


def haiku_log_fields(
    outcome: TriageOutcome | None, latency_ms: int, status: str | None = None, model: str | None = None
) -> dict[str, Any]:
    """The Haiku half of the log line. `outcome=None` (worker crashed) logs status only."""
    if outcome is None:
        return {
            "status": status or "error", "haiku_route": None, "route": None, "complexity": None,
            "confidence": None, "category": None, "haiku_prompt_tokens": None, "haiku_cached_tokens": None,
            "haiku_output_tokens": None, "haiku_cost_usd": None, "iterations": 0, "over_budget": False,
            "latency_ms": latency_ms,
        }
    decision = outcome.decision
    return {
        "status": status or outcome.status,
        "haiku_route": decision.route if decision else None,
        "route": decision.route if decision else "escalate",
        "complexity": decision.complexity if decision else None,
        "confidence": decision.confidence if decision else None,
        "category": decision.category if decision else None,
        "haiku_invalid": decision.invalid if decision else None,
        # Haiku's own read that the message is health-related (it escalates on this alone).
        "haiku_health_escalate": decision.category == "health" if decision else None,
        "haiku_prompt_tokens": outcome.prompt_tokens or None,
        "haiku_measured_tokens": outcome.measured_tokens,
        "haiku_cached_tokens": outcome.cached_tokens,
        "haiku_output_tokens": outcome.output_tokens,
        "haiku_cost_usd": round(outcome.cost_usd, 6),
        "est_cost_usd": round(outcome.cost_usd, 6) if price_for(model) is not None else None,
        "prompt_tokens_total": outcome.prompt_tokens,
        "over_100k": outcome.prompt_tokens > 100_000,
        "haiku_tools": outcome.tools_called,
        "triage_fallback": outcome.triage_fallback,
        "triage_fallback_tokens": (outcome.fallback_prompt_tokens + outcome.fallback_output_tokens) or None,
        "triage_fallback_prompt_tokens": outcome.fallback_prompt_tokens or None,
        "triage_fallback_output_tokens": outcome.fallback_output_tokens or None,
        "triage_fallback_cost_usd": round(outcome.fallback_cost_usd, 6) if outcome.triage_fallback else None,
        "iterations": outcome.iterations,
        "over_budget": outcome.over_budget,
        "trimmed": outcome.trimmed,
        "count_method": outcome.count_method,
        "latency_ms": latency_ms,
    }


def build_haiku_context(inputs: ShadowInputs) -> HaikuContext:
    """Haiku's request, from the same builders Sonnet's uses: block A, block C (as built for this
    request), routed block B, history, question. Same breakpoints and TTLs."""
    settings = inputs.settings
    block_a = build_system_blocks(
        settings.library_dir, athlete_sports=inputs.athlete_sports, cache_ttl=settings.prompt_cache_ttl
    )
    block_b = build_routed_block(
        settings.library_dir, inputs.message, athlete_sports=inputs.athlete_sports,
        cache_ttl=settings.prompt_cache_ttl_context,
    )
    messages = build_messages(
        message=inputs.message, history=inputs.history, library_text=None,
        cache_ttl=settings.prompt_cache_ttl_context,
    )
    return HaikuContext(
        block_a=block_a,
        block_c=list(inputs.context_block),
        block_b=block_b,
        history=messages[:-1],
        question=messages[-1]["content"],
        cache_ttl=settings.prompt_cache_ttl_context,
        rebuild_block_c=inputs.rebuild_context_block,
    )


def _haiku_worker(inputs: ShadowInputs, recorder: _Recorder) -> None:
    """Runs the triage; ALWAYS reports to the recorder, whatever happens."""
    started = time.monotonic()
    outcome: TriageOutcome | None = None
    status: str | None = None
    try:
        context = build_haiku_context(inputs)
        outcome = run_triage(
            inputs.client, model=inputs.settings.router_model, context=context,
            handlers=inputs.build_handlers(),
        )
    except Exception:  # noqa: BLE001 - shadow failures must never touch the athlete's turn
        status = "error"
        log.error("router shadow triage failed", request_id=inputs.request_id, exc_info=True)
    latency_ms = int((time.monotonic() - started) * 1000)
    reply = outcome.decision.reply if outcome and outcome.decision else None
    try:
        recorder.set_haiku(haiku_log_fields(outcome, latency_ms, status, inputs.settings.router_model), reply)
    except Exception:  # noqa: BLE001
        log.error("router shadow record failed", request_id=inputs.request_id, exc_info=True)


def _make_capture(inputs: ShadowInputs) -> Callable[[dict[str, Any]], None] | None:
    if inputs.athlete_slug not in inputs.settings.router_capture_athletes:
        return None

    def capture(record: dict[str, Any]) -> None:
        fields = record["fields"]
        decision = {
            k: fields.get(k)
            for k in ("pre_rule", "pre_rule_id", "route", "haiku_route", "complexity", "confidence",
                      "category", "status", "haiku_prompt_tokens", "haiku_cost_usd", "iterations",
                      "over_budget", "sonnet_tools", "sonnet_write_tool", "sonnet_draft_tool", "disagree_write")
        }
        inputs.store.save_router_capture(
            inputs.athlete_slug,
            RouterShadowCapture(
                id=uuid.uuid4(),
                athlete_id=uuid.UUID(inputs.athlete_id),
                request_id=inputs.request_id,
                question=record["question"],
                haiku_reply=record["haiku_reply"],
                sonnet_reply=record["sonnet_reply"],
                decision=decision,
            ),
        )

    return capture


class ShadowSession:
    """Handle for one message's shadow run. `wrap` passes the Sonnet stream through unchanged."""

    def __init__(self, recorder: _Recorder, stats: TurnStats) -> None:
        self._recorder = recorder
        self.stats = stats
        self.pre_rule: str | None = recorder.base.get("pre_rule")
        self.pre_rule_id: str | None = recorder.base.get("pre_rule_id")

    def wrap(self, stream: Iterator[str]) -> Iterator[str]:
        reply_parts: list[str] = []
        try:
            for line in stream:
                self._observe(line, reply_parts)
                yield line
        finally:
            try:
                self._recorder.set_sonnet(self.stats, "".join(reply_parts).strip())
            except Exception:  # noqa: BLE001 - observing must never break the stream
                log.error("router shadow sonnet record failed", exc_info=True)

    @staticmethod
    def _observe(line: str, reply_parts: list[str]) -> None:
        if not line.startswith("data: "):
            return
        try:
            event = json.loads(line[len("data: "):])
        except ValueError:
            return
        if isinstance(event, dict) and event.get("type") == "text":
            reply_parts.append(str(event.get("text") or ""))


def begin_shadow(inputs: ShadowInputs) -> ShadowSession | None:
    """Start shadowing one message. Returns None (and the chat proceeds untouched) if anything at
    all goes wrong while setting up."""
    try:
        pending = has_pending_draft(inputs.context_block)
        hit: PreRuleHit | None = match_pre_rule(
            inputs.message, history=inputs.history, has_pending_draft=pending,
            sports=inputs.athlete_sports,
        )
        base: dict[str, Any] = {
            "request_id": inputs.request_id,
            "athlete_id": inputs.athlete_id,
            "mode": "shadow",
            "model": inputs.settings.router_model,
            "sonnet_model": inputs.settings.claude_model,
            "pre_rule": hit.category if hit else None,
            "pre_rule_id": hit.rule_id if hit else None,
        }
        # A health keyword hit still gets a Haiku PROBE (its answer is never used; the turn goes to
        # Sonnet regardless) so the report can count "keywords caught what Haiku called non-health".
        # Every other pre-rule skips Haiku entirely.
        probe = hit is not None and hit.category == CATEGORY_HEALTH
        base["haiku_probe"] = probe
        recorder = _Recorder(
            base=base, expects_haiku=hit is None or probe, question=inputs.message, capture=_make_capture(inputs)
        )
        if hit is not None and not probe:
            recorder.set_haiku(
                {"status": "skipped_pre_rule", "haiku_route": None, "route": "escalate", "over_budget": False},
                None,
            )
        else:
            thread = threading.Thread(
                target=_run_and_forget, args=(inputs, recorder), name="router-shadow", daemon=True
            )
            with _THREADS_LOCK:
                _THREADS.add(thread)
            thread.start()
        return ShadowSession(recorder, TurnStats())
    except Exception:  # noqa: BLE001 - the router is an observer; it cannot be allowed to fail a chat
        log.error("router shadow setup failed", request_id=inputs.request_id, exc_info=True)
        return None


def _run_and_forget(inputs: ShadowInputs, recorder: _Recorder) -> None:
    try:
        _haiku_worker(inputs, recorder)
    finally:
        with _THREADS_LOCK:
            _THREADS.discard(threading.current_thread())
