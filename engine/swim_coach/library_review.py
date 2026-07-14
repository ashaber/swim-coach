"""Parse review-pending ("UNREVIEWED") blocks out of `library/*.md`.

Pure parsing module -- no side effects, no writes, no LLM/network calls.
`cli.py`'s `review-queue` and `review-accept` subcommands are the only
callers; they own all I/O (reading the library tree, writing an accepted
file back, printing JSON/HTML).

Why this exists: per `library/00-conventions.md`, a freshly-authored or
freshly-changed topic-file section is marked `UNREVIEWED` inline until
Andrew reviews it. Grepping for that tag and manually working out which
hits actually need judgment (an evidence claim resting on a shaky source)
versus which are just an engineering default waiting for a rubber stamp
was the exact pain point this module and its CLI commands remove.

Marker variety actually present in `library/` (grepped, not invented --
see PR description for the full account):
  - `**UNREVIEWED**` standalone (e.g. `04-css-intensity-anchors.md`'s
    "Coach judgment / UNREVIEWED" open-question line combines this with a
    tag word -- see below).
  - `**Coach judgment, UNREVIEWED.**` (`07-strength-dryland.md`).
  - `**Coach judgment / UNREVIEWED**` (`04-css-intensity-anchors.md`).
  - A file-level marker in `07-strength-dryland.md`'s opening paragraph
    (nearest preceding heading is the file's own H1).
  - Prose *mentions* of the word in `INDEX.md` (a table cell mirroring a
    topic file's overall status -- not itself a claim; `review-accept`
    writes to it but never scans it for items), `reference_list.md` (one
    source's own quality flag, not a library claim) and
    `00-conventions.md` (documentation of the convention itself, using the
    word as its own example). All three are meta files, not topic files
    with reviewable claims, so they're excluded from item-scanning below
    -- see `META_FILES`. `research-dossiers/` mentions are raw research
    input, never claims either, and aren't matched by the `library/*.md`
    glob (dossier filenames are dated, not `NN-*.md`); dossiers are only
    ever consulted as *provenance* for an item (`find_dossier`), never
    scanned for items of their own.

Only a **bold** span containing "UNREVIEWED" counts as a marker (see
`MARKER_RE`) -- `07-strength-dryland.md`'s "Open questions" section
restates the dosing gap in a plain `` `UNREVIEWED` `` code span, which is
deliberately NOT re-matched as a second item; it's the same underlying gap
already tracked by the bold marker earlier in the file, not a new claim.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# --- files excluded from item-scanning (see module docstring) --------------

META_FILES = {"INDEX.md", "reference_list.md", "00-conventions.md"}

# --- regexes -----------------------------------------------------------------

# A bold span containing the word UNREVIEWED. Captures the inner text (group
# 1) so `strip_marker` can edit just that span.
MARKER_RE = re.compile(r"\*\*([^*\n]*\bUNREVIEWED\b[^*\n]*)\*\*")

# Any markdown heading, any level. Section boundaries (for "nearest
# preceding heading" + "claim/section text") are the span from one heading
# to the next (any level) or EOF -- same scoping style as
# tests/unit/test_library_discipline.py's `find_adapted_blocks`.
HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$", re.MULTILINE)

TAG_RE = re.compile(r"\[(EVIDENCE|ADAPTED):\s*([^\]]*)\]")
# Negative lookbehind for a backtick: a backtick-wrapped `` `Confidence: X` ``
# is always an inline-code *reference* to some other section's rating (seen
# in 07-strength-dryland.md's intro, citing 04's grade), never this block's
# own -- a real confidence assertion is always bare or **bold**, never
# backtick-wrapped (grepped, not assumed).
CONFIDENCE_RE = re.compile(r"(?<!`)Confidence:\**\s*([A-Za-z]+(?:-[A-Za-z]+)*)")
TEST_RE = re.compile(r"\*{0,2}Test:\*{0,2}\s*(.+?)(?=\n\n|\Z)", re.DOTALL)
COACH_JUDGMENT_RE = re.compile(r"Coach judgment", re.IGNORECASE)

# Citation shape reused from tests/unit/test_library_discipline.py's
# CITATION_RE: capitalized name-like token(s) (Unicode-aware), optionally
# "et al.", immediately followed by "(YYYY)".
_NAME_TOKEN = r"[A-Z][\w'\-]*\.?"
_JOIN = r"(?:,\s*|\s*&\s*|\s+and\s+|\s+)"
CITATION_RE = re.compile(
    rf"(?P<name>{_NAME_TOKEN}(?:{_JOIN}{_NAME_TOKEN})*)(?:,?\s*et\s+al\.)?"
    rf"\s*\((?P<year>(?:19|20)\d{{2}})\)"
)

# reference_list.md bullet lead-in: "- **<✓/~/⚠ markers><space><key text>**".
REF_ENTRY_RE = re.compile(r"^- \*\*([✓~⚠]+)\s*(.+?)\*\*", re.MULTILINE)

LIBRARY_FILE_MENTION_RE = re.compile(r"library/([A-Za-z0-9_.\-]+\.md)")


def slugify(heading: str) -> str:
    """Deterministic slug for a markdown heading: lowercase, markdown
    emphasis/code markers stripped, non-alphanumeric runs collapsed to a
    single hyphen, leading/trailing hyphens trimmed."""
    text = heading.strip().lower()
    text = re.sub(r"[`*_]", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    text = re.sub(r"-{2,}", "-", text)
    return text or "section"


def sections(text: str) -> list[tuple[str, int, int]]:
    """(heading_text, start_offset, end_offset) spans, any heading level.

    A span runs from its heading line's start to the next heading's start
    (any level) or EOF. Every real topic file opens with an H1, so there's
    no "before the first heading" case in practice; the defensive fallback
    below (whole file, heading="") only fires for a headingless fixture."""
    matches = list(HEADING_RE.finditer(text))
    if not matches:
        return [("", 0, len(text))]
    spans = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        spans.append((m.group(2).strip(), m.start(), end))
    return spans


def _section_slugs(headings: list[str]) -> list[str]:
    """Per-file disambiguated slugs, one per heading, in document order.

    Disambiguation is computed over *all* headings in the file (not just
    ones currently carrying a pending marker) so that accepting one item
    can never shift another item's id on a later scan -- id stability
    holds across `review-accept` calls, not just across repeated scans of
    an unchanged file."""
    counts: dict[str, int] = {}
    out = []
    for heading in headings:
        base = slugify(heading)
        counts[base] = counts.get(base, 0) + 1
        n = counts[base]
        out.append(base if n == 1 else f"{base}-{n}")
    return out


def file_heading_ids(filename: str, text: str) -> set[str]:
    """Every id (`filename#slug`) producible for *any* heading in this file,
    marker or not. Used by `review-accept` to tell "already accepted" (a
    real heading, marker already gone) apart from "no such id" (typo)."""
    headings = [h for h, _, _ in sections(text)]
    return {f"{filename}#{slug}" for slug in _section_slugs(headings)}


# --- reference_list.md parsing -----------------------------------------------


@dataclass(frozen=True)
class RefEntry:
    """One `reference_list.md` bullet: its ✓/~/⚠ marker(s) and key text
    (author/title + year, verbatim from the bullet's bold lead-in)."""

    markers: str
    key: str


def parse_reference_list(text: str) -> list[RefEntry]:
    return [RefEntry(markers=m.group(1), key=m.group(2).strip()) for m in REF_ENTRY_RE.finditer(text)]


def candidate_surnames(name_blob: str) -> list[str]:
    """Split a matched citation's name blob into plausible surname tokens
    (drops bare initials, which are noise for matching) -- mirrors
    tests/unit/test_library_discipline.py's helper of the same purpose."""
    tokens = re.split(r"[,&]|\s+and\s+|\s+", name_blob)
    return [t.strip(". \n\t") for t in tokens if len(t.strip(". \n\t")) > 2]


@dataclass(frozen=True)
class SourceCitation:
    """A `reference_list.md` entry resolved as cited by a review item,
    carrying that entry's own ✓/~/⚠ verification marker(s) -- the signal a
    reviewer needs to weigh an `[ADAPTED]`/`[EVIDENCE]` claim."""

    markers: str
    key: str


def resolve_citations(claim_text: str, entries: list[RefEntry]) -> tuple[SourceCitation, ...]:
    """Every `entries` item plausibly cited by `claim_text`, in entry order,
    each deduplicated once. Two match strategies, either sufficient:
      1. An "Author(s) (YYYY)"-shaped citation in `claim_text` whose
         surname and year both appear in the entry's key text.
      2. The entry's key text appears verbatim as a substring of
         `claim_text` (catches title-only mentions with no inline year,
         e.g. citing `reference_list.md`'s "Sex differences in marathon
         pacing" entry by title)."""
    found: dict[str, SourceCitation] = {}

    citations = list(CITATION_RE.finditer(claim_text))
    for entry in entries:
        if entry.key in found:
            continue
        for m in citations:
            year = m.group("year")
            if year not in entry.key:
                continue
            surnames = candidate_surnames(m.group("name"))
            if any(s in entry.key for s in surnames):
                found[entry.key] = SourceCitation(entry.markers, entry.key)
                break

    for entry in entries:
        if entry.key in found:
            continue
        if entry.key in claim_text:
            found[entry.key] = SourceCitation(entry.markers, entry.key)

    return tuple(found.values())


# --- dossier provenance -------------------------------------------------------


def find_dossier(filename: str, dossiers_dir: Path) -> str | None:
    """The `research-dossiers/` file (if any) that explicitly names
    `library/{filename}` as its authoring target -- dossiers consistently
    say so in their own header (e.g. "candidate `library/10-recovery-
    hrv.md`" / "used to author ... in `library/10-recovery-hrv.md`"), so an
    exact substring match is precise rather than a fuzzy heuristic.
    Deterministic: first match in sorted filename order."""
    if not dossiers_dir.exists():
        return None
    target = f"library/{filename}"
    for path in sorted(dossiers_dir.glob("*.md")):
        if target in path.read_text(encoding="utf-8"):
            return path.name
    return None


# --- review items --------------------------------------------------------------

NEEDS_JUDGMENT = "needs-judgment"
MECHANICAL = "mechanical"


@dataclass(frozen=True)
class ReviewItem:
    id: str
    file: str
    heading: str
    marker_text: str
    claim_text: str
    tag_kind: str | None  # "EVIDENCE" | "ADAPTED" | "Coach judgment" | None
    tag_value: str | None  # e.g. "swim", "cycling/running" (EVIDENCE/ADAPTED only)
    confidence: str | None
    test: str | None
    sources: tuple[SourceCitation, ...]
    dossier: str | None
    classification: str  # NEEDS_JUDGMENT | MECHANICAL
    marker_start: int  # offset of the full "**...**" span in the file's text
    marker_end: int

    @property
    def tag_display(self) -> str | None:
        if self.tag_kind in ("EVIDENCE", "ADAPTED"):
            return f"{self.tag_kind}: {self.tag_value}"
        return self.tag_kind

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "file": self.file,
            "heading": self.heading,
            "marker_text": self.marker_text,
            "claim_text": self.claim_text,
            "tag": self.tag_display,
            "confidence": self.confidence,
            "test": self.test,
            "sources": [{"markers": s.markers, "key": s.key} for s in self.sources],
            "dossier": self.dossier,
            "classification": self.classification,
        }


def _classify(tag_kind: str | None) -> str:
    """needs-judgment: an [EVIDENCE]/[ADAPTED] claim -- is the (often
    cross-discipline) inference sound? mechanical: a bare `Coach judgment:`
    engineering default, or a bare file-status flag with no evidence tag at
    all -- just needs an OK, nothing to weigh."""
    if tag_kind in ("EVIDENCE", "ADAPTED"):
        return NEEDS_JUDGMENT
    return MECHANICAL


def _extract_tag(claim_text: str) -> tuple[str | None, str | None]:
    tag_match = TAG_RE.search(claim_text)
    if tag_match:
        return tag_match.group(1), tag_match.group(2).strip()
    if COACH_JUDGMENT_RE.search(claim_text):
        return "Coach judgment", None
    return None, None


def scan_file(
    filename: str,
    text: str,
    ref_entries: list[RefEntry],
    dossiers_dir: Path,
) -> list[ReviewItem]:
    """Every review-pending item in one topic file's text."""
    section_spans = sections(text)
    slugs = _section_slugs([h for h, _, _ in section_spans])
    items: list[ReviewItem] = []

    for (heading, start, end), slug in zip(section_spans, slugs):
        section_text = text[start:end]
        for m in MARKER_RE.finditer(section_text):
            marker_start = start + m.start()
            marker_end = start + m.end()
            # claim/section text: the section's body, heading line excluded.
            heading_line_end = section_text.find("\n")
            body = section_text[heading_line_end + 1 :] if heading_line_end != -1 else ""
            claim_text = body.strip()

            tag_kind, tag_value = _extract_tag(claim_text)
            confidence_match = CONFIDENCE_RE.search(claim_text)
            test_match = TEST_RE.search(claim_text)

            items.append(
                ReviewItem(
                    id=f"{filename}#{slug}",
                    file=filename,
                    heading=heading,
                    marker_text=m.group(1).strip(),
                    claim_text=claim_text,
                    tag_kind=tag_kind,
                    tag_value=tag_value,
                    confidence=confidence_match.group(1) if confidence_match else None,
                    test=test_match.group(1).strip() if test_match else None,
                    sources=resolve_citations(claim_text, ref_entries),
                    dossier=find_dossier(filename, dossiers_dir),
                    classification=_classify(tag_kind),
                    marker_start=marker_start,
                    marker_end=marker_end,
                )
            )
    return items


def scan_library(library_dir: Path) -> list[ReviewItem]:
    """Every review-pending item across `library/*.md`, excluding
    `META_FILES` (see module docstring). Deterministic order: files sorted
    by name, items within a file in document order."""
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
        text = path.read_text(encoding="utf-8")
        items.extend(scan_file(path.name, text, ref_entries, dossiers_dir))
    return items


# --- marker stripping (review-accept) ----------------------------------------


INDEX_UNREVIEWED_SUFFIX = "**UNREVIEWED**, pending human review."
INDEX_REVIEWED_SUFFIX = "Human-reviewed."


def mark_index_reviewed(index_text: str, filename: str) -> tuple[str, bool]:
    """If `INDEX.md`'s row for `filename` still ends with the UNREVIEWED
    status sentence, replace it with "Human-reviewed." Returns
    `(new_text, changed)`. Scoped to that file's own row (matched by its
    backtick-quoted filename at the row's start) so this can never touch
    another file's status by accident, and is a no-op if the row already
    says something else (e.g. already reviewed)."""
    row_prefix = f"| `{filename}` |"
    lines = index_text.split("\n")
    changed = False
    for i, line in enumerate(lines):
        if line.startswith(row_prefix) and INDEX_UNREVIEWED_SUFFIX in line:
            lines[i] = line.replace(INDEX_UNREVIEWED_SUFFIX, INDEX_REVIEWED_SUFFIX)
            changed = True
            break
    return "\n".join(lines), changed


def strip_marker(text: str, marker_start: int, marker_end: int) -> str:
    """Remove exactly the UNREVIEWED marker at `text[marker_start:marker_end]`
    (a `**...**` span matched by `MARKER_RE`), editing only that span (plus,
    for a bare standalone `**UNREVIEWED**` flag, one immediately-following
    ': ' or '. ' lead-in that existed solely to introduce it). Every other
    byte in `text` is untouched -- never rewrites claim text, only removes
    the flag itself:
      - "**Coach judgment, UNREVIEWED.**" -> "**Coach judgment.**"
      - "**Coach judgment / UNREVIEWED**" -> "**Coach judgment**"
      - "**UNREVIEWED**: <prose>"         -> "<prose>" (lead-in swallowed)
      - anything else containing the bare word -> word removed, wrapper kept
    """
    match_text = text[marker_start:marker_end]
    inner = match_text[2:-2]  # strip the outer "**"

    comma_stripped = re.sub(r",\s*UNREVIEWED\b", "", inner)
    if comma_stripped != inner:
        return text[:marker_start] + f"**{comma_stripped}**" + text[marker_end:]

    slash_stripped = re.sub(r"\s*/\s*UNREVIEWED\b", "", inner)
    if slash_stripped != inner:
        return text[:marker_start] + f"**{slash_stripped}**" + text[marker_end:]

    if inner.strip() == "UNREVIEWED":
        rest = text[marker_end:]
        lead_in = re.match(r"[:.]\s+", rest)
        new_rest = rest[lead_in.end() :] if lead_in else rest
        return text[:marker_start] + new_rest

    fallback = re.sub(r"\s*\bUNREVIEWED\b\s*", " ", inner).strip()
    return text[:marker_start] + f"**{fallback}**" + text[marker_end:]


# --- HTML rendering ------------------------------------------------------------


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
    loud = "⚠" in source.markers or "~" in source.markers
    css_class = "source source-loud" if loud else "source"
    return f'<span class="{css_class}">{_esc(source.markers)} {_esc(source.key)}</span>'


def _item_html(item: ReviewItem) -> str:
    tag = _esc(item.tag_display) or "untagged"
    confidence = f'<div class="row"><span class="label">Confidence</span> {_esc(item.confidence)}</div>' if item.confidence else ""
    test = f'<div class="row"><span class="label">Test</span> {_esc(item.test)}</div>' if item.test else ""
    dossier = f'<div class="row"><span class="label">Dossier</span> {_esc(item.dossier)}</div>' if item.dossier else ""
    if item.sources:
        sources = '<div class="row sources"><span class="label">Sources</span> ' + " ".join(
            _source_html(s) for s in item.sources
        ) + "</div>"
    else:
        sources = '<div class="row"><span class="label">Sources</span> <span class="muted">none cited</span></div>'

    card_class = "card needs-judgment" if item.classification == NEEDS_JUDGMENT else "card mechanical"
    return f"""
    <div class="{card_class}">
      <div class="item-id">{_esc(item.id)}</div>
      <div class="row"><span class="label">File</span> {_esc(item.file)}</div>
      <div class="row"><span class="label">Heading</span> {_esc(item.heading)}</div>
      <div class="row"><span class="label">Tag</span> <span class="tag">{tag}</span></div>
      {confidence}
      {test}
      {sources}
      {dossier}
      <div class="claim">{_esc(item.claim_text)}</div>
    </div>
    """


def render_html(items: list[ReviewItem]) -> str:
    """A self-contained HTML page (inline CSS only, no external assets/
    fonts/CDN) rendering the review queue, needs-judgment items first, in
    the project's "Bioluminescent Dusk" palette -- see
    `design/channel-dragon-handoff/README.md`'s Design Tokens section."""
    needs = [i for i in items if i.classification == NEEDS_JUDGMENT]
    mechanical = [i for i in items if i.classification == MECHANICAL]

    needs_html = "\n".join(_item_html(i) for i in needs) or '<p class="muted">None.</p>'
    mechanical_html = "\n".join(_item_html(i) for i in mechanical) or '<p class="muted">None.</p>'

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Library review queue</title>
<style>
  :root {{
    color-scheme: dark;
  }}
  body {{
    margin: 0;
    padding: 24px 16px 64px;
    background: #0f3138;
    color: #eef7f8;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    line-height: 1.5;
  }}
  h1 {{
    font-size: 22px;
    margin: 0 0 4px;
  }}
  h2 {{
    font-size: 15px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #a3e4d7;
    margin: 32px 0 12px;
  }}
  .subtitle {{
    color: #7fa8b0;
    font-size: 13px;
    margin: 0 0 8px;
  }}
  .card {{
    background: #123f4a;
    border: 1px solid #1c525d;
    border-radius: 14px;
    padding: 14px 16px;
    margin-bottom: 12px;
    max-width: 720px;
  }}
  .card.needs-judgment {{
    border-color: #f49342;
  }}
  .item-id {{
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 14px;
    font-weight: 700;
    color: #45afc6;
    margin-bottom: 8px;
    word-break: break-all;
  }}
  .row {{
    font-size: 13px;
    color: #eef7f8;
    margin: 4px 0;
  }}
  .label {{
    color: #7fa8b0;
    text-transform: uppercase;
    font-size: 10.5px;
    letter-spacing: 0.06em;
    margin-right: 6px;
  }}
  .tag {{
    color: #a3e4d7;
    font-weight: 700;
  }}
  .claim {{
    margin-top: 10px;
    padding-top: 10px;
    border-top: 1px solid #1a4550;
    font-size: 13px;
    color: #eef7f8;
    white-space: pre-wrap;
  }}
  .muted {{
    color: #7fa8b0;
  }}
  .source {{
    display: inline-block;
    background: #0e3a44;
    border: 1px solid #1c6478;
    border-radius: 999px;
    padding: 2px 10px;
    margin: 2px 4px 2px 0;
    font-size: 12px;
  }}
  .source-loud {{
    background: #4a2410;
    border-color: #f49342;
    color: #f49342;
    font-weight: 700;
  }}
</style>
</head>
<body>
<h1>Library review queue</h1>
<p class="subtitle">{len(needs)} needing judgment, {len(mechanical)} mechanical</p>

<h2>Needs judgment ({len(needs)})</h2>
{needs_html}

<h2>Mechanical ({len(mechanical)})</h2>
{mechanical_html}

</body>
</html>
"""
