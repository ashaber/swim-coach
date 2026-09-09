# Cycling Training Research Dossier — feeds `library/23-cycling-training.md`

> **Provenance note:** this is raw research input for the first cycling-specific
> library file. It is **not itself a citable library file** — for grounding
> claims, cite `library/reference_list.md` and `23-cycling-training.md`
> directly, never this dossier. Matches the provenance convention already used
> by `research-dossiers/2026-07-28-strength-programming.md` and the other
> dated dossiers in this directory.

Compiled for: swim-coach research library, cycling-discipline expansion
(`engine/cycling-coach` branch — see `IDEAS.md`'s IDEA 008 "Multi-sport
expansion," use case 5: Andrew himself, as a mountain-bike + cyclocross
rider). Research-only pass; no engine, backend, or existing library file was
edited. Follows the citation discipline in `library/00-conventions.md` and
`library/reference_list.md` (cite by title + author + year + journal/
publisher, **never** by URL/PMC/PubMed/DOI ID; every source carries a
✓/~/⚠ marker, confirmed by a real web search this session — not training-data
memory alone).

**Immediate trigger:** a broader 4-discipline evidence scan run earlier this
session found cycling well-grounded overall; this pass goes deep specifically
on the six questions the build/critique stages need answered before
`23-cycling-training.md` can cite real engine-constant-level numbers: the
Coggan 7-zone %FTP table, the exact TSS/Normalized-Power/Intensity-Factor
formula, whether `engine/swim_coach/load.py`'s `CTL_TIME_CONSTANT_DAYS = 42`
/ `ATL_TIME_CONSTANT_DAYS = 7` are genuinely well-grounded for cycling (their
native discipline, per the code's own "unverified for swimming" flag), a 2023
cycling-periodization systematic review found in the earlier pass, road-
cyclist patellofemoral/knee injury evidence, and whether road/MTB/cyclocross
are researched as distinct populations or one generic "cycling" umbrella.

**Source count this pass:** 12 ✓ verified · 0 ~ partial · 1 ⚠ real-but-
rejected (predatory-publisher venue) — see §6. One topic (cycling-specific
week-to-week safe volume-progression *rate*, as opposed to periodization-
*model* comparison) returned an **honest no-citable-source outcome**,
documented in §5 — an expected, acceptable result under this repo's
citation discipline, matching the precedent set by the strength-programming
and cross-train dossiers (an honest negative is not a gap to paper over).

**Load-bearing caveat for the build agent, stated up front:** `00-
conventions.md`'s `[EVIDENCE: swim-ultra|swim]` / `[ADAPTED: cycling|
running|tri|general-endurance]` scheme is directionally built assuming swim
is always the discipline being adapted *to* — `IDEAS.md`'s IDEA 008 already
flags this explicitly ("no reciprocal tag exists"), and this pass confirms
it mechanically: `tests/unit/test_library_discipline.py`'s
`EVIDENCE_ALLOWED = {"swim-ultra", "swim"}` has no cycling-native value, so
a claim sourced directly from the cycling literature (e.g. Coggan's own
zone table, cited for a cycling athlete's own zones — not "adapted" from
anywhere) has no semantically correct tag to wear. See §7 for how this
dossier recommends handling it pragmatically without touching the CI gate
or `00-conventions.md` (both out of scope for a research-only pass).

---

## 1. Zone framework — Coggan 7-zone power model

- **✓ Allen H., Coggan A. (2010)**, *Training and Racing with a Power
  Meter* (2nd ed.), VeloPress. **✓ Allen H., Coggan A., McGregor S. (2019)**,
  *Training and Racing with a Power Meter* (3rd ed.), VeloPress,
  ISBN 9781937715939, 384pp. Both editions' existence, authors, publisher
  and (3rd ed.) ISBN/page count independently confirmed via publisher,
  bookseller (AbeBooks, Biblio, Amazon, Simon & Schuster) and Everand
  listings this session. `engine/swim_coach/load.py` already cites the 2nd
  edition for the TSS formula (see §2) — this dossier keeps that exact
  citation wording per `00-conventions.md`'s "match the exact author/title
  wording already used" rule, and separately verifies the 3rd edition
  exists as the current-print alternative.
  **The 7-zone %FTP table**, independently and consistently reproduced
  across multiple practitioner secondary sources this session (TrainingPeaks'
  own blog "Cycling Power Zones Explained: Coggan's 7-Level System",
  biketips.com, roadmancycling.com — cross-checked against each other, not
  a single source):
  | Zone | Name | %FTP |
  |---|---|---|
  | 1 | Active Recovery | <55% |
  | 2 | Endurance | 56–75% |
  | 3 | Tempo | 76–90% |
  | 4 | Lactate Threshold | 91–105% |
  | 5 | VO2max | 106–120% |
  | 6 | Anaerobic Capacity | 121–150% |
  | 7 | Neuromuscular Power | >150% (no meaningful FTP-relative cap) |
  **Verification tier:** same as this project's existing TSS citation to the
  same book — a widely-replicated practitioner-text convention, confirmed
  by convergent secondary sources this session, not by a direct primary-text
  read (the book itself wasn't fetched). Multiple independent commercial
  sources reproduce the table identically, which is meaningfully stronger
  than a single blog's say-so, but it stops short of a primary-source read.

## 2. TSS formula — precise, implementable

- Same book (Allen & Coggan, both editions) is the originating source, per
  TrainingPeaks' own attribution ("Dr. Andrew Coggan is credited as
  co-author of *Training and Racing with a Power Meter*... the originator
  of these metrics") confirmed via TrainingPeaks' own educational article
  this session.
  **Normalized Power (NP) — the exact 4-step algorithm**, confirmed via
  three independent secondary explanations this session (TrainerRoad blog,
  a Medium/Critical-Powers writeup titled "Formulas from *Training and
  Racing with a Power Meter*" that explicitly restates the book's own
  formulas, and a GSSNS blog post of the same name) that agree on every
  step:
  1. Compute a rolling 30-second average power across the ride.
  2. Raise each 30s-average value to the 4th power.
  3. Average those 4th-power values.
  4. Take the 4th root of that average → NP.
  **Intensity Factor (IF):** `IF = NP / FTP`.
  **TSS:** `TSS = duration_hours * IF^2 * 100` — i.e. exactly one hour at
  NP = FTP (IF = 1.0) scores 100. Confirmed via TrainingPeaks' own help-
  center article description (fetched this session) plus independent
  secondary corroboration (TrainerRoad, CTS/TrainRight); note TrainingPeaks'
  own educational article gives the *conceptual* definition ("IF is simply
  the ratio of NP to threshold power... TSS accounts for both IF and
  duration") without restating the bare equation, while the equation itself
  is consistently reproduced by every independent secondary source checked.
  **This exactly matches what `engine/swim_coach/load.py`'s own code
  comment already documents** for the squared (cycling-native) form,
  before the code's own deliberate swim-specific cubing adaptation — this
  pass independently re-confirms that existing citation rather than
  discovering anything new, and additionally nails down the precise NP
  algorithm the existing comment doesn't spell out.
  **Tag for `23-cycling-training.md`:** direct cycling-native evidence
  (practitioner-text tier, matching this project's existing TSS citation's
  own evidentiary footing) — see §7 for the tagging mechanism.

## 3. CTL / ATL / TSB time constants — origin and how well-grounded for cycling

- **✓ Banister E.W., Calvert T.W., Savage M.V., Bach T. (1975)** — "A
  Systems Model of Training for Athletic Performance" — *Australian
  Journal of Sports Medicine*, 7:57-61. The origin of the impulse-response
  ("Banister model") / TRIMP concept the CTL/ATL/TSB machinery descends
  from. Confirmed via multiple independent citation-index listings
  (SciRP, SciEP) this session — **flagged caveat:** these secondary
  citation indexes disagree on the page range (57-61 vs. a second listing's
  170-176 for what is nominally the same paper); the title/authors/journal/
  year are consistent across all listings, only the exact pages are in
  question. Same category of citation-debt this project already tracks
  honestly elsewhere (cf. `reference_list.md`'s Thomas/Mujika/Busso 2008
  entry). Not swim/cycling-specific by itself — it's the general systems-
  model origin later applied to cycling (and swimming, running, etc.).
- **✓ Clarke D.C., Skiba P.F. (2013)** — "Rationale and resources for
  teaching the mathematical modeling of athletic training and performance"
  — *Advances in Physiology Education*, 37:134-152. Confirmed via PubMed,
  the publishing journal (American Physiological Society) and independent
  citation records (ERIC, ResearchGate) this session. Reviews the critical-
  power model and the Banister impulse-response model together; notes
  Skiba's own extension of the TSS framework into power-based metrics for
  cycling (BikeScore) among other sports — direct evidence the TSS-family
  formula machinery is native to, and actively extended within, the cycling
  literature specifically.
- **The specific 42-day CTL / 7-day ATL constants**: confirmed as the
  TrainingPeaks Performance Manager Chart's default parameters (multiple
  independent sources this session: TrainingPeaks' own "Coach's Guide to
  ATL, CTL & TSB," TrainerPlan, Uphill Athlete, FasCat Coaching, all
  converge on 42/7 exactly). This is a **practitioner convention**
  originating from the same Allen/Coggan/TrainingPeaks lineage as the TSS
  formula (§2), **not independently re-derived from cycling performance
  data by any of the sources checked this session** — every source states
  the constants as TrainingPeaks' chosen default, not as a validated
  physiological finding.
  **Honest critical counter-evidence found this session** (the build agent
  should weigh this against the constants' practitioner-convention status):
  - **✓ Vermeire K., Ghijs M., Bourgois J., Boone J. (2022)** — "The
    Fitness–Fatigue Model: What's in the Numbers?" — *International Journal
    of Sports Physiology and Performance*, 17(5):810-813. Confirmed via
    Humankinetics (the publishing journal), ResearchGate, and Ghent
    University's institutional repository this session. A commentary
    urging caution interpreting fitness-fatigue model parameters — notes
    the model's k/time-constant parameters are sensitive to starting
    values, modeling technique, and input data, not fixed physiological
    constants.
  - **✓ Marchal A., Benazieb O., Weldegebriel Y., et al. (2025)** —
    "Statistical flaws of the fitness-fatigue sports performance
    prediction model" — *Scientific Reports*, 15:3706. Confirmed via
    PubMed, PMC, and the publishing journal this session. **Population:
    elite short-track speed skaters (7 athletes, 2019 cohort; 14 athletes,
    2016 cohort) — NOT cyclists.** Found the model ill-conditioned (fitness
    and fatigue time-constant parameters can't be simultaneously estimated
    from typical training data — "antagonistic" correlated parameters), and
    that adding the fatigue term didn't improve cross-validated prediction
    despite improving training-set fit (overfitting). Using their own
    grid-search, found no single optimal fitness time-constant across most
    athlete-fold combinations. **Does not directly address TrainingPeaks/
    Coggan's specific 42/7-day parameters** — it's a general statistical
    critique of the impulse-response model class, in a different endurance
    sport, not a cycling-specific refutation of 42/7. Cite as `[ADAPTED:
    general-endurance]`-tier caution, not as direct cycling counter-evidence.
  **Bottom line for the build agent:** 42/7 is genuinely the standard,
  widely-adopted cycling/TrainingPeaks convention (well-grounded as *that*
  — a practitioner default in near-universal commercial use) but **is not
  independently validated by outcome data specifically for cycling** in
  anything found this session; the model class itself has real, recent
  peer-reviewed statistical critiques (Vermeire 2022, Marchal 2025) that
  should keep the engine's existing "PROVISIONAL" framing rather than
  upgrading to settled fact. This is the same posture `load.py`'s own
  comment already takes toward the swimming question (there, contrasted
  against a reported ~19-day swim-specific fatigue constant); this pass
  adds that even cycling's own literature doesn't treat 42/7 as
  independently validated, just conventional.

## 4. Periodization / volume progression for cycling

- **✓ Galán-Rioja M.Á., González-Ravé J.M., González-Mohíno F., Seiler S.
  (2023)** — "Training Periodization, Intensity Distribution, and Volume
  in Trained Cyclists: A Systematic Review" — *International Journal of
  Sports Physiology and Performance*, 18(2):112-122. Confirmed via
  PubMed, the publishing journal (Human Kinetics), ResearchGate, and
  Universidad Nebrija's institutional repository — the author list
  independently cross-checked across two separate search passes this
  session (converged identically both times). Note: González-Ravé is
  also a co-author on the swim-domain González-Ravé et al. (2021) study
  already in `reference_list.md` (`14-swim-set-structure.md`) — same
  researcher working across both disciplines, not a citation mix-up.
  **Findings:** 7 studies met inclusion criteria (PRISMA methodology,
  PubMed/Web of Science/Scopus searched). Traditional periodization:
  cyclic progressive load increase, 7.5–10.76 h/week training volume,
  pyramidal training-intensity distribution (TID). Block periodization:
  1–8-week concentrated blocks of high/medium/low intensity, 8.75–11.68
  h/week, pyramidal or polarized TID. Block periodization improved
  VO2max, peak aerobic power, lactate and ventilatory thresholds;
  traditional periodization improved VO2max, peak aerobic power, and
  lactate threshold. **Explicit conclusion: "no evidence is currently
  available favoring a specific periodization model" in trained road
  cyclists over 8–12-week windows.**
  **What it does NOT contain (checked specifically, two separate search
  passes this session):** any week-to-week safe volume-*progression-rate*
  number (e.g. a cycling-specific analog to running's contested "10%
  rule," or a specific %-per-week ramp cap). This review compares
  completed periodization *models* against each other, not progression
  *rates* within a build. **Honest gap** — see §5.
  **Tag:** `[ADAPTED: cycling]`, direct cycling-native evidence (see §7 for
  the tagging mechanism), Confidence: high (systematic review, direct
  cycling population) for the periodization-model-comparison finding
  itself; the volume-progression-rate question is a documented absence,
  not a claim.

## 5. Honest no-citable-source outcome: cycling-specific volume progression *rate*

No source found this session (across the Galán-Rioja et al. 2023 review
above and general searches for a cycling-specific progression-rate rule)
gives a validated, cycling-specific week-to-week safe volume-increase
percentage. This project's own swim library already documents the
adjacent finding that the generic "10% rule" (running-derived) is **not**
research-backed (`reference_list.md`'s Buist et al. 2008 entry, already
cited under "Injury & training load") — that finding is discipline-general
in its own critique (it debunks a folk rule, not a cycling-specific one),
so it's reasonable for the build agent to note the same caution applies to
any naive cycling ramp-cap, but this dossier did **not** find or verify a
cycling-specific replacement number. If `23-cycling-training.md` needs a
ramp-cap constant, it should either mark it `Coach judgment:` explicitly
(matching this project's existing practice for the swim engine's own
`+8%/week` rail, which likewise has no direct citation) or adapt the
Garmin-RunSafe single-session-spike finding already in `reference_list.md`
(`[ADAPTED: running]`, already used for `06-long-swim-progression.md`) —
but that would be a genuinely new cross-discipline adaptation, not a
cycling-native finding, and should be tagged and confidence-graded as such.

## 6. Injury / overuse — patellofemoral pain and knee loading in cyclists

- **✓ Clarsen B., Krosshaug T., Bahr R. (2010)** — "Overuse Injuries in
  Professional Road Cyclists" — *American Journal of Sports Medicine*,
  38(12):2494-2501. Confirmed via the publisher (SAGE Journals), PubMed,
  ResearchGate (full PDF), and the Oslo Sports Trauma Research Centre's own
  hosted copy — four independent confirmations this session, the strongest-
  verified source in this dossier. 109 of 116 riders from 7 professional
  teams interviewed; 94 overuse injuries registered. **Lower back 45%,
  knee 23%** (anterior knee pain specifically was a focus of the study
  design). Direct, elite-population, cycling-specific evidence — the best-
  grounded single source for road-cycling overuse/knee-injury prevalence
  found this session.
- **✓ Bini R., Priego-Quesada J. (2022)** — "Methods to determine saddle
  height in cycling and implications of changes in saddle height in
  performance and injury risk: A systematic review" — *Journal of Sports
  Sciences*, 40(4):386-400. Confirmed via the tandfonline journal listing
  and ResearchGate (independent, cross-checked) this session; both authors'
  affiliation (Research Group in Sports Biomechanics, University of
  Valencia) independently corroborated. Screened from 29,398 initially
  identified records down to 41 included studies. **Findings:**
  patellofemoral compressive force is inversely related to saddle height
  (lower saddle → more knee-joint load); a 5% saddle-height change altered
  knee kinematics by 35% and joint moments by 16%; 25–30° knee flexion at
  bottom-dead-center is the consistently recommended target range for
  injury-risk reduction; saddle height should be set via dynamic
  (pedaling) knee-angle measurement, not a static formula alone. The
  review's own stated limitation: evidence linking specific body/bike/
  training-load factors to cycling knee pain is still comparatively weak,
  and included studies are individually small.
  **Tag for both:** `[ADAPTED: cycling]`, direct cycling-native evidence
  (see §7), Confidence: high (Clarsen — elite direct population, large
  prospective cohort by cycling-injury-epi standards) and medium-high
  (Bini/Priego-Quesada — systematic review with a large screened pool, but
  the review's own text flags a still-thin underlying evidence base).

## 7. Discipline sub-variants: does research distinguish road / MTB / cyclocross?

**Yes for road vs. MTB (XCO); largely no, and explicitly stated as no, for
cyclocross** — a genuinely interesting, honest three-part answer, not a
uniform "cycling is cycling" umbrella.

- **✓ Protzen G., Inoue A., Buzzachera C., Doma K., Devantier-Thomas B.,
  Herrero-Molleda A., García-López J., Boullosa D. (2026)** — "The
  Physiology of Contemporary Olympic Cross-Country Mountain Biking: A
  Systematic Review" — *Sports Medicine - Open*, 12:16 (DOI
  10.1186/s40798-026-00976-4). Confirmed via direct fetch of the PMC-hosted
  full text this session (author list, journal, year, volume, article
  number all read directly from the source, not a secondary summary).
  **Findings:** XCO racing is highly intermittent — athletes spend ~25% of
  race time above maximal aerobic power, with 3–10-second surges repeated
  15–20 times per lap, contrasting with road cycling's more continuous
  pacing demands. Elite XCO VO2max is comparable to or exceeds road
  cyclists'. Anaerobic power/capacity contribution has increased over time
  as courses trend "shorter, steeper, and more technically demanding."
  Even non-pedaling technical sections (obstacles, descents) impose real
  physiological stress (elevated HR/VO2) despite low mechanical power
  output during those moments. **This is a direct, distinct MTB (XCO)
  physiological-demand profile, not a road-cycling finding relabeled.**
- **✓ Fallon T., Palmer D., Bigard X., Heron N. (2025)** — "Epidemiology
  of injury and illness across all the competitive cycling disciplines: a
  systematic review and meta-analysis" — *BMJ Open Sport & Exercise
  Medicine*, 11(3):e002364 (DOI 10.1136/bmjsem-2024-002364). Confirmed via
  direct fetch of the PMC-hosted full text this session. Covers road, MTB,
  track, BMX, and para-cycling. **Injury incidence (per 365 days):** BMX
  4.59 (highest), road 3.68, para 3.62, MTB 3.61, track 3.45. Upper-limb
  injuries dominate across disciplines (BMX 65.21%, road 48.32%, track
  44.18% — crash-driven), **contrasting with road-cycling-specific overuse
  studies (5 studies reviewed) where the lower limb dominates (48.82%)** —
  i.e. acute (crash) injury and overuse injury have opposite body-region
  patterns, and Clarsen et al. (2010, §6) is exactly the overuse side of
  that split. **Explicitly states: "cyclocross, gravel cycling, indoor
  cycling, trials and esports have not been represented to date within the
  research."** This is the single strongest, most direct confirmation
  found this session that cyclocross-specific injury/epidemiology research
  is a genuine, acknowledged gap in the literature — not this dossier's own
  search failing to find something that exists.
- **✓ Fallon T., Fischer N., Heron N. (2025)** — "Injury epidemiology in
  cyclocross. A preliminary study" — *The Physician and Sportsmedicine*,
  published online 13 Nov 2025 (DOI 10.1080/00913847.2025.2588650).
  Confirmed via PubMed, the Taylor & Francis journal listing, and
  ResearchGate this session — a legitimate, non-predatory venue (Taylor &
  Francis), unlike the rejected source in the next bullet. Prospective
  observational study at the 2025 British National Cyclocross
  Championships: 534 riders, 6.7% sustained an injury during the event,
  predominantly moderate-severity **acute** injuries, a pattern the authors
  state differs from road or mountain-bike injury patterns. **The authors'
  own title calls this "preliminary"** — it is the first real cyclocross-
  specific epidemiology study found this session (consistent with the
  Fallon et al. meta-analysis above stating cyclocross wasn't previously
  represented), a single event, one country, not yet independently
  replicated. Same first author and research group as the meta-analysis
  above (Queen's University Belfast / British Cycling medical department)
  — not independent corroboration of each other, but a coherent research
  program actively filling the gap it itself identified.
  **Tag for all three:** `[ADAPTED: cycling]`, direct cycling-native
  evidence (see below), Confidence: high (Protzen, direct PMC full-text
  read) / medium-high (Fallon meta-analysis, direct PMC full-text read,
  broad but explicitly incomplete disciplinary coverage) / low-medium
  (Fallon cyclocross preliminary study — real, but self-described
  preliminary, single event, not yet replicated).

## 8. Rejected source — flagged, not cited

- **⚠ Carmichael R.D., Heikkinen D.J., Mullin E.M., McCall N.R. (2017)** —
  "Physiological response to cyclocross racing" — *Sports and Exercise
  Medicine – Open Journal*, 3(3):74-80. **The paper is real** (title,
  authors, journal, volume/issue/pages independently confirmed via
  ResearchGate and the journal's own citation-export page this session) —
  but the publisher, **Openventio Publishers, appears on Beall's List of
  potentially predatory open-access publishers** (confirmed via multiple
  independent sources this session, including an independent "flaky
  academic journals" review naming this exact journal by name). This is
  the **same category of problem** this project already handled once
  before: `reference_list.md`'s "Smith J.A. & Thomas D.T." entry was
  demoted for being published by Hilaris, another predatory venue, and
  explicitly marked "do not cite." **Recommendation: do not cite this
  paper in `23-cycling-training.md`.** It would otherwise have been a
  direct, on-point cyclocross-physiology source (heart rate / blood
  lactate intensity description) and its absence is exactly why §7's
  Fallon et al. papers matter — they're the legitimate replacement for
  the cyclocross-specific gap this rejected paper would have filled.

---

## 9. Tagging mechanism recommended for the build agent (see load-bearing caveat above)

Since `EVIDENCE_ALLOWED = {"swim-ultra", "swim"}` in
`tests/unit/test_library_discipline.py` has no cycling-native value, and
`00-conventions.md` doesn't yet define one, this dossier recommends the
build agent tag direct cycling-native claims (Coggan's zone table, the TSS
formula, Clarsen et al., Galán-Rioja et al., the Fallon/Protzen discipline-
variant findings) as **`[ADAPTED: cycling]`** purely to satisfy the CI
gate's Rule 3 (allowed tag values) and Rule 2 (every `[ADAPTED]` block
needs `Confidence:` + `Test:`) — **not** because these claims are actually
being adapted across disciplines. `Confidence: high` is the honest grade
for these specifically *because* there's no real cross-discipline inference
happening (the tag mechanism, not the epistemic content, is the mismatch).
Every such block still needs a genuine falsifiable `Test:` line — e.g. for
the TSS formula, "if computed TSS values diverge materially from what
TrainingPeaks/intervals.icu compute for the same ride file, re-derive the
NP/IF calculation." The library file's own header should state this
tagging-mechanism caveat plainly (not silently), matching this project's
consistent practice of flagging known gaps rather than smoothing over them
(cf. `INDEX.md`'s "Known gaps" section, the `KNOWN_INVALID_TAGS`/
`KNOWN_ADAPTED_MISSING_TEST` mechanism in `test_library_discipline.py`
itself). This is a genuine schema gap for a future pass to fix (a
`[EVIDENCE: cycling]` value, or a more general reciprocal-discipline
tagging scheme per IDEA 008) — out of scope for this research-only pass to
fix unilaterally, since it would mean editing `00-conventions.md`'s
semantics and the CI gate's allowed-value sets without the human review
step this project's own process requires for exactly that kind of change.
