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

## Ramp floor and ceiling: CTL substitution, not flat means (2026-09)

The ramp's floor (`recent_baseline_daily_load`) and ceiling
(`pre_layoff_baseline_daily_load`) were originally plain TRAILING
ARITHMETIC MEANS: 21 days for the recent/floor number, 28 days for the
pre-layoff/ceiling number (`RECENT_BASELINE_WINDOW_DAYS`/
`PRE_LAYOFF_BASELINE_WINDOW_DAYS`, both now deleted). Neither had any real
decay awareness -- an athlete who stopped logging during an injury had her
"recent baseline" silently FROZEN at whatever her last active window
looked like, no matter how much real detraining time had since passed, and
a fresh restriction needed a separate manual window-shrinking hack
(`effective_recent_window_days`, also now deleted) just to keep old
pre-injury days from dominating a still-mostly-empty recent window.

Andrew's own question, verbatim, surfaced this: "are we using recent max
duration? recent max load? Should we be using Acute:Chronic Workload Ratio
(ACWR)... EWMA of ATL and CTL instead of static trailing-maximum values?
ACWR would account for decay of fitness due to time off and also would
allow for a higher rate of increase back to pre-injury load."

**Two decisions followed, both confirmed:**

1. **CTL substitution, yes.** `search_taper_grid` already computes a full
   Banister CTL/ATL/TSB series (`load.ctl_atl_tsb_series`,
   `03-periodization.md`) for its own TSB projection -- `ctl0` (CTL at
   "now") IS already the decay-aware EWMA Andrew described, just not
   previously used as the ramp floor. The floor is now `ctl0` directly (no
   new computation). The ceiling is now a point-in-time CTL LOOKUP
   (`ctl_at`, an O(1) dict read into the same already-computed series) at
   the pre-layoff boundary date, rather than a second, independently
   averaged number. CTL's own 42-day exponential decay supersedes the old
   window-shrinking hack structurally, not just numerically -- old
   (pre-layoff) history is naturally discounted relative to recent history
   by the EWMA itself, with no manual window-capping mechanism needed at
   all. A genuinely new capability came with this: the CTL walk is now
   extended through to "today" (seeding a zero-load day at `as_of` when the
   athlete has stopped logging entirely -- the same "missing day counts as
   zero load" convention already used throughout `load.py`) rather than
   stopping at her last logged day, so real elapsed time off is actually
   reflected in `ctl0` even when she's stopped logging altogether.

2. **A literal ACWR ratio/threshold, explicitly rejected.** This
   codebase's own `load.py` already carries a LOW-confidence caveat on
   ACWR as a swimmer-specific safety signal (`ACWR_ACUTE_WINDOW_DAYS`/
   `ACWR_CHRONIC_WINDOW_DAYS`'s own citation block: elevated ACWR was
   associated with shoulder pain in *youth* swimmers, Feijen S. et al.
   2021, but the odds-ratio confidence interval's lower bound sits near
   1.0 -- marginal -- and "ACWR methodology is broadly criticized," with a
   separate Garmin-RunSafe cohort finding week-to-week ratio/ACWR a weak
   predictor next to a simpler single-session-vs-30-day-longest check).
   Adopting a literal ACWR ratio here would mean stacking a SECOND,
   separately low-confidence methodology on top of one this codebase
   already carries citation debt for, for no real gain over the CTL
   machinery already sitting computed and unused in this exact module.
   `taper_search.py` does not implement an ACWR ratio or any ACWR-derived
   threshold anywhere.

**Out-of-range fallback.** If the pre-layoff boundary date falls before the
earliest day the athlete's logged history ever reaches (a short/incomplete
logging history), `ctl_at` returns `None` -- the only way it can be
"missing," since the CTL series never has gaps once it starts. In that
case `search_taper_grid` falls back to the EARLIEST available CTL in the
series: `ctl_atl_tsb_series` seeds CTL near 0 at the true start of walked
history, so the earliest available point is the closest honest answer
available for "what was her fitness before this history even starts,"
rather than fabricating a number for a date the engine has no data reaching
back to. `pre_layoff_baseline_used_earliest_fallback` in the tool's
response says plainly whether this fallback was used.

The BOUNDARY DATE the ceiling is looked up at is still governed by the
value formerly named `RECENT_BASELINE_WINDOW_DAYS`, renamed
`NO_RESTRICTION_PRE_LAYOFF_LOOKBACK_DAYS = 21` now that its only remaining
role is picking a date (not sizing an averaging window): the active
`HealthStatus.reported_at` date when one exists, or 21 days back from
`anchor_date` as a generic "before recent" fallback when there's no active
restriction on file. **Coach judgment / PROVISIONAL** -- no swim-specific
citation pins this exact lookback; same posture as before.

## The ramp cap: `LIGHT_ONLY_RAMP_CAP_FRACTION = 0.55`

When an active `HealthStatus.restriction == "light_only"` exists, the ramp
phase's target load is capped at 55% of the athlete's own pre-layoff
baseline -- a HARD CEILING, full stop.

**Real bug fixed before merge, worth documenting here honestly:** an
earlier version of this cap read `max(current_recent_baseline,
55%_of_pre_layoff)`, intended to mean "never propose ramping DOWN below
what she's already doing." In practice that let the cap be silently
overridden whenever `current_recent_baseline` itself read high for reasons
unrelated to genuinely, safely handling more load -- most notably, the
recent-baseline window is deliberately shrunk right when a restriction is
freshly reported (see above), so a single big pre-injury session logged
the very day of the injury can dominate that shrunk window and read near
full pre-injury load, erasing the cap at exactly the moment it matters
most. A safety ceiling a data artifact can quietly cancel isn't a ceiling.
The cap is now unconditional: exactly 55% of pre-layoff baseline, never
extended upward to match a higher current-baseline reading. A coach who
genuinely believes more is safe than this cap allows has `restriction_
override` (the calling tool's own parameter) for that -- an explicit,
visible human choice, never a silent side effect of which days happened to
fall inside a rolling average window.

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
