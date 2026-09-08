# Cycling periodization frameworks and interval-session taxonomy

See `00-conventions.md` for the tagging scheme and `reference_list.md` for
full citations. Extends `23-cycling-training.md` — split into its own file
to stay under that file's word-count cap (`00-conventions.md`'s "topic
files stay <= ~2,500 words" rule), matching this project's existing
precedent of splitting a topic out rather than trimming content
(`15-tiered-session-load.md` split out of `03-periodization.md` for the
same reason).

**UNREVIEWED.** `engine/cycling-coach` branch, continuing the stage after
PR #167 (CI-green at `76e7caf`). Written to close two gaps `plan.py`'s bike
functions already document as **known, deliberately unfixed limitations**
from PR #167's own red-team review:

1. `_bike_week_sessions`'s block-interpolation math (`plan.py`, the
   `# KNOWN LIMITATION (PR #167 red-team review...)` comment above
   `frac = (week_index_in_block + 1) / weeks_in_block`) climbs volume every
   week from `base` straight through `peak` with no periodic deload/
   recovery week built in.
2. `_bike_session_structure`'s own docstring (`# KNOWN, DOCUMENTED
   LIMITATION (PR #167 red-team review...)`) generates one flat generic
   power block for every week's differentiated session regardless of week
   or discipline — contradicting `23-cycling-training.md`'s own Protzen et
   al. (2026) warning that MTB/CX sessions need surge/interval-shaped
   content, not a single steady watt target.

This file grounds the citable research content that closes both gaps.
**Wiring either into `plan.py` is explicitly deferred to a future build
stage** — this pass is research/library only, matching this project's own
established "library grounds constants, then engine code cites the
library" sequencing (see how `23-cycling-training.md` itself was drafted
before `zones.py`'s bike code existed).

**Sport scope: `bike`.** Same guidance-scoping constraint as
`23-cycling-training.md` — never surfaced to a swim-only athlete. See that
file's header for the structural enforcement mechanism (`Athlete.
effective_sports`, `context.py`'s `filter_files_by_sport_scope`); this
file is intended to inherit the identical routing treatment once wired in.

**Provenance note on real-plan grounding:** the interval-session taxonomy
below is derived from a real, already-approved, already red-team-reviewed
macrocycle and first training block belonging to an actual masters
cyclocross athlete (`../ai-coach/athlete/plans/current/macrocycle.md` and
`block-01-reset-race1.md` — a sibling app's real athlete intake, read but
not modified by this pass; already credited in this repo's README for the
same "leverage away, credit as due" precedent). What is extracted below is
the generalizable interval-shape **pattern** — durations, work:rest
ratios, %FTP bands, and which taxonomy category each belongs to. That
athlete's specific FTP anchor, specific watt targets, and race calendar
are his own personal profile data, not library content, and are
deliberately **not** reproduced here.

## Framework grounding: polarized distribution and block periodization

**`[ADAPTED: general-endurance]`** Per `Seiler S. (2010)`, "What is Best
Practice for Training Intensity and Duration Distribution in Endurance
Athletes?," *International Journal of Sports Physiology and Performance*,
5(3):276-291: elite endurance athletes' logged training converges on a
"polarized" distribution — roughly 80% low-intensity, 20% high-intensity,
with deliberately little time spent in the moderate ("grey zone")
intensity band that is neither restorative nor a strong enough stimulus to
be worth its fatigue cost. **Confidence: high** (near-1,100-citation
synthesis, but a multi-sport review, not a cyclist-specific trial).
**Test:** if a week's actual logged intensity distribution drifts toward
several moderate-intensity days rather than a clear hard/easy split,
that's the pattern this source predicts will plateau performance —
treat it as a signal to re-sharpen the hard/easy contrast, not to add more
moderate volume.

**`[ADAPTED: general-endurance]`** Per `Issurin V. B. (2008)`, "Block
periodization versus traditional training theory: a review," *The Journal
of Sports Medicine and Physical Fitness*, 48(1):65-75: concentrating
training on a narrow set of targeted qualities for a defined block, rather
than trying to develop many qualities simultaneously, exploits each
quality's residual training effect and avoids the conflicting-adaptation
problem of long, generalized mixed blocks. **Confidence: medium**
(theory/review-level, not an empirical cycling trial). **Test:** if a
concentrated block consistently underperforms a more traditional
distributed approach for a given athlete's own power/threshold trend, that
is athlete-specific signal worth weighing against the model, not grounds
to assume the block itself was designed wrong.

`Galán-Rioja et al. (2023)` (already cited in `23-cycling-training.md`)
independently corroborates that concentrated block periodization is
actually used, and works, in trained cyclists specifically — 1-8-week
block lengths in the reviewed literature — which is real cycling-native
evidence for the block *shape* even though Issurin's own foundational
paper is not itself a cycling-specific trial.

## Closing the deload-cadence gap

None of the three sources above, nor `Galán-Rioja et al. (2023)`, specify
a validated numeric deload-week cadence (e.g. "every 3rd week") — the same
kind of honest gap `23-cycling-training.md` already documents for
week-to-week volume-progression rate. `Coach judgment:` a periodic
step-down cadence of roughly every 3rd-4th week (three build weeks, one
reduced-volume week), informed by Issurin's block-to-block restitution
concept and consistent with Galán-Rioja's observed 1-8-week block-length
range, is a reasonable default **pending explicit athlete/coach
confirmation** — not a citation-backed number. This is the same posture
`23-cycling-training.md` already takes toward its own uncited ramp-cap
gap: label it plainly as a coaching decision, not a finding.

This closes the *grounding* half of `plan.py`'s documented deload gap; the
*implementation* half (an actual scheduled deload week inside
`_bike_week_sessions`'s block-interpolation math) remains explicitly
deferred to a future build stage, per that function's own comment.

## Interval-design taxonomy (Laursen & Buchheit)

**`[ADAPTED: general-endurance]`** Per `Buchheit M., Laursen P. B. (2013)`,
"High-Intensity Interval Training, Solutions to the Programming Puzzle"
(Parts I & II, *Sports Medicine*, 43(5):313-338 and 43(10):927-954) and
`Laursen P., Buchheit M. (2019)`, *Science and Application of
High-Intensity Interval Training*, Human Kinetics: an interval session's
physiological target is set primarily by work-bout **duration** and
**work:rest ratio**, not by intensity alone. Long, near-continuous bouts
target sustained lactate-threshold-adjacent adaptations. Short, fixed-
ratio "short-short" formats (e.g. 30s/15s, 40s/20s on/off) exploit
VO2-kinetics priming — the off-period is too brief for oxygen uptake to
fully fall — to accumulate more total time at/near VO2max, at lower
per-repetition neuromuscular cost, than one long continuous bout at the
same intensity would produce. **Confidence: high** (the standard
HIIT-programming reference text across endurance sports; not cycling-
specific trial data). **Test:** if an athlete's short-short set shows
material power/HR decay by the final reps of a block (a specific, checkable
per-rep drop), that's the taxonomy's own signal the block is too long or
the recovery too short for that athlete on that day — stop the block
rather than pushing through, per the same logic block-01's own
`block-01-reset-race1.md` reference sessions already apply informally
("if power on rep 4 drops more than 5% below rep 1, stop the set").

The four named session formats below are this taxonomy's principles
instantiated as specific, reusable %FTP-band/duration templates — the
specific instantiation (exact seconds, exact %FTP band width) is
`Coach judgment:` practitioner convention layered on the taxonomy's
general principles above, not a verbatim quote from Laursen & Buchheit.
%FTP bands reference `23-cycling-training.md`'s own Coggan zone table
(Z2 Endurance 56-75%, Z3 Tempo 76-90%, Z4 Lactate Threshold 91-105%, Z5
VO2max 106-120%) so the two files stay internally consistent.

### Sustained threshold

Continuous work bouts of roughly 8-12 minutes at ~91-100% FTP (upper Z4),
2-3 reps per session, with near-full recovery between reps. The "long
interval" end of the taxonomy above — targets lactate-threshold-adjacent
adaptations with a different fatigue profile than the short-format
sessions below (fewer, longer, more mentally demanding bouts rather than
many short ones).

### Over/unders

Continuous blocks of roughly 6-8 minutes built from alternating ~90-second
sub-threshold ("under," ~76-85% FTP, upper Z2/low Z3) and ~90-second
supra-threshold ("over," ~100-105% FTP, low Z4) work, 2-4 blocks per
session with recovery between blocks. Targets lactate production/
clearance under a fluctuating load rather than at one fixed intensity —
"over/unders" as a named format is cycling-coaching practitioner
convention applying the taxonomy's work:rest/intensity-fluctuation
principle, not a term used verbatim in the Laursen & Buchheit source
itself.

### Short-short (VO2)

Short, fixed-ratio work:rest bouts — roughly 30-40 seconds on, 15-20
seconds off — at ~106-118% FTP (Z5), repeated in sets of 8-12 reps, 1-2
sets per session with several minutes of easy recovery between sets. This
IS the taxonomy's own directly-documented "short-short" format (see
above) — the closest of the four templates to a literal citation rather
than a practitioner adaptation of a general principle.

### Race-pace / long VO2

Bouts of roughly 2-3 minutes at ~105-114% FTP (the Z4/Z5 boundary), 3-5
reps per session, with near-full recovery between reps. Bridges the
threshold and VO2max stimuli and approximates the effort/recovery cadence
of a short, punchy race format (e.g. cyclocross's repeated short hard
efforts) more directly than either of the two formats above — a
practitioner-convention race-specificity application of the same
duration/ratio principle, not a distinct physiological mechanism from
"short-short."

## Deferred to a future build stage

Not attempted in this pass, consistent with the task scope: wiring any of
the periodization/deload-cadence guidance or the four interval templates
above into `plan.py`'s `_bike_week_sessions` (deload cadence) or
`_bike_session_structure` (interval-shaped `WorkoutStructure` content,
selected by week/discipline instead of the current flat single-block
default) is real future engine work, not attempted here. No `plan.py`
changes were made by this pass.
