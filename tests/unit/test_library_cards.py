"""Tests for `swim_coach.library_cards` -- the review-card sidecar schema
and its derivation helpers (`docs/library-review.md` describes the full
authoring/review workflow).

Cards live at `library/review-cards/<topic-stem>.yaml`, one entry per `##`
section of a topic file, NOT inside the topic file itself (topic files are
routed into the chat model's context; every added word costs tokens on
every relevant request -- see that module's docstring). Everything besides
`section`/`heading`/`summary`/`recommendation`/`content_hash` is derived at
request time from `library_review` (confidence, tags, review status,
staleness) -- never hand-typed onto a card.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from swim_coach.library_cards import (
    CARD_SCHEMA_VERSION,
    EXCLUDED_FROM_CARDS,
    MAX_RECOMMENDATION_WORDS,
    MAX_SUMMARY_WORDS,
    ReviewCardEntry,
    ReviewCardFile,
    card_path_for,
    content_hash,
    in_scope_topic_files,
    is_stale,
    load_card_file,
    section_text,
    topic_sections,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
LIBRARY_DIR = REPO_ROOT / "library"
CARDS_DIR = LIBRARY_DIR / "review-cards"

# --- fixtures ----------------------------------------------------------------

TWO_SECTION_FILE = """# A topic file

Intro paragraph, not a section of its own -- no card for this.

## First section

Some claim text. `[EVIDENCE: swim]` Confidence: high.

## Second section

More prose here, with a nested subsection below.

### A nested subsection

This stays folded into "Second section"'s card -- no separate card for an
`###` heading.
"""

REPEATED_HEADING_FILE = """# T

## Open questions

- a.

## Open questions
"""


# --- topic_sections ------------------------------------------------------------


def test_topic_sections_finds_only_level_2_headings():
    sections = topic_sections(TWO_SECTION_FILE)
    assert [s.heading for s in sections] == ["First section", "Second section"]


def test_topic_sections_absorbs_nested_h3_into_the_h2_span():
    sections = topic_sections(TWO_SECTION_FILE)
    second = sections[1]
    text = section_text(TWO_SECTION_FILE, second)
    assert "A nested subsection" in text
    assert "stays folded" in text


def test_topic_sections_slug_matches_library_review_slugify():
    from swim_coach.library_review import slugify

    sections = topic_sections(TWO_SECTION_FILE)
    assert sections[0].slug == slugify("First section")


def test_topic_sections_ordinal_suffix_on_repeated_heading():
    sections = topic_sections(REPEATED_HEADING_FILE)
    slugs = [s.slug for s in sections]
    assert slugs == ["open-questions", "open-questions-2"]


# --- content_hash / is_stale ----------------------------------------------------


def test_content_hash_stable_for_same_text():
    assert content_hash("some text") == content_hash("some text")


def test_content_hash_changes_when_text_changes():
    assert content_hash("some text") != content_hash("some other text")


def test_is_stale_true_when_section_text_changed():
    card = ReviewCardEntry(
        section="first-section",
        heading="First section",
        summary="A short summary.",
        recommendation="A short recommendation.",
        content_hash=content_hash("original section text"),
    )
    assert is_stale(card, "original section text") is False
    assert is_stale(card, "edited section text") is True


# --- ReviewCardEntry / ReviewCardFile schema validation --------------------------


def test_review_card_entry_rejects_summary_over_word_limit():
    long_summary = " ".join(["word"] * (MAX_SUMMARY_WORDS + 1))
    with pytest.raises(ValidationError):
        ReviewCardEntry(
            section="s",
            heading="S",
            summary=long_summary,
            recommendation="fine",
            content_hash="deadbeef",
        )


def test_review_card_entry_rejects_recommendation_over_word_limit():
    long_rec = " ".join(["word"] * (MAX_RECOMMENDATION_WORDS + 1))
    with pytest.raises(ValidationError):
        ReviewCardEntry(
            section="s",
            heading="S",
            summary="fine",
            recommendation=long_rec,
            content_hash="deadbeef",
        )


def test_review_card_entry_allows_exactly_the_word_limit():
    summary = " ".join(["word"] * MAX_SUMMARY_WORDS)
    rec = " ".join(["word"] * MAX_RECOMMENDATION_WORDS)
    card = ReviewCardEntry(
        section="s", heading="S", summary=summary, recommendation=rec, content_hash="deadbeef"
    )
    assert card.summary == summary


def test_review_card_entry_allows_none_background_only_recommendation():
    card = ReviewCardEntry(
        section="s",
        heading="S",
        summary="Background context only.",
        recommendation="none -- background only",
        content_hash="deadbeef",
    )
    assert card.recommendation == "none -- background only"


def test_review_card_file_round_trips_through_yaml(tmp_path):
    path = tmp_path / "sample.yaml"
    data = {
        "schema_version": CARD_SCHEMA_VERSION,
        "file": "sample-topic.md",
        "cards": [
            {
                "section": "first-section",
                "heading": "First section",
                "summary": "A faithful summary.",
                "recommendation": "A faithful recommendation.",
                "content_hash": "abc123",
            }
        ],
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    loaded = load_card_file(path)
    assert isinstance(loaded, ReviewCardFile)
    assert loaded.file == "sample-topic.md"
    assert loaded.cards[0].section == "first-section"


# --- card_path_for / in_scope_topic_files ---------------------------------------


def test_card_path_for_strips_md_extension(tmp_path):
    path = card_path_for(tmp_path, "07-strength-dryland.md")
    assert path == tmp_path / "review-cards" / "07-strength-dryland.yaml"


def test_in_scope_topic_files_excludes_meta_and_sample_and_researched_files(tmp_path):
    for name in [
        "00-conventions.md",
        "INDEX.md",
        "reference_list.md",
        "sample_pool_workout_traditional.md",
        "sample_pool_workout_openwater_focus.md",
        "researched-masters-pool-workouts.md",
        "researched-masters-openwater-workouts.md",
        "07-strength-dryland.md",
    ]:
        (tmp_path / name).write_text("# T\n\n## S\n\nbody\n", encoding="utf-8")
    in_scope = {p.name for p in in_scope_topic_files(tmp_path)}
    assert in_scope == {"07-strength-dryland.md"}


def test_excluded_from_cards_matches_module_constant(tmp_path):
    # Sanity: the exclusion set used by in_scope_topic_files is importable
    # and non-empty, so docs/library-review.md's own claim about what's
    # excluded stays checkable.
    assert "00-conventions.md" in EXCLUDED_FROM_CARDS
    assert "INDEX.md" in EXCLUDED_FROM_CARDS


# --- the real library: every in-scope section has a card ------------------------


def test_every_section_of_every_in_scope_topic_file_has_a_card():
    missing = []
    for topic_path in in_scope_topic_files(LIBRARY_DIR):
        card_path = card_path_for(LIBRARY_DIR, topic_path.name)
        if not card_path.exists():
            missing.append(f"{topic_path.name}: no card file at all")
            continue
        card_file = load_card_file(card_path)
        card_slugs = {c.section for c in card_file.cards}
        text = topic_path.read_text(encoding="utf-8")
        for section in topic_sections(text):
            if section.slug not in card_slugs:
                missing.append(f"{topic_path.name}#{section.slug}")
    assert not missing, f"sections missing a review card: {missing}"


def test_real_cards_stay_within_word_limits():
    # Redundant with per-entry pydantic validation, but a direct pin against
    # the real content so a future hand-edit that bypasses validation (e.g.
    # editing YAML directly without re-running through the loader) is still
    # caught by the test suite.
    over_limit = []
    for topic_path in in_scope_topic_files(LIBRARY_DIR):
        card_path = card_path_for(LIBRARY_DIR, topic_path.name)
        if not card_path.exists():
            continue
        card_file = load_card_file(card_path)
        for card in card_file.cards:
            if len(card.summary.split()) > MAX_SUMMARY_WORDS:
                over_limit.append(f"{topic_path.name}#{card.section} summary")
            if len(card.recommendation.split()) > MAX_RECOMMENDATION_WORDS:
                over_limit.append(f"{topic_path.name}#{card.section} recommendation")
    assert not over_limit, f"cards over word limit: {over_limit}"


def test_real_cards_content_hash_matches_current_section_text():
    # Every shipped card's hash must match the section text it describes --
    # a stale card would mean the card content wasn't updated alongside a
    # library edit, and this test exists to catch that at authoring time
    # (not just surface `stale: true` at read time).
    stale = []
    for topic_path in in_scope_topic_files(LIBRARY_DIR):
        card_path = card_path_for(LIBRARY_DIR, topic_path.name)
        if not card_path.exists():
            continue
        card_file = load_card_file(card_path)
        text = topic_path.read_text(encoding="utf-8")
        by_slug = {s.slug: s for s in topic_sections(text)}
        for card in card_file.cards:
            section = by_slug.get(card.section)
            if section is None:
                continue  # caught by the "missing card" test instead
            if is_stale(card, section_text(text, section)):
                stale.append(f"{topic_path.name}#{card.section}")
    assert not stale, f"cards whose content_hash is stale: {stale}"


def test_real_cards_file_field_matches_its_own_filename():
    mismatched = []
    for topic_path in in_scope_topic_files(LIBRARY_DIR):
        card_path = card_path_for(LIBRARY_DIR, topic_path.name)
        if not card_path.exists():
            continue
        card_file = load_card_file(card_path)
        if card_file.file != topic_path.name:
            mismatched.append((card_path.name, card_file.file, topic_path.name))
    assert not mismatched, f"card file field mismatches: {mismatched}"
