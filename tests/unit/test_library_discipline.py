"""CI gate enforcing library/ evidence discipline (see library/00-conventions.md).

Why this exists
----------------
The research library was originally poisoned by an AI research pass that
fabricated URLs and PubMed/PMC/DOI identifiers (see reference_list.md's
header and 00-conventions.md's "one rule that matters most" section for the
full account). The evidence-tagging discipline described in
00-conventions.md is currently enforced only by careful human/agent
prompting -- a convention, not an invariant. This module makes violations
mechanically unmergeable, which is the precondition for safely automating
library drafting (an agent that turns logged research questions into draft
library sections for human review).

Every check below is a small, pure function over text, exercised both
against the real library/ tree and against inline fixture strings (the
negative tests at the bottom of this file) so the gate is provably able to
bite, not just provably green today.

Scope definitions
------------------
- ``numbered_files()``: every ``library/[0-9][0-9]-*.md`` file that exists
  (currently 00, 03, 04, 05, 06, 07, 10). Literal reading of this project's
  "topic files" glob; includes ``00-conventions.md``.
- ``claim_topic_files()``: ``numbered_files()`` minus ``00-conventions.md``.
  ``00-conventions.md`` itself defines "topic file" as "``01-*.md`` through
  ``12-*.md``" in its own "## The evidence-tag scheme" section -- i.e. NOT
  including itself. Rules about claim-tagging (word count, ADAPTED
  completeness, tag values, confidence values, citation resolution) use
  this narrower scope both because it matches the spec's own definition and
  because 00-conventions.md's "## The evidence-tag scheme" section
  illustratively writes ``[ADAPTED: cycling|running|tri|general-endurance]``
  with a literal pipe character -- that's defining the *scheme*, not making
  a claim, and would be a false positive if scanned as a real tag instance.
- Rule 1 (fabricated identifiers / bare URLs) scans ``numbered_files()``
  (all of them, including ``00-conventions.md``) plus ``reference_list.md``.
  This is the literal scope given in the spec for this repo's CI gate task,
  and it needs 00-conventions.md in scope (with a targeted prose exemption
  for its own warning text -- see ``is_rule1_exempt``).
- ``library/research-dossiers/**`` is excluded from every rule in this
  module. It is raw, uncurated research input -- its own header explicitly
  says "this is the raw research input ... It is not itself a citable
  library file" -- and it deliberately still contains the original
  fabricated PMC ids as a provenance record of what NOT to reuse. It is
  never matched by the ``library/[0-9][0-9]-*.md`` glob anyway (its
  filenames are dated, e.g. ``2026-07-10-recovery.md``, which does not
  match ``[0-9][0-9]-*.md`` -- the third character is not a literal ``-``).

Citation-matching convention (rule 6)
--------------------------------------
Topic files cite sources almost exclusively as ``` `Author et al. (Year)` ```
or ``` `Author & Author (Year)` ``` (sometimes without backticks, e.g.
"Wakayoshi et al. (1992)"), immediately followed by a parenthesised
4-digit year. ``CITATION_RE`` matches that specific shape: one or more
capitalized name-like tokens (Unicode-aware, so "Rønnestad" and "Häkkinen"
match) joined by ", " / " & " / " and " / whitespace, optionally followed by
"et al.", immediately followed by "(YYYY)". A citation is considered
"resolved" if at least one candidate surname extracted from the matched
span appears verbatim in ``reference_list.md``.

This deliberately does NOT try to match every citation-shaped thing in the
library. Two patterns are excluded on purpose because they're too ambiguous
to match without a real risk of false positives/negatives:
  - Citations by quoted title with no attached year, e.g. "(`reference_list
    .md`, \"Sex differences in marathon pacing\")" (04-css-intensity-
    anchors.md) or organisation names like "Santa Barbara Channel Swimming
    Association" (06-long-swim-progression.md) -- there's no reliable
    "(YYYY)" anchor to key off, and title-matching against
    reference_list.md's prose would be far too fuzzy to trust.
  - Any other free-form mention of a source that doesn't end in "(YYYY)"
    immediately after a name-shaped token.
The task's own framing is the guide here: "a gate that reliably catches 80%
of fabrications and never cries wolf is far more valuable than a brittle
100% one that authors learn to ignore."

Known, already-reported content issues
----------------------------------------
This module's checks found a few genuine pre-existing issues in library/
content. Rather than silently "fixing" them (most require an editorial
judgment call this module can't make) or silently widening an allowlist to
paper over them, they were recorded explicitly in ``KNOWN_INVALID_TAGS`` and
``KNOWN_ADAPTED_MISSING_TEST`` below, with a reason, and a companion test
(``test_known_violations_still_reproduce``) asserted they still existed --
so that if someone fixed the content, that test would fail and force the
stale entry to be removed, rather than the exception silently living
forever. See past PR descriptions (#29 and its predecessors) for the full
history.

Both dicts are now empty: every previously-grandfathered gap has been
fixed at the content level instead of permanently allowlisted.
``KNOWN_ADAPTED_MISSING_TEST``'s two `Test:` lines (10-recovery-hrv.md:64
and :123) were written in. ``KNOWN_INVALID_TAGS``'s last entry
(05-open-water-pace-inference.md:64, an ``[ADAPTED: general open-water
coaching guidance]`` tag with no matching allowed value) was resolved by
re-tagging the claim ``[EVIDENCE: swim]`` -- Andrew's editorial call that
the source (PurplePatch Fitness's OW pacing guide) is swim coaching
guidance itself, not borrowed from an adjacent discipline, so it was never
really an ADAPTED claim; see 05's own text for the reasoning and the
discounted ``Confidence: low-medium`` grade. Every gate rule in this module
now enforces with zero allowlisted exceptions.

Both dicts and their companion-test loops (in
``test_known_violations_still_reproduce``) are left in place, not deleted,
so a future genuine gap has somewhere to go without re-deriving this
mechanism from scratch. With both dicts empty, those loops are no-ops by
construction (an empty dict's ``.items()`` never executes the loop body) --
that's the intended, verified end state, not a silent gap: the underlying
checkers (``find_invalid_tags``, ``find_adapted_blocks``) are independently
exercised against inline fixtures by the negative tests below, so their
ability to bite is proven without depending on real library/ content
currently containing a violation.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LIBRARY_DIR = REPO_ROOT / "library"
ENGINE_DIR = REPO_ROOT / "engine" / "swim_coach"
REFERENCE_LIST = LIBRARY_DIR / "reference_list.md"

# --- Rule 5: word count -----------------------------------------------------
# 00-conventions.md: "Topic files stay <= ~2,500 words". This is a hard cap,
# not a style preference: 00-conventions.md sizes it so up to three topic
# files fit in a single context window, because /coach's routing budget is
# 2-4 topic files plus reference_list.md per question (see INDEX.md). A
# tolerance just becomes the new de facto cap -- so there is none. A file
# over the limit is an editorial decision (trim, or split into a new topic
# file), not something this gate should silently wave through.
WORD_COUNT_LIMIT = 2500

# --- Rule 3: allowed tag values ---------------------------------------------
EVIDENCE_ALLOWED = {"swim-ultra", "swim"}
# Combined ADAPTED forms actually in use in the repo today (grepped, not
# invented): cycling/running, running/cycling, general-endurance/multi-sport.
ADAPTED_ALLOWED = {
    "cycling",
    "running",
    "tri",
    "general-endurance",
    "cycling/running",
    "running/cycling",
    "general-endurance/multi-sport",
}

# --- Rule 4: allowed confidence values ---------------------------------------
# 00-conventions.md documents the 5-tier scale: "Confidence:
# high|medium-high|medium|low-medium|low", with guidance on when an
# intermediate grade (medium-high/low-medium) is the honest choice rather
# than a rounding to either neighbor. This module enforces exactly that
# documented scale -- it is not a tolerated deviation from 00-conventions.md;
# library content (10-recovery-hrv.md, 05-open-water-pace-inference.md, and
# reference_list.md itself) already used "medium-high"/"low-medium" as a
# genuine, consistently-used intermediate grade before the prose was
# updated to match.
CONFIDENCE_ALLOWED = {"high", "medium", "low", "low-medium", "medium-high"}

FABRICATED_ID_RE = re.compile(r"\bPMC\d+\b|\bPubMed\s*:\s*\d+|\bdoi\s*:", re.IGNORECASE)
BARE_URL_RE = re.compile(r"https?://\S+")
TAG_RE = re.compile(r"\[(EVIDENCE|ADAPTED):\s*([^\]]*)\]")
CONFIDENCE_RE = re.compile(r"Confidence:\**\s*([A-Za-z]+(?:-[A-Za-z]+)*)")
HEADING2_RE = re.compile(r"^## (.+)$", re.MULTILINE)
HEADING_ANY_RE = re.compile(r"^#{1,6}\s", re.MULTILINE)

# Citation shape: capitalized name token(s) (Unicode-aware), optionally
# joined by ", " / " & " / " and " / whitespace, optionally followed by
# "et al.", immediately followed by "(YYYY)". See module docstring.
_NAME_TOKEN = r"[A-Z][\w'\-]*\.?"
_JOIN = r"(?:,\s*|\s*&\s*|\s+and\s+|\s+)"
CITATION_RE = re.compile(
    rf"(?P<name>{_NAME_TOKEN}(?:{_JOIN}{_NAME_TOKEN})*)(?:,?\s*et\s+al\.)?"
    rf"\s*\((?P<year>(?:19|20)\d{{2}})\)"
)

LIBRARY_REF_RE = re.compile(r"library/([A-Za-z0-9_.\*-]+\.md)")

# --- Known, already-reported violations (see module + PR body) -------------
# (filename, line) -> human-readable reason. Deliberately NOT folded into
# the allowlists above -- see test_known_violations_still_reproduce.
KNOWN_INVALID_TAGS: dict[tuple[str, int], str] = {}
# Empty: 05-open-water-pace-inference.md:64's
# `[ADAPTED: general open-water coaching guidance]` -- the last remaining
# entry -- was re-tagged `[EVIDENCE: swim]` (Andrew's call: PurplePatch's OW
# pacing guide is swim coaching guidance itself, not borrowed from an
# adjacent discipline, so it was never really an ADAPTED claim; it's the
# same situation 06-long-swim-progression.md's Santa Barbara citation
# handles, discounted to `Confidence: low-medium` since it's a practitioner
# resource rather than a peer-reviewed study). Both allowlists in this
# module are now empty -- see module docstring. Kept as a live mechanism
# (not deleted) for any future genuine gap; test_known_violations_still_
# reproduce's loops over these dicts are no-ops while they're empty, which
# is the desired end state, not a hidden gap in the mechanism (the dicts'
# types are still exercised by the two `test_...tag_value_is_flagged` /
# `test_adapted_block_missing_test_is_flagged` negative tests above, which
# prove the underlying checkers still bite against fixtures independent of
# whether real library/ content currently has any violations).
KNOWN_ADAPTED_MISSING_TEST: dict[tuple[str, int], str] = {}


# ============================================================================
# Pure helper functions (exercised directly by the negative tests below).
# ============================================================================


def numbered_files() -> list[Path]:
    """Every library/[0-9][0-9]-*.md file that currently exists."""
    return sorted(LIBRARY_DIR.glob("[0-9][0-9]-*.md"))


def claim_topic_files() -> list[Path]:
    """numbered_files() minus 00-conventions.md -- see module docstring."""
    return [f for f in numbered_files() if not f.name.startswith("00-")]


def line_of(text: str, pos: int) -> int:
    """1-indexed line number of a character offset into text."""
    return text.count("\n", 0, pos) + 1


def sections_by_h2(text: str) -> list[tuple[str | None, int, int]]:
    """Split text into (heading_or_None, start_offset, end_offset) spans,
    bucketing everything before the first '## ' heading under heading=None.
    """
    headings = list(HEADING2_RE.finditer(text))
    if not headings:
        return [(None, 0, len(text))]
    sections: list[tuple[str | None, int, int]] = []
    if headings[0].start() > 0:
        sections.append((None, 0, headings[0].start()))
    for i, h in enumerate(headings):
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        sections.append((h.group(1).strip(), h.start(), end))
    return sections


def is_rule1_exempt(filename: str, heading: str | None) -> bool:
    """Section-scoped exemptions for rule 1 (fabricated ids / bare URLs).

    - reference_list.md: the header (before the first '## ' heading, where
      the fabrication history is narrated -- including the literal string
      "https://nih.gov" as an example of what was fabricated) and the
      "Practical / non-journal resources" section (URLs there ARE the
      citation).
    - 00-conventions.md: "The one rule that matters most" section, which
      narrates the same fabrication history in prose.
    - Every other file: no exemption.
    """
    if filename == "reference_list.md":
        return heading is None or heading == "Practical / non-journal resources"
    if filename == "00-conventions.md":
        return heading == "The one rule that matters most"
    return False


def find_rule1_violations(filename: str, text: str) -> list[tuple[int, str]]:
    """(line, matched_text) for fabricated ids / bare urls, honoring exemptions."""
    violations: list[tuple[int, str]] = []
    for heading, start, end in sections_by_h2(text):
        if is_rule1_exempt(filename, heading):
            continue
        chunk = text[start:end]
        for m in FABRICATED_ID_RE.finditer(chunk):
            violations.append((line_of(text, start + m.start()), m.group(0)))
        for m in BARE_URL_RE.finditer(chunk):
            violations.append((line_of(text, start + m.start()), m.group(0)))
    return violations


def find_adapted_blocks(text: str) -> list[dict]:
    """One entry per [ADAPTED: ...] tag occurrence.

    Block scope: from the tag itself to the next EVIDENCE/ADAPTED tag, the
    next markdown heading (any level), or end of file -- whichever comes
    first. This is deliberately tighter than "enclosing section" scoping:
    prototyping against the real library content showed that section-level
    scoping hides genuine gaps (two ADAPTED blocks in
    10-recovery-hrv.md that have no Test: of their own, but sit in a
    section with an unrelated Test: elsewhere) -- see KNOWN_ADAPTED_MISSING_TEST.
    """
    blocks = []
    for m in TAG_RE.finditer(text):
        if m.group(1) != "ADAPTED":
            continue
        search_from = m.end()
        next_tag = TAG_RE.search(text, search_from)
        next_heading = HEADING_ANY_RE.search(text, search_from)
        candidates = [len(text)]
        if next_tag:
            candidates.append(next_tag.start())
        if next_heading:
            candidates.append(next_heading.start())
        end = min(candidates)
        block_text = text[m.start() : end]
        blocks.append(
            {
                "line": line_of(text, m.start()),
                "value": m.group(2).strip(),
                "has_confidence": "Confidence:" in block_text,
                "has_test": "Test:" in block_text,
            }
        )
    return blocks


def find_invalid_tags(text: str) -> list[tuple[int, str, str]]:
    """(line, kind, raw_value) for any [EVIDENCE: ...]/[ADAPTED: ...] tag
    whose value isn't in the allowed set for its kind."""
    out = []
    for m in TAG_RE.finditer(text):
        kind, raw = m.group(1), m.group(2).strip()
        allowed = EVIDENCE_ALLOWED if kind == "EVIDENCE" else ADAPTED_ALLOWED
        if raw not in allowed:
            out.append((line_of(text, m.start()), kind, raw))
    return out


def find_invalid_confidence(text: str) -> list[tuple[int, str]]:
    """(line, raw_value) for any 'Confidence: X' whose X isn't allowed."""
    out = []
    for m in CONFIDENCE_RE.finditer(text):
        if m.group(1).lower() not in CONFIDENCE_ALLOWED:
            out.append((line_of(text, m.start()), m.group(1)))
    return out


def word_count(text: str) -> int:
    return len(text.split())


def extract_citations(text: str) -> list[dict]:
    """(line, name_blob, year) for every 'Author(s) (YYYY)'-shaped citation."""
    return [
        {
            "line": line_of(text, m.start()),
            "name_blob": m.group("name"),
            "year": m.group("year"),
        }
        for m in CITATION_RE.finditer(text)
    ]


def candidate_surnames(name_blob: str) -> list[str]:
    """Split a matched citation's name blob into plausible surname tokens
    (drops bare initials / single letters, which are noise for matching)."""
    tokens = re.split(r"[,&]|\s+and\s+|\s+", name_blob)
    return [t.strip(". \n\t") for t in tokens if len(t.strip(". \n\t")) > 2]


def citation_resolves(name_blob: str, reference_text: str) -> bool:
    """True if at least one candidate surname from name_blob appears
    verbatim in reference_text (reference_list.md's full content)."""
    names = candidate_surnames(name_blob)
    return bool(names) and any(n in reference_text for n in names)


def find_library_refs(text: str) -> list[str]:
    """Every distinct 'library/<...>.md' path mentioned in text."""
    return sorted(set(LIBRARY_REF_RE.findall(text)))


def library_ref_exists(ref: str) -> bool:
    """True if a library/ reference (possibly a glob like
    'sample_pool_workout_*.md') resolves to at least one real file."""
    if "*" in ref:
        return any(LIBRARY_DIR.glob(ref))
    return (LIBRARY_DIR / ref).exists()


# ============================================================================
# Rule 1: no fabricated-identifier / bare-URL citations.
# ============================================================================

_RULE1_FILES = numbered_files() + [REFERENCE_LIST]


@pytest.mark.parametrize("path", _RULE1_FILES, ids=lambda p: p.name)
def test_no_fabricated_identifiers_or_bare_urls(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    violations = find_rule1_violations(path.name, text)
    assert not violations, (
        f"{path.relative_to(REPO_ROOT)} contains PMC/PubMed/doi identifiers "
        f"or bare URLs outside the documented exemptions (reference_list.md's "
        f"header + 'Practical / non-journal resources' section; "
        f"00-conventions.md's 'The one rule that matters most' section): "
        f"{violations}. Per library/00-conventions.md, cite by title + "
        f"author + year only -- see reference_list.md's header for why."
    )


# ============================================================================
# Rule 2: every [ADAPTED: ...] block carries Confidence: and Test:.
# ============================================================================


@pytest.mark.parametrize("path", claim_topic_files(), ids=lambda p: p.name)
def test_adapted_blocks_have_confidence_and_test(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    problems = []
    for block in find_adapted_blocks(text):
        key = (path.name, block["line"])
        if key in KNOWN_ADAPTED_MISSING_TEST:
            continue
        missing = []
        if not block["has_confidence"]:
            missing.append("Confidence:")
        if not block["has_test"]:
            missing.append("Test:")
        if missing:
            problems.append((block["line"], missing))
    assert not problems, (
        f"{path.relative_to(REPO_ROOT)} has [ADAPTED: ...] block(s) missing "
        f"required field(s): {problems}. Per library/00-conventions.md, "
        f"'Every [ADAPTED] block must carry two more things: Confidence: "
        f"high|medium-high|medium|low-medium|low, and Test: <falsifiable "
        f"statement>.'"
    )


# ============================================================================
# Rule 3: [EVIDENCE: ...] / [ADAPTED: ...] tags use an allowed value.
# ============================================================================

_TAG_FILES = claim_topic_files() + [REFERENCE_LIST]


@pytest.mark.parametrize("path", _TAG_FILES, ids=lambda p: p.name)
def test_tags_use_allowed_values(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    violations = [
        (line, kind, raw)
        for (line, kind, raw) in find_invalid_tags(text)
        if (path.name, line) not in KNOWN_INVALID_TAGS
    ]
    assert not violations, (
        f"{path.relative_to(REPO_ROOT)} has tag(s) with a value outside the "
        f"allowed set (EVIDENCE: {sorted(EVIDENCE_ALLOWED)}; "
        f"ADAPTED: {sorted(ADAPTED_ALLOWED)}): {violations}. If this is a "
        f"genuinely new, legitimate combined form, add it to the allowlist "
        f"in tests/unit/test_library_discipline.py explicitly -- don't "
        f"widen the regex to paper over it."
    )


# ============================================================================
# Rule 4: Confidence: values match the documented 5-tier scale --
# high|medium-high|medium|low-medium|low (see CONFIDENCE_ALLOWED's comment).
# ============================================================================


@pytest.mark.parametrize("path", _TAG_FILES, ids=lambda p: p.name)
def test_confidence_values_are_allowed(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    violations = find_invalid_confidence(text)
    assert not violations, (
        f"{path.relative_to(REPO_ROOT)} has Confidence: value(s) outside "
        f"{sorted(CONFIDENCE_ALLOWED)}: {violations}."
    )


# ============================================================================
# Rule 5: topic files stay <= 2,500 words, hard cap (see WORD_COUNT_LIMIT
# comment). A soft warn threshold at 2,300 words gives authors notice before
# they hit the wall, without failing the build.
# ============================================================================

WORD_COUNT_WARN_THRESHOLD = 2300


@pytest.mark.parametrize("path", claim_topic_files(), ids=lambda p: p.name)
def test_topic_file_word_count(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    count = word_count(text)
    assert count <= WORD_COUNT_LIMIT, (
        f"{path.relative_to(REPO_ROOT)} is {count} words, over the 2,500 "
        f"cap. The cap exists so any 3 topic files fit one context window "
        f"(00-conventions.md). Decide: trim the file, or split it into a "
        f"new topic file."
    )
    if count > WORD_COUNT_WARN_THRESHOLD:
        print(
            f"\nWARN: {path.relative_to(REPO_ROOT)} is {count} words, "
            f"approaching the 2,500-word hard cap (warn threshold "
            f"{WORD_COUNT_WARN_THRESHOLD})."
        )


# ============================================================================
# Rule 6: topic-file citations resolve to reference_list.md.
# ============================================================================


@pytest.mark.parametrize("path", claim_topic_files(), ids=lambda p: p.name)
def test_citations_resolve_to_reference_list(path: Path) -> None:
    reference_text = REFERENCE_LIST.read_text(encoding="utf-8")
    text = path.read_text(encoding="utf-8")
    unresolved = [
        (c["line"], c["name_blob"], c["year"])
        for c in extract_citations(text)
        if not citation_resolves(c["name_blob"], reference_text)
    ]
    assert not unresolved, (
        f"{path.relative_to(REPO_ROOT)} cites source(s) that don't appear "
        f"in reference_list.md: {unresolved}. Per library/00-conventions.md, "
        f"reference_list.md is the only trustworthy citation source in this "
        f"repo -- if this is a real source, add it to reference_list.md "
        f"first (verified, per the header's discipline); if it's not real, "
        f"remove the claim."
    )


# ============================================================================
# Rule 7: engine constants' library/ citations point at files that exist.
# ============================================================================


def test_engine_library_refs_exist() -> None:
    """Every library/NN-*.md (or library/reference_list.md, etc.) path
    referenced in an engine/swim_coach/*.py comment must exist as a real
    file. This is the tractable direction of 00-conventions.md's "every
    engine constant citing a topic file must have a matching claim in that
    file" rule -- the semantic direction (that the claim actually matches
    what the code does) is not machine-checkable and isn't attempted here.
    """
    missing: list[tuple[str, str]] = []
    for py_file in sorted(ENGINE_DIR.glob("*.py")):
        text = py_file.read_text(encoding="utf-8")
        for ref in find_library_refs(text):
            if not library_ref_exists(ref):
                missing.append((py_file.name, ref))
    assert not missing, (
        f"engine/swim_coach/*.py cites library/ file(s) that don't exist: "
        f"{missing}. Per library/00-conventions.md, engine constants must "
        f"cite a real library file."
    )


# ============================================================================
# Negative tests: prove the checkers actually bite, using inline fixtures
# (no dependency on real library/ content staying in any particular state).
# ============================================================================


def test_find_rule1_violations_catches_fabricated_pmc_id() -> None:
    text = "Some claim, supported by this paper (PMC1234567).\n"
    violations = find_rule1_violations("06-long-swim-progression.md", text)
    assert violations == [(1, "PMC1234567")]


def test_find_rule1_violations_catches_pubmed_and_doi_and_bare_url() -> None:
    text = (
        "First claim (PubMed: 99999).\n"
        "Second claim, doi:10.1234/fake.\n"
        "Third claim, see https://example.com/paper for details.\n"
    )
    violations = find_rule1_violations("04-css-intensity-anchors.md", text)
    assert len(violations) == 3


def test_find_rule1_violations_respects_documented_exemptions() -> None:
    # Mimics reference_list.md's header (before any '## ' heading) and its
    # "Practical / non-journal resources" section: both are exempt.
    text = (
        "# Research Reference List\n\n"
        "The original fields included the bare string `https://nih.gov`.\n\n"
        "## Swimming\n\n"
        "This section is NOT exempt: (PMC9999999) should still be flagged.\n\n"
        "## Practical / non-journal resources\n\n"
        "- Some site: <https://example.com/training>\n"
    )
    violations = find_rule1_violations("reference_list.md", text)
    assert violations == [(7, "PMC9999999")]


def test_adapted_block_missing_test_is_flagged() -> None:
    text = (
        "## Some section\n\n"
        "**[ADAPTED: cycling] Confidence: medium.** Some claim with no "
        "falsifiable test attached.\n\n"
        "## Next section\n"
    )
    blocks = find_adapted_blocks(text)
    assert len(blocks) == 1
    assert blocks[0]["has_confidence"] is True
    assert blocks[0]["has_test"] is False


def test_adapted_block_with_confidence_and_test_passes() -> None:
    text = (
        "**[ADAPTED: running] Confidence: high.** Some claim. "
        "**Test:** check X against Y.\n"
    )
    blocks = find_adapted_blocks(text)
    assert blocks[0]["has_confidence"] is True
    assert blocks[0]["has_test"] is True


def test_invalid_evidence_tag_value_is_flagged() -> None:
    text = "**[EVIDENCE: made-up-category]** Some claim.\n"
    violations = find_invalid_tags(text)
    assert violations == [(1, "EVIDENCE", "made-up-category")]


def test_invalid_adapted_tag_value_is_flagged() -> None:
    text = "**[ADAPTED: skiing]** Some claim.\n"
    violations = find_invalid_tags(text)
    assert violations == [(1, "ADAPTED", "skiing")]


def test_valid_tag_values_pass() -> None:
    text = "**[EVIDENCE: swim-ultra]** X. **[ADAPTED: cycling/running]** Y.\n"
    assert find_invalid_tags(text) == []


def test_invalid_confidence_value_is_flagged() -> None:
    text = "**[ADAPTED: cycling] Confidence: super-duper-high.** Some claim.\n"
    violations = find_invalid_confidence(text)
    assert violations == [(1, "super-duper-high")]


def test_citation_not_in_reference_list_is_flagged() -> None:
    reference_text = REFERENCE_LIST.read_text(encoding="utf-8")
    text = "`Fakeperson et al. (2099)` invented this finding.\n"
    citations = extract_citations(text)
    assert len(citations) == 1
    assert not citation_resolves(citations[0]["name_blob"], reference_text)


def test_citation_in_reference_list_resolves() -> None:
    reference_text = REFERENCE_LIST.read_text(encoding="utf-8")
    text = "`Wakayoshi et al. (1992)` derived critical velocity.\n"
    citations = extract_citations(text)
    assert len(citations) == 1
    assert citation_resolves(citations[0]["name_blob"], reference_text)


def test_library_ref_exists_handles_glob() -> None:
    assert library_ref_exists("sample_pool_workout_*.md") is True
    assert library_ref_exists("99-does-not-exist.md") is False


# ============================================================================
# Meta: known pre-existing violations must still reproduce, so a stale
# exception isn't silently masking a since-fixed (or since-worsened) issue.
# ============================================================================


def test_known_violations_still_reproduce() -> None:
    # Both loops below are no-ops today -- KNOWN_INVALID_TAGS and
    # KNOWN_ADAPTED_MISSING_TEST are both empty (see module docstring). That
    # is the desired end state (every gate rule enforces with zero
    # allowlisted exceptions), not a silently-broken mechanism: the
    # assertion right after the loops pins the "both empty" state itself,
    # so this test still fails (rather than vacuously passing) if either
    # dict is ever repopulated without this assertion being updated, and
    # the checkers' ability to bite at all is independently proven by the
    # negative tests above (e.g. test_invalid_adapted_tag_value_is_flagged,
    # test_adapted_block_missing_test_is_flagged), which don't depend on
    # real library/ content containing a violation.
    for (filename, expected_line), reason in KNOWN_INVALID_TAGS.items():
        text = (LIBRARY_DIR / filename).read_text(encoding="utf-8")
        lines = [ln for (ln, _kind, _raw) in find_invalid_tags(text)]
        assert expected_line in lines, (
            f"KNOWN_INVALID_TAGS says {filename}:{expected_line} should "
            f"still be an invalid tag ({reason}) but it no longer "
            f"reproduces -- remove this stale entry from "
            f"KNOWN_INVALID_TAGS in tests/unit/test_library_discipline.py."
        )

    for (filename, expected_line), reason in KNOWN_ADAPTED_MISSING_TEST.items():
        text = (LIBRARY_DIR / filename).read_text(encoding="utf-8")
        blocks = {b["line"]: b for b in find_adapted_blocks(text)}
        assert expected_line in blocks and not blocks[expected_line]["has_test"], (
            f"KNOWN_ADAPTED_MISSING_TEST says {filename}:{expected_line} "
            f"should still be missing Test: ({reason}) but it no longer "
            f"reproduces -- remove this stale entry from "
            f"KNOWN_ADAPTED_MISSING_TEST in tests/unit/test_library_discipline.py."
        )

    assert KNOWN_INVALID_TAGS == {} and KNOWN_ADAPTED_MISSING_TEST == {}, (
        "Both allowlists are expected to be empty -- every gate rule should "
        "enforce with zero allowlisted exceptions. If you've added a new "
        "entry, that's a regression in gate strictness unless it's a "
        "genuinely new, reviewed exception; update this assertion "
        "deliberately, don't just let it fail."
    )
