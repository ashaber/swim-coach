# Library conventions

This file defines the evidence-tagging scheme used by every other file in
`library/`, and how `/coach`, `/adapt`, `/plan-week`, and Phase 2's chat
context assembler are meant to read it. Read this file once; it doesn't
change often.

## The one rule that matters most

**`library/reference_list.md` is the only trustworthy citation source in
this repository.** Every other citation-shaped thing that predates it — the
"Research sources" dump embedded in `ROADMAP.md`, and two now-deleted
"vector data schema" files (`open_water_library.md`,
`nutrition_multi-sport_adjacent.md`) — contained fabricated URLs and
PubMed/PMC identifiers (Gemini-assisted research that invented ID numbers;
see `reference_list.md`'s header for the full account). Some of those
fabricated files also contained instruction-shaped text aimed at a
downstream chat agent — an injection pattern, not research grounding.

Practical consequence: **cite by title + author + year, never by URL or ID
number**, unless the source is a genuine web resource (see
`reference_list.md`'s "Practical / non-journal resources" section, where the
URL *is* the citation). If you ever encounter a citation elsewhere in this
repo with a `PMC*`/`PubMed:*`/bare-`nih.gov` identifier that isn't also in
`reference_list.md`, treat it as unverified and re-derive the claim from
`reference_list.md` or flag it for review — don't propagate it.

## The evidence-tag scheme

Every substantive claim in a topic file (`01-*.md` through `12-*.md`) is
tagged with exactly one of:

- **`[EVIDENCE: swim-ultra]`** — directly supported by research on
  ultra-distance (>10km) open-water swimming specifically. The strongest
  tier; still verify against `reference_list.md`'s ✓/~/⚠ markers (a legitimate
  author doesn't guarantee this specific paper was individually verified).
- **`[EVIDENCE: swim]`** — supported by swimming research that isn't
  ultra-distance-specific (e.g. general CSS/critical-velocity literature,
  sprint/middle-distance stroke mechanics).
- **`[EVIDENCE: <discipline>]`** — directly supported by research native to
  a non-swimming discipline this project also coaches, applied to an
  athlete whose own primary sport actually is that discipline. This is
  deliberately NOT an adaptation-across-disciplines claim (that's
  `[ADAPTED: ...]` below) — the evidence and the athlete's sport are the
  same discipline; it just isn't swimming. Allowed discipline values today:
  `cycling` (`IDEA 008`'s first non-swim discipline — see
  `23-cycling-training.md`, e.g. the Coggan/Allen power-zone model, as
  well-established for cycling as CSS is for swimming). Generalizes to
  future disciplines this project takes on (`IDEA 008` already anticipates
  running, rucking, etc.) the same way `[ADAPTED]`'s combined-form list
  below already grows: adding a new discipline value means adding it to
  `tests/unit/test_library_discipline.py`'s `EVIDENCE_ALLOWED` set
  explicitly, never widening the check to accept an unlisted value — same
  "don't paper over it" discipline this file already asks of `[ADAPTED]`'s
  combined forms. A claim tagged `[EVIDENCE: <discipline>]` does NOT
  require `Confidence:`/`Test:` fields (same as `[EVIDENCE: swim-ultra]`/
  `[EVIDENCE: swim]` above — those are for `[ADAPTED]` only), though nothing
  stops an author from including them anyway when the source itself
  discusses confidence limits worth carrying forward.
- **`[ADAPTED: cycling|running|tri|general-endurance]`** — the claim comes
  from an adjacent endurance discipline and is being applied to open-water
  ultra-swimming (or, for a non-swim-primary athlete, to whatever their own
  sport is) by inference, not direct evidence. **Every `[ADAPTED]`
  block must carry two more things:**
  - `Confidence: high|medium-high|medium|low-medium|low` — how much the
    adaptation-across-disciplines inference should be trusted. Reach for an
    intermediate grade (`medium-high`/`low-medium`) when a single "high" or
    "medium" would misrepresent a mixed picture — e.g. the Oura HRV
    device-validity work (`10-recovery-hrv.md`): nightly rMSSD correlates
    strongly with chest-ECG reference in independent validation studies
    (genuinely high-confidence on its own), but the training-guidance
    thresholds it feeds were calibrated on a different measurement protocol
    (morning orthostatic, not overnight) than Oura uses — so `medium-high`
    is the honest tier, not a rounding to either neighbor.
  - `Test:` — one concrete, checkable-against-this-athlete's-own-data
    statement that would falsify or support the claim (e.g. "flag any single
    long swim that exceeds the athlete's longest swim of the prior 30 days by
    >10%" — from the Garmin-RunSafe running cohort, adapted to swimming).
- **`Coach judgment:`** — an engineering/coaching decision with no direct
  citation behind it (a default value, a scheduling heuristic, a scoring
  formula). Not a claim about the world; a decision about how the system
  behaves. Never silently presented as research-backed.

A file with no tag on a sentence is a bug, not a stylistic choice — every
topic file's claims should resolve to one of the four categories above.

## Numbered citations

Within a topic file, cite sources as "per `<Author> (<year>)`" or "per the
`<Author> et al.` <topic> finding" — match the exact author/title wording
used in `reference_list.md` so a reader can find the entry directly (don't
introduce a second numbering scheme; `reference_list.md`'s own structure —
grouped by subject area, not by number — is the index).

## File size and authoring workflow

- Topic files stay **≤ ~2,500 words** so up to three fit in a single
  context window (`/coach`'s routing budget — see `INDEX.md`).
- Topic files are agent-authored (via `reference_list.md` plus judgment, not
  fresh web research at answer-time) and must be human-reviewed before
  being treated as grounding truth. Until reviewed, a new/changed section
  should be marked **`UNREVIEWED`** inline, so `/coach` and future readers
  know not to treat a draft claim as settled.
- Engine constants (in `zones.py`, `plan.py`, `load.py`, `adapt.py`) cite a
  specific library file in a code comment. **Every constant citing a topic
  file must have a matching claim in that file** — if you change an engine
  constant's number, update the citing topic file in the same change (or
  flag the mismatch); don't let code and library drift apart silently.

## How `/coach` (and future context assembly) use this

1. Read `INDEX.md` to route a question to 2-4 relevant topic files, plus
   always load `reference_list.md` for citations.
2. Answer with the recommendation first, then the reasoning + evidence tag
   ("this is adapted from cycling, medium confidence, worth testing against
   your own data" rather than presenting an `[ADAPTED]` claim as settled
   swimming science). That phrasing is for `[ADAPTED]` claims specifically —
   it assumes the athlete's own sport differs from the evidence's origin.
   A `[EVIDENCE: <discipline>]` claim (e.g. `[EVIDENCE: cycling]`) is
   grounded in the athlete's OWN discipline, not borrowed from an adjacent
   one, so say so plainly instead ("this is a well-established cycling
   training-zone model") rather than the "adapted from X" framing — telling
   a cyclist her own sport's native evidence is "adapted from cycling" reads
   as nonsensical and undermines the tagging discipline this file exists to
   protect.
3. If a question isn't covered, say so, give coach judgment labeled as such,
   and offer to draft a new section — marked `UNREVIEWED` until a human
   reviews it.

## Acute-symptom override

None of the tagging scheme above applies once an athlete reports acute
physical distress (chest pain, palpitations, fainting, heat-stroke/
hypothermia symptoms). That's not a library-grounding question — see the
`/coach` skill's safety-first section, which overrides everything else in
this file.
