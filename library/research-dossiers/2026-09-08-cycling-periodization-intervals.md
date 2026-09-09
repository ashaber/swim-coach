# Cycling Periodization & Interval-Taxonomy Research Dossier — feeds `library/24-cycling-periodization-intervals.md`

> **Provenance note:** raw research input for the periodization/deload and
> interval-taxonomy follow-up to `library/23-cycling-training.md`. **Not
> itself a citable library file** — for grounding claims, cite
> `library/reference_list.md` and `24-cycling-periodization-intervals.md`
> directly, never this dossier. Matches the provenance convention already
> used by `2026-09-07-cycling-training.md` and the other dated dossiers in
> this directory.

Compiled for: swim-coach research library, continuing the `engine/
cycling-coach` branch (PR #167, CI-green at `76e7caf`) into a follow-up
research/library-only stage. Trigger: two "KNOWN LIMITATION" code comments
in `engine/swim_coach/plan.py`, left deliberately unfixed by PR #167's own
red-team review — (1) no periodic deload/recovery week in the bike
block-interpolation math, (2) `_bike_session_structure` generates one flat
generic power block per session regardless of week or discipline. Andrew's
real, already-approved, already red-team-reviewed cyclocross macrocycle
and first training block (`../ai-coach/athlete/profile.md`,
`plans/current/macrocycle.md`, `plans/current/block-01-reset-race1.md`)
name three real frameworks in their own "Framework rationale" section —
Seiler's polarized distribution, Issurin's block periodization, Laursen &
Buchheit's HIIT taxonomy — none of which were yet cited anywhere in this
repo's library. This pass verifies and cites all three, and extracts the
generalizable interval-session-shape pattern from the real plan's sessions
as citable, reusable session templates.

**Source count this pass:** 4 ✓ verified (Seiler 2010; Issurin 2008;
Buchheit & Laursen 2013 Parts I+II counted as one entry; Laursen & Buchheit
2019 book) · 0 ~ partial · 0 ⚠ rejected.

## 1. Seiler's polarized intensity-distribution model

- **✓ Seiler S. (2010)** — "What is Best Practice for Training Intensity
  and Duration Distribution in Endurance Athletes?" — *International
  Journal of Sports Physiology and Performance*, 5(3):276-291. Confirmed
  via the publishing journal (Human Kinetics/IJSPP, `journals.humankinetics
  .com`) directly, plus independent secondary convergence (Semantic
  Scholar, ResearchGate) this session. Over 1,100 citations per Semantic
  Scholar — among the most-cited papers in endurance training science.
  **Findings:** competitive endurance athletes training 10-13x/week show a
  convergent "polarized" pattern — roughly 80% of sessions at low
  intensity (<=2 mM blood lactate), ~20% at high intensity (~90% VO2max),
  and deliberately little time in the moderate/"grey zone" band.
  Intensification studies on already-well-trained athletes don't
  convincingly show that adding more high-intensity work improves
  long-term performance further. **Population:** cross-country skiing,
  rowing, running, and cycling case studies/cohorts — a multi-sport
  synthesis, not a cyclist-specific trial. **Tag:** `[ADAPTED:
  general-endurance]`, Confidence: high (synthesis strength/citation
  count/replication is very high; the discipline-match to "trained
  cyclist" specifically is the one honest discount).
- **Relevance check against the real macrocycle:** the macrocycle's own
  "Framework rationale" section cites this exact concept by name
  ("Seiler polarized distribution") as the correction to a documented
  in-plan problem — four moderate/grey-zone-intensity days per week that
  the plan's own red-team review flagged as the likely cause of both a
  late-race fade and weak flat-power sections, resolved to "two hard days
  per week, maximum. Everything else true Zone 2." This is a real,
  concrete, already-validated-by-outcome application of Seiler's model —
  not hypothetical grounding.

## 2. Issurin's block periodization

- **✓ Issurin V.B. (2008)** — "Block periodization versus traditional
  training theory: a review" — *The Journal of Sports Medicine and
  Physical Fitness*, 48(1):65-75. Confirmed via PubMed (PMID 18212712)
  plus independent convergence (ResearchGate, Semantic Scholar, the
  Coaching Science Abstracts mirror at `coachsci.sdsu.edu`) this session.
  **Findings:** traditional periodization tries to develop many fitness
  qualities simultaneously across long mixed mesocycles; block
  periodization instead sequences short, narrowly-targeted mesocycle
  blocks, exploiting and superimposing each quality's residual training
  effect. Identifies specific traditional-theory drawbacks: inability to
  provide multi-peak performance across a season, negative interaction of
  non-compatible workloads within one long mixed block. **Population:**
  general training theory across sports, not a cycling-specific empirical
  trial. **Tag:** `[ADAPTED: general-endurance]`, Confidence: medium
  (foundational review/theory paper, not itself an outcome trial).
  **Cross-check:** `Galán-Rioja et al. (2023)` — already cited in
  `23-cycling-training.md`/`reference_list.md` — independently confirms
  block periodization is actually practiced and effective in trained
  road cyclists specifically (1-8-week concentrated blocks, 8.75-11.68
  h/week), so the *shape* Issurin proposes has real cycling-native
  empirical support even though Issurin's own paper isn't a cycling trial.
- **Relevance check against the real macrocycle:** the macrocycle's own
  "Framework rationale" names "Issurin-style concentrated block loading in
  the single 3-week raceless window (weeks 3-5), the only place a real
  training stimulus fits before the peak" — an explicit, deliberate,
  narrow-window application of exactly this concept, not a generic
  base-build-peak label.

## 3. Laursen & Buchheit's HIIT taxonomy

- **✓ Buchheit M., Laursen P.B. (2013)** — "High-Intensity Interval
  Training, Solutions to the Programming Puzzle: Part I: Cardiopulmonary
  Emphasis" — *Sports Medicine*, 43(5):313-338 (confirmed via Springer/
  Sports Medicine directly, Semantic Scholar >1,000 citations, PubMed).
  "...Part II: Anaerobic Energy, Neuromuscular Load and Practical
  Applications" — *Sports Medicine*, 43(10):927-954, DOI
  10.1007/s40279-013-0066-5 (confirmed via PubMed PMID 23832851 and the
  authors' own hosted PDF at `martin-buchheit.net`). **✓ Laursen P.,
  Buchheit M. (2019)** — *Science and Application of High-Intensity
  Interval Training: Solutions to the Programming Puzzle* — Human
  Kinetics, published 2019-02-28 (confirmed via publisher listing and
  multiple independent bookseller listings — AbeBooks, Waterstones,
  Human Kinetics UK — converging on author, publisher, and year). The
  book is the two-part review's book-length successor covering the same
  authors' taxonomy, extended with sport-specific application chapters.
  **Findings relevant to session-shape taxonomy:** interval physiological
  target is set primarily by work-bout duration and work:rest ratio, not
  intensity alone; short, fixed-ratio "short-short" formats (their own
  documented term, e.g. 30s/15s or similar on/off ratios) exploit
  VO2-kinetics priming — the off-period being too short for oxygen uptake
  to fully decay — to accumulate more total time-at-VO2max at lower
  per-repetition neuromuscular/anaerobic cost than one long continuous
  bout at equivalent intensity. **Population:** multi-sport (endurance
  and team sports broadly) — not cycling-specific. **Tag:** `[ADAPTED:
  general-endurance]`, Confidence: high (the standard reference across
  endurance-sport HIIT programming, near-universal secondary adoption,
  though not itself a cycling trial).
- **Relevance check against the real macrocycle and block-01:** the
  macrocycle's "Framework rationale" names this taxonomy explicitly:
  "short-short (40/20) for repeatability, over/unders for lactate
  tolerance and clearance under load, sustained threshold for the
  flat-power limiter." `block-01-reset-race1.md`'s actual prescribed
  sessions instantiate two of the four taxonomy templates directly (a
  2x12min sustained-threshold field-test session; a 5x2min VO2 long-
  interval session with 3min recovery), and the macrocycle's week-by-week
  table names all four (over/unders in weeks 3 and 5; short-short VO2 in
  week 4; sustained threshold in weeks 1 and 4; race-pace in weeks 5, 6,
  and 11) plus two lower-stress variants (openers/pre-race primers).

## 4. What was extracted vs. deliberately excluded

Extracted as generalizable pattern (now in `24-cycling-periodization-
intervals.md`): the four taxonomy categories' typical duration ranges,
work:rest ratios, and %FTP bands (re-expressed against `23-cycling-
training.md`'s own Coggan zone table so the two files stay internally
consistent, rather than as raw watts).

Deliberately **excluded** as this athlete's personal profile data, not
library content: his specific FTP anchor (263 W, an intentionally
conservative estimate pending a field test — see `profile.md`'s "Standing
coaching decisions"), his specific watt targets for each named session
(e.g. "270 W" for an "over"), and his race calendar (2026-09-19/20,
2026-10-17/18, etc.). None of these appear in `24-cycling-periodization-
intervals.md`.

## 5. Deload-cadence gap — honest non-finding

None of the three sources above, nor `Galán-Rioja et al. (2023)`, specify
a validated numeric deload-week cadence (e.g. "every 3rd week"). This
dossier did not find one this pass either — searches for a cycling-
specific deload-frequency validation study returned nothing beyond
practitioner convention (TrainingPeaks/Friel's common 3:1 build:unload
ratio, itself uncited in any of the sources checked). `24-cycling-
periodization-intervals.md` records a `Coach judgment:` default informed
by Issurin's block-transition concept and Galán-Rioja's observed
1-8-week block-length range, explicitly not presented as citation-backed
— matching this project's existing practice for the swim engine's own
uncited +8%/week ramp cap.
