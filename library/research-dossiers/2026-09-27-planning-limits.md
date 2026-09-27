# Deterministic "Red Team" Planning-Limits Research Dossier — feeds a new engine check that validates coach-authored plans against research-based limits (masters training-load ramp tolerance, realistic progression rates, age-related decline, swim taper length, hours/time feasibility)

> **Provenance note:** raw research input for the engine's planned "red team" /
> plan-validation feature — checking coach-authored training plans against
> research-based limits and reality checks for masters endurance athletes
> (cyclists/CX, open-water swimmers, ages ~45-60). **Not itself a citable
> library file** — for grounding claims, cite `library/reference_list.md`
> and the target library file(s) directly, never this dossier. Matches the
> provenance convention used by `dossier-season-taper-2026-09-26.md` and
> other dated dossiers in this directory.

Compiled for: swim-coach research library, plan-validation "red team" build.
Already-cited and NOT re-researched (per brief, confirmed via
`library/reference_list.md` grep): Bosquet L. et al. 2007 (2-wk exponential
taper, ~41-60% volume cut meta-analysis), Mujika I., Padilla S. 2003 (4-28
day taper range, ~3% typical performance gain), Wang Z. et al. 2023
(≤21-day tapers 41-60% cut effective; ≤7-day tapers still positive),
Thomas L., Mujika I., Busso T. 2008 (elite-swimmer taper model — the
commonly-quoted "~33±16 day optimal taper" figure remains **unconfirmed
citation debt**, per `03-periodization.md` line 143-146; not re-verified
this pass, still flagged ⚠), and Formosa D.P. et al.'s 78-km solo
open-water swim case study (already corrected in `reference_list.md` to
~3-week/~43% taper, ~15-70 km/week buildup — re-confirmed, see Q4 below).

**Source count this pass:** 13 ✓ verified · 3 ~ partial/practitioner-only ·
0 ⚠ rejected.

---

## Q1 — Masters training-load ramp tolerance & recovery-week cadence

- **✓ Hottenrott L., Möhle M., Feichtinger S., Ketelhut S., Stoll O.,
  Hottenrott K. (2022)** — "Performance and Recovery of Well-Trained
  Younger and Older Athletes during Different HIIT Protocols" — *Sports*,
  10(1):9. Verified via MDPI + PMC (PMC8822894). 12 younger (24.5±3.7y) vs
  12 older (47.3±8.6y) **well-trained** cyclists/triathletes: recovery
  kinetics (lactate, performance) after HIIT did **not** differ between
  age groups.
  **[EVIDENCE: cycling/general-endurance]** Confidence: medium. Important
  **counter-evidence** to the popular "masters always need much more
  recovery" claim — in *well-trained* masters specifically, recovery from
  a single HIIT session was not measurably slower. **Test:** don't apply a
  blanket recovery-time penalty to a well-conditioned masters athlete on
  the strength of age alone; if this athlete's own HRV/RHR or session RPE
  shows a real lag, treat it as an individual finding, not a population
  default.

- **~ Reaburn P.R.J., Doering T.M., Borges N.R. (2019)** — "Masters
  athletes take longer to recover from high intensity exercise than
  training-matched younger athletes. Does increased protein intake enhance
  recovery?" — *Journal of Science and Medicine in Sport*, 22(Suppl
  2):S32-S33. Verified via JSAMS + Bond University research portal.
  Conference-abstract tier (not a full peer-reviewed paper) — marked **~**
  for that reason. Found masters athletes recover more slowly than
  training-matched younger athletes after exercise-induced muscle damage.
  **[EVIDENCE: general-endurance]** Confidence: low-medium (abstract only,
  full methods/effect size not accessible). Sits in tension with
  Hottenrott 2022 above — **honest read: recovery-speed evidence for
  masters is mixed**, likely depends on damage type (eccentric/muscle-
  damage protocols show a masters deficit; steady HIIT-recovery protocols
  don't).

- **✓ Burtscher J., Strasser B., Burtscher M., Millet G.P. (2022)** — "The
  Impact of Training on the Loss of Cardiorespiratory Fitness in Aging
  Masters Endurance Athletes" — *International Journal of Environmental
  Research and Public Health*, 19(17):11050. Verified via MDPI + PMC
  (PMC9517884). Review: VO2max decline in masters ranges from -5% to -46%
  per decade depending almost entirely on **training-volume changes** (54%
  and 39% of variance in men/women respectively explained by volume
  change, not age per se); athletes maintaining volume decline at the low
  end of that range.
  **[EVIDENCE: general-endurance]** Confidence: medium-high. Grounds a
  "don't cut volume just because the athlete is aging" principle, but does
  **not** itself test ramp-RATE tolerance (how fast load can safely
  increase) — that's the actual gap below.

- **Convention only, no peer-reviewed evidence found for ramp-rate or
  recovery-week cadence specifically in masters athletes.** Searched
  directly this pass (coaching-blog/practitioner sources: thecyclingweek.com,
  TrainingPeaks' "Training for Masters Runners" series, paincave.io).
  Multiple practitioner sources converge on **2:1 (two build weeks, one
  recovery)** replacing the standard 3:1 cadence for masters athletes,
  with some suggesting 1:1 past ~55, and recovery-week volume cuts of
  40-60%. This mirrors — and is likely descended from — the same
  practitioner literature the prior dossier found ungrounded for the
  general-population 3:1 cadence (Q4 of `dossier-season-taper-2026-09-26.md`:
  "5-8 CTL-points/week... Confirmed: convention only"). **No study was
  found that directly tests 3:1 vs 2:1 cadence, or a lower %-ramp cap, in
  a masters cohort.** **Label honestly:** `Coach judgment:` if written into
  a library file — do not tag `[EVIDENCE]`.

**Recommended number for this athlete:** no evidence-backed masters-specific
ramp-rate number exists. Given Burtscher 2022's volume-decline-matters
finding plus the (mixed, abstract-tier) masters-slower-recovery signal, a
defensible **Coach judgment** position is: keep the general
`WEEKLY_VOLUME_RAMP_CAP = 0.08` but shift recovery-week cadence from 3:1
toward **2:1** for a mid-50s athlete, and treat any single week's ramp cap
as a ceiling, not a target. Confidence: low (convention, corroborated only
indirectly by real physiology, not a ramp-rate trial).

---

## Q2 — Realistic performance progression rates & W/kg ceilings

- **✓ Bacon A.P., Carter R.E., Ogle E.A., Joyner M.J. (2013)** — "VO2max
  Trainability and High Intensity Interval Training in Humans: A
  Meta-Analysis" — *PLoS ONE*, 8(9):e73182. Verified via PLOS + PMC
  (PMC3774727). Untrained/sedentary subjects show large VO2max gains
  (~10-20% over 8-12 weeks common); ~10-20% of individuals show negligible
  measurable VO2max response even under fully supervised standardized
  training (heritability ~47% of response variance, HERITAGE Family
  Study). Gains shrink sharply as baseline fitness/training age rises.
  **[EVIDENCE: general-endurance]** Confidence: high for the qualitative
  "diminishing returns with training age" pattern; the specific %
  quoted is untrained-population, not directly transferable to an
  already-trained masters athlete.

- **✓ Cove B. et al. (2024/2025)** — "The effect of training distribution,
  duration, and volume on VO2max and performance in trained cyclists: A
  systematic review, multilevel meta-analysis, and multivariate
  meta-regression" — *Journal of Science and Medicine in Sport*,
  28:423-434. Verified via ScienceDirect + JSAMS (published online 2024,
  print 2025). 41 studies, 81 training groups, 797 **trained** cyclists:
  significant but modest effect on VO2max (Hedges' g=0.42) and TT
  performance (g=0.39); training **duration** (in weeks) predicted
  improvement, but weekly/total training **volume** did not — i.e. past a
  threshold, more volume doesn't buy more adaptation in already-trained
  athletes.
  **[EVIDENCE: cycling]** Confidence: high — large, recent, directly
  on-population (trained cyclists, adult). **Concrete recommendation:**
  a trained masters cyclist should expect **modest (roughly small-to-
  medium effect size, single-digit-to-low-teens %) FTP/VO2max gains per
  structured training block**, not large jumps, and extending training
  block DURATION is a better lever than simply adding more weekly hours.
  **Test:** if a coach's plan projects a large FTP jump (e.g. >15-20%) in
  one season for an already-trained masters athlete, that's out of line
  with this evidence and should be flagged.

- **✓ Valenzuela P.L., Muriel X., van Erp T., et al. (2022)** — "The
  Record Power Profile of Male Professional Cyclists: Normative Values
  Obtained From a Large Database" — *International Journal of Sports
  Physiology and Performance*, 17(5):701-710. Verified via Human Kinetics
  journal + ResearchGate. 144 professional cyclists, 129,262 files, 1,062
  seasons across 8 years and 4 WorldTour/ProTeam squads: normative
  record-power-profile (max mean power at 1s-240min) values in both W and
  W/kg, by competitive tier.
  **[ADAPTED: cycling]** Confidence: high for the data itself, but it is
  an **elite/professional population, not masters** — using it as a
  ceiling for a masters recreational/competitive athlete requires an
  age-grading adjustment factor that this paper does not itself supply
  (see Q3's age-decline %/decade figures for that adjustment). **Test:**
  never compare this athlete's raw W/kg directly to the Valenzuela table
  without first applying an age-decline discount — otherwise the "ceiling"
  is nonsensically strict.

- **Convention only, no peer-reviewed source found for age-graded W/kg
  category tables specifically.** Searched directly this pass — the
  widely-used "Coggan power profile" (from Allen H. & Coggan A., *Training
  and Racing with a Power Meter*) is a coaching-book compilation, not a
  peer-reviewed study, and its age-grading crosswalks (e.g. "3.0 W/kg is
  competitive for a 55-year-old") are practitioner-blog extensions
  (roadmancycling.com, sportcoaching.com.au) with no cited primary data.
  **Label honestly:** `Coach judgment:` for any age-graded W/kg category
  cutoff — ground the actual decline-rate discount in Q3's peer-reviewed
  %/decade figures instead, and treat the Coggan/blog category bands only
  as informal color, not a hard ceiling.

**Recommended number for this athlete:** no single "ceiling" number is
evidence-backed, but the shape is: (a) modest per-block gains for an
already-trained masters athlete (single-digit-to-low-teens %, Cove 2024),
(b) diminishing returns compound with training age (Bacon 2013), and (c)
any "ceiling" check should apply Q3's age-decline discount to an elite
open dataset (Valenzuela 2022) rather than use an unvalidated age-graded
blog table. Confidence: medium for the qualitative shape; no numeric
ceiling meets `[EVIDENCE]` bar.

---

## Q3 — Age-related decline in endurance performance/VO2max/threshold for trained masters

- **✓ Tanaka H., Seals D.R. (2008)** — "Endurance exercise performance in
  Masters athletes: age-associated changes and underlying physiological
  mechanisms" — *The Journal of Physiology*, 586(1):55-63. Verified via
  Wiley + PubMed (PMID 17717011). Foundational review: peak endurance
  performance is maintained to ~age 35, followed by a **modest decline to
  ~50-60**, then **progressively steeper decline** thereafter; primarily
  driven by declining maximal cardiac output/VO2max and, at older ages,
  reduced muscle mass/neuromuscular drive.
  **[EVIDENCE: general-endurance]** Confidence: high — this is the
  standard reference review for the shape of the masters age-performance
  curve (companion piece: Tanaka H., Seals D.R. (2003), "Dynamic exercise
  performance in Masters athletes," *Journal of Applied Physiology*,
  95:2152-2162, verified same session, earlier/narrower version of the
  same argument). **Directly grounds** a "goal requires progression faster
  than plausible before the athlete ages out" check: for a mid-50s
  athlete, model performance ceiling as flat-to-mildly-declining over a
  multi-year goal horizon, not flat indefinitely.

- **✓ Rogers M.A., Hagberg J.M., Martin W.H., Ehsani A.A., Holloszy J.O.
  (1990)** — "Decline in VO2max with aging in master athletes and
  sedentary men" — *Journal of Applied Physiology*, 68(5):2195-2199.
  Verified via APS journal + PubMed (PMID 2361923) + Semantic Scholar
  (full author list cross-checked). 8-year longitudinal follow-up, 15
  well-trained masters athletes (mean age 62) vs 14 sedentary controls
  (mean age 61.4): masters athletes' VO2max declined **~5.5%/decade**,
  roughly **half** the sedentary controls' **~12%/decade**.
  **[EVIDENCE: general-endurance]** Confidence: high — classic, direct,
  longitudinal (not cross-sectional) comparison. **Concrete recommendation:**
  a **~5-6%/decade** (≈0.5-0.6%/year) VO2max decline figure for a
  training-maintaining masters athlete is a defensible, citable anchor.

- **✓ Pimentel A.E., Gentile C.L., Tanaka H., Seals D.R., Gates P.E.
  (2003)** — "Greater rate of decline in maximal aerobic capacity with age
  in endurance-trained than in sedentary men" — *Journal of Applied
  Physiology*, 94(6):2406-2413. Verified via APS journal + ResearchGate.
  Cross-sectional, 153 healthy men aged 20-75 (64 sedentary, 89 endurance-
  trained): found endurance-**trained** men's VO2max declined at a
  **greater** rate with age than sedentary men's, in absolute terms.
  **[EVIDENCE: general-endurance]** Confidence: medium — **directly
  contradicts** the Rogers 1990 "trained decline slower" framing on its
  face. Honest reconciliation: this is a known, unresolved tension in the
  masters-athletics literature — cross-sectional designs (Pimentel) can be
  confounded by different cohorts' peak historical training volumes,
  while longitudinal designs tracking the *same* individuals as they age
  (Rogers) more directly isolate the training-maintenance effect. **Do not
  present either number as settled** — flag this exact tension if either
  figure is written into a library file. **Test:** trust the athlete's own
  longitudinal trend (her own CTL/zone data over years) over either
  population figure.

**Recommended number for this athlete:** use **~5-8%/decade** VO2max/
threshold decline as the working range for a training-maintaining masters
athlete (Rogers 1990 anchor at the low end; general masters-population
figures commonly cited up to ~10%/decade at the high end, per Burtscher
2022's review above), explicitly flagging the Pimentel 2003 contradiction
as an open question rather than picking a false-precision single number.
Confidence: medium.

---

## Q4 — Swim taper length for distance/ultra open-water swimming

- **✓ Hellard P., Avalos M., Hausswirth C., Pyne D., Toussaint J.F., Mujika
  I. (2013)** — "Identifying Optimal Overload and Taper in Elite Swimmers
  over Time" — *Journal of Sports Science & Medicine*, 12(4):668-678.
  Verified via JSSM + PMC (PMC3873657) direct fetch. Studied a **6-week
  final training period (3-week overload + 3-week taper)** before national
  championships; optimal taper pattern showed mean total training load at
  57±26%, 45±24%, 38±14% (of overload peak) across taper weeks 3, 2, 1
  respectively — an overall ~55% total-load reduction (37% cut to
  low-intensity work, 49% to high-intensity, 95% to strength); mean
  performance gain 1.7±1.7% (76/85 observations improved).
  **[EVIDENCE: swim]** Confidence: high — real, quantified, **directly
  supports a genuine 3-week taper window** in competitive swimmers (elite
  pool swimmers preparing for national championships, not ultra/open-water
  specifically, and not a step-function cut — it's a progressive weekly
  decay). **Important for the athlete's complaint:** a 3-week taper *is*
  evidence-backed for swimming generally — the un-grounded part was never
  "3 weeks," it's specifically a **4-week** taper for **ultra-distance
  open-water** swimming (see below).

- **✓⚠ Formosa D.P. et al.** — "Training for a 78-km Solo Open Water Swim"
  (already in `library/reference_list.md`, re-confirmed this pass via
  independent web search, not re-derived from primary text). 48-year-old
  **masters-aged** male long-distance swimmer, 32-week build, weekly
  volume 15-70 km/week, **~3-week taper with ~43% total volume
  reduction** before the swim. Single case, but **directly on-population**
  (masters-aged, ultra open-water) — the single strongest real-world data
  point for this exact athlete profile. Confirms the library's prior
  correction stands: the case supports **~3 weeks**, not 4, and there is
  still **no primary-source support for a 4-week ultra-swim taper**.
  **[EVIDENCE: swim]** Confidence: low-medium (n=1 case study) but
  directly population-matched.

- **~ Marathon Swimmers Forum (ultraswimming.org)** — community discussion
  thread, "how to taper well before a race." Practitioner/community-tier,
  not peer-reviewed, but the relevant population (experienced marathon/
  open-water swimmers themselves). Consensus: **2 weeks minimum**, halving
  volume week-over-week (one proposed pattern: full volume → 50% → 25%),
  explicit disagreement on whether to cut volume-first vs intensity-first,
  but **no one in that community argued for a 3-4 week taper** — several
  explicitly argued shorter (down to 1-2 days of near-rest) works fine if
  base fitness is solid.
  **Label honestly:** community/practitioner convention, not `[EVIDENCE]`
  — but worth citing as **corroborating, not contradicting**, the
  "4 weeks is too long" conclusion.

**Recommended number for this athlete:** the evidence (Hellard 2013 for
competitive swimming generally, Formosa for the exact ultra/open-water/
masters population, Mujika & Padilla 2003's 4-28-day studied range, Bosquet
2007's ~2-week optimum, and the marathon-swimming community consensus) all
converge on **2-3 weeks** as the defensible taper window for this
athlete's ultra open-water goal — **not 4 weeks**. A 4-week taper sits at
the very outer edge of Mujika & Padilla's studied range (28 days) but has
**no direct supporting citation** for ultra-distance open water
specifically; the one number that would justify 4 weeks (Thomas/Mujika/
Busso 2008's "~33±16 day" figure) remains **unconfirmed citation debt**
per `03-periodization.md`, not a number to build on. **Recommendation:**
change `TAPER_WEEKS_LONG` from 4 to **3**, with ~40-45% total volume
reduction (Formosa/Hellard both cluster near this), re-deriving from
Formosa + Hellard rather than the still-unconfirmed Thomas 2008 figure.
Confidence: medium-high — this is a defensible, citable correction, not
just "the athlete complained so we should change it."

---

## Q5 — Hours/time feasibility: planned vs. completed training time

- **✓ Inoue A., Bunn P.d.S., do Carmo E.C., Lattari E., da Silva E.B.
  (2022)** — "Internal Training Load Perceived by Athletes and Planned by
  Coaches: A Systematic Review and Meta-Analysis" — *Sports Medicine -
  Open*, 8:35. Verified via SpringerOpen + PMC (PMC8897524) direct fetch.
  27 studies, 725 participants, multiple sports, 1997-2021: overall
  RPE/session-RPE agreement between coach-planned and athlete-perceived
  load was **not significantly different** (SMD 0.05-0.19), **except**
  on **easy days**, where athletes perceived meaningfully **higher**
  intensity/load than coaches planned (SMD -0.44 to -0.54, small-moderate
  effect, p=0.04).
  **[EVIDENCE: general/multi-sport]** Confidence: medium — this is
  **adjacent, not direct**, evidence: it measures perceived *intensity*
  agreement, not planned-vs-completed *duration/hours*. Its practical
  relevance: a coach-planned "easy" day is the specific spot most likely
  to run hotter than intended — worth a targeted reality-check, distinct
  from a blanket time-margin.

- **Confirmed: no peer-reviewed source found for a specific planned-vs-
  completed training-TIME (hours) adherence percentage in adult endurance
  athletes.** Searched directly this pass. The one quantified adherence
  figure found (mean 66.05%, SD 25.75%, completed-vs-planned *sessions*)
  is from junior netball athletes — a poor population match (team-sport
  youth, not masters endurance) and measures session-count adherence, not
  hours. TrainingPeaks' own help documentation confirms it tracks
  planned-vs-actual duration/TSS/distance for "compliance" but does not
  publish a general reality-check margin.
  **Label honestly:** the "+~10% time reality" margin the app might want
  to apply is **`Coach judgment:` / convention only** — there is no
  evidence base to cite for a specific percentage. If adopted, frame it
  explicitly as a coaching heuristic (real life runs long — travel to
  pool/start, warmup/cooldown not always logged, weather/mechanicals) and
  give it a `Test:` (does this athlete's own logged-vs-planned duration
  gap over a rolling window match or exceed 10%?) rather than a citation.

**Recommended number for this athlete:** no evidence-backed number exists
for a planned-vs-actual time margin. Recommend **`Coach judgment: +10%`**
labeled explicitly as convention (matching the honest-labeling precedent
set by the prior dossier's CTL-ramp-rate finding), with the Inoue 2022
easy-day-intensity finding cited separately as a related but distinct
caution about easy-day RPE drift, not folded into the same number.

---

## Summary table (recommended constants, if adopted)

| Question | Concrete number | Confidence | Grounding |
|---|---|---|---|
| Q1 masters ramp/recovery | No evidence-backed ramp-rate number; recovery-week cadence 2:1 (not 3:1) is `Coach judgment:` only | low (convention) / medium-high (volume-matters principle) | Hottenrott 2022, Reaburn 2019 (~), Burtscher 2022 (all ✓); cadence itself uncited |
| Q2 progression/ceiling | Modest per-block gains (single-digit-to-low-teens %) for trained masters; no evidence-backed W/kg ceiling | high (qualitative shape) / N/A (no numeric ceiling) | Bacon 2013, Cove 2024, Valenzuela 2022 (all ✓); age-graded W/kg tables are `Coach judgment:` |
| Q3 age decline | ~5-8%/decade VO2max/threshold decline for a training-maintaining masters athlete (flag Pimentel 2003 contradiction) | medium | Tanaka & Seals 2008, Rogers 1990 (✓); Pimentel 2003 (✓, contradicts) |
| Q4 swim taper | 3 weeks (not 4), ~40-45% volume cut — change `TAPER_WEEKS_LONG` from 4 to 3 | medium-high | Hellard 2013 (✓), Formosa (✓⚠, re-confirmed), Marathon Swimmers Forum (~) |
| Q5 time feasibility | +~10% time margin is `Coach judgment:`, not evidence; separately flag easy-day RPE drift | N/A (convention) / medium (adjacent finding) | Inoue 2022 (✓, adjacent); no direct source found |

---

## Most load-bearing sources for spot-verification (recommended priority order)

1. **Hellard P. et al. (2013)**, "Identifying Optimal Overload and Taper
   in Elite Swimmers over Time," *J Sports Sci Med* 12(4):668-678 — the
   strongest single new finding (real 3-week taper, quantified weekly
   decay %, real performance-gain data); directly reframes the athlete's
   complaint from "3 weeks is unsupported" to "4 weeks is unsupported."
2. **Rogers M.A. et al. (1990)**, "Decline in VO2max with aging in master
   athletes and sedentary men," *J Appl Physiol* 68(5):2195-2199 — the
   core %/decade anchor for the age-decline check, longitudinal (not
   cross-sectional) design.
3. **Tanaka H., Seals D.R. (2008)**, "Endurance exercise performance in
   Masters athletes: age-associated changes and underlying physiological
   mechanisms," *J Physiol* 586(1):55-63 — the standard review grounding
   the shape of the masters age-performance curve used by the "ages out
   before goal" check.

---
## ORCHESTRATOR CORRECTION (2026-09-27, spot-verification)
Q4 is OVERSTATED. Hellard et al. (2013) predefined the final 6 weeks as a 3-week overload + 3-week taper and compared load patterns WITHIN that fixed window. It did not compare taper lengths, so it cannot show that 3 weeks is optimal. Population: elite pool swimmers (100-400 m), not ultra/open-water. **Do NOT change TAPER_WEEKS_LONG to 3 on this basis, and do not tell the athlete a 3-week taper is evidence-backed.** Best-supported default: Bosquet 2007 (~2 weeks, 41-60% volume cut, intensity held), with length chosen per event by the coach (red-team check = advisory), per the approved coach-authors architecture.
Also verified: Rogers 1990 ✓ (trained masters decline ≈ half the sedentary rate of ~12%/decade, so ~5-6%/decade); Tanaka & Seals 2008 ✓ (J Physiol 586:55-63; peak to ~35, modest decline to 50-60, steeper after).
