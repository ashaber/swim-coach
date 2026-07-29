# Strength & dryland programming

Grounds `engine/swim_coach/plan.py`'s `STRENGTH_SESSIONS_PER_WEEK`,
`STRENGTH_SESSION_MIN`, the strength-session placement rule inside
`generate_week()`, and `engine/swim_coach/adapt.py`'s cut-week
strength->recovery conversion. See `00-conventions.md` for the tagging
scheme and `reference_list.md` for full citations.
`04-css-intensity-anchors.md`'s "Dryland strength as an intensity-adjacent
input" section already grounds the 2x/week *frequency* constant at
`Confidence: high`; this file is the fuller home for everything around that
frequency number — duration, placement, load-budget interaction, and what
happens to strength under a cut or taper. **UNREVIEWED**: this file is
agent-authored per `00-conventions.md`'s workflow and needs Andrew's human
review before being treated as settled grounding truth.

## Why strength is in the plan at all: strength/balance improvement, not proven injury-incidence reduction

**[EVIDENCE: swim]** `reference_list.md`'s "Injury & training load" section
cites three dry-land shoulder-strengthening RCTs in competitive swimmers —
Hibberd et al. (2012), Manske et al. (2015), and Tavares, Vilas-Boas &
Castro (2025) — showing improved rotator-cuff strength/functional balance
and reduced in-season shoulder-rotational imbalance from structured
dry-land rotator-cuff/scapular-stabilizer programs. Confidence: high for
the strength/balance finding — three RCTs, direct swim population, not an
adaptation from another sport.

**Correction (2026-07-28):** this section previously said the RCTs showed
"reduced shoulder pain/injury incidence." That overstates what these three
verified trials individually report: Hibberd (2012) found no significant
*between-group* strength difference, and Manske (2015) found shoulder
soreness *not* significantly different between groups over 12 weeks —
neither trial was powered as an injury-incidence study. The durable,
well-supported claim is **rotator-cuff strength/balance improvement and
in-season imbalance prevention**; injury/pain-incidence reduction is a
plausible but *mixed*, weaker downstream inference that these three trials
do not individually prove. Same honest-correction spirit as the Formosa
citation-debt note (`03-periodization.md`/`06-long-swim-progression.md`) —
flagged rather than quietly left overstated.

Two of the three trials also independently corroborate
`STRENGTH_SESSIONS_PER_WEEK = 2`: Tavares (2025) dosed twice weekly and
Manske (2015) dosed 2-3x/week — the same studies that now supply the
exercise selection below also ground the frequency constant, tightening
`04-css-intensity-anchors.md`'s previously generic "multiple RCTs"
reference.

Framing matters here: this is a *strength/balance* claim, not a
performance claim, and — per the correction above — not a settled
*injury-incidence* claim either. The RCT evidence supports strength work
improving rotator-cuff strength and reducing in-season imbalance in
swimmers who train a lot of pool volume; it does not, by itself, prove
reduced injury/pain incidence, and it does not claim strength work makes
this athlete swim faster. That performance question is addressed
separately below, with much weaker evidence.

## Session duration: 45 minutes

**Coach judgment.** `STRENGTH_SESSION_MIN = 45` has no citation behind it
— none of the RCTs in `reference_list.md` are individually verified down
to a specific per-session duration, and even if they were, translating a
study protocol's duration into "45 minutes" for this athlete's own
schedule is an engineering choice, not a research finding. 45 minutes is
sized to fit a genuine strength stimulus (warm-up, several exercises,
work sets) inside a slot that doesn't crowd out the rest of a training
day around 3-5x/week pool practice plus long-swim volume.

## What's actually in a session: exercise selection and dosing

**UNREVIEWED.** Hibberd et al. (2012), Manske et al. (2015), and Tavares,
Vilas-Boas & Castro (2025) — the same three RCTs above — give complete,
reproducible protocols in this exact population and mechanism, not just a
frequency number. This moves the section from pure `Coach judgment` to a
mix of `[EVIDENCE: swim]`-grounded exercise selection and `Coach judgment`
for the specific fixed dose this engine picks — but it is still a starting
point pending Andrew's review, not a prescription (see the caveats below).

**Core exercise list** `[EVIDENCE: swim]` (rotator-cuff/scapular-stabilizer
movements appearing across two or more of the three trials):
internal rotation at 90° abduction, external rotation at 90° abduction,
scapular punches, scapular retraction ("Ts"), and retraction with upward
rotation ("Ys"). Hibberd (2012) additionally used retraction with downward
rotation ("Ws"), low rows, and shoulder flexion; Manske (2015) used the
same movement pattern set as five resistance-band exercises (flexors,
abductors, extensors, internal/external rotators).

**Dosing** `[EVIDENCE: swim] Confidence: medium` for the *range*: across
the three trials, volume converges loosely on 2-3 sets x 10-20 reps, but
load does **not** converge — Manske (2015) used self-regulated elastic
bands (RPE 6-10, progressed when RPE dropped below 6), Hibberd (2012) used
resistance tubing without a tightly specified load, and Tavares (2025)
used dumbbells at 75% 1RM with a 5s-concentric/5s-eccentric tempo. Do not
collapse this into a single "high-rep, low-load rotator-cuff rule" — no
such source was verified, and Tavares' 75% 1RM load contradicts a blanket
low-load framing.

**This engine's fixed default** (`plan.py`'s `_strength_session_structure`,
`STRENGTH_CORE_EXERCISES`): 2 sets x 10 reps of the core five exercises
above, following Tavares (2025) — the strongest/most recent of the three
citations (blinded RCT, twice-weekly, matching `STRENGTH_SESSIONS_PER_WEEK`)
— at a moderate/RPE-anchored load rather than a literal 1RM percentage
(this athlete's 1RM isn't tested). `Coach judgment:` for collapsing the
trials' divergent-load range to this one number, not itself a cited dose.
The second weekly session additionally layers in general full-body work
(squat, single-leg RDL, core hold) — `Coach judgment:`, since none of the
three trials tested full-body additions; a reasonable, honestly-labelled,
time-permitting extra, not evidence-graded.

**Kettlebell equipment choice: `Coach judgment:`, no citation exists.** No
swim-specific or defensibly adjacent endurance-transfer source was found
for kettlebell programming — general kettlebell-strength reviews exist,
but not in swimmers or a comparably adjacent population. If kettlebells
are used, that is an equipment/exercise-selection choice, not a
research-backed prescription.

**Return-from-a-layoff progression: `Coach judgment:`, no citation
exists.** Mujika & Padilla (2000, Parts I & II) verify how quickly
training adaptations are *lost* during a layoff (`[ADAPTED:
general-endurance] Confidence: high` for the detraining phenomenon itself)
— useful framing for why an experienced lifter returning after months
should start below prior capacity — but they prescribe no
return-to-training ramp. Any specific return progression built on top of
that framing is `Coach judgment:`, not a cited number. **Test:** if this
athlete resumes strength work after a month-plus layoff and starts at
full pre-layoff load rather than a reduced one, watch for
disproportionate soreness/fatigue relative to the same exercises earlier
in the season — that would support the detraining framing above, i.e.
that capacity genuinely regressed and wasn't just deconditioning-in-name.

Treat any specific exercise list or dose generated from this section as a
starting point pending Andrew's review, not a prescription — same caveat
this file has carried since before this rewrite.

## Does strength training improve swim performance, not just reduce injury?

**[ADAPTED: cycling/running] Confidence: low.** Rønnestad B.R. & Mujika I.
(2014), "Optimizing strength training for running and cycling endurance
performance: A review" (*Scandinavian Journal of Medicine & Science in
Sports*), found heavy/explosive strength training improves endurance
economy in runners and cyclists. It is tempting to apply this directly to
swimming as a rationale for strength work beyond injury prevention, but
the inference is weaker here than in `06-long-swim-progression.md`'s or
`04`'s running/cycling adaptations, for a specific reason: running and
cycling economy are substantially mechanical/muscular (stride and pedal
mechanics respond fairly directly to leg strength and power), while
swimming economy is dominated by stroke technique and water-specific
skill in a way land-based leg/trunk strength transfers to only
indirectly. Confidence is therefore graded **low**, not medium — this is
a plausible-but-unconfirmed transfer, closer to speculation than the
shoulder-injury evidence above. **Test:** if a strength block coincides
with an improving CSS re-test (`04-css-intensity-anchors.md`'s 4-6 week
re-test cadence) with no corresponding change in swim-specific pool
volume, that's a weak positive signal for transfer; if CSS holds flat or
degrades across a strength block despite consistent pool training, that's
evidence against meaningful economy transfer for this athlete, and the
practical takeaway (injury prevention alone, not performance) should be
treated as the default rather than the exception.

This is not currently wired to any engine constant — `plan.py` doesn't
size strength load by a performance target, only by fixed frequency and
duration — so this section is a caveat for `/coach` conversations, not a
grounded number.

## Placement: pool-free weekdays, never the weekend

**Coach judgment.** `generate_week()`'s strength placement excludes both
the athlete's pool-practice days (`pool_offsets`) and Saturday/Sunday
(`_WEEKDAY_OFFSETS["sat"]`, `["sun"]`) before picking
`STRENGTH_SESSIONS_PER_WEEK` days via `_pick_days()`. Two judgment calls
bundled into one rule:

- **Not on pool days**: fresh shoulders for quality dryland work, and
  avoiding same-day interference between a pool session that already
  loads the shoulders/upper body and a strength session targeting the
  same joints. This isn't independently cited — it's a stress-budget
  heuristic, not a tested same-day-interference finding for swimmers
  specifically (the Rønnestad & Mujika review above touches on
  concurrent-training interference in a run/bike context, but that's not
  extended here as a citation for swim-specific same-day sequencing).
- **Never Saturday/Sunday**: the weekend is long-swim territory
  (`06-long-swim-progression.md`) — Saturday (and Sunday, in
  `multi_day_stage` format) already carries the week's highest-load,
  most race-specific session. Stacking a strength session on top of that
  would compete for the same recovery window the long swim needs most,
  so strength is deliberately kept off those days regardless of whether
  a pool session also happens to fall there.

`_pick_days()` falls back to reusing an excluded day only if there aren't
enough free weekdays — in a normal 3-5 day/week pool schedule this
fallback essentially never triggers, since 7 days minus a pool schedule
minus 2 weekend days almost always leaves at least 2 free weekdays for 2
strength sessions.

## Watch total load, not just strength load, when ramping

**[EVIDENCE: swim] Confidence: low (caveat-heavy).** Feijen S. et al.
(2021), "Prediction of Shoulder Pain in Youth Competitive Swimmers"
(*American Journal of Sports Medicine*), found an acute:chronic workload
ratio (ACWR) associated with shoulder pain, odds ratio ~4.31 — but the
cohort was **youth** swimmers, the confidence interval's lower bound sits
near 1.0 (marginal significance), and ACWR methodology is broadly
criticized as a predictive tool (see `03-periodization.md`'s ACWR
section for the fuller critique, including Buist et al. 2008's finding
that graded-progression "10% rule" programs show no injury-rate advantage
over faster progression). Treat this as a weak-evidence caution, not a
hard threshold: when a week's pool volume, long-swim ladder step
(`06-long-swim-progression.md`), and strength sessions are all ramping
together, shoulder load isn't just the strength sessions' problem —
that's the practical reason this section belongs in `07` even though it's
not a numeric engine constant. **Test:** if shoulder soreness/pain shows
up in a wellness check-in during a week where total training load (not
just strength volume) spiked, don't isolate the strength sessions as the
cause without first checking whether pool volume or long-swim distance
also jumped — this is exactly the kind of total-load confound Feijen's
own caveated finding warns about.

## Cut weeks: strength is the first thing sacrificed

**Coach judgment.** `adapt.py`'s cut-week handling converts the *last*
strength session of the week into a recovery session
(`sport="strength"` -> `sport="recovery"`, `RECOVERY_SESSION_MIN`
duration) rather than trimming pool volume, the long swim, or the
remaining strength session. The rationale: strength sessions are
`source="ai_coach"` — this project's own addition to the week — not a
fixed pool-coach commitment the athlete has already scheduled around, so
they're the most flexible thing on the calendar to remove first when
total load needs to drop.

This trade-off deserves to be stated honestly, not presented as a free
lunch: the strength/balance evidence above is the reason strength is in
the plan at all, and a cut week converting strength to recovery is
explicitly *dropping rotator-cuff strength/balance work* at precisely the
moment (elevated load, triggering a cut) when the athlete may be at
*elevated* shoulder-load risk per the same load-monitoring logic. The
counter-argument
`adapt.py` implicitly makes is that total stress reduction — the reason
for the cut in the first place — outweighs losing one dryland session for
a single week. This file doesn't resolve that tension; it flags it as a
real cost of the cut-week rule, worth `/adapt`'s judgment review rather
than silent automatic application, especially if cuts recur in
back-to-back weeks (repeatedly dropping strength, not just one week's
worth).

## Taper: strength sessions are not currently modified

**Coach judgment / open question, honestly scoped to what the engine
does today.** `plan.py`'s taper-block logic (`TAPER_WEEKS_LONG/SHORT`,
`TAPER_WEEKLY_DECAY`) only caps the long-swim distance during taper
weeks — `generate_week()` still calls the same strength-placement logic
with the same `STRENGTH_SESSIONS_PER_WEEK` and `STRENGTH_SESSION_MIN`
regardless of which macro block the week falls in. There is no
taper-specific strength reduction, conversion, or removal anywhere in
`plan.py` or `adapt.py` today; this file is not inventing one. Formosa
D.P. et al.'s "Training for a 78-km Solo Open Water Swim" case study
(`reference_list.md`, corrected figures) found a ~3-week taper reduced
**total** volume by ~43% while maintaining intensity, which is at least
directionally consistent with strength volume also stepping down during
taper — but that source describes overall swim-training volume, not
dryland strength specifically, so it cannot be cited as direct support
for a strength-taper rule. Whether strength sessions should reduce in
frequency, duration, or intensity during taper (to protect the taper's
purpose of arriving fresh) is flagged here as an **open question**, not
answered by evidence currently in `reference_list.md` — a candidate for
`/adapt`'s manual judgment during taper weeks until (if) the engine grows
an explicit rule.

## Open questions / not yet covered here

- The fixed 2x10 dose, the choice of moderate/RPE-anchored load over a
  literal 1RM percentage, and the general full-body addition are all
  `UNREVIEWED Coach judgment` — the exercise selection and the 2-3 sets x
  10-20 rep range are `[EVIDENCE: swim]`, but collapsing that range to one
  program for this athlete is an engineering choice, not itself evidenced.
- Kettlebell equipment choice and a formal return-from-layoff progression
  remain `Coach judgment` with no citable source found (see "What's
  actually in a session" above) — not gaps to revisit expecting a
  citation to appear, but honest, expected no-source outcomes.
- Whether strength volume/intensity should scale with macro block (base
  vs. build vs. peak) the way swim volume does is not implemented and not
  evidenced here.
- Same-day pool/strength interference (beyond the "not on pool days"
  placement rule) has no swim-specific citation in `reference_list.md`;
  the Rønnestad & Mujika review's concurrent-training discussion is
  run/bike-specific and not extended here.
