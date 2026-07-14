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
  Swimming through Nutritional Support" — Hilaris. **DEMOTED (2026-07-13):**
  the document exists, but Hilaris is a known predatory / low-quality
  publisher, and the `08-ultra-feeding.md` research pass found nothing to
  rehabilitate it. Do not cite. Martinez-Sanz (2024), Shaw (2014),
  Wagner (2012) and Cox (2002) below now cover the same feeding/hydration
  ground with real, verified citations — prefer those.

## Fuelling, hydration & hyponatremia

Curated for `08-ultra-feeding.md` (2026-07-13 pass;
`library/research-dossiers/2026-07-13-ultra-feeding.md` is the raw research
input, not itself citable).

- **✓ Bergström J., Hermansen L., Hultman E., Saltin B. (1967)** — "Diet,
  Muscle Glycogen and Physical Performance" — *Acta Physiologica
  Scandinavica*, 71:140-150. 9 subjects, needle biopsy, cycling to
  exhaustion at 75% VO2max: time to exhaustion 59 min (low-carbohydrate
  diet), 126 min (mixed), 189 min (carbohydrate-rich), correlating with
  starting muscle glycogen. `[ADAPTED: cycling]`. The foundational
  starting-glycogen-determines-duration finding; small n, 1967, male.
- **✓ Coyle E.F., Coggan A.R., Hemmert M.K., Ivy J.L. (1986)** — "Muscle
  glycogen utilization during prolonged strenuous exercise when fed
  carbohydrate" — *Journal of Applied Physiology*, 61(1):165-172. 7 trained
  cyclists at 71% VO2max; carbohydrate feeding delayed fatigue by ~1h
  **without sparing muscle glycogen** — it works via blood glucose.
  `[ADAPTED: cycling]`. The reason "carbs helped" does not prove "it was
  glycogen."
- **✓ Coggan A.R., Coyle E.F. (1987)** — "Reversal of fatigue during
  prolonged exercise by carbohydrate infusion or ingestion" — *Journal of
  Applied Physiology*, 63(6):2388-2395. 7 cyclists fatigued at ~170 min at
  70% VO2max with plasma glucose fallen to 3.1 mmol/L; fatigue was reversed
  by glucose ingestion (26 min further) or IV infusion (43 min further) vs.
  placebo (10 min). `[ADAPTED: cycling]`. Sets the fatigue point at ~2.8h
  and localises it to blood glucose.
- **✓ Gonzalez J.T., Fuchs C.J., Betts J.A., van Loon L.J.C. (2016)** —
  "Liver glycogen metabolism during and after prolonged endurance-type
  exercise" — *American Journal of Physiology - Endocrinology and
  Metabolism*, 311(3):E543-E553. Review: liver glycogen is a small store,
  substantially depleted by an overnight fast, and central to maintaining
  euglycemia — historically neglected relative to muscle glycogen.
  `[ADAPTED: general-endurance]`. **Cite qualitatively only — specific gram
  figures were not verified from the primary text.**
- **✓ Areta J.L., Hopkins W.G. (2018)** — "Skeletal Muscle Glycogen Content
  at Rest and During Endurance Exercise in Humans: A Meta-Analysis" —
  *Sports Medicine*, 48(9):2091-2102. Establishes normative muscle-glycogen
  values at rest and during exercise and their modification by training
  status and carbohydrate availability. `[ADAPTED: general-endurance]`.
  **Cite qualitatively — numeric thresholds not verified from a primary
  read.**
- **✓ Tarnopolsky M.A. (2008)** — "Sex Differences in Exercise Metabolism and
  the Role of 17-Beta Estradiol" — *Medicine & Science in Sports & Exercise*,
  40(4):648-654. Review: women oxidize proportionally more fat and less
  carbohydrate at matched relative intensity, with evidence of muscle-
  glycogen sparing; estradiol appears causal. `[ADAPTED: general-endurance]`.
  Relevant caveat: nearly all glycogen-timeline studies above are male.
- **✓ Tucker R. (2009)** — "The anticipatory regulation of performance: the
  physiological basis for pacing strategies and the development of a
  perception-based model for exercise performance" — *British Journal of
  Sports Medicine*, 43(6):392-400. RPE is matched against a subconscious
  template scaled to the *expected* endpoint. `[ADAPTED: running/cycling]`.
  **Contested** — the anticipatory-regulation / "central governor" family of
  models has active critics; cite the expectation-moves-RPE finding, not the
  model, as settled.
- **✓ Baden D.A., McLean T.L., Tucker R., Noakes T.D., St Clair Gibson A.
  (2005)** — "Effect of anticipation during unknown or unexpected exercise
  duration on rating of perceived exertion, affect, and physiological
  function" — *British Journal of Sports Medicine*, 39(10):742-746. RPE and
  affect shifted sharply when *expected* duration changed, with treadmill
  speed and physiological demand held constant. `[ADAPTED: running]`. The
  cleanest evidence that a "wall" can be produced by expectation alone.
- **~ Eston R. et al. (2012)** — "Effect of deception and expected exercise
  duration on psychological and physiological variables during treadmill
  running and cycling" — *Psychophysiology*, 49(4). Deception about task
  duration altered RPE and pacing without physiological justification.
  `[ADAPTED: running/cycling]`. **Full author list and pages not
  individually verified.** Independent corroboration of Baden (2005).
- **✓ Chambers E.S., Bridge M.W., Jones D.A. (2009)** — "Carbohydrate sensing
  in the human mouth: effects on exercise performance and brain activity" —
  *The Journal of Physiology*, 587(8):1779-1794. Mouth-rinsing (not
  swallowing) carbohydrate improved cycling time-trial performance and
  activated taste/reward brain regions on fMRI, independent of sweetness.
  `[ADAPTED: cycling]`. Proves a central/oral route with zero substrate
  delivery — the reason a naive feeding trial cannot diagnose a "wall."
  Note: mouth-rinse effects are most reliable in efforts <1h and in fasted
  subjects.
- **~ Carter J.M., Jeukendrup A.E., Jones D.A. (2004)** — "The effect of
  carbohydrate mouth rinse on 1-h cycle time trial performance" — *Medicine
  & Science in Sports & Exercise*, 36(12). The original mouth-rinse study.
  `[ADAPTED: cycling]`. **Not individually verified from the primary source
  — prefer Chambers et al. (2009) for the same point.**
- **✓ Jeukendrup A.E. (2017)** — "Training the Gut for Athletes" — *Sports
  Medicine*, 47(Suppl 1):101-110. The gut is nutrient-specifically trainable
  (gastric emptying, comfort, intestinal absorption); rehearse the
  competition feeding strategy at least weekly. `[ADAPTED:
  general-endurance]`. **COI: the author has extensive long-standing
  sports-nutrition industry ties; findings are well replicated but the
  field's central recommendations originate largely from industry-adjacent
  labs.**
- **✓ Miall A., Khoo A., Rauch C., Snipe R.M.J., Camões-Costa V.L.,
  Gibson P.R., Costa R.J.S. (2018)** — "Two weeks of repetitive gut-challenge
  reduce exercise-associated gastrointestinal symptoms and malabsorption" —
  *Scandinavian Journal of Medicine & Science in Sports*, 28(2):630-640.
  Two weeks of repeated in-run carbohydrate exposure reduced GI symptoms and
  malabsorption, increased blood glucose availability, and improved
  performance. `[ADAPTED: running]`. The experimental basis for "90 g/h is a
  trained capacity, not a starting one." Small n.
- **✓ Cox G.R., Broad E.M., Riley M.D., Burke L.M. (2002)** — "Body mass
  changes and voluntary fluid intakes of elite level water polo players and
  swimmers" — *Journal of Science and Medicine in Sport*, 5(3):183-193.
  Elite swimmers' pool-training sweat rates were low (~138 mL/km male,
  ~107 mL/km female) and dehydration was consistently less than in
  land-based athletes. `[EVIDENCE: swim]`. Establishes that pool swimming is
  a low-sweat-loss activity — do not back-apply warm-open-water fluid
  numbers to pool sessions.
- **✓ Chalmers S., Shaw G., Mujika I., Jay O. (2021)** — "Thermal Strain
  During Open-Water Swimming Competition in Warm Water Environments" —
  *Frontiers in Physiology*, 12:785399. Perspective piece (**not primary
  data**) on the significant thermal/physiological strain of warm-water
  open-water racing. `[EVIDENCE: swim]`. Directly relevant to a September
  swim in Greece.
- **~ Gonzalez-Custodio A., Crespo C., Gonzalez-Perez I., Timon R.,
  Olcina G. (2025)** — "Sweat rates during international open water
  competitions and the importance of feedings in elite swimmers" (in
  Spanish) — *E-balonmano.com: Revista de Ciencias del Deporte*,
  21(2):291-298. 45 elite open-water swimmers; reported sweat rates ~1.99
  L/h in warm water vs. ~1.14-1.48 L/h otherwise. `[EVIDENCE: swim]`,
  Confidence: **low-medium**. **Method caveat: "sweat rate" is derived from
  body-mass change, which during immersion cannot be separated from urine
  loss (see Epstein 1992) — the figure is very likely inflated. Use
  directionally ("warm open water causes real fluid loss"), never as a
  replacement target.** Small, low-impact, Spanish-language journal;
  unreplicated.
- **✓ Shirreffs S.M., Taylor A.J., Leiper J.B., Maughan R.J. (1996)** —
  "Post-exercise rehydration in man: effects of volume consumed and drink
  sodium content" — *Medicine & Science in Sports & Exercise*,
  28(10):1260-1271. A volume greater than the sweat loss must be ingested to
  restore fluid balance, but unless drink sodium is high enough this merely
  increases urine output; fluid retained was directly related to sodium
  concentration. `[ADAPTED: general-endurance]`. The canonical source for the
  150%-of-losses rule. 12 men, cycling.
- **✓ Merson S.J., Maughan R.J., Shirreffs S.M. (2008)** — "Rehydration with
  drinks differing in sodium concentration and recovery from moderate
  exercise-induced hypohydration in man" — *European Journal of Applied
  Physiology*, 103(5):585-594. 150% of body-mass loss given at 1/31/40/50
  mmol/L sodium; urine output inversely related to sodium, with 40-50 mmol/L
  producing effective rehydration vs. a sodium-free drink. `[ADAPTED:
  general-endurance]`. Pins the practical sodium threshold — most sports
  drinks (~10-25 mmol/L) fall below it.
- **✓ Evans G.H., James L.J., Shirreffs S.M., Maughan R.J. (2017)** —
  "Optimizing the restoration and maintenance of fluid balance after
  exercise-induced dehydration" — *Journal of Applied Physiology*,
  122(4):945-951. Review: replacement volume must exceed losses; plain water
  provokes diuresis; sodium is the key determinant of retention;
  carbohydrate/protein and food eaten with fluid also aid retention; alcohol
  impairs it. `[ADAPTED: general-endurance]`. The review-level citation to
  lead the rehydration section.
- **✓ McDermott B.P., Anderson S.A., Armstrong L.E., Casa D.J.,
  Cheuvront S.N., Cooper L., et al. (2017)** — "National Athletic Trainers'
  Association Position Statement: Fluid Replacement for the Physically
  Active" — *Journal of Athletic Training*, 52(9):877-895. 31 graded
  recommendations; explicitly treats **hyperhydration** as a risk alongside
  hypohydration and warns of overdrinking/hyponatremia; individualised plans
  built on measured body-mass change. `[ADAPTED: general-endurance]`.
- **✓ Hew-Butler T., Rosner M.H., Fowkes-Godek S., et al. (2015)** —
  "Statement of the Third International Exercise-Associated Hyponatremia
  Consensus Development Conference, Carlsbad, California, 2015" — *Clinical
  Journal of Sport Medicine*, 25(4):303-320 (also *British Journal of Sports
  Medicine*, 49(22):1432-1446). The governing consensus: definition,
  epidemiology, risk factors, pathophysiology, diagnosis, treatment,
  prevention, and 9 recommendations. Headline prevention position: **drink
  to individually regulated thirst; do not gain weight during exercise.**
  **Safety rail, not a coaching preference.**
- **✓ Hew-Butler T., Loi V., Pani A., Rosner M.H. (2017)** —
  "Exercise-Associated Hyponatremia: 2017 Update" — *Frontiers in Medicine*,
  4:21. EAH = blood sodium <135 mmol/L during or immediately after activity.
  Mechanism: non-osmotic vasopressin secretion → water retention. **Sodium
  ingestion cannot prevent EAH in the setting of excessive fluid intake — it
  is fluid volume, not sodium, that drives final blood sodium.** EAH can
  present with net weight *loss* (hypovolemic EAH) as well as weight gain.
  The Boston Marathon female-sex risk excess disappeared after adjustment for
  BMI and racing time.
- **✓ Rosner M.H. (2019)** — "Exercise-Associated Hyponatremia" —
  *Transactions of the American Clinical and Climatological Association*,
  130. Review. Kidneys excrete ~500-1000 mL/h of water; some athletes drink
  1000-1500+ mL/h. Risk factors: excessive fluid intake (primary), longer
  duration, low or high BMI, **NSAIDs**, SSRIs. **Symptoms include low urine
  output and weight gain** alongside headache, nausea, confusion, seizures —
  and are routinely **mistaken for dehydration**, where giving hypotonic
  fluid would be **detrimental**.
- **✓ Wagner S., Knechtle B., Knechtle P., Rüst C.A., Rosemann T. (2012)** —
  "Higher prevalence of exercise-associated hyponatremia in female than in
  male open-water ultra-endurance swimmers: the 'Marathon-Swim' in Lake
  Zurich" — *European Journal of Applied Physiology*, 112(3):1095-1106.
  36 swimmers over 26.4 km: EAH in **8% of males and 36% of females**; one
  symptomatic female at 127 mmol/L. **`[EVIDENCE: swim-ultra]`** — the
  closest population match in the literature to this athlete (female,
  ultra-distance, open water). Small n (36), single event, cool lake water.
- **✓ Rogers I.R. et al. (2015)** — "Exercise-associated hyponatremic
  encephalopathy in an endurance open water swimmer" — *Wilderness &
  Environmental Medicine*, 26(1). Case report: a **woman** after a **20 km
  open-ocean swim** presented with altered consciousness and **seizures**;
  serum sodium **119 mmol/L**; treated with hypertonic saline and critical
  care, discharged neurologically intact. **`[EVIDENCE: swim-ultra]`**
  (case-report tier — n=1 establishes the failure mode, not its incidence;
  pair with Wagner et al. (2012)). Full author list not transcribed.
- **✓ Knechtle B., Chlíbková D., Papadopoulou S., Mantzorou M., Rosemann T.,
  Nikolaidis P.T. (2019)** — "Exercise-Associated Hyponatremia in Endurance
  and Ultra-Endurance Performance - Aspects of Sex, Race Location, Ambient
  Temperature, Sports Discipline, and Length of Performance: A Narrative
  Review" — *Medicina (Kaunas)*, 55(9):537. Narrative review of EAH across
  disciplines with explicit attention to sex and sport. `[ADAPTED:
  general-endurance]`. Same research group as Wagner (2012) — not fully
  independent corroboration.
- **✓ Epstein M. (1992)** — "Renal effects of head-out water immersion in
  humans: a 15-year update" — *Physiological Reviews*, 72(3):563-621.
  Head-out immersion shifts ~700 mL of blood centrally via hydrostatic
  pressure, suppressing vasopressin and the renin-angiotensin-aldosterone
  system and producing diuresis and natriuresis. `[ADAPTED:
  general-endurance]` (human immersion physiology). **Key practical
  consequence: swimmers urinate during immersion, so post-swim body-mass
  loss overestimates sweat loss — including in published swim "sweat rate"
  figures.**

## Energy availability & RED-S/REDs

Curated for `13-reds-energy-availability.md` (2026-07-13 pass;
`library/research-dossiers/2026-07-13-reds-energy-availability.md` is the
raw research input, not itself citable).

- **✓ Loucks A.B., Thuma J.R. (2003)** — "Luteinizing Hormone Pulsatility Is
  Disrupted at a Threshold of Energy Availability in Regularly Menstruating
  Women" — *Journal of Clinical Endocrinology & Metabolism*, 88(1):297-311.
  29 **sedentary** young women, 5-day EA clamp; LH pulsatility disrupted below
  ~30 kcal/kg LBM/day. **Origin of the "30 kcal/kg" number — a 5-day study in
  sedentary women, NOT a validated clinical threshold for trained or older
  athletes.** Do not use as an engine constant or an athlete target.
- **✓ Mountjoy M., Sundgot-Borgen J., Burke L., et al. (2014)** — "The IOC
  consensus statement: beyond the Female Athlete Triad — Relative Energy
  Deficiency in Sport (RED-S)" — *British Journal of Sports Medicine*.
  Consensus opinion, not primary evidence. Page numbers not confirmed.
- **✓ De Souza M.J., Williams N.I., Nattiv A., et al. (2014)** —
  "Misunderstanding the female athlete triad: refuting the IOC consensus
  statement on Relative Energy Deficiency in Sport (RED-S)" — *British Journal
  of Sports Medicine*, 48(20):1461-1465. Formal rebuttal by the Female Athlete
  Triad expert panel. **The disagreement in this field is between senior
  researchers, not fringe voices.**
- **✓ Mountjoy M. et al. (2018)** — "IOC consensus statement on relative
  energy deficiency in sport (RED-S): 2018 update" — *British Journal of
  Sports Medicine*, 52(11):687-697. Consensus opinion; introduced the RED-S CAT.
- **✓ Mountjoy M., Ackerman K.E., Bailey D.M., Burke L.M., Constantini N.,
  Hackney A.C., Heikura I.A., Melin A., Pensgaard A.M., Stellingwerff T.,
  Sundgot-Borgen J.K., Torstveit M.K., Jacobsen A.U., Verhagen E., Budgett R.,
  Engebretsen L., Erdener U. (2023)** — "2023 International Olympic
  Committee's (IOC) consensus statement on Relative Energy Deficiency in Sport
  (REDs)" — *British Journal of Sports Medicine*, 57(17):1073-1097. Current
  consensus; **abandons fixed EA cut-offs** for an adaptable-vs-problematic
  LEA spectrum plus primary/secondary indicators; introduces REDs CAT2.
  Consensus opinion. **COI note:** IOC-convened panel with a research stake in
  the construct.
- **✓ Stellingwerff T., Mountjoy M., McCluskey W.T., Ackerman K.E.,
  Verhagen E., Heikura I.A. (2023)** — "Review of the scientific rationale,
  development and validation of the International Olympic Committee Relative
  Energy Deficiency in Sport Clinical Assessment Tool: V.2 (IOC REDs CAT2)" —
  *British Journal of Sports Medicine*. **Final diagnosis is explicitly
  physician-led** — the citation for this system's refusal to diagnose.
  Volume/pages not confirmed.
- **✓ Burke L.M., Lundy B., Fahrenholtz I.L., Melin A.K. (2018)** — "Pitfalls
  of Conducting and Interpreting Estimates of Energy Availability in
  Free-Living Athletes" — *International Journal of Sport Nutrition and
  Exercise Metabolism*, 28(4):350-363. Field EA estimates are unreliable; no
  standard protocol; error in every term. **Grounds the rule that the engine
  never computes an EA number.**
- **✓ Areta J.L., Taylor H.L., Koehler K. (2021)** — "Low energy availability:
  history, definition and evidence of its endocrine, metabolic and
  physiological effects in prospective studies in females and males" —
  *European Journal of Applied Physiology*, 121(1):1-21. Prospective evidence
  is thin; controlled LEA interventions typically ≤5 days; thresholds
  "debated in females and unknown in males."
- **✓ Jeukendrup A.E., Areta J.L., Van Genechten L., et al. (2024)** — "Does
  Relative Energy Deficiency in Sport (REDs) Syndrome Exist?" — *Sports
  Medicine*, 54(11):2793-2816. The systematic critique: EA unmeasurable in the
  field, ~90% of the literature observational, circular diagnosis, inflated
  prevalence estimates. Proposes a multi-stressor checklist (AHaRC) instead.
  No COI disclosed.
- **✓ Heikura I.A., Uusitalo A.L.T., Stellingwerff T., Bergland D., Mero A.A.,
  Burke L.M. (2018)** — "Low Energy Availability Is Difficult to Assess but
  Outcomes Have Large Impact on Bone Injury Rates in Elite Distance Athletes"
  — *International Journal of Sport Nutrition and Exercise Metabolism*,
  28(4):403-411. 59 elite distance athletes; amenorrheic women ~4.5× bone
  injury prevalence; diagnostic tools disagreed with each other; reproductive
  function was the most reliable marker. `[ADAPTED: running]`.
- **✓ VanHeest J.L., Rodgers C.D., Mahoney C.E., De Souza M.J. (2014)** —
  "Ovarian suppression impairs sport performance in junior elite female
  swimmers" — *Medicine & Science in Sports & Exercise*, 46(1):156-166. 10
  junior elite female swimmers, 12 weeks: ovarian-suppressed group **-9.8%**
  in 400 m velocity vs. **+8.2%** in cyclic swimmers, with suppressed T3.
  `[EVIDENCE: swim]`, Confidence: medium (n=10, ages 15-17, observational).
- **✓ Caldwell H.G., et al. (2024)** — "The whole-body and skeletal muscle
  metabolic response to 14 days of highly controlled low energy availability
  in endurance-trained females" — *The FASEB Journal*. 12 trained women,
  randomised blinded crossover, 14 days at 22.3 vs. 51.9 kcal/kg FFM/day;
  **20-min TT impaired 7.8%, persisting after 3 days of refuelling**; muscle
  glycogen and mitochondrial capacity unchanged. `[ADAPTED:
  general-endurance]`, Confidence: medium-high. **The best causal-design
  evidence in women found in this pass.**
- **✓ Ackerman K.E., Holtzman B., Cooper K.M., et al. (2019)** — "Low energy
  availability surrogates correlate with health and performance consequences
  of Relative Energy Deficiency in Sport" — *British Journal of Sports
  Medicine*, 53(10):628-633. 1,000 female athletes **aged 15-30**;
  **cross-sectional, entirely self-report on both exposure and outcome.**
  Widely cited as strong; it is not. Confidence: low-medium.
- **✓ Gallant T.L., Ong L.F., Wong L., Sparks M., Wilson E., Puglisi J.L.,
  Gerriets V.A. (2025)** — "Low Energy Availability and Relative Energy
  Deficiency in Sport: A Systematic Review and Meta-analysis" — *Sports
  Medicine*, 55(2):325-339. 59 studies, 6,118 athletes; 44.7% classified LEA;
  performance impairments across several domains; illness absence increased;
  injury findings mixed. Meta-analysis of a mostly cross-sectional,
  self-report literature. Confidence: medium.
- **✓ Melin A., Tornberg Å.B., Skouby S., Faber J., Ritz C., Sjödin A.,
  Sundgot-Borgen J. (2014)** — "The LEAF questionnaire: a screening tool for
  the identification of female athletes at risk for the female athlete triad"
  — *British Journal of Sports Medicine*, 48(7):540-545. Original LEAF-Q
  (score ≥8 = at risk); validated in **elite** female athletes.
- **✓ Rogers M.A., et al. (2021)** — "The Utility of the Low Energy
  Availability in Females Questionnaire to Detect Markers Consistent With Low
  Energy Availability-Related Conditions in a Mixed-Sport Cohort" —
  *International Journal of Sport Nutrition and Exercise Metabolism*, 31(5).
  High sensitivity/NPV, **low specificity** — rule-out tool only, **not** a
  diagnostic surrogate. Page range not confirmed.
- **✓ Klein D.J., McClain P., Montemorano V., Santacroce A. (2023)** —
  "Pre-Season Nutritional Intake and Prevalence of Low Energy Availability in
  NCAA Division III Collegiate Swimmers" — *Nutrients*, 15(13):2827. 30
  swimmers; **43% below 30 kcal/kg FFM**; **LEAF-Q failed to discriminate**
  low-EA female swimmers. Authors note BIA over-estimates FFM in athletes,
  which inflates apparent LEA prevalence. `[EVIDENCE: swim]`, Confidence:
  medium. **The only swimmer-specific LEA study found.**
- **✓ Gowers C.R., McManus C.J., Chung H.C., Jones B., Tallent J.,
  Waterworth S.P. (2025)** — "Assessing the risk of low energy availability,
  bone mineral density and psychological strain in endurance athletes" —
  *Journal of the International Society of Sports Nutrition*. 23 female
  (**45±13y**) and 32 male endurance athletes; 77% of women flagged on
  LEAF-Q; only 9% had low lumbar BMD. **Authors explicitly warn
  peri-menopausal symptoms may have artificially inflated LEAF-Q scores.**
  The closest study found to Renee's age band. Confidence: medium.
- **✓ Fahrenholtz I.L., Sjödin A., Benardot D., Tornberg Å.B., Skouby S.,
  Faber J., Sundgot-Borgen J., Melin A.K. (2018)** — "Within-day energy
  deficiency and reproductive function in female endurance athletes" —
  *Scandinavian Journal of Medicine & Science in Sports*, 28(3):1139-1146.
  25 elite female endurance athletes with **matched 24-h EA**; those with
  menstrual dysfunction spent more of the day in deficit. Timing, not just
  daily total. `[ADAPTED: general-endurance]`, Confidence: medium.
- **✓ Gómez-Bruton A., Gónzalez-Agüero A., Gómez-Cabello A., Casajús J.A.,
  Vicente-Rodríguez G. (2013)** — "Is Bone Tissue Really Affected by Swimming?
  A Systematic Review" — *PLOS ONE*, 8(8):e70119. 64 studies: swimmers' BMD is
  **lower than high-impact athletes and similar to sedentary controls**.
  `[EVIDENCE: swim]`, Confidence: high. **Swimming is not osteogenic.**
- **✓ Gómez-Bruton A., Montero-Marín J., González-Agüero A., Gómez-Cabello A.,
  García-Campayo J., Moreno L.A., Casajús J.A., Vicente-Rodríguez G. (2018)**
  — "Swimming and peak bone mineral density: A systematic review and
  meta-analysis" — *Journal of Sports Sciences*, 36(4):365-377. Quantitative
  confirmation of the above in 18-30y adults. `[EVIDENCE: swim]`.
- **✓ Hutson M.J., O'Donnell E., Brooke-Wavell K., Sale C., Blagrove R.C.
  (2021)** — "Effects of Low Energy Availability on Bone Health in Endurance
  Athletes and High-Impact Exercise as A Potential Countermeasure: A Narrative
  Review" — *Sports Medicine*, 51(3):391-403. High-impact loading is osteogenic
  and **energy-cheap**; rarely used in endurance athletes. Narrative review —
  the countermeasure is a **proposal**, not a completed trial. `[ADAPTED:
  general-endurance]`, Confidence: medium.
- **✓ Cialdella-Kam L., Guebels C.P., Maddalozzo G.F., Manore M.M. (2014)** —
  "Dietary Intervention Restored Menses in Female Athletes with
  Exercise-Associated Menstrual Dysfunction with Limited Impact on Bone and
  Muscle Health" — *Nutrients*, 6(8). **+360 kcal/day for 6 months**: menses
  restored in 7/8 (mean 2.6 months); **bone and muscle outcomes barely moved.**
  n=8, uncontrolled. `[ADAPTED: general-endurance]`, Confidence: low-medium.
- **✓ Kuikman M.A., Mountjoy M., Stellingwerff T., Burr J.F. (2021)** — "A
  Review of Nonpharmacological Strategies in the Treatment of Relative Energy
  Deficiency in Sport" — *International Journal of Sport Nutrition and Exercise
  Metabolism*, 31(3):268-275. Treatment levers: raise energy intake, address
  low **carbohydrate** availability specifically, fix within-day deficit
  windows, bone-building nutrients, mechanical loading, reduce psychogenic
  stress. Narrative review; a published Commentary in Response contests it.
  **Treatment is a clinician's call, not this system's.**
- **✓ Grigg M.J., Thake C.D., Allgrove J.E., King J.A., Thackray A.E.,
  Stensel D.J., Owen A., Broom D.R. (2023)** — "Influence of water-based
  exercise on energy intake, appetite, and appetite-related hormones in adults:
  A systematic review and meta-analysis" — *Appetite*, 180:106375. 8 acute
  studies: water-based exercise does **not** suppress intake vs. land-based and
  *increases* it vs. rest; **cold water (18-20°C) increases intake more than
  neutral water**. `[ADAPTED: general-endurance]`, Confidence: medium.
  **Refutes the "swimming suppresses appetite" assumption.**
- **✓ White L.J., Dressendorfer R.H., Holland E., McCoy S.C., Ferguson M.A.
  (2005)** — "Increased caloric intake soon after exercise in cold water" —
  *International Journal of Sport Nutrition and Exercise Metabolism*,
  15(1):38-47. 11 **men**, submerged cycle ergometer, 20°C vs. 33°C water;
  post-exercise intake ~41-44% higher after cold. Confidence: low-medium for
  transfer (male, cycling, single acute bout).
- **✓ Henninger K., Pritchett K., Brooke K., Dambacher L. (2024)** — "Low
  Energy Availability, Disordered Eating, Exercise Dependence, and Fueling
  Strategies in Trail Runners" — *International Journal of Exercise Science*,
  16(2):1471-1486. 1,955 trail/ultra runners, **ages 18-40**; 43% at LEA risk;
  87.3% exercise-dependence symptoms. Self-report survey, cross-sectional.
  `[ADAPTED: running]`, Confidence: low-medium — **prevalence context only.**
- **✓ Sterringer T., Larson-Meyer D.E. (2022)** — "RMR Ratio as a Surrogate
  Marker for Low Energy Availability" — *Current Nutrition Reports*,
  11:263-272. Promising but unstandardised; misses milder deficiency;
  complementary measure only.
- **✓ Espinar S., Martin-Olmedo J.J., Rueda-Córdoba M., Prado-Nóvoa O.,
  Contreras C., Martínez-Sanz J.M., Jurado-Fasoli L. (2025)** — "RMR and RMR
  ratio are not related to energy availability in elite and pre-elite athletes"
  — *Applied Physiology, Nutrition, and Metabolism*, 50. 49 athletes; **no
  association** between EA and RMR or RMR-ratio. Confidence: medium.
- **✓ Charlton B.T., Forsyth S., Clarke D.C. (2022)** — "Low Energy
  Availability and Relative Energy Deficiency in Sport: What Coaches Should
  Know" — *International Journal of Sports Science & Coaching*, 17(2):445-460.
  Practitioner review; coach's role is **recognise and refer**. As few as 15%
  of coaches are aware of the Triad. Educational, **not** primary evidence.
- **~ Tegg N.L., et al. (2024)** — "Impact of Secondary Amenorrhea on
  Cardiovascular Disease Risk in Physically Active Women: A Systematic Review
  and Meta-Analysis" — *Journal of the American Heart Association*.
  **Full author list NOT confirmed (full text 403'd); verify before relying
  on it.** Physically active women with secondary amenorrhea: lower estradiol,
  lower flow-mediated dilation, **lower resting HR**, lower BP, worse lipids —
  FHA may obviate the cardiovascular benefit of exercise. **Load-bearing for
  the RHR-confound claim in `13-reds-energy-availability.md`; must be upgraded
  to ✓ before that claim leaves `UNREVIEWED`.**

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
- **✓ Nuuttila O.-P., Kyröläinen H., Kokkonen V.-P., Uusitalo A. (2024)** —
  "Morning versus nocturnal heart rate and heart rate variability
  responses to intensified training in recreational runners" — *Sports
  Medicine - Open*, 10:120. 24 recreational runners, 3-week baseline plus
  a 2-week ~80%-training-load-increase block; compared a **morning
  orthostatic** HRV protocol (the same style Kiviniemi/Vesterinen/
  Javaloyes above used) against **nocturnal PPG-wearable** HRV in the same
  athletes. The two correlated at baseline but **diverged in their
  response to the training-load increase**; only the nocturnal signal
  correlated with subsequent 3000m performance change (r=0.63 HR,
  r=-0.50 LnRMSSD). `[ADAPTED: running]`, Confidence: medium — the key
  citation establishing that the Kiviniemi/Vesterinen/Javaloyes trio's
  morning-protocol thresholds were never validated on overnight
  (Oura-style) data; see `10-recovery-hrv.md`'s HRV-guided-load section.
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

## Wearables & device validity

Oura-ring-specific validation research, curated for `10-recovery-hrv.md`'s
"Oura device trust" section. `Nuuttila et al. (2024)` (morning-vs-overnight
HRV protocol comparison) is grouped above with the HRV-guided-training
sources instead, since it's more directly a companion to Kiviniemi/
Vesterinen/Javaloyes than a device-accuracy study.

- **✓ Cao R., Azimi I., Sarhaddi F., Niela-Vilén H., Axelin A., Liljeberg
  P., Rahmani A.M. (2022)** — "Accuracy Assessment of Oura Ring Nocturnal
  Heart Rate and Heart Rate Variability in Comparison With
  Electrocardiography in Time and Frequency Domains: Comprehensive
  Analysis" — *Journal of Medical Internet Research*, 24(1):e27487. 35
  healthy adults, one home overnight recording each vs. a Shimmer3 chest-
  ECG reference; whole-night-average HR and rMSSD correlations both
  approached 1.0 (5-minute-window HR r=0.993, rMSSD r=0.915). Independent
  academic authorship (Turku/UC Irvine), no Oura affiliation found.
  Confidence: high for the whole-night-average unit specifically; authors
  themselves flag single-night, healthy-adults-only sample as a
  generalizability limit.
- **✓⚠ Kinnunen H., Rantanen A., Kenttä T., Koskimäki H. (2020)** —
  "Feasible assessment of recovery and cardiovascular health: accuracy of
  nocturnal HR and HRV assessed via ring PPG in comparison to medical
  grade ECG" — *Physiological Measurement*, 41:04NT01. **Conflict of
  interest:** Kinnunen was Oura's Chief Scientific Officer (2014-2021) at
  publication — manufacturer-affiliated research. Full text paywalled;
  specific effect sizes circulating online (r²=0.996 HR / r²=0.980 HRV)
  are **not confirmed** here and should not be cited as fact without a
  full-text read. Cite as corroborating-but-lower-weight only.
- **✓ Liang T., Yilmaz G., Soon C.-S. (2024)** — "Deriving Accurate
  Nocturnal Heart Rate, rMSSD and Frequency HRV from the Oura Ring" —
  *Sensors*, 24(23):7475. 114 participants (Oura Gen3), SOMNOtouch ECG
  reference, in-lab sleep studies, split younger (20-44y, n=92) vs. older
  (45-68y, n=22). At an 80% data-quality threshold: HR r=0.992-0.994;
  rMSSD r=0.979 (younger)/0.937 (older). Over half of older participants
  exceeded 10% HRV error at the 5-minute level; the 80% quality filter
  rejected ~30-35% of nights outright. Independent academic authorship.
  Confidence: high for whole-night rMSSD as a trend signal; explicitly
  flags age-related and short-window accuracy degradation.
- **✓ Dial M.B., Hollander M.E., Vatne E.A., Emerson A.M., Edwards N.A.,
  Hagen J.A. (2025)** — "Validation of nocturnal resting heart rate and
  heart rate variability in consumer wearables" — *Physiological
  Reports*, 13(16):e70527. 13 healthy adults, 536 nights, head-to-head:
  Oura Gen3/Gen4, Polar Grit X Pro, Garmin Fenix 6, WHOOP 4.0 vs. a Polar
  H10 chest-strap reference. Oura was the best-performing device tested
  for both RHR (CCC 0.97-0.98) and HRV (CCC 0.97-0.99) — ahead of WHOOP
  and well ahead of the Garmin/Polar watches. Independent, multi-night,
  small n. Confidence: medium-high (small n, but only source found
  benchmarking Oura head-to-head against direct competitors).
- **✓⚠ de Zambotti M., Rosas L., Colrain I.M., Baker F.C. (2017)** — "The
  Sleep of the Ring: Comparison of the ŌURA Sleep Tracker Against
  Polysomnography" — *Behavioral Sleep Medicine*, 17(2):124-136. 41
  healthy adolescents/young adults, single in-lab PSG night, **first-
  generation Oura ring**. Total sleep time bias -1.3±21.7 min (88% of
  nights within a clinically satisfactory band); deep sleep significantly
  underestimated (~20 min, p=.004), REM significantly overestimated
  (~17 min, p=.034); specificity to detect wake only 48%. Independent
  (SRI International/Stanford-affiliated). **Major caveat:** superseded
  hardware generation — stage-detail findings should not be assumed to
  transfer unchanged to current rings.
- **✓⚠ Svensson T., Madhawa K., NT H., Chung U., Kishi Svensson A.
  (2024)** — "Validity and reliability of the Oura Ring Generation 3
  (Gen3) with Oura sleep staging algorithm 2.0 (OSSA 2.0) when compared
  to multi-night ambulatory polysomnography" — *Sleep Medicine* (2024).
  96 participants, ages 20-70, multi-night ambulatory PSG, current
  hardware + algorithm. Title/authors/journal corroborated (a published
  comment-and-response pair confirms the study drew scientific scrutiny),
  but full text paywalled — secondary sources describe "good agreement
  with PSG for global sleep measures and light/deep sleep," recorded here
  as an **unverified qualitative characterization only**, not a confirmed
  figure.
- **✓⚠ Maijala A., Kinnunen H., Koskimäki H., Jämsä T., Kangas M.
  (2019)** — "Nocturnal finger skin temperature in menstrual cycle
  tracking: ambulatory pilot study using a wearable Oura ring" — *BMC
  Women's Health*, 19:150. Small pilot (n=22 women); nocturnal skin
  temperature differed 0.30°C between follicular/luteal phases (vs.
  0.23°C oral-thermometer, skin-vs-oral r=0.563); best ovulation-detection
  variant ~83% sensitivity within a fertile window. **Conflict of
  interest:** Kinnunen (Oura's then-CSO) co-authored. Authors themselves
  call it a pilot needing larger validation.
- **✓⚠ Thigpen N., Patel S., Zhang X. (2025)** — "Oura Ring as a Tool for
  Ovulation Detection: Validation Analysis" — *Journal of Medical
  Internet Research*, 27:e60667. **Conflict of interest — significant:**
  all three authors are Oura Health employees (disclosed in the paper);
  reference standard is self-reported home LH-test results from Oura's
  own commercial user base, not a lab-confirmed standard. 1,155 ovulatory
  cycles, 964 users; temperature-based algorithm detected 96.4% of
  ovulations at 1.26-day average error vs. 3.44 days for calendar-based
  estimation. Treat direction as plausible, heavily discount precision of
  the specific percentages given the conflict of interest.
- **✓ Alzueta E., de Zambotti M., Javitz H., et al. (2022)** — "Tracking
  Sleep, Temperature, Heart Rate, and Daily Symptoms Across the Menstrual
  Cycle with the Oura Ring in Healthy Women" — *International Journal of
  Women's Health*, 14:491-503. 26 healthy women, one full cycle each;
  nocturnal HR rose mid-/late-luteal (p=.001), distal skin temperature
  showed the expected biphasic pattern (p=.05). Independent (de Zambotti
  group, no Oura employees). Observational/descriptive — no hormone assay
  collected — not a diagnostic-accuracy validation.
- **✓ Doherty C., Baldwin M., Lambe R., Burke D., Altini M. (2025)** —
  "Readiness, recovery, and strain: an evaluation of composite health
  scores in consumer wearables" — *Translational Exercise Biomedicine*,
  2(2):128-144. Systematic review of 14 composite readiness/recovery/
  strain scores across 10 wearable manufacturers (Oura's Readiness/
  Resilience, Garmin's Body Battery/Training Readiness, WHOOP's Recovery/
  Strain, Polar's Nightly Recharge, and others included). Found none of
  the manufacturers publish exact scoring formulas/weights, and this
  class of proprietary composite score generally lacks independent
  peer-reviewed validation. Title/authors/journal corroborated across
  three independent listings; full publisher text not directly fetched,
  so the characterization above is drawn from consistent secondary
  summaries. **Informs directly:** `10-recovery-hrv.md`'s Readiness-score
  section — the composite should not drive plan decisions; use raw
  HRV/RHR/sleep instead.

**Rejected/unverifiable, not cited above:** Oura's own marketing blog post
summarizing Dial et al. 2025 (cite Dial directly, not the blog); an
aggregator claim linking Oura temperature deviation to Kinsa QuickCare
oral-thermometer readings (untraceable to a primary source); Marco Altini's
Substack commentary on motion-artifact HRV (Altini is a legitimate
researcher and a Doherty et al. 2025 co-author, but a Substack post isn't a
citable primary source — the underlying point is already covered by Cao
2022 and Liang 2024's own discussion sections); viral "15.6%/74% HRV drop
after drinking" figures attributed to Oura/WHOOP user data (no traceable
primary study found).

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
5. **Smith & Thomas (Hilaris) demoted** (2026-07-13, `08-ultra-feeding.md`
   pass): the `⚠` entry above is no longer cited anywhere — its ground
   (open-water swim feeding/nutrition) is now covered by verified sources
   (Martinez-Sanz 2024, Shaw 2014, Wagner 2012, Cox 2002) added in the same
   pass, and the predatory-publisher caveat found nothing to rehabilitate
   the original entry.
