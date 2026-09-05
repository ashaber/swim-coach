# Injury/layoff-aware ramp-then-taper (`taper_search.py`)

Grounds `engine/swim_coach/taper_search.py`'s constants: the three-phase
RAMP -> HOLD -> TAPER projection extending the plain hold-then-decay taper
grid search, and the restriction-driven ramp cap. See `03-periodization.md`
for the underlying CTL/ATL/TSB Banister model and its own citation debt
(time constants unverified for swimming) -- this file only covers what's
new here, not a restatement of that model.

## Why this exists

Built for a real, current situation (Sept 2026): an athlete suffered a
shoulder/rib injury with ~13 days' runway left before a real 4-day stage
event, took several days fully off, then completed one light test swim.
Feeding her literal recent daily load (near-zero, post-injury) into a plain
hold-then-decay taper model would project her staying near that depressed
level all the way to race day -- clearly wrong. This module adds a genuine
capped RAMP phase before the existing TAPER decay, so the engine can
propose "rebuild toward a safe target, then taper" instead of only "hold
wherever you already are, then taper."

This is a general engine capability (any coach-callable taper search can
hit an active `HealthStatus` restriction, an athlete returning from illness
or travel, or no restriction at all), not a one-off patch for this
athlete's specific case -- see `backend/app/tools.py`'s
`propose_injury_adapted_taper` for the coach-facing tool.

## Race-day TSB band

`RACE_DAY_TSB_BAND = {"low": 5.0, "high": 25.0}`. **✓ Verified by direct
fetch this session**: Joe Friel, quoted in TrainingPeaks' "Applying the
Numbers Part 3: Training Stress Balance" -- "When I'm tapering and peaking
athletes for A-priority races I like to have their Form at around plus 15
to plus 25 on race day," while separately noting some athletes perform best
around +5 to +10. The band spans both figures rather than picking one.
`[ADAPTED: cycling]` -- a cycling/TrainingPeaks practitioner convention,
stacked on top of `03-periodization.md`'s already-flagged, swimming-
unverified CTL/ATL time constants. **Confidence: medium.** **Test:** if
this athlete's own real race-day outcomes correlate poorly with landing in
this band (either direction), revisit the band itself before touching the
underlying CTL/ATL time constants.

## Pre-layoff baseline window

`PRE_LAYOFF_BASELINE_WINDOW_DAYS = 28`, ending the day before the
reference boundary date (an active `HealthStatus.reported_at`, or a generic
fallback when there's no active restriction -- see the module's own
docstring). Four weeks, slightly longer than the existing
`RECENT_BASELINE_WINDOW_DAYS = 21` (unchanged from the abandoned draft this
module extends): long enough to average out one atypical week without
reaching back into an earlier, lower-volume training phase. **Coach
judgment / PROVISIONAL** -- no swim-specific citation pins this exact
window; same posture as `RECENT_BASELINE_WINDOW_DAYS` itself.

## The ramp cap: `LIGHT_ONLY_RAMP_CAP_FRACTION = 0.55`

When an active `HealthStatus.restriction == "light_only"` exists, the ramp
phase's target load is capped at 55% of the athlete's own pre-layoff
baseline (never lower than her current recent baseline -- this never
proposes ramping DOWN).

**Confidence: LOW-MEDIUM, stated honestly.** There is no established
research pinning an exact "what fraction of pre-injury training volume is
safe to ramp back to in N days" figure for a return-from-shoulder-injury
swimmer. 0.55 was chosen as the midpoint of a defensible 40-70% range,
grounded in two things:

1. This module's own real motivating context: an athlete's real advisory-
   panel consultation (physiologist/sports-med/psychologist personas,
   Sept 2026) reasoned explicitly that a compressed return-to-event taper
   should keep "same swim intensity, meaningfully less volume" rather than
   chase volume back up.
2. The same "hold intensity, cut volume" principle `03-periodization.md`
   already cites for taper-DECAY (`Mujika I., Padilla S. (2003)`,
   "Scientific bases for precompetition tapering strategies," *Medicine &
   Science in Sports & Exercise*, 35(7):1182-1187: volume can be cut 60-90%
   while holding intensity, with minimal performance cost) -- applied here
   symmetrically to the ramp-BACK-UP side: if a large volume cut with
   intensity held is the safe taper direction, a conservative (not
   aggressive) fraction of pre-injury volume, again with intensity held
   rather than chased, is the same logic in reverse. This is this module's
   OWN extension of that principle -- Mujika & Padilla's paper does not
   itself address return-from-injury ramping, and this fraction should not
   be read as if it did.

Complements `21-shoulder-health-and-load.md`'s existing swim-specific
return-to-training criteria (Wilk et al. 2020) and rehab-phase structure --
this module's cap is a training-LOAD-planning number for the engine's own
math, not a substitute for that file's clinical return-to-swim criteria or
a practitioner's actual clearance.

**Test:** revisit once real dual-logged return-from-injury data exists (for
this or other athletes) -- either a stalled return (too conservative) or a
flare-up/re-injury following a ramp that used this fraction (not
conservative enough) should move the number, not just confirm it.

`restriction == "no_training"` permits NO ramp at all -- the ramp target is
pinned to the athlete's current recent baseline, and no candidate above it
is ever generated. This is a hard behavioral rule, not itself a numeric
constant needing its own confidence grade.

## Ramp-day grid and rest-day cadence

`RAMP_DAYS_GRID_DEFAULT = (0, 2, 4, 6, 8, 10, 14)` -- day-granular (not
week-granular like `taper_weeks`) specifically because a short-notice,
injury-interrupted runway (this module's own real motivating case: 12
days) is exactly where a coarser weekly grid would miss the relevant
detail. **Coach judgment / PROVISIONAL**, no citation.

`REST_DAY_CADENCE_DAYS = 3` (session-content generation only, not fed back
into the TSB projection): every third day is rendered as a full rest day,
matching the real advisory-panel plan's own roughly one-rest-day-per-two-
training-days cadence. **Coach judgment / PROVISIONAL**, explicitly flagged
as a real simplification -- the smooth TSB projection treats each day's
target load continuously, while real training is lumpier; the two are not
reconciled in this build. **Test:** revisit if real adherence data suggests
a different cadence distributes load better for this kind of short-notice
window.
