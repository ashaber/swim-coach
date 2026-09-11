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

## A second macro shape: established-base, short-runway sharpening

`swim_coach.plan.scaffold_sharpening_macro`'s **hold -> sharpen -> taper**
shape — a second, deliberately DIFFERENT periodization shape from
`scaffold_macro`'s own base->build->peak->taper, for the athlete who
already has a real training base but not enough runway for that shape —
reuses this file's own Issurin (2008) block-periodization citation and
`sharpen`-block interval content, but is documented in its own file,
`25-macro-sharpening-established-base.md`, to stay under this file's own
word-count cap. See that file for the shape itself, the derived
`SHARPENING_MIN_MACRO_WEEKS` minimum runway, and the separately-flagged-
PROVISIONAL established-base detection threshold
(`swim_coach.load.has_established_training_base`).

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

### Openers / pre-race primers (taper)

Grounds `plan.py`'s fifth interval template, `"openers"`
(`_bike_openers_main`, `BIKE_OPENERS_*`), selected instead of the rotation
pick when a race is within `BIKE_OPENERS_PROXIMITY_DAYS` or the week is a
`"taper"` block (`_select_bike_interval_template`'s `use_openers`) — the
WEEKLY hard-day's own shape during that block. **Build E revision:** each
rep is now a progressive RAMP (`BIKE_OPENERS_RAMP_Z3_S`/`_Z4_S`/`_Z5_S` —
Z3 build, into Z4, into a brief Z5 top-end), not the original flat "1-2
min a touch above threshold" repeated bout — Andrew's own real pre-race
practice. A SEPARATE standalone day-before-race primer session
(`_bike_prerace_primer_session`, additive, not a rotation pick) reuses
this ramp unit at a short, nominal duration; see `16-race-week.md`'s "Bike
pre-race primer" section for that session's own grounding.

**`[ADAPTED: general-endurance]`** `Bosquet L., Montpetit J., Arvisais D.,
Mujika I. (2007)`, "Effects of tapering on performance: a meta-analysis,"
*Medicine & Science in Sports & Exercise*, 39(8):1358-1365: the optimal
taper reduces training VOLUME 41-60% while INTENSITY is held.
`Mujika & Padilla (2003)` concurs — volume down up to 60-90%, intensity
kept. A pre-race week keeps race-intensity contact (the ramps) while
`BIKE_TAPER_INTENSITY_VOLUME_REDUCTION` pulls weekly volume down.
**Confidence: high.** The REP SHAPE (ramp vs. the original flat-bout
convention) is `Coach judgment:`, same footing as the four templates
above. **Test:** if race power the week after an openers taper reads
flat, the taper is too deep or the ramps too sparse — add a rep, not
volume.

### Hard-day density ceiling (the realism guardrail)

Grounds `plan.evaluate_week_realism`'s `BIKE_MAX_HARD_DAYS_PER_WEEK` (3).
Per `Seiler (2010)` above, elite endurance training converges on ~80%
low / ~20% high intensity; for a cyclist on ~5-6 days/week that ~20% is
about three hard sessions, and a fourth pushes toward the "several
moderate days" pattern Seiler's own **Test** line flags as a plateau
predictor. Races are additive and don't count.
`BIKE_MAX_BIKE_DAYS_PER_WEEK` (6) is `Coach judgment:` only. The guardrail
FLAGS to the coach; it never clamps.

## Ramp test protocol and FTP formula (threshold-history build)

Grounds `plan.py`'s `_bike_ramp_test_structure`/`ftp_from_ramp_test` -- a
real, dedicated FTP-establishing test for when no current reading exists
at all (distinct from the "doubles as a fitness check" purpose-text note
`_bike_week_sessions` attaches to an ordinary sustained-threshold session
when the athlete's current FTP is only an estimate, not a fresh test --
see that function's own docstring; Andrew's own real block-01 (Tim's app)
embeds the latter, not a dedicated ramp test, precisely because his own
FTP was already reasonably well-known).

**Protocol.** A few minutes of easy warm-up spinning, then a continuous
ramp: start around 100W (or roughly 50% of an already-estimated FTP if one
exists), increase 20W every minute, continue to voluntary failure --
typically 8-25 minutes total including the build, depending on fitness.
**✓ Verified by direct fetch this session.** Roadman Cycling's own "How to
Do a Ramp Test for FTP" guide states this plainly: "A common structure
starts around 100W (or roughly 50% of estimated FTP) and adds 20W per
minute," each stage lasting one minute, with warm-up described only as "a
few minutes of easy spinning... enough" (no exact figure given). This
matches the same step-rate/starting-wattage convention TrainerRoad and
Zwift's own ramp tests use.

**FTP formula: 75% of best 1-minute power.** Take the athlete's best
1-minute average power reached during the test (typically the final
completed or near-completed stage); FTP = that value x 0.75. Worked
example from the same source: "If your final minute averaged 320W, your
FTP estimate is 240W." **`Coach judgment:` treat this as a genuine,
directly-fetch-confirmed practical resource (this file's own reference_list.md
"Practical / non-journal resources" tier), NOT an `[EVIDENCE]`/`[ADAPTED]`
claim** -- despite extensive searching this session (multiple queries
across CycleCoach.com, TrainerRoad, Roadman Cycling, Zwift Insider, and a
general academic-publication search), no peer-reviewed journal paper
establishing this specific 72-77%/75% figure could be located. It traces
to Ric Stern (CycleCoach.com; 25+ years as a cycling coach and sport
scientist) -- ✓ verified by direct fetch this session against his own
site: his "Ramp Testing" article (cyclecoach.com/blog/2019/1/13) states
"you can use it to estimate your FTP. This would usually be in the 72 to
77% range," describing this as his own quantified observation from ramp
testing at the University of Brighton, not a citation to a separate,
independently-published study -- his site's own bio page (cyclecoach.com/
ric-stern, direct-fetch confirmed) similarly credits him only with having
"developed early ramp-test-based models for estimating sustainable
threshold power from maximal aerobic power (MAP)... that later informed
widely adopted MAP-to-FTP conversion approaches," with no journal citation
attached. **Confidence: medium** -- a real, named, credentialed
practitioner-expert's own directly-fetched, cross-confirmed figure
(Roadman Cycling's independent description of "well-established and used
across TrainerRoad and Zwift" corroborates the same 75% number), but
resting on his own stated coaching-practice experience rather than a
citable peer-reviewed trial. **Test:** if an athlete's ramp-test-derived
FTP consistently overshoots what a subsequent real-world sustained effort
(a race file, or the embedded threshold-check session above) can actually
hold, that is this athlete's own individual-variation signal (the 72-77%
range itself, not just the 75% midpoint) -- prefer the real sustained
effort over the ramp-test estimate going forward, per `ThresholdRecord`'s
own "coach judges trustworthiness, engine never auto-picks" design.

The ramp itself is genuinely continuous in the real protocol only at the
per-minute-stage level (a new fixed wattage each minute, not a smooth
line) -- `plan.py`'s `_bike_ramp_test_structure` approximates this as one
continuous linear ZWO `<Ramp>` element over a fixed 20-minute window
(`Coach judgment`, the middle of the observed 8-25 minute range) rather
than modeling 20 discrete one-minute steps; an athlete who fails before
reaching the ramp's end simply stops early, same as the real protocol's
own termination rule. See that function's own docstring for the full
engineering rationale.

## Implementation history

Every part of this file is now wired into `plan.py`: the deload cadence and
the interval-template rotation landed with PR #167 / `engine/cycling-coach`;
the ramp-test protocol/formula and the FTP-check purpose-text note landed
with the threshold-history build; the openers template, taper volume
pull-down, and the hard-day realism guardrail landed with `engine/week-
generator-realism` (Build A); the ramp-shaped openers rep and the
standalone pre-race primer landed with `engine/race-week-content-
refinement` (Build E, see `16-race-week.md`). No open deferral remains.
