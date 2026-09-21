"""When a tool hits an INTERNAL error (a bug, not bad input) it must (1) be logged with a real stack
trace so it can be diagnosed, (2) hand the coach a structured, actionable result instead of a raw
exception string -- so it neither retries the same failing call nor makes an excuse -- and (3) never
take down a write over an OPTIONAL step. Andrew, 2026-09-21: graceful degradation with logging, so
failures are not silently eaten and the tool gives a better-than-fail answer."""

from __future__ import annotations

import json

from app.claude import MAX_TOOL_ITERATIONS, ClaudeChat
from app.logging_config import get_logger
from app.tool_errors import internal_tool_error
from fakes import FakeAnthropicClient, make_final_message, make_text_block, make_tool_use_block
from test_claude import _settings  # noqa: E402


def _lines(capsys):
    out = capsys.readouterr()
    return [json.loads(l) for l in (out.out + out.err).splitlines() if l.startswith("{")]


# --- 1. the logger records a real stack -----------------------------------------------------------


def test_exc_info_logs_the_type_and_a_real_stack_trace(capsys) -> None:
    log = get_logger("t")
    try:
        {}["missing"]
    except KeyError:
        log.error("boom", tool="x", exc_info=True)
    entry = _lines(capsys)[-1]
    assert entry["error_type"] == "KeyError"
    assert "Traceback" in entry["stack"] and "test_tool_failure_handling.py" in entry["stack"]
    assert "exc_info" not in entry  # it is consumed, never logged as a literal `true`


def test_a_huge_stack_is_capped(capsys) -> None:
    log = get_logger("t")

    def recurse(n):
        return recurse(n - 1) if n else 1 / 0

    try:
        recurse(400)
    except ZeroDivisionError:
        log.error("deep", exc_info=True)
    assert len(_lines(capsys)[-1]["stack"]) <= 6100


def test_logging_without_exc_info_is_unchanged(capsys) -> None:
    get_logger("t").info("plain", a=1)
    entry = _lines(capsys)[-1]
    assert entry["a"] == 1 and "stack" not in entry


# --- 2. the coach gets a structured, actionable result ----------------------------------------------


def test_the_internal_error_result_says_it_is_a_tool_bug_and_what_to_do_instead() -> None:
    result = internal_tool_error("patch_week_plan", AttributeError("'WorkoutRepeat' object has no attribute 'role'"))
    assert result["code"] == "internal_error" and result["input_problem"] is False
    assert result["do_not_retry_same_call"] is True
    assert "patch_week_plan" in result["error"] and "AttributeError" in result["error"]
    assert "structure" in result["what_to_do"]          # a real alternative path for week tools
    assert "Never" in result["what_to_do"] or "do not" in result["what_to_do"].lower()  # and no excuses


def test_every_tool_gets_some_guidance_even_an_unknown_one() -> None:
    assert internal_tool_error("some_new_tool", RuntimeError("x"))["what_to_do"]


def test_the_loop_logs_a_stack_and_returns_the_structured_result(capsys) -> None:
    tool_use = make_tool_use_block("t1", "patch_week_plan", {"iso_week": "2026-W30"})
    turns = [([], make_final_message([tool_use], "tool_use")), (["ok"], make_final_message([make_text_block("ok")], "end_turn"))]
    client = FakeAnthropicClient(turns)
    chat = ClaudeChat(_settings(), client=client)

    def broken(_input):
        raise AttributeError("'WorkoutRepeat' object has no attribute 'role'")

    list(chat.run_streaming([], [{"role": "user", "content": "x"}], [{"name": "patch_week_plan"}], {"patch_week_plan": broken}))

    failed = next(e for e in _lines(capsys) if e.get("msg") == "tool execution failed")
    assert failed["tool"] == "patch_week_plan" and failed["error_type"] == "AttributeError" and "Traceback" in failed["stack"]
    sent = json.loads(client.messages.calls[1]["messages"][-1]["content"][0]["content"])
    assert sent["code"] == "internal_error" and sent["do_not_retry_same_call"] is True


def test_the_turn_log_counts_tool_errors_so_the_failure_tax_is_measurable(capsys) -> None:
    tool_use = make_tool_use_block("t1", "patch_week_plan", {})
    turns = [([], make_final_message([tool_use], "tool_use")), ([], make_final_message([tool_use], "tool_use")),
             (["ok"], make_final_message([make_text_block("ok")], "end_turn"))]
    chat = ClaudeChat(_settings(), client=FakeAnthropicClient(turns))
    handlers = {"patch_week_plan": lambda _i: {"error": "bad input"}}  # an ordinary validation error counts too
    list(chat.run_streaming([], [{"role": "user", "content": "x"}], [{"name": "patch_week_plan"}], handlers))
    completes = [e for e in _lines(capsys) if e.get("msg") == "claude turn complete"]
    assert [c["tool_errors_so_far"] for c in completes] == [0, 1, 2]


# --- 3. optional steps degrade instead of failing the write ------------------------------------------------


def test_a_realism_check_that_crashes_does_not_fail_the_write(athletes_dir, monkeypatch, capsys) -> None:
    from swim_coach.store import FileStore

    import app.tools as tools

    store = FileStore(base_dir=athletes_dir)
    h = tools.build_tool_handlers(store, slug="renee", expert_mode=False)
    h["set_weekly_template"]({"template": {"tue": [{"kind": "bike", "role": "hard"}]}, "confirm": True})  # runs the realism re-run
    monkeypatch.setattr(tools, "evaluate_week_realism", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("realism blew up")))

    draft = h["replace_week_plan"]({"iso_week": "2026-W28"})
    assert "error" not in draft and draft["sessions"]                      # the plan is still drafted
    assert any("realism check could not run" in w.lower() for w in draft["planning_warnings"])
    logged = next(e for e in _lines(capsys) if e.get("msg") == "optional step failed")
    assert logged["step"] == "realism check" and "Traceback" in logged["stack"]   # and it is not silent


def test_one_workout_that_cannot_be_summarized_does_not_fail_get_workouts(athletes_dir, monkeypatch, capsys) -> None:
    from datetime import date

    from swim_coach.store import FileStore

    import app.tools as tools

    store = FileStore(base_dir=athletes_dir)
    h = tools.build_tool_handlers(store, slug="renee", expert_mode=False)
    real = tools._summarize_workout
    calls = {"n": 0}

    def flaky(w, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("bad analytics on this one")
        return real(w, **kw)

    monkeypatch.setattr(tools, "_summarize_workout", flaky)
    result = h["get_workouts"]({"start_date": "2026-01-01", "end_date": "2026-12-31"})
    assert "error" not in result and result["count"] >= 1
    assert any("summary_error" in w for w in result["workouts"])
    assert any(e.get("msg") == "optional step failed" for e in _lines(capsys))


# --- 4. nothing is silently eaten -------------------------------------------------------------------------


def test_a_storage_read_failure_is_logged_with_a_stack_and_still_answers_the_coach(athletes_dir, capsys) -> None:
    from swim_coach.store import FileStore

    import app.tools as tools

    class NoAthleteStore(FileStore):
        def load_athlete(self, slug):
            raise RuntimeError("db connection reset")

    h = tools.build_tool_handlers(NoAthleteStore(base_dir=athletes_dir), slug="renee", expert_mode=False)
    result = h["update_athlete_profile"]({"ftp_watts": 250})

    assert "could not load athlete profile" in result["error"]                # the coach still gets an answer
    entry = next(e for e in _lines(capsys) if e.get("msg") == "storage read failed")
    assert entry["what"] == "athlete profile" and entry["error_type"] == "RuntimeError" and "Traceback" in entry["stack"]


def test_a_swallowed_lookup_failure_leaves_a_log_line(athletes_dir, capsys) -> None:
    from swim_coach.store import FileStore

    from app.drafts import pending_drafts

    class BrokenList(FileStore):
        def list_week_drafts(self, slug):
            raise RuntimeError("simulated")

    assert pending_drafts(BrokenList(base_dir=athletes_dir), "renee") == []   # degrades to "none waiting"
    entry = next(e for e in _lines(capsys) if e.get("msg") == "swallowed exception, using a default")
    assert "drafts.py" in entry["where"] and "Traceback" in entry["stack"]
