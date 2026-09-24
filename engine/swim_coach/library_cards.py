"""Review-card sidecar schema for `library/*.md` topic files.

Cards live at `library/review-cards/<topic-stem>.yaml`, NOT inside the
topic file itself -- topic files are routed into the chat model's context
(`backend/app/context.py`), and every word added there costs tokens on
every relevant request. A card is a small, human-authored abstract of one
`##` section: `section` (a slug), `heading` (verbatim), `summary` (what the
section says, <= `MAX_SUMMARY_WORDS`), `recommendation` (what the coach
will actually tell/do an athlete because of it, <= `MAX_RECOMMENDATION_WORDS`
-- `"none -- background only"` is a valid recommendation), and
`content_hash` (a hash of the section's own text at card-authoring time,
used to detect drift -- see `is_stale`).

Everything else a reviewer needs -- confidence, evidence tags, source
count/verification markers, review status, dossier link -- is DERIVED at
request time from `library_review.scan_file`/`scan_library`, never
hand-typed onto a card. See `docs/library-review.md` for the full
authoring/review workflow this module supports.

Granularity: one card per `##` (level-2) heading. A nested `###`
subsection stays folded into its parent `##` section's single card --
`topic_sections` never returns a level-3 span of its own.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, field_validator

from swim_coach.library_review import HEADING_RE, slugify

CARD_SCHEMA_VERSION = 1
MAX_SUMMARY_WORDS = 35
MAX_RECOMMENDATION_WORDS = 35

CARDS_DIRNAME = "review-cards"

# Topic files excluded from card coverage:
#   - meta files (00-conventions.md, INDEX.md, reference_list.md): no
#     reviewable claims of their own -- same exclusion `library_review`
#     already applies via its own META_FILES set, plus 00-conventions.md
#     (which library_review does NOT exclude, since it can carry a stray
#     UNREVIEWED mention, but which is pure scheme documentation, not
#     claims to card).
#   - sample_*.md: raw pool-coach workout samples, reference material for
#     the coach-text parser, not research content.
#   - researched-*.md: raw sourced-workout reference lists, same category
#     as the samples above -- not periodization/physiology claims.
EXCLUDED_FROM_CARDS = frozenset(
    {
        "00-conventions.md",
        "INDEX.md",
        "reference_list.md",
        "sample_pool_workout_traditional.md",
        "sample_pool_workout_openwater_focus.md",
        "researched-masters-pool-workouts.md",
        "researched-masters-openwater-workouts.md",
    }
)


class ReviewCardEntry(BaseModel):
    section: str
    heading: str
    summary: str
    recommendation: str
    content_hash: str

    @field_validator("summary")
    @classmethod
    def _summary_word_limit(cls, value: str) -> str:
        if len(value.split()) > MAX_SUMMARY_WORDS:
            raise ValueError(f"summary exceeds {MAX_SUMMARY_WORDS} words")
        return value

    @field_validator("recommendation")
    @classmethod
    def _recommendation_word_limit(cls, value: str) -> str:
        if len(value.split()) > MAX_RECOMMENDATION_WORDS:
            raise ValueError(f"recommendation exceeds {MAX_RECOMMENDATION_WORDS} words")
        return value


class ReviewCardFile(BaseModel):
    schema_version: int
    file: str
    cards: list[ReviewCardEntry]


@dataclass(frozen=True)
class TopicSection:
    heading: str
    slug: str
    start: int  # offset of the heading line
    end: int  # offset of the next level-<=2 heading, or EOF
    body_start: int  # offset just past the heading line


def topic_sections(text: str) -> list[TopicSection]:
    """Every level-2 (`##`) section, in document order, its span extending
    to the next level-1-or-2 heading -- so a nested `###` subsection is
    absorbed into its parent's span, never split into its own section.
    Slugs use the same base-plus-ordinal-suffix scheme as
    `library_review._assign_ids` (`slugify`, then `-2`/`-3`... on a repeat),
    so a card's `section` id composes with a file name into the same
    `file#slug` shape `library_review.ReviewItem.id` uses."""
    top_level = [m for m in HEADING_RE.finditer(text) if len(m.group(1)) <= 2]
    out: list[TopicSection] = []
    counts: dict[str, int] = {}
    for i, m in enumerate(top_level):
        if len(m.group(1)) != 2:
            continue
        end = top_level[i + 1].start() if i + 1 < len(top_level) else len(text)
        heading = m.group(2).strip()
        base = slugify(heading)
        counts[base] = counts.get(base, 0) + 1
        n = counts[base]
        slug = base if n == 1 else f"{base}-{n}"
        out.append(
            TopicSection(heading=heading, slug=slug, start=m.start(), end=end, body_start=m.end())
        )
    return out


def section_text(text: str, section: TopicSection) -> str:
    """The section's own body text (heading line excluded), stripped --
    the exact string `content_hash` is computed over."""
    return text[section.body_start : section.end].strip()


def content_hash(text: str) -> str:
    """Deterministic hash of a section's stripped body text, used to detect
    when a card's summary/recommendation has drifted from the library edit
    that prompted it (`is_stale`)."""
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def is_stale(card: ReviewCardEntry, current_section_text: str) -> bool:
    return card.content_hash != content_hash(current_section_text)


def in_scope_topic_files(library_dir: Path) -> list[Path]:
    """Every `library/*.md` file that should carry review cards, sorted by
    name -- every topic file except `EXCLUDED_FROM_CARDS`."""
    return sorted(
        p for p in library_dir.glob("*.md") if p.name not in EXCLUDED_FROM_CARDS
    )


def card_path_for(library_dir: Path, topic_filename: str) -> Path:
    """`library/review-cards/<stem>.yaml` for a topic file named
    `<stem>.md`."""
    stem = topic_filename[:-3] if topic_filename.endswith(".md") else topic_filename
    return library_dir / CARDS_DIRNAME / f"{stem}.yaml"


def load_card_file(path: Path) -> ReviewCardFile:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ReviewCardFile.model_validate(data)
