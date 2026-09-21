"""Unit tests for `app.claude.ClaudeChat` / `build_request_kwargs`, isolated
from the FastAPI layer. No real Anthropic API calls."""

from __future__ import annotations

import httpx

import anthropic

import json

from app.claude import (
    MAX_TOKENS_TRUNCATION_MARKER,
    MAX_TOOL_ITERATIONS,
    ClaudeChat,
    build_request_kwargs,
    count_cache_breakpoints,
    request_segment_sizes,
    with_loop_breakpoint,
)
from app.config import Settings
from fakes import (
    FakeAnthropicClient,
    make_final_message,
    make_text_block,
    make_tool_use_block,
    make_usage,
)


def _settings(**overrides) -> Settings:
    base = dict(
        anthropic_api_key="sk-ant-test",
        api_token_hash="x" * 64,
        claude_model="claude-sonnet-5",
        claude_thinking="adaptive",
        allowed_origins=["https://ashaber.github.io"],
        athletes_dir=None,
        library_dir=None,
        research_dir=None,
        port=8000,
        chat_rate_per_min=20,
        store_backend="file",
        database_url=None,
        google_client_id="test-client-id.apps.googleusercontent.com",
        session_ttl_days=30,
        chat_daily_cap_per_athlete=50,
    )
    base.update(overrides)
    return Settings(**base)


def test_build_request_kwargs_adaptive_thinking_is_explicit() -> None:
    settings = _settings(claude_thinking="adaptive")
    kwargs = build_request_kwargs(settings, system=[], messages=[])
    # Explicit, not omitted -- omission means "off" on the Opus line.
    assert kwargs["thinking"] == {"type": "adaptive"}
    assert "budget_tokens" not in kwargs["thinking"]
    assert "temperature" not in kwargs
    assert "top_p" not in kwargs
    assert "top_k" not in kwargs


def test_build_request_kwargs_disabled_thinking() -> None:
    settings = _settings(claude_thinking="disabled")
    kwargs = build_request_kwargs(settings, system=[], messages=[])
    assert kwargs["thinking"] == {"type": "disabled"}
    assert "budget_tokens" not in kwargs["thinking"]


def test_build_request_kwargs_omits_tools_when_empty() -> None:
    settings = _settings()
    kwargs = build_request_kwargs(settings, system=[], messages=[], tools=[])
    assert "tools" not in kwargs


def test_run_streaming_max_iterations_guard() -> None:
    settings = _settings()
    tool_use = make_tool_use_block("t1", "get_plan_summary", {})
    # Every turn returns tool_use -- would loop forever without the guard.
    turns = [([], make_final_message([tool_use], "tool_use")) for _ in range(MAX_TOOL_ITERATIONS)]
    client = FakeAnthropicClient(turns)
    chat = ClaudeChat(settings, client=client)

    handlers = {"get_plan_summary": lambda _input: {"ok": True}}
    events = list(chat.run_streaming([], [], [{"name": "get_plan_summary"}], handlers))

    assert any('"type": "error"' in e for e in events)
    assert len(client.messages.calls) == MAX_TOOL_ITERATIONS


def test_max_iterations_yields_coach_voiced_text_alongside_error_and_warns(capsys) -> None:
    # Build E: real incident, prod 2026-09-11 -- a "remove this session"
    # request retried replace_week_plan 5 times (genuine retries, input
    # tokens growing each turn) and surfaced only a bare
    # `{"error": "max tool iterations exceeded"}`, zero information for the
    # athlete. The streaming path must now ALSO yield a normal-rendering
    # "text" event with a coach-voiced explanation before the error event,
    # and the WARN log must carry tools_invoked across ALL iterations.
    settings = _settings()
    tool_use_1 = make_tool_use_block("t1", "replace_week_plan", {"iso_week": "2026-W30"})
    tool_use_2 = make_tool_use_block("t2", "propose_adaptation", {})
    turns = [
        ([], make_final_message([tool_use_1], "tool_use")) if i % 2 == 0
        else ([], make_final_message([tool_use_2], "tool_use"))
        for i in range(MAX_TOOL_ITERATIONS)
    ]
    client = FakeAnthropicClient(turns)
    chat = ClaudeChat(settings, client=client)

    handlers = {
        "replace_week_plan": lambda _input: {"error": "still broken"},
        "propose_adaptation": lambda _input: {"error": "still broken too"},
    }
    events = list(
        chat.run_streaming(
            [],
            [{"role": "user", "content": "remove Wednesday's strength session"}],
            [{"name": "replace_week_plan"}, {"name": "propose_adaptation"}],
            handlers,
        )
    )

    text_events = [json.loads(e[len("data: ") :]) for e in events if '"type": "text"' in e]
    joined = "".join(t["text"] for t in text_events)
    assert "wasn't able to finish" in joined
    assert "nothing was saved" in joined

    # error event still present -- run_once still needs a hard failure signal.
    assert any('"type": "error"' in e for e in events)
    # the coach-voiced text is yielded BEFORE the error event (soft bubble
    # first, error chip after -- see _run_turns' own comment for why).
    error_index = next(i for i, e in enumerate(events) if '"type": "error"' in e)
    text_index = next(i for i, e in enumerate(events) if '"type": "text"' in e and "wasn't able to finish" in e)
    assert text_index < error_index

    logged = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{") and "max tool iterations exceeded" in line
    ]
    warn = next(r for r in logged if r["level"] == "warn" and r["msg"] == "max tool iterations exceeded")
    assert warn["max_iterations"] == MAX_TOOL_ITERATIONS
    assert "replace_week_plan" in warn["tools_invoked"]
    assert "propose_adaptation" in warn["tools_invoked"]
    assert len(warn["tools_invoked"]) == MAX_TOOL_ITERATIONS


def test_tool_call_input_and_error_flag_are_logged_every_iteration(capsys) -> None:
    # Build E: this incident could only be diagnosed from stop_reason/
    # token-count patterns, not what was actually TRIED -- close that gap
    # with a per-tool-call log line: tool name, a bounded input summary,
    # and whether the result carried an "error" key.
    settings = _settings()
    tool_use = make_tool_use_block("t1", "replace_week_plan", {"iso_week": "2026-W30", "confirm": False})
    turns = [([], make_final_message([tool_use], "tool_use")) for _ in range(MAX_TOOL_ITERATIONS)]
    client = FakeAnthropicClient(turns)
    chat = ClaudeChat(settings, client=client)

    handlers = {"replace_week_plan": lambda _input: {"error": "still broken"}}
    list(
        chat.run_streaming(
            [], [{"role": "user", "content": "x"}], [{"name": "replace_week_plan"}], handlers
        )
    )

    logged = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{") and json.loads(line).get("msg") == "tool call"
    ]
    assert len(logged) == MAX_TOOL_ITERATIONS
    for i, entry in enumerate(logged):
        assert entry["tool"] == "replace_week_plan"
        assert entry["iteration"] == i
        assert entry["had_error"] is True
        assert "2026-W30" in entry["input_summary"]


def test_tool_call_log_had_error_false_on_success(capsys) -> None:
    settings = _settings()
    tool_use = make_tool_use_block("t1", "get_plan_summary", {})
    final = make_final_message([tool_use], "tool_use")
    end_final = make_final_message([make_text_block("done")], "end_turn")
    client = FakeAnthropicClient([([], final), (["done"], end_final)])
    chat = ClaudeChat(settings, client=client)

    handlers = {"get_plan_summary": lambda _input: {"ok": True}}
    list(chat.run_streaming([], [{"role": "user", "content": "x"}], [{"name": "get_plan_summary"}], handlers))

    logged = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{") and json.loads(line).get("msg") == "tool call"
    ]
    assert len(logged) == 1
    assert logged[0]["had_error"] is False


def test_tool_call_log_carries_the_real_error_text_not_just_the_boolean(capsys) -> None:
    # Real incident, 2026-09-18: `had_error` alone was enough to see THAT
    # replace_week_plan kept failing, but root-causing WHY required
    # reconstructing the failure from a truncated `input_summary` with no
    # error text at all -- this closes that gap.
    settings = _settings()
    tool_use = make_tool_use_block("t1", "replace_week_plan", {"iso_week": "2026-W30"})
    final = make_final_message([tool_use], "tool_use")
    end_final = make_final_message([make_text_block("done")], "end_turn")
    client = FakeAnthropicClient([([], final), (["done"], end_final)])
    chat = ClaudeChat(settings, client=client)

    handlers = {"replace_week_plan": lambda _input: {"error": "no such week: 2026-W30"}}
    list(chat.run_streaming([], [{"role": "user", "content": "x"}], [{"name": "replace_week_plan"}], handlers))

    logged = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{") and json.loads(line).get("msg") == "tool call"
    ]
    assert len(logged) == 1
    assert logged[0]["had_error"] is True
    assert logged[0]["error"] == "no such week: 2026-W30"


def test_tool_call_log_surfaces_the_tools_own_persisted_verdict(capsys) -> None:
    # Real incident, 2026-09-18: draft_season_macro_plan's `confirm: true`
    # follow-up was narrated to the athlete as "Persisted"/"verified" twice
    # in one evening, but the real DB never changed -- `had_error=False`
    # alone can't distinguish "actually wrote" from "returned a clean
    # draft-only result" for a draft-then-confirm tool. Logging the tool's
    # own `persisted` field directly answers "did this write anything"
    # without needing to reconstruct it from the database after the fact.
    settings = _settings()
    tool_use = make_tool_use_block("t1", "draft_season_macro_plan", {"confirm": True})
    final = make_final_message([tool_use], "tool_use")
    end_final = make_final_message([make_text_block("done")], "end_turn")
    client = FakeAnthropicClient([([], final), (["done"], end_final)])
    chat = ClaudeChat(settings, client=client)

    handlers = {"draft_season_macro_plan": lambda _input: {"persisted": False, "coverage": {}}}
    list(
        chat.run_streaming(
            [], [{"role": "user", "content": "x"}], [{"name": "draft_season_macro_plan"}], handlers
        )
    )

    logged = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{") and json.loads(line).get("msg") == "tool call"
    ]
    assert len(logged) == 1
    assert logged[0]["had_error"] is False
    assert logged[0]["persisted"] is False


def test_tool_call_log_persisted_is_null_for_a_tool_result_with_no_such_field(capsys) -> None:
    # A read-only tool's result (e.g. get_plan_summary) has no `persisted`
    # concept at all -- must log a real null, not crash or fabricate False
    # (which would misleadingly read as "this tried to persist and didn't").
    settings = _settings()
    tool_use = make_tool_use_block("t1", "get_plan_summary", {})
    final = make_final_message([tool_use], "tool_use")
    end_final = make_final_message([make_text_block("done")], "end_turn")
    client = FakeAnthropicClient([([], final), (["done"], end_final)])
    chat = ClaudeChat(settings, client=client)

    handlers = {"get_plan_summary": lambda _input: {"ok": True}}
    list(chat.run_streaming([], [{"role": "user", "content": "x"}], [{"name": "get_plan_summary"}], handlers))

    logged = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{") and json.loads(line).get("msg") == "tool call"
    ]
    assert len(logged) == 1
    assert logged[0]["persisted"] is None
    assert logged[0]["error"] is None


def test_max_tokens_stop_reason_appends_visible_marker_and_warns(capsys) -> None:
    # Prod 2026-09-10: a "redraft this week" turn hit stop_reason=max_tokens
    # at exactly 16384 output tokens; the PWA showed a truncated answer with
    # NO indication anything was cut off. Never silent: the streamed text
    # must carry a visible marker AND app.claude must emit a WARN log so
    # every hit is a reviewable signal.
    settings = _settings()
    final = make_final_message(
        [make_text_block("Here is the start of the redraft")],
        "max_tokens",
        usage=make_usage(output_tokens=16384),
    )
    client = FakeAnthropicClient([(["Here is the start of the redraft"], final)])
    chat = ClaudeChat(settings, client=client)

    events = list(
        chat.run_streaming(
            [], [{"role": "user", "content": "redraft this week"}], [{"name": "create_week_plan"}], {}
        )
    )

    # The partial text still reaches the client, followed by the visible marker.
    text_events = [json.loads(e[len("data: ") :]) for e in events if '"type": "text"' in e]
    joined = "".join(t["text"] for t in text_events)
    assert "Here is the start of the redraft" in joined
    assert MAX_TOKENS_TRUNCATION_MARKER in joined
    assert "cut off" in MAX_TOKENS_TRUNCATION_MARKER

    # Loop still terminates cleanly with a done event carrying the reason.
    assert any('"type": "done"' in e and "max_tokens" in e for e in events)

    # WARN log from app.claude, with the review-signal fields.
    logged = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{") and "max_tokens" in line
    ]
    warn = next(r for r in logged if r["level"] == "warn" and r["msg"] == "turn hit max_tokens")
    assert warn["output_tokens"] == 16384
    assert warn["iteration"] == 0
    assert "create_week_plan" in warn["tools_available"]


def test_max_tokens_marker_not_emitted_on_normal_end_turn() -> None:
    settings = _settings()
    final = make_final_message([make_text_block("all done, nothing cut")], "end_turn")
    client = FakeAnthropicClient([(["all done, nothing cut"], final)])
    chat = ClaudeChat(settings, client=client)

    events = list(chat.run_streaming([], [{"role": "user", "content": "hi"}], [], {}))
    assert not any(MAX_TOKENS_TRUNCATION_MARKER in e for e in events)


def test_run_streaming_handles_anthropic_api_error() -> None:
    settings = _settings()

    class BrokenMessagesAPI:
        def stream(self, **kwargs):
            request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
            raise anthropic.APIConnectionError(request=request)

    class BrokenClient:
        def __init__(self):
            self.messages = BrokenMessagesAPI()

    chat = ClaudeChat(settings, client=BrokenClient())
    events = list(chat.run_streaming([], [{"role": "user", "content": "hi"}], [], {}))

    assert len(events) == 1
    assert '"type": "error"' in events[0]


def test_run_streaming_unknown_tool_reports_error_result() -> None:
    settings = _settings()
    tool_use = make_tool_use_block("t1", "not_a_real_tool", {})
    turn_1 = make_final_message([tool_use], "tool_use")
    turn_2 = make_final_message([make_text_block("done")], "end_turn")
    client = FakeAnthropicClient([([], turn_1), (["done"], turn_2)])
    chat = ClaudeChat(settings, client=client)

    list(chat.run_streaming([], [], [], {}))  # no handlers registered at all

    second_call_messages = client.messages.calls[1]["messages"]
    tool_result = second_call_messages[-1]["content"][0]
    assert "unknown tool" in tool_result["content"]


def test_replayed_assistant_content_drops_sdk_only_null_fields() -> None:
    # D1: a text block emitted alongside a tool_use carries SDK-only null
    # fields (parsed_output/citations). When the assistant turn is replayed on
    # the follow-up request, those must not be sent back or the API 400s with
    # "text.parsed_output: Extra inputs are not permitted".
    settings = _settings()
    text = make_text_block("logging a question for research...")
    tool_use = make_tool_use_block("t1", "flag_for_coach_review", {"question": "fueling?"})
    turn_1 = make_final_message([text, tool_use], "tool_use")
    turn_2 = make_final_message([make_text_block("done")], "end_turn")
    client = FakeAnthropicClient([([], turn_1), (["done"], turn_2)])
    chat = ClaudeChat(settings, client=client)

    list(chat.run_streaming([], [], [], {"flag_for_coach_review": lambda _in: {"ok": True}}))

    replayed = client.messages.calls[1]["messages"]
    assistant_turn = next(m for m in replayed if m["role"] == "assistant")
    text_blocks = [b for b in assistant_turn["content"] if b["type"] == "text"]
    assert text_blocks, "the assistant's text block must be replayed"
    for block in assistant_turn["content"]:
        assert "parsed_output" not in block
        assert "citations" not in block


# --- request segment sizes (IDEA 022 step 1: measure before optimizing) -------


def test_request_segment_sizes_splits_history_context_and_question() -> None:
    system = [{"type": "text", "text": "A" * 400}, {"type": "text", "text": "B" * 800}]
    tools = [{"name": "t", "description": "d" * 100}]
    messages = [
        {"role": "user", "content": "h" * 40},
        {"role": "assistant", "content": [{"type": "text", "text": "a" * 60}]},
        {"role": "user", "content": "C" * 1000 + "\n\n---\n\n" + "how did it go?"},
    ]

    sizes = request_segment_sizes(system, messages, tools)

    assert sizes["system_block_chars"] == [400, 800]
    assert sizes["system_chars"] == 1200
    assert sizes["tools_chars"] == len(json.dumps(tools))
    assert sizes["tool_count"] == 1
    assert sizes["history_chars"] == 100
    assert sizes["history_messages"] == 2
    assert sizes["question_chars"] == len("how did it go?")
    assert sizes["context_chars"] == 1000
    total = sizes["system_chars"] + sizes["tools_chars"] + sizes["history_chars"] + sizes["latest_message_chars"]
    assert sizes["est_input_tokens"] == total // 4


def test_request_segment_sizes_handles_no_tools_no_history_no_delimiter() -> None:
    sizes = request_segment_sizes(
        [{"type": "text", "text": "S"}], [{"role": "user", "content": "just a question"}], None
    )
    assert sizes["tools_chars"] == 0
    assert sizes["tool_count"] == 0
    assert sizes["history_chars"] == 0
    assert sizes["context_chars"] == 0
    assert sizes["question_chars"] == len("just a question")


def test_request_sizes_logged_once_on_the_first_iteration_only(capsys) -> None:
    tool_use = make_tool_use_block("t1", "get_workouts", {})
    turns = [
        ([], make_final_message([tool_use], "tool_use")),
        ([], make_final_message([make_text_block("done")], "end_turn")),
    ]
    chat = ClaudeChat(_settings(), client=FakeAnthropicClient(turns))

    list(
        chat.run_streaming(
            [{"type": "text", "text": "sys"}],
            [{"role": "user", "content": "ctx\n\n---\n\nq"}],
            [{"name": "get_workouts"}],
            {"get_workouts": lambda _i: {"ok": True}},
        )
    )

    logged = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{") and json.loads(line).get("msg") == "claude request sizes"
    ]
    assert len(logged) == 1
    assert logged[0]["tool_count"] == 1
    assert logged[0]["model"] == "claude-sonnet-5"


# --- moving cache breakpoint inside the tool loop (IDEA 022 step 2) ----------
# Every tool-loop iteration re-sends the newest user message (per-request
# context) and all tool results so far. Without a breakpoint after them they
# are re-billed at full price on each iteration; a breakpoint on the LAST
# block of the LAST message makes iteration N+1 read them from cache.

EPHEMERAL = {"type": "ephemeral"}


def _marked(messages) -> list[int]:
    """Indexes of messages carrying a cache_control marker on any block."""
    return [
        i for i, m in enumerate(messages)
        if isinstance(m["content"], list) and any("cache_control" in b for b in m["content"])
    ]


def test_with_loop_breakpoint_marks_last_block_of_last_message_without_mutating() -> None:
    messages = [
        {"role": "user", "content": "ctx\n\n---\n\nq"},
    ]
    out = with_loop_breakpoint([], messages, None)

    assert out[-1]["content"] == [{"type": "text", "text": "ctx\n\n---\n\nq", "cache_control": EPHEMERAL}]
    assert messages == [{"role": "user", "content": "ctx\n\n---\n\nq"}]  # input untouched


def test_with_loop_breakpoint_marks_last_tool_result_block() -> None:
    results = [
        {"type": "tool_result", "tool_use_id": "a", "content": "1"},
        {"type": "tool_result", "tool_use_id": "b", "content": "2"},
    ]
    messages = [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": [{"type": "text", "text": "x"}]},
        {"role": "user", "content": results},
    ]
    out = with_loop_breakpoint([], messages, None)

    assert "cache_control" not in out[-1]["content"][0]
    assert out[-1]["content"][1]["cache_control"] == EPHEMERAL
    assert "cache_control" not in results[1]  # original block dict untouched


def test_with_loop_breakpoint_never_exceeds_four_breakpoints() -> None:
    system = [
        {"type": "text", "text": "A", "cache_control": EPHEMERAL},
        {"type": "text", "text": "B", "cache_control": EPHEMERAL},
    ]
    history_marked = {"role": "assistant", "content": [{"type": "text", "text": "h", "cache_control": EPHEMERAL}]}
    tools = [{"name": "t", "cache_control": EPHEMERAL}]
    messages = [{"role": "user", "content": "u"}, history_marked, {"role": "user", "content": "q"}]

    assert count_cache_breakpoints(system, messages, tools) == 4
    out = with_loop_breakpoint(system, messages, tools)  # already at the cap
    assert count_cache_breakpoints(system, out, tools) == 4
    assert out[-1]["content"] == "q"


def test_real_system_plus_history_plus_loop_marker_totals_exactly_four(app_env, library_dir) -> None:
    from app.context import build_messages, build_system
    from swim_coach.store import FileStore

    system = build_system(library_dir, "hello")
    messages = build_messages(
        FileStore(base_dir=app_env),
        "renee",
        message="q",
        history=[{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}],
        expert_mode=False,
    )
    assert count_cache_breakpoints(system, with_loop_breakpoint(system, messages, None), None) == 4


def test_tool_loop_requests_carry_the_marker_on_the_current_last_message_only() -> None:
    tool_use = make_tool_use_block("t1", "get_workouts", {})
    turns = [
        ([], make_final_message([tool_use], "tool_use")),
        ([], make_final_message([make_text_block("done")], "end_turn")),
    ]
    client = FakeAnthropicClient(turns)
    chat = ClaudeChat(_settings(), client=client)

    list(
        chat.run_streaming(
            [{"type": "text", "text": "sys"}],
            [{"role": "user", "content": "ctx\n\n---\n\nq"}],
            [{"name": "get_workouts"}],
            {"get_workouts": lambda _i: {"ok": True}},
        )
    )

    first, second = (c["messages"] for c in client.messages.calls)
    assert _marked(first) == [0]
    assert _marked(second) == [2]  # moved to the newest (tool_result) message; not left on message 0
