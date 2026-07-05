# Research Reference List

Curated, verified source list for the swim-coach research library. The
underlying research was collected with Gemini's help, which fabricated the
URL and PubMed/PMC/DOI identifier fields (every `canonical_url` was the bare
string `https://nih.gov`; several ID numbers are impossible). Those fields
have been **stripped** — a paper's title + authors + year + journal is the
trustworthy key here, not any ID. Titles were verified by web search where
marked ✓.

This file is the **canonical citation list**. It supersedes the raw
"Research sources" dump in `ROADMAP.md` and the two deleted vector-schema
files (`open_water_library.md`, `nutrition_multi-sport_adjacent.md`), which
contained fabricated URLs and embedded agent-directive text.

**Verification legend**
- ✓ — paper verified real by title/author search.
- ~ — author is a legitimate researcher in the field, but this specific
  paper was **not** individually verified. Treat as provisional; verify
  before relying on it heavily.
- ⚠ — caveat attached; read the note.

---

## Swimming — CSS, pacing & performance

- **✓ Wakayoshi et al. (1992)** — Critical velocity / Critical Swim Speed
  derivation in swimming (adapted from critical-power theory; validated
  against lactate threshold). Foundation for the engine's CSS-anchored pace
  zones.
- **✓ Saavedra J.M., Einarsson, et al. (2018)** — "Analysis of Pacing
  Strategies in 10 km Open Water Swimming in International Events" —
  *Kinesiology*. 437 swimmers; medal winners and top finishers negative-split
  (first half slower than second).
- **✓⚠ Formosa D.P. et al.** — "Training for a 78-km Solo Open Water Swim" —
  *International Journal of Sports Medicine*. Real training-intensity-
  distribution case study (~Z1 64% / Z2 28% / Z3 8%). **CORRECTION:** the
  actual paper reports weekly volume ~15–70 km/week and a ~3-week taper with
  ~43% volume reduction (intensity maintained). The previously circulated
  "95 km/week, 4-week 25%-linear taper" figures were embellishments and must
  **not** be cited. Note: `engine/swim_coach/plan.py` currently cites this
  source for a 4-week / 25% taper — that citation needs correcting in a later
  engine pass.
- **~ Hue O. et al.** — "Evaluation of Race Pace Using Critical Swimming
  Speed During 10-km Open-Water Swimming." Author legitimate; not
  individually verified.
- **~ Zamparo P. et al.** — pool vs open-water swimming energy cost /
  biomechanical determinants. Zamparo is a leading swimming-energetics
  researcher; this specific paper not individually verified.
- **~ Puce L. et al.** — EMG / kinematic fatigue in long-distance swimmers.
  Not individually verified.
- **~ Psycharakis & Sanders** — stroke coordination & mechanics
  (~*J Sports Sci* 2010). Author pairing is real and published.

## Swimming — physiology & nutrition

- **✓ Martinez-Sanz J.M. et al. (2024)** — "Endurance in Long-Distance
  Swimming and the Use of Nutritional Aids" — *Nutrients*.
- **✓⚠ Knechtle B. et al.** — "Biochemical and Hematological Changes
  Following the 120-km Open-Water Marathon Swim." Real case report (61-yr-old,
  27 h 33 min). **CORRECTION:** most biomarkers actually stayed within normal
  range; the ">400% CK surge / severe catabolic state / cortisol–testosterone
  crash" claims are **not** supported by the paper. Only the general principle
  "extended recovery is warranted after an ultra-distance swim" survives —
  and only as coach judgment, not as a cited figure.
- **✓⚠ Shaw G. et al. (2014)** — "Nutrition Considerations for Open-Water
  Swimming" — *International Journal of Sport Nutrition and Exercise
  Metabolism*. **NOTE:** this is an IJSNEM review, **not** an "ISSN Position
  Stand" as previously mislabeled. Supports ~90 g/hr carbohydrate for 10 km+
  events fed from pontoons.
- **✓ Jeukendrup A.E. (2014)** — "A Step Towards Personalized Sports
  Nutrition: Carbohydrate Intake During Exercise" — *Sports Medicine*. Up to
  ~90 g/hr from multi-transportable carbohydrate sources; advise intake in
  absolute grams, not per body mass.
- **~ Kato H. et al.** — protein ingestion for ultra-endurance recovery. Not
  individually verified; the previously attached ID was fabricated.
- **⚠ Smith J.A. & Thomas D.T.** — "Optimizing Endurance in Long-distance
  Swimming through Nutritional Support" — Hilaris. **CAVEAT:** the document
  exists, but Hilaris is a known predatory / low-quality publisher. Marked
  UNREVIEWED; prefer Martinez-Sanz (2024) or Shaw (2014) for the same feeding
  claims.

## Injury & training load

- **✓ Dry-land shoulder-strengthening RCTs in competitive swimmers** —
  multiple studies show reduced shoulder pain / injury incidence and improved
  rotator-cuff strength balance from dry-land rotator programs. This is the
  evidence behind the engine's 2×/week strength sessions.
- **✓⚠ Feijen S. et al. (2021)** — "Prediction of Shoulder Pain in Youth
  Competitive Swimmers" — *American Journal of Sports Medicine*. Acute:chronic
  workload ratio associated with shoulder pain, odds ratio ~4.31 — but in
  **youth** swimmers, with a wide confidence interval whose lower bound sits
  at ~1.0 (marginal significance). ACWR methodology is broadly criticized;
  treat as weak evidence.
- **✓ Garmin-RunSafe running-health cohort** — "How much running is too much?
  Identifying high-risk running sessions in a 5200-person cohort study" —
  *British Journal of Sports Medicine* (2025/26). Injury risk rose when a
  single session exceeded ~10% of the longest run in the prior 30 days;
  week-to-week ratio and ACWR were weak predictors.
  `[ADAPTED: running]` — most relevant to long-swim progression.
  Confidence: medium. Test: flag any single long swim that exceeds the
  athlete's longest swim of the prior 30 days by >10%.
- **✓ Buist et al. (2008)** — RCT finding no injury-rate difference from a
  graded "10% rule" program vs a faster progression; supported by systematic
  reviews concluding no evidence backs the 10% rule. Corrects the common
  misconception that the 10% rule is research-based (it originates from 1980s
  running lore).

## Cross-discipline endurance (cycling / running / triathlon)

- **✓ Rønnestad B.R. & Mujika I. (2014)** — "Optimizing strength training for
  running and cycling endurance performance: A review" — *Scandinavian
  Journal of Medicine & Science in Sports*. Heavy/explosive strength improves
  endurance economy. `[ADAPTED: cycling/running]` rationale for concurrent
  strength work.
- **✓ Sex differences in marathon pacing** — analysis of ~873,000 Berlin
  Marathon finishers — *Scientific Reports* (2026). Men ~2× as likely to "hit
  the wall"; negative or flat pacing is optimal. (Previously mislabeled as
  "The Running Week Research Archive" — that label was fabricated; the study
  itself is real.) `[ADAPTED: running]` supports conservative early pacing for
  ultra swims.
- **~ Walsh J.A. et al.** — prolonged cycling reduces subsequent running
  economy (bike-to-run transition). Not individually verified.
- **~ Millet G.P. & Vleck V.E.** — physiological / metabolic demands of
  running vs cycling in triathletes. Real authors; the attached PubMed ID was
  fabricated. Not individually verified.
- **~ Chapman A.R. et al.** — biomechanics of running after cycling. Not
  individually verified.

## Practical / non-journal resources

These are web resources rather than journal citations, so their URLs are the
resource itself and are kept.

- Santa Barbara Channel Swimming Association — channel/marathon-swim training
  guidance: <https://santabarbarachannelswim.org/training>
- PurplePatch Fitness — open-water pacing tips:
  <https://www.purplepatchfitness.com/freetrainingtips/triathlon-open-water-swimming-tips-and-strategies>
- Fueling technique ("bottle on a string"):
  <https://www.youtube.com/watch?v=41c61sus4Xg>

---

## Corrections log

Provenance of the fixes applied while curating this list:

1. **Formosa (78-km case study)** — corrected the taper/volume figures:
   actual paper is ~15–70 km/week and a ~3-week / ~43% taper, not
   "95 km/week, 4-week / 25% linear." Engine constants in `plan.py` that cite
   this source for taper length/decay need re-citing.
2. **Knechtle (120-km swim)** — removed the embellished biomarker claims
   (">400% CK," "severe catabolic state"); the real case kept most biomarkers
   within normal range. Kept only a general "extended recovery" takeaway as
   coach judgment.
3. **Shaw (2014)** — relabeled from "ISSN Position Stand" to its true form, an
   IJSNEM review.
