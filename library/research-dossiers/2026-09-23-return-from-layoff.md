# Return-to-Training After a Layoff Research Dossier — feeds a future `library/` section on return-from-layoff progression (swim volume + strength)

> **Provenance note:** this is raw research input for a future library section
> (likely a new `library/25-return-from-layoff.md`, or additions to
> `03-periodization.md`'s ramp-cap discussion and `07-strength-dryland.md`'s
> already-flagged "no citable return progression" gap). It is **not itself a
> citable library file** — for grounding claims, cite `library/reference_list.md`
> and the eventual topic file directly, never this dossier. Follows the
> citation discipline in `library/00-conventions.md` and
> `library/reference_list.md` (cite by title + author + year + journal,
> **never** by URL/PMC/PubMed/DOI ID; every source carries a ✓/~/⚠ marker).

**Immediate trigger:** the in-app coach logged three separate questions asking
how to progress swim volume and strength after a **5-6 month layoff**.
Population: masters endurance athletes (swimmers primarily, some also cycle
and lift). This is explicitly **not** the injury-rehab return-to-swim
question already covered by `21-shoulder-health-and-load.md` (criteria-based
clearance after a diagnosed shoulder injury) or the compressed
injury-interrupted-taper question already covered by
`22-injury-adapted-taper.md` (`taper_search.py`'s RAMP→HOLD→TAPER, built for
a ~12-13 day runway to a real race after a shoulder/rib injury). This dossier
covers the more general case: a masters athlete who simply stopped training
for months (life, travel, motivation, minor issues never formally
diagnosed/rehabbed) and wants to know how fast they can rebuild, with no
race-runway time pressure forcing the question.

**Source count this pass:** 15 ✓ verified · 2 ~ partial/secondary · 0 ⚠
unverified-but-carried, plus 3 sources reused from `reference_list.md`'s
existing entries (Mujika & Padilla 2000, Garmin-RunSafe cohort, Feijen et al.
2021 — not re-verified here, cross-referenced only). One topic (a
swim-specific or strength-specific *quantitative* return-ramp protocol)
returned an **honest no-citable-source outcome**, consistent with what
`research-dossiers/2026-07-28-strength-programming.md` already found for the
strength side — documented in §4, not papered over.

---

## 1. Executive summary

- **The detraining time course is well-documented and directionally
  consistent across sources, but the exact numbers vary study-to-study**:
  VO2max declines measurably within 2 weeks of complete cessation, drops
  sharply over the first 2-4 weeks, and continues declining (more slowly)
  out to 12 weeks, with cited figures ranging from roughly -5% (2 weeks) to
  -20% (12 weeks) depending on the study and population. The mechanism shifts
  over time: early VO2max loss is driven by falling blood/plasma volume and
  stroke volume; loss from roughly 3 weeks onward increasingly reflects
  reduced mitochondrial oxidative-enzyme activity (citrate synthase,
  succinate dehydrogenase) and a falling arterial-venous oxygen difference.
  **Strength is retained substantially longer than cardiovascular fitness** —
  this is the most load-bearing, best-corroborated claim in this dossier
  (four independent sources agree; see §2 Topic 3).
- **Masters-specific detraining data exists and is more reassuring than
  might be assumed**, but it is not swim-specific: Burtscher et al. (2022)
  found masters athletes' VO2max decline is tightly tied to *training volume*
  changes (54%/39% of variance explained in men/women), and their reduced
  mitochondrial/oxidative capacity from detraining "can be largely rescued"
  on retraining — i.e., masters athletes are not shown to detrain
  catastrophically differently from younger athletes, and what's lost is
  substantially recoverable.
- **Swim-specific detraining data is thin but real and reassuring at the
  layoff length in question.** A genuine natural experiment — the COVID-19
  training interruption — gives the best available swim-specific evidence at
  roughly this dossier's exact layoff length: Tsalis & Mougios (2022) found
  2-4 months of youth-swimmer detraining had a **negligible effect** on
  100m/400m freestyle performance once an equal-length return-to-training
  period followed, with swimmers resuming training at higher aerobic volume
  but *no* intensity initially. This is the single most encouraging,
  most load-bearing finding for framing the athlete's expectations honestly
  (it will come back), even though it's a youth/competitive cohort, not
  masters.
- **"Muscle memory" is real but genuinely contested at the mechanistic
  level, and this dossier deliberately does not overclaim it** — this
  project's own citation discipline (`00-conventions.md`) exists because of
  a prior fabrication incident, and the muscle-memory literature is an
  active scientific dispute, not settled fact. The strongest human data
  (Psilander et al. 2019) found strength stayed markedly elevated above
  baseline through 20 weeks of detraining (a genuine, useful finding) but did
  **not** find faster/enhanced retraining in the previously-trained leg vs.
  a naive control leg — directly cutting against the popular "myonuclei make
  the comeback faster" framing. A separate, real study in **older men**
  specifically (Blocquiaux et al. 2020) *did* find retraining reached the
  prior 1RM in under 8 weeks (vs. the original 12-week build) — genuine
  support for "regaining is faster than gaining" in this dossier's actual
  target population, just not via the myonuclear mechanism the popular
  framing assumes. Present both findings; don't resolve the mechanism debate
  as settled.
- **No swim-specific or strength-specific quantitative return-ramp protocol
  exists in the literature** — this confirms and extends what
  `research-dossiers/2026-07-28-strength-programming.md` already found for
  strength. The best available guidance is qualitative practitioner
  convention (US Masters Swimming's own coach-authored return-to-swimming
  articles) that explicitly avoids giving percentage/yardage targets in
  favor of individualized, symptom-guided pacing. A concrete numeric
  template for this system therefore has to be `Coach judgment`, reconciled
  against the engine's existing `WEEKLY_VOLUME_RAMP_CAP = 0.08` rail — see
  §3.
- **DOMS/rhabdomyolysis risk on first sessions back is real and
  well-documented in the sports-medicine literature**, with "unaccustomed
  intense exercise following a period of inactivity" as a named classic
  trigger pattern — directly relevant to a masters athlete who remembers
  their pre-layoff loads and is tempted to resume there.

---

## 2. Verified sources by topic

### Topic 1 — Detraining time course: general endurance (VO2max, blood volume, mitochondrial enzymes)

- **✓ Mujika I., Padilla S. (2000)** — "Detraining: Loss of Training-Induced
  Physiological and Performance Adaptations. Part I: Short Term Insufficient
  Training Stimulus" and "Part II: Long Term Insufficient Training
  Stimulus" — *Sports Medicine*, 30(2):79-87 and 30(3):145-154. Already
  verified and cited in `reference_list.md`'s "Injury & training load"
  section (reused here, not re-verified this pass). The canonical two-part
  review: short-term (<4 weeks) insufficient stimulus already erodes some
  adaptations; long-term (>4 weeks) detraining markedly reduces VO2max
  (recently-acquired gains lost completely; long-standing gains decline but
  stay above untrained baseline) with parallel muscular/metabolic losses.
  **This dossier's addition beyond the existing citation:** the review's
  own mechanistic account is that early VO2max loss (<3-4 weeks) is driven
  mainly by falling blood/plasma volume and reduced stroke volume, while
  loss from roughly 3 weeks onward (out to 12+ weeks) increasingly reflects
  falling mitochondrial oxidative-enzyme activity and a reduced
  arterial-venous oxygen difference — i.e., the *mechanism* of loss changes
  over the timeline, not just the magnitude.
  **Tag:** `[ADAPTED: general-endurance] Confidence: high` for the
  detraining phenomenon and its two-phase mechanism; not swim-specific.

- **✓ Chen Y.T., Hsieh Y.Y., Ho J.Y., Lin T.Y., Lin J.C. (2022)** — "Two
  Weeks of Detraining Reduces Cardiopulmonary Function and Muscular Fitness
  in Endurance Athletes" — *European Journal of Sport Science*,
  22(3):399-406. **Verification:** title, full author list, journal,
  year, volume/issue/pages confirmed via publisher (Taylor & Francis) and
  independent citation records. 15 endurance-trained male athletes (ages
  19-26), pre/post a 2-week complete detraining period: significant
  decreases in VO2max, exercise time to exhaustion, maximal stroke volume,
  and isokinetic knee-extensor strength. **Why it matters:** the fastest,
  most acute data point in this dossier — real, measurable cardiopulmonary
  loss inside just 2 weeks, useful for calibrating how quickly a masters
  athlete should expect *some* loss even from a short interruption, before
  getting to the 5-6-month case this dossier is actually about.
  **Tag:** `[ADAPTED: general-endurance] Confidence: medium` (direct,
  well-verified finding; young male athletes, not masters or swim-specific).

- **✓ Burtscher J., Strasser B., Burtscher M., Millet G.P. (2022)** — "The
  Impact of Training on the Loss of Cardiorespiratory Fitness in Aging
  Masters Endurance Athletes" — *International Journal of Environmental
  Research and Public Health*, 19(17):11050. **Verification:** title, full
  author list, journal, year, volume/article number confirmed via
  publisher (MDPI) and PubMed listing. Longitudinal masters-athlete data:
  VO2max declines of -5% to -46% per decade correlate with changes in
  *training volume* (explaining 54%/39% of variance in men/women
  respectively, not age per se); an almost-linear VO2max decrease begins
  within days of cessation, reaching roughly -20% by 12 weeks, with a
  faster initial 2-3-week decline followed by a shallower slope; the
  underlying mitochondrial/oxidative-capacity loss (citrate synthase,
  succinate dehydrogenase activity) is "largely rescued" within a similar
  timeframe of retraining. **Why it matters — the best masters-specific
  citation in this dossier:** this is the strongest available evidence that
  a masters athlete's detraining is governed more by *how much volume
  stopped* than by age itself, and that the loss is substantially
  recoverable, not a permanent ratchet down.
  **Tag:** `[ADAPTED: general-endurance] Confidence: medium-high` (direct
  masters population, real longitudinal and mechanistic data; not
  swim-specific).

### Topic 2 — Detraining time course: swim-specific

- **✓ Głyk W., Hołub M., Karpiński J., Rejdych W., Sadowski W., Trybus A.,
  Baron J., Rydzik Ł., Ambroży T., Stanula A. (2022)** — "Effects of a
  12-Week Detraining Period on Physical Capacity, Power and Speed in Elite
  Swimmers" — *International Journal of Environmental Research and Public
  Health*, 19(8):4594. **Verification:** title, full author list, journal,
  year, volume/article number confirmed via publisher (MDPI) and
  independent listings. 14 elite swimmers (7 female, 7 male, age ~20.4),
  tested before and after a 12-week transition-period detraining window
  (land power: Keiser squat/arms, countermovement jump; water: 20m
  legs-only, arms-only, and full-stroke speed): both sexes showed reduced
  lactate-threshold swimming speed and reduced speed/power on
  legs/arms/full-crawl tests after 12 weeks off.
  **Tag:** `[EVIDENCE: swim] Confidence: medium` — direct swim population,
  real measured outcomes; elite/young cohort, not masters, and a *planned*
  transition-period detraining, not an unplanned life-circumstance layoff.

- **✓ Tsalis G., Mougios V. (2022)** — "Effect of the Reduction in Training
  Volume during the COVID-19 Era on Performance in 100-m and 400-m
  Freestyle Events in Greek Swimming Championships" — *Sports*,
  10(3):40. **Verification:** title, full author list, journal, year,
  volume/article number confirmed via publisher (MDPI) and PubMed listing.
  Natural-experiment design: 41 coaches interviewed on training-process
  disruption; national-championship 100m/400m freestyle results for ages
  13-18 compared across seven seasons (2014-2021) spanning two COVID-era
  interruptions of roughly 2-4 months each. **Findings — the single most
  load-bearing swim-specific citation in this dossier:** despite training
  load during lockdown falling ~78% and critical speed dropping ~4.7-4.9%,
  a return-to-training period **of similar length to the interruption**
  restored performance almost fully — only the men's 400m free showed a
  small (-2.7%) decline vs. a pre-pandemic reference season, with no
  significant effect on 100m free or women's 400m free, and no reduction in
  the number of swimmers qualifying for nationals. Coaches reported
  resuming training with **higher aerobic volume but no intensity
  initially**, before reintroducing daily sessions with aerobic/technique
  emphasis.
  **Tag:** `[EVIDENCE: swim] Confidence: medium-high` — real competitive
  outcomes data (not just physiological surrogates), at close to this
  dossier's exact layoff duration; caveat: youth/competitive swimmers, not
  masters, and it's an observational natural experiment (self-reported
  coach process alongside real results), not a controlled trial.
  **This is the paper to lean on for the honest, reassuring framing:**
  "the return took about as long as the layoff, and performance came back."

### Topic 3 — Strength retained longer than cardiovascular fitness/hypertrophy

**This is the best-corroborated claim in the dossier — four independent
lines of evidence agree**, which is why it's promoted to its own topic
rather than folded into Topic 1:

- **✓ Chen et al. (2022)** (Topic 1, reused): even at just 2 weeks,
  isokinetic knee-extensor strength declined — so short-term strength loss
  is real and fast-starting, but see the longer-timeline entries below for
  the "retained longer than endurance" comparison.
- **✓ Encarnação I.G.A., Viana R.B., Soares S.R.S., Freitas E.D.S.,
  de Lira C.A.B., Ferreira-Junior J.B. (2022)** — "Effects of Detraining on
  Muscle Strength and Hypertrophy Induced by Resistance Training: A
  Systematic Review" — *Muscles*, 1(1):1-15. **Verification:** title, full
  author list, journal, year, volume/article number confirmed via
  publisher (MDPI) and independent listings. Systematic review: strength
  gains from resistance training were **maintained through roughly 16-24
  weeks of detraining**, becoming statistically similar to non-exercising
  controls only after **32-48 weeks**. Insufficient data existed to
  meta-analyze hypertrophy loss separately.
  **Tag:** `[ADAPTED: general-endurance] Confidence: medium` — systematic
  review, not swim/masters-specific, but a real, sourced timeline for how
  long strength genuinely persists.
- **✓ Grgic J. (2022)** — "Use It or Lose It? A Meta-Analysis on the
  Effects of Resistance Training Cessation (Detraining) on Muscle Size in
  Older Adults" — *International Journal of Environmental Research and
  Public Health*, 19(21):14048. **Verification:** title, author, journal,
  year, volume/article number confirmed via publisher (MDPI) and PubMed
  listing. Six studies/eight groups, resistance-training interventions 9-24
  weeks, detraining duration 12-52 weeks, **specifically in older adults**:
  no significant decrease in muscle *size* after 12-24 weeks of cessation;
  a significant decrease only appeared after 31-52 weeks.
  **Tag:** `[ADAPTED: general-endurance] Confidence: medium-high` — the
  closest age-matched (older-adult) corroboration of the "strength/muscle
  persists longer than expected" claim in this dossier, though it measures
  muscle size specifically, not strength.
- **✓ Blocquiaux S. et al. (2020)** — "The Effect of Resistance Training,
  Detraining and Retraining on Muscle Strength and Power, Myofibre Size,
  Satellite Cells and Myonuclei in Older Men" — *Experimental Gerontology*,
  133:110860. **Verification:** title, journal, year, volume/article number
  confirmed via publisher (Elsevier/ScienceDirect) and PubMed listing (a
  published corrigendum to this same article also independently confirms
  its existence). 30 older men + 10 controls, 12 weeks resistance training
  → 12 weeks detraining → 12 weeks retraining, with vastus lateralis
  biopsies. **Findings — directly on-point for this dossier's population
  and question:** training increased knee-extension strength/power
  10-36%; detraining produced only a **modest** loss (-5% to -15%) over 12
  full weeks off; critically, **retraining reached the post-training 1RM
  strength level in under 8 weeks** — faster than the original 12-week
  build. Full 12 weeks of retraining also drove type-II fibre hypertrophy
  and increases in satellite-cell and myonuclear counts in type II fibres.
  **Tag:** `[ADAPTED: general-endurance] Confidence: medium-high` — real
  RCT-quality data in exactly this dossier's population (older men), the
  single best citation for "regaining is faster than the original gain" in
  a masters-relevant context; not swim-specific, and it's land-based
  resistance training, not swim-specific muscular endurance.

### Topic 4 — Retraining / "muscle memory": genuinely contested, don't overclaim

**This library has a specific, hard-earned reason to be careful about
overclaiming here** (`00-conventions.md`'s account of fabricated prior
research). The muscle-memory literature is a live, unresolved scientific
dispute at the mechanistic level — this dossier represents that honestly
rather than picking a side.

- **✓ Bruusgaard J.C., Johansen I.B., Egner I.M., Rana Z.A., Gundersen K.
  (2010)** — "Myonuclei Acquired by Overload Exercise Precede Hypertrophy
  and Are Not Lost on Detraining" — *Proceedings of the National Academy of
  Sciences*, 107(34):15111-15116. **Verification:** title, full author
  list, journal, year, volume/pages confirmed via publisher (PNAS) and
  multiple independent citation records. The foundational paper behind the
  popular "muscle memory" narrative: in **mice**, myonuclei added during
  overload-induced hypertrophy were retained even after prolonged
  detraining and fibre atrophy, using in vivo imaging of individual
  myonuclei. **Critical caveat the build agent must carry: this is a
  rodent study.** It is the origin of the myonuclear-permanence hypothesis,
  not itself evidence in humans.
  **Tag:** `[ADAPTED: general-endurance] Confidence: medium` for the
  mechanism-exists-in-principle claim; explicitly **not** direct human
  evidence — downgrade any claim that cites this alone as proof of human
  muscle memory.

- **✓ Psilander N., Eftestøl E., Cumming K.T., Juvkam I., Ekblom M.M.,
  Sunding K., Wernbom M., Holmberg H.C., Ekblom B., Bruusgaard J.C.,
  Raastad T., Gundersen K. (2019)** — "Effects of Training, Detraining, and
  Retraining on Strength, Hypertrophy, and Myonuclear Number in Human
  Skeletal Muscle" — *Journal of Applied Physiology*, 126(6):1636-1645.
  **Verification:** title, full author list, journal, year, volume/pages
  confirmed via publisher (American Physiological Society) and independent
  listings. Human unilateral-training design (one leg trained, one leg
  naive control): 10 weeks training → 20 weeks detraining → 5 weeks
  bilateral retraining, with biopsies. **Findings — the most important
  nuance in this dossier's muscle-memory section:** CSA and muscle
  thickness returned essentially to baseline during the 20-week detraining
  period, but **strength remained ~60% above baseline** throughout — a
  genuine, useful "strength outlasts hypertrophy" finding, attributed to a
  lasting motor-learning/neural effect rather than a structural one.
  Myonuclear number did **not** increase during the original 10-week
  training block in the first place. During retraining, the
  previously-trained leg gained strength/thickness at essentially the
  **same rate as the naive control leg** — i.e., **no enhanced/faster
  retraining response was found in this design**, cutting directly against
  the popular "myonuclei make the comeback faster" framing.
  **Tag:** `[ADAPTED: general-endurance] Confidence: medium` — real human
  RCT-quality data; the "strength retained far longer than size" finding is
  solid, the "no faster retraining" finding is a genuine complication for
  the muscle-memory narrative, not swim/masters-specific.

- **✓ Snijders T., Aussieker T., Holwerda A., Parise G., van Loon L.J.C.,
  Verdijk L.B. (2020)** — "The Concept of Skeletal Muscle Memory: Evidence
  from Animal and Human Studies" — *Acta Physiologica*, 229(3):e13465.
  **Verification:** title, full author list, journal, year, volume/article
  number confirmed via publisher (Wiley) and independent listings. A
  balanced review covering both the animal (myonuclear-permanence,
  supportive) and human (mixed) evidence bases, explicitly noting the
  human data are less consistent than the mouse data underlying the
  popular narrative.
  **Tag:** `[ADAPTED: general-endurance] Confidence: medium` — the
  review-level citation to lead with when representing this topic's actual
  state of evidence, rather than either primary study alone.

- **✓ Rahmati M., McCarthy J.J., Malakoutinia F. (2022)** — "Myonuclear
  Permanence in Skeletal Muscle Memory: A Systematic Review and
  Meta-Analysis of Human and Animal Studies" — *Journal of Cachexia,
  Sarcopenia and Muscle*, 13(5) (2022). **Verification:** title, full
  author list, journal, year confirmed via publisher (Wiley) and PubMed
  listing. 147 studies across five meta-analyses (human/rodent hypertrophy,
  human/rodent atrophy, human ageing). **Headline finding — the sharpest
  counter-evidence in this dossier:** myonuclei were retained with atrophy
  in **rodents** but **not** in **humans** — i.e., the central mechanism
  behind the popular "muscle memory" story (Bruusgaard 2010, in mice) does
  **not** appear to replicate in human atrophy/detraining data at the
  meta-analytic level.
  **Tag:** `[ADAPTED: general-endurance] Confidence: medium-high` (a large,
  recent meta-analysis directly on this question) — the single strongest
  reason not to present myonuclear-driven "muscle memory" as settled human
  physiology in this system's output.

- **✓ Cumming K.T., Reitzner S.M., Hanslien M., Skilnand K., Seynnes O.R.,
  et al. (2024)** — "Muscle Memory in Humans: Evidence for Myonuclear
  Permanence and Long-Term Transcriptional Regulation After Strength
  Training" — *The Journal of Physiology*, 602(17):4171-4193.
  **Verification:** title, journal, year, volume/pages confirmed via
  publisher (Wiley) and independent listings; **full author list beyond
  the first five names not individually confirmed this pass.** A more
  recent, positive re-argument for human myonuclear permanence — i.e., the
  literature has not settled in either direction even by 2024.
  **Tag:** `[ADAPTED: general-endurance] Confidence: medium` — recent,
  published in a top physiology journal, but part of an active back-and-forth
  (see the two entries immediately below), not a resolving finding.

- **✓ Sitko S., Castillo-García A., Valenzuela P.L. (2025)** — "Muscle
  Memory Theory: Implications for Health, Athletic Performance and Sports
  Integrity" — *The Journal of Physiology* (2025), an Opinion piece.
  **Verification:** title, full author list, journal, year confirmed via
  publisher (Wiley) and PubMed listing. Argues myonuclear-content
  differences (from prior training, ageing, or exogenous/endogenous
  hormone exposure) have downstream implications for remodeling capacity
  after disuse — an opinion/implications piece, not new primary data.
  **Tag:** `Coach judgment context only` — an opinion piece arguing the
  practical *stakes* of the debate, not itself evidence either way.

- **✓ Serrano N., Dupont-Versteegden E.E., Murach K.A. (2025)** — "Muscle
  Memory Theory: A Critical Evaluation" — *The Journal of Physiology*,
  603:4705-4711. **Verification:** title, full author list, journal, year,
  volume/pages confirmed via publisher (Wiley) and independent listings.
  Direct published response/counterpoint to the Sitko et al. (2025) opinion
  piece above, applying contemporary myonuclear-biology scrutiny to the
  muscle-memory narrative.
  **Tag:** `Coach judgment context only`, same reasoning as Sitko above —
  documents that as of 2025 this remains an active, published disagreement
  among specialists, not a settled question this system should present as fact.

**Honest synthesis for this topic (do not soften into a single confident
claim):** the human evidence supports "strength is retained well above
baseline for a long time after training stops, and losses are recovered
faster than they took to build" (Psilander 2019's ~60%-retained finding;
Blocquiaux 2020's <8-week older-men retraining finding) — but it does
**not** cleanly support the popular myonuclear mechanism as the explanation,
and the largest human meta-analysis (Rahmati 2022) found myonuclei are
*not* permanent in humans the way they are in mice. **Recommendation for the
eventual library file:** state the practical, well-supported claim
("retraining will likely be faster than the original build, and strength
tends to outlast fitness") without asserting the myonuclear mechanism as
settled human science.

### Topic 5 — Swim volume return progression: practitioner guidance (honest gap)

- **US Masters Swimming** — "What Swimmers Should Know When Returning After
  a Long Layoff" and "What Coaches Should Do After a Long Layoff From
  Workouts," both by **Terry Heggy** (USMS-certified Level 4 Masters coach,
  head coach of Saddlebrook Masters, Arizona). **Practical / non-journal
  resource** — same tier as the Santa Barbara Channel Swimming Association
  guidance already cited in `06-long-swim-progression.md` (the resource
  itself, not a URL/ID, is the citation, per `reference_list.md`'s
  "Practical / non-journal resources" convention). **Content, read in
  full:** both articles deliberately avoid giving percentage or yardage
  return targets. Guidance is qualitative: ease back in 2-3x/week rather
  than immediately resuming prior frequency; lead with technique-focused
  long warm-ups over yardage; use a repeatable weekly test set (over the
  first 4-6 weeks) to track real progress rather than assuming a smooth
  curve (expect plateaus, even brief backslides); build work-set volume by
  adding one repeat per session, or by holding repeat count and shortening
  rest, rather than jumping straight to a target distance; err toward a
  ramp that's "too flat rather than too steep" — the cost of under-doing it
  is a short delay, the cost of over-doing it is soreness/injury that costs
  far more time. **Why this matters for this dossier's honesty:** a
  working masters coach, writing specifically for USMS's own
  returning-after-a-layoff audience, chose *not* to give a number — that is
  itself informative about how settled (or not) a quantitative swim-return
  protocol actually is in real coaching practice.
  **Tag:** `Coach judgment` (practitioner convention) — informs the
  *shape* of a return plan (technique-first, test-set-tracked, err flat)
  but supplies no citable percentage figure.

- **Cross-reference, not re-verified this pass:** generic online
  running-return guidance (multiple commercial coaching blogs) commonly
  states "start at 30-50% of pre-break weekly volume depending on layoff
  length, then apply something like the 10% rule." **This dossier does not
  treat those figures as evidence** — they are unattributed blog-tier
  content, not a verifiable primary source, and this project's own
  reference list already documents that the generic "10% rule" itself
  has been specifically tested and found **not evidence-based** (Buist et
  al. 2008, already in `reference_list.md`, cited in
  `03-periodization.md`). Repeating an unverified blog percentage next to a
  debunked "10% rule" would be exactly the kind of citation-laundering this
  library's conventions exist to prevent. **See §4 for why no swim-specific
  quantitative return-ramp source exists to replace it.**

### Topic 6 — Strength return progression: starting load, DOMS/rhabdomyolysis risk

- **✓ O'Connor F.G., Brennan F.H., Campbell W., Heled Y., Deuster P.
  (2008)** — "Return to Physical Activity After Exertional Rhabdomyolysis"
  — *Current Sports Medicine Reports*, 7(6):328-331. **Verification:**
  title, full author list, journal, year, volume/issue/pages confirmed via
  publisher (Wolters Kluwer/ACSM) and independent listings. Clinical
  guidance on the return-to-activity pathway after a diagnosed
  exertional-rhabdomyolysis episode: confirm normal CK/clear urine, then a
  graded, monitored return; explicitly distinguishes ER from "just" DOMS
  (athletes often mistake early ER symptoms for ordinary soreness, which
  delays presentation).
  **Tag:** `[ADAPTED: general-endurance] Confidence: medium` — clinical
  guidance, not swim/masters-specific, but directly names the risk pattern
  this dossier needs to flag.

- **✓ Tietze D.C., Borchers J. (2014)** — "Exertional Rhabdomyolysis in the
  Athlete: A Clinical Review" — *Sports Health*, 6(4):336-339.
  **Verification:** title, full author list, journal, year, volume/issue/
  pages confirmed via publisher (SAGE) and PubMed listing. Clinical review
  (literature search 2003-2013): names **"unaccustomed high-intensity
  exercise, often following a period of relative inactivity"** as a classic
  triggering pattern for exertional rhabdomyolysis — precisely the
  mechanism of concern for a masters athlete resuming strength work at
  remembered (pre-layoff) loads after 5-6 months off. Also flags eccentric-
  loaded, high-repetition, novel-movement first sessions as higher-risk.
  **Tag:** `[ADAPTED: general-endurance] Confidence: medium** — a clinical
  review, not masters/swim-specific, but this is exactly the mechanism this
  dossier's strength-return section needs cited plainly.

- **✓ Blocquiaux et al. (2020)** (Topic 3, reused): the same study supplies
  the best available quantitative anchor for "how far below prior capacity
  should we assume a returning masters athlete actually is" — strength loss
  of only -5% to -15% after a full 12 weeks of detraining in older men
  (i.e., strength itself degrades slowly), which argues *against* needing
  to restart at a drastically reduced fraction of prior strength purely on
  physiological grounds — the real risk in the first sessions back is not
  "the muscle forgot how to be strong," it's **unaccustomed loading/novel
  movement pattern + reduced connective-tissue/tendon conditioning**
  relative to the muscle's own retained contractile capacity (see the
  reconciliation in §3).

- **⚠ Not independently verified this pass, not carried as a citation:**
  a widely repeated figure ("~47% of rhabdomyolysis cases occur in people
  doing extreme exercise unfamiliar to them") appears in secondary/press
  coverage but its primary source could not be confirmed this session.
  **Do not cite this specific figure** — the qualitative pattern it
  describes is independently supported by the two verified clinical sources
  above, so the number is not needed to make the point.
  **Generic strength-return starting-load percentages** (e.g. "restart at
  50-70% of prior working weight after a month-plus off") found via general
  web search are **fitness-blog/coaching-commentary tier, not a verified
  primary source** (unlike the running-return blogs in Topic 5, these
  weren't even internally consistent with each other across sources) — **not
  cited as evidence** in this dossier, consistent with
  `research-dossiers/2026-07-28-strength-programming.md`'s finding that no
  citable return-from-layoff strength protocol exists. See §4.

### Topic 7 — Reconciling with this engine's existing safety rails

Not new sources — cross-referencing this codebase's own existing,
already-cited machinery, to show how a return-from-layoff phase should
interact with it rather than propose silently changing it:

- **`WEEKLY_VOLUME_RAMP_CAP = 0.08`** (`03-periodization.md`) — the
  project's own standing +8%/week ceiling on weekly volume increases,
  itself `Coach judgment`/project safety rail, deliberately more
  conservative than the debunked "10% rule" (Buist et al. 2008, already in
  `reference_list.md`).
- **`SINGLE_SESSION_STEP_CAP = 0.15`** and the **30-day-longest-swim
  lookback** (`06-long-swim-progression.md`), `[ADAPTED: running]` from the
  Garmin-RunSafe cohort (already in `reference_list.md`) — governs how fast
  any *single* long swim can grow relative to the athlete's own recent
  longest effort.
- **The CTL-substitution precedent** (`22-injury-adapted-taper.md`) —
  `taper_search.py`'s existing solution to a structurally similar problem
  (an athlete's recent training history is artificially depressed after a
  restriction/layoff): use the decay-aware CTL series itself as the ramp
  floor/ceiling rather than a flat trailing average, and explicitly
  **reject** a literal ACWR ratio/threshold for this purpose (the existing
  low-confidence Feijen et al. 2021 caveat, already in `reference_list.md`,
  plus the Garmin-RunSafe finding that ACWR is a weak predictor generally).

---

## 3. What this supports: a proposed concrete return template

**All of this section is `Coach judgment`** unless a specific claim is
re-tagged inline — this dossier did not find a citable quantitative
return-ramp protocol (swim or strength) to lift a template from directly
(§4). This is a synthesis built on the detraining/retraining evidence above
plus this engine's own existing rails, offered as a starting point for
`/adapt`'s or a future engine feature's judgment review, explicitly **not**
a settled prescription.

### The core reconciliation question: does a layoff-return phase break the +8%/week rail?

**No — the rail should not be raised or bypassed. What needs to change is
the *starting point* the rail ramps from, not the rail itself.** This
mirrors the lesson `22-injury-adapted-taper.md` already learned and
documents for the injury-restriction case: the danger isn't the 8%/week
*rate*, it's silently assuming the athlete's **pre-layoff peak volume** (or
a stale, artificially-high recent-baseline reading) as the starting point
for that rate. `Coach judgment`, `Test:` if a future return-from-layoff
feature is ever built, its acceptance test should be: does the *rate* of
week-over-week increase ever exceed 8%? If yes, that's a bug regardless of
how conservative the starting point was — the same non-negotiable ceiling
this project already applies everywhere else.

**Proposed starting point, `Coach judgment`:** for a 5-6 month layoff
specifically, start the return week at roughly **25-35% of the athlete's
own last-known peak weekly swim volume** — a range chosen to sit
comfortably under Tsalis & Mougios (2022)'s real observed pattern (return
training resumed at *higher* aerobic volume than the tail of the layoff,
but explicitly without intensity) while still respecting that this is a
masters, non-race-runway-driven return, not an elite competitive squad's
managed transition period. **Confidence: low** — no source pins this exact
fraction for this exact population; it is this dossier's own synthesis, not
a lifted number. **Test:** if an athlete returning at this starting fraction
reports minimal soreness/fatigue relative to session RPE in week 1-2, that
would support the fraction as appropriately conservative (room to move it
up for a future case); persistent excessive soreness/fatigue at this
starting point would argue for starting lower next time.

**Arithmetic consequence, stated honestly:** climbing from ~30% back to
100% of prior peak volume purely via 8%/week compounding takes roughly
15-17 weeks (`ln(1/0.30) / ln(1.08) ≈ 15.6`). **This is a feature, not a
problem to engineer around** — it's directionally consistent with Tsalis &
Mougios (2022)'s own finding that a return took roughly as long as the
layoff itself, and with this project's already-stated preference (per
`03-periodization.md`) for conservatism over precision given this project's
own athlete history of training interruptions. A "6-8 week return template"
should therefore be read as **the initial, most-conservative ramp phase**
(getting safely off a near-zero base and re-establishing tolerance and
technique), not as a claim that full prior volume is restored by week 8 —
after that initial phase, the athlete re-enters the normal macro
periodization (base→build→peak→taper) from wherever the ramp has landed,
governed by the same rail as everyone else.

### Intensity reintroduction

**`Coach judgment`, informed by `[EVIDENCE: swim] Confidence: medium-high`**
(Tsalis & Mougios 2022's directly observed real-world return pattern):
hold intensity at low/moderate (easy aerobic + technique) for the first
3-4 weeks of the return regardless of how the athlete's cardiovascular
system feels — the Głyk et al. (2022) and general detraining literature
above both note that a returning athlete's subjective effort tolerance can
outrun their actual connective-tissue/technical readiness, particularly
for a masters athlete whose recovery from a hard session is itself slower
than a younger athlete's. **Test:** don't reintroduce CSS-anchored
threshold/race-pace work before week 4 of a return-from-months-off phase
even if the athlete self-reports feeling ready sooner.

### Long-swim / distance-specific reintroduction

**No new rule needed — the existing mechanism already generalizes
correctly, `Coach judgment` to confirm this rather than build something
new.** `SINGLE_SESSION_STEP_CAP` and the 30-day-longest-swim lookback
(`06-long-swim-progression.md`) naturally handle "returning from nothing":
if the athlete's actual logged swims in the trailing 30 days are small
(because they just restarted), the ladder's own step cap anchors off that
real, small number rather than any assumption about pre-layoff distance —
structurally the same insight already documented in
`22-injury-adapted-taper.md`'s CTL-substitution fix (use what's actually
been happening, not a stale pre-layoff number, and let the existing
mechanism's own decay/lookback do the discounting). **Test:** if a
returning athlete's early long swim ladder ever proposes a jump that isn't
bounded by the actual prior-30-day-longest reading, that's a bug in
applying the existing mechanism, not a reason to invent a parallel
layoff-specific rule.

### Strength return

**`Coach judgment`, informed by Blocquiaux et al. (2020) `[ADAPTED:
general-endurance] Confidence: medium-high`:** because strength itself
degrades slowly (that study's older-men cohort lost only -5% to -15% after
a full 12 weeks off), **the primary first-session risk is not "the muscle
forgot how to be strong" — it's unaccustomed loading and reduced
connective-tissue conditioning relative to retained contractile capacity**,
exactly the mechanism O'Connor et al. (2008) and Tietze & Borchers (2014)
name for exertional rhabdomyolysis risk. Practical consequence: **do not
size the first strength session(s) back by "how strong the athlete
remembers being"** — cap the first 1-2 sessions' volume and load
conservatively regardless of remembered capacity (a specific number is
`Coach judgment`, no citable figure exists per §4), avoid maximal-effort
eccentric or high-volume novel movements in session 1 specifically, and
progress based on next-day soreness/recovery response rather than a
pre-set schedule. **Test:** if this athlete resumes strength work after the
5-6 month layoff and reports soreness disproportionate to the (modest)
load used, that's consistent with the connective-tissue-lag mechanism
above and argues for holding the current load an extra session rather than
progressing on schedule — don't let a fixed weekly progression override an
adverse soreness signal.

### ACWR / load-monitoring caveat specific to a layoff return

**`Coach judgment`, directly generalizing `22-injury-adapted-taper.md`'s
already-documented lesson:** any load-ratio-based red-flag rule
(`adapt.py`'s `LOAD_RATIO_RED_THRESHOLD`) computed against a 28-day chronic
baseline will be structurally unreliable for a just-returned athlete,
because that chronic baseline is itself near-zero right after months off —
even a small, appropriately conservative return week will register as a
large ratio spike, generating noise rather than signal, for the same
reason this project already rejected a literal ACWR ratio for the
injury-restriction ramp case. **Test:** if a general (non-injury)
layoff-return feature is ever automated, don't gate it on the raw
load-ratio threshold in the first several weeks post-return; prefer the
CTL-series-based framing this project already built for the injury case.

---

## 4. Rejected / unverifiable / honest no-source outcomes

- **A swim-specific quantitative return-to-volume protocol — NO citable
  source.** US Masters Swimming's own coach-authored guidance (Topic 5)
  deliberately gives no percentage/yardage numbers. The Santa Barbara
  Channel Swimming Association guidance already cited in
  `06-long-swim-progression.md` addresses *building toward* an ultra swim
  from a normal training base, not *restarting* after months of complete
  cessation — it does not transfer to this question. No peer-reviewed
  swim-specific return-ramp study was found. This confirms, for the swim
  side, the same honest gap `research-dossiers/2026-07-28-strength-programming.md`
  already documented for strength.
- **A strength-specific quantitative starting-load percentage after a
  multi-month layoff — NO citable source**, extending that same prior
  dossier's finding. Generic web/blog percentages (50-70% of prior working
  weight, etc.) are internally inconsistent across sources and are not
  peer-reviewed — **not cited as evidence** anywhere in this dossier or its
  proposed template.
- **The "~47% of rhabdomyolysis cases from unfamiliar extreme exercise"
  statistic — NOT independently verified this session.** The qualitative
  pattern it describes is independently supported by two verified clinical
  sources (O'Connor et al. 2008; Tietze & Borchers 2014), so this figure is
  not needed and should not be quoted.
- **The myonuclear-domain "muscle memory" mechanism as settled human
  physiology — NOT established, and partly contradicted.** The largest
  human meta-analysis found (Rahmati et al. 2022) found myonuclei are
  **not** permanent in humans with atrophy (unlike in rodents), and the
  most relevant human RCT-quality data (Psilander et al. 2019) found no
  faster retraining response in previously-trained vs. naive muscle. Do not
  let a future build present "muscle memory via myonuclei" as an
  established mechanism in athlete-facing coaching language — the
  *practical* claim ("regaining tends to be faster than the original gain,
  especially for strength") has real support; the *mechanistic* claim does
  not, cleanly, in humans.
- **A single, agreed-upon detraining-rate number for VO2max — NOT a single
  number, a range.** Sources in Topic 1 report VO2max declines ranging from
  roughly -5% (2 weeks) to -20% (12 weeks), varying by population, training
  status, and study design. Report this as a directional timeline with a
  range, never collapse it into one figure presented as precise.

---

## 5. Verification method note

Every source above was checked for existence and identity via publisher,
PubMed, or PMC listings (title + full author list where available + journal
+ year + volume/pages/article number), per `00-conventions.md`'s "cite by
title+author, never by ID" rule. No PMC/PubMed/DOI identifier is carried
into this dossier as a citation — identifiers were used only as a
verification lookup and are deliberately omitted here, matching this
project's existing practice. Two sources (Cumming et al. 2024's full
author list beyond the first five names) were not confirmed down to every
co-author; this is flagged inline rather than either silently completing
the list from a secondary source or omitting the citation. Where a
practitioner/blog-tier claim was found but could not be verified as a
primary, checkable source (running-return percentage figures; strength
starting-load percentage figures; the rhabdomyolysis prevalence statistic),
it is explicitly excluded from the citable content and flagged in §4 rather
than laundered into an `[EVIDENCE]`/`[ADAPTED]` tag it doesn't earn.
