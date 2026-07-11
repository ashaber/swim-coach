# Recovery & HRV

Grounds `engine/swim_coach/adapt.py`'s post-milestone recovery window
(`RECOVERY_DAYS_AFTER_MILESTONE_MIN/MAX = 3/5`) with recovery-science
support — `06-long-swim-progression.md` stays the constant's primary
citation home; this file adds *why* 3-5 days is defensible, not just where
the number comes from. It also grounds `load.py`/`adapt.py`'s subjective
`wellness_composite` (`WELLNESS_RED_THRESHOLD = 2.0` over
`WELLNESS_WINDOW_DAYS = 7`) as a legitimate primary monitoring signal, not
a substitute for objective/HRV data, and lays groundwork for HRV-guided
daily adjustment and a between-events mini-taper — neither implemented
yet. See `00-conventions.md` for the tagging scheme and `reference_list.md`
for citations.

**Concrete trigger for this file:** Renee's actual W28/W29 (per
`athletes/renee/notes/decisions.md`) — a ~5-hour Lucky Peak open-water swim
with kayak support on Thu 7/9, followed by the Bear Lake Monster 10K
(B-priority, kayak-supported) on Sat 7/18, roughly nine days later — the
real scenario this file is written against, not a hypothetical.

## Recovery windows between hard efforts (5-10 days)

**Coach judgment**, informed by `Driller & Leabeater (2023)`'s narrative
review, which classifies recovery modalities by evidence strength and
concludes that **sleep, nutrition, and periodization are the evidence-backed
foundation** — newer recovery devices (foam rolling, cryotherapy,
photobiomodulation) lack strong support and shouldn't be prioritized over
those fundamentals. `Braun-Trocchio et al. (2022)`'s 264-athlete survey
across 11 endurance sports is consistent: hydration, nutrition, sleep, and
rest are what practitioners actually use and trust most — useful as color
for what to prioritize, not as efficacy evidence.

No engine constant exists yet for a fixed "short-turnaround between two
hard efforts" window — `RECOVERY_DAYS_AFTER_MILESTONE_MIN/MAX` in `adapt.py`
is tuned for the long-swim ladder's milestone-then-build pattern
(`06-long-swim-progression.md`), not a B-event-to-A-event gap. A 9-day gap
between two open-water efforts is a candidate for a future `MINI_TAPER_*`
constant (see the mini-taper section below), not a direct application of
the milestone-recovery window.

## Nutrition for the refeed window

**[ADAPTED: cycling] Confidence: high.** `Ivy et al. (1988)`: 12 cyclists,
immediate (vs. 2h-delayed) carbohydrate ingestion (2 g/kg) roughly doubled
glycogen resynthesis rate over the first 4h. `Burke et al. (2011)`'s review
backs ~1.0-1.2 g/kg/h carbohydrate in the first 4h post-exercise, with
intake highest-priority in the first 1-2h. **Test:** on the day after a long
swim/kayak effort, confirm carbohydrate intake started within ~30-60 min
rather than delayed, and check whether next-day sRPE for an easy session is
lower (better) on early-refeed days vs. delayed-refeed days in Renee's own
log history.

**[ADAPTED: running] Confidence: high.** `Kato et al. (2016)` — six
endurance-trained runners, indicator amino acid oxidation method — derived
an Estimated Average Requirement of **1.65 g/kg/day** protein and a
Recommended (safe) intake of **1.83 g/kg/day**, well above the general
population's 0.8 g/kg/day RDA. This is a whole-day target, not a
post-exercise-window dose; no engine constant currently cites a protein
g/kg figure to check this against. **Test:** compare self-reported recovery/
soreness on days protein intake sits above vs. below ~1.6 g/kg in Renee's
own logs — exploratory, not powered, but checkable.

**[ADAPTED: general-endurance] Confidence: medium-high.** `Koopman et al.
(2004)`: 8 endurance athletes doing 6h of mixed-modality exercise at 50%
VO2max; carbohydrate+protein co-ingestion (0.7 g/kg/h CHO + 0.25 g/kg/h
protein) every 30 min kept whole-body protein balance positive/less-negative
vs. carbohydrate-only, which stayed negative throughout. Directly relevant
to a combined long-swim-plus-kayak day like 7/9: offering a carb+protein
feed *during* the effort, not just after, is the practical takeaway. This
sits at the edge of this file's scope — full during-exercise fueling belongs
in the not-yet-authored `08-*` ultra-feeding file; it's included here only
because it bears on the *recovery* outcome of the same day. **Test:** after
long (>3h) efforts where the feed included protein alongside carbohydrate,
compare next-day wellness-composite/soreness recovery against carbohydrate-
only efforts of similar duration in Renee's own logs — if enough paired
cases show no difference, drop the co-ingestion emphasis from her
during-effort fueling.

## Sleep: the highest-leverage lever available in a short window

**[ADAPTED: general-endurance] Confidence: high** for the lead citation.
`Bonnar et al. (2018)`'s systematic review of sleep interventions in
athletes found sleep **extension** the most consistently beneficial
intervention for performance/recovery outcomes, with napping and sleep-
hygiene education producing mixed results by comparison. `Mah et al.
(2011)` is the illustrative underlying study (medium confidence alone —
single small-n team-sport study, not endurance-specific): 11 basketball
players extending sleep toward ~10h/night for 5-7 weeks saw improved sprint
speed, shooting accuracy, reaction time, and mood.

`load.py`'s `wellness_composite` already includes a sleep-quality term
(equal-weighted with stress/soreness/motivation, per `03-periodization.md`)
— this section documents *why* sleep earns that weight, without adding a
sleep-duration threshold the engine doesn't model.
**Test:** in a short-turnaround window, if sleep can be extended toward
8.5-9.5h/night, check whether Renee's wellness-composite energy/soreness
sub-scores trend upward relative to her own recent baseline.

## Modality tier list: comfort vs. performance-recovery

**[ADAPTED: general-endurance] Confidence: medium-high.** `Moore et al.
(2022)`'s meta-analysis found cold-water immersion (CWI) improved muscular-
power recovery, perceived soreness, and creatine-kinase markers after
eccentric/high-intensity exercise — but was **not effective** at improving
recovery of *endurance* performance specifically, at either 24h or 48h
post-exercise. For an athlete whose limiter nine days out is aerobic
capacity, not power, this matters: CWI is a soreness/comfort tool here,
not a proven endurance-recovery accelerant. `Hill et al. (2014)`'s
meta-analysis on compression garments found a similar pattern —
small-to-moderate soreness/strength benefit, weaker/inconsistent effect on
objective performance (Confidence: low-medium — verified by consistent
secondary citation listings, not an individually fetched full-text read).

**Practical framing, not a rule:** offer CWI/compression as comfort-tier
recovery support after 7/9, but don't treat either as a substitute for
sleep or refeeding, and don't expect either to move endurance readiness
for 7/18. **Test:** if CWI is used, track whether Renee's perceived-
soreness wellness sub-score improves without a corresponding change in
matched-effort session pace/RPE — if pace/RPE doesn't move with CWI use,
that's consistent with Moore et al.'s endurance-null finding and supports
treating it as comfort-only going forward.

## HRV- and wellness-guided load adjustment

**[ADAPTED: general-endurance/multi-sport] Confidence: high.** `Saw, Main
& Gastin (2016)`'s 56-study systematic review found subjective and
objective training-response measures generally didn't correlate with each
other, and **subjective self-report showed greater sensitivity and
consistency** than the objective measures tested. This is the strongest
citation in this file for an *already-implemented* engine constant: it
directly supports treating `wellness_composite` (`WELLNESS_RED_THRESHOLD =
2.0` over `WELLNESS_WINDOW_DAYS = 7` in `adapt.py`) as a legitimate primary
signal, not a fallback for when HRV/objective data is unavailable. **Test:**
on days both exist, check whether Renee's wellness-composite tracks (or
leads) her Oura HRV/RHR trend; if the composite consistently diverges from
the objective signals over a training block, stop treating it as the
primary go/no-go signal and re-weight toward the device data.

**[ADAPTED: running/cycling] Confidence: medium.** Three independent-lab
RCTs converge on the same mechanism: `Kiviniemi et al. (2007)` (26 males, 4
weeks) found HRV-guided training — hard only on stable/rising-HRV mornings,
easy/rest below a rolling threshold — improved max running velocity more
than a fixed program; `Vesterinen et al. (2016)` (40 runners, 8 weeks) and
`Javaloyes et al. (2020)` (20 cyclists, 8 weeks) each found the same
directional result in their own populations. None tested an 8-10-day
single-athlete window — all are multi-week blocks in runners/cyclists —
so the mechanism is well-evidenced and cheap to apply, but the *exact
scenario* (a short taper-in window before a B-then-A event pair) wasn't
tested.

A second, independent reason this stays **medium, not high**: all three
RCTs measured HRV each **morning**, post-waking, via an orthostatic
protocol — not **overnight**, the way Oura measures. `Nuuttila et al.
(2024)` directly compared both protocols in the same runners under a
training-load increase and found morning and nocturnal HRV **diverge in
their response to training**, despite correlating at baseline; the
overnight-style signal tracked the load increase and subsequent 3000m
performance change *better* than the morning protocol did — reassuring for
the underlying mechanism (hard day only on stable/rising HRV plausibly
transfers to an overnight-measuring device), but the specific thresholds
these three RCTs calibrated — e.g. Kiviniemi's "1 SD below a rolling
10-day baseline" — were never validated on overnight data and shouldn't be
imported into an engine rule as-is. **Test:** once Renee's Oura
rMSSD accumulates a rolling baseline, check whether a "hard day only if
last night's rMSSD sits at/above a trailing 7-10-day mean" rule flags the
same easy/rest days her `wellness_composite` already flags — frequent
disagreement means the morning-protocol threshold doesn't transfer as-is
and needs recalibrating from her own overnight baseline, not imported from
these three studies' numbers directly.

**Athlete context, stated plainly:** Renee's profile (`athletes/renee/
profile.yaml`) lists `hrv_source: Oura ring` — the device exists — but no
wellness log entry populates the `Wellness` model's optional `hrv` field
(`engine/swim_coach/models.py`). This section is grounding for a rule not
yet implemented, not a description of an active constant. **Test:** once HRV values start
appearing in daily check-ins, apply the same "hard day only if HRV stable-
or-rising vs. the trailing baseline, else easy/rest" rule as a layer on top
of (not a replacement for) `wellness_composite`, and check whether that
layered signal catches anything the subjective composite alone misses over
a few weeks — if it never disagrees with wellness_composite, that's a
signal the added complexity isn't earning its keep for this athlete.

## Oura device trust: how much to believe each signal

Before any Oura-derived number is trusted enough to influence coaching,
here's how much each signal should be believed, per `reference_list.md`'s
"Wearables & device validity" sources.

**Resting heart rate — high confidence.** `[ADAPTED: general-endurance]
Confidence: high.` `Cao et al. (2022)` (n=35, chest-ECG reference) and
`Liang et al. (2024)` (n=114, current-generation ring) both found
whole-night-average HR correlating with ECG at r≈0.99; `Dial et al.
(2025)`'s small independent multi-device comparison (13 adults, 536
nights) found Oura the most accurate RHR tracker of the five tested,
ahead of WHOOP/Garmin/Polar. **Test:** if the engine or coach ever flags
an RHR trend as elevated, treat it as a real physiological signal first.

**HRV nightly rMSSD — medium-high confidence, as a multi-night trend
only.** `[ADAPTED: general-endurance] Confidence: medium-high.` The same
two studies found whole-night rMSSD correlating with chest ECG at
r≈0.92-0.99 (Cao et al. 2022, n=35; Liang et al. 2024, n=114) — strong
enough to treat a *sustained* rMSSD trend as real. Two caveats keep this
below "high": accuracy degrades in short/noisy windows and older adults
(Liang et al. found >10% error at the 5-minute level in over half their
45-68y subgroup), and the data-quality filter that preserves accuracy
silently **drops ~30-35% of nights**. **Test:** don't act on a single
night's dip — check it holds across 3+ consecutive nights, and discount
any night the app flags as low signal quality.

**Sleep staging — medium for total sleep time, low-medium for stage
detail.** `[ADAPTED: general-endurance] Confidence: low-medium.`
`de Zambotti et al. (2017)` found total sleep time within a clinically
acceptable band on 88% of nights, but deep sleep underestimated and REM
overestimated — on **first-generation** ring hardware. A newer Gen3 study
(`Svensson et al. 2024`) reports "good agreement," but its exact numbers
were paywalled and couldn't be independently confirmed — treat that as
unverified pending full-text access, not a settled figure. **Test:** trust total-sleep-time for trend
purposes; don't base a coaching call on a specific light/deep/REM split
until the Gen3 numbers are confirmed.

**Readiness score (0-100 composite) — low confidence; must not drive plan
changes.** `[ADAPTED: general-endurance] Confidence: low.` `Doherty et al.
(2025)`'s cross-brand review of 14 composite scores across 10 wearable
manufacturers (Oura's Readiness/Resilience included) found none publish
their scoring weights, and no reviewed composite score had independent
peer-reviewed validation. **Coach judgment:** the engine and `/coach`
should read the *raw* HRV/RHR/sleep trend, never the blended 0-100
Readiness number, when informing a plan decision. **Test:** if
Readiness and the raw trend ever disagree, trust the raw trend — that's a
reason to distrust Readiness further, not the reverse.

**Employee-authored sources, flagged distinctly:** `Kinnunen et al.
(2020)` (Oura's then-Chief Scientific Officer; accuracy numbers could not
be independently confirmed — paywalled) and `Thigpen, Patel & Zhang
(2025)` (all three authors Oura employees; self-reported reference
standard) are manufacturer-affiliated — real and peer-reviewed, but
lower-trust-tier than the independent studies above; neither is
load-bearing for the ratings above.

**Open gap:** no Oura-specific validation exists for alcohol use,
arrhythmia, or illness — a real gap, not a resolved low-risk.

## Swimming-specific recovery-load monitoring

**[EVIDENCE: swim] Confidence: high** for population/question match (n=5 is
small). `Collette et al. (2018)` monitored 5 elite female swimmers over 17
weeks using session-RPE load metrics and the Acute Recovery and Stress
Scale: session-RPE (particularly a distance-weighted variant) tracked
recovery-stress state more strongly than acute:chronic workload ratio
(ACWR), and individual baselines outperformed group-level thresholds. This
is swim-specific corroboration for a claim `03-periodization.md` sources
only from the running Garmin-RunSafe cohort — cross-reference that file's
ACWR-is-a-weak-predictor section rather than duplicating it here. Practical
takeaway: an individualized sRPE/wellness read on Renee's recovery-stress
state between 7/9 and 7/18 is better-evidenced in swimmers than leaning on
`adapt.py`'s ACWR red-flag threshold (`LOAD_RATIO_RED_THRESHOLD = 1.4`)
alone.

## Mini-taper for a B-event ~1 week out

**[ADAPTED: general-endurance] Confidence: medium-high.** `Mujika &
Padilla (2003)`'s foundational taper review recommends maintaining
intensity while cutting volume 60-90% and frequency by no more than ~20%,
with progressive non-linear tapers outperforming step tapers.
`Wang et al. (2023)`'s 14-study meta-analysis found ≤21-day tapers with
41-60% volume reduction (intensity/frequency roughly held) generally
effective, and — the closest finding to Renee's actual situation — **tapers
of ≤7 days still produced a positive effect**, though the 8-14-day band
showed the largest gains overall.

Applied to the 7/9-to-7/18 window: this supports treating W29 as a short
taper-in — volume down, intensity/frequency held close to normal — rather
than a normal training week, which is exactly what `athletes/renee/notes/
decisions.md` already records for W29 (~17,500m, a Greece dress rehearsal,
not an all-out effort). **State the gap honestly:** neither source tested
a "B-event, then a second hard event ~9 days later" design — both study
tapering into a single peak event. No direct evidence exists for recovery
between two ultra-distance open-water swims (or a swim-plus-kayak day and
a swim) roughly a week apart; this is a coach-judgment gap, not a solved
problem. **Test:** track whether Renee's post-Bear-Lake perceived freshness
/ RPE-at-pace differs from a matched no-taper week in her history, if one
exists, as a weak local check on whether this treatment earns its keep for
her specifically.

The clearest candidate here for a future engine constant: a `MINI_TAPER_*`
rule distinct from `03-periodization.md`'s macro-block taper
(`TAPER_WEEKS_LONG/SHORT`, itself citation-debt-flagged), since 8-10 days
is shorter than any macro taper the engine models. **Not implemented
today**

## What's still a gap

- No swim-specific or kayak-cross-fatigue evidence exists for the exact
  7/9-to-7/18 scenario; every citation above is adjacent, not direct.
- No engine constant yet for post-exercise carbohydrate/protein timing,
  a short-turnaround recovery window distinct from milestone recovery, or
  a mini-taper volume cut — this file documents the evidence base for
  adding one, not an implemented rule.
- HRV-guided adjustment is fully forward-looking: the device exists in
  Renee's profile, but no HRV data has been logged yet. That's narrower
  than "can the device be trusted" — accuracy evidence exists (see "Oura
  device trust" above, including the alcohol/arrhythmia/illness gap) — the
  gap is that no rolling baseline exists on her own data yet.
