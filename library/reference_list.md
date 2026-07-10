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
- **✓ Mujika I., Padilla S. (2003)** — "Scientific bases for precompetition
  tapering strategies" — *Medicine & Science in Sports & Exercise*, 35(7):
  1182-1187. Foundational taper-physiology review: maintain training
  intensity while reducing volume 60-90% and frequency by no more than
  ~20%; taper duration 4-28 days studied, progressive non-linear tapers
  outperform step tapers; typical performance gain ~3% (range 0.5-6.0%).
  This is the taper-*mechanism* citation the project had been missing
  (Formosa above is a single-case *example*, not the mechanism review).
- **✓ Wang Z., Wang Y.T., Gao W., Zhong Y. (2023)** — "Effects of tapering
  on performance in endurance athletes: A systematic review and
  meta-analysis" — *PLOS ONE*, 18(5):e0282838. 14-study meta-analysis:
  tapering significantly improved time-trial/time-to-exhaustion
  performance (no significant effect on VO2max or economy); ≤21-day
  tapers with 41-60% volume cut (intensity/frequency roughly held) were
  generally effective, and tapers ≤7 days still produced a positive
  effect, though 8-14 days showed the largest gains. `[ADAPTED:
  general-endurance]` — not swim-specific, and doesn't model a
  short-taper-before-a-B-event-then-A-event scenario directly; see
  `10-recovery-hrv.md`'s mini-taper section.
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
- **✓ Kato H., Suzuki K., Bannai M., Moore D.R. (2016)** — "Protein
  Requirements Are Elevated in Endurance Athletes after Exercise as
  Determined by the Indicator Amino Acid Oxidation Method" — *PLOS ONE*,
  11(6):e0157406. **UPGRADED from `~` to `✓`** (see Corrections log):
  fetched directly from the publisher; six endurance-trained runners did a
  3-day/35 km training protocol + a 20 km test run, then had protein
  requirement derived via indicator amino acid oxidation — Estimated
  Average Requirement = 1.65 g/kg/day, Recommended (safe) intake =
  1.83 g/kg/day, well above the general-population RDA of 0.8 g/kg/day.
  `[ADAPTED: running]` (subjects were runners, not swimmers). Not
  "ultramarathon-specific" as an earlier, unverified characterization of
  this paper implied — there is no ultramarathon protocol in the study.
- **✓ Ivy J.L. et al. (1988)** — "Muscle glycogen synthesis after exercise:
  effect of time of carbohydrate ingestion" — *Journal of Applied
  Physiology*, 64(4):1480-1485. 12 male cyclists; immediate (vs. 2h-delayed)
  ingestion of a 2 g/kg carbohydrate solution roughly doubled glycogen
  resynthesis rate over the first 4h of recovery. `[ADAPTED: cycling]`,
  classic, widely-replicated finding.
- **✓ Burke L.M., Hawley J.A., Wong S.H.S., Jeukendrup A.E. (2011)** —
  "Carbohydrates for training and competition" — *Journal of Sports
  Sciences*, 29(sup1):S17-S27. IOC-conference-linked review recommending
  ~1.0-1.2 g/kg/h carbohydrate in the first 4h post-exercise for glycogen
  resynthesis, highest-priority in the first 1-2h. `[ADAPTED:
  general-endurance]`.
- **✓ Koopman R., Pannemans D.L.E., Jeukendrup A.E., Gijsen A.P.,
  Senden J.M.G., Halliday D., Saris W.H.M., van Loon L.J.C.,
  Wagenmakers A.J.M. (2004)** — "Combined ingestion of protein and
  carbohydrate improves protein balance during ultra-endurance exercise" —
  *American Journal of Physiology-Endocrinology and Metabolism*,
  287(4):E712-720. 8 endurance athletes, 6h mixed-modality effort at 50%
  VO2max; carbohydrate+protein co-ingestion (0.7 g/kg/h CHO + 0.25 g/kg/h
  protein) produced a positive/less-negative whole-body protein balance vs.
  carbohydrate-only. `[ADAPTED: general-endurance]`.
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

## Recovery, sleep & HRV

- **✓ Driller M., Leabeater A. (2023)** — "Fundamentals or Icing on Top of
  the Cake? A Narrative Review of Recovery Strategies and Devices for
  Athletes" — *Sports (Basel)*, 11(11):213. Narrative review classifying
  recovery modalities by evidence strength; concludes sleep, nutrition, and
  periodization are the evidence-backed foundation — many recovery
  *devices* (foam rolling, cryotherapy, photobiomodulation) lack strong
  support and shouldn't be prioritized over fundamentals. `[ADAPTED:
  general-endurance]`, Confidence: medium (narrative, not systematic,
  review).
- **✓ Braun-Trocchio R., Graybeal A.J., Kreutzer A., et al. (2022)** —
  "Recovery Strategies in Endurance Athletes" — *Journal of Functional
  Morphology and Kinesiology*, 7(1):22. Survey (not an efficacy trial) of
  264 endurance athletes across 11 sports: hydration, nutrition, sleep, and
  rest are the most-used/most-trusted recovery practices. Descriptive
  only — cite as color for what practitioners prioritize, not as proof any
  practice works.
- **✓ Moore E., Fuller J.T., Buckley J.D., Saunders S., Halson S.L.,
  Broatch J.R., Bellenger C.R. (2022)** — "Impact of Cold-Water Immersion
  Compared with Passive Recovery Following a Single Bout of Strenuous
  Exercise on Athletic Performance in Physically Active Participants: A
  Systematic Review with Meta-analysis and Meta-regression" — *Sports
  Medicine*, 52(7):1667-1688. Meta-analysis: CWI improved muscular-power
  recovery, soreness, and CK after eccentric/high-intensity exercise, but
  was **not effective** at improving recovery of *endurance* performance at
  24h or 48h. `[ADAPTED: general-endurance]`, Confidence: medium-high.
- **✓ Hill J., Howatson G., van Someren K., Leeder J., Pedlar C. (2014)** —
  "Compression garments and recovery from exercise-induced muscle damage: A
  meta-analysis" — *British Journal of Sports Medicine*, 48:1340-1346.
  Small-to-moderate benefit for soreness/strength recovery (strongest in
  the 24h+ window), weaker/inconsistent for objective performance measures.
  `[ADAPTED: general-endurance]`, Confidence: low-medium (title/author/
  journal corroborated across independent secondary listings, not
  individually fetched full-text).
- **✓ Mah C.D., Mah K.E., Kezirian E.J., Dement W.C. (2011)** — "The
  Effects of Sleep Extension on the Athletic Performance of Collegiate
  Basketball Players" — *Sleep*, 34(7):943-950. 11 basketball players
  extended sleep toward ~10h/night for 5-7 weeks; sprint speed, free-throw/
  3-point accuracy, reaction time, and mood all improved. `[ADAPTED:
  general-endurance]`, Confidence: medium (single small-n team-sport
  study).
- **✓ Bonnar D., Bartel K., Kakoschke N., et al. (2018)** — "Sleep
  Interventions Designed to Improve Athletic Performance and Recovery: A
  Systematic Review of Current Approaches" — *Sports Medicine*, 48(3):
  683-703. Systematic review: sleep *extension* is the most consistently
  beneficial intervention for performance/recovery; napping and sleep-
  hygiene education produce mixed results. `[ADAPTED: general-endurance]`,
  Confidence: high (review-level).
- **✓ Kiviniemi A.M. et al. (2007)** — "Endurance training guided
  individually by daily heart rate variability measurements" — *European
  Journal of Applied Physiology*, 101(6):743-751. 26 moderately-fit males,
  4 weeks; HRV-guided training (hard only on stable/rising-HRV days, easy/
  rest below a rolling-mean-minus-SD threshold) improved maximal running
  velocity more than a predefined program. `[ADAPTED: running]`,
  Confidence: medium (small n, 4 weeks; foundational, frequently-replicated
  protocol design).
- **✓ Vesterinen V., Nummela A., Heikura I., Laine T., Hynynen E.,
  Botella J., Häkkinen K. (2016)** — "Individual Endurance Training
  Prescription with Heart Rate Variability" — *Medicine & Science in
  Sports & Exercise*, 48(7):1347-1354. 40 recreational runners, 8-week
  block; HRV-guided training produced greater aerobic-performance gains
  than a fixed program. `[ADAPTED: running]`, Confidence: medium.
- **✓ Javaloyes A., Sarabia J.M., Lamberts R.P., Plews D., Moya-Ramon M.
  (2020)** — "Training Prescription Guided by Heart Rate Variability Vs.
  Block Periodization in Well-Trained Cyclists" — *Journal of Strength and
  Conditioning Research*, 34(6):1511-1518. 20 well-trained cyclists, 8
  weeks; HRV-guided group improved VO2max, peak power, ventilatory
  thresholds, and 40-min TT more than block periodization. `[ADAPTED:
  cycling]`, Confidence: medium.
- **✓ Saw A.E., Main L.C., Gastin P.B. (2016)** — "Monitoring the athlete
  training response: subjective self-reported measures trump commonly used
  objective measures: a systematic review" — *British Journal of Sports
  Medicine*, 50(5):281-291. 56-study systematic review: subjective and
  objective load-response measures generally did not correlate with each
  other, and subjective measures showed *greater* sensitivity/consistency
  in detecting acute and chronic training-load response. `[ADAPTED:
  general-endurance/multi-sport]`, Confidence: high — directly grounds
  `engine/swim_coach/load.py`'s `wellness_composite` as a legitimate
  primary signal, not a fallback for when HRV/objective data is
  unavailable.
- **✓ Collette R., Kellmann M., Ferrauti A., Meyer T., Pfeiffer M.
  (2018)** — "Relation Between Training Load and Recovery-Stress State in
  High-Performance Swimming" — *Frontiers in Physiology*, 9:845. 5 elite
  female swimmers, 17 weeks: session-RPE (particularly a distance-weighted
  variant) tracked recovery-stress state (Acute Recovery and Stress Scale)
  better than acute:chronic workload ratio (ACWR); individual baselines
  outperformed group-level thresholds. `[EVIDENCE: swim]`, Confidence: high
  for population/question match (n=5 is small, but purpose-built for this
  exact population and question) — swim-specific corroboration for
  `03-periodization.md`'s ACWR-is-weak caveat, currently sourced only from
  the running Garmin-RunSafe cohort.

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
4. **Kato H. et al. (2016)** — upgraded from `~` (not individually verified)
   to `✓`: paper fetched directly from the publisher (PLOS ONE) and
   confirmed; the placeholder description ("protein ingestion for
   ultra-endurance recovery," not individually verified) is replaced with
   the real finding (endurance-trained runners, EAR 1.65 g/kg/day / RDA
   1.83 g/kg/day). Also corrects a separate, unverified characterization
   that had called this paper "ultramarathon-specific" — the actual study
   protocol is a 3-day/35 km training block plus a 20 km test run, not an
   ultramarathon.
