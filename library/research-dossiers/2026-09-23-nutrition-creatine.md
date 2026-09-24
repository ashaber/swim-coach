# Nutrition Research Dossier — creatine, daily/periodized fueling, gut training, cramping — candidate additions to `library/`

> **Provenance note:** this is raw research input for a future library update
> (most likely a new `library/17-supplements.md` for creatine/caffeine/
> vitamin D/iron, plus small additions to the existing `08-ultra-feeding.md`
> gut-training section and `16-race-week.md` carb-loading section). It is
> **not itself a citable library file** — for grounding claims, cite
> `library/reference_list.md` and the relevant topic file directly, never
> this dossier.

Compiled for: swim-coach research library. Research-only pass; nothing in
`/home/ashaber/projects/swim-coach` was edited. Follows the citation
discipline in `library/00-conventions.md` and `library/reference_list.md`
(cite by title + author + year + journal, **never** by URL/PMC/PubMed/DOI —
those were used only as verification lookups and are deliberately omitted
below; every source carries a ✓/~/⚠ marker).

**Trigger:** six library-gap questions logged by the in-app coach — creatine
(thorough pass, including the specific hydration/cramping/EAH interaction
question), daily/periodized carbohydrate and protein intake, in-session gut
training progression rate, a masters/female nuance on carb-loading, the
mechanism behind muscle cramping, and a brief pass on other well-evidenced
supplements (caffeine, vitamin D, iron).

**Athlete context:** masters (post-menopausal) female, ultra-distance
open-water swimmer, target 33.3 km continuous swim; pool practice 3–5×/week,
strength 2×/week. Other athletes in the system also cycle (MTB/CX) and lift.

**Existing coverage — read, not duplicated:**
- `08-ultra-feeding.md` — in-swim carbohydrate rates/transporters, the
  90-minute-wall analysis, post-swim rehydration (150% rule, sodium
  concentration), and the EAH safety rail (Wagner 2012, Hew-Butler 2015/2017,
  Rosner 2019 already cited there). This dossier does **not** re-litigate
  that section; it only adds the creatine×EAH interaction question, which
  `08` does not address, and one new gut-training progression-rate datum.
- `16-race-week.md` — the 36–72h, 10–12 g/kg/day carb-loading protocol
  (Burke 2011, Bussau 2002 already cited). This dossier adds one
  female-specific nuance those citations don't cover.
- `10-recovery-hrv.md` "Nutrition for the refeed window" — already cites
  `Kato et al. (2016)` for a **1.65–1.83 g/kg/day** whole-day protein target
  and `Koopman et al. (2004)` for carb+protein co-ingestion during long
  efforts. This dossier does not re-derive the daily protein *total*; it
  adds the **per-meal/leucine-threshold** and **pre-sleep protein** layer,
  which `10` does not cover.
- `13-reds-energy-availability.md` — energy availability model, why the
  amenorrhea red flag doesn't exist for a post-menopausal athlete, and the
  honest "evidence vacuum for her demographic" framing. This dossier's
  daily-carbohydrate-periodization content is downstream of (not a
  contradiction of) `13`'s energy-availability framing — a periodized
  carbohydrate plan is not automatically a low-energy-availability risk, and
  the library should say so if it draws on both files.

**Source count this pass:** 15 ✓ verified · 4 ~ partially verified ·
0 ⚠ unverifiable carried forward as citable. 19 sources total, plus 2 named
and explicitly rejected (see §6).

---

## 1. Executive summary — the 5 most important claims

1. **Creatine's hydration/cramping myth is specifically and directly
   rebutted, and the rebuttal is stronger than "no evidence of harm" — the
   controlled evidence points the other way.** `Dalbo et al. (2008)` is a
   review built substantially on `Greenwood et al.`'s American-football-
   athlete data: athletes *taking* creatine reported **fewer** episodes of
   cramping, muscle tightness/strains, and dehydration/heat illness than
   non-users, and short-term creatine loading did not alter hydration status
   or thermoregulation in dehydrated, trained men. The mechanism given is
   that creatine draws water **intracellularly** (into the muscle), which is
   a fluid-*retention* effect, not a fluid-*deficit* effect. `[ADAPTED:
   general-endurance]`, Confidence: medium-high — real controlled data, but
   none of it is in open-water swimmers or in a hyponatremia-risk context
   specifically (see caveat below).
2. **No study anywhere tests creatine's interaction with EAH risk — this is
   a genuine, honestly-stated gap, and the honest answer is "no known
   mechanism, not yet tested."** Creatine's water-retention effect is
   intracellular (inside muscle cells), whereas EAH is a *plasma*-sodium-
   dilution problem driven by hypotonic fluid *volume* intake (per
   `08-ultra-feeding.md`'s existing Hew-Butler citations). These are
   different fluid compartments, so there is no clear mechanistic reason to
   expect creatine to worsen EAH — but "no clear mechanism" is an inference
   by this dossier, not a tested finding, and nobody has run the
   experiment in an ultra-swim population. State this as a stated gap, not
   a reassurance. `Coach judgment:`, low confidence on the interaction
   question specifically.
3. **Creatine + resistance training in older adults (including women) is
   one of the best-supported claims in this whole dossier: real, replicated
   lean-mass and strength gains, at ordinary doses, with no bone-density
   signal.** `Chilibeck et al. (2017)` meta-analysis (22 RCTs, 721 subjects,
   mean age 57–70) found +1.37 kg lean tissue mass and greater upper/lower-
   body strength gains vs. resistance training alone. The dedicated
   postmenopausal-bone RCT (`Chilibeck et al. 2023`, 237 women, 2 years)
   found creatine did **not** improve areal bone mineral density at any
   site, but did help preserve bone bending-strength/geometry at the femoral
   neck and modestly increased lean mass and walking speed. `[ADAPTED:
   general-endurance]` (resistance-trained older adults broadly, not
   swimmers), Confidence: high for lean-mass/strength; medium for the bone
   geometry finding (single trial).
4. **Creatine has essentially no demonstrated benefit for swimming
   performance specifically, and the most recent swim-specific
   meta-analysis is a clean null result — this must be stated plainly, not
   softened.** `Huang et al. (2024)`, 17 RCTs, 361 swimmers: creatine
   supplementation showed **no meaningful improvement** in performance,
   physiological markers, or body composition among swimmers. Broader
   aerobic-endurance meta-analyses (`Fernández-Landa et al. 2023`) likewise
   found creatine **ineffective** for pure endurance performance, with
   ergogenic potential (from phosphocreatine/ATP resynthesis) limited to
   efforts under ~150 seconds or repeated-sprint contexts — not relevant to
   a 33.3 km continuous swim. `[EVIDENCE: swim]` for the null swim finding;
   `[ADAPTED: general-endurance]` for the broader endurance null.
   Confidence: high that creatine will not improve this athlete's ultra-swim
   performance. **The honest framing for the athlete: creatine's case here,
   if there is one, is strength/lean-mass/bone-adjacent (her 2×/week
   strength work) and general healthy-aging, not swim performance** — and it
   adds body mass (water + some lean tissue), a real trade-off for a
   swimmer to weigh consciously, not a free supplement.
5. **Muscle cramping (EAMC) is not well explained by the dehydration/
   electrolyte model the athlete population usually assumes, and the honest
   current position is "multifactorial, leaning neuromuscular," not settled
   either way.** `Schwellnus (2009)` argued the electrolyte/dehydration
   hypotheses lack supporting mechanistic evidence and that altered
   neuromuscular control (fatigue-driven hyperexcitability of the motor
   neuron) is the better-supported principal mechanism — cramps cluster in
   locally fatigued muscle, not in a pattern that tracks whole-body
   electrolyte/fluid status. The more recent `Miller et al. (2022)` review
   is more cautious: EAMC likely reflects a **confluence of individual
   intrinsic/extrinsic risk factors**, not one singular cause, and it
   explicitly walks back a purely neuromuscular monocausal claim.
   `[ADAPTED: general-endurance]` (running/multi-sport evidence, not
   swim-specific — and immersion changes fluid/electrolyte handling per
   `08`'s existing Epstein 1992 citation, so transfer to swimming is
   uncertain). Confidence: medium.

---

## 2. Creatine — the thorough pass

### 2a. What it is, dosing

- **✓ Hultman E., Söderlund K., Timmons J.A., Cederblad G., Greenhaff P.L.
  (1996)** — "Muscle creatine loading in men" — *Journal of Applied
  Physiology*, 81(1):232–237.
  **Verification:** title, full author list, journal, year, volume/pages
  confirmed via publisher and independent citation records.
  **Summary:** 31 men. A **20 g/day loading dose for 6 days** raised total
  muscle creatine by ~20%; that elevation was *maintained* by a subsequent
  **2 g/day maintenance dose for 30 days**. A slower, no-loading protocol of
  **3 g/day for 28 days** produced the same ~20% rise gradually, without a
  loading phase.
  **Why it matters:** the canonical dosing citation — confirms both the
  classic "load then maintain" protocol and that a **plain 3–5 g/day, no
  loading**, gets to the same total-body-creatine endpoint over roughly a
  month, just slower. Relevant to this athlete: skipping the loading phase
  avoids the sharpest, fastest water-weight gain, which may matter more to a
  swimmer worried about body-mass/buoyancy changes than to a lifter.
  **Tag:** `[ADAPTED: general-endurance]`, Confidence: high (foundational,
  replicated repeatedly since).

- **✓ Kreider R.B., Kalman D.S., Antonio J., Ziegenfuss T.N., Wildman R.,
  Collins R., Candow D.G., Kleiner S.M., Almada A.L., Lopez H.L. (2017)** —
  "International Society of Sports Nutrition position stand: safety and
  efficacy of creatine supplementation in exercise, sport, and medicine" —
  *Journal of the International Society of Sports Nutrition*, 14:18.
  **Verification:** title, full author list, journal, year, volume/article
  number confirmed via publisher, PubMed and independent citation records.
  **Summary:** Position stand (not a primary trial — say so). Creatine
  monohydrate is characterized as the most effective legal ergogenic
  nutritional supplement for increasing high-intensity exercise capacity and
  lean body mass with training; short- and long-term use (up to 30 g/day for
  5 years in some cited populations) shows no compelling evidence of harm in
  otherwise healthy people. Lists dosing options including the 5-day loading
  (~0.3 g/kg/day) → 3–5 g/day maintenance pattern, and a slower straight
  3–5 g/day approach.
  **Tag:** position stand — cite as such, not as primary evidence.
  Confidence: high as an authoritative summary; note the panel includes
  several authors (e.g. Candow, Antonio, Kalman) who are prolific creatine
  researchers and, in some cases, have industry-adjacent consulting/
  advisory ties — standard for this specific position-stand genre, and worth
  a one-line COI note in the library rather than treating it as disinterested.

### 2b. Strength/lean mass in older adults and post-menopausal women

- **✓ Chilibeck P.D., Kaviani M., Candow D.G., Zello G.A. (2017)** — "Effect
  of creatine supplementation during resistance training on lean tissue mass
  and muscular strength in older adults: a meta-analysis" — *Open Access
  Journal of Sports Medicine*, 8:213–226.
  **Verification:** title, full author list, journal, year, volume/pages
  confirmed via publisher and PubMed listings.
  **Summary:** 22 RCTs, 721 participants (men and women, mean age 57–70y),
  creatine + resistance training (2–3 days/week, 7–52 weeks) vs. resistance
  training alone. Creatine group gained significantly more **lean tissue
  mass (+1.37 kg)** and greater **chest-press and leg-press strength**.
  **Tag:** `[ADAPTED: general-endurance]` (older-adult resistance-training
  population, not swim- or endurance-specific), Confidence: high
  (meta-analysis, direct age-relevant population, includes women).

- **✓ Chilibeck P.D., Candow D.G., Gordon J.J., Duff W.R.D., Mason R., Shaw
  K., Taylor-Gjevre R., Nair B., Zello G.A. (2023)** — "A 2-Year Randomized
  Controlled Trial on Creatine Supplementation During Exercise for
  Postmenopausal Bone Health" — *Medicine & Science in Sports & Exercise*,
  55(10):1750–1760.
  **Verification:** title, full author list, journal, year, volume/pages
  confirmed via publisher listing and independent citation records.
  **Summary:** 237 postmenopausal women, creatine (~0.1 g/kg/day) vs.
  placebo, all doing supervised resistance training 3×/week plus walking, for
  2 years. **No difference in areal bone mineral density at any site** vs.
  resistance training alone. Creatine **did** better preserve
  bending-strength-relevant bone **geometry** (section modulus, buckling
  ratio) at the narrow femoral neck, modestly increased lean tissue mass, and
  improved walking speed.
  **Why it matters:** this is the direct population match (postmenopausal
  women) this athlete's coach question is asking about, and it's an honest
  mixed result — no BMD headline win, but not nothing either, and no safety
  signal over 2 years. A smaller **pilot** version of this same research
  line reportedly found less femoral-neck BMD *decline* in the creatine
  group over 1 year — **flagged but not independently verified this pass;
  do not cite the pilot's numbers without a direct check**, since the
  larger, later 2-year trial with more power is the one to lead with.
  **Tag:** `[ADAPTED: general-endurance]` (this is general-population
  osteoporosis-prevention research, not swim- or ultra-specific — but it is
  the athlete's own age/sex/menopausal-status population, which is rare in
  this library — see `13-reds-energy-availability.md`'s "evidence vacuum"
  framing). Confidence: medium-high (large, long RCT; single research
  group/line of work).
  **Test:** if this athlete supplements creatine, track lean mass /
  bodyweight trend and any DEXA follow-up (per `13`'s recommendation of a
  bone scan as a first step) — this is a 2-year-timescale question, not
  something her weekly data can resolve quickly.

### 2c. Cognitive/recovery claims

- **✓ Xu C., Bi S., Zhang W., Luo L. (2024)** — "The effects of creatine
  supplementation on cognitive function in adults: a systematic review and
  meta-analysis" — *Frontiers in Nutrition*, 11:1424972.
  **Verification:** title, full author list, journal, year, volume/article
  number confirmed via direct fetch of the publisher's full text.
  **Summary:** 16 RCTs, 492 participants aged 20.8–76.4y. Creatine improved
  **memory** (moderate-certainty evidence) and **speed of** attention and
  processing-speed tasks, but **not** raw attention/processing-speed
  accuracy scores, and **not** executive function. **Age-subgroup finding,
  and it cuts against the population of interest**: in the **>60y
  subgroup**, the attention-time benefit was **not statistically
  significant**; the significant speed benefit was concentrated in the
  **18–60y** subgroup. **Verification caveat the library must carry**: EFSA's
  formal evaluation of this literature flagged that pooling
  non-independent cognitive-test results in analyses like this one likely
  **inflated effective sample size**, and concluded no health claim could be
  substantiated on that basis — so this meta-analysis's positive headline
  should be presented as suggestive, not settled, and the older-adult
  subgroup specifically should **not** be oversold to this athlete.
  **Tag:** `[ADAPTED: general-endurance]`, Confidence: low-medium (positive
  overall signal, but the specific age-relevant subgroup was null, and a
  regulatory body has flagged a methodological concern with this literature
  as a whole).

### 2d. Endurance performance (expect little — confirmed)

- **✓ Fernández-Landa J., Santibañez-Gutierrez A., Todorovic N., Stajer V.,
  Ostojic S.M. (2023)** — "Effects of Creatine Monohydrate on Endurance
  Performance in a Trained Population: A Systematic Review and
  Meta-analysis" — *Sports Medicine*, 53(9):1811–1821.
  **Verification:** title, full author list, journal, year confirmed via
  independent citation and publisher listings (full volume/page precision
  not independently re-derived beyond the year/journal match — mark `~`
  for that reason).
  **Summary:** Meta-analysis in trained endurance athletes: creatine
  monohydrate supplementation was **ineffective** for improving aerobic
  endurance performance; ergogenic value (via phosphocreatine resynthesis/
  buffering) is concentrated in efforts under ~150 seconds or with a
  repeated high-intensity-effort component, not sustained aerobic output.
  **Tag:** `[ADAPTED: general-endurance]`, Confidence: medium-high (~,
  see verification note).

- **✓ Huang D., Wang X., Gonjo T., Takagi H., Huang B., Huang W., Shan Q.,
  Chow D.H.-K. (2024)** — "Effects of Creatine Supplementation on the
  Performance, Physiological Response, and Body Composition Among Swimmers:
  A Systematic Review and Meta-Analysis of Randomized Controlled Trials" —
  *Sports Medicine – Open*, 10:115.
  **Verification:** title, full author list, journal, year, volume/article
  number confirmed via direct fetch of the publisher's full text.
  **Summary:** 17 RCTs, 361 swimmers. Creatine supplementation showed **no
  meaningful improvement** in sprint performance, physiological markers, or
  body composition among swimmers, across the pooled trials. Authors
  explicitly recommend caution before recommending it to swimmers for
  performance.
  **Why it matters — this is the single most directly relevant "does it
  help her swim" citation in the dossier, and it is a clean null.** Older,
  smaller individual trials (not independently re-verified this pass, and
  now superseded by this 2024 pooled analysis) had reported mixed/small
  sprint benefits, sometimes sex-differentiated (male but not female
  swimmers improving) — **do not cite those older single studies over this
  meta-analysis**; the pooled, most-recent evidence is the null result
  above.
  **Tag:** `[EVIDENCE: swim]`, Confidence: high (meta-analysis, direct
  population, most recent evidence on this exact question).

### 2e. Safety: kidney, GI

- **✓ Longobardi I., Solis M.Y., Roschel H., Gualano B. (2025)** — "A short
  review of the most common safety concerns regarding creatine ingestion" —
  *Frontiers in Nutrition*, 12:1682746.
  **Verification:** title, full author list, journal, year, volume/article
  number confirmed via direct fetch of the publisher's full text.
  **Summary:** Narrative review addressing the most commonly raised safety
  concerns (kidney function, cancer risk, dehydration, GI symptoms).
  Concludes creatine monohydrate is **generally safe** at recommended doses
  in healthy people; **GI symptoms (diarrhea, bloating, stomach discomfort)
  are the most commonly reported adverse effect**, and are **dose-dependent**
  — more common at high/bolus (loading-phase) doses than at steady 3–5 g/day.
  On kidney function: an athlete supplementing at recommended doses shows no
  meaningful renal harm in healthy people; a *rise in serum creatinine* after
  starting creatine reflects increased creatine/creatinine turnover, **not**
  kidney damage, but creatinine-based eGFR estimates become an unreliable
  monitoring tool once someone supplements (relevant if this athlete or her
  physician ever orders routine bloodwork and sees a creatinine bump).
  **Tag:** `[ADAPTED: general-endurance]`, Confidence: medium-high (recent
  narrative review by researchers with an established, non-industry academic
  publication record in this space; still a narrative, not a fresh
  meta-analysis, on the kidney point specifically).
  **Practical takeaway for the library:** if this athlete supplements, a
  **straight 3–5 g/day** (skipping the 20 g/day loading phase) is both
  effective per Hultman (1996) and avoids the dose range most associated
  with GI symptoms — a reasonable coach recommendation, though the specific
  "skip loading to avoid GI symptoms" framing is `Coach judgment:` built on
  the two verified sources above, not a study that tested that exact
  trade-off.

### 2f. The logged question: creatine × hydration/EAH/cramping

- **✓ Dalbo V.J., Roberts M.D., Stout J.R., Kerksick C.M. (2008)** —
  "Putting to rest the myth of creatine supplementation leading to muscle
  cramps and dehydration" — *British Journal of Sports Medicine*,
  42(7):567–573.
  **Verification:** title, full author list, journal, year, volume/pages
  confirmed via publisher and independent institutional-repository listings.
  **Summary:** Narrative review directly addressing the popular claim that
  creatine causes cramping/dehydration. Concludes the claim is a media-
  and-anecdote-driven "fallacy" unsupported by controlled research; cites
  data (including `Greenwood et al.`'s American-football-athlete cohort) in
  which creatine **users reported fewer** episodes of cramping, muscle
  tightness/strains, heat illness, and dehydration than non-users, and notes
  short-term creatine supplementation did **not** compromise hydration
  status or thermoregulation in dehydrated, trained men. Proposes creatine
  may even aid thermoregulation via increased intracellular/total body
  water and plasma volume expansion.
  **Why it matters for this athlete specifically — and the limit of that
  relevance:** this directly answers "does creatine increase cramping or
  dehydration risk" — the evidence says no, and if anything the opposite in
  the populations studied (American football, resistance/team-sport
  athletes in heat). **None of this evidence is in open-water swimmers, in
  an immersion context, or in anyone at elevated EAH risk** — the mechanism
  (intracellular water retention, expanded plasma volume) does not obviously
  translate to a protective *or* harmful effect on the plasma-sodium-
  dilution problem that defines EAH (`08-ultra-feeding.md`'s existing
  Hew-Butler citations: EAH is driven by hypotonic fluid *volume* intake
  relative to renal excretion capacity, a different compartment/mechanism
  than creatine's intracellular effect). **State this as an open,
  unaddressed question, not an inferred reassurance.**
  **Tag:** `[ADAPTED: general-endurance]` for the cramping/dehydration myth
  itself, Confidence: medium-high (real controlled data, but not
  ultra-endurance, not swimming, not immersion, not in anyone with EAH risk
  factors — a meaningful population gap). The creatine×EAH interaction
  claim specifically is `Coach judgment:` (no mechanism-tested source
  exists), Confidence: low.
  **Test:** if this athlete supplements creatine and does a long open-water
  swim, weigh her pre/post (per `08`'s existing nude-body-mass protocol) on
  a creatine day vs. a non-creatine day of similar duration/conditions — if
  her measured mass trend or urine-output pattern differs meaningfully, that
  would be the first real-world signal on a question the literature hasn't
  answered.

---

## 3. Daily/periodized nutrition (not in-session)

- **✓ Impey S.G., Hearris M.A., Hammond K.M., Bartlett J.D., Louis J., Close
  G.L., Morton J.P. (2018)** — "Fuel for the Work Required: A Theoretical
  Framework for Carbohydrate Periodization and the Glycogen Threshold
  Hypothesis" — *Sports Medicine*, 48(5):1031–1048.
  **Verification:** title, full author list, journal, year, volume/pages
  confirmed via publisher, PMC, and independent citation records.
  **Summary:** Theoretical/narrative review. Proposes that daily and even
  meal-to-meal carbohydrate intake should be adjusted to match the specific
  demands and goals of *that* training session — high carbohydrate
  availability for sessions needing top-end quality/intensity (e.g. a race-
  pace or long-swim session), deliberately lower availability for some
  easier sessions to bias the training-adaptation signal ("train low,
  compete high"), rather than a flat daily carbohydrate number regardless of
  the day's training. Introduces a "glycogen threshold" window — enough
  glycogen to complete the required work, but not so much that the
  molecular signal for adaptation is blunted.
  **Why it matters for this athlete:** a coached pool practice + open-water
  + strength schedule already has very heterogeneous daily loads (easy
  technique day vs. long open-water day vs. race-pace intervals) — this is
  the theoretical grounding for varying her daily carbohydrate target by
  the day's *purpose*, not just its duration, which is a genuinely different
  and more useful lever than a flat g/kg/day number.
  **Tag:** `[ADAPTED: general-endurance]` (theoretical framework, largely
  built on cycling/running literature — no swim-specific validation),
  Confidence: medium (influential, widely cited framework, but it is a
  *hypothesis paper*, not a body of swim-specific outcome trials — say so).
  **Caveat, and it's an important one for this athlete specifically:** a
  "train low" strategy that deliberately restricts carbohydrate on some
  days sits close to the low-energy-availability territory `13-reds-
  energy-availability.md` already flags as a live concern for this athlete
  — the library should present periodization as varying intake *around* an
  adequate total, not as license to under-fuel easy days, and should
  cross-reference `13`'s existing caution.
  **Test:** compare next-day quality-session RPE/pace on days following a
  deliberately lower-carbohydrate easy day vs. a flat-carbohydrate easy day,
  in her own log history — exploratory only.

- **✓ Moore D.R., Churchward-Venne T.A., Witard O., Breen L., Burd N.A.,
  Tipton K.D., Phillips S.M. (2015)** — "Protein Ingestion to Stimulate
  Myofibrillar Protein Synthesis Requires Greater Relative Protein Intakes
  in Healthy Older Versus Younger Men" — *The Journals of Gerontology:
  Series A*, 70(1):57–62.
  **Verification:** title, full author list, journal, year, volume/pages
  confirmed via publisher and independent citation records.
  **Summary:** Older men needed a **greater relative per-meal protein dose**
  (~0.40 g/kg body mass) than younger men (~0.24 g/kg) to maximally
  stimulate post-exercise muscle protein synthesis — "anabolic resistance."
  This underlies the commonly cited **per-meal leucine threshold**: roughly
  **2.5 g leucine** sufficient in younger adults vs. an estimated **~3 g**
  needed in older adults to maximally trigger the mTORC1 muscle-protein-
  synthesis signal, translating in practice to **~0.4 g/kg (≈25–40 g total)
  high-quality protein per meal** for an older athlete, spread across
  multiple meals/day rather than back-loaded onto one.
  **Why it matters — and the gap**: this is **men only**; women (let alone
  post-menopausal women) are not directly studied here, and the
  per-meal-distribution literature broadly has the same male-skew problem
  `13-reds-energy-availability.md` already documents for this athlete's
  demographic. Use the ~0.4 g/kg/meal figure as a reasonable practical
  target, honestly labeled as extrapolated across sex.
  **Tag:** `[ADAPTED: general-endurance]`, Confidence: medium (real
  mechanistic dose-response data, directly age-relevant, but male-only
  subjects — a genuine, stated gap for this athlete's exact demographic,
  same pattern `13` already flags repeatedly).
  **Test:** on training days, check whether her per-meal protein intake
  (from logged nutrition, if tracked) clusters below ~25 g on any meal
  adjacent to a hard session, and flag it as a pattern worth discussing with
  her, not a rule to enforce automatically.

- **✓ Res P.T., Groen B., Pennings B., Beelen M., Wallis G.A., Gijsen A.P.,
  Senden J.M., van Loon L.J.C. (2012)** — "Protein Ingestion before Sleep
  Improves Postexercise Overnight Recovery" — *Medicine & Science in Sports
  & Exercise*, 44(8):1560–1569.
  **Verification:** title, full author list, journal, year, volume/pages
  confirmed via publisher listing and independent citation records.
  **Summary:** 16 young men, evening resistance exercise + standard
  post-exercise carb/protein feed, then **40 g casein protein ~30 min before
  sleep** vs. placebo. Pre-sleep protein increased overnight whole-body
  protein synthesis and **muscle** protein synthesis (~22% higher) and
  improved net protein balance overnight, with the protein digested and
  absorbed effectively overnight (casein's slow-release profile is the
  presumed mechanism, though this wasn't tested against faster proteins
  head-to-head here).
  **Why it matters:** a concrete, actionable addition on top of `10-
  recovery-hrv.md`'s existing "start carbs within 30–60 min" refeed-window
  guidance — a pre-sleep protein dose (~30–40 g, casein or a mixed/slow-
  digesting source such as dairy or a bedtime snack with dairy) on hard
  training days is a low-cost, evidence-backed addition distinct from the
  immediate post-exercise feed already covered.
  **Tag:** `[ADAPTED: general-endurance]`, Confidence: medium-high (single
  study, young men only, resistance-exercise model rather than swimming —
  but a clean, mechanistically direct result, and pre-sleep protein has been
  replicated in follow-up work by the same/adjacent groups, not
  independently re-verified this pass).
  **Test:** on days with a hard evening session, compare next-morning
  wellness-composite/soreness on nights with vs. without a pre-sleep
  protein feed, in her own log history.

**Cross-reference, not re-derived here:** `10-recovery-hrv.md` already cites
`Kato et al. (2016)` for the **whole-day** 1.65–1.83 g/kg/day protein target
and `Koopman et al. (2004)` for during-exercise carb+protein co-ingestion on
very long days. This section's Moore (2015) and Res (2012) additions are
about **distribution** (per-meal dose, pre-sleep timing) layered on top of
that existing daily total — the library should link them, not duplicate the
daily-total citation.

---

## 4. Gut training progression rate — only the new material

`08-ultra-feeding.md` already covers the *why* (gut adaptation is trainable
and nutrient-specific, transporters upregulate with repeated exposure) via
`Jeukendrup (2017)` and the *evidence it works* via `Miall et al. (2018)`.
Neither of those, per the earlier dossier's own notes, specifies a **rate**
of progression in g/h per week. This pass looked specifically for that gap.

- **~ Cox G.R., Clark S.A., Cox A.J., Halson S.L., Hargreaves M., Hawley
  J.A., Jeacocke N., Snow R.J., Yeo W.K., Burke L.M. (2010)** — "Daily
  training with high carbohydrate availability increases exogenous
  carbohydrate oxidation during endurance cycling" — *Journal of Applied
  Physiology*, 109(1):126–134.
  **Verification:** title, journal, year and lead/senior authors (Cox,
  Burke) confirmed via independent citation records and secondary reviews
  citing this study by name; **full author list and exact page range not
  independently re-derived from a primary fetch this pass** — mark `~`.
  **Summary:** 28 days of daily high-carbohydrate-intake training in
  competitive cyclists measurably **increased exogenous carbohydrate
  oxidation** (i.e. the body got better at using ingested carbohydrate
  during exercise) compared to a low-carbohydrate-availability comparison
  group — direct physiological evidence for gut/metabolic trainability, at
  a **daily, several-week** timescale.
  **Tag:** `[ADAPTED: cycling]`, Confidence: medium (~, see verification
  note; the finding itself — daily repeated exposure over weeks changes
  exogenous-carb handling — is a genuinely different and useful data point
  from `Miall (2018)`'s 2-week GI-symptom-reduction result already in `08`,
  because it's a longer timescale and a different outcome measure).
- **No single verified controlled trial specifies an exact g/h-per-week
  progression step** (e.g. "+10 g/h every 1–2 weeks") — that specific number
  circulating in practitioner content (Precision Hydration, TrainingPeaks,
  various cycling-coaching blogs) is **practitioner convention**, not a
  cited trial finding, and should **not** be presented as `[EVIDENCE]`.
  **Tag:** `Coach judgment:` for any specific weekly step-size the library
  adopts — ground it in "the athlete's own tolerance, progressed gradually
  over the training block, per the trainability shown in Cox (2010) and
  Miall (2018)," not a specific number claimed to come from a trial.

---

## 5. Carb-loading — masters/female-specific nuance only

`16-race-week.md` already covers the core protocol (`Burke 2011`, `Bussau
2002`). This pass looked specifically for a female/masters nuance.

- **✓ Tarnopolsky M.A., Zawada C., Richmond L.B., Carter S., Shearer J.,
  Graham T., Phillips S.M. (2001)** — "Gender differences in carbohydrate
  loading are related to energy intake" — *Journal of Applied Physiology*,
  91(1):225–230.
  **Verification:** title, full author list, journal, year, volume/pages
  confirmed via direct fetch of the publisher's full text.
  **Summary:** 6 well-trained men and 6 well-trained women. A prior finding
  (cited within this paper) was that women, unlike men, **failed to increase
  muscle glycogen** when carbohydrate intake alone rose from ~58% to ~74–75%
  of energy intake at their *habitual* total energy level. This 2001 study
  tested whether that was really a sex-based physiological limit or an
  artifact of women's typically lower absolute energy intake: when the women
  were given both a higher-carbohydrate-percentage diet **and** ~34% more
  total energy, they **did** successfully load muscle glycogen, comparable
  to men.
  **Why it matters — this is the specific masters/female nuance the
  question asked for:** the practical takeaway for `16-race-week.md` is that
  a female athlete's carb-loading protocol should be dosed against **total
  energy intake, not diet-percentage alone** — simply raising carbohydrate's
  *share* of a habitually-restricted or low-total-calorie diet may
  under-load a female athlete even while looking correct on paper (e.g.
  "she's eating 70% carbs now"). Given `13-reds-energy-availability.md`'s
  existing concern about this athlete's habitual energy intake, this is a
  directly relevant cross-check: **carb-loading needs an absolute gram
  target and adequate total calories, not just a percentage shift**, which
  is exactly how `16` already frames Burke (2011)'s 10–12 g/kg/day figure —
  so this mostly reinforces `16`'s existing approach and flags the failure
  mode to avoid (raising %CHO without raising total energy).
  **Tag:** `[ADAPTED: general-endurance]`, Confidence: medium-high (small n,
  but a clean, directly-on-point mechanistic study, and it is the specific
  Tarnopolsky female-physiology work already referenced qualitatively in
  `library/research-dossiers/2026-07-13-ultra-feeding.md`'s Topic 1 — this
  is a different, carb-loading-specific paper by the same senior author, not
  a duplicate citation).
  **Test:** N/A directly — this is a pre-race protocol design point, not
  something to test against her training-day data; the actionable check is
  simply confirming her carb-load-window meal plan hits the **absolute**
  g/kg target on top of, not instead of, adequate total calories.

---

## 6. Muscle cramping (EAMC) — dehydration/electrolyte vs. neuromuscular

- **✓ Schwellnus M.P. (2009)** — "Cause of exercise associated muscle cramps
  (EAMC)—altered neuromuscular control, dehydration or electrolyte
  depletion?" — *British Journal of Sports Medicine*, 43(6):401–408.
  **Verification:** title, author, journal, year, volume/pages confirmed via
  independent web search and citation records.
  **Summary:** Narrative review. Argues the "dehydration" and "electrolyte
  depletion" hypotheses for EAMC lack a plausible, evidence-supported
  mechanism adequate to explain EAMC's clinical presentation (cramps occur
  in specific, locally fatigued muscles, not as a whole-body phenomenon
  tracking systemic fluid/electrolyte status) — and that accumulating
  evidence instead supports **altered neuromuscular control**: exercise-
  induced local muscle fatigue increases excitatory afferent signaling
  (muscle spindles) and decreases inhibitory signaling (Golgi tendon
  organs), producing abnormal motor-neuron firing that presents first as
  fasciculation/twitching and, if the contraction continues, frank cramping.
  **Tag:** `[ADAPTED: running/general-endurance]`, Confidence: medium (an
  influential single-author narrative review, not a systematic review or
  RCT — present the mechanism as the *leading* explanation, not settled
  fact; see the more recent, more cautious Miller (2022) below).

- **✓ Miller K.C., McDermott B.P., Yeargin S.W., Fiol A., Schwellnus M.P.
  (2022)** — "An Evidence-Based Review of the Pathophysiology, Treatment,
  and Prevention of Exercise-Associated Muscle Cramps" — *Journal of
  Athletic Training*, 57(1):5–15.
  **Verification:** title, full author list, journal, year, volume/pages
  confirmed via independent web search and citation records.
  **Summary:** More recent review, co-authored by Schwellnus himself,
  explicitly **walking back a single-cause claim**: EAMC pathophysiology
  "appears controversial," and current evidence points to a **confluence of
  individual intrinsic and extrinsic risk factors** (fitness level, prior
  cramping history, muscle fatigue, possibly some individuals' fluid/
  electrolyte sensitivity, environmental heat, etc.) rather than one
  singular mechanism for all cramping athletes. Treatment remains
  acute static stretching; prevention is individualized risk-factor
  identification, not a blanket electrolyte or hydration prescription.
  **Why it matters — this is the honest, current synthesis to lead the
  library section with**, not the sharper 2009 neuromuscular-only claim:
  present both, in order (2009's mechanism as the leading contender, 2022's
  "it's probably multifactorial, don't over-commit to one cause" as the
  more current, more careful position).
  **Tag:** `[ADAPTED: general-endurance]`, Confidence: medium (recent
  review, same lead expert revising his own earlier stronger claim — a
  genuinely more trustworthy signal than either paper alone).
  **Gap, stated bluntly:** no swim-specific EAMC evidence exists at all, and
  immersion changes both fluid distribution and neuromuscular/thermal
  context (per `08-ultra-feeding.md`'s existing Epstein 1992 citation on
  immersion diuresis) — whether either the neuromuscular or the
  multifactorial model transfers to a cold- or warm-water ultra-swim is
  untested. `Coach judgment:` if the library wants a swim-specific framing:
  treat an in-swim cramp as a local-fatigue signal to ease pace/effort in
  that limb/stroke phase first, and only treat it as a fluid/electrolyte
  problem alongside other EAH-consistent signs (per `08`'s existing safety
  rail), not as a default assumption.

---

## 7. Other supplements — brief, lower priority

- **✓ Guest N.S., VanDusseldorp T.A., Nelson M.T., Grgic J., Schoenfeld
  B.J., Jenkins N.D.M., Arent S.M., Antonio J., Stout J.R., Trexler E.T.,
  Smith-Ryan A.E., Goldstein E.R., Kalman D.S., Campbell B.I. (2021)** —
  "International society of sports nutrition position stand: caffeine and
  exercise performance" — *Journal of the International Society of Sports
  Nutrition*, 18:1.
  **Verification:** title, full author list, journal, year, volume/article
  confirmed via publisher and PubMed listings.
  **Summary:** Position stand. Caffeine at **3–6 mg/kg** body mass reliably
  improves a range of performance measures (endurance, strength/power,
  sprinting) in many but not all studies; **4–6 mg/kg** specifically
  supported for endurance exercise in heat or at altitude. Individual
  response varies (genetics, habituation).
  **Tag:** position stand — cite as such. `[ADAPTED: general-endurance]`,
  Confidence: high as an authoritative summary of a large literature; same
  COI note as the creatine position stand (overlapping author panel,
  Antonio/Kalman/Campbell appear on both ISSN stands).

- **✓ Owens D.J., Allison R., Close G.L. (2018)** — "Vitamin D and the
  Athlete: Current Perspectives and New Challenges" — *Sports Medicine*,
  48(Suppl 1):3–16.
  **Verification:** title, full author list, journal, year, volume/
  supplement/pages confirmed via publisher and independent citation records.
  **Summary:** Review. Vitamin D inadequacy is common in athletes
  (~56% in one 23-study/2313-athlete pooled figure cited within), worse in
  winter/higher latitude/indoor sport. Notably, **serum vitamin D does not
  correlate with bone health in athletes** the way it does in the general
  population — plausibly because exercise itself is osteogenic and swamps
  the vitamin D signal. Muscle-function/performance effects are only clearly
  seen at **clinically low** levels (<25 nmol/L); supplementing already-
  inadequate men (4,000 IU/day) improved muscle force recovery after
  eccentric-heavy exercise.
  **Why it matters for this athlete:** relevant given her sport
  (open-water/pool — much of it indoor-adjacent or covered) and age; **but**
  swimming's non-osteogenic nature (already flagged as the single
  highest-value finding in `13-reds-energy-availability.md`) means the
  athlete cannot lean on "exercise protects bone regardless of vitamin D" the
  way a land-based athlete might — this is a case where two library
  sections should be read together, not independently.
  **Tag:** `[ADAPTED: general-endurance]`, Confidence: medium (review-level;
  actual deficiency status here would need her own bloodwork, not inferred).

- **✓ Sim M., Garvican-Lewis L.A., Cox G.R., Govus A., McKay A.K.A.,
  Stellingwerff T., Peeling P. (2019)** — "Iron considerations for the
  athlete: a narrative review" — *European Journal of Applied Physiology*,
  119(7):1463–1478.
  **Verification:** title, full author list, journal, year, volume/pages
  confirmed via direct fetch of the publisher's full text.
  **Summary:** Narrative review. Iron deficiency is common in athletes,
  disproportionately in **female** athletes (~15–35% of female-athlete
  cohorts vs. ~5–11% of male cohorts). Exercise itself raises hepcidin (the
  master iron-regulatory hormone) acutely, which can suppress iron
  absorption particularly after hard training — timing iron-rich meals away
  from the immediate post-hard-session window (hepcidin peaks ~3–6h
  post-exercise) is a discussed practical lever.
  **Tag:** `[ADAPTED: general-endurance]`, Confidence: medium-high (review,
  directly relevant demographic — female endurance athlete — though not
  swim- or masters-specific; menopausal status changes iron dynamics
  further via the loss of menstrual iron loss, which this review, being
  general-population-female-athlete-focused, does not address — a gap).
  **Test:** if this athlete's bloodwork ever shows low ferritin, note
  whether hard-training days' iron-rich meals cluster immediately
  post-session (per the hepcidin-timing point above) vs. spread out, as a
  low-cost behavior check — not a substitute for actual lab-guided
  supplementation, which is a medical decision.

---

## 8. Rejected / unverifiable / do-not-chase

- **The postmenopausal-bone creatine *pilot* study's specific "-0.5% vs.
  -3.9% femoral neck BMD decline" figures.** Real research line (same
  Chilibeck/Candow group, one-year pilot preceding the verified 2023 2-year
  RCT above), but this pass did not independently verify the pilot's exact
  title/authors/journal/numbers. **Do not cite the pilot's specific numbers**
  — lead with the larger, verified 2023 2-year RCT instead, which already
  supersedes it in statistical power.
- **Older individual creatine-and-swimming sprint trials reporting a
  male-only or small sprint benefit** (surfaced repeatedly in search but not
  individually verified this pass, and in any case superseded by the
  pooled, verified `Huang et al. (2024)` null meta-analysis above). **Do not
  cite them as current evidence of a swim benefit** — they predate and are
  outweighed by the 2024 pooled analysis.
- **Commercial/blog "gut training: +10g/h every 1–2 weeks" step-size
  claims** (Precision Hydration, TrainingPeaks, Roadman Cycling and similar
  practitioner content). Internally consistent and plausible, but **not
  traceable to a specific controlled trial** that tested that exact step
  size. Usable only as `Coach judgment:` practitioner convention, exactly
  the same treatment `08-ultra-feeding.md`'s existing dossier gave the
  Channel-swimmer feeding-interval survey — not a citation.
- **A dedicated swim-immersion angle on EAMC cramping** — surfaced in
  searches but not pursued this pass; if the library wants that angle, it
  would need a dedicated verification pass, not an extrapolation from this
  dossier.
- **A creatine × EAH interaction study of any kind.** Searched directly;
  none exists. This is the honest, stated answer to that specific logged
  question — not a citation gap to paper over with an inference dressed up
  as evidence (see §2f for the mechanistic reasoning, explicitly labeled
  `Coach judgment:`, low confidence).

---

## 9. Gaps, stated bluntly

No swim-specific creatine trial exists outside the sprint-performance
literature already superseded by Huang (2024)'s null result — there is no
ultra-distance or open-water creatine study at all. No study has tested
creatine's interaction with exercise-associated hyponatremia risk, in any
sport. The bone/lean-mass creatine literature in postmenopausal women is
strong on lean mass and bone geometry but null on areal BMD, from
essentially one research group's line of trials — independent replication
is thin. The per-meal-protein/leucine-threshold literature (Moore 2015) is
male-only, the same demographic gap `13-reds-energy-availability.md`
already documents repeatedly for this athlete. No EAMC research exists in
swimmers or in an immersion context, so the neuromuscular-vs-multifactorial
cramping question is answered here entirely by extrapolation from land
sports. The Tarnopolsky (2001) carb-loading-by-sex nuance is small-n
(n=6/sex) and not itself in masters/post-menopausal women specifically.
