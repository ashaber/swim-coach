"""Tests for swim_coach.library_review and cli.py's review-queue /
review-accept commands.

Fixtures are modeled on the shapes actually in library/ today:
  - a freshly-drafted topic file (08-ultra-feeding.md, 13-reds-energy-
    availability.md, 07-strength-dryland.md): ONE file-level `**UNREVIEWED**`
    in the header, then many individually-tagged claim blocks in the body.
    Enumerating those claims is the whole job -- see
    test_file_level_marker_enumerates_every_claim_in_the_file.
  - a section-scoped marker (04-css-intensity-anchors.md's open-questions
    bullet), which must cover only its own section.
  - reference_list.md entries whose bold author key WRAPS ACROSS TWO LINES
    (most of the real file's entries do), carrying ✓ / ~ / ✓⚠ markers.
  - citations written backticked as `Author et al. (Year)`.

No LLM calls, no network, no subprocess -- pure functions plus `cli.main()`
driven against tmp_path, same style as test_cli.py.
"""

from __future__ import annotations

import json
from pathlib import Path

from swim_coach.cli import main
from swim_coach.library_review import (
    CLAIM,
    FILE_HEADER,
    MECHANICAL,
    NEEDS_JUDGMENT,
    all_item_ids,
    find_claim_blocks,
    find_dossier,
    find_markers,
    mark_index_reviewed,
    parse_reference_list,
    render_html,
    render_text,
    resolve_citations,
    scan_file,
    scan_library,
    slugify,
    sort_for_review,
    strip_marker,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

# --- fixtures modeled on the real files ------------------------------------------

# A freshly-drafted topic file: file-level marker + tagged claim body.
# Mirrors 08-ultra-feeding.md / 13-reds-energy-availability.md.
DRAFTED_FILE = """# Ultra feeding: the wall and in-swim carbohydrate

**UNREVIEWED** — drafted from `library/research-dossiers/2026-07-13-ultra-feeding.md`
(sources independently spot-verified); pending human review.

Covers the athlete's hottest logged question. See `00-conventions.md`.

## The 90-minute wall is not a glycogen wall

**The premise needs correcting.** A ~90-minute point is not where depletion
lands. `[ADAPTED: cycling]` Confidence: high. Time to exhaustion ran ~126 min
in `Bergstrom et al. (1967)`. **Test:** compare the wall's timing across
sessions of different intensity.

**A perceptual duration ceiling competes as an explanation.**
`[ADAPTED: running]` Confidence: medium-high. RPE is scaled against an
expected endpoint (`Tucker (2009)`, corroborated by `Eston et al. (2012)`).
**Test:** tell her a session is 2.5h rather than 90 min and see if the wall
moves.

## In-session carbohydrate feeding

**Dose ladder.** `[EVIDENCE: swim]` for the open-water application,
`[ADAPTED: cycling]` for the transporter physiology. Confidence: high. Up to
90 g/h from multiple-transportable sources, per `Shaw et al. (2014)`.
**Test:** verify tolerance on long swims, logging GI symptoms.

**Feed cadence costs less than swimmers assume.** `Coach judgment:`
practitioner convention; no controlled study measured the performance cost of
feed stops in swimming.

## Bone loading

`[EVIDENCE: swim]` Confidence: high. `Gomez-Bruton et al. (2013)` find
swimmers' bone density similar to sedentary controls.
`[ADAPTED: general-endurance]` Confidence: medium. `Hutson et al. (2021)`
argue impact loading is osteogenic and energy-cheap. **Test:** adding impact
work should cost near-zero extra session RPE.
"""

# A section-scoped marker only -- mirrors 04-css-intensity-anchors.md.
SECTION_MARKER_FILE = """# CSS & intensity anchors

## Critical Swim Speed

**[EVIDENCE: swim]** `Wakayoshi et al. (1992)` derived critical velocity.

## Open questions / not yet covered here

- HR-based anchoring isn't implemented yet. **Coach judgment / UNREVIEWED**:
  flagged as a gap, not a decision.
"""

# A file-level marker PLUS an inner section marker -- mirrors
# 07-strength-dryland.md, whose dosing section carries its own.
NESTED_MARKER_FILE = """# Strength & dryland programming

Grounds some engine constants. **UNREVIEWED**: this file is agent-authored
and needs human review.

## Why strength is in the plan

**[EVIDENCE: swim]** Dry-land RCTs show reduced shoulder pain.
Confidence: high.

## What's actually in a session

**Coach judgment, UNREVIEWED.** Nothing in `reference_list.md` specifies
exercise selection.

## Watch total load when ramping

**[EVIDENCE: swim] Confidence: low.** `Feijen et al. (2021)` found an ACWR
association with shoulder pain. **Test:** check whether pool volume also
jumped.
"""

# reference_list.md with WRAPPED bold author keys (as the real file has) and a
# title-keyed entry, spanning ✓ / ~ / ✓⚠ verification markers.
REFERENCE_LIST_FIXTURE = """# Research Reference List

**Verification legend**
- ✓ — paper verified real.
- ~ — author legitimate, this paper not individually verified.
- ⚠ — caveat attached.

## Sources

- **✓ Bergstrom J., Hermansen L., Hultman E., Saltin B. (1967)** — muscle
  glycogen and physical performance.
- **✓ Tucker R. (2009)** — the anticipatory regulation of performance.
- **~ Eston R. et al. (2012)** — effort perception; not individually
  verified.
- **✓⚠ Shaw G. et al. (2014)** — "Nutrition Considerations for Open-Water
  Swimming". **NOTE:** an IJSNEM review, not an ISSN Position Stand.
- **✓ Gomez-Bruton A., Gonzalez-Aguero A., Gomez-Cabello A., Casajus J.A.,
  Vicente-Rodriguez G. (2013)** — is bone tissue really affected by
  swimming? A systematic review.
- **✓ Hutson M.J., O'Donnell E., Brooke-Wavell K., Sale C., Blagrove R.C.
  (2021)** — effects of low energy availability on bone health.
- **✓⚠ Feijen S. et al. (2021)** — "Prediction of Shoulder Pain in Youth
  Competitive Swimmers". ACWR methodology is broadly criticized.
- **✓ Wakayoshi et al. (1992)** — Critical Swim Speed derivation.
- **✓ Dry-land shoulder-strengthening RCTs in competitive swimmers** —
  multiple studies show reduced shoulder pain.
"""


def _write(directory: Path, name: str, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def _out(capsys):
    return json.loads(capsys.readouterr().out.strip())


def _refs():
    return parse_reference_list(REFERENCE_LIST_FIXTURE)


def _scan(filename: str, text: str, dossiers_dir: Path | None = None):
    return scan_file(filename, text, _refs(), dossiers_dir or Path("/nonexistent"))


# --- slugify -----------------------------------------------------------------------


def test_slugify_basic_heading():
    assert slugify("Session duration: 45 minutes") == "session-duration-45-minutes"


def test_slugify_strips_markdown_and_collapses_punctuation():
    assert slugify("What's actually in a session") == "what-s-actually-in-a-session"


def test_slugify_ampersand():
    assert slugify("Strength & dryland programming") == "strength-dryland-programming"


# --- THE headline behavior: a file-level marker enumerates every claim ------------


def test_file_level_marker_enumerates_every_claim_in_the_file():
    """The defect this tool exists to fix: one header `**UNREVIEWED**` over a
    body of individually-tagged claims must yield one item PER CLAIM, not a
    single item for the untagged header blurb."""
    items = _scan("08-ultra-feeding.md", DRAFTED_FILE)
    claims = [i for i in items if i.item_kind == CLAIM]
    headers = [i for i in items if i.item_kind == FILE_HEADER]

    assert len(headers) == 1  # the header blurb, low-priority
    assert len(claims) == 6  # 5 tagged claims + 1 coach-judgment block
    assert len([i for i in claims if i.classification == NEEDS_JUDGMENT]) == 5
    assert len([i for i in claims if i.classification == MECHANICAL]) == 1


def test_file_header_item_is_mechanical_and_sorted_last():
    items = sort_for_review(_scan("08-ultra-feeding.md", DRAFTED_FILE))
    header = next(i for i in items if i.item_kind == FILE_HEADER)
    assert header.classification == MECHANICAL
    assert items[-1] is header


def test_needs_judgment_claims_carry_tag_confidence_and_test():
    items = _scan("08-ultra-feeding.md", DRAFTED_FILE)
    wall = next(i for i in items if i.id.endswith("#the-90-minute-wall-is-not-a-glycogen-wall"))
    assert wall.classification == NEEDS_JUDGMENT
    assert wall.tag_kind == "ADAPTED"
    assert wall.tag_value == "cycling"
    assert wall.confidence == "high"
    assert wall.test.startswith("compare the wall's timing")


def test_two_tags_in_one_sentence_are_one_claim_not_two():
    # "`[EVIDENCE: swim]` for the open-water application, `[ADAPTED: cycling]`
    # for the transporter physiology. Confidence: high." is ONE claim.
    items = _scan("08-ultra-feeding.md", DRAFTED_FILE)
    feeding = [i for i in items if i.heading == "In-session carbohydrate feeding"]
    assert len(feeding) == 2  # the dose-ladder claim + the coach-judgment one
    dose = next(i for i in feeding if i.tag_kind == "EVIDENCE")
    assert dose.confidence == "high"


def test_two_claims_in_one_paragraph_split_on_confidence():
    # The "Bone loading" section stacks an [EVIDENCE: swim] claim and an
    # [ADAPTED] claim in a single paragraph, each with its own Confidence: --
    # they are two distinct review items, and neither may collapse to an
    # empty span.
    items = _scan("08-ultra-feeding.md", DRAFTED_FILE)
    bone = [i for i in items if i.heading == "Bone loading"]
    assert len(bone) == 2
    assert {i.tag_kind for i in bone} == {"EVIDENCE", "ADAPTED"}
    assert all(len(i.claim_text) > 40 for i in bone)
    assert all(i.sources for i in bone)


def test_coach_judgment_caveat_inside_a_tagged_claim_is_not_its_own_item():
    text = (
        "# T\n\n**UNREVIEWED**: draft.\n\n## S\n\n"
        "`[ADAPTED: running]` Confidence: medium. A claim citing "
        "`Tucker (2009)`. `Coach judgment:` a caveat riding along inside the "
        "same paragraph. **Test:** something checkable.\n"
    )
    claims = [i for i in _scan("x.md", text) if i.item_kind == CLAIM]
    assert len(claims) == 1
    assert claims[0].classification == NEEDS_JUDGMENT


# --- marker scope -------------------------------------------------------------------


def test_section_marker_covers_only_its_own_section():
    items = _scan("04-css-intensity-anchors.md", SECTION_MARKER_FILE)
    assert len(items) == 1
    assert items[0].heading == "Open questions / not yet covered here"
    assert items[0].classification == MECHANICAL
    # The [EVIDENCE: swim] CSS claim is not under the marker, so not an item.
    assert all(i.heading != "Critical Swim Speed" for i in items)


def test_file_marker_and_inner_section_marker_coexist():
    items = _scan("07-strength-dryland.md", NESTED_MARKER_FILE)
    by_id = {i.id: i for i in items}

    dosing = by_id["07-strength-dryland.md#what-s-actually-in-a-session"]
    assert dosing.marker_scope == "section"
    assert dosing.owns_marker is True  # its own inline marker

    ramping = by_id["07-strength-dryland.md#watch-total-load-when-ramping"]
    assert ramping.marker_scope == "file"
    assert ramping.owns_marker is False  # covered by the header marker

    header = by_id["07-strength-dryland.md#strength-dryland-programming"]
    assert header.item_kind == FILE_HEADER
    assert header.owns_marker is True


def test_no_marker_means_no_items():
    text = "# T\n\n## S\n\n**[EVIDENCE: swim]** A reviewed claim. Confidence: high.\n"
    assert _scan("x.md", text) == []


# --- ids ------------------------------------------------------------------------------


def test_ids_stable_across_repeated_scans():
    first = [i.id for i in _scan("08-ultra-feeding.md", DRAFTED_FILE)]
    second = [i.id for i in _scan("08-ultra-feeding.md", DRAFTED_FILE)]
    assert first == second


def test_multiple_claims_under_one_heading_get_ordinal_ids():
    items = _scan("08-ultra-feeding.md", DRAFTED_FILE)
    bone = sorted(i.id for i in items if i.heading == "Bone loading")
    assert bone == ["08-ultra-feeding.md#bone-loading", "08-ultra-feeding.md#bone-loading-2"]


def test_all_item_ids_stay_the_same_once_the_marker_is_gone():
    # So review-accept can tell an already-accepted id (no-op) from a typo.
    ids = all_item_ids("08-ultra-feeding.md", DRAFTED_FILE)
    assert "08-ultra-feeding.md#bone-loading-2" in ids
    marker = find_markers(DRAFTED_FILE)[0]
    accepted = strip_marker(DRAFTED_FILE, marker.start, marker.end)
    assert all_item_ids("08-ultra-feeding.md", accepted) == ids


# --- source resolution (the reviewer's key signal) --------------------------------


def test_resolves_backticked_author_year_citation_with_verified_marker():
    sources, unresolved = resolve_citations("Per `Tucker (2009)`, RPE scales.", _refs())
    assert [(s.markers, s.key) for s in sources] == [("✓", "Tucker R. (2009)")]
    assert unresolved == ()


def test_tilde_marked_source_surfaces_as_weak():
    sources, _ = resolve_citations("corroborated by `Eston et al. (2012)`.", _refs())
    assert len(sources) == 1
    assert sources[0].markers == "~"
    assert sources[0].is_weak is True


def test_caveat_marked_source_surfaces_as_weak():
    sources, _ = resolve_citations("per `Shaw et al. (2014)`.", _refs())
    assert sources[0].markers == "✓⚠"
    assert sources[0].is_weak is True


def test_resolves_entry_whose_author_key_wraps_across_two_lines():
    # Most real reference_list.md entries wrap; a parser that reads only the
    # first line loses the source on every claim citing them.
    sources, unresolved = resolve_citations("`Gomez-Bruton et al. (2013)` find...", _refs())
    assert len(sources) == 1
    assert sources[0].key.startswith("Gomez-Bruton A., Gonzalez-Aguero A.")
    assert "(2013)" in sources[0].key
    assert unresolved == ()


def test_resolves_title_keyed_entry_cited_by_title():
    sources, _ = resolve_citations(
        "cites multiple dry-land shoulder-strengthening RCTs in competitive swimmers.",
        _refs(),
    )
    assert [s.key for s in sources] == [
        "Dry-land shoulder-strengthening RCTs in competitive swimmers"
    ]


def test_citation_absent_from_reference_list_is_reported_unresolved():
    sources, unresolved = resolve_citations("Per `Fakeperson et al. (2099)`.", _refs())
    assert sources == ()
    assert unresolved == ("Fakeperson (2099)",)


def test_same_year_citation_does_not_false_match_another_entry():
    # 2021 exists in the list (Feijen, Hutson); an unrelated 2021 author must
    # not silently borrow one of their verification markers.
    sources, unresolved = resolve_citations("Per `Nobody et al. (2021)`.", _refs())
    assert sources == ()
    assert unresolved == ("Nobody (2021)",)


def test_adapted_claim_resting_on_a_weak_source_is_flagged_for_attention():
    # The exact scenario the tool exists for.
    items = _scan("08-ultra-feeding.md", DRAFTED_FILE)
    ceiling = next(i for i in items if i.tag_value == "running")
    assert ceiling.classification == NEEDS_JUDGMENT
    assert ceiling.confidence == "medium-high"
    assert [s.markers for s in ceiling.weak_sources] == ["~"]
    assert ceiling.needs_attention is True


def test_attention_items_sort_ahead_of_clean_ones():
    ordered = sort_for_review(_scan("08-ultra-feeding.md", DRAFTED_FILE))
    needs = [i for i in ordered if i.classification == NEEDS_JUDGMENT]
    first_clean = next(idx for idx, i in enumerate(needs) if not i.needs_attention)
    last_flagged = max(idx for idx, i in enumerate(needs) if i.needs_attention)
    assert last_flagged < first_clean


# --- dossier attribution ----------------------------------------------------------


def test_dossier_read_from_the_topic_file_s_own_header(tmp_path):
    dossiers = tmp_path / "research-dossiers"
    _write(dossiers, "2026-07-13-ultra-feeding.md", "# Ultra feeding dossier\n")
    assert find_dossier(DRAFTED_FILE, dossiers) == "2026-07-13-ultra-feeding.md"


def test_file_naming_no_dossier_gets_none_even_if_a_dossier_cross_references_it(tmp_path):
    # The real misattribution: the RED-S dossier mentions
    # `library/07-strength-dryland.md` as a cross-reference. That must not
    # attribute 07 to it.
    dossiers = tmp_path / "research-dossiers"
    _write(
        dossiers,
        "2026-07-13-reds-energy-availability.md",
        "# RED-S dossier\n\nCross-refs `library/07-strength-dryland.md` for the "
        "one actionable training move.\n",
    )
    assert find_dossier(NESTED_MARKER_FILE, dossiers) is None
    items = _scan("07-strength-dryland.md", NESTED_MARKER_FILE, dossiers)
    assert all(i.dossier is None for i in items)


def test_dossier_ignored_when_the_named_file_does_not_exist(tmp_path):
    dossiers = tmp_path / "research-dossiers"
    dossiers.mkdir(parents=True)
    assert find_dossier(DRAFTED_FILE, dossiers) is None


# --- markers / claim blocks (unit level) --------------------------------------------


def test_find_markers_classifies_file_vs_section_scope():
    assert {m.scope for m in find_markers(NESTED_MARKER_FILE)} == {"file", "section"}


def test_find_claim_blocks_ignores_untagged_prose():
    blocks = find_claim_blocks(DRAFTED_FILE)
    assert len(blocks) == 6
    assert all(b.tag_kind in ("EVIDENCE", "ADAPTED", "Coach judgment") for b in blocks)


def test_scan_library_excludes_meta_files(tmp_path):
    library = tmp_path / "library"
    _write(library, "INDEX.md", "| `08-ultra-feeding.md` | s. **UNREVIEWED**, pending human review. |\n")
    _write(library, "reference_list.md", REFERENCE_LIST_FIXTURE)
    _write(library, "00-conventions.md", "# Conventions\n\nmark it **`UNREVIEWED`** inline.\n")
    _write(library, "08-ultra-feeding.md", DRAFTED_FILE)
    assert {i.file for i in scan_library(library)} == {"08-ultra-feeding.md"}


# --- the real library (regression pin) -----------------------------------------------


def test_real_library_surfaces_per_claim_items_from_the_new_wave():
    items = scan_library(REPO_ROOT / "library")
    by_id = {i.id: i for i in items}
    needs = [i for i in items if i.classification == NEEDS_JUDGMENT]

    # The new wave's files must each enumerate many needs-judgment CLAIM
    # items -- not one "mechanical" header item apiece (the defect pinned).
    for filename in ("08-ultra-feeding.md", "13-reds-energy-availability.md"):
        file_needs = [i for i in needs if i.file == filename and i.item_kind == CLAIM]
        assert len(file_needs) >= 5, f"{filename} should enumerate its claims"

    # Existing debt still surfaces.
    assert "04-css-intensity-anchors.md#open-questions-not-yet-covered-here" in by_id
    assert any(i.file == "07-strength-dryland.md" for i in items)

    # Sources resolve, and weak (~/⚠) sources are surfaced.
    assert any(i.sources for i in needs)
    assert any(i.weak_sources for i in needs)

    # Dossier attribution: the new files name theirs in their own header;
    # 07 names none and must not inherit the RED-S dossier's cross-reference.
    assert (
        by_id["13-reds-energy-availability.md#hrv-rhr-confound-cross-reference-10-recovery-hrv-md"].dossier
        == "2026-07-13-reds-energy-availability.md"
    )
    assert all(i.dossier is None for i in items if i.file == "07-strength-dryland.md")


# --- strip_marker ----------------------------------------------------------------------


def test_strip_marker_comma_joined():
    text = "**Coach judgment, UNREVIEWED.** Some prose follows."
    assert strip_marker(text, 0, text.index("**", 2) + 2) == "**Coach judgment.** Some prose follows."


def test_strip_marker_slash_joined():
    text = "**Coach judgment / UNREVIEWED**: flagged as a gap."
    assert strip_marker(text, 0, text.index("**", 2) + 2) == "**Coach judgment**: flagged as a gap."


def test_strip_marker_bare_flag_swallows_em_dash_lead_in():
    text = "**UNREVIEWED** — drafted from a dossier; pending review."
    assert strip_marker(text, 0, len("**UNREVIEWED**")) == "drafted from a dossier; pending review."


def test_strip_marker_bare_flag_swallows_colon_lead_in():
    text = "prose. **UNREVIEWED**: this file is agent-authored."
    start = text.index("**UNREVIEWED")
    assert strip_marker(text, start, start + len("**UNREVIEWED**")) == (
        "prose. this file is agent-authored."
    )


def test_strip_marker_leaves_everything_outside_the_span_identical():
    marker = find_markers(DRAFTED_FILE)[0]
    new_text = strip_marker(DRAFTED_FILE, marker.start, marker.end)
    assert new_text.startswith(DRAFTED_FILE[: marker.start])
    assert new_text.endswith(DRAFTED_FILE[marker.end :].lstrip(" —"))
    assert "UNREVIEWED" not in new_text


# --- INDEX.md ---------------------------------------------------------------------------


def test_mark_index_reviewed_updates_only_the_matching_row():
    index_text = (
        "| `07-strength-dryland.md` | s. **UNREVIEWED**, pending human review. |\n"
        "| `08-ultra-feeding.md` | s. **UNREVIEWED**, pending human review. |\n"
    )
    new_text, changed = mark_index_reviewed(index_text, "07-strength-dryland.md")
    assert changed is True
    lines = new_text.split("\n")
    assert "Human-reviewed." in lines[0]
    assert "**UNREVIEWED**, pending human review." in lines[1]


def test_mark_index_reviewed_noop_when_row_absent():
    index_text = "| `other.md` | summary. Human-reviewed. |\n"
    assert mark_index_reviewed(index_text, "07-strength-dryland.md") == (index_text, False)


# --- renderers ---------------------------------------------------------------------------


def test_render_text_groups_needs_judgment_first_and_shows_the_signals():
    report = render_text(_scan("08-ultra-feeding.md", DRAFTED_FILE))
    assert report.index("NEEDS JUDGMENT") < report.index("MECHANICAL")
    assert "08-ultra-feeding.md#the-90-minute-wall-is-not-a-glycogen-wall" in report
    assert "Confidence: high" in report
    assert "test " in report  # the Test: line is shown
    assert "~ Eston R. et al. (2012)" in report
    assert "WEIGH THIS" in report  # weak source called out


def test_render_html_has_no_external_references():
    html = render_html(_scan("08-ultra-feeding.md", DRAFTED_FILE)).lower()
    assert "http" not in html
    assert "src=" not in html
    assert "href=" not in html


def test_render_html_makes_weak_sources_impossible_to_miss():
    html = render_html(_scan("08-ultra-feeding.md", DRAFTED_FILE))
    assert "source-weak" in html
    assert "has-weak" in html
    assert "check sources" in html


def test_render_html_needs_judgment_section_precedes_mechanical():
    html = render_html(_scan("08-ultra-feeding.md", DRAFTED_FILE))
    assert html.index("Needs judgment (") < html.index("Mechanical (")


# --- CLI: review-queue -------------------------------------------------------------------


def _library_tree(tmp_path) -> Path:
    library = tmp_path / "library"
    _write(
        library,
        "INDEX.md",
        "| `08-ultra-feeding.md` | summary. **UNREVIEWED**, pending human review. |\n",
    )
    _write(library, "reference_list.md", REFERENCE_LIST_FIXTURE)
    _write(library, "08-ultra-feeding.md", DRAFTED_FILE)
    _write(library, "04-css-intensity-anchors.md", SECTION_MARKER_FILE)
    return library


def test_cli_review_queue_default_output_is_human_readable(tmp_path, capsys):
    code = main(["--library-dir", str(_library_tree(tmp_path)), "review-queue"])
    assert code == 0
    out = capsys.readouterr().out
    assert not out.strip().startswith("{")  # not a raw JSON dump
    assert "NEEDS JUDGMENT" in out
    assert "MECHANICAL" in out
    assert "08-ultra-feeding.md#bone-loading" in out


def test_cli_review_queue_json_flag_emits_machine_form(tmp_path, capsys):
    code = main(["--library-dir", str(_library_tree(tmp_path)), "review-queue", "--json"])
    assert code == 0
    result = _out(capsys)
    assert result["counts"]["needs_judgment"] == 5
    assert result["counts"]["weak_sourced"] >= 1
    assert result["needs_judgment"][0]["sources"]


def test_cli_review_queue_file_filter(tmp_path, capsys):
    code = main(
        [
            "--library-dir",
            str(_library_tree(tmp_path)),
            "review-queue",
            "--file",
            "04-css-intensity-anchors.md",
            "--json",
        ]
    )
    assert code == 0
    result = _out(capsys)
    assert result["counts"]["total"] == 1
    assert result["mechanical"][0]["file"] == "04-css-intensity-anchors.md"


def test_cli_review_queue_html_is_self_contained(tmp_path, capsys):
    html_path = tmp_path / "queue.html"
    code = main(
        ["--library-dir", str(_library_tree(tmp_path)), "review-queue", "--html", str(html_path)]
    )
    assert code == 0
    html = html_path.read_text(encoding="utf-8").lower()
    assert "http" not in html
    assert "src=" not in html
    assert "href=" not in html


# --- CLI: review-accept --------------------------------------------------------------------


def test_cli_review_accept_clears_the_file_marker_and_every_claim_it_covered(tmp_path, capsys):
    library = _library_tree(tmp_path)
    code = main(
        [
            "--library-dir",
            str(library),
            "review-accept",
            "08-ultra-feeding.md#ultra-feeding-the-wall-and-in-swim-carbohydrate",
        ]
    )
    assert code == 0
    result = _out(capsys)
    accepted = result["results"][0]
    assert accepted["status"] == "accepted"
    assert len(accepted["also_cleared"]) == 6  # the claims that marker covered
    assert result["index_updated"] == ["08-ultra-feeding.md"]

    assert "UNREVIEWED" not in (library / "08-ultra-feeding.md").read_text(encoding="utf-8")
    assert "Human-reviewed." in (library / "INDEX.md").read_text(encoding="utf-8")


def test_cli_review_accept_refuses_a_claim_that_does_not_own_its_marker(tmp_path, capsys):
    library = _library_tree(tmp_path)
    before = (library / "08-ultra-feeding.md").read_bytes()
    code = main(["--library-dir", str(library), "review-accept", "08-ultra-feeding.md#bone-loading"])
    assert code == 1
    result = _out(capsys)
    assert "file-level marker" in result["error"]
    assert result["results"][0]["status"] == "not-marker-owner"
    assert result["results"][0]["marker_owner"] == (
        "08-ultra-feeding.md#ultra-feeding-the-wall-and-in-swim-carbohydrate"
    )
    assert (library / "08-ultra-feeding.md").read_bytes() == before  # untouched


def test_cli_review_accept_is_idempotent(tmp_path, capsys):
    library = _library_tree(tmp_path)
    item_id = "04-css-intensity-anchors.md#open-questions-not-yet-covered-here"

    assert main(["--library-dir", str(library), "review-accept", item_id]) == 0
    assert _out(capsys)["results"][0]["status"] == "accepted"
    after = (library / "04-css-intensity-anchors.md").read_bytes()

    assert main(["--library-dir", str(library), "review-accept", item_id]) == 0
    assert _out(capsys)["results"][0]["status"] == "already-accepted"
    assert (library / "04-css-intensity-anchors.md").read_bytes() == after


def test_cli_review_accept_unknown_id_is_an_error(tmp_path, capsys):
    library = _library_tree(tmp_path)
    code = main(["--library-dir", str(library), "review-accept", "04-css-intensity-anchors.md#nope"])
    assert code == 1
    assert "error" in _out(capsys)


def test_cli_review_accept_changes_nothing_but_the_marker_bytes(tmp_path, capsys):
    """Byte-compare the file before/after: the ONLY difference may be the
    removed marker -- claim prose is never rewritten."""
    library = _library_tree(tmp_path)
    path = library / "04-css-intensity-anchors.md"
    before = path.read_bytes()

    code = main(
        [
            "--library-dir",
            str(library),
            "review-accept",
            "04-css-intensity-anchors.md#open-questions-not-yet-covered-here",
        ]
    )
    assert code == 0
    after = path.read_bytes()
    assert before != after

    prefix = 0
    while prefix < min(len(before), len(after)) and before[prefix] == after[prefix]:
        prefix += 1
    suffix = 0
    while (
        suffix < len(before) - prefix
        and suffix < len(after) - prefix
        and before[-1 - suffix] == after[-1 - suffix]
    ):
        suffix += 1

    removed = before[prefix : len(before) - suffix].decode("utf-8")
    added = after[prefix : len(after) - suffix].decode("utf-8")
    assert "UNREVIEWED" in removed
    assert "UNREVIEWED" not in added
    # The claim's own prose survived verbatim.
    assert "flagged as a gap, not a decision." in after.decode("utf-8")
