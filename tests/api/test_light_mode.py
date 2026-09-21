"""Light mode (IDEA 022 step 5): cheap conversational turns with no tools, no
library and a trimmed context, plus a `need_more` escape hatch that re-runs the
same question in full mode. Flag-gated (COACH_LIGHT_MODE, default off)."""

from __future__ import annotations

import dataclasses
import json
from datetime import date, timedelta

import pytest
from swim_coach.store import FileStore

from app.claude import ClaudeChat
from app.config import Settings
from app.light_mode import (
    LIGHT_TOOLS,
    NEED_MORE_TOOL_NAME,
    build_light_context,
    build_light_messages,
    build_light_system,
    is_light_turn,
)
from fakes import (
    FakeAnthropicClient,
    auth_headers,
    make_event,
    make_final_message,
    make_text_block,
    make_tool_use_block,
    make_workout,
)


@pytest.mark.parametrize(
    "message",
    [
        "hey coach, finished my race today",
        "hi",
        "Thanks!",
        "just got back from the pool",
        "good morning coach",
        "it was a tough one but I felt strong at the end",
    ],
)
def test_conversational_messages_are_light(message) -> None:
    assert is_light_turn(message, history_len=0) is True


@pytest.mark.parametrize(
    "message",
    [
        "what pace should I swim the long swim at",          # topic keyword
        "how should I fuel a 4 hour ride",                    # topic keyword
        "review my race and tell me how I paced it",          # analysis
        "how did I do on the second lap",                     # needs data
        "can you move tomorrow's session to Friday",          # plan change
        "my shoulder hurts when I breathe",                   # health
        "I felt chest tightness on the hill",                 # acute safety
        "please log my ride from this morning",               # action
        "should I taper earlier",                             # advice
    ],
)
def test_topic_health_data_and_action_messages_are_not_light(message) -> None:
    assert is_light_turn(message, history_len=0) is False


def test_long_messages_long_histories_focus_and_expert_mode_are_never_light() -> None:
    assert is_light_turn("hi " * 200, history_len=0) is False
    assert is_light_turn("hi", history_len=20) is False
    assert is_light_turn("hi", history_len=0, focused=True) is False
    assert is_light_turn("hi", history_len=0, expert_mode=True) is False


def test_light_tools_are_only_need_more() -> None:
    assert [t["name"] for t in LIGHT_TOOLS] == [NEED_MORE_TOOL_NAME]


def test_light_system_is_one_small_stable_block() -> None:
    system = build_light_system()
    assert len(system) == 1
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    assert len(system[0]["text"]) < 6000
    assert NEED_MORE_TOOL_NAME in system[0]["text"]
    assert build_light_system() == system  # byte-stable


def test_light_context_has_today_events_and_recent_sessions_but_no_plan(app_env) -> None:
    store = FileStore(base_dir=app_env)
    today = date.today()
    store.save_events("renee", [make_event(name="Big Race", event_date=today + timedelta(days=10), distance_m=10000)])
    store.save_workout("renee", make_workout(date=today - timedelta(days=1), sport="bike"))
    store.save_workout("renee", make_workout(date=today - timedelta(days=20), sport="bike"))

    text = build_light_context(store, "renee")

    assert today.isoformat() in text
    assert "Big Race" in text
    assert text.count('"sport": "bike"') == 1  # last 7 days only
    assert "### Profile" not in text and "week_plan" not in text.lower()


def test_light_messages_keep_history_verbatim_and_context_on_the_newest_message(app_env) -> None:
    store = FileStore(base_dir=app_env)
    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello!"}]
    messages = build_light_messages(store, "renee", message="finished my race", history=history)
    assert messages[0] == {"role": "user", "content": "hi"}
    assert messages[-1]["content"].endswith("finished my race")
    assert "## Light athlete context" in messages[-1]["content"]


def _settings(**overrides) -> Settings:
    base = dict(
        anthropic_api_key="sk-ant-test", api_token_hash="x" * 64, claude_model="claude-sonnet-5",
        claude_thinking="adaptive", allowed_origins=["https://ashaber.github.io"], athletes_dir=None,
        library_dir=None, research_dir=None, port=8000, chat_rate_per_min=20, store_backend="file",
        database_url=None, google_client_id="test.apps.googleusercontent.com", session_ttl_days=30,
        chat_daily_cap_per_athlete=50,
    )
    base.update(overrides)
    return Settings(**base)


def test_need_more_reruns_the_question_in_full_mode() -> None:
    need_more = make_tool_use_block("t1", NEED_MORE_TOOL_NAME, {"reason": "needs plan data"})
    turns = [
        ([], make_final_message([need_more], "tool_use")),
        (["full answer"], make_final_message([make_text_block("full answer")], "end_turn")),
    ]
    client = FakeAnthropicClient(turns)
    chat = ClaudeChat(_settings(), client=client)
    full = (
        [{"type": "text", "text": "FULL SYSTEM"}],
        [{"role": "user", "content": "FULL MESSAGE"}],
        [{"name": "get_workouts"}],
        {"get_workouts": lambda _i: {}},
    )

    events = list(
        chat.run_streaming(
            build_light_system(),
            [{"role": "user", "content": "light message"}],
            LIGHT_TOOLS,
            {},
            escalate=lambda: full,
        )
    )

    light_call, full_call = client.messages.calls
    assert [t["name"] for t in light_call["tools"]] == [NEED_MORE_TOOL_NAME]
    assert full_call["system"] == full[0]
    assert full_call["tools"] == full[2]
    assert "FULL MESSAGE" in json.dumps(full_call["messages"])
    assert not any(NEED_MORE_TOOL_NAME in json.dumps(m) for m in full_call["messages"])  # never replayed
    assert any("full answer" in e for e in events)
    assert '"type": "done"' in events[-1]


def test_need_more_without_an_escalation_path_does_not_loop_forever() -> None:
    need_more = make_tool_use_block("t1", NEED_MORE_TOOL_NAME, {"reason": "x"})
    turns = [([], make_final_message([need_more], "tool_use")) for _ in range(6)]
    chat = ClaudeChat(_settings(), client=FakeAnthropicClient(turns))
    events = list(chat.run_streaming([], [{"role": "user", "content": "x"}], LIGHT_TOOLS, {}))
    assert events  # terminates via the normal iteration guard, no crash


def test_escalation_is_single_shot() -> None:
    need_more = make_tool_use_block("t1", NEED_MORE_TOOL_NAME, {"reason": "x"})
    turns = [([], make_final_message([need_more], "tool_use")) for _ in range(6)]
    client = FakeAnthropicClient(turns)
    chat = ClaudeChat(_settings(), client=client)
    calls = {"n": 0}

    def escalate():
        calls["n"] += 1
        return ([], [{"role": "user", "content": "F"}], [{"name": "x"}], {})

    list(chat.run_streaming([], [{"role": "user", "content": "x"}], LIGHT_TOOLS, {}, escalate=escalate))
    assert calls["n"] == 1


# --- route wiring -------------------------------------------------------------


def _enable(app) -> None:
    app.state.settings = dataclasses.replace(app.state.settings, light_mode=True)


def test_flag_off_light_looking_message_still_gets_full_mode(client, fake_claude_chat_factory) -> None:
    chat = fake_claude_chat_factory([(["ok"], make_final_message([make_text_block("ok")], "end_turn"))])
    r = client.post(
        "/api/chat",
        json={"message": "hey coach, finished my race today", "history": [], "athlete": "renee", "expert_mode": False},
        headers=auth_headers(),
    )
    assert r.status_code == 200
    assert len(chat.client.messages.calls[0]["tools"]) > 5


def test_flag_on_light_message_uses_light_request(app, client, fake_claude_chat_factory) -> None:
    _enable(app)
    chat = fake_claude_chat_factory([(["nice"], make_final_message([make_text_block("nice")], "end_turn"))])
    r = client.post(
        "/api/chat",
        json={"message": "hey coach, finished my race today", "history": [], "athlete": "renee", "expert_mode": False},
        headers=auth_headers(),
    )
    assert r.status_code == 200
    call = chat.client.messages.calls[0]
    assert [t["name"] for t in call["tools"]] == [NEED_MORE_TOOL_NAME]
    assert len(json.dumps(call["system"])) < 8000


def test_flag_on_non_light_message_uses_full_request(app, client, fake_claude_chat_factory) -> None:
    _enable(app)
    chat = fake_claude_chat_factory([(["ok"], make_final_message([make_text_block("ok")], "end_turn"))])
    r = client.post(
        "/api/chat",
        json={"message": "what pace should I swim at", "history": [], "athlete": "renee", "expert_mode": False},
        headers=auth_headers(),
    )
    assert r.status_code == 200
    assert len(chat.client.messages.calls[0]["tools"]) > 5


def test_flag_on_need_more_escalates_through_the_route(app, client, fake_claude_chat_factory) -> None:
    _enable(app)
    need_more = make_tool_use_block("t1", NEED_MORE_TOOL_NAME, {"reason": "wants data"})
    chat = fake_claude_chat_factory(
        [
            ([], make_final_message([need_more], "tool_use")),
            (["full"], make_final_message([make_text_block("full")], "end_turn")),
        ]
    )
    r = client.post(
        "/api/chat",
        json={"message": "hey coach, finished my race today", "history": [], "athlete": "renee", "expert_mode": False},
        headers=auth_headers(),
    )
    assert r.status_code == 200
    light_call, full_call = chat.client.messages.calls
    assert len(light_call["tools"]) == 1
    assert len(full_call["tools"]) > 5
    assert "finished my race today" in json.dumps(full_call["messages"])
    assert "full" in r.text
