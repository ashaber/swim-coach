# Altitude effects on cycling power (elevation-aware compliance)

See `00-conventions.md` for the tagging scheme and `reference_list.md` for
full citations.

**Sport scope: `bike`.** Grounds `engine/swim_coach/interval_analysis.py`'s
altitude-context signal only — never surfaced to a swim-only athlete, same
scoping posture as `26-activity-stream-interval-analysis.md` and
`28-bike-ftp-test-protocols.md`.

## The real request this grounds

Andrew asked for the stream analyzer to be "aware of elevation change" in
two distinct senses: (1) a ride that climbs a lot **within itself** (e.g.
2500ft of gain) — does that sustained climbing explain a below-target power
reading; and (2) a ride performed **above the athlete's usual/home
elevation** (e.g. 2500ft higher than baseline) — does reduced air pressure
there explain it. These are physiologically different questions and this
file treats them separately, honestly, rather than forcing one correction
factor to cover both.

**A load-bearing premise up front: cycling power is grade-independent.** A
power meter reads the same watts whether the road is flat or climbing —
what changes with grade is the resulting speed, not the wattage a rider
can sustain. So question (1) is NOT "correct the power number for the
grade" the way pace-on-a-hill would need correcting; question (2) is a real
physiological ceiling on sustainable power itself, unrelated to grade.

## Question 2: absolute elevation vs. the athlete's baseline (real, buildable)

This is the physiologically well-established half. Reduced barometric
pressure reduces inspired oxygen partial pressure, which measurably lowers
VO2max and sustainable aerobic power output at altitude. Three real sources,
verified this session, converge on the shape of the effect but not exactly
on where it starts — stated honestly below rather than picking one and
hiding the disagreement.

**[EVIDENCE: cycling]** `Garvican-Lewis L.A., Clark B., Martin D.T.,
Schumacher Y.O., McDonald W., Stephens B., et al. (2015)`, "Impact of
Altitude on Power Output during Cycling Stage Racing" — *PLoS ONE*,
10(12):e0143028 — the best population match available: real elite road
cyclists' own power-meter data from actual stage races (plus a lab
power-profile arm), not a simulated-altitude estimate. Against a ~600m
near-sea-level baseline: mean power was **not significantly different**
for rides below 2000m absolute altitude; maximal mean power for **4- and
10-minute efforts** (240s/600s MMP — the duration band this analyzer's own
`EFFORT_MIN_S`-gated "sustained effort" detection targets) was already
**4.1% / 7.8% lower** in the 1000-2000m absolute band; mean power fell
**~12.4%** at 2000-3000m and **~12.3%** above 3000m. The paper's own
stated summary dose-response: **"a decline in MMP for 240 and 600 s of
~6% per 1000 m above sea-level."** Confidence: high for the cycling
population/modality match; the riders are elite professionals, which this
athlete is not — his own sensitivity may differ. **Test:** if this
athlete's own elevated-ride sustained efforts consistently under- or
over-shoot the ~6%/1000m estimate relative to his near-baseline
performance, recalibrate against his own logged data rather than the
elite-cyclist figure.

**[ADAPTED: general-endurance] Confidence: medium.** `Fulco C.S., Rock
P.B., Cymerman A. (1998)`, "Maximal and submaximal exercise performance at
altitude" — *Aviation, Space, and Environmental Medicine*, 69(8):793-801
(citation verified via PubMed, PMID 9715971). A cross-sport review of four
decades of altitude research and competitive events: VO2max is reduced in
"smaller increments" starting around 580m, then roughly **1% per 100m
above 1500m** (~10%/1000m); submaximal performance decrements can appear
as low as ~700m for events lasting 20+ minutes. Foundational, widely-cited
review-level synthesis, not cycling-specific data — the broader,
cross-discipline corroboration that *some* real threshold-shaped effect
exists well below 3000m, not just above it. **Test:** the same as above —
prefer this athlete's own data once enough elevated rides accumulate.

**[ADAPTED: running] Confidence: medium.** `Wehrlin J.P., Hallén J.
(2006)`, "Linear decrease in VO2max and performance with increasing
altitude in endurance athletes" — *European Journal of Applied Physiology*,
96(4):404-412. Eight elite endurance-trained runners in a hypobaric
chamber, simulated altitudes 300-2800m: VO2max declined **linearly, ~6.3%
per 1000m** (range 4.6-7.5%) with no clear low-altitude floor in this small
elite sample — i.e. this study found a *more aggressive*, threshold-free
version of the effect than Fulco's review or Garvican-Lewis's own cycling
data. Small n (8), a different modality (running) and protocol (simulated
hypobaric chamber, not real riding). Included honestly as the source that
disagrees with a clean "negligible below ~1500-2000m" story — highly
trained endurance athletes may be more altitude-sensitive than the general
threshold framing suggests. **Not adopted as the engine's rate** (the
cycling-native Garvican-Lewis figure is preferred for a cycling athlete),
but the disagreement is real and stated here rather than smoothed over.
**Test:** if this athlete's own elevated-ride data tracks closer to this
more-aggressive linear figure than to Garvican-Lewis's cycling-specific
one, that is itself useful individual-variation signal — revisit which
source's rate the engine uses.

### What the engine actually does with this

**Original build (2026-09-13):** `interval_analysis` had no "home/baseline
elevation" concept on `Athlete`, and adding one looked like an
athlete-onboarding change out of scope for that build. The analyzer instead
derived a **session-relative baseline** — a ride's own minimum `altitude_m`
sample — reasoning that a ride typically starts near wherever the athlete
actually is that day.

**Re-anchored 2026-09-14, after real use exposed the gap.** Andrew reviewed
a real ride (2026-08-26/27) where he was traveling: the ride's own baseline
(its lowest sample, 1835.2m/6021ft) was itself already ~1012m above his
real home elevation (823m/2700ft) — but the ride-relative-only heuristic
compared each effort against that same elevated in-ride baseline, so
nothing ever crossed the flag threshold. The ride-relative heuristic isn't
wrong on its own terms (it correctly describes "how much higher did this
effort climb than where the ride itself started"), but it cannot answer
the question that actually matters for compliance scoring: **was this ride
performed somewhere higher than the athlete normally trains at all**,
regardless of how much the ride climbed once it got there. A ride that
starts already 1000m above home should be flaggable from its very first
sample, not just for climbing further above wherever it happened to start.

**`Athlete.home_elevation_m`** (added this pass) fixes this: an explicit,
human-set field, the same posture this engine already gives `ftp_watts`,
`lthr_bpm`, `css_pace_s_per_100m`, and `ThresholdRecord` — a real,
athlete-specific reference point the athlete or coach sets, never a value
the engine invents or infers. When set, it replaces the ride-relative
baseline as the anchor every effort's altitude gain is measured against.
When unset (still true for every existing athlete profile today), the
analyzer falls back to the original session-relative heuristic exactly as
before — a pure regression for every athlete/ride without it configured.
`WorkoutIntervals.baseline_altitude_source` records which of the two
applied to a given ride, so a coach can tell at a glance whether a flag
(or its absence) reflects the athlete's real home elevation or just
wherever a particular ride happened to start.

**Considered and rejected: an auto-inferred rolling baseline.** Rather than
requiring the athlete to set `home_elevation_m` by hand, the engine could
instead average recent ride-start elevations over, say, 2-3 weeks and treat
that rolling figure as the baseline automatically. This was considered and
explicitly rejected. Partial altitude acclimatization over multiple weeks
at elevation is real physiology (the dose-response curves above are all
acute-exposure figures; sustained residence at moderate altitude does
produce some real, if slow and incomplete, adaptation) — but a rolling
average of ride-start elevations cannot distinguish "genuinely living and
training at 5000ft for three weeks, partially adapted" from "just traveling
there this week, not adapted at all." Averaging the two together would
silently launder a travel week into a new "normal" baseline exactly when
the athlete most needs the flag to fire — the Aug 26/27 scenario this
re-anchor fixes would, after a few more elevated days, eventually
re-poison its own rolling average and go silent again. This also breaks
the engine's own standing convention, restated here deliberately: **a
human sets threshold-type values; the engine never auto-infers one from
recent data** (`ftp_watts`/`lthr_bpm`/`css_pace_s_per_100m` all work this
way, and `ThresholdRecord`'s own docstring says so explicitly). A future
session should not re-propose an auto-inferred rolling baseline without
re-deriving why it was rejected here.

**Known limitation, stated plainly (applies to whichever baseline is
active):** the cited dose-response curves are all anchored to *absolute*
sea-level altitude, not to "however high the athlete's normal riding
already is." An athlete whose baseline (home-elevation-set or ride-relative)
is itself at moderate elevation carries some real acclimatization the
literature doesn't cleanly separate out. This analyzer does not attempt to
model that separately — it applies the elevation gained above the resolved
baseline through the same dose-response line, which is the correct question
for Andrew's own framing ("2500ft above home elevation") and is a reasonable
approximation specifically because this athlete's own home elevation
(823m/2700ft) sits well below the altitude range where these studies'
curves are best characterized. It would not be a safe approximation for an
athlete whose home base is itself already at, say, 2500m.

**Chosen constants** (both `Coach judgment:` for the exact cutoffs/values,
grounded in the evidence above for the shape):
- **Flag threshold: 1000m (~3281ft) above the resolved baseline.**
  Garvican-Lewis's own bands are anchored to their ~600m baseline; their
  1000-2000m absolute band (roughly 400-1400m *relative* to that baseline)
  is where sustained-effort power first measurably drops. 1000m sits
  inside that already-affected zone, on the conservative side — deliberately
  erring toward fewer false positives, same "flag real signal, don't cry
  wolf" posture `GRADE_DROP_FLAG` already uses in this file's sibling
  terrain-confound logic. Below this, the analyzer stays silent (no context
  note at all) rather than noting a trivial effect on every ride with any
  hill in it.
- **Rate: ~6% power decrement per 1000m above that threshold**, taken
  directly from Garvican-Lewis's own stated MMP240/600 dose-response — the
  duration band that matches this analyzer's own sustained-effort scope.

The signal is a **flag, never a silent override** — same posture as
`terrain_flag`/`evaluate_week_realism` elsewhere in this codebase. It never
adjusts `pct_of_target`, `avg_w`, or `verdict`; it surfaces a labelled,
computed estimate (e.g. "~9.5% less sustainable power expected at this
elevation") alongside the raw numbers for the coach to weigh.

**Elevation-adjusted target comparison.** Andrew's real question, stated
precisely: during effort/interval work on a climb that gains toward or past
the flag threshold above a meaningful baseline, is the raw target itself
context-blind to how much harder that same wattage is getting as the climb
progresses — and if a rep reads below raw target, would it have cleared an
elevation-adjusted target? When both a target and an altitude flag exist
for an effort, `IntervalEffort` now also carries `altitude_decrement_pct`
(the same number embedded in the note, exposed as a plain float),
`altitude_adjusted_target_w` (`target_w * (1 - altitude_decrement_pct /
100)`), and `cleared_altitude_adjusted_target` (`avg_w >= altitude_adjusted_
target_w`). `pct_of_target`/`avg_vs_target_w`/`verdict` are computed against
the RAW target exactly as before — these are additional, clearly-labeled
fields, not a replacement.

**Real-numbers check (2026-08-26/27 ride, not committed as a fixture —
personal ride data, same convention as `library/26`'s validation rides):**
home elevation 823m, ride bottom 1835.2m (1012.2m above home, 6.07%
decrement, effective FTP ≈259.2W off a 276W FTP), ride top 2406.6m (1583.6m
above home, 9.50% decrement, effective FTP ≈249.8W). Both real detected
efforts' gain above the ride's OWN baseline (308.5m, 542.0m) stayed under
the 1000m flag threshold — which is exactly why the original ride-relative
heuristic correctly produced no flag for this ride and, at the same time,
completely missed that the whole ride sat >1000m above where this athlete
actually lives. With `home_elevation_m=823` supplied, both efforts now
clear the threshold from their very first sample.

## Question 1: sustained climbing within a ride (no distinct effect found)

Because cycling power is grade-independent, "does a long climb reduce how
many watts a rider CAN produce" is not, by itself, a real question distinct
from ordinary fatigue and altitude (covered above). What IS real and
well-documented is that sustained climbing tends to be ridden at **lower
cadence and higher torque per pedal stroke** than flat riding at the same
power, and that low-cadence/high-torque work recruits muscle differently
and may fatigue the legs on a different timeline than high-cadence spinning
— a genuine biomechanical/pacing difference, but not a proven, separately
quantifiable discount on sustainable power itself.

**[EVIDENCE: cycling] Confidence: medium.** `Javaloyes A.,
Sánchez-Jiménez J.L., Peña-González I., Moya-Ramón M., Mateo-March M.
(2025)`, "The Role of Cadence and Torque in Fatigue-Related Power Output
Decline in Cycling's Grand Monuments" — *Sports (Basel)*, 13(11):406.
64 professional male cyclists' real race-file data (power/cadence/torque)
across the five cycling Monuments, comparing fresh vs. fatigued states
(post 30-60 kJ/kg accumulated work). Found top-finishing riders hold power
and torque more durably than mid-pack riders as fatigue accumulates, with
cadence/torque strategy shifting as riders fatigue — but the paper studies
**whole-race durability**, not an isolated climbing-vs-flat power
comparison, and proposes **no numeric correction factor**. It attributes
the durability difference to metabolic/physiological training status, not
a biomechanical climbing-specific power ceiling. Checked specifically for
a distinct, quantifiable "climbing tax" on power — none exists in this
source or any other found this session.

**Honest conclusion:** no real, independently-citable "sustained-climbing
power penalty" distinct from ordinary within-effort fatigue was found.
What this codebase already has — `FADE_FLAG_PCT`'s within-interval fade
detection (`Barsumyan A., Soost C., Burchard R. (2025)`, already grounding
`26-activity-stream-interval-analysis.md`) and `_terrain_flag`'s
grade-delta / HR-drift decision tree — already covers "a long climb makes
an effort harder to hold evenly" from the pacing/fatigue side. **No new
correction factor was built for question 1.** If a below-target effort
happens to occur on a ride that also gains a lot of elevation overall, the
existing terrain-confound machinery (not a new one) is the right tool, and
the question-2 altitude-context note (if the ride also climbed high enough
in absolute terms) covers the other real explanation. Forcing a third,
uncited "climbing tax" number into the code would have been exactly the
kind of dressed-up guess this project's evidence discipline exists to
prevent.

## Implementation

Grounds `interval_analysis.py`'s `ALTITUDE_FLAG_THRESHOLD_M` and
`ALTITUDE_POWER_DECREMENT_PCT_PER_1000M` constants; `_effective_baseline_
altitude_m` (home-elevation-first, ride-relative-fallback resolution) and
`_ride_baseline_altitude_m` (the fallback heuristic itself); and the
`altitude_m` / `altitude_gain_m` / `altitude_context` /
`altitude_decrement_pct` / `altitude_adjusted_target_w` /
`cleared_altitude_adjusted_target` fields on `models.IntervalEffort`, plus
`baseline_altitude_m` / `baseline_altitude_source` on `models.
WorkoutIntervals` and `Athlete.home_elevation_m` itself. See those
docstrings for the exact computation; this file is the evidence source,
not a second copy of the algorithm.
