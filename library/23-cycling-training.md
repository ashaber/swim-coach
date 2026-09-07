# Cycling training (road / mountain bike / cyclocross)

**UNREVIEWED.** First cycling-native library file (`engine/cycling-coach`
branch; `IDEAS.md` IDEA 008 "Multi-sport expansion," use case 5 — Andrew
himself, MTB + cyclocross). Research-only pass: no engine code changed yet.
Raw research input: `library/research-dossiers/2026-09-07-cycling-training.md`
(not itself citable — cite this file and `reference_list.md` directly).

**Tagging-mechanism caveat, stated plainly:** `00-conventions.md`'s
EVIDENCE tag (allowed values `swim-ultra`/`swim`) and ADAPTED tag (allowed
values `cycling`/`running`/`tri`/`general-endurance`) scheme has no
cycling-native EVIDENCE value — `tests/unit/test_library_discipline.py`'s
`EVIDENCE_ALLOWED` only permits `swim-ultra`/`swim`, and `00-conventions.md`
doesn't define anything else.
Every claim below sourced directly from cycling's own literature is
therefore tagged **ADAPTED (cycling)** purely to satisfy the CI gate's
allowed-value list — not because it is genuinely being adapted across
disciplines. A "high" confidence grade on those claims means "no real
cross-discipline inference is happening," which is the honest read of the
tag mechanism's mismatch, not the epistemic content. `IDEAS.md`'s IDEA 008
already flags this exact gap ("no reciprocal tag exists"); fixing it means
editing `00-conventions.md` and the CI gate's allowed-value sets, which is
out of scope for a research-only pass and needs its own human-reviewed
change, not a unilateral fix here.

## Power-based training zones (Coggan 7-zone model)

**`[ADAPTED: cycling]`** Cycling's power-meter-based training zones are
defined as fixed percentages of Functional Threshold Power (FTP — the
highest average power sustainable for ~60 minutes): Z1 Active Recovery
<55%, Z2 Endurance 56–75%, Z3 Tempo 76–90%, Z4 Lactate Threshold 91–105%,
Z5 VO2max 106–120%, Z6 Anaerobic Capacity 121–150%, Z7 Neuromuscular Power
>150% (no meaningful upper %FTP cap — these are short, maximal sprint
efforts). Per `Allen H., Coggan A. (2010)`, *Training and Racing with a
Power Meter* (2nd ed., VeloPress) and its 2019 3rd edition (adds
McGregor) — the originating practitioner text, confirmed by multiple
independent secondary sources converging on an identical table this
session, though not by a direct primary-text read. **Confidence: high**
(the practitioner-convention tier — same footing as this project's
existing TSS citation to the same book, not an independently validated
physiological threshold set). **Test:** if this athlete's own RPE/HR
response at a given %FTP drifts consistently outside what the assigned
zone predicts (e.g. Z2 riding feels harder than "conversational" across
several weeks), re-test FTP before assuming the zone boundaries themselves
are wrong.

Unlike swimming (no power meter — `05-open-water-pace-inference.md`
infers pace from CSS instead), cycling zones anchor directly to a
continuously measurable output, so there is no analog to swimming's
open-water-pace-correction problem here — a genuine structural difference
between the two disciplines' zone systems, not just a units change.

## Training Stress Score, Normalized Power, Intensity Factor

**`[ADAPTED: cycling]`** Normalized Power (NP) is computed via a 4-step
algorithm: (1) a rolling 30-second average of power across the ride, (2)
each value raised to the 4th power, (3) those values averaged, (4) the
4th root taken. Intensity Factor `IF = NP / FTP`. Training Stress Score
`TSS = duration_hours * IF^2 * 100` — one hour exactly at FTP (IF = 1.0)
scores 100. Per the same Allen/Coggan text; the exact NP algorithm
independently confirmed by three convergent secondary explanations this
session. **This is the un-adapted, squared-exponent form** that
`engine/swim_coach/load.py`'s own `SWIM_TSS_INTENSITY_EXPONENT` comment
already documents before applying its own deliberate swim-specific cubing
— this file cites the same source, just for its native cycling use rather
than the swim adaptation. **Confidence: high.** **Test:** if a computed
TSS for a ride diverges materially from what TrainingPeaks or
intervals.icu computes for the same file, re-derive the NP/IF calculation
step by step before trusting either number.

`Coach judgment:` Applying cycling TSS to MTB/cyclocross rides assumes a
power meter (or a reliable HR-based substitute — see
`15-tiered-session-load.md`'s tiered fallback, already sport-agnostic).
Technical off-road terrain's stop-start power spikes are exactly the
pattern NP's 4th-power weighting was designed to capture rather than
average away, so the formula itself should transfer mechanically better
to MTB than a simple average-power measure would — but this is
engineering reasoning, not a claim backed by an MTB-specific NP validation
study; none was found this pass.

## CTL / ATL / TSB time constants — how well-grounded for cycling

`engine/swim_coach/load.py`'s `CTL_TIME_CONSTANT_DAYS = 42` /
`ATL_TIME_CONSTANT_DAYS = 7` are already flagged "unverified for swimming."
This section answers the parallel question for their native discipline.

**`[ADAPTED: cycling]`** The impulse-response model these constants
implement originates with `Banister E.W., Calvert T.W., Savage M.V.,
Bach T. (1975)`, "A Systems Model of Training for Athletic Performance,"
*Australian Journal of Sports Medicine*, 7:57-61 (title/authors/journal/
year confirmed across independent citation indexes; the exact page range
has a minor cross-index discrepancy, flagged honestly rather than picked
arbitrarily). TrainingPeaks' specific 42-day/7-day defaults are a
practitioner convention from the same Allen/Coggan/TrainingPeaks lineage
as the TSS formula above — confirmed as the actual shipped default by
several independent sources, but **not independently re-derived from
cycling outcome data by any source found this session**; every source
states it as a chosen default, not a validated finding. **Confidence:
medium** (near-universal practitioner adoption, but the specific numbers
themselves are convention, not outcome-validated). **Test:** if this
athlete's real TSB swings correlate poorly with felt form/fatigue on
`CTL_TIME_CONSTANT_DAYS=42`/`ATL_TIME_CONSTANT_DAYS=7`, that's grounds to
revisit the constants for this athlete specifically, the same posture
`03-periodization.md` already takes toward the swimming question.

Real, recent methodological critique exists and should temper any
"settled fact" framing: `Vermeire K., Ghijs M., Bourgois J., Boone J.
(2022)`, "The Fitness-Fatigue Model: What's in the Numbers?," *IJSPP*,
17(5):810-813, cautions that fitness-fatigue-model parameters are
sensitive to fitting technique and starting values, not fixed
physiological constants. `Marchal A., Benazieb O., Weldegebriel Y., et al.
(2025)`, "Statistical flaws of the fitness-fatigue sports performance
prediction model," *Scientific Reports*, 15:3706, found the model
ill-conditioned in elite short-track speed skaters (fitness/fatigue time
constants not simultaneously identifiable from typical training data) —
**not a cycling population**, so this is general model-class caution, not
direct cycling counter-evidence. `[ADAPTED: general-endurance]`,
**Confidence: low-medium** for relevance to this athlete's cycling plan
specifically. **Test:** treat any single day's TSB as noisy; trust the
multi-week trend, not a point value, before making a plan decision off it.

## Periodization and volume progression

**`[ADAPTED: cycling]`** `Galán-Rioja M.Á., González-Ravé J.M.,
González-Mohíno F., Seiler S. (2023)`, "Training Periodization, Intensity
Distribution, and Volume in Trained Cyclists: A Systematic Review,"
*IJSPP*, 18(2):112-122 (7 studies, PRISMA methodology): traditional
periodization ran 7.5–10.76 h/week with pyramidal intensity distribution;
block periodization ran 1–8-week concentrated blocks at 8.75–11.68 h/week
with pyramidal or polarized distribution. Both improved VO2max and
threshold measures; **the review's own conclusion is that no evidence
currently favors one periodization model over the other** in trained road
cyclists across 8–12-week windows. **Confidence: high** (systematic
review, direct cycling population, on the periodization-model-comparison
question specifically). **Test:** if a block-periodization mesocycle
consistently underperforms a traditional one for this athlete's own power/
threshold trend, that is athlete-specific signal this review's "no clear
winner" verdict already anticipates — don't force whichever model failed
into future macro-planning by default.

`Coach judgment, honest gap:` this review does **not** contain a
week-to-week safe volume-*progression-rate* number (checked specifically
this pass) — it compares completed periodization models, not build-up
speed within one. No cycling-specific replacement for running's
already-debunked "10% rule" (`Buist et al. 2008`, already in
`reference_list.md`'s "Injury & training load" section) was found. Any
week-to-week ramp cap this engine adds for cycling should be marked
`Coach judgment:` explicitly (matching the swim engine's own uncited
+8%/week rail) rather than implying a citation that doesn't exist.

## Injury: patellofemoral pain and knee loading

**`[ADAPTED: cycling]`** `Clarsen B., Krosshaug T., Bahr R. (2010)`,
"Overuse Injuries in Professional Road Cyclists," *American Journal of
Sports Medicine*, 38(12):2494-2501 — 109 of 116 riders across 7
professional teams, 94 overuse injuries registered: lower back 45%, knee
23% (anterior knee pain a specific study focus). The best-grounded single
source for road-cycling overuse/knee-injury prevalence found this pass —
an elite, direct, cycling-specific cohort. **Confidence: high.** **Test:**
flag any week where reported knee discomfort co-occurs with a recent
saddle-height or cleat-position change before assuming it's a load-volume
problem rather than a bike-fit one.

**`[ADAPTED: cycling]`** `Bini R., Priego-Quesada J. (2022)`, "Methods to
determine saddle height in cycling and implications of changes in saddle
height in performance and injury risk: A systematic review," *Journal of
Sports Sciences*, 40(4):386-400 (41 included studies, screened from
29,398 records): patellofemoral compressive force is inversely related to
saddle height (lower saddle → more knee load); a 5% saddle-height change
altered knee kinematics by 35% and joint moments by 16%; 25–30° knee
flexion at bottom-dead-center is the consistently recommended target. The
review's own text flags the underlying body/bike/training-load-to-knee-
pain evidence base as still comparatively thin. **Confidence:
medium-high.** **Test:** if this athlete reports anterior knee pain,
check saddle height/fore-aft position against the 25–30° BDC-flexion
target before treating it purely as an overuse-volume issue.

## Discipline variants: road vs. mountain bike vs. cyclocross

Research does **not** treat cycling as one generic umbrella — road and
MTB (XCO) are studied as physiologically distinct, and cyclocross is an
explicitly acknowledged research gap, not merely an unexamined one.

**`[ADAPTED: cycling]`** `Protzen G., Inoue A., Buzzachera C., Doma K.,
Devantier-Thomas B., Herrero-Molleda A., García-López J., Boullosa D.
(2026)`, "The Physiology of Contemporary Olympic Cross-Country Mountain
Biking: A Systematic Review," *Sports Medicine - Open*, 12:16 (direct
full-text read this session): XCO racing spends ~25% of race time above
maximal aerobic power via 3–10-second surges repeated 15–20 times per
lap — highly intermittent versus road's continuous pacing; elite XCO
VO2max is comparable to or exceeds road cyclists'; anaerobic-capacity
contribution has grown as courses trend more technical; even non-pedaling
technical sections impose real physiological stress. **Confidence:
high.** **Test:** if this athlete's MTB sessions are planned using
road-style steady-power targets, expect a mismatch against felt effort on
technical terrain — MTB session design should budget for intermittent
above-threshold surges, not a single target watt.

**`[ADAPTED: cycling]`** `Fallon T., Palmer D., Bigard X., Heron N.
(2025)`, "Epidemiology of injury and illness across all the competitive
cycling disciplines: a systematic review and meta-analysis," *BMJ Open
Sport & Exercise Medicine*, 11(3):e002364 (direct full-text read):
injury incidence/365 days — BMX 4.59, road 3.68, para 3.62, MTB 3.61,
track 3.45; acute injury is upper-limb-dominant (crash-driven) across
disciplines, the opposite pattern from road-cycling overuse studies'
lower-limb dominance (Clarsen et al. 2010 above) — acute and overuse
injury are genuinely different problems, not the same risk measured two
ways. **States explicitly that cyclocross, gravel, indoor cycling,
trials, and esports "have not been represented to date within the
research."** **Confidence: medium-high.** **Test:** if this athlete
reports a crash-related injury, treat it as this section's acute/
upper-limb pattern, not the overuse/knee pattern above — different
mechanism, different response.

**`[ADAPTED: cycling]`** `Fallon T., Fischer N., Heron N. (2025)`, "Injury
epidemiology in cyclocross. A preliminary study," *The Physician and
Sportsmedicine*, published online 2025-11-13: 534 riders at the 2025
British National Cyclocross Championships, 6.7% injury rate, mostly
moderate acute injuries — a pattern the authors themselves describe as
distinct from road/MTB. Self-described "preliminary," single event, not
yet replicated — genuinely the first cyclocross-specific epidemiology
study found this pass, not this dossier's search failing to find an
established one. **Confidence: low-medium.** **Test:** treat any
cyclocross-specific injury-risk guidance for this athlete as provisional
pending a second independent study; don't let one preliminary event stand
in for an established base rate.

**Rejected source, flagged for the record:** `Carmichael et al. (2017)`,
"Physiological response to cyclocross racing," *Sports and Exercise
Medicine - Open Journal*,
3(3):74-80, is real but published by Openventio, a Beall's-list
potentially-predatory publisher — same category as `reference_list.md`'s
already-demoted Smith & Thomas/Hilaris entry. Not cited above; recorded so
a future pass doesn't re-verify and reintroduce it unknowingly.
