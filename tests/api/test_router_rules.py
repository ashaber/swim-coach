"""Deterministic pre-rules for the Haiku coach router: pure functions, no engine, no network.

A match forces Sonnet and skips the Haiku call. The table is data (PRE_RULES) so these tests also
guard the table's shape. Sources of the cases: IDEAS.md IDEA 022 "PR #215 review conclusions"
(confirmations routed light; health keyword holes) plus the repo's pain -> stop-and-assess rail.
"""

from __future__ import annotations

import pytest

from app.router_rules import (
    CATEGORY_CONFIRMATION,
    CATEGORY_HEALTH,
    CATEGORY_LARGE_ANALYSIS,
    CATEGORY_WRITE_INTENT,
    PRE_RULES,
    match_pre_rule,
)

PROPOSAL = [
    {"role": "user", "content": "can we make Thursday easier?"},
    {"role": "assistant", "content": "Want me to move Thursday's tempo to Friday?"},
]


def category(message: str, *, history=None, pending=False, active_health=False, sports=None) -> str | None:
    hit = match_pre_rule(
        message, history=history or [], has_pending_draft=pending, has_active_health_status=active_health,
        sports=sports,
    )
    return hit.category if hit else None


def test_rules_are_a_table_of_categorised_patterns() -> None:
    assert len(PRE_RULES) >= 8
    ids = [r.id for r in PRE_RULES]
    assert len(ids) == len(set(ids)), "rule ids must be unique (they are logged)"
    assert {r.category for r in PRE_RULES} == {
        CATEGORY_CONFIRMATION,
        CATEGORY_HEALTH,
        CATEGORY_WRITE_INTENT,
        CATEGORY_LARGE_ANALYSIS,
    }


def test_pending_draft_forces_sonnet_for_any_message() -> None:
    assert category("hello!", pending=True) == CATEGORY_CONFIRMATION
    assert category("thanks", pending=True) == CATEGORY_CONFIRMATION


def test_active_health_status_forces_sonnet() -> None:
    assert category("what's my week look like?", active_health=True) == CATEGORY_HEALTH


@pytest.mark.parametrize(
    "message",
    [
        "yes",
        "Yes!",
        "ok do it",
        "sounds good",
        "sounds good, thanks",
        "go ahead",
        "yes, go ahead",
        "yep please do",
        "no",
        "no, leave it",
        "cancel that",
        "never mind",
    ],
)
def test_short_affirmations_or_declines_after_an_assistant_turn_force_sonnet(message: str) -> None:
    assert category(message, history=PROPOSAL) == CATEGORY_CONFIRMATION


def test_affirmation_without_any_history_is_not_a_confirmation() -> None:
    assert category("ok", history=[]) is None


def test_long_message_starting_with_yes_is_not_a_bare_affirmation() -> None:
    long_yes = "yes I did that swim and honestly the whole week felt a bit different from what I expected overall"
    assert category(long_yes, history=PROPOSAL) is None


@pytest.mark.parametrize(
    "message",
    [
        "my shoulder hurts when I breathe to the left",
        "I have a sore knee",
        "feeling a bit of pain in my hip",
        "I think I tweaked my back",
        "I blacked out on the climb",  # PR #215 hole: only routed full by accident
        "coming down with something",  # PR #215 hole
        "I have a headache",  # PR #215 hole
        "scratchy throat since this morning",  # PR #215 hole
        "I'm sick",
        "got a cold and a fever",
        "feeling dizzy after the swim",
        "my chest felt tight",
        "heart racing at rest",
        "tingling in my fingers",
        "doctor said rest",
        "physio says no running",
        "on antibiotics this week",
        "I've got a niggle in my achilles",
        "felt nauseous",
    ],
)
def test_health_and_safety_language_forces_sonnet(message: str) -> None:
    assert category(message) == CATEGORY_HEALTH


@pytest.mark.parametrize(
    "message",
    [
        "create a plan for next week",
        "build me a new week",
        "move Tuesday's ride to Wednesday",
        "swap my long swim and the strength day",
        "change Thursday's session to an easy swim",
        "push this workout to my Garmin",
        "push it to intervals",
        "save this as a note",
        "log my swim from this morning",
        "log today's ride",
        "update my FTP to 280",
        "reschedule the tempo session",
        "add a recovery swim on Friday",
        "remove Saturday's ride",
    ],
)
def test_explicit_write_or_plan_intent_forces_sonnet(message: str) -> None:
    assert category(message) == CATEGORY_WRITE_INTENT


@pytest.mark.parametrize(
    "message",
    [
        "why did I fade in the last lap?",
        "can you debrief my race",
        "race analysis please",
        "analyze my pacing on Sunday",
        "plan my season",
        "help me with macro planning for the spring",
        "how should I structure the taper",
        "how did the race go compared to last year",
    ],
)
def test_large_analysis_forces_sonnet(message: str) -> None:
    assert category(message) == CATEGORY_LARGE_ANALYSIS


@pytest.mark.parametrize(
    "message",
    [
        "hello",
        "hi coach!",
        "thanks, that helps",
        "thank you",
        "what is on my plan tomorrow?",
        "what pace is CSS for me?",
        "how far was my long swim last week?",
        "is cold water swimming good for recovery?",  # 'cold' alone is not illness language
        "what should I eat before a long ride?",
        "good morning",
    ],
)
def test_ordinary_questions_do_not_match(message: str) -> None:
    assert category(message, history=PROPOSAL) is None


def test_health_wins_over_write_intent() -> None:
    hit = match_pre_rule(
        "move my swim, my shoulder hurts",
        history=[],
        has_pending_draft=False,
        has_active_health_status=False,
    )
    assert hit is not None and hit.category == CATEGORY_HEALTH


def test_hit_names_the_rule_but_never_echoes_the_message() -> None:
    hit = match_pre_rule(
        "my knee hurts", history=[], has_pending_draft=False, has_active_health_status=False
    )
    assert hit is not None
    assert hit.rule_id in {r.id for r in PRE_RULES}
    assert "knee" not in repr(hit).lower()


def test_sport_specific_health_terms_apply_by_athlete_sport() -> None:
    assert category("I had a crash on the descent", sports=["bike"]) == CATEGORY_HEALTH
    assert category("I had a crash on the descent", sports=["swim_pool"]) is None
    assert category("got stung by a jellyfish", sports=["swim_ow"]) == CATEGORY_HEALTH


def test_known_slang_does_not_force_sonnet_but_real_reports_still_do() -> None:
    assert category("I was in the pain cave all day") is None
    assert category("pain cave, and now my knee hurts") == CATEGORY_HEALTH
