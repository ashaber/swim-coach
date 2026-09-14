# FTP / threshold-power change: real signals from an athlete's own data

See `00-conventions.md` for the tagging scheme and `reference_list.md` for
full citations. **Sport scope: `bike`.** Same guidance-scoping constraint
as `23-cycling-training.md`/`24-cycling-periodization-intervals.md`/
`28-bike-ftp-test-protocols.md` — never surfaced to a swim-only athlete.
Not yet wired into `context.py`'s routing (`_LIBRARY_FILE_SPORT_SCOPE`/
keyword routes) — same deferred state `24`/`25`/`28` are honestly left in.
**Research-only pass: no engine code changed.**

## The real question this grounds

Logged athlete feedback (2026-09-13): what real data/model exists for
projecting FTP change from training stimulus — and, specifically, what
real SIGNALS, visible in an athlete's own logged training data, indicate
a genuine threshold shift, as opposed to trusting a vendor's opaque
rolling estimate (the question was prompted by TrainerRoad's AI FTP
detection swinging 282W→277W within a month, a swing this file addresses
briefly, not as its center). This file answers: (1) does real literature
connect a training-load history (CTL/ATL/TSB-style) to actual FTP/
threshold-power *change*, as opposed to general "form"/readiness; (2)
what real, established signals in an athlete's OWN logged data — repeated
real efforts, power-vs-HR trends across sessions — indicate a genuine
threshold shift, and how much noise is normal before a trend is signal;
(3) given both, how should this engine treat a short-window estimate and
what would its own deterministic analyzer need to compute to surface a
real "your recent efforts suggest FTP may have shifted" signal.

## Q1: Does training-load history (CTL/ATL/TSB) predict FTP change itself?

`engine/swim_coach/load.py`'s `ctl_atl_tsb_series` already implements the
standard Banister impulse-response model (`Banister E.W., Calvert T.W.,
Savage M.V., Bach T. (1975)`), and `23`/`24` already document it honestly
as modeling **CTL/ATL/TSB — "fitness"/"fatigue"/"form"** — a *readiness
to perform* estimate, not a model of the underlying physiological ceiling
(FTP/critical power) itself. That distinction matters directly here: TSB
answers "how fresh is this athlete right now," not "has this athlete's
threshold actually moved." Conflating the two is the exact trap the
question is testing.

Two model-class critiques already cited in `23`/`24` bear on whether
CTL/ATL/TSB-style modeling should be trusted for either question.
**`[ADAPTED: general-endurance]`** `Vermeire et al. (2022)`, *IJSPP*,
17(5):810-813, cautions the model's fitted parameters (including its time
constants) are technique/data-sensitive fitted values, not fixed
physiological truths — and that similar training loads from very
different session *types* distort the fit against a real outcome (quoted
directly by Kontro et al. 2026 below). **Confidence: medium.** **Test:**
if this athlete's own logged sessions of similar total load but different
session-type composition (e.g. a threshold-build day vs. an
endurance-volume day of the same TSS) produce visibly different
downstream performance, that is this critique's own prediction — a
single load number hiding real differences — not a modeling artifact.

**`[ADAPTED: general-endurance]`** `Marchal et al. (2025)`, *Scientific
Reports*, 15:3706 (elite short-track speed skaters), found the Banister
model **ill-conditioned** (fitness/fatigue time constants aren't
simultaneously identifiable from typical training data) and **overfits**
— the fatigue term improves training-set fit but not cross-validated
prediction (p=0.57, p=0.41 across two datasets). **Confidence: low-medium**
for cycling transfer (wrong sport), but real statistical caution about the
model class this engine's own CTL/ATL/TSB math belongs to. **Test:**
treat any single day's TSB/CTL/ATL reading as noisy and non-diagnostic of
threshold change; only a multi-week trend, cross-checked against a real
performance outcome, should ever inform a plan decision — same posture
`23`/`24` already take toward this same model class.

The most direct real attempt found this session at modeling **threshold
power change itself** is `[ADAPTED: general-endurance]` `Kontro et al.
(2026)`, *PLOS ONE*, 21(2):e0341721 — a proposal to track critical power
(CP), W′, and Pmax as three separate energy-system-specific parameters
instead of one combined fitness number. **Honest finding, not a hedge: it
is theoretical, not validated.** The authors' own words, confirmed by
direct fetch: "the presented model has not been under strict scientific
scrutiny" and "no published data exist to support the energy-system
specific model parameters." No outcome-validated dataset is reported.
**Confidence: low.** **Test:** if a future validated version of this
model (or a successor) is published with real outcome data connecting
training load to CP change, revisit this file's Q1 conclusion; until
then, treat any claim that a training-load trend predicts real FTP/CP
change as unproven, not merely unconfirmed.

**Net honest conclusion on Q1:** despite an active research thread
(Banister 1975 → Vermeire 2022 → Marchal 2025 → Kontro 2026), **no
validated model was found this session that predicts FTP/threshold-power
change from a training-load history with real outcome data behind it.**
CTL/ATL/TSB estimates readiness, not threshold; treating a CTL/ATL/TSB
trend as a proxy for "FTP is changing" is an inference this file found no
support for, either way.

## Q2: Real signals of genuine threshold change in an athlete's own data

This is the more productive question, and the one most aligned with this
engine's own deterministic-analysis philosophy: rather than trusting any
single test or any vendor's black-box number, look for convergent signal
across an athlete's own **repeated real efforts**.

**Critical power from multiple real maximal efforts, not one test.**
`[ADAPTED: general-endurance]` The CP concept originates with `Monod &
Scherrer (1965)`, *Ergonomics*, 8(3):329-338, and is comprehensively
validated (not merely a practical convention) by `Poole et al. (2016)`,
"Critical Power: An Important Fatigue Threshold in Exercise Physiology,"
*MSSE*, 48(11):2320-2334: CP is a genuine physiological boundary — below
it, muscle PCr/Pi/pH and VO2 stabilize; above it, they progress
continuously to exhaustion. Both sources describe CP/W′ as fit from
**several maximal efforts at different durations, typically performed on
different days** — the power-duration curve, not a single point-in-time
reading, is the real signal. **Confidence: high.** This is a structurally
different construct from an app's single rolling number: it is built
from multiple convergent real data points by design. **Test:** a CP/W′
fit (or any claimed threshold reading built the same way) from fewer than
two real maximal efforts at genuinely different durations should not be
treated as a resolved reading — the source's own multi-point requirement,
not this file's addition.

**How much apparent change is real vs. noise.**
`[ADAPTED: general-endurance]` `Triska et al. (2017)`, *PLOS ONE*,
12(12):e0189776: 10 well-trained triathletes, two repeated
CP tests (each three maximal time-trial efforts: 12/7/3-min) ≥72h apart
under controlled lab conditions. **CP test-retest CV = 2.6%** (a
first-exposure familiarization effect pushes CV to 4.1% the first time);
W′ far noisier (CV 8.2-25.3%). **Confidence: high** — the concrete
quantitative anchor this file uses for "how big a swing is plausibly
real": roughly **2.6-4%** is the noise floor even for genuinely maximal,
purpose-built lab efforts — an athlete's own uncontrolled real training
sessions (varying fatigue, pacing, conditions, motivation) should be
expected to show *at least* that much apparent swing with zero real
fitness change, and likely more. **Test:** a single-session-to-session
swing under ~4% on a comparable real effort is not, by itself,
distinguishable from measurement/day-state noise; a swing that persists
across several repeated real efforts, or one that clears roughly 5-10%
band, is the more defensible signal-vs-noise line — no source found this
session states an exact "N reps over N weeks" number for real (non-lab)
training data specifically, so the multiplier above the lab CV for
real-world noise is `Coach judgment:`, not itself cited.

**Cross-session power-vs-HR decoupling trend.** `[ADAPTED: cycling]`
`Barsumyan et al. (2025)`, "Quantifying training response in cycling
based on cardiovascular drift using machine learning," *Frontiers in
Artificial Intelligence*, 8:1623384: 20 cyclists, monthly standardized
sessions (75% FTP, 60min) over 5 months. Athletes whose cardiovascular-
drift/aerobic-decoupling reading *improved* between consecutive monthly
standardized sessions were reliably classified "responders" (0.87-0.93
cross-validated ML accuracy) — real, if preliminary (n=20, single
protocol, authors themselves call for a larger cohort), evidence that
**the TREND of decoupling/efficiency-factor across multiple comparable
real sessions**, not any one ride's own first-half/second-half split, is
genuine fitness signal. **Confidence: medium.** **Test:** one session's
improved (or worsened) decoupling reading, alone, is not this source's
signal — a consistent direction across several comparable real sessions
over weeks is; a single favorable or unfavorable ride should not move a
threshold judgment on its own. Adjacent to, but distinct from, this
engine's *existing* `interval_analysis.tightened_decoupling` (grounded in
`11-workout-analytics.md`/TrainingPeaks' EF citation, already in
`reference_list.md`) — that function already computes a real, single-ride
EF-decoupling number; Barsumyan et al. add the validated claim that
trending that same kind
of number *across* repeated comparable sessions over weeks is where the
real training-response signal lives, not in any single ride's value.

**Why a single test (or a single vendor number) is a narrower construct.**
`[EVIDENCE: cycling]` `Karsten B., Petrigna L., Klose A., et al. (2021)`,
*Frontiers in Physiology*, 11:613151: CP (multi-effort-derived, mean
256W) and single-20-min-test FTP (mean 249W) correlate strongly (r=0.969)
but are **not interchangeable** for an individual (>90% probability of a
meaningfully different reading, wide ±19-33W limits of agreement).
**Confidence: high**, direct cycling population. Reinforces the same
point from a different angle: a single reading, from any single method —
a lab test, a field test, or an opaque vendor algorithm — carries real
individual-level uncertainty that only resolves with multiple convergent
real data points.

## What this engine's own analyzer would need to compute (IDEA-capture, not built)

`interval_analysis.py` already has the raw machinery this needs — it
just doesn't trend it across sessions yet. `detect_efforts`/
`match_efforts_to_structure` already extract per-effort mean power/HR
from a single real completed ride; `tightened_decoupling` already
computes a single-ride EF-decoupling number. A future build stage could,
without inventing anything new physiologically:

1. **Matched-effort power trend.** For an athlete's own recurring
   session shapes (e.g. a repeated "5x2min" or "2x12min" structure this
   athlete's actual plan already generates), track mean power on the
   *matched* interval type across repeats over a rolling window, and flag
   when the trend clears roughly the Triska et al. (2017) noise floor
   (Q2 above) scaled up for real-world (non-lab, non-maximal) conditions
   — `Coach judgment:` on the exact real-world multiplier, since no
   source found this session states one directly.
2. **Cross-session decoupling trend.** Extend `tightened_decoupling`'s
   existing single-ride EF number into a rolling trend across repeated,
   comparable-intensity real sessions (not necessarily a dedicated
   monthly standardized test the way Barsumyan et al. ran it — this
   athlete's own recurring aerobic sessions may already approximate the
   "comparable session, different week" comparison that trend needs).
3. **A real, athlete-derived power-duration curve.** If an athlete's own
   logged history contains genuinely maximal or near-maximal efforts at
   several different durations (not necessarily from a dedicated CP test
   — a hard race effort, a real threshold interval, a VO2 rep, spread
   across weeks), fit CP/W′ from those real points per Poole et al.
   (2016)'s own multi-trial methodology, rather than from one test or one
   vendor's black-box number — a more principled `ThresholdRecord`
   candidate than a single reading of any kind.

None of this is built this pass — flagged as a concrete, citation-grounded
direction for a future build, at the same `IDEAS.md`-adjacent level as
this repo's other forward-looking library notes, not a commitment.

## Vendor rolling estimators (brief aside — not this file's focus)

`Coach judgment:` (practitioner-vendor documentation, not
`[EVIDENCE]`/`[ADAPTED]`) — TrainerRoad's own first-party documentation (confirmed by
direct fetch this session, not peer-reviewed or independently audited)
distinguishes **AI FTP Detection** (analyzes completed workouts) from
**AI FTP Prediction** (forward-projects from the *planned* calendar, and
states directly that swapping a scheduled hard workout for an easier one
changes the predicted number — "Introducing TrainerRoad AI"). Detection
itself recalibrates around a stated "level 3" completed-threshold-workout
baseline (below level 3: FTP decrease), per "A Data Driven Explanation of
the Latest Updates to AI FTP Detection," independently corroborated by a
founder forum quote — a real, company-documented mechanism by which
completing an easier session than scheduled could plausibly register as
a lower detected number, independent of real fitness change. No published
accuracy/error margin exists for either feature, and real user-reported
single-recalibration swings run -4.3% to -9.3% (TrainerRoad forum) —
**larger than** the 282W→277W (-1.8%) swing that prompted this question,
so that swing is not anomalously large by the platform's own users'
reports either way. **Bottom line for this aside:** a workout-type-
sensitive mechanism in this specific rolling estimator is real and
company-documented, not merely inferred — plausible support for a taper/
opener explanation — but this is one vendor's own unaudited account, and
Q2 above is the more defensible, citation-dense answer to lean on.

## Practical guidance for this engine

This engine's existing `ThresholdRecord` design (`models.py`) already
gets the core posture right, and Q1/Q2 ground rather than redesign it.
`ThresholdRecord.source` already has a dedicated `"app_estimate"` value
whose schema description (`backend/app/tools.py`'s `record_threshold_test`)
names a platform's algorithmic estimate as "real signal, but modelled,
not directly tested" — and the engine deliberately never auto-picks a
"current" value from the `ThresholdRecord` history; a human/coach judges
trustworthiness. Given Q1 (no validated link from load history to real
FTP change) and Q2 (real, multi-effort, athlete-own-data signals exist
and are more principled than any single reading), the defensible ranking
is: a `field_test`/`ramp_test`/`race_file` reading outweighs a single
`app_estimate` reading, and — not yet built, per the IDEA-capture section
above — a trend across the athlete's own repeated real efforts or
decoupling readings would, if built, outweigh either single-reading type,
being the only one of the three grounded in multiple convergent real data
points rather than one moment. `Coach judgment:` treat a lone `app_estimate`
swing of a few percent (per Q2's ~4% real-world noise floor) as expected
noise, not grounds to update `Athlete.ftp_watts` via `update_athlete_profile`,
and weight it further down when it coincides with a known session-type
change (taper, opener, missed hard day) rather than a change in
demonstrated output on a genuinely comparable session. **Test:** if an
athlete's `app_estimate` readings and later `field_test`/`ramp_test`
readings for the same period routinely diverge in a *consistent
direction*, that is this athlete's own individual-variation signal,
worth weighing more than the general caution above — same "prefer the
athlete's own real, recent data" posture `24`'s ramp-test and `28`'s
2x20-test sections already take toward their own formulas.

## What's NOT well-established

- No literature — cycling, swimming, or any endurance sport — validates a
  model predicting FTP/threshold-power *change* from a training-load
  history with real outcome data (Q1); Kontro et al. (2026) is the
  closest attempt and is unvalidated by its own authors' admission.
- No source found this session states an exact "how many repeated real
  (non-lab) efforts, over how many weeks" threshold for trusting a
  matched-effort power trend as real signal — Triska et al. (2017)'s
  2.6-4.1% CV is a lab-controlled, genuinely-maximal-effort floor, not a
  real-training-data number; the multiplier applied to it for real,
  uncontrolled training sessions is `Coach judgment:`.
- The Barsumyan et al. (2025) cross-session decoupling-trend evidence is
  real but preliminary (n=20, one protocol, one intensity) — promising,
  not settled.
- TrainerRoad's "threshold level" mechanism is the company's own
  first-party, unaudited account — not independently verified, and not a
  general claim about other vendors' algorithms (no comparable published
  technical account was found this session for a competing platform).
- Nothing in the IDEA-capture section above is built; it is a concrete,
  citation-grounded direction, not a shipped feature.

## Implementation history

Research-only pass (no engine code, no `context.py` sport-scope wiring —
same deferred state as `24`/`25`/`28`). No `ThresholdRecord` design
change: this file grounds the existing `source="app_estimate"` posture
and sketches (IDEA-capture only) a future cross-session analyzer.
