"""Parse review-pending ("UNREVIEWED") claims out of `library/*.md`.

Pure parsing module -- no side effects, no writes, no LLM/network calls.
`cli.py`'s `review-queue` and `review-accept` subcommands are the only
callers; they own all I/O (reading the library tree, writing an accepted
file back, printing the queue or the HTML page).

Why this exists: per `library/00-conventions.md`, a freshly-authored or
freshly-changed topic file (or section) is marked `UNREVIEWED` until Andrew
reviews it. Grepping for that word and manually working out which *claims*
it actually covers -- and which of those need real judgment (a cross-
discipline inference resting on a shaky source) versus a rubber stamp (an
engineering default) -- was the exact pain point this module removes.

The central idea: **a marker has a scope, and the reviewable units are the
tagged claim blocks inside that scope, not the marker itself.**

Marker scope
------------
- A marker in a file's header (the H1 section, before the first `##`) is a
  **file-level** marker: it covers every claim in the file. This is the
  common case for a freshly-drafted topic file -- `08-ultra-feeding.md`,
  `13-reds-energy-availability.md` and `07-strength-dryland.md` each carry
  one, covering ~2,000+ words of individually-tagged claims. Enumerating
  those claims individually is the whole point of the queue; reporting the
  header blurb alone (which carries no tag) as the file's only item would
  be exactly backwards.
- A marker inside a `##` section is a **section-level** marker: it covers
  only that section's claims (e.g. `04-css-intensity-anchors.md`'s
  "Coach judgment / UNREVIEWED" line in its Open-questions section).
- A claim block is governed by the **innermost** marker whose scope
  contains it, so a section marker inside an otherwise file-marked file
  (`07-strength-dryland.md`'s dosing section) survives acceptance of the
  file-level marker.

Claim blocks
------------
A claim block is anchored on an evidence tag -- `[EVIDENCE: ...]`,
`[ADAPTED: ...]`, or `Coach judgment` -- and runs to the next anchor or the
next heading, extended *backwards* to the start of its paragraph/bullet so
the claim's bold lead-in sentence (its headline) travels with it.

Two anchors collapse into one block when they belong to the same claim:
  - Two tags in one sentence with no `Confidence:` between them -- e.g.
    `08`'s "`[EVIDENCE: swim]` for the open-water application,
    `[ADAPTED: cycling]` for the transporter physiology. Confidence: high."
    is one claim with two tags, not two claims. Every real claim carries
    its own `Confidence:`, so an intervening `Confidence:` is the reliable
    "this is a new claim" signal (`13`'s osteogenic section stacks two
    genuinely distinct claims in one paragraph exactly that way).
  - A `Coach judgment` caveat *inside* an already-anchored paragraph (e.g.
    `13`'s HRV-confound section, `08`'s immersion-diuresis section) is part
    of that claim, not a separate mechanical item.

Classification
--------------
- **needs-judgment**: an `[EVIDENCE: ...]` / `[ADAPTED: ...]` claim -- is
  the (often cross-discipline) inference sound, given what its sources
  actually are? This is the question only a human can answer.
- **mechanical**: a `Coach judgment` engineering default -- just needs an
  OK. A file-header blurb with no tag at all is reported as a single
  low-priority `file-header` item (it's the marker's own home, and the
  thing `review-accept` acts on), never as the file's substantive content.

Marker forms actually present in `library/` (grepped, not invented)
-------------------------------------------------------------------
  - `**UNREVIEWED**` standalone, as a file header flag (`07`, `08`, `13`).
  - `**Coach judgment, UNREVIEWED.**` (`07`'s dosing section).
  - `**Coach judgment / UNREVIEWED**` (`04`'s open-questions bullet).
Only a **bold** span containing "UNREVIEWED" counts (see `MARKER_RE`);
`07`'s plain `` `UNREVIEWED` `` code-span restatement of the same dosing
gap, and `13`'s in-prose "verify before this claim leaves `UNREVIEWED`"
aside, are deliberately not treated as separate markers.

`INDEX.md`, `reference_list.md` and `00-conventions.md` are meta files
(status mirror, citation source, and the convention's own documentation);
they contain the word but no reviewable claims, so they're excluded from
scanning (`META_FILES`). `research-dossiers/` files are raw research input,
never claims -- they're consulted only as *provenance* (`find_dossier`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# --- files excluded from item-scanning (see module docstring) --------------

META_FILES = {"INDEX.md", "reference_list.md", "00-conventions.md"}

# --- regexes -----------------------------------------------------------------

# A bold span containing the word UNREVIEWED. Captures the inner text (group
# 1) so `strip_marker` can edit just that span.
MARKER_RE = re.compile(r"\*\*([^*\n]*\bUNREVIEWED\b[^*\n]*)\*\*")

HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$", re.MULTILINE)

TAG_RE = re.compile(r"\[(EVIDENCE|ADAPTED):\s*([^\]]*)\]")
# Case-sensitive and without a required colon: the canonical tag is
# `Coach judgment:`, but 07-strength-dryland.md writes "**Coach judgment.**"
# and "**Coach judgment, UNREVIEWED.**", and 04 writes
# "**Coach judgment / UNREVIEWED**". Case-sensitivity keeps in-prose
# lowercase mentions ("as coach judgment, not evidence") from anchoring a
# block that isn't canonically tagged.
COACH_JUDGMENT_RE = re.compile(r"Coach judgment")

CONFIDENCE_RE = re.compile(r"(?<!`)Confidence:\**\s*([A-Za-z]+(?:-[A-Za-z]+)*)")
# `Test:` runs to the end of its paragraph (claims write it as the block's
# closing sentence, sometimes several lines long).
TEST_RE = re.compile(r"\*{0,2}Test:\*{0,2}\s*(.+?)(?=\n\s*\n|\Z)", re.DOTALL)

# Citation shape, same as tests/unit/test_library_discipline.py's
# CITATION_RE: capitalized name-like token(s) (Unicode-aware, so
# "Bergström"/"Gómez-Bruton" match), optional "et al.", then "(YYYY)".
# Library files write these inside backticks (`Wagner et al. (2012)`),
# which conveniently bound the name blob.
_NAME_TOKEN = r"[A-Z][\w'\-]*\.?"
_JOIN = r"(?:,\s*|\s*&\s*|\s+and\s+|\s+)"
CITATION_RE = re.compile(
    rf"(?P<name>{_NAME_TOKEN}(?:{_JOIN}{_NAME_TOKEN})*)(?:,?\s*et\s+al\.)?"
    rf"\s*\((?P<year>(?:19|20)\d{{2}})\)"
)

# reference_list.md bullet lead-in: "- **<✓/~/⚠ marker(s)> <key text>**".
# DOTALL matters: plenty of entries wrap the bold author list across two
# lines (e.g. "- **✓ Gómez-Bruton A., ... Casajús J.A.,\n  Vicente-Rodríguez
# G. (2013)**"). Without it those entries parse as nothing at all, and every
# claim citing them silently resolves to no source.
REF_ENTRY_RE = re.compile(r"^- \*\*([✓~⚠]+)\s*(.+?)\*\*", re.MULTILINE | re.DOTALL)

# A topic file names its own dossier in its header, e.g. 08-ultra-feeding.md:
# "drafted from `library/research-dossiers/2026-07-13-ultra-feeding.md`".
DOSSIER_MENTION_RE = re.compile(r"research-dossiers/([A-Za-z0-9_.\-]+\.md)")

# Verification markers that mean "do not lean on this source without
# looking": ~ (not individually verified) and ⚠ (caveat attached). See
# reference_list.md's own "Verification legend".
WEAK_SOURCE_MARKERS = ("~", "⚠")

NEEDS_JUDGMENT = "needs-judgment"
MECHANICAL = "mechanical"

CLAIM = "claim"
FILE_HEADER = "file-header"


def slugify(heading: str) -> str:
    """Deterministic slug for a markdown heading: lowercase, emphasis/code
    markers stripped, non-alphanumeric runs collapsed to single hyphens."""
    text = heading.strip().lower()
    text = re.sub(r"[`*_]", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "section"


# --- structure: sections, paragraphs, markers, claim blocks --------------------


@dataclass(frozen=True)
class Section:
    heading: str
    level: int
    start: int  # offset of the heading line
    end: int  # offset of the next heading, or EOF
    body_start: int  # offset just past the heading line


def sections(text: str) -> list[Section]:
    """Every heading's span, any level: heading line start to the next
    heading (any level) or EOF. Topic files always open with an H1, so the
    headingless fallback below only fires for a fixture."""
    matches = list(HEADING_RE.finditer(text))
    if not matches:
        return [Section(heading="", level=0, start=0, end=len(text), body_start=0)]
    out = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out.append(
            Section(
                heading=m.group(2).strip(),
                level=len(m.group(1)),
                start=m.start(),
                end=end,
                body_start=m.end(),
            )
        )
    return out


def _section_containing(spans: list[Section], pos: int) -> Section:
    for section in spans:
        if section.start <= pos < section.end:
            return section
    return spans[-1]


def _paragraph_start(text: str, pos: int, floor: int) -> int:
    """Start of the paragraph or top-level bullet containing `pos`, never
    earlier than `floor`. Paragraph boundaries are blank lines; a top-level
    "- " bullet also starts its own block, so a bullet list of separately-
    tagged claims (08's EAH safety rail) yields one item per bullet."""
    blank = text.rfind("\n\n", floor, pos)
    start = floor if blank == -1 else blank + 2
    bullet = text.rfind("\n- ", start, pos)
    if bullet != -1:
        start = bullet + 1
    return start


def _same_paragraph(text: str, a: int, b: int) -> bool:
    return "\n\n" not in text[a:b]


@dataclass(frozen=True)
class Marker:
    """One UNREVIEWED marker and the span of text it governs."""

    text: str  # inner text of the `**...**` span
    start: int
    end: int
    scope: str  # "file" | "section"
    scope_start: int
    scope_end: int
    heading: str  # heading of the section the marker itself sits in


def find_markers(text: str) -> list[Marker]:
    spans = sections(text)
    out = []
    for m in MARKER_RE.finditer(text):
        section = _section_containing(spans, m.start())
        file_level = section.level <= 1
        out.append(
            Marker(
                text=m.group(1).strip(),
                start=m.start(),
                end=m.end(),
                scope="file" if file_level else "section",
                scope_start=0 if file_level else section.start,
                scope_end=len(text) if file_level else section.end,
                heading=section.heading,
            )
        )
    return out


@dataclass(frozen=True)
class ClaimBlock:
    start: int
    end: int
    heading: str
    tag_kind: str  # "EVIDENCE" | "ADAPTED" | "Coach judgment"
    tag_value: str | None


def _anchors(text: str) -> list[tuple[int, int, str, str | None]]:
    """(start, end, kind, value) for every evidence-tag anchor, with
    same-claim anchors collapsed -- see the module docstring."""
    raw: list[tuple[int, int, str, str | None]] = [
        (m.start(), m.end(), m.group(1), m.group(2).strip()) for m in TAG_RE.finditer(text)
    ]
    raw += [(m.start(), m.end(), "Coach judgment", None) for m in COACH_JUDGMENT_RE.finditer(text)]
    raw.sort()

    kept: list[tuple[int, int, str, str | None]] = []
    for anchor in raw:
        start, _end, kind, _value = anchor
        if kept:
            prev_start, prev_end, _prev_kind, _prev_value = kept[-1]
            if _same_paragraph(text, prev_start, start):
                # A Coach-judgment caveat inside an already-anchored claim
                # belongs to that claim.
                if kind == "Coach judgment":
                    continue
                # Two tags in one claim (no Confidence: between them) are
                # one block; an intervening Confidence: means a new claim.
                if not CONFIDENCE_RE.search(text[prev_end:start]):
                    continue
        kept.append(anchor)
    return kept


def find_claim_blocks(text: str) -> list[ClaimBlock]:
    """Every tagged claim block in a file, in document order."""
    spans = sections(text)
    anchors = _anchors(text)
    blocks: list[ClaimBlock] = []

    for i, (start, _end, kind, value) in enumerate(anchors):
        section = _section_containing(spans, start)
        floor = max(section.body_start, blocks[-1].end if blocks else 0)
        block_start = _paragraph_start(text, start, floor)

        next_anchor_start = anchors[i + 1][0] if i + 1 < len(anchors) else len(text)
        if next_anchor_start >= section.end:
            block_end = section.end
        else:
            next_para = _paragraph_start(text, next_anchor_start, block_start)
            # If the next claim opens its own paragraph/bullet, end this
            # block at that paragraph's start so the next claim's bold
            # lead-in isn't swallowed here. If instead it's a second claim
            # *inside this same paragraph* (13's osteogenic section stacks
            # two), its paragraph start is our own -- end exactly at the
            # next anchor rather than collapsing this block to nothing.
            block_end = next_para if next_para > start else next_anchor_start

        blocks.append(
            ClaimBlock(
                start=block_start,
                end=block_end,
                heading=section.heading,
                tag_kind=kind,
                tag_value=value,
            )
        )
    return blocks


# --- reference_list.md ---------------------------------------------------------


@dataclass(frozen=True)
class RefEntry:
    """One `reference_list.md` bullet: its ✓/~/⚠ verification marker(s) and
    its key text (author + year, verbatim from the bullet's bold lead-in)."""

    markers: str
    key: str


def _normalize(text: str) -> str:
    """Collapse whitespace (incl. the line wraps markdown puts mid-citation)
    so keys and claim text can be compared as flat strings."""
    return " ".join(text.split())


def parse_reference_list(text: str) -> list[RefEntry]:
    return [
        RefEntry(markers=m.group(1), key=_normalize(m.group(2)))
        for m in REF_ENTRY_RE.finditer(text)
    ]


def candidate_surnames(name_blob: str) -> list[str]:
    """Plausible surname tokens from a matched citation's name blob (bare
    initials dropped -- they're noise for matching)."""
    tokens = re.split(r"[,&]|\s+and\s+|\s+", name_blob)
    return [t.strip(". \n\t") for t in tokens if len(t.strip(". \n\t")) > 2]


@dataclass(frozen=True)
class SourceCitation:
    """A `reference_list.md` entry cited by a claim, carrying that entry's
    own ✓/~/⚠ marker -- the signal a reviewer weighs the claim against."""

    markers: str
    key: str

    @property
    def is_weak(self) -> bool:
        return any(mark in self.markers for mark in WEAK_SOURCE_MARKERS)


def resolve_citations(
    claim_text: str, entries: list[RefEntry]
) -> tuple[tuple[SourceCitation, ...], tuple[str, ...]]:
    """`(resolved_sources, unresolved_citations)` for one claim.

    Two matching strategies, either sufficient:
      1. An "Author(s) (YYYY)"-shaped citation -- library files write these
         backticked, e.g. `` `Wagner et al. (2012)` ``, `` `Coggan & Coyle
         (1987)` `` -- whose year AND at least one surname both appear in
         the entry's key. Requiring *both* is what stops a stray capitalized
         word in the name blob from resolving to an unrelated same-year
         entry.
      2. A title-keyed entry (no year in its key, e.g. "Dry-land shoulder-
         strengthening RCTs in competitive swimmers") whose key appears in
         the claim, compared case-insensitively on normalized whitespace.

    A citation that matches no entry is reported as unresolved rather than
    dropped: "this claim cites something that isn't in reference_list.md" is
    itself a finding the reviewer wants (per 00-conventions.md,
    reference_list.md is the only trustworthy citation source).
    """
    flat_claim = _normalize(claim_text)
    found: dict[str, SourceCitation] = {}
    resolved_spans: set[str] = set()

    for m in CITATION_RE.finditer(flat_claim):
        year, blob = m.group("year"), m.group("name")
        surnames = candidate_surnames(blob)
        if not surnames:
            continue
        label = f"{surnames[-1]} ({year})"
        for entry in entries:
            if year in entry.key and any(s in entry.key for s in surnames):
                found[entry.key] = SourceCitation(entry.markers, entry.key)
                resolved_spans.add(label)
                break

    unresolved = []
    for m in CITATION_RE.finditer(flat_claim):
        surnames = candidate_surnames(m.group("name"))
        if not surnames:
            continue
        label = f"{surnames[-1]} ({m.group('year')})"
        if label not in resolved_spans and label not in unresolved:
            unresolved.append(label)

    for entry in entries:
        if entry.key in found or re.search(r"\((?:19|20)\d{2}\)", entry.key):
            continue
        if entry.key.casefold() in flat_claim.casefold():
            found[entry.key] = SourceCitation(entry.markers, entry.key)

    ordered = tuple(
        SourceCitation(e.markers, e.key) for e in entries if e.key in found
    )
    return ordered, tuple(unresolved)


# --- dossier provenance --------------------------------------------------------


def find_dossier(text: str, dossiers_dir: Path) -> str | None:
    """The `research-dossiers/` file a topic file was drafted from, per the
    topic file's own header (e.g. 08-ultra-feeding.md: "drafted from
    `library/research-dossiers/2026-07-13-ultra-feeding.md`").

    Read in that direction deliberately: scanning *dossiers* for a mention
    of the topic file misattributes, because dossiers cross-reference other
    topic files freely (the RED-S dossier names `07-strength-dryland.md`,
    which it did not author). A file that names no dossier -- `07`, `04` --
    correctly gets None.
    """
    for m in DOSSIER_MENTION_RE.finditer(text):
        name = m.group(1)
        if (dossiers_dir / name).exists():
            return name
    return None


# --- review items ---------------------------------------------------------------


@dataclass(frozen=True)
class ReviewItem:
    id: str
    file: str
    heading: str
    item_kind: str  # CLAIM | FILE_HEADER
    claim_text: str
    tag_kind: str | None  # "EVIDENCE" | "ADAPTED" | "Coach judgment" | None
    tag_value: str | None
    confidence: str | None
    test: str | None
    sources: tuple[SourceCitation, ...]
    unresolved_citations: tuple[str, ...]
    dossier: str | None
    classification: str
    marker_text: str
    marker_start: int  # span of the GOVERNING marker in the file's text
    marker_end: int
    owns_marker: bool  # is the governing marker physically inside this item?
    marker_scope: str  # "file" | "section"

    @property
    def tag_display(self) -> str | None:
        if self.tag_kind in ("EVIDENCE", "ADAPTED"):
            return f"[{self.tag_kind}: {self.tag_value}]"
        return self.tag_kind

    @property
    def weak_sources(self) -> tuple[SourceCitation, ...]:
        return tuple(s for s in self.sources if s.is_weak)

    @property
    def needs_attention(self) -> bool:
        """The claim rests on a ~/⚠-marked source, or cites something that
        isn't in reference_list.md at all. Either way a human must look."""
        return bool(self.weak_sources or self.unresolved_citations)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "file": self.file,
            "heading": self.heading,
            "item_kind": self.item_kind,
            "tag": self.tag_display,
            "confidence": self.confidence,
            "test": self.test,
            "sources": [{"markers": s.markers, "key": s.key} for s in self.sources],
            "unresolved_citations": list(self.unresolved_citations),
            "dossier": self.dossier,
            "classification": self.classification,
            "marker_text": self.marker_text,
            "marker_scope": self.marker_scope,
            "owns_marker": self.owns_marker,
            "claim_text": self.claim_text,
        }


def _classify(tag_kind: str | None) -> str:
    return NEEDS_JUDGMENT if tag_kind in ("EVIDENCE", "ADAPTED") else MECHANICAL


def _innermost_marker(markers: list[Marker], start: int, end: int) -> Marker | None:
    """The narrowest-scoped marker whose scope contains [start, end)."""
    covering = [m for m in markers if m.scope_start <= start and end <= m.scope_end]
    if not covering:
        return None
    return min(covering, key=lambda m: m.scope_end - m.scope_start)


def _assign_ids(filename: str, headings: list[str]) -> list[str]:
    """Per-file ids: slugified heading, with a deterministic ordinal suffix
    when a heading holds more than one item. Computed over every claim block
    in the file (not just currently-pending ones), so an id never shifts
    because some other marker was accepted."""
    counts: dict[str, int] = {}
    out = []
    for heading in headings:
        base = slugify(heading)
        counts[base] = counts.get(base, 0) + 1
        n = counts[base]
        out.append(f"{filename}#{base}" if n == 1 else f"{filename}#{base}-{n}")
    return out


def all_item_ids(filename: str, text: str) -> set[str]:
    """Every id this file *could* produce -- one per claim block plus the
    file header -- independent of whether any marker currently covers them.

    `review-accept` uses this to tell an already-accepted id (a real id
    whose marker is gone: a clean no-op) apart from a typo (an error)."""
    spans = sections(text)
    h1 = next((s for s in spans if s.level <= 1), spans[0])
    headings = [h1.heading] + [b.heading for b in find_claim_blocks(text)]
    return set(_assign_ids(filename, headings))


def scan_file(
    filename: str,
    text: str,
    ref_entries: list[RefEntry],
    dossiers_dir: Path,
) -> list[ReviewItem]:
    """Every review-pending item in one topic file, in document order.

    An item is either a tagged claim block governed by an UNREVIEWED marker,
    or (for a file-level marker whose header carries no tagged claim of its
    own) a single low-priority `file-header` item -- the marker's own home
    and the thing `review-accept` acts on.
    """
    markers = find_markers(text)
    if not markers:
        return []

    spans = sections(text)
    h1 = next((s for s in spans if s.level <= 1), spans[0])
    blocks = find_claim_blocks(text)
    dossier = find_dossier(text, dossiers_dir)

    # Ids are keyed to headings and computed over every claim block in the
    # file, plus the H1 (for a possible file-header item), so they're stable
    # whatever the marker state.
    id_by_index = _assign_ids(filename, [h1.heading] + [b.heading for b in blocks])
    header_id, block_ids = id_by_index[0], id_by_index[1:]

    items: list[ReviewItem] = []

    file_markers = [m for m in markers if m.scope == "file"]
    for marker in file_markers:
        # Only emit a header item if the marker isn't already inside a
        # tagged claim block (which would be the substantive item instead).
        if any(b.start <= marker.start < b.end for b in blocks):
            continue
        items.append(
            ReviewItem(
                id=header_id,
                file=filename,
                heading=h1.heading,
                item_kind=FILE_HEADER,
                claim_text=text[h1.body_start : h1.end].strip(),
                tag_kind=None,
                tag_value=None,
                confidence=None,
                test=None,
                sources=(),
                unresolved_citations=(),
                dossier=dossier,
                classification=MECHANICAL,
                marker_text=marker.text,
                marker_start=marker.start,
                marker_end=marker.end,
                owns_marker=True,
                marker_scope=marker.scope,
            )
        )

    for block, item_id in zip(blocks, block_ids):
        marker = _innermost_marker(markers, block.start, block.end)
        if marker is None:
            continue
        claim_text = text[block.start : block.end].strip()
        confidence = CONFIDENCE_RE.search(claim_text)
        test = TEST_RE.search(claim_text)
        sources, unresolved = resolve_citations(claim_text, ref_entries)
        items.append(
            ReviewItem(
                id=item_id,
                file=filename,
                heading=block.heading,
                item_kind=CLAIM,
                claim_text=claim_text,
                tag_kind=block.tag_kind,
                tag_value=block.tag_value,
                confidence=confidence.group(1) if confidence else None,
                test=" ".join(test.group(1).split()) if test else None,
                sources=sources,
                unresolved_citations=unresolved,
                dossier=dossier,
                classification=_classify(block.tag_kind),
                marker_text=marker.text,
                marker_start=marker.start,
                marker_end=marker.end,
                owns_marker=block.start <= marker.start < block.end,
                marker_scope=marker.scope,
            )
        )

    return sorted(items, key=lambda i: (i.marker_start if i.item_kind == FILE_HEADER else 0, i.id))


def scan_library(library_dir: Path) -> list[ReviewItem]:
    """Every review-pending item across `library/*.md`, excluding META_FILES.
    Deterministic order: files sorted by name, items in document order."""
    reference_list_path = library_dir / "reference_list.md"
    ref_entries = (
        parse_reference_list(reference_list_path.read_text(encoding="utf-8"))
        if reference_list_path.exists()
        else []
    )
    dossiers_dir = library_dir / "research-dossiers"

    items: list[ReviewItem] = []
    for path in sorted(library_dir.glob("*.md")):
        if path.name in META_FILES:
            continue
        items.extend(scan_file(path.name, path.read_text(encoding="utf-8"), ref_entries, dossiers_dir))
    return items


def sort_for_review(items: list[ReviewItem]) -> list[ReviewItem]:
    """Queue order: needs-judgment first; within each group, claims with a
    weak (~/⚠) source first -- those are the ones a human most needs to
    weigh -- then file-header items last (they're the marker's home, not the
    substance)."""
    return sorted(
        items,
        key=lambda i: (
            0 if i.classification == NEEDS_JUDGMENT else 1,
            1 if i.item_kind == FILE_HEADER else 0,
            0 if i.needs_attention else 1,
            i.id,
        ),
    )


# --- INDEX.md ------------------------------------------------------------------

INDEX_UNREVIEWED_SUFFIX = "**UNREVIEWED**, pending human review."
INDEX_REVIEWED_SUFFIX = "Human-reviewed."


def mark_index_reviewed(index_text: str, filename: str) -> tuple[str, bool]:
    """Flip `INDEX.md`'s row for `filename` from the UNREVIEWED status
    sentence to "Human-reviewed." Returns `(new_text, changed)`. Scoped to
    that file's own row, so it can never touch another file's status."""
    row_prefix = f"| `{filename}` |"
    lines = index_text.split("\n")
    for i, line in enumerate(lines):
        if line.startswith(row_prefix) and INDEX_UNREVIEWED_SUFFIX in line:
            lines[i] = line.replace(INDEX_UNREVIEWED_SUFFIX, INDEX_REVIEWED_SUFFIX)
            return "\n".join(lines), True
    return index_text, False


# --- marker stripping (review-accept) -------------------------------------------


def strip_marker(text: str, marker_start: int, marker_end: int) -> str:
    """Remove exactly the UNREVIEWED marker at `text[marker_start:marker_end]`,
    editing only that span (plus, for a bare standalone flag, the immediately
    following ": "/". "/" — " lead-in that existed solely to introduce it).
    Every other byte is untouched -- claim prose is never rewritten:
      - "**Coach judgment, UNREVIEWED.**" -> "**Coach judgment.**"
      - "**Coach judgment / UNREVIEWED**" -> "**Coach judgment**"
      - "**UNREVIEWED** — drafted from ..." -> "drafted from ..."
      - anything else containing the word -> word removed, wrapper kept
    """
    inner = text[marker_start:marker_end][2:-2]

    comma_stripped = re.sub(r",\s*UNREVIEWED\b", "", inner)
    if comma_stripped != inner:
        return text[:marker_start] + f"**{comma_stripped}**" + text[marker_end:]

    slash_stripped = re.sub(r"\s*/\s*UNREVIEWED\b", "", inner)
    if slash_stripped != inner:
        return text[:marker_start] + f"**{slash_stripped}**" + text[marker_end:]

    if inner.strip() == "UNREVIEWED":
        rest = text[marker_end:]
        lead_in = re.match(r"\s*[—:.]\s+", rest)
        return text[:marker_start] + (rest[lead_in.end() :] if lead_in else rest)

    fallback = re.sub(r"\s*\bUNREVIEWED\b\s*", " ", inner).strip()
    return text[:marker_start] + f"**{fallback}**" + text[marker_end:]


# --- terminal rendering ----------------------------------------------------------


def _wrap(value: str, width: int, indent: str) -> str:
    words = value.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return f"\n{indent}".join(lines)


def _source_line(source: SourceCitation) -> str:
    flag = "  <-- WEIGH THIS" if source.is_weak else ""
    return f"{source.markers} {source.key}{flag}"


def render_text(items: list[ReviewItem]) -> str:
    """Human-readable grouped queue for a terminal: needs-judgment first,
    each item showing id, file, heading, tag, confidence, Test: line, and
    its cited sources with their ✓/~/⚠ markers."""
    ordered = sort_for_review(items)
    needs = [i for i in ordered if i.classification == NEEDS_JUDGMENT]
    mechanical = [i for i in ordered if i.classification == MECHANICAL]
    weak = [i for i in needs if i.needs_attention]

    out: list[str] = []
    out.append(
        f"Library review queue: {len(needs)} needing judgment, "
        f"{len(mechanical)} mechanical ({len(weak)} resting on a ~/⚠ source)"
    )

    for title, group in (("NEEDS JUDGMENT", needs), ("MECHANICAL", mechanical)):
        out.append("")
        out.append(f"{title} ({len(group)})")
        if not group:
            out.append("  (none)")
            continue
        for item in group:
            out.append("")
            out.append(f"  {item.id}")
            out.append(f"    file       {item.file}")
            out.append(f"    heading    {item.heading}")
            tag = item.tag_display or "(file header -- no claim tag)"
            if item.confidence:
                tag = f"{tag}   Confidence: {item.confidence}"
            out.append(f"    tag        {tag}")
            if item.test:
                out.append(f"    test       {_wrap(item.test, 66, ' ' * 15)}")
            if item.sources:
                first, *rest = item.sources
                out.append(f"    sources    {_source_line(first)}")
                for source in rest:
                    out.append(f"               {_source_line(source)}")
            else:
                out.append("    sources    (none cited)")
            if item.unresolved_citations:
                out.append(
                    f"    UNSOURCED  {', '.join(item.unresolved_citations)} "
                    f"<-- not in reference_list.md"
                )
            if item.dossier:
                out.append(f"    dossier    {item.dossier}")
            if not item.owns_marker:
                out.append(f"    marker     {item.marker_scope}-level: '{item.marker_text}'")
    out.append("")
    return "\n".join(out)


# --- HTML rendering ---------------------------------------------------------------


def _esc(value: str | None) -> str:
    if value is None:
        return ""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _source_html(source: SourceCitation) -> str:
    if source.is_weak:
        return (
            f'<span class="source source-weak">{_esc(source.markers)} '
            f'{_esc(source.key)}<span class="weigh">weigh this</span></span>'
        )
    return f'<span class="source">{_esc(source.markers)} {_esc(source.key)}</span>'


def _row(label: str, value: str) -> str:
    return f'<div class="row"><span class="label">{label}</span> {value}</div>'


def _item_html(item: ReviewItem) -> str:
    rows = [
        _row("File", _esc(item.file)),
        _row("Heading", _esc(item.heading)),
    ]
    tag = _esc(item.tag_display) or "(file header — no claim tag)"
    rows.append(_row("Tag", f'<span class="tag">{tag}</span>'))
    if item.confidence:
        rows.append(_row("Confidence", _esc(item.confidence)))
    if item.test:
        rows.append(_row("Test", _esc(item.test)))
    if item.sources:
        rows.append(_row("Sources", " ".join(_source_html(s) for s in item.sources)))
    else:
        rows.append(_row("Sources", '<span class="muted">none cited</span>'))
    if item.unresolved_citations:
        pills = " ".join(
            f'<span class="source source-weak">{_esc(c)}'
            f'<span class="weigh">not in reference_list</span></span>'
            for c in item.unresolved_citations
        )
        rows.append(_row("Unsourced", pills))
    if item.dossier:
        rows.append(_row("Dossier", _esc(item.dossier)))
    if not item.owns_marker:
        rows.append(
            _row("Marker", _esc(f"{item.marker_scope}-level: '{item.marker_text}'"))
        )

    classes = ["card", item.classification]
    if item.needs_attention:
        classes.append("has-weak")
    if item.item_kind == FILE_HEADER:
        classes.append("file-header")

    badge = '<span class="badge">⚠ check sources</span>' if item.needs_attention else ""
    return (
        f'<div class="{" ".join(classes)}">'
        f'<div class="item-id">{_esc(item.id)}{badge}</div>'
        f'{"".join(rows)}'
        f'<div class="claim">{_esc(item.claim_text)}</div>'
        f"</div>"
    )


def render_html(items: list[ReviewItem]) -> str:
    """A self-contained HTML page (inline CSS only -- no external assets,
    fonts or CDN; renders offline and on a phone) in the project's
    "Bioluminescent Dusk" palette (design/channel-dragon-handoff/README.md).
    Needs-judgment items first; a claim resting on a ~/⚠ source is made
    impossible to miss (amber card edge + badge + amber source pill)."""
    ordered = sort_for_review(items)
    needs = [i for i in ordered if i.classification == NEEDS_JUDGMENT]
    mechanical = [i for i in ordered if i.classification == MECHANICAL]
    weak = [i for i in needs if i.needs_attention]

    needs_html = "\n".join(_item_html(i) for i in needs) or '<p class="muted">None.</p>'
    mechanical_html = "\n".join(_item_html(i) for i in mechanical) or '<p class="muted">None.</p>'

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Library review queue</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 20px 14px 64px;
    background: #0f3138; color: #eef7f8;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    line-height: 1.5; font-size: 14px;
  }}
  h1 {{ font-size: 21px; margin: 0 0 4px; }}
  h2 {{
    font-size: 13px; text-transform: uppercase; letter-spacing: .08em;
    color: #a3e4d7; margin: 30px 0 12px;
    border-bottom: 1px solid #1a4550; padding-bottom: 6px;
  }}
  .subtitle {{ color: #7fa8b0; font-size: 13px; margin: 0 0 6px; }}
  .subtitle strong {{ color: #f49342; }}
  .card {{
    background: #123f4a; border: 1px solid #1c525d; border-left: 3px solid #1c525d;
    border-radius: 14px; padding: 13px 15px; margin-bottom: 11px; max-width: 780px;
  }}
  .card.needs-judgment {{ border-left-color: #45afc6; }}
  .card.has-weak {{ border-left-color: #f49342; border-color: #f49342; }}
  .card.file-header {{ opacity: .75; }}
  .item-id {{
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 13px; font-weight: 700; color: #45afc6;
    margin-bottom: 9px; word-break: break-word;
  }}
  .badge {{
    display: inline-block; margin-left: 8px; padding: 1px 8px;
    background: #f49342; color: #0f3138; border-radius: 999px;
    font-family: inherit; font-size: 10.5px; font-weight: 700;
    letter-spacing: .04em; text-transform: uppercase; vertical-align: middle;
  }}
  .row {{ font-size: 13px; margin: 3px 0; }}
  .label {{
    display: inline-block; min-width: 74px;
    color: #7fa8b0; text-transform: uppercase;
    font-size: 10px; letter-spacing: .06em;
  }}
  .tag {{ color: #a3e4d7; font-weight: 700; }}
  .source {{
    display: inline-block; background: #0e3a44; border: 1px solid #1c6478;
    border-radius: 999px; padding: 2px 10px; margin: 2px 4px 2px 0; font-size: 12px;
  }}
  .source-weak {{
    background: #f49342; border-color: #f49342; color: #0f3138; font-weight: 700;
  }}
  .weigh {{
    margin-left: 7px; padding-left: 7px; border-left: 1px solid #0f3138;
    font-size: 10px; text-transform: uppercase; letter-spacing: .04em;
  }}
  .claim {{
    margin-top: 10px; padding-top: 10px; border-top: 1px solid #1a4550;
    font-size: 12.5px; color: #7fa8b0; white-space: pre-wrap; overflow-wrap: break-word;
  }}
  .muted {{ color: #7fa8b0; }}
</style>
</head>
<body>
<h1>Library review queue</h1>
<p class="subtitle">{len(needs)} needing judgment &middot; {len(mechanical)} mechanical &middot;
<strong>{len(weak)} resting on a ~/&#9888; source</strong></p>

<h2>Needs judgment ({len(needs)})</h2>
{needs_html}

<h2>Mechanical ({len(mechanical)})</h2>
{mechanical_html}
</body>
</html>
"""
