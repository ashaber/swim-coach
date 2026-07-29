# Strength / Dryland Programming Research Dossier — feeds `library/07-strength-dryland.md`

> **Provenance note:** this is raw research input for a future rewrite of
> `library/07-strength-dryland.md`'s "What's actually in a session" section
> (exercise selection + dosing), plus the return-from-layoff question. It is
> **not itself a citable library file** — for grounding claims, cite
> `library/reference_list.md` and the topic file directly, never this
> dossier.

Compiled for: swim-coach research library. Research-only pass; no engine,
backend, or existing library file was edited. Follows the citation
discipline in `library/00-conventions.md` and `library/reference_list.md`
(cite by title + author + year + journal, **never** by URL/PMC/PubMed ID;
every source carries a ✓/~/⚠ marker).

**Immediate trigger:** the strength gap logged five separate times in the
feedback/research-question queue since 2026-07-08 — kettlebell exercise
selection, set/rep dosing beyond the bare 2×/week frequency, and
return-from-layoff progression for an experienced lifter. `07`'s own "What's
actually in a session" section currently says plainly that
`reference_list.md` specifies **no** exercises, sets/reps, or load, and
recommends a movement-pattern default (rotator-cuff/scapular-stability core
+ general full-body) as `Coach judgment, UNREVIEWED`.

**Athlete context:** masters female, ultra-distance open-water, 3–5 coached
pool sessions/week + open-water + strength. The strength work in this
system is planned as **injury-prevention** (shoulder), not performance —
see `07`'s framing, which this dossier does not disturb.

**Source count this pass:** 5 ✓ verified · 0 ~ partial · 0 ⚠ unverifiable
carried forward. Two topics returned an **honest no-citable-source
outcome** (kettlebell-for-swimmers; a formal return-to-training
progression), documented in §4 — that is an expected, acceptable result
under this repo's citation discipline, not a gap to paper over.

---

## 1. Executive summary

- **The best-case outcome the task hoped for is real: the swimmer
  shoulder-injury-prevention RCT literature *does* specify actual exercises,
  sets, reps, and load** — it is not frequency-only. Three verifiable trials
  (Hibberd 2012; Manske 2015; Tavares 2025) give complete, reproducible
  protocols in the exact population (competitive swimmers) and the exact
  mechanism (rotator-cuff/scapular-stabilizer balance) that `07` already
  names. This means the `07` "What's actually in a session" section can move
  from `Coach judgment, UNREVIEWED` to **`[EVIDENCE: swim]`-grounded exercise
  selection**, with dosing cited to these protocols rather than invented.
- **Two of the three protocols used ~twice-weekly frequency** (Tavares 2025:
  twice weekly, 12 wk; Manske 2015: 2–3×/week, 12 wk), which independently
  corroborates the engine's `STRENGTH_SESSIONS_PER_WEEK = 2` from the same
  studies that supply the exercises — a tighter grounding than the current
  generic "multiple RCTs" reference.
- **Honest caveat the build agent must carry:** these trials robustly show
  improved rotator-cuff **strength and conventional/functional balance** and
  reduced in-season imbalance; they are **weaker on proven pain/injury
  incidence reduction**. Hibberd (2012) found no significant *between-group*
  strength difference; Manske (2015) found shoulder soreness *not*
  significantly different between groups. The current `reference_list.md`
  line ("reduced shoulder pain/injury incidence") slightly overstates what
  these specific verified studies show — the durable, well-supported claim is
  **strength/balance improvement and imbalance prevention**, with injury/pain
  reduction as a plausible-but-mixed downstream inference. Grade accordingly.
- **Injury-prevention dosing has no single universal convention** — the
  verified protocols themselves *are* the dosing evidence, and they converge
  loosely (2–3 sets × 10–20 reps) but diverge on load (elastic bands at
  RPE 6–10, vs. dumbbells at 75% 1RM). Report the range; do not launder it
  into a fake "high-rep low-load" rule.
- **Return-from-layoff progression: no swim-specific or strength-specific
  *retraining-progression* protocol was found.** The detraining literature
  (Mujika & Padilla 2000, Parts I & II — verified) documents how fast
  adaptations are *lost*, which usefully frames why an experienced lifter
  returning after months starts below prior capacity — but it prescribes no
  return ramp. A return progression stays **`Coach judgment`**, honestly
  labelled, with the detraining reviews cited only for the framing.
- **Kettlebell-for-swimmers: no verifiable sport-specific evidence exists**
  (as `07` already suspected). General kettlebell reviews exist but none in
  swimmers or a defensibly adjacent endurance-transfer context. Kettlebells
  stay an **equipment/exercise-selection choice under `Coach judgment`**, not
  a citation — the expected, legitimate outcome.

---

## 2. Verified sources by topic

### Topic 1 — Swimmer shoulder-injury-prevention protocols (exercises + dosing)

- **✓ Hibberd E.E., Oyama S., Spang J.T., Prentice W.E., Myers J.B.
  (2012)** — "Effect of a 6-Week Strengthening Program on Shoulder and
  Scapular-Stabilizer Strength and Scapular Kinematics in Division I
  Collegiate Swimmers" — *Journal of Sport Rehabilitation*, 21(3):253–265.
  **Verification:** title, full author list, journal, year, volume/issue/
  pages confirmed across the publisher (Human Kinetics), PubMed, and Semantic
  Scholar listings.
  **Protocol (this is the citable content):** resistance-tubing program,
  **3×/week for 6 weeks**. Exercises: scapular retraction (**Ts**), retraction
  with upward rotation (**Ys**), retraction with downward rotation (**Ws**),
  shoulder flexion, low rows, throwing acceleration and deceleration, scapular
  punches, internal rotation at 90° abduction, external rotation at 90°
  abduction; plus two stretches (corner stretch, sleeper stretch).
  **Findings:** shoulder-extension and internal-rotation strength increased
  across all subjects, but there was **no significant *between-group*
  difference** — the study was small and not powered as an injury-incidence
  trial. Cite it for **exercise selection**, not for proof of injury
  reduction.
  **Tag:** `[EVIDENCE: swim]` for the exercise-selection/movement-pattern
  content; Confidence: medium (direct swim population, real protocol; small n,
  no between-group effect, surrogate outcomes not injury rates).

- **✓ Manske R.C., Lewis S., Wolff S., Smith B. (2015)** — "Effects of a
  Dry-Land Strengthening Program in Competitive Adolescent Swimmers" —
  *International Journal of Sports Physical Therapy*, 10(6):858–867.
  **Verification:** title, full author list, journal, year, volume/issue/
  pages confirmed via PubMed and PMC listings.
  **Protocol:** five resistance-band movements (shoulder flexors, abductors,
  extensors, internal rotators, external rotators), performed bilaterally,
  **2 sets of 15 reps**, **2–3×/week for 12 weeks**, done *before* swim
  practice. Band load self-selected to a difficulty of 6–10 on a 0–10 scale,
  progressed when perceived difficulty dropped below 6.
  **Findings:** experimental group gained significantly more **external-
  rotation strength** (23% vs. 11%, p=0.013); other muscle-group gains not
  significant between groups; **shoulder soreness not significantly different
  between groups** over 12 weeks.
  **Why it matters:** supplies a clean sets/reps dosing point (2×15) and a
  practical self-regulated band-load scheme, and corroborates ~2×/week
  frequency. Also the source for the honest "soreness did not differ" caveat.
  **Tag:** `[EVIDENCE: swim]`; Confidence: medium (direct population, real
  protocol; single study, surrogate outcomes).

- **✓ Tavares N., Vilas-Boas J.P., Castro M.A. (2025)** — "Effect of
  Preventive Exercise Programs for Swimmer's Shoulder Injury on Rotator Cuff
  Torque and Balance in Competitive Swimmers: A Randomized Controlled Trial"
  — *Healthcare (Basel)*, 13(5):538.
  **Verification:** title, full author list, journal, year, volume/issue/
  article number confirmed via PMC.
  **Protocol:** care-provider- and participant-blinded parallel RCT, swimmers
  16–35, three groups (weights, elastic band, sham control). Five open-kinetic-
  chain exercises: **internal rotation at 90°, external rotation at 90°,
  scapular punches, Ts, Ys**. **2 sets of 10 reps**, **75% 1RM** (reassessed at
  6 weeks), **5-second concentric + 5-second eccentric tempo**, **twice weekly
  for 12 weeks**. Weight arm used dumbbells (1–5 kg); band arm used resistance
  bands.
  **Findings:** both intervention groups largely **preserved rotator-cuff peak
  torque** across the competitive season (one significant decline in the
  weight group) while controls showed **five** significant declines, and
  intervention groups kept **less conventional/functional imbalance** than
  controls. Conclusion: a 12-week twice-weekly program **minimizes progressive
  in-season shoulder rotational imbalance**.
  **Why it matters:** the strongest single citation for this dossier — recent,
  RCT, blinded, exact population, **twice-weekly** (matching the engine
  constant), and it gives a full dosing prescription (2×10, 75% 1RM, tempo).
  The outcome is framed as **imbalance prevention**, which is exactly how
  `07` should frame the benefit rather than as swim-speed performance.
  **Tag:** `[EVIDENCE: swim]`; Confidence: medium-high (RCT, blinded, direct
  population, contemporary; still surrogate/balance outcomes rather than
  hard injury-incidence endpoints, and from a single research group's line
  of work).
  **Note for the build agent:** the "75% 1RM" load is more strength-oriented
  than the classic low-load band rehab convention — this is real and citable,
  but it means the exercises are prescribed as genuine strengthening, not
  featherweight activation. Present dosing as a *range* across the three
  studies, not a single number.

### Topic 2 — Injury-prevention dosing conventions (not hypertrophy/max-strength)

**Finding: there is no separate, better-verified "injury-prevention dosing"
source than the three protocols above — and they *are* the dosing evidence.**
Across the verified swimmer trials the volume converges loosely on **2–3 sets
× 10–20 reps**, but **load does not converge**: Manske (2015) used
self-regulated elastic-band resistance (RPE 6–10), Hibberd (2012) used
resistance tubing (load not tightly specified), and Tavares (2025) used
75% 1RM. The honest characterization for `07` is therefore:

- `[EVIDENCE: swim]` — the *volume* range (2–3 sets, 10–20 reps) is what the
  swimmer shoulder-prevention trials actually used; Confidence: medium.
- `Coach judgment:` — collapsing that into a single prescribed set/rep/load
  for this athlete is an engineering choice, because the trials themselves
  disagree on load and none was individually dosed to *this* athlete. Do not
  cite a universal "high-rep, low-load rotator-cuff rule"; no such single
  source was verified this pass, and the protocols above contradict a blanket
  low-load framing.

### Topic 3 — Detraining (framing for the return-from-layoff question)

- **✓ Mujika I., Padilla S. (2000)** — "Detraining: Loss of Training-Induced
  Physiological and Performance Adaptations. Part I: Short Term Insufficient
  Training Stimulus" — *Sports Medicine*, 30(2):79–87. **And Part II: Long
  Term Insufficient Training Stimulus** — *Sports Medicine*, 30(3):145–154.
  **Verification:** titles, authors, journal, year, and both volume/page
  ranges confirmed via PubMed (Part II PMID 10999420, used only as a lookup),
  Springer, and multiple independent citation records.
  **Summary:** the canonical two-part review of detraining. Short-term
  (<4 weeks) insufficient stimulus already erodes some adaptations; long-term
  (>4 weeks) detraining markedly reduces VO2max (recently acquired gains lost
  completely; long-standing gains decline but stay above untrained baseline),
  with parallel losses in muscular/metabolic adaptations. Part II also
  discusses strategies to blunt detraining.
  **Why it matters — and its limit:** it supplies the *framing* for the
  return-from-layoff question (an experienced lifter returning after months
  has genuinely lost adaptations, so starting below prior loads is correct and
  expected), but **it does not prescribe a retraining/return progression** —
  it describes the losses, not the ramp back. Use it to justify "start
  conservative, it will come back," not to set specific return percentages.
  **Tag:** `[ADAPTED: general-endurance]` (the reviews are cross-discipline,
  not swim-strength-specific); Confidence: high for the detraining phenomenon
  itself, but the return-progression built on top of it is `Coach judgment`.

---

## 3. What this supports for `library/07-strength-dryland.md`

Pre-characterized so the build agent can lift claims with correct tags (the
`07` file stays **`UNREVIEWED`** until Andrew reviews it):

- **Exercise selection** (rotator-cuff/scapular core): `[EVIDENCE: swim]`,
  citing Hibberd (2012), Manske (2015), Tavares (2025). Concrete named
  movements available: internal/external rotation at 90° abduction, Ts, Ys,
  Ws, scapular punches, low rows, shoulder flexion, scapular retraction —
  all drawn directly from these protocols, all in the exact population.
- **Dosing**: `[EVIDENCE: swim]` for the 2–3 sets × 10–20 rep *range*;
  `Coach judgment:` for the single set/rep/load this engine picks, because the
  trials disagree on load.
- **Twice-weekly frequency**: reinforced by Tavares (2025, twice weekly) and
  Manske (2015, 2–3×/week) — the same studies that supply the exercises now
  also ground `STRENGTH_SESSIONS_PER_WEEK = 2`, tightening `04`/`07`'s
  current generic "multiple RCTs" reference.
- **Benefit framing**: keep it **injury-prevention via rotator-cuff
  strength/balance and in-season imbalance prevention** — *not* proven
  pain/injury-incidence reduction (mixed) and *not* swim-speed performance
  (`07`'s existing `low`-confidence `[ADAPTED]` section already handles that).
- **General full-body work** (legs/trunk/pulling layered in): remains
  `Coach judgment:` — none of the verified swimmer trials tested it; it is a
  reasonable time-permitting addition, honestly labelled.
- **Return-from-layoff**: `Coach judgment:` for the progression itself, with
  Mujika & Padilla (2000) cited only for the detraining framing.

If the build agent adds any of the three RCTs to `reference_list.md`'s
"Injury & training load" section, they should be listed individually (they
are currently only implied by the generic "Dry-land shoulder-strengthening
RCTs in competitive swimmers" line), matching that file's citation format.

---

## 4. Rejected / unverifiable / honest no-source outcomes

- **Kettlebell-specific programming for swimmers — NO citable source.**
  General kettlebell reviews and non-swim RCTs exist (e.g. kettlebell effects
  on strength/power in general athletes, and one HR-recovery RCT in amateur
  male athletes), but **nothing in swimmers, and nothing in a defensibly
  adjacent endurance-transfer context**. Commercial "kettlebell for swimmers"
  programs (TrainHeroic / Train Daly) are practitioner products, **not
  evidence**. Conclusion, stated plainly per `00-conventions.md`: kettlebells
  are an **equipment/exercise-selection choice under `Coach judgment`**, not a
  citation. This is the expected outcome `07` already anticipated — do not
  force-fit a citation.
- **A formal return-to-training / retraining-progression protocol — NO
  citable source.** The detraining reviews (Mujika & Padilla 2000) are real
  and describe the losses, but no verified source prescribes the ramp back for
  an experienced lifter. Return progression stays `Coach judgment`.
- **A universal "injury-prevention = high-rep, low-load" dosing rule — NOT
  verified, and partly contradicted.** No single source establishes it, and
  Tavares (2025) used 75% 1RM. Report the trials' actual (divergent) loads.
- **Batalha N. et al. (2020), "The Effectiveness of a Dry-Land Shoulder
  Rotators Strength Training Program in Injury Prevention in Competitive
  Swimmers," *Journal of Human Kinetics*, 71:11–20** — the paper is **real and
  verified** (title/authors/journal/volume/pages confirmed), but on fetch it
  reads as an **acute single-session** design reporting *no* meaningful
  prevention effect, which makes it a weak and potentially confusing citation
  next to the three multi-week protocols above. **Recommend not citing it** in
  `07` unless the build agent reads the primary text and confirms its design;
  it adds noise, not grounding.
- **Rønnestad & Mujika (2014)** strength-and-endurance-economy review is
  already in `reference_list.md` and already handled by `07`'s existing
  `low`-confidence performance section — **out of scope here**; this dossier
  is about injury-prevention exercise selection/dosing, not the
  strength-improves-swim-speed question.

---

## 5. Verification method note

Every source above was checked for existence and identity via publisher /
PubMed / PMC listings (title + full author list + journal + year +
volume/pages), per `00-conventions.md`'s "cite by title+author, never by ID"
rule. No PMC/PubMed identifier is carried into the library as a citation —
identifiers were used only as a verification lookup and are deliberately
omitted from the citable output. Where a protocol detail (e.g. exact load)
came from a database abstract rather than a full-text primary read, the
dossier says so; the build agent should not promote any single numeric dose
beyond what these summaries support without a primary read.
