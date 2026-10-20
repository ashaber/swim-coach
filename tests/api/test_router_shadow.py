"""Shadow mode end to end through POST /api/chat with fake clients: the athlete's stream is
unaffected, one `router shadow` line joins Haiku's decision to Sonnet's behaviour, nothing private
is logged, and every Haiku failure is swallowed."""

from __future__ import annotations

import json
from typing import Any

import anthropic
import httpx
import pytest
from swim_coach.store import FileStore

from app.router_shadow import PENDING_DRAFTS_MARKER, join_shadow_threads
from fakes import (
    FakeRouterMessages,
    auth_headers,
    make_final_message,
    make_text_block,
    make_tool_use_block,
    make_triage_block,
    make_usage,
)

SENTINEL = "ZXQ-SENTINEL-93"
HAIKU_REPLY = "HAIKU-REPLY-SENTINEL-77 easy swim tomorrow"


def _payload(message: str = f"{SENTINEL} what is on my plan tomorrow?", **kw: Any) -> dict:
    return {"message": message, "history": [], "athlete": "renee", "expert_mode": False, **kw}


def _logged(capsys) -> list[dict]:
    captured = capsys.readouterr()
    text = captured.out + "\n" + captured.err  # errors go to stderr
    return [json.loads(line) for line in text.splitlines() if line.startswith("{")]


def _haiku_answer(**kw: Any):
    block = make_triage_block(reply=HAIKU_REPLY, **kw)
    return make_final_message([block], "tool_use", make_usage(input_tokens=900, cache_read_input_tokens=50_000,
                                                              output_tokens=80))


@pytest.fixture
def shadow_client(monkeypatch: pytest.MonkeyPatch, app_env, fake_claude_chat_factory):
    """(post, router_fake): a chat client with COACH_ROUTER_MODE=shadow whose Anthropic fake also
    serves Haiku's create/count_tokens."""
    monkeypatch.setenv("COACH_ROUTER_MODE", "shadow")
    monkeypatch.setenv("COACH_ROUTER_MODEL", "claude-haiku-5-5")
    monkeypatch.setenv("COACH_ROUTER_CAPTURE_ATHLETES", "renee")
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.routes.chat import get_claude_chat
    from app.claude import ClaudeChat
    from fakes import FakeAnthropicClient

    app = create_app()

    def make(sonnet_turns, haiku_responses, **router_kw):
        fake = FakeAnthropicClient(sonnet_turns)
        router = FakeRouterMessages(haiku_responses, **router_kw)
        fake.messages.create = router.create
        fake.messages.count_tokens = router.count_tokens
        chat = ClaudeChat(app.state.settings, client=fake)
        app.dependency_overrides[get_claude_chat] = lambda: chat
        return fake, router

    with TestClient(app) as client:
        yield client, make, app


def _sonnet_text(text: str = "Tomorrow is an easy swim."):
    return [([text], make_final_message([make_text_block(text)], "end_turn", make_usage(output_tokens=33)))]


def test_router_off_runs_nothing_and_logs_no_router_line(client, fake_claude_chat_factory, capsys) -> None:
    chat = fake_claude_chat_factory(_sonnet_text())
    chat.client.messages.create = lambda **kw: pytest.fail("Haiku must not run when the router is off")
    r = client.post("/api/chat", json=_payload(), headers=auth_headers())
    assert r.status_code == 200
    join_shadow_threads()
    assert not [l for l in _logged(capsys) if l.get("msg") == "router shadow"]


def test_shadow_stream_is_identical_and_one_line_joins_both(shadow_client, client, fake_claude_chat_factory, capsys) -> None:
    sc, make, _ = shadow_client
    baseline_chat = fake_claude_chat_factory(_sonnet_text())
    baseline = client.post("/api/chat", json=_payload(), headers=auth_headers()).text
    capsys.readouterr()

    fake, router = make(_sonnet_text(), [_haiku_answer()])
    r = sc.post("/api/chat", json=_payload(), headers=auth_headers())
    join_shadow_threads()
    assert r.text == baseline  # Sonnet's answer, byte for byte
    lines = [l for l in _logged(capsys) if l.get("msg") == "router shadow"]
    assert len(lines) == 1
    line = lines[0]
    assert line["pre_rule"] is None
    assert line["haiku_route"] == "answer" and line["route"] == "answer"
    assert line["confidence"] == 0.9 and line["complexity"] == 0.2 and line["category"] == "greeting/thanks"
    assert line["haiku_prompt_tokens"] == 50_900 and line["haiku_cached_tokens"] == 50_000
    assert line["haiku_output_tokens"] == 80 and line["iterations"] == 1
    assert line["over_budget"] is False and line["haiku_cost_usd"] > 0
    assert line["model"] == "claude-haiku-5-5" and line["est_cost_usd"] == line["haiku_cost_usd"]
    assert line["over_100k"] is False and line["prompt_tokens_total"] == 50_900
    assert line["sonnet_tools"] == [] and line["sonnet_write_tool"] is False
    assert line["sonnet_output_tokens"] == 33 and line["sonnet_completed"] is True
    assert line["disagree_write"] is False
    assert line["request_id"]
    assert len(router.creates) == 1 and router.counts, "Haiku was measured and called"


def test_haiku_answer_while_sonnet_wrote_is_flagged_as_disagreement(shadow_client, capsys) -> None:
    sc, make, _ = shadow_client
    tool_turn = ([], make_final_message(
        [make_tool_use_block("t1", "set_event_active_status", {"event_name": "nope", "active": False})],
        "tool_use", make_usage(output_tokens=10)))
    final_turn = _sonnet_text("done")[0]
    make([tool_turn, final_turn], [_haiku_answer()])
    sc.post("/api/chat", json=_payload(), headers=auth_headers())
    join_shadow_threads()
    line = [l for l in _logged(capsys) if l.get("msg") == "router shadow"][0]
    assert line["sonnet_tools"] == ["set_event_active_status"]
    assert line["sonnet_write_tool"] is True
    assert line["disagree_write"] is True


def test_pre_rule_skips_haiku_and_is_logged(shadow_client, capsys) -> None:
    sc, make, _ = shadow_client
    fake, router = make(_sonnet_text(), [])
    r = sc.post("/api/chat", json=_payload("please move tomorrow's session to Friday"), headers=auth_headers())
    join_shadow_threads()
    assert r.status_code == 200
    assert router.creates == [] and router.counts == []
    line = [l for l in _logged(capsys) if l.get("msg") == "router shadow"][0]
    assert line["pre_rule"] == "write_intent" and line["pre_rule_id"]
    assert line["route"] == "escalate" and line["status"] == "skipped_pre_rule"
    assert line["haiku_probe"] is False


def test_health_keyword_hit_probes_haiku_but_still_goes_to_sonnet(shadow_client, capsys) -> None:
    sc, make, _ = shadow_client
    probe = _haiku_answer(category="other")  # Haiku thinks it is NOT health: the keywords disagree
    fake, router = make(_sonnet_text(), [probe])
    r = sc.post("/api/chat", json=_payload("my knee hurts when I kick"), headers=auth_headers())
    join_shadow_threads()
    assert r.status_code == 200
    assert len(router.creates) == 1
    line = [l for l in _logged(capsys) if l.get("msg") == "router shadow"][0]
    assert line["pre_rule"] == "health_safety" and line["haiku_probe"] is True
    assert line["route"] == "escalate" and line["haiku_health_escalate"] is False
    assert line["disagree_write"] is False


def test_haiku_health_category_escalates_without_a_keyword(shadow_client, capsys) -> None:
    sc, make, _ = shadow_client
    make(_sonnet_text(), [_haiku_answer(category="health")])
    sc.post("/api/chat", json=_payload("my left thing feels odd after intervals"), headers=auth_headers())
    join_shadow_threads()
    line = [l for l in _logged(capsys) if l.get("msg") == "router shadow"][0]
    assert line["pre_rule"] is None
    assert line["haiku_route"] == "escalate" and line["haiku_health_escalate"] is True


def test_haiku_failure_never_reaches_the_athlete(shadow_client, client, fake_claude_chat_factory, capsys) -> None:
    sc, make, _ = shadow_client
    baseline_chat = fake_claude_chat_factory(_sonnet_text())
    baseline = client.post("/api/chat", json=_payload(), headers=auth_headers()).text
    capsys.readouterr()
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    make(_sonnet_text(), [anthropic.APIConnectionError(request=req)])
    r = sc.post("/api/chat", json=_payload(), headers=auth_headers())
    join_shadow_threads()
    assert r.status_code == 200 and r.text == baseline
    logged = _logged(capsys)
    assert any(l.get("msg") == "router shadow triage failed" and l.get("stack") for l in logged)
    line = [l for l in logged if l.get("msg") == "router shadow"][0]
    assert line["status"] == "error" and line["route"] is None


def test_no_log_line_contains_message_or_reply_text(shadow_client, capsys) -> None:
    sc, make, _ = shadow_client
    make(_sonnet_text("Tomorrow is an easy swim."), [_haiku_answer()])
    sc.post("/api/chat", json=_payload(), headers=auth_headers())
    join_shadow_threads()
    out = capsys.readouterr()
    for stream in (out.out, out.err):
        assert SENTINEL not in stream
        assert "HAIKU-REPLY-SENTINEL" not in stream
        assert "Tomorrow is an easy swim" not in stream


def test_model_cost_and_shape_fields_on_sonnet_lines(shadow_client, capsys) -> None:
    sc, make, app = shadow_client
    make(_sonnet_text(), [_haiku_answer()])
    sc.post("/api/chat", json=_payload(), headers=auth_headers())
    join_shadow_threads()
    logged = _logged(capsys)
    turn = [l for l in logged if l.get("msg") == "claude turn complete"][0]
    assert turn["model"] == app.state.settings.claude_model
    assert turn["est_cost_usd"] > 0 and turn["prompt_tokens_total"] == 100 and turn["over_100k"] is False
    assert turn["tools_called"] == [] and turn["write_tool_called"] is False
    shape = [l for l in logged if l.get("msg") == "coach request shape"][0]
    assert shape["request_id"] == turn["request_id"]
    assert len(shape["system_block_chars"]) >= 2 and all(isinstance(n, int) for n in shape["system_block_chars"])
    assert shape["history_turns"] == 0 and shape["tool_count"] > 10
    assert shape["cache_ttl_system"] and shape["cache_ttl_context"]
    assert shape["routed_files"] and all(f.endswith(".md") for f in shape["routed_files"])
    assert shape["athlete"] == "renee" and shape["router_pre_rule"] is None


def test_unknown_sonnet_model_logs_null_cost_not_a_crash(monkeypatch, client, fake_claude_chat_factory, capsys) -> None:
    chat = fake_claude_chat_factory(_sonnet_text())
    object.__setattr__(chat.settings, "claude_model", "claude-mystery-9")
    r = client.post("/api/chat", json=_payload(), headers=auth_headers())
    assert r.status_code == 200
    turn = [l for l in _logged(capsys) if l.get("msg") == "claude turn complete"][0]
    assert turn["model"] == "claude-mystery-9" and turn["est_cost_usd"] is None


def test_capture_stores_both_replies_for_listed_athletes_only(shadow_client, app_env) -> None:
    sc, make, app = shadow_client
    make(_sonnet_text("Sonnet says easy swim."), [_haiku_answer()])
    sc.post("/api/chat", json=_payload(), headers=auth_headers())
    join_shadow_threads()
    captures = FileStore(base_dir=app.state.settings.athletes_dir).list_router_captures("renee")
    assert len(captures) == 1
    c = captures[0]
    assert c.haiku_reply == HAIKU_REPLY and c.sonnet_reply == "Sonnet says easy swim."
    assert SENTINEL in c.question
    assert c.decision["route"] == "answer" and c.decision["pre_rule"] is None

    app.state.settings.router_capture_athletes.__class__  # frozenset: swap to exclude renee
    object.__setattr__(app.state.settings, "router_capture_athletes", frozenset({"someone-else"}))
    make(_sonnet_text(), [_haiku_answer()])
    sc.post("/api/chat", json=_payload(), headers=auth_headers())
    join_shadow_threads()
    assert len(FileStore(base_dir=app.state.settings.athletes_dir).list_router_captures("renee")) == 1


def test_capture_write_failure_is_swallowed(shadow_client, monkeypatch, capsys) -> None:
    sc, make, app = shadow_client
    monkeypatch.setattr(FileStore, "save_router_capture", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    make(_sonnet_text(), [_haiku_answer()])
    r = sc.post("/api/chat", json=_payload(), headers=auth_headers())
    join_shadow_threads()
    assert r.status_code == 200
    assert any(l.get("msg") == "router capture failed" for l in _logged(capsys))


def test_context_markers_match_what_the_renderers_emit() -> None:
    import inspect

    from app import drafts

    assert PENDING_DRAFTS_MARKER in inspect.getsource(drafts.render_pending_drafts)


def test_recent_session_days_shrinks_only_the_sessions_list(athletes_dir) -> None:
    from app.context import build_per_request_context_and_sizes as build

    store = FileStore(base_dir=athletes_dir)
    full = build(store, "renee", expert_mode=False)[0]
    short = build(store, "renee", expert_mode=False, recent_session_days=7)[0]
    assert "(last 28 days)" in full and "(last 7 days)" in short
    assert len(short) <= len(full)
