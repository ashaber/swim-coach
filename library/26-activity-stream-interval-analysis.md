# Activity-stream interval analyzer (detection, quality, sub-structure)

See `00-conventions.md` for the tagging scheme and `reference_list.md` for
full citations. Split out of `11-workout-analytics.md` to stay under that
file's word-count cap (`00-conventions.md`'s "topic files stay <= ~2,500
words" rule), matching this repo's precedent of splitting a topic rather
than trimming it (`24-cycling-periodization-intervals.md` split out of
`23-cycling-training.md`; `15-tiered-session-load.md` out of
`03-periodization.md`).

**Sport scope: `bike`.** `engine/swim_coach/interval_analysis.analyze`
returns `None` for every non-`bike` sport, so nothing here is ever surfaced
to a swim-only athlete. `11-workout-analytics.md` still grounds
`analytics.py`'s own cross-sport constants (cardiac drift, splits, pauses,
SWOLF); this file grounds only `interval_analysis.py`.

**Provenance note:** most thresholds below are engineering defaults / coach
judgment tuned against a real validation pass over four of this athlete's
own cycling `.fit` rides (a 30/30 VO2 ERG session, a gravel step set, a
feel-ridden trail over/under, a steady 2x12) -- the exact rides are her
personal data, not library content, and are not reproduced here; what is
recorded is which constant each finding drove and to what value. Two
constants (`IN_BAND_FRAC`, `FADE_FLAG_PCT`) additionally carry an
ADAPTED-cycling tag with its own Confidence and Test line, in the
"Interval quality vs. target" section below.

## Deterministic activity-stream interval analyzer

Grounds `engine/swim_coach/interval_analysis.py` (detect sustained efforts
in a ride, assess each vs a target, flag terrain confounds; no LLM tokens
spent on the stream). Most thresholds are engineering defaults / coach
judgment chosen against this athlete's real cycling `.fit` data; two carry
an ADAPTED (cycling) tag with its own Confidence/Test, below.

### Detection thresholds (coach judgment)

**Coach judgment:** `EFFORT_MIN_S = 120.0` (shortest span counted as a
deliberate effort — structured cycling work bouts are minutes, not seconds;
cf. `24-cycling-periodization-intervals.md`), `EFFORT_MERGE_GAP_S = 25.0`
(a shorter sub-threshold dip — a corner, a freewheel over a crest — doesn't
end the effort), `EFFORT_DYNAMIC_FRAC = 0.62` (with no supplied target the
threshold sits this far from the ride's 40th- toward its 85th-percentile
working power), `COASTING_FLOOR_W = 20.0` (at/below this the rider is
freewheeling), `TARGET_GATE_FRAC = 0.80` (with a target supplied, "in an
effort" means >= 80% of it — 195W against a 239W target is still an
attempt). All engineering defaults tuned so the scan ignores steady
endurance riding but catches a threshold interval; none is a cited value.

### Interval quality vs. target

**[ADAPTED: cycling] Confidence: medium.** `IN_BAND_FRAC = 0.05` — percent
of an interval's samples within +/-5% of target power is the compliance
metric the power-meter-training literature favours, explicitly *not*
normalized power (a fatigue-cost estimate that outdoor coasting/surging
inflates, misleading a time-in-zone read). The +/-5% band is the standard
practitioner target-range width in the Allen/Coggan lineage (`Allen H.,
Coggan A. (2010)` / `(2019)`, *Training and Racing with a Power Meter*;
`reference_list.md`, "Cycling training (native)"), corroborated by
convergent secondary sources (TrainingPeaks, TrainerRoad, CTS). **Test:**
if this athlete's "on target" intervals routinely coincide with her saying
the session felt too easy/hard, revisit the band against her own RPE/HR.

**[ADAPTED: cycling] Confidence: medium.** `FADE_FLAG_PCT = 10.0` —
first-third-vs-last-third mean power drop within one effort. `Barsumyan A.,
Soost C., Burchard R. (2025)`, "Enhanced durability predicts success in
amateur road cycling: evidence of power output declines" — *Frontiers in
Sports and Active Living* (`reference_list.md`, "Cycling training
(native)") — found ~6.5% first-to-last power decline over a fatigued 20-min
TT in *successful* amateur road cyclists vs ~12.5% in *less successful*
ones (n=14; no 5-min or HR-response difference), so a within-interval fade
past ~10% is a real durability/pacing signal, not noise. One small
trained-amateur study of a fixed fatiguing protocol, not this athlete's
field intervals — hence medium. **Test:** if her flagged >10%-fade
intervals don't track hard days / poor fuelling / heat / late-ride efforts
more than her non-flagged ones, recalibrate from her own data.

### Terrain-confound detection (coach judgment)

**Coach judgment:** the confound this analyzer exists for — "a threshold
interval up a steepening dirt road reads like a power fade" — is flagged
from three engineering defaults: `GRADE_DROP_FLAG = 0.03` (a first-third-
to-last-third mean-grade decrease >= 3 percentage points is "materially
more downhill"), `HR_HELD_BAND_BPM = 2.0` (HR drift within +/-2 bpm is
"held"), `HR_BACKOFF_DROP_BPM = 5.0` (HR falling > 5 bpm alongside a power
fade reads as easing off). Rule: fade + grade dropped + HR held/rising ->
"likely terrain"; fade + HR dropped hard -> "backed off"; fade >= 10% + HR
held/rising + grade NOT dropped -> "genuine fade". No cited physiological
threshold — read-the-data-not-the-label heuristics, same spirit as
`_is_cycling_sport`; verified to behave sensibly on `real_mtb_race.fit`.
**Test:** if the flag fires on efforts she calls genuine fades (or misses
ones she calls terrain), tighten `GRADE_DROP_FLAG` / the HR bands against
her annotated rides.

### Tightened aerobic decoupling (supplements `cardiac_drift_pct`, never replaces it)

**Coach judgment:** `TIGHTENED_DECOUPLING_MIN_WORKING_FRAC = 0.5`. The
standard first-half-EF vs second-half-EF calc (`analytics.cardiac_drift`)
is documented by TrainingPeaks (`reference_list.md`, "Practical / non-
journal resources") as **invalid on "variable, stop-start or all-out"
rides** — exactly why this athlete's dirt-road interval rides confound the
unfiltered `cardiac_drift_pct`. `tightened_decoupling` runs the same
formula on genuinely *working* samples only (power > `COASTING_FLOOR_W`;
speed > 0.5 m/s absent power), returning `(None, reason)` when < 50% of
moving time was working. Both numbers are reported; the tightened one is
labelled with the fraction of moving time it covers. The 50% floor is a
coach-judgment cutoff. **Test:** the tightened and unfiltered numbers
should roughly agree on her steady Z2 rides and diverge (tightened =
trustworthy, or `None`) on stop-start interval rides; if the tightened one
is still noisy on steady rides, the working-sample filter needs work.

### Match-to-prescription (coach judgment)

**Coach judgment:** `DURATION_TOLERANCE_FRAC = 0.25` — a detected effort
within +/-25% of a prescribed rep's duration is "the same rep" when
aligning efforts to a recovered `WorkoutStructure`'s interval steps in
order. With no recoverable structure (the common case — `planned_session_
id` is never populated in practice, and a TrainerRoad-originated workout
carries none), efforts are reported raw against a caller-supplied target.
Engineering default.

### Micro-interval detection and set clustering (coach judgment / PROVISIONAL)

A real validation pass ran the analyzer against four of this athlete's
rides and found the flat `EFFORT_MIN_S = 120` floor made 30/30-style VO2
work **completely invisible** (0 efforts on a structured 6×5×30/30 ERG
session). The fix keeps `EFFORT_MIN_S` as the *sustained*-effort cutoff but
lowers the primitive scan to `MICRO_EFFORT_MIN_S = 12.0` and adds a
clustering pass:

- **`MICRO_EFFORT_MIN_S = 12.0`** — the raw span scan's floor. A short-short
  VO2 rep is ~30–40s on (`24-cycling-periodization-intervals.md`,
  "Short-short (VO2)"); after the ramp in and settle out, ~12s of
  genuinely-above-threshold samples is the smallest run worth keeping as a
  candidate rep. Tuned against the real 30/30 file (a 10s floor also
  worked; a 20s floor started dropping real reps). No source pins the
  number — `Coach judgment:`, PROVISIONAL.
- **`SET_RECOVERY_MAX_S = 75.0`** — the longest gap between two consecutive
  short reps that keeps them in one set. Short-short floats are ~15–20s and
  a 30/30's is ~30s (`24-...`), while sets are separated by "several
  minutes of easy recovery" — 75s bridges a sloppy in-set float without
  ever joining two sets. `Coach judgment:`, PROVISIONAL.
- **`SET_MIN_REPS = 4`** — fewer than four short above-threshold reps is a
  handful of surges / warm-up openers, not a set. `24-...` describes VO2
  sets as "8–12 reps"; four is a floor, set deliberately above three so a
  warm-up's two or three openers never form a phantom set. `Coach
  judgment:`.
- **`SET_MAX_REP_S = 150.0`**, **`SET_MAX_SPAN_S = 1500.0`**,
  **`SET_MIN_ON_POWER_FRAC = 0.80`** — a "rep" longer than `SET_MAX_REP_S`
  is a work bout in its own right; a cluster spanning more than
  `SET_MAX_SPAN_S` (~25 min) is a long stretch of punchy riding, not one
  coherent set; and a cluster is only kept if its ON-rep mean power reaches
  `SET_MIN_ON_POWER_FRAC` of the target (same 0.80 as `TARGET_GATE_FRAC`),
  so a cluster of ~180W surges during a 263W warm-up is discarded. All
  `Coach judgment:`, engineering defaults tuned against the real files.

A clustered set is reported as one effort carrying an
`IntervalSubStructure(pattern="rep_set", n_reps, high_avg_w, low_avg_w,
high_s, low_s, ...)` — the ON count, ON vs float power, and their median
durations.

### Non-effort false-positive filter (`SUSTAINED_EFFORT_GATE_FRAC`)

The same validation pass found that, with a target supplied, a warm-up ramp
from 138→248W into a 263W target registered as an "effort" flagged "under
target 76%" — a false failure — because `detect_efforts` opened a span on
*any* sample ≥ `target × TARGET_GATE_FRAC`. **Coach judgment:**
`SUSTAINED_EFFORT_GATE_FRAC = 0.80` — a ≥ `EFFORT_MIN_S` candidate only
survives if its own *mean* power (not just momentary crossings) reaches
0.80 of the target. Same height as the instantaneous entry bar by design:
"195W against a 239W target is still an attempt" applies to the sustained
level too, not one lucky sample. In dynamic (no-target) mode the equivalent
gate is "span mean ≥ the ride's own 40th-percentile working power", which
kills a mid-ride lull that only crested the detection threshold on a couple
of bridged spikes. Verified against the real files: the 2×12 and
Chamberlin-4 sustained blocks still detect; the warm-up/cool-down ramps no
longer do.

### Over/under sub-resolution (coach judgment)

Within one continuous effort, a roughly regular high/low power oscillation
(an over/under set — `24-...`, "Over/unders") is split into its OVER and
UNDER halves. **Coach judgment**, all engineering defaults tuned against
this athlete's clean gravel over/unders and her feel-ridden trail
"Heat Animation" file:

- **`OVER_UNDER_SMOOTH_S = 30.0`** — raw off-road power crosses its own mean
  ~150 times in a 10-min effort from surface/line noise alone, so power is
  first smoothed with a centred ~30s moving average. Short enough to
  preserve a real ~90–120s segment, long enough to erase the chatter.
- **`OVER_UNDER_MIN_CYCLES = 3`**, **`OVER_UNDER_MIN_SEG_S = 20.0`**,
  **`OVER_UNDER_MIN_MEDIAN_SEG_S = 30.0`** — at least three OVER runs,
  sub-20s runs merged into neighbours first, and the median OVER run must
  last ≥ 30s (a stepped effort whose sustained portion merely wobbles
  across its own mean is not an over/under).
- **`OVER_UNDER_MIN_SPREAD_FRAC = 0.16`** — the OVER-mean vs UNDER-mean must
  differ by ≥ 16% of the effort mean. `24-...`'s canonical over
  (~100–105% FTP) vs under (~76–85% FTP) is a ~20% spread; the defining
  feature is that the UNDER segments deliberately drop *below* threshold. A
  steady 2×12's incidental wobble stays bunched near target (~15% smoothed
  spread on the real file, all of it near threshold) and is correctly not
  flagged; a feel-ridden set still shows a real ~18–25% spread.

Reported as `IntervalSubStructure(pattern="over_under", n_reps=<cycles>,
high_avg_w, low_avg_w, high_s, low_s, time_in_high_pct, time_in_low_pct)`.

### All-interval decoupling guard (coach judgment)

`tightened_decoupling` returned 20.7% for a pure 30/30 VO2 session, where a
first-half/second-half efficiency-factor number is meaningless (no steady
aerobic block for it to describe). **Coach judgment:** `analyze` nulls the
decoupling read (with a reason) when the ride is "all-interval" — its own
*dynamic-threshold* efforts (detected with no supplied target, so this is a
property of the ride, not the coach's query) number ≥
`ALL_INTERVAL_MIN_EFFORTS = 3` and together cover ≥
`ALL_INTERVAL_EFFORT_COVERAGE = 0.45` of the ride's working time. On the
real files this lands ~0.51 on the 30/30 session (fires) vs ~0.38 on a
2×12 threshold ride and ~0.22–0.27 on long mixed rides (all keep their real
number). Both the fraction and the min-effort count are fitted cutoffs, not
cited values. The `24-...` polarized-distribution framing is the
background: an all-hard session has no "grey zone" steady block by design.

### Adaptive in-band tolerance (coach judgment, extends the `IN_BAND_FRAC` ADAPTED tag)

The fixed ±5% band read this athlete's well-ridden gravel efforts as bad
execution (17–25% time-in-band). **Coach judgment:** the band scales with
the ride's own surface roughness:

- **`IN_BAND_FRAC = 0.05`** stays the FLOOR and the indoor-ERG value (the
  ADAPTED: cycling tag above still applies — it is the Allen/Coggan
  practitioner band, and correct when a trainer holds the watts).
- **`IN_BAND_FRAC_MAX = 0.15`** — the widest the band opens: ±15% is about
  the honest limit of "held the interval" on gravel/MTB where grade and
  line move the power under a rider pacing by feel.
- **`IN_BAND_ROUGHNESS_MULT = 2.0`**, **`INDOOR_ROUGHNESS_MAX = 0.02`** —
  `band = clamp(roughness × 2.0, 0.05, 0.15)` where `roughness` is the
  ride's median sample-to-sample |power change| ÷ mean working power. On
  the real files this lands ~5% (indoor ERG, roughness ~0.005), ~9%
  (paved/gravel, ~0.046), ~15% (singletrack, ~0.115) — the band an
  experienced coach would eyeball per surface. A ride below
  `INDOOR_ROUGHNESS_MAX` keeps the tight floor; a caller that knows the FIT
  `sub_sport`/`trainer` flag can force it via `analyze(..., indoor=...)`.
  The multiplier is a fitted constant, not cited.
