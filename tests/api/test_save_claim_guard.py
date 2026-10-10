"""False save-claim guard: a reply that says "persisted"/"locked in" with no
successful persisting write in the same turn gets a visible warning appended.

Real incident, prod 2026-10-10 (athlete andrew, W41): "Persisted and verified
-- Option 2 is locked in" in a turn with NO tool call."""

from __future__ import annotations

import json

import pytest

from app.claude import ClaudeChat
from app.save_claims import UNVERIFIED_SAVE_NOTICE, claims_a_save, write_succeeded
from test_claude import _settings
from fakes import FakeAnthropicClient, make_final_message, make_text_block, make_tool_use_block


@pytest.mark.parametrize(
    "text",
    [
        "Persisted and verified -- Option 2 is locked in.",
        "Done. I've saved the new long swim to your plan.",
        "That change is now on your plan for W41.",
        "I updated your plan with the new bike session.",
        "Written to the week file.",
    ],
)
def test_claims_a_save_positive(text: str) -> None:
    assert claims_a_save(text)


@pytest.mark.parametrize(
    "text",
    [
        "Not persisted yet -- say the word.",
        "Nothing's written yet; here is the draft.",
        "Confirm and I'll persist it.",
        "This is a draft only, nothing saved.",
        "Want me to save this?",
        "Your saved notes say you prefer mornings.",
        "If you like it I will lock it in.",
        "Here is the plan for Thursday: 60 min easy bike.",
        "",
    ],
)
def test_claims_a_save_negative(text: str) -> None:
    assert not claims_a_save(text)


def test_write_succeeded_shapes() -> None:
    assert write_succeeded("patch_week_plan", {"persisted": True})
    assert not write_succeeded("patch_week_plan", {"persisted": False})
    assert not write_succeeded("patch_week_plan", {"persisted": True, "error": "x"})
    assert write_succeeded("save_athlete_note", {"saved": True})
    assert write_succeeded("record_threshold_test", {"logged": True})
    assert write_succeeded("update_athlete_profile", {"updated": True, "ftp_watts": 250})
    assert not write_succeeded("update_athlete_profile", {"updated": False})
    assert not write_succeeded("get_week_plan", {"persisted": True})  # not a write tool
    assert not write_succeeded("patch_week_plan", "oops")


def _run(texts_and_tools, handlers):
    steps = []
    for tool_use, text in texts_and_tools:
        if tool_use is not None:
            steps.append(([], make_final_message([tool_use], "tool_use")))
        else:
            steps.append(([text], make_final_message([make_text_block(text)], "end_turn")))
    chat = ClaudeChat(_settings(), client=FakeAnthropicClient(steps))
    events = list(chat._run_turns([], [{"role": "user", "content": "x"}], [{"name": n} for n in handlers], handlers))
    text = "".join(e["text"] for e in events if e["type"] == "text")
    return text, events


def _warns(capsys):
    out = [json.loads(l) for l in capsys.readouterr().out.splitlines() if l.startswith("{")]
    return [o for o in out if o.get("msg") == "unverified_save_claim"]


def test_no_tool_call_but_claims_save_appends_notice_and_warns(capsys) -> None:
    text, events = _run([(None, "Persisted and verified -- Option 2 is locked in.")], {})
    assert UNVERIFIED_SAVE_NOTICE in text
    assert events[-1]["type"] == "done"
    assert len(_warns(capsys)) == 1


def test_turn_that_persisted_gets_no_notice(capsys) -> None:
    tu = make_tool_use_block("t1", "patch_week_plan", {})
    text, _ = _run(
        [(tu, None), (None, "Persisted -- Option 2 is locked in.")],
        {"patch_week_plan": lambda _i: {"persisted": True}},
    )
    assert UNVERIFIED_SAVE_NOTICE not in text
    assert _warns(capsys) == []


def test_draft_only_tool_result_does_not_count_as_a_write(capsys) -> None:
    tu = make_tool_use_block("t1", "patch_week_plan", {})
    text, _ = _run(
        [(tu, None), (None, "Option 2 is locked in.")],
        {"patch_week_plan": lambda _i: {"persisted": False}},
    )
    assert UNVERIFIED_SAVE_NOTICE in text
    warns = _warns(capsys)
    assert warns and warns[0]["tools_invoked"] == ["patch_week_plan"]


def test_hedged_text_gets_no_notice(capsys) -> None:
    text, _ = _run([(None, "Nothing's written yet -- confirm and I'll persist it.")], {})
    assert UNVERIFIED_SAVE_NOTICE not in text
    assert _warns(capsys) == []


def test_persona_tells_the_coach_never_to_claim_an_unmade_save() -> None:
    from app.context import PERSONA_AND_RULES

    assert "Never claim a save you did not make" in PERSONA_AND_RULES
    assert "persisted: true" in PERSONA_AND_RULES
