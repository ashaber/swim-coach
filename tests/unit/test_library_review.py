"""Tests for swim_coach.library_review and the cli.py review-queue /
review-accept commands built on it.

Fixture strings cover every UNREVIEWED marker form actually present in
library/ today (grepped, see library_review.py's module docstring):
  - a bare file-level "**UNREVIEWED**: <prose>" marker under the file's H1
  - "**Coach judgment, UNREVIEWED.**" (comma-joined)
  - "**Coach judgment / UNREVIEWED**" (slash-joined)
plus the deliberately-NOT-matched plain-code-span "`UNREVIEWED`" mention,
and an [ADAPTED]/[EVIDENCE] needs-judgment fixture with reference_list.md
source resolution (including a `~`/`⚠`-marked source).

No LLM calls, no network, no subprocess -- pure functions plus `cli.main()`
driven directly against tmp_path, same style as test_cli.py.
"""

from __future__ import annotations

import json
from pathlib import Path

from swim_coach.cli import main
from swim_coach.library_review import (
    MECHANICAL,
    NEEDS_JUDGMENT,
    RefEntry,
    file_heading_ids,
    mark_index_reviewed,
    parse_reference_list,
    render_html,
    resolve_citations,
    scan_file,
    scan_library,
    slugify,
    strip_marker,
)

# --- fixture builders --------------------------------------------------------------

FILE_LEVEL_MARKER_TEXT = """# Strength & dryland programming

Grounds some engine constants. **UNREVIEWED**: this file is agent-authored
and needs human review before being treated as settled grounding truth.

## What's actually in a session: exercise selection and dosing

**Coach judgment, UNREVIEWED.** Nothing in `reference_list.md` specifies
exercise selection; a practical default is used pending review.

## Open questions / not yet covered here

- Exercise dosing beyond the default above is `UNREVIEWED` coach judgment,
  not evidence-backed.
"""

SLASH_MARKER_TEXT = """# CSS & intensity anchors

## Open questions / not yet covered here

- HR-based anchoring isn't implemented yet. **Coach judgment / UNREVIEWED**:
  flagged as a gap, not a decision.
"""

NEEDS_JUDGMENT_TEXT = """# Fake topic file

## A shaky cross-discipline claim

**[ADAPTED: cycling] Confidence: low.** Some claim adapting Smith et al.
(2020) to swimming. **Test:** check X against Y for this athlete.
"""

REFERENCE_LIST_FIXTURE = """# Research Reference List

## Some section

- **~ Smith J.A. et al. (2020)** — a provisional finding, author legitimate
  but this specific paper not individually verified.
- **✓⚠ Jones B. (2019)** — verified, with a caveat attached.
- **✓ Verified Title Only Source** — a practical resource cited by title.
"""


def _write(path: Path, name: str, text: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    file_path = path / name
    file_path.write_text(text, encoding="utf-8")
    return file_path


def _out(capsys):
    return json.loads(capsys.readouterr().out.strip())


# --- slugify -----------------------------------------------------------------------


def test_slugify_basic_heading():
    assert slugify("Session duration: 45 minutes") == "session-duration-45-minutes"


def test_slugify_strips_markdown_and_collapses_punctuation():
    assert slugify("What's actually in a session: exercise selection") == (
        "what-s-actually-in-a-session-exercise-selection"
    )


def test_slugify_ampersand_and_h1():
    assert slugify("Strength & dryland programming") == "strength-dryland-programming"


# --- marker detection: every real form, plus the deliberate non-match ------------


def test_file_level_marker_keyed_to_h1():
    items = scan_file("07-strength-dryland.md", FILE_LEVEL_MARKER_TEXT, [], Path("/nonexistent"))
    file_level = next(i for i in items if i.heading == "Strength & dryland programming")
    assert file_level.id == "07-strength-dryland.md#strength-dryland-programming"
    assert file_level.marker_text == "UNREVIEWED"


def test_comma_joined_coach_judgment_marker_detected():
    items = scan_file("07-strength-dryland.md", FILE_LEVEL_MARKER_TEXT, [], Path("/nonexistent"))
    dosing = next(i for i in items if "exercise selection" in i.heading)
    assert dosing.marker_text == "Coach judgment, UNREVIEWED."
    assert dosing.tag_kind == "Coach judgment"


def test_slash_joined_coach_judgment_marker_detected():
    items = scan_file("04-css-intensity-anchors.md", SLASH_MARKER_TEXT, [], Path("/nonexistent"))
    assert len(items) == 1
    assert items[0].marker_text == "Coach judgment / UNREVIEWED"


def test_plain_code_span_unreviewed_is_not_a_second_marker():
    # The "Open questions" section in FILE_LEVEL_MARKER_TEXT mentions
    # `UNREVIEWED` in a plain code span (not bold) -- restating the dosing
    # gap already tracked by the earlier bold marker. It must not produce
    # its own queue item.
    items = scan_file("07-strength-dryland.md", FILE_LEVEL_MARKER_TEXT, [], Path("/nonexistent"))
    assert len(items) == 2
    assert not any(i.heading == "Open questions / not yet covered here" for i in items)


# --- heading association + id stability -----------------------------------------


def test_heading_association_nearest_preceding():
    items = scan_file("07-strength-dryland.md", FILE_LEVEL_MARKER_TEXT, [], Path("/nonexistent"))
    headings = {i.heading for i in items}
    assert headings == {
        "Strength & dryland programming",
        "What's actually in a session: exercise selection and dosing",
    }


def test_ids_stable_across_repeated_scans():
    first = [i.id for i in scan_file("f.md", FILE_LEVEL_MARKER_TEXT, [], Path("/nonexistent"))]
    second = [i.id for i in scan_file("f.md", FILE_LEVEL_MARKER_TEXT, [], Path("/nonexistent"))]
    assert first == second


def test_id_disambiguation_on_heading_collision():
    text = """# Topic

## Repeated heading

**UNREVIEWED**: first one.

## Repeated heading

**UNREVIEWED**: second one.
"""
    items = scan_file("dup.md", text, [], Path("/nonexistent"))
    ids = [i.id for i in items]
    assert ids == ["dup.md#repeated-heading", "dup.md#repeated-heading-2"]


def test_disambiguation_survives_removal_of_earlier_item():
    # If the first "Repeated heading" section's marker is stripped, the
    # second section's id must NOT shift to the base slug -- disambiguation
    # is computed over all headings, not just currently-pending ones.
    text = """# Topic

## Repeated heading

no marker here anymore.

## Repeated heading

**UNREVIEWED**: still pending.
"""
    items = scan_file("dup.md", text, [], Path("/nonexistent"))
    assert len(items) == 1
    assert items[0].id == "dup.md#repeated-heading-2"


# --- classification ----------------------------------------------------------------


def test_bare_file_level_marker_classifies_mechanical():
    items = scan_file("07-strength-dryland.md", FILE_LEVEL_MARKER_TEXT, [], Path("/nonexistent"))
    file_level = next(i for i in items if i.heading == "Strength & dryland programming")
    assert file_level.classification == MECHANICAL


def test_coach_judgment_marker_classifies_mechanical():
    items = scan_file("f.md", SLASH_MARKER_TEXT, [], Path("/nonexistent"))
    assert items[0].classification == MECHANICAL


def test_adapted_tag_classifies_needs_judgment():
    ref_entries = parse_reference_list(REFERENCE_LIST_FIXTURE)
    text = NEEDS_JUDGMENT_TEXT.replace(
        "Some claim adapting", "**UNREVIEWED** Some claim adapting"
    )
    items = scan_file("fake.md", text, ref_entries, Path("/nonexistent"))
    assert len(items) == 1
    assert items[0].classification == NEEDS_JUDGMENT
    assert items[0].tag_kind == "ADAPTED"
    assert items[0].tag_value == "cycling"
    assert items[0].confidence == "low"
    assert items[0].test == "check X against Y for this athlete."


# --- source resolution, including a ~/⚠-marked source ---------------------------


def test_resolve_citations_author_year_match_surfaces_verification_marker():
    ref_entries = parse_reference_list(REFERENCE_LIST_FIXTURE)
    claim = "Adapting Smith et al. (2020) to this population."
    sources = resolve_citations(claim, ref_entries)
    assert len(sources) == 1
    assert sources[0].markers == "~"
    assert sources[0].key == "Smith J.A. et al. (2020)"


def test_resolve_citations_caveat_marker_surfaces():
    ref_entries = parse_reference_list(REFERENCE_LIST_FIXTURE)
    claim = "Per Jones B. (2019), the effect held."
    sources = resolve_citations(claim, ref_entries)
    assert len(sources) == 1
    assert sources[0].markers == "✓⚠"


def test_resolve_citations_title_only_match():
    ref_entries = parse_reference_list(REFERENCE_LIST_FIXTURE)
    claim = "See reference_list.md's 'Verified Title Only Source' for background."
    sources = resolve_citations(claim, ref_entries)
    assert len(sources) == 1
    assert sources[0].key == "Verified Title Only Source"


def test_resolve_citations_no_match_returns_empty():
    ref_entries = parse_reference_list(REFERENCE_LIST_FIXTURE)
    assert resolve_citations("Nothing cited here.", ref_entries) == ()


def test_needs_judgment_item_with_shaky_source_end_to_end():
    # The scenario the task calls out explicitly: an [ADAPTED] Confidence:
    # low claim resting on a `~`-marked source.
    ref_entries = parse_reference_list(REFERENCE_LIST_FIXTURE)
    items = scan_file("fake.md", NEEDS_JUDGMENT_TEXT, ref_entries, Path("/nonexistent"))
    assert len(items) == 0  # no UNREVIEWED marker in this fixture yet
    marked = NEEDS_JUDGMENT_TEXT.replace(
        "**[ADAPTED", "**UNREVIEWED** **[ADAPTED"
    )
    items = scan_file("fake.md", marked, ref_entries, Path("/nonexistent"))
    assert len(items) == 1
    item = items[0]
    assert item.classification == NEEDS_JUDGMENT
    assert len(item.sources) == 1
    assert item.sources[0].markers == "~"


# --- dossier provenance -------------------------------------------------------------


def test_find_dossier_matches_explicit_target_mention(tmp_path):
    dossiers_dir = tmp_path / "research-dossiers"
    _write(
        dossiers_dir,
        "2026-07-10-recovery.md",
        "# Recovery Dossier — candidate `library/10-recovery-hrv.md`\n",
    )
    items = scan_file("10-recovery-hrv.md", FILE_LEVEL_MARKER_TEXT, [], dossiers_dir)
    assert all(i.dossier == "2026-07-10-recovery.md" for i in items)


def test_find_dossier_none_when_no_dossier_names_the_file(tmp_path):
    dossiers_dir = tmp_path / "research-dossiers"
    _write(dossiers_dir, "2026-07-10-recovery.md", "# Dossier for `library/10-recovery-hrv.md`\n")
    items = scan_file("07-strength-dryland.md", FILE_LEVEL_MARKER_TEXT, [], dossiers_dir)
    assert all(i.dossier is None for i in items)


# --- scan_library: META_FILES excluded, real library() integration --------------


def test_scan_library_excludes_meta_files(tmp_path):
    library_dir = tmp_path / "library"
    _write(library_dir, "INDEX.md", "**UNREVIEWED**, pending human review.\n")
    _write(library_dir, "reference_list.md", REFERENCE_LIST_FIXTURE)
    _write(library_dir, "00-conventions.md", "# Conventions\n\nmarked **`UNREVIEWED`** inline.\n")
    _write(library_dir, "07-strength-dryland.md", FILE_LEVEL_MARKER_TEXT)

    items = scan_library(library_dir)
    files = {i.file for i in items}
    assert files == {"07-strength-dryland.md"}


def test_real_library_current_known_items_and_classification():
    # Regression pin on the real repo's current state -- 07-strength-
    # dryland.md's two open items and 04-css-intensity-anchors.md's
    # coach-judgment line, all mechanical (no [EVIDENCE]/[ADAPTED] tag).
    # If library/ content changes, update this pin deliberately (same
    # spirit as test_library_discipline.py's KNOWN_* pins).
    repo_root = Path(__file__).resolve().parents[2]
    items = scan_library(repo_root / "library")
    ids = {i.id: i for i in items}
    assert "07-strength-dryland.md#strength-dryland-programming" in ids
    assert "07-strength-dryland.md#what-s-actually-in-a-session-exercise-selection-and-dosing" in ids
    assert "04-css-intensity-anchors.md#open-questions-not-yet-covered-here" in ids
    assert all(item.classification == MECHANICAL for item in ids.values())


# --- strip_marker: every variant, byte-identical elsewhere ------------------------


def test_strip_marker_comma_joined():
    text = "**Coach judgment, UNREVIEWED.** Some prose follows."
    match_start = text.index("**Coach")
    match_end = text.index("**", match_start + 2) + 2
    result = strip_marker(text, match_start, match_end)
    assert result == "**Coach judgment.** Some prose follows."


def test_strip_marker_slash_joined():
    text = "**Coach judgment / UNREVIEWED**: flagged as a gap."
    match_start = text.index("**Coach")
    match_end = text.index("**", match_start + 2) + 2
    result = strip_marker(text, match_start, match_end)
    assert result == "**Coach judgment**: flagged as a gap."


def test_strip_marker_bare_standalone_swallows_leadin():
    text = "sentence before. **UNREVIEWED**: this file needs review."
    match_start = text.index("**UNREVIEWED")
    match_end = match_start + len("**UNREVIEWED**")
    result = strip_marker(text, match_start, match_end)
    assert result == "sentence before. this file needs review."


def test_strip_marker_byte_identical_outside_marker_span():
    items = scan_file("07-strength-dryland.md", FILE_LEVEL_MARKER_TEXT, [], Path("/nonexistent"))
    dosing = next(i for i in items if "exercise selection" in i.heading)
    new_text = strip_marker(FILE_LEVEL_MARKER_TEXT, dosing.marker_start, dosing.marker_end)
    before_prefix = FILE_LEVEL_MARKER_TEXT[: dosing.marker_start]
    after_suffix = FILE_LEVEL_MARKER_TEXT[dosing.marker_end :]
    assert new_text.startswith(before_prefix)
    assert new_text.endswith(after_suffix)
    assert "UNREVIEWED" not in new_text[dosing.marker_start : dosing.marker_start + len("**Coach judgment.**")]


# --- file_heading_ids / mark_index_reviewed ---------------------------------------


def test_file_heading_ids_includes_headings_without_markers():
    ids = file_heading_ids("f.md", FILE_LEVEL_MARKER_TEXT)
    assert "f.md#open-questions-not-yet-covered-here" in ids
    assert "f.md#strength-dryland-programming" in ids


def test_mark_index_reviewed_updates_only_matching_row():
    index_text = (
        "| `07-strength-dryland.md` | some summary. **UNREVIEWED**, pending human review. |\n"
        "| `10-recovery-hrv.md` | some summary. **UNREVIEWED**, pending human review. |\n"
    )
    new_text, changed = mark_index_reviewed(index_text, "07-strength-dryland.md")
    assert changed is True
    lines = new_text.split("\n")
    assert "Human-reviewed." in lines[0]
    assert "**UNREVIEWED**, pending human review." in lines[1]  # untouched


def test_mark_index_reviewed_noop_when_no_matching_row():
    index_text = "| `other-file.md` | summary. Human-reviewed. |\n"
    new_text, changed = mark_index_reviewed(index_text, "07-strength-dryland.md")
    assert changed is False
    assert new_text == index_text


# --- render_html: self-contained, no external references -------------------------


def test_render_html_has_no_external_references():
    items = scan_file("07-strength-dryland.md", FILE_LEVEL_MARKER_TEXT, [], Path("/nonexistent"))
    html = render_html(items)
    assert "http" not in html.lower()
    assert "src=" not in html.lower()
    assert "href=" not in html.lower()


def test_render_html_needs_judgment_items_appear_first():
    ref_entries = parse_reference_list(REFERENCE_LIST_FIXTURE)
    marked_needs_judgment = NEEDS_JUDGMENT_TEXT.replace("**[ADAPTED", "**UNREVIEWED** **[ADAPTED")
    needs = scan_file("needs.md", marked_needs_judgment, ref_entries, Path("/nonexistent"))
    mechanical = scan_file("f.md", SLASH_MARKER_TEXT, [], Path("/nonexistent"))
    html = render_html(needs + mechanical)
    assert html.index("needs.md#") < html.index("f.md#")
    # A ~/⚠ source must be visually distinct (its own CSS class).
    assert "source-loud" in html


# --- CLI: review-queue -------------------------------------------------------------


def _library_tree(tmp_path) -> Path:
    library_dir = tmp_path / "library"
    _write(library_dir, "INDEX.md", "| `07-strength-dryland.md` | summary. **UNREVIEWED**, pending human review. |\n")
    _write(library_dir, "reference_list.md", REFERENCE_LIST_FIXTURE)
    _write(library_dir, "07-strength-dryland.md", FILE_LEVEL_MARKER_TEXT)
    _write(library_dir, "04-css-intensity-anchors.md", SLASH_MARKER_TEXT)
    return library_dir


def test_cli_review_queue_prints_grouped_json(tmp_path, capsys):
    library_dir = _library_tree(tmp_path)
    code = main(["--library-dir", str(library_dir), "review-queue"])
    assert code == 0
    result = _out(capsys)
    assert result["counts"]["total"] == 3
    assert result["counts"]["mechanical"] == 3
    assert result["counts"]["needs_judgment"] == 0


def test_cli_review_queue_file_filter(tmp_path, capsys):
    library_dir = _library_tree(tmp_path)
    code = main(["--library-dir", str(library_dir), "review-queue", "--file", "04-css-intensity-anchors.md"])
    assert code == 0
    result = _out(capsys)
    assert result["counts"]["total"] == 1
    assert result["mechanical"][0]["file"] == "04-css-intensity-anchors.md"


def test_cli_review_queue_html_writes_self_contained_file(tmp_path, capsys):
    library_dir = _library_tree(tmp_path)
    html_path = tmp_path / "queue.html"
    code = main(["--library-dir", str(library_dir), "review-queue", "--html", str(html_path)])
    assert code == 0
    result = _out(capsys)
    assert result["html_written_to"] == str(html_path)
    html = html_path.read_text(encoding="utf-8")
    assert "http" not in html.lower()
    assert "src=" not in html.lower()


# --- CLI: review-accept -------------------------------------------------------------


def test_cli_review_accept_strips_marker_and_is_idempotent(tmp_path, capsys):
    library_dir = _library_tree(tmp_path)
    file_path = library_dir / "07-strength-dryland.md"
    before = file_path.read_text(encoding="utf-8")

    code = main(
        [
            "--library-dir",
            str(library_dir),
            "review-accept",
            "07-strength-dryland.md#strength-dryland-programming",
        ]
    )
    assert code == 0
    result = _out(capsys)
    assert result["results"] == [
        {"id": "07-strength-dryland.md#strength-dryland-programming", "status": "accepted"}
    ]
    after = file_path.read_text(encoding="utf-8")
    assert after != before
    assert "**UNREVIEWED**" not in after

    # Idempotent: accepting again is a clean no-op, not an error.
    code = main(
        [
            "--library-dir",
            str(library_dir),
            "review-accept",
            "07-strength-dryland.md#strength-dryland-programming",
        ]
    )
    assert code == 0
    result = _out(capsys)
    assert result["results"] == [
        {"id": "07-strength-dryland.md#strength-dryland-programming", "status": "already-accepted"}
    ]
    assert file_path.read_text(encoding="utf-8") == after


def test_cli_review_accept_unknown_id_is_an_error(tmp_path, capsys):
    library_dir = _library_tree(tmp_path)
    code = main(["--library-dir", str(library_dir), "review-accept", "07-strength-dryland.md#no-such-heading"])
    assert code == 1
    result = _out(capsys)
    assert "error" in result


def test_cli_review_accept_updates_index_when_last_item_clears(tmp_path, capsys):
    library_dir = _library_tree(tmp_path)
    # 07-strength-dryland.md fixture has two pending items; accept both.
    code = main(
        [
            "--library-dir",
            str(library_dir),
            "review-accept",
            "07-strength-dryland.md#strength-dryland-programming",
            "07-strength-dryland.md#what-s-actually-in-a-session-exercise-selection-and-dosing",
        ]
    )
    assert code == 0
    result = _out(capsys)
    assert result["index_updated"] == ["07-strength-dryland.md"]
    index_text = (library_dir / "INDEX.md").read_text(encoding="utf-8")
    assert "Human-reviewed." in index_text
    assert "**UNREVIEWED**, pending human review." not in index_text


def test_cli_review_accept_byte_identical_except_marker(tmp_path, capsys):
    library_dir = _library_tree(tmp_path)
    file_path = library_dir / "04-css-intensity-anchors.md"
    before = file_path.read_bytes()

    code = main(
        [
            "--library-dir",
            str(library_dir),
            "review-accept",
            "04-css-intensity-anchors.md#open-questions-not-yet-covered-here",
        ]
    )
    assert code == 0
    after = file_path.read_bytes()
    assert before != after

    # Compute the common prefix/suffix byte length; everything outside that
    # window must be the removed marker text, nothing else.
    prefix_len = 0
    while prefix_len < len(before) and prefix_len < len(after) and before[prefix_len] == after[prefix_len]:
        prefix_len += 1
    suffix_len = 0
    while (
        suffix_len < len(before) - prefix_len
        and suffix_len < len(after) - prefix_len
        and before[len(before) - 1 - suffix_len] == after[len(after) - 1 - suffix_len]
    ):
        suffix_len += 1

    removed = before[prefix_len : len(before) - suffix_len].decode("utf-8")
    added = after[prefix_len : len(after) - suffix_len].decode("utf-8")
    assert "UNREVIEWED" in removed
    assert "UNREVIEWED" not in added
