# Open-water session-content templates

Grounds `engine/swim_coach/ow_session_templates.py`'s template library
(feed-window practice, out-and-back negative split, chop/wind adaptation,
sighting drill, breathing-pattern variation, back-to-back multi-day-stage
fatigue simulation, taper activation, race dress rehearsal) and its
`OWTemplateScaling` design. See `00-conventions.md` for the tagging scheme
and `reference_list.md` for citations — this file carries almost none,
deliberately: see "What this file is (and isn't)" below.

## Why this exists

`plan.py`'s `generate_week` leaves the week's actual long swim / stage
sessions with `structure=None`/`structured=None` — real distance, no real
content ("swim 6000m"). For an athlete going through a stretch of
open-water-only training with no pool-coach input to lean on (this
module's originating case), every session's actual content has to come
from somewhere. `ow_session_templates.py` is that library: general,
athlete-parameterized (by `distance_m`/`css_pace_s`, never hardcoded to one
athlete) session-content templates a coach (human or the LLM
session-authoring tool) can pick from by name, the open-water counterpart
to `plan.py`'s existing `_additional_swim_structure_template` (pool-
independent aerobic swim) and `_strength_session_structure_template`
(dryland strength) — same architectural pattern, new content domain.

Several of the underlying session IDEAS were adapted from an external
prompt-experiment (a colleague's Joe-Friel-periodization "advisory panel"
persona prompt, run through another model) — the fictional named-expert
panel framing and dramatic language ("boredom tolerance," "sensory-
deprivation coping mechanisms") were discarded entirely; only the
underlying mechanical shape of each workout (rep/rest structure, pacing
contrast, technique focus) was kept, rewritten in this project's own plain,
single-voice tone. See each template's `source_note` in the
`OW_SESSION_TEMPLATES` registry for exactly which idea it traces to.

## What this file is (and isn't)

Almost everything in this module is **Coach judgment**, not evidence-tagged
research — these are practitioner-convention session *shapes* (rep counts,
rest durations, warm-up/cool-down proportions), the same category as
`14-swim-set-structure.md`'s main-set format menu ("No verified source in
this pass ranks one format as superior"). Two exceptions genuinely cross-
reference real evidence already established elsewhere in this library, not
re-derived here:

- Feed-window practice's rationale (rehearsing feeding logistics at
  race-relevant pace/duration) leans on `08-ultra-feeding.md`'s existing
  in-swim-carbohydrate/gut-training section — that file owns the *what/how
  much to feed* evidence; this module only concerns itself with rehearsing
  the stop-and-restart mechanics.
- Back-to-back stage simulation's premise (training the body to swim well
  on already-accumulated fatigue) is the training-side analog of
  `06-long-swim-progression.md`'s `multi_day_stage` format section, which
  already documents why a stage event's second day is trained on the
  first day's fatigue (`STAGE_SATURDAY_SHARE`'s "fresher day gets the
  larger share" framing) — this module's Day 1/Day 2 templates are content
  for exactly those Saturday/Sunday sessions, not a new claim.

Nothing here claims `[EVIDENCE]`/`[ADAPTED]` status for a rep count, rest
duration, or warm-up share; every such number is Coach judgment, tagged as
such directly in `ow_session_templates.py`'s own comments (per this
project's "every engine constant cites its library file" rule — this file
IS that citation target, it just isn't citing a paper for most of them).

## Duration-floor design: `skill_scalable` vs `endurance_floor`

**Coach judgment (Andrew, applied-coaching insight, not a research
finding).** Every template in the registry carries an `OWTemplateScaling`
tag governing how aggressively its `distance_m` may be compressed — e.g.
by a taper week's volume-reduction pass — without losing the session's
actual training purpose:

- **`skill_scalable`** — negative-split pacing, chop/wind adaptation,
  sighting, breathing-pattern variation, taper activation. The skill being
  trained doesn't need full volume to fire: a 50% cut still rehearses the
  same pacing/technique judgment, just over less distance. Safe to scale
  down roughly proportionally with a taper factor. (Taper activation is
  the one exception with a *ceiling* rather than a floor —
  `TAPER_ACTIVATION_MAX_DISTANCE_M` — since it's deliberately short/sharp
  by design; scaling it *up* defeats its own purpose the same way
  under-flooring an endurance session does.)
- **`endurance_floor`** — feed-window practice, back-to-back stage
  simulation, race dress rehearsal. These exist to train something that
  only happens at real duration: fat-oxidation shift, gut/fueling training
  at race-relevant timescale, or durability under genuinely accumulated
  fatigue. A 6-hour endurance/fueling session cut to 3 hours does not
  "train half as much" — it may train nothing useful for its actual
  purpose, the same way a 30-second submaximal effort can't be "scaled
  down" from a 5-minute VO2max effort and still train VO2max. Each
  `endurance_floor` template therefore declares a `min_duration_min`
  (`FEED_WINDOW_MIN_DURATION_MIN` / `BACK_TO_BACK_MIN_DURATION_MIN` /
  `RACE_REHEARSAL_MIN_DURATION_MIN`, all 75-90 min) and its `build_*`
  function raises `ValueError` rather than silently building a session
  below that floor.

**These floors are deliberately well below a real race-day duration** —
they mark "long enough for the intended mechanism to plausibly occur at
all," not "as long as race day itself." A genuinely shorter EARLY-build
version of one of these sessions is fine and expected; what the floor
guards against is an aggressive *taper* cut applied mechanically to a
session whose purpose doesn't linearly scale with volume the way a
technique session's does. A caller needing a shorter session on a taper
day should reach for a `skill_scalable` template instead of forcing an
`endurance_floor` one under its documented floor.

**Test (falsifiable, not yet run):** if an athlete's own logged sessions
ever show a below-floor "cut" endurance/fueling session followed by
race-day fueling problems (GI distress, bonking) that a full-duration
rehearsal earlier in the build didn't produce, that's evidence the floor is
in the right place (or should be raised); if athletes report the floor
feels arbitrarily conservative with no downside from cutting further,
that's evidence it could be lowered. No such data exists yet — this is a
Day 1 design constant, not a calibrated one.

## Deliberate deviation from the source material: no eyes-closed sighting drill

The sighting-drill template's source idea included a brief eyes-closed/
no-sighting "drift awareness" component. This module deliberately drops
it — voluntarily swimming open water with eyes closed, even briefly, is an
avoidable real safety risk (losing orientation, a support boat/kayak not
expecting it) for training value fully achievable another way (the
frequent-vs-infrequent sighting-cost comparison the shipped template uses
instead). Not a citation-backed claim; Coach judgment, made explicit here
because it's a deliberate rejection of the source idea, not an oversight.
