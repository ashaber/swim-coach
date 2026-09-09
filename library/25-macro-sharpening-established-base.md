# A second macro shape: established-base, short-runway sharpening

See `00-conventions.md` for the tagging scheme and `reference_list.md` for
full citations. Split out of `24-cycling-periodization-intervals.md` to
stay under that file's word-count cap (`00-conventions.md`'s "topic files
stay <= ~2,500 words" rule) — same precedent as `15-tiered-session-load.md`
splitting out of `03-periodization.md`.

**Sport scope: `bike`.** Same guidance-scoping constraint as
`23-cycling-training.md`/`24-cycling-periodization-intervals.md` — never
surfaced to a swim-only athlete. `swim_coach.plan.scaffold_sharpening_macro`
(the engine function this file grounds) is, as of this build, only ever
invoked from `backend/app/tools.py`'s `draft_macro_plan` handler, and only
when the target event's `primary_sport == "bike"` — see that function's own
docstring and `MacroBlock.name`'s docstring (`swim_coach/models.py`) for the
explicit statement that the swim path never reaches a `"hold"`/`"sharpen"`
block in practice.

## The shape itself

**`[ADAPTED: general-endurance]`**, Confidence: medium — re-verified by a
fresh web search this build (not carried over from an earlier session's
summary on trust). Issurin's block periodization (already cited in
`24-cycling-periodization-intervals.md`: `Issurin V. B. (2008)`, "Block
periodization versus traditional training theory: a review," *The Journal
of Sports Medicine and Physical Fitness*, 48(1):65-75) structures training
into three specialized mesocycle-blocks — **accumulation** (building
general/basic abilities), **transmutation** (converting accumulated
potential into event-specific preparedness, via concentrated, narrow-focus
work), and **realization** (peaking/tapering into competition) — and
states a single mesocycle-block's duration runs **2 to 4 weeks**. A full
accumulation->transmutation->realization sequence is one "training stage,"
typically ~8-12 weeks. **Test:** if a `sharpen` block consistently
underperforms a longer, traditionally-ramped build for a given athlete's
own real fitness trend, that is athlete-specific signal worth weighing
against the model, not grounds to assume the block itself was designed
wrong (same posture `24-cycling-periodization-intervals.md` already takes
toward this same source).

This grounds `scaffold_sharpening_macro`'s **hold -> sharpen -> taper**
shape — a second, deliberately DIFFERENT periodization shape from
`scaffold_macro`'s own base->build->peak->taper, built for the athlete who
already has a real, evidence-based training base (see below) but does not
have `MIN_MACRO_WEEKS` (8) weeks of runway before their event:

- **sharpen** is this engine's transmutation-block implementation:
  concentrated, race-specific intensity work (the existing
  `_select_bike_interval_template` rotation `24-cycling-periodization-
  intervals.md` already grounds), bounded to Issurin's own stated 2-4 week
  range (`SHARPEN_WEEKS_MIN`/`SHARPEN_WEEKS_MAX`) — never longer, since a
  longer block would no longer be the concentrated block the source
  describes.
- **hold** stands in for accumulation, but INVERTED: an athlete with an
  established base has already accumulated the base quality accumulation
  would otherwise build, so this phase is a flat maintenance hold (no ramp)
  rather than a fresh accumulation climb — only present when the runway has
  real spare weeks beyond what sharpen+taper need.
- **taper** is realization, and is NOT re-derived: it reuses
  `scaffold_macro`'s own existing taper block (`TAPER_WEEKS_SHORT`,
  `TAPER_WEEKLY_DECAY`) completely unchanged — the same block, not a
  second taper design.

`Galán-Rioja et al. (2023)` (already cited in `23-cycling-training.md`/`24-
cycling-periodization-intervals.md`) independently corroborates
concentrated blocks (1-8 weeks) being real practice in trained cyclists
specifically — the same corroboration `24` already leans on for its own
deload-cadence gap, now doing double duty for this shape's `sharpen` block
length.

`SHARPENING_MIN_MACRO_WEEKS` (this shape's own minimum runway, `engine/
swim_coach/plan.py`) is a derived, not guessed, number: Issurin's own
minimum transmutation-block length (`SHARPEN_WEEKS_MIN` = 2) plus the
taper this shape reuses unchanged from `scaffold_macro` (`TAPER_WEEKS_
SHORT` = 2) = 4 weeks — always strictly below `MIN_MACRO_WEEKS` (8), so the
two shapes' accepted runway ranges never overlap and never leave a gap
between them.

## Established-base detection: honestly flagged PROVISIONAL

`swim_coach.load.has_established_training_base` /
`BASE_DETECTION_LOOKBACK_DAYS` / `BASE_DETECTION_MIN_WEEKS_WITH_LOAD_
FRACTION` decide whether an athlete's REAL logged training history (never
this shape, never the event being planned, never conversation) counts as
an "established base" at all — a question deliberately independent of any
specific macro/event, by construction (the function takes no `Event`/
`MacroPlan` parameter at all).

**Confirmed absent by direct search this build:** no primary literature —
not Issurin (2008), not any source already cited in this file, `23-
cycling-training.md`, or `24-cycling-periodization-intervals.md` — pins an
exact "how many weeks of consistent training makes a base established"
number. The 84-day/12-week lookback window and the 75%-of-weeks-must-carry-
real-load breadth check are both `Coach judgment:`, derived (not arbitrary)
from what this engine's own `CTL_TIME_CONSTANT_DAYS = 42` (`load.py`)
implies about how long a Banister-model CTL exponentially-weighted moving
average takes to reach a stable reading from a cold start: standard
EWMA-to-steady-state math (not a swim/cycling-specific claim) puts an EWMA
with time constant tau at ~63% of the way to steady state after 1 tau,
~86% after 2 tau, ~95% after 3 tau. `BASE_DETECTION_LOOKBACK_DAYS` takes
2 x `CTL_TIME_CONSTANT_DAYS` (42) = 84 days = exactly 12 whole weeks — the
low end of `load.py`'s own `ctl_atl_tsb_series` module docstring's "a few
multiples of the longer time constant" language for when that series is
already "warmed up," not "still climbing from a cold start."

The 75% breadth check (real logged load present in at least 9 of the
trailing 12 weeks, not just a raw CTL/mean reading) is this build's direct
answer to "not just one big week skewing a mean": a single spike week amid
an otherwise-empty lookback window fails it even though it could inflate a
naive mean or a raw CTL reading on its own. No citation grounds the 0.75
fraction specifically — a deliberately generous majority threshold (allows
a real missed week, illness, or travel) without allowing a base to be
"established" by training in only a small minority of the window.

Deliberately does NOT gate on an absolute CTL magnitude (e.g. "CTL must
exceed N AU") — `load.py`'s own documented tiered sRPE/HR-TRIMP/pace-IF/
duration-only scale mismatch (see that module's docstring) means a single
AU threshold could not be trusted the same way across two athletes, or even
across one athlete's own history if which tier a given day resolves to
changes over time. The real `ctl_atl_tsb_series` CTL reading is still used,
but only as a cheap sanity floor (`> 0`, guarding a long-dormant history)
on top of the breadth check, not as the primary criterion.

**Test:** if a real athlete with a genuinely short (<12-week) but
clearly-consistent history keeps getting refused established-base status
in a case a coach would obviously call base-trained, revisit the lookback
multiple (3 tau ≈ 95% is the more conservative alternative the same math
already implies) rather than inventing an unrelated number.
