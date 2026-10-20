"""Haiku triage engine: tool allowlist, decision parsing, budgeted context, bounded tool loop,
cost maths. Fake client only -- no network, no LLM."""

from __future__ import annotations

import json
from typing import Any

import anthropic
import httpx
import pytest

from app.claude import with_loop_breakpoint
from app.router_triage import (
    CEILING_TOKENS,
    HAIKU_MAX_ITERATIONS,
    HAIKU_TOOL_ALLOWLIST,
    PRICE_STEP_TOKENS,
    TARGET_TOKENS,
    TRIAGE_CATEGORIES,
    HaikuContext,
    TriageDecision,
    build_haiku_tools,
    estimate_cost_usd,
    run_triage,
)
from app.save_claims import DRAFT_TOOLS, WRITE_TOOLS
from app.tools import TOOLS_SCHEMA
from fakes import (
    FakeRouterMessages,
    make_final_message,
    make_text_block,
    make_tool_use_block,
    make_triage_block,
    make_usage,
)

MODEL = "claude-haiku-5-5-test"
ROUTED_MARK = "ROUTED-LIBRARY-TEXT"


class _Client:
    def __init__(self, messages: FakeRouterMessages) -> None:
        self.messages = messages


def _ctx(*, history_turns: int = 0, filler: int = 0, sessions_filler: int = 0) -> HaikuContext:
    history: list[dict[str, Any]] = []
    for i in range(history_turns):
        history.append({"role": "user", "content": f"user turn {i} " + "x" * filler})
        history.append({"role": "assistant", "content": f"assistant turn {i} " + "y" * filler})

    def block_c(days: int) -> list[dict[str, Any]]:
        return [{"type": "text", "text": f"ATHLETE-CONTEXT days={days} " + "s" * min(days, 28) * sessions_filler}]

    return HaikuContext(
        block_a=[{"type": "text", "text": "PERSONA " + "a" * 400, "cache_control": {"type": "ephemeral"}}],
        block_c=block_c(28),
        block_b=[{"type": "text", "text": ROUTED_MARK + " b" * 200, "cache_control": {"type": "ephemeral"}}],
        history=history,
        question="what is on my plan tomorrow?",
        cache_ttl="5m",
        rebuild_block_c=block_c,
    )


def _full_tokens(ctx: HaikuContext) -> int:
    """What the fake count_tokens will report for this context as run_triage sends it."""
    tools = build_haiku_tools()
    sent = with_loop_breakpoint(ctx.system(), ctx.messages(), tools, ctx.cache_ttl)
    return len(json.dumps([ctx.system(), sent, tools], default=str)) // 4


def _msg(blocks: list[Any], stop: str = "tool_use", **usage: Any):
    return make_final_message(blocks, stop, make_usage(**usage))


def _run(responses: list[Any], ctx: HaikuContext | None = None, handlers: dict | None = None, **kw: Any):
    messages = FakeRouterMessages(responses, count_error=kw.pop("count_error", None))
    outcome = run_triage(_Client(messages), model=MODEL, context=ctx or _ctx(), handlers=handlers or {}, **kw)
    return outcome, messages


# --- tools -------------------------------------------------------------------------------------


def test_allowlist_is_read_only_and_real() -> None:
    schema_names = {t["name"] for t in TOOLS_SCHEMA}
    assert set(HAIKU_TOOL_ALLOWLIST) <= schema_names
    assert not set(HAIKU_TOOL_ALLOWLIST) & set(WRITE_TOOLS)
    assert not set(HAIKU_TOOL_ALLOWLIST) & DRAFT_TOOLS
    for forbidden in ("push_to_garmin", "sync_workouts", "export_zwo_workout", "reanalyze_workout",
                      "pull_activity_stream", "flag_for_coach_review", "log_app_feedback",
                      "set_workout_chat_muted", "render_plan_table", "check_plan"):
        assert forbidden not in HAIKU_TOOL_ALLOWLIST


def test_haiku_tools_are_allowlist_plus_triage_only() -> None:
    tools = build_haiku_tools()
    names = [t["name"] for t in tools]
    assert names[-1] == "triage"
    assert set(names[:-1]) == set(HAIKU_TOOL_ALLOWLIST)
    triage = tools[-1]
    props = triage["input_schema"]["properties"]
    assert props["route"]["enum"] == ["answer", "escalate"]
    assert set(props["category"]["enum"]) == set(TRIAGE_CATEGORIES)
    assert {"greeting/thanks", "plan lookup", "workout question", "general training question", "health",
            "planning", "race analysis", "research", "other"} == set(TRIAGE_CATEGORIES)
    assert props["complexity"]["minimum"] == 0 and props["complexity"]["maximum"] == 1
    assert set(triage["input_schema"]["required"]) >= {"route", "complexity", "confidence", "category", "reason"}


# --- decision parsing --------------------------------------------------------------------------


def test_decision_answer_requires_a_reply() -> None:
    d = TriageDecision.from_tool_input(
        {"route": "answer", "complexity": 0.1, "confidence": 0.9, "category": "other", "reason": "r"}
    )
    assert d.route == "escalate" and d.invalid is True


def test_decision_clamps_and_defaults() -> None:
    d = TriageDecision.from_tool_input(
        {"route": "answer", "complexity": 7, "confidence": -2, "category": "nonsense", "reason": "r" * 500,
         "reply": "hi"}
    )
    assert d.complexity == 1.0 and d.confidence == 0.0
    assert d.category == "other"
    assert len(d.reason) <= 200


def test_decision_unknown_route_escalates() -> None:
    d = TriageDecision.from_tool_input({"route": "maybe", "complexity": 0.5, "confidence": 0.5})
    assert d.route == "escalate" and d.invalid is True


def test_would_answer_threshold() -> None:
    d = TriageDecision.from_tool_input(
        {"route": "answer", "complexity": 0.3, "confidence": 0.85, "category": "plan lookup", "reason": "r",
         "reply": "x"}
    )
    assert d.would_answer(0.8) and not d.would_answer(0.9)
    hard = TriageDecision.from_tool_input(
        {"route": "answer", "complexity": 0.6, "confidence": 0.99, "category": "other", "reason": "r", "reply": "x"}
    )
    assert not hard.would_answer(0.7)  # complexity above the 0.5 Sonnet mark


# --- cost --------------------------------------------------------------------------------------


def test_cost_below_the_step() -> None:
    # 10k fresh in, 60k cache read, 0 write, 1k out at $0.10 / $0.01 / $0.50 per MTok
    cost = estimate_cost_usd(input_tokens=10_000, cache_read=60_000, cache_write_5m=0, cache_write_1h=0, output=1_000)
    assert cost == pytest.approx(0.001 + 0.0006 + 0.0005)


def test_cost_above_100k_is_five_times() -> None:
    low = estimate_cost_usd(input_tokens=99_000, cache_read=0, cache_write_5m=0, cache_write_1h=0, output=1_000)
    high = estimate_cost_usd(input_tokens=101_000, cache_read=0, cache_write_5m=0, cache_write_1h=0, output=1_000)
    assert PRICE_STEP_TOKENS == 100_000
    assert high == pytest.approx(5 * (101_000 * 0.10 + 1_000 * 0.50) / 1e6)
    assert low == pytest.approx((99_000 * 0.10 + 1_000 * 0.50) / 1e6)


def test_cost_counts_cache_reads_and_writes_toward_the_step() -> None:
    cost = estimate_cost_usd(input_tokens=1_000, cache_read=60_000, cache_write_5m=0, cache_write_1h=50_000, output=0)
    expected = 5 * (1_000 * 0.10 + 60_000 * 0.01 + 50_000 * 0.20) / 1e6
    assert cost == pytest.approx(expected)


# --- run_triage --------------------------------------------------------------------------------


def test_single_call_answer_and_request_shape() -> None:
    outcome, fake = _run([_msg([make_triage_block()], input_tokens=500, cache_read_input_tokens=40_000,
                               output_tokens=60)])
    assert outcome.decision is not None and outcome.decision.route == "answer"
    assert outcome.decision.reply == "Hi! Ready when you are."
    assert outcome.iterations == 1 and outcome.over_budget is False
    assert len(fake.creates) == 1
    kw = fake.creates[0]
    assert kw["model"] == MODEL
    assert kw["thinking"] == {"type": "adaptive"}
    for forbidden in ("temperature", "top_p", "top_k"):
        assert forbidden not in kw
    names = [t["name"] for t in kw["tools"]]
    assert set(names) == set(HAIKU_TOOL_ALLOWLIST) | {"triage"}
    assert outcome.cached_tokens == 40_000 and outcome.output_tokens == 60
    assert outcome.prompt_tokens == 40_500  # input + cache read + cache write, the number Haiku prices on
    assert outcome.cost_usd > 0


def test_same_cache_breakpoints_and_ttl_as_sonnet_layout() -> None:
    ctx = _ctx(history_turns=2)
    ctx.cache_ttl = "1h"
    ctx.block_a = [{**ctx.block_a[0], "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
    outcome, fake = _run([_msg([make_triage_block()])], ctx=ctx)
    system = fake.creates[0]["system"]
    assert system[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    marked = [b for b in system if "cache_control" in b]
    assert len(marked) >= 2
    sent = fake.creates[0]["messages"]
    # exactly one breakpoint in messages (end of history); loop breakpoint is a no-op at the cap of 4
    marks = sum(1 for m in sent if isinstance(m["content"], list) for b in m["content"] if "cache_control" in b)
    assert marks <= 1
    total = len(marked) + marks
    assert total <= 4


def test_measures_with_count_tokens_before_every_call() -> None:
    outcome, fake = _run([_msg([make_triage_block()])])
    assert len(fake.counts) >= 1
    assert fake.counts[0]["model"] == MODEL
    assert outcome.measured_tokens and outcome.measured_tokens[0] > 0
    assert outcome.count_method == "count_tokens"


def test_tool_loop_runs_read_tool_then_triage() -> None:
    calls: list[dict] = []

    def get_week_plan(inp: dict) -> dict:
        calls.append(inp)
        return {"sessions": ["swim"]}

    outcome, fake = _run(
        [
            _msg([make_tool_use_block("t1", "get_week_plan", {"iso_week": "current"})], output_tokens=30),
            _msg([make_triage_block()], output_tokens=50),
        ],
        handlers={"get_week_plan": get_week_plan},
    )
    assert calls == [{"iso_week": "current"}]
    assert outcome.iterations == 2 and outcome.decision.route == "answer"
    assert outcome.output_tokens == 80
    second = fake.creates[1]["messages"]
    assert second[-1]["role"] == "user" and second[-1]["content"][0]["type"] == "tool_result"
    assert len(fake.counts) >= 2, "budget is re-measured every iteration"


def test_non_allowlisted_tool_is_never_executed() -> None:
    called: list[str] = []
    handlers = {"author_week_plan": lambda inp: called.append("author") or {"persisted": True}}
    outcome, fake = _run(
        [
            _msg([make_tool_use_block("t1", "author_week_plan", {"confirm": True})]),
            _msg([make_triage_block(route="escalate", reply=None)]),
        ],
        handlers=handlers,
    )
    assert called == []
    result = json.loads(fake.creates[1]["messages"][-1]["content"][0]["content"])
    assert "error" in result


def test_tool_loop_is_capped() -> None:
    reads = [_msg([make_tool_use_block(f"t{i}", "get_week_plan", {"iso_week": "current"})]) for i in range(10)]
    outcome, fake = _run(reads, handlers={"get_week_plan": lambda inp: {"ok": True}})
    assert HAIKU_MAX_ITERATIONS == 3
    assert len(fake.creates) == 3
    assert outcome.iterations == 3
    assert outcome.decision is None and outcome.status == "no_triage"


def test_text_only_reply_without_triage_is_no_triage() -> None:
    outcome, _ = _run([_msg([make_text_block("hi there")], "end_turn")])
    assert outcome.decision is None and outcome.status == "no_triage"


def test_handler_exception_becomes_error_result_not_crash() -> None:
    def boom(inp: dict) -> dict:
        raise ValueError("kaput")

    outcome, fake = _run(
        [_msg([make_tool_use_block("t1", "get_week_plan", {})]), _msg([make_triage_block()])],
        handlers={"get_week_plan": boom},
    )
    assert outcome.decision is not None
    assert "error" in json.loads(fake.creates[1]["messages"][-1]["content"][0]["content"])


# --- budget ------------------------------------------------------------------------------------


def test_under_target_trims_nothing() -> None:
    outcome, fake = _run([_msg([make_triage_block()])])
    assert outcome.trimmed == []
    assert ROUTED_MARK in json.dumps(fake.creates[0]["system"])


def _force_budget(monkeypatch: pytest.MonkeyPatch, target: int, ceiling: int) -> None:
    import app.router_triage as rt

    monkeypatch.setattr(rt, "TARGET_TOKENS", target)
    monkeypatch.setattr(rt, "CEILING_TOKENS", ceiling)


def test_trim_order_routed_then_history_then_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _ctx(history_turns=6, filler=300, sessions_filler=200)
    full = _full_tokens(ctx)
    # reach the lowest step (routed + all history gone + sessions shrunk) by setting a tiny target
    _force_budget(monkeypatch, target=full // 4, ceiling=full * 2)
    outcome, fake = _run([_msg([make_triage_block()])], ctx=ctx)
    steps = [t.split(":")[0] for t in outcome.trimmed]
    assert steps[0] == "routed_library"
    first_history = steps.index("history")
    assert all(s == "history" for s in steps[first_history:first_history + 1])
    assert "sessions" in steps
    assert steps.index("routed_library") < first_history < steps.index("sessions")
    sent = fake.creates[0]
    assert ROUTED_MARK not in json.dumps(sent["system"])


def test_only_trims_as_much_as_needed(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _ctx(history_turns=4, filler=50)
    full = _full_tokens(ctx)
    routed = len(json.dumps(ctx.block_b)) // 4
    _force_budget(monkeypatch, target=full - routed // 2, ceiling=full * 2)  # dropping routed is enough
    outcome, fake = _run([_msg([make_triage_block()])], ctx=ctx)
    assert [t.split(":")[0] for t in outcome.trimmed] == ["routed_library"]
    assert len(fake.creates[0]["messages"]) == 9  # history untouched


def test_history_trim_drops_oldest_first_and_keeps_alternation(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _ctx(history_turns=5, filler=400)
    ctx.block_b = []  # nothing routed to trim; go straight to history
    full = _full_tokens(ctx)
    _force_budget(monkeypatch, target=full - 450, ceiling=full * 2)  # ~2 of the 5 turn pairs
    outcome, fake = _run([_msg([make_triage_block()])], ctx=ctx)
    sent = fake.creates[0]["messages"]
    assert sent[0]["role"] == "user"
    roles = [m["role"] for m in sent]
    assert all(a != b for a, b in zip(roles, roles[1:]))
    text = json.dumps(sent)
    assert "user turn 0" not in text and "user turn 4" in text  # oldest gone, newest kept
    assert sent[-1]["role"] == "user" and "what is on my plan tomorrow?" in json.dumps(sent[-1])


def test_over_ceiling_skips_the_haiku_call(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _ctx(history_turns=3, filler=100)
    _force_budget(monkeypatch, target=10, ceiling=20)
    outcome, fake = _run([_msg([make_triage_block()])], ctx=ctx)
    assert outcome.over_budget is True and outcome.status == "over_budget"
    assert outcome.decision is None
    assert fake.creates == []
    assert outcome.cost_usd == 0


def test_default_budget_constants() -> None:
    assert TARGET_TOKENS <= 80_000 and TARGET_TOKENS >= 70_000
    assert CEILING_TOKENS <= 95_000 < PRICE_STEP_TOKENS


def test_count_tokens_failure_falls_back_to_estimate_and_still_works() -> None:
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages/count_tokens")
    outcome, fake = _run(
        [_msg([make_triage_block()])], count_error=anthropic.APIConnectionError(request=req)
    )
    assert outcome.count_method == "estimate"
    assert outcome.decision is not None


def test_api_error_propagates_to_the_caller() -> None:
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    with pytest.raises(anthropic.APIConnectionError):
        _run([anthropic.APIConnectionError(request=req)])
