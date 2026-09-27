# Multi-race-season periodization: chaining several goal races into one plan

See `00-conventions.md` for the tagging scheme and `reference_list.md` for
full citations (new "Multi-race-season periodization" section there).
Grounds `engine/swim_coach/plan.py`'s `scaffold_season_macro` — the
multi-race-season-macro build, 2026-09-14.

**Sport scope: `bike`.** Same guidance-scoping intent as
`23-cycling-training.md`/`24-cycling-periodization-intervals.md`/
`25-macro-sharpening-established-base.md` — never surfaced to a swim-only
athlete. `scaffold_season_macro`'s own docstring requires every race passed
to it to share one `primary_sport`, and its real call site (this build) is
scoped to `primary_sport="bike"`, matching `scaffold_sharpening_macro`'s
own existing scope boundary. `context.py` routing wiring for this file
follows the same deferred-to-a-future-build-stage status `24`/`25`/`28`/
`29`/`30` already document for themselves — not done here.

**The real, grounded problem.** A logged feedback entry (2026-09-11)
documented a real athlete (Andrew, masters cyclocross) with FOUR real races
across roughly nine weeks, and a macro-planning system built around exactly
one target event per athlete — drafting a macro toward one race silently
orphaned whatever macro was already covering a different one. This file
asks: is there a real, citable, non-exotic way to periodize a season with
several goal races, and how much can a "peak" genuinely repeat within one
season? Short answer: yes — this is well-established, mainstream
periodization theory, not a novel problem, and the answer converges from
three independent angles below.


**UNREVIEWED**, pending human review.

## Not every race is an A race

**`[EVIDENCE: cycling]`** Per a Roadman Cycling interview with Joe Friel
(August 2025, see `reference_list.md` — a secondary-source interview
restating his own coaching position from *The Cyclist's Training Bible*,
not the book itself), Friel's A/B/C race-priority framework is the
mainstream cycling-coaching answer to a multi-race season: an A-priority
race gets the full periodization treatment and a real taper; treating
every race on the calendar as an A race "makes a real peak difficult." His
own stated cardinality: one A-priority race per season is the clearest
option, two is possible if separated by several months, and three or more
is "increasingly difficult" — the article's own framing, quoted directly
rather than smoothed over: this is Friel's coaching position in an
interview, "not... a physiological law." Since this is native cycling
coaching guidance applied to a cyclist (Andrew), the claim above carries
the native-discipline evidence tag rather than the cross-discipline
adaptation tag `00-conventions.md` reserves for a claim borrowed from an
outside sport (see that file's own tag-scheme section for the
distinction).

This directly grounds `scaffold_season_macro`'s graduated per-race depth:
only an "A"-priority race gets the full three-way shape (`scaffold_macro`'s
base->build->peak->taper, or `scaffold_sharpening_macro`'s hold->sharpen->
taper for a shorter runway) — the SAME shape a single-race macro already
gets, unchanged. "B"/"C" races never grow a full peak, matching Friel's
"don't treat every race as an A race" position directly, not a coaching
default invented for this build.

**Coach judgment**, not itself part of Friel's own framework: `Event.
priority` (this codebase's existing free-text "A"/"B" convention, already
used by `RACE_WEEK_PRIORITY`) is read case-insensitively, and any value
that isn't recognizably "A" or "B" (including "C", blank, or a typo) is
treated as the C-tier default — no dedicated block at all, race for
training/experience. This mirrors Friel's own C-race guidance (don't alter
the plan, don't taper) without requiring a third, format-validated enum
value on a field that has always been free text.

## A season CAN have multiple peaks — this is not exotic

**`[ADAPTED: general-endurance]` Confidence: medium.** Per Bompa (1999),
*Periodization: Theory and Methodology of Training*, 4th edition (Human
Kinetics — see `reference_list.md` for the verification-tier note: the
primary text was not freely fetchable this session, confirmed instead via
a direct-fetched secondary source that quotes the specific
title/author/edition/year directly), an annual training plan is not always
one continuous macrocycle: it can be mono-cyclical (one preparatory ->
competitive -> transition cycle), bi-cyclical, or tri-cyclical/multiple,
depending on how many major competitions the season actually has. When 3-5
major competitions fall within one year, a double or multiple
periodization structure — several distinct, smaller cycles chained across
the season rather than one long one — is the standard model, not an
exception. Bompa's own caveat carries forward too: more frequent peaking
means more cumulative stress, so races still need real prioritization even
within a multi-cycle season (the same point Friel's A/B/C framework makes
from the cycling-coaching side). **Test:** if `scaffold_season_macro`'s
chained-cycles output, run against a real athlete's calendar, produces
week-to-week volume swings that read as choppier or less coherent than a
coach's own hand-built multi-peak season would, that's real signal the
CHAINING boundary itself (not just one block's own sizing) needs revisiting
— not grounds to assume a single continuous macro was the right shape for
a multi-race season after all.

This is the direct grounding for `scaffold_season_macro`'s core design
choice: a CHAIN of per-race mini-cycles (each one calling the existing
`scaffold_macro`/`scaffold_sharpening_macro`, unchanged) rather than one
continuous macro stretched across every race, or a single new giant block
shape invented for this build. Andrew's real season — four races in about
nine weeks — is squarely inside Bompa's own "3-5 major competitions"
range.

## How much can a taper/peak repeat within one season?

This is the concrete engineering question `scaffold_season_macro`'s
`MINI_TAPER_WEEKS`/`B_TIER_MAX_DEDICATED_WEEKS` constants answer, and it
resolves from sources this codebase already cites, reused rather than
re-derived:

**`[ADAPTED: general-endurance]` Confidence: medium.** `Mujika I., Padilla
S. (2003)` (already cited in `reference_list.md` and `24-cycling-
periodization-intervals.md`), "Scientific bases for precompetition
tapering strategies," *Medicine & Science in Sports & Exercise*, 35(7):
1182-1187: taper duration studied across the literature spans **4-28
days**, with volume cut 60-90% and intensity/frequency mostly held. A
B-priority race's own shallower `MINI_TAPER_WEEKS = 1` (7 days) sits at
the SHORT end of that same studied range — not below it, not a number
invented outside what the literature actually examined — reusing the
exact same `TAPER_WEEKLY_DECAY` per-week decay rate `scaffold_macro`'s own
2-week `TAPER_WEEKS_SHORT` A-race taper already uses, just applied for one
week instead of two (a ~25% volume cut instead of ~50%). This is a
genuinely shallower pull-down for a lower-priority race, not the same
taper relabeled. **Test:** if a B-priority race's 1-week mini-taper
produces visibly flat/underpowered racing relative to what the athlete's
current fitness should support, that's real, athlete-specific signal the
mini-taper is too shallow for THIS athlete — worth lengthening toward
`TAPER_WEEKS_SHORT` (the full A-race depth) for that specific race next
time, not grounds to assume the studied 4-28-day range itself is wrong.

**`[ADAPTED: general-endurance]` Confidence: high.** `Bosquet L.,
Montpetit J., Arvisais D., Mujika I. (2007)` (already cited in
`reference_list.md` and `24`), "Effects of tapering on performance: a
meta-analysis," *Medicine & Science in Sports & Exercise*, 39(8):
1358-1365: the optimal FULL taper is a ~2-week exponential volume
reduction of 41-60% — this is what an A-priority race's own unchanged,
full-depth taper already uses; nothing new derived here, just confirmed as
the correct ceiling a B-race's shallower pull-down should sit below, not
match. **Test:** if an A-priority race's own full 2-week taper stops
producing this meta-analysis's expected performance bump for a given
athlete over several seasons of real logged races, that is athlete-
specific signal worth weighing against the model — not grounds to shorten
a B-race's already-shallower taper further on the same evidence.

**`[ADAPTED: general-endurance]` Confidence: medium.** `Issurin V. B.
(2008)` (already cited in `24`/`25`), "Block periodization versus
traditional training theory: a review," *The Journal of Sports Medicine
and Physical Fitness*, 48(1):65-75: a concentrated mesocycle block runs
2-4 weeks. `scaffold_season_macro`'s B-priority "sharpen" phase reuses this
exact bound (`SHARPEN_WEEKS_MIN`/`SHARPEN_WEEKS_MAX`, already established
by `25-macro-sharpening-established-base.md`) unchanged — a B-race's
tune-up cycle is still Issurin's own transmutation block, never a longer,
different concentrated-training shape invented for a lower-priority race.
`B_TIER_MAX_DEDICATED_WEEKS` (capping how much runway a B-race's own
dedicated cycle ever consumes, regardless of how much sits in front of it)
is `Coach judgment:` — no source pins an upper bound on how much idle
runway should "count" toward a tune-up cycle before it becomes plain
maintenance instead; any excess becomes a flat hold block ahead of the
capped cycle rather than an unbounded, ever-growing tune-up block.
**Test:** same posture `25-macro-sharpening-established-base.md` already
takes toward this identical citation — if a B-priority race's capped
sharpen block consistently underperforms a longer build for a given
athlete's own real fitness trend, that is athlete-specific signal worth
weighing against the model, not grounds to assume the block itself was
designed wrong.

## Cyclocross-specific literature: genuinely thin, said plainly

Searched directly this build (Simple Endurance Coaching's cyclocross-
periodization blog, TrainerRoad's cyclocross training guide, and a general
web search for cyclocross-specific periodization/racing-frequency
research) and found no peer-reviewed, cyclocross-specific systematic
review of racing frequency, recovery demands, or multi-peak periodization
— the same honest gap `27-cyclocross-skills.md` already documents for CX
race-demand research generally ("no equivalent full systematic review" to
mountain biking's Protzen et al. 2026). What exists is real, credentialed
practitioner coaching advice (Paul Warloski, USA Cycling Level 1 Advanced
Certified Coach — see `reference_list.md`) making the same qualitative
point already covered above by Friel/Bompa (decide whether to peak once or
stay competitive all season; rebuild endurance between race blocks) but
with no cyclocross-specific quantified racing-frequency or taper-depth
number to add. Nothing in this section is cited as grounding for any
specific constant — it is recorded as an honest, searched-for-and-thin
result, per this file's own `Coach judgment:`/verification discipline,
leaning on the general-endurance sources above instead, clearly labeled as
such (per `00-conventions.md`'s framing rule for `[ADAPTED]` claims).

## Design mapping: how this became `scaffold_season_macro`

The engineering question this build actually had to answer was not "is
multi-peak periodization real" (yes, per Bompa above) but which of two
implementation shapes is less invasive: a `MacroPlan` that becomes
one-per-SEASON with multiple `event_id` slots and its own new storage
model, or a CHAIN of the existing single-race shapes stitched into one
`MacroPlan.blocks` list. The chain won: `generate_week`'s own block-
interpolation math already walks a flat `blocks` list with no notion of
which shape or which race a block belongs to, so concatenating several
race-cycles' worth of blocks is exactly what it already consumes,
unmodified — and the athlete's existing single `macro_plans` DB row (one
per athlete, unique on `athlete_id`) needed no schema change at all: the
season's extra structure (`MacroPlan.event_ids`, `MacroBlock.
race_event_id`) is additive and lives inside the existing JSONB `data`
column. See `scaffold_season_macro`'s own docstring (`plan.py`) for the
full per-race decision logic and the cursor-continuity property that keeps
the existing `WEEKLY_VOLUME_RAMP_CAP` safety rail enforced automatically
across every race-to-race transition, never bypassed by chaining.

## Short-event taper and in-season maintenance

Curated for `engine/swim_coach/plan_check.py`'s `check_macro` (PR 1 of the
engine/plan-check-red-team architecture change, 2026-09-27): a short
(<=~1.5h) cycling event's
taper is genuinely shallower/shorter than the general 8-14-day finding
above, not just an extrapolation from it — and a B-race's own mini-taper,
or a maintenance stretch between B races, does not cost real fitness.

**✓ Neary P. J., Bhambhani Y., McKenzie D. C. (2003)** — "Effects of
Different Stepwise Reduction Taper Protocols on Cycling Performance" —
*Canadian Journal of Applied Physiology*, 28(4):576-587. 11 male cyclists,
a 7-day taper at three volume-cut magnitudes (30%/50%/80%, intensity held
at 85% pretaper): the 50%-cut protocol produced a significant 5.4%
improvement in a simulated 20km time trial (a ~25-30 min effort); 30%/80%
did not reach significance. `[EVIDENCE: cycling]`, Confidence: medium (lab
TT, not a technical mass-start race). Directly grounds
`plan_check.SHORT_EVENT_TAPER_DAYS_MIN/MAX` (5-7 days) and
`SHORT_EVENT_TAPER_VOLUME_CUT_FRACTION` (0.50). **Test:** if a real
cyclocross A-race reads flat despite a much deeper cut than 50%, the
taper overshot depth, not necessarily duration.

**✓ Houmard J. A. (1991)** — "Impact of Reduced Training on Performance in
Endurance Athletes" — *Sports Medicine*, 12(6):380-393. Review: VO2max/max
workload maintained 10-28 days with volume cuts up to 70-80%; performance
maintained or improved with 60-90% cuts over 6-21 days, provided training
frequency drops no more than ~20%. `[EVIDENCE: cycling]`, Confidence:
medium-high. A 1-week B-race mini-taper (`MINI_TAPER_WEEKS` above) sits
comfortably inside this no-fitness-loss window — a real peer-reviewed
backstop for a constant this file previously grounded only via the Friel
interview. **Test:** if repeated B-race mini-tapers correlate with an
unintended downward CTL drift across a season, check the frequency cut
(not volume cut) first — Houmard's own caveat.

**✓ Rønnestad B. R., Hansen E. A., Raastad T. (2010)** — "In-season strength
maintenance training increases well-trained cyclists' performance" —
*European Journal of Applied Physiology*, 110(6):1269-1282. 1x/week
strength maintenance through 13 weeks of competition season preserved
prep-period strength/thigh-CSA gains with no negative effect on VO2max or
cycling economy. `[EVIDENCE: cycling]`, Confidence: high. Grounds this
project's between-B-races maintenance posture (~2x/week endurance-
intensity, ~1x/7-10 days strength — see the dossier this section is
condensed from, `library/research-dossiers/2026-09-26-season-taper.md`,
for the full cross-discipline maintenance-dose picture). **Test:** if threshold power
visibly slides across a multi-week B-race stretch at this dose, check
intensity fidelity first, not just frequency.

## What's not resolved

**The cross-sport swim-vs-cyclocross goal conflict is explicitly NOT
addressed here**, matching the original 2026-09-11 feedback entry's own
framing: it called this a decision for a human, not a research question,
and this build keeps that posture. `scaffold_season_macro` requires every
race passed to it to share one `primary_sport` and raises rather than
guess at cross-sport prioritization — Andrew's real swim goals (Quinn's
Halloween Spook Swim, currently `active=False` in the real DB as of this
build) and his real cyclocross season are still two separate questions a
coach/athlete decision needs to reconcile, not something this chained-
macro design resolves by construction. A clean single-sport season design
does make the SHAPE of a future cross-sport answer clearer (each sport
could plausibly get its own season-macro, prioritized against each other
the same way races within one sport already are) — noted honestly as an
observation, not built or decided here.

**CX-specific racing-frequency/recovery research stays a real, stated
gap** (see above) — this build leans on general-endurance/cycling-native
sources throughout, clearly labeled, rather than inventing CX-specific
numbers no source actually supports.

**`generate_week`'s own per-week event selection was not extended** to
automatically resolve which race a given week of a season-spanning macro
is building toward — `scaffold_season_macro`'s own docstring documents
this as an explicitly deferred follow-up, not silently dropped.
