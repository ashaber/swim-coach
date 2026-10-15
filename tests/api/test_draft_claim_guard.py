"""False draft-claim guard: a reply that says "draft is clean, no planning
warnings" with no plan draft/write tool called in the turn gets a warning.

Real incident, prod 2026-10-15: the coach described a drafted plan change and a
clean check in a turn with ZERO tool calls."""

from __future__ import annotations

import json

import pytest

from app.save_claims import UNVERIFIED_DRAFT_NOTICE, claims_a_draft
from test_save_claim_guard import _run
from fakes import make_tool_use_block


@pytest.mark.parametrize(
    "text",
    [
        "Draft is clean, no planning warnings.",
        "The draft looks good: Saturday gets the long swim.",
        "I've drafted the change to Thursday.",
        "No planning warnings on this one.",
        "Confirm and I'll persist it.",
        "Say the word and I'll save it.",
    ],
)
def test_claims_a_draft_positive(text: str) -> None:
    assert claims_a_draft(text)


@pytest.mark.parametrize(
    "text",
    [
        "Want me to draft a change to Thursday?",
        "I can draft that if you like.",
        "I haven't drafted anything yet.",
        "Is the draft ready for you to review?",
        "Here is the plan for Thursday: 60 min easy bike.",
        "Once the draft is clean I will persist it.",
        "That wasn't drafted.",
        "",
    ],
)
def test_claims_a_draft_negative(text: str) -> None:
    assert not claims_a_draft(text)


def _warns(capsys):
    out = [json.loads(l) for l in capsys.readouterr().out.splitlines() if l.startswith("{")]
    return [o for o in out if o.get("msg") == "unverified_draft_claim"]


def test_no_tool_call_but_claims_draft_appends_notice_and_warns(capsys) -> None:
    text, events = _run([(None, "Draft is clean, no planning warnings.")], {})
    assert UNVERIFIED_DRAFT_NOTICE in text
    assert events[-1]["type"] == "done"
    assert len(_warns(capsys)) == 1


def test_turn_that_drafted_gets_no_notice(capsys) -> None:
    tu = make_tool_use_block("t1", "patch_week_plan", {})
    text, _ = _run(
        [(tu, None), (None, "Draft is clean, no planning warnings.")],
        {"patch_week_plan": lambda _i: {"persisted": False}},
    )
    assert UNVERIFIED_DRAFT_NOTICE not in text
    assert _warns(capsys) == []


def test_hedged_text_gets_no_notice(capsys) -> None:
    text, _ = _run([(None, "Want me to draft that?")], {})
    assert UNVERIFIED_DRAFT_NOTICE not in text
    assert _warns(capsys) == []
