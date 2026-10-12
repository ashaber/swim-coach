# Cycling start analysis (standing/rolling maximal starts from power data)

See `00-conventions.md` for the tagging scheme and `reference_list.md` for
full citations (section "Cycling start analysis").

**Sport scope: `bike`.** Grounds any analyzer logic that reads a short
maximal start (CX race-start practice, holeshot reps) out of a `.fit`
power/cadence stream. Never surfaced to a swim-only athlete.

**UNREVIEWED**, pending human review. Every source below was located and
read (abstract minimum) in the drafting session; see `39-references.md`
for how each was verified. There is **no peer-reviewed power-file study of
cyclocross starts**: everything quantitative is adapted from BMX gate
starts, track standing starts, lab sprints, or XCO mass starts.

## 1. Metrics used to analyze a maximal start

Researchers analyzing standing starts report: **peak power**, **time to
peak power (TTPP)**, **peak torque** (especially of the lead leg),
**cadence at peak / optimal cadence (Fopt)**, the **torque–cadence
(force–velocity) profile** (Pmax, Fopt, Tmax), **split times over the first
metres**, and **fatigue / power decrement** after peak.

**[ADAPTED: cycling] Confidence: medium.** Kordi & van Rijswijk (2024),
elite team-sprint man 1: 15/65/125 m splits from 36 standing starts; peak
lead-leg torque and peak power predicted 15, 65 and 125 m times, and the
first 15 m predicted a disproportionate share of opening-lap time.
Janssen & Cornelissen (2017): higher effective pedal force gave a faster
first pedal stroke; lead leg produced more effective force than trail leg;
no BMX-vs-track difference. Padulo et al. (2016): a standing (vs seated)
start gave ~10% more speed over the first 5 m, with the extra muscle
activation confined to the first pedal stroke. **Test:** across an
athlete's start reps, power averaged over the first 3 s should correlate
more strongly with 10–15 s average power than peak 1-s power does; if not,
the launch is not the limiter.

**[ADAPTED: cycling] Confidence: medium.** Rylands, Roberts & Hurst (2017,
gear ratio) and Rylands et al. (2016, cadence) use peak power + TTPP as
the two headline BMX start metrics; Daneshfar et al. (2020) add peak
cadence and mean power with/without rest. **Test:** both metrics are
computable from a 1 Hz stream (see sampling caveat, §6).

**Fatigue index is a weak metric.** **[EVIDENCE: cycling] Confidence:
medium-high.** Coleman et al. (2005), well-trained cyclists on their own
bikes with SRM, 30-s sprint ×4: CV 4.5% peak power, 2.4% mean power, but
**17.2% for fatigue index**. Driss & Vandewalle (2013) review: fatigue
index was "the least reliable" Wingate index and its validity questioned.
Prefer mean power over a fixed window to peak-to-minimum ratios.

## 2. Time-course of a maximal start

**Time to peak power ≈ 2–3.5 s.** **[ADAPTED: cycling] Confidence: medium.**
Daneshfar et al. (2020), 14 sub-elite BMX riders, field gate starts, SRM
at 1 Hz: peak 1288.7 ± 62.6 W reached at 2.34 s; peak cadence 131 ± 6 rpm
at 2.13 s. Rylands et al. (2016), 6 elite BMX riders, isokinetic lab:
TTPP 2.5 ± 1.07 s at 120 rpm, 3.0–3.5 s at 80/100/140 rpm. Rylands et al.
(2015): field TTPP was markedly shorter and peak power ~34% higher than
lab values. A CX start is clipped-out/one-foot, on grass or tarmac, in a
road-ish gear, so expect the slower end. **Test:** median TTPP across the
athlete's clean start reps should fall in ~2–6 s; a TTPP > 8 s marks a
rolling/gradual effort, not a launch.

**Peak sits near optimal cadence.** **[ADAPTED: cycling] Confidence: medium.**
Elite sprinters: Fopt 128–130 rpm (Dorel et al. 2005: Pmax 1600 ± 116 W at
129.8 ± 4.7 rpm; Gardner et al. 2007: 1791 W, 128 ± 7 rpm lab vs 129 ± 9
field). Trained non-sprint cyclists: Pmax ~1311–1320 W at Fopt 116–118 rpm
(Wackwitz et al. 2020). **Test:** cadence at the 1-s peak should land
~100–130 rpm; peak power at < 80 rpm means the gear was too big (torque-
limited) and > 140 rpm too small (spun out).

**Decline after peak.** **[ADAPTED: cycling] Confidence: medium.**
Power falls by a roughly constant increment per crank revolution — fatigue
tracks cumulative contractions, not time (Tomas, Ross & Martin 2010; r² =
0.99). Over 30 s all-out, decline from peak is ~52–59% (Tomas 2010) and
55 ± 14% in trained cyclists (Passfield & Doust 1999). World-class
sprinters lose ~15–17 W per pedal stroke in 15-s sprints regardless of
±15% cadence (Wackwitz et al. 2023), so a bigger gear (fewer strokes)
reduces total decrement. No source gave a clean 10-s or 20-s decline for
amateurs. **Coach judgment:** by interpolation, a well-executed 10–15 s
start sits ~20–35% below its peak by the end of the window; a CX
practitioner example (Wolfe 2014, TrainingPeaks) shows 1100 W peak / 743 W
15-s mean (mean ≈ 68% of peak). **Test:** fit 15-s-window mean/peak across
reps; flag reps outside 0.55–0.85 for review rather than as "bad."

Age: sprint power in well-trained triathletes declined continuously after
50, −36% from 20–29 to > 70 years (Brisswalter et al. 2014,
**[ADAPTED: cycling] Confidence: medium**). Use the athlete's own
best start as reference, never elite absolutes. **Test:** the analyzer compares a start only with the same athlete's earlier starts, never with an absolute watts figure.

## 3. Gear choice and shift dips

**[ADAPTED: cycling] Confidence: medium.** Rylands et al. (2017): 45/16 gave
higher peak power (1658 ± 221 W) than 43/16 (1436 W) or 41/16 (1380 W)
with **no change in TTPP**. Rylands et al. (2016) found peak power at 100
rpm but fastest TTPP at 120 rpm. A modestly bigger gear helps if the rider
can still turn it over. **Test:** compare peak power and TTPP by starting
gear if the head unit records gear (Di2/AXS); otherwise by cadence in the
first 2 s.

**Shift dips — no research located.** Practitioner sources only: Matheny
(RoadBikeRider) — start ~80 rpm, jump past 100, shift up while standing,
"ease off pedal pressure slightly" at the shift (less needed with
electronic); Liv Cycling — "lighten up on your pedals for a half stroke
while you shift"; shifting under load risks skipped gears. **Coach
judgment:** so a deliberate shift shows as a 1–2 s power dip with cadence
falling *after* it (higher gear); a mis-shift/skip shows as a dip with a
cadence spike or a near-zero sample.

## 4. Repeated starts: recovery, decline, variability

**Recovery.** **[ADAPTED: cycling] Confidence: medium.** Glaister
et al. (2005): 20×5 s with 30 s vs 10 s recovery gave ~4% higher peak and
~26% higher mean power. Dale et al. (2022), 18-s sprints with 45–720 s
recovery: τ ≈ 131 s, recovery stabilised within ~12 min, but a two-phase
fit plateaued short of full recovery (fast component ~88%). **Test:**
starts separated by ≥ 3 min should hold peak within ~5% of rep 1; a steady
downward trend at ≥ 3 min spacing points to fatigue/glycogen, not rest
length.

**Fatigue vs technique.** **[ADAPTED: cycling] Confidence:
medium.** Girard et al. (2011): repeated-sprint fatigue shows as falling
peak power/total work across reps, with both muscular and neural causes;
decrement is inversely related to initial sprint performance.
Mendez-Villanueva et al. (2007): 6-s standing sprints, trial 1 was 4.9%
lower than later trials (familiarisation); CV 1.8–2.8%. **Coach
judgment:** a monotonic decline across reps = fatigue; a single low rep
among normal ones = execution (missed clip-in, bad shift, traffic). **Test:** on the real 10/10 and 9/26 starts, isolated weak starts (3 and 5) read as execution and no steady decline reads as fatigue.

**Set sizes.** No source gave CX start-practice set sizes. **Coach
judgment:** 4–8 starts of 10–20 s, 3–5 min easy between, stop when peak
drops > ~10% from the set's best.

## 5. Cyclocross/MTB starts and the holeshot

**[ADAPTED: cycling] Confidence: medium.** XCO is a fast start then even
or declining pace: Granier et al. (2018, international XCO); Hays et al.
(2018) — 32.8% of lap 1 above maximal aerobic power vs 24.0% by lap 3, lap-1
lactate 7.4 mmol/L; Næss et al. (2021) — W′ per bout fell from 0.113 (start
lap) to 0.045 (final lap), riders "employ an aggressive start to best
position themselves." Start position strongly predicts finish in World Cup
XCO (Macdermid & Morton 2012) and BMX (Rylands & Roberts 2014; position at
the second timing gate τ ≈ 0.57–0.58). CX itself: only practitioner
material (Wolfe 2014: "the start of the race is the most important").
**Test:** in the athlete's race files, mean power over the first 60 s
should exceed lap-average power; if not, the start is under-cooked.

## 6. Reading one start's trace

**Measurement caveat. [EVIDENCE: cycling] Confidence: medium.**
Iglesias-Pino et al. (2023): Power2Max and PowerTap were valid at
~100–450 W but agreement was "questionable" above 500 W, and cadence
reliability was poor in sprints. Treat single-sample peaks cautiously;
prefer 3–5 s means.

**Coach judgment** (no source) for phase labels:
- **Launch:** the rise from rest (last sample under half of FTP) to peak
  power; judge it by time to peak and the 3-5 s mean, not the 1-s peak.
- **Shift dip:** a ≥ 25% drop lasting ≤ 2 s with a recovery after.
- **Sustain:** post-peak plateau/decline phase; judge by mean power.
- **Stopped early:** power < ~50% of the start's peak for ≥ 3 s before the
  planned duration.
- **Restart:** a new launch within ~10 s of a stop (aborted start).

## What this means for the analyzer

- **Launch time / rate:** TTPP target ~2–6 s (BMX field 2.3 s; lab
  2.5–3.5 s, slower for CX). Rate = (peak − baseline)/TTPP; compare to own
  history only. Cadence at peak ~100–130 rpm (Fopt 116–130).
- **Shift-dip detection:** coach judgment (§3, §6); pair a power dip with
  cadence direction to tell a shift from a skip.
- **Sustained-power floor:** fatigue is per-revolution (Tomas 2010); score
  window mean/peak; 0.55–0.85 over 15 s is the review band (coach
  judgment anchored on Wolfe 2014 and 30-s decline data). Do not use
  fatigue index (CV 17%).
- **Stopped early vs intended:** coach judgment threshold (§6); compare
  effort length with the prescribed rep.
- **Restart:** coach judgment (§6); don't count an aborted launch as a
  weak rep.
- **Rep-to-rep:** expect ~2–5% CV between clean reps (Mendez-Villanueva
  2007; Coleman 2005) and a lower first rep. Monotonic decline =
  fatigue; isolated outlier = execution.

## 7. Finding -> likely cause -> practice cue

The analyzer emits `start_findings` with a `cue_key`; each key is a row
here. Everything below is **`Coach judgment:`** unless a source is named; a
sourced practice-cue pass (drills, set design) is still to be merged. One
cause and one thing to practice per finding; the athlete's own best start
is the reference.

| `cue_key` | Finding (engine) | Likely cause | Practice cue |
|---|---|---|---|
| `slow_launch` | time to peak above 6 s (typical 2-3.5 s, BMX field/lab) | gear too small or too big for a standing clip-in; soft first stroke | Rylands et al. (2017): a modestly bigger gear raised peak power with time to peak unchanged, so test one gear up on 4-6 clean starts; otherwise rehearse clip-in and a hard first stroke at 80 rpm |
| `low_peak` | best 3-5 s mean well under the athlete's best start | cadence under 80 rpm (torque-limited) or over 140 (spun out); early sit-down | Start in a gear that reaches 100-130 rpm by the third second; stay standing until the peak |
| `early_shift_dip` | a sharp dip in the first 8 s that recovers | shifting under load or a late shift | Shift once, early, with a half-stroke of eased pressure (electronic shifting needs less); set the gear before the start |
| `stopped_early` | power under half of peak for 3 s or more well before the planned end | ending the effort on feel, not on the timer | Hold to the beep; count the planned seconds aloud; finish the step before easing |
| `weak_restart` | a restart after the stop at under 60% of the peak | trying to rescue a step that already ended | Treat the restart as a new rep or skip it; do not pad the step |
| `execution_miss` | one start well below the rest, the others steady | missed clip, bad shift, traffic | Repeat the rep; practice clip-in and the first stroke; do not read it as fatigue |
| `fatigue_decline` | starts fall rep after rep | too little recovery or too many reps | Longer recovery (3-5 min) or fewer reps; stop the set when peak drops by about 10% |
