# Race week: a distinct final phase layered on the taper block's last week

**UNREVIEWED** — drafted this session from citations verified by direct web
search (see `reference_list.md`'s "Race-week preparation" section, not a
research-dossier file); pending human review before treated as grounding
truth, per `00-conventions.md`.

Grounds `engine/swim_coach/plan.py`'s `_race_week_checklist()` and
`RACE_WEEK_PRIORITY`/`CARB_LOAD_WINDOW_START_DAYS_OUT`/
`BODYWORK_WINDOW_DAYS_OUT`/`RACE_WEEK_LOGISTICS_LABELS` constants, and
`models.RaceWeekChecklistItem`. Split out of `03-periodization.md` (which
was already at its word-count cap) rather than appended there — see
`00-conventions.md`'s file-size rule. See `00-conventions.md` for the
tagging scheme and `reference_list.md` for full citations.

**Not a new macro block.** A single week is too short a window to model an
entire taper on its own — `03-periodization.md`'s taper block already owns
that job — but the literature and this project's own practitioner
conventions both treat the final few days before an ultra-distance
open-water race as their own, more prescriptive checklist, distinct from an
ordinary taper week's "less volume, same intensity" framing. `plan.py`'s
`generate_week()` therefore layers a `WeekPlan.race_week_checklist` onto
whichever week already comes out of the taper block's own volume math
(`TAPER_WEEKS_LONG/SHORT`, `TAPER_WEEKLY_DECAY`, both unchanged by this
file) as its FINAL week, when that week immediately precedes the athlete's
active, priority-"A" target event. **This never changes a single
volume/duration number** — purely additive athlete-facing content.

## Why a dated checklist, not per-session prose

The two physiologically-timed windows below (carbohydrate loading,
bodywork) are pinned to specific offsets *before `Event.event_date`*, not
to "this week" in general. For a race that doesn't fall on a Monday — the
common case, and Renee's own 2026-09-18 UltraSwim 33.3 is a Friday — those
offsets can land on calendar days *after* the final taper week's own last
day, in the following week that contains the event itself (which
`scaffold_macro`/`generate_week` deliberately don't model as a block at all
— see `plan.py`'s module docstring). A `Session.date` can't represent a day
outside the `WeekPlan` it belongs to; a `RaceWeekChecklistItem.date`,
computed straight from `event.event_date`, can. Concretely, for Renee's
real macro (as of this writing): the final taper week runs 2026-09-07 →
2026-09-13, but her carb-load date computes to 2026-09-15 — two days
*after* that week ends — while her bodywork date (2026-09-13) lands exactly
on the week's last day. Both are real, precisely computed dates, not a
vague "eat more carbs this week."

## Carbohydrate loading — `CARB_LOAD_WINDOW_START_DAYS_OUT = 3`

**[ADAPTED: general-endurance] Confidence: high.** The strongest, most
precisely-timed evidence in this file. `Burke et al. (2011)` — "Carbohydrates
for training and competition" — *Journal of Sports Sciences*,
29(sup1):S17-S27 — the consensus review behind the now-standard **10-12
g/kg body weight/day for 36-48h before events lasting >90 minutes**, in
already well-trained athletes. `Bussau et al. (2002)` — "Carbohydrate
loading in human muscle: an improved 1 day protocol" — *European Journal of
Applied Physiology*, 87(3):290-295 — is the direct evidence that **no
depletion phase is needed**: 8 endurance-trained athletes reached
near-maximal muscle glycogen (95 → 180 mmol/kg wet mass) within a single
day of 10 g/kg/day high-glycemic-index carbohydrate combined with rest;
two further days of the same diet added no further store. Both verified by
direct web search this session (title/authors/journal/volume/pages/
findings confirmed).

`generate_week` marks the window's earlier (72h-out) edge as a single
calendar day computed from `event.event_date` — PROVISIONAL: collapsing a
36-72h *duration* to one whole-day marker is Coach judgment (an event's
exact start time isn't modeled by `Event` today), chosen deliberately
conservative (earlier, not later) so the athlete has the full window rather
than being told to start on its most time-pressured day. **Test:** if a
future athlete's actual race start time is known, this could be refined
from a whole-day marker to an hour-precise one.

## Bodywork / massage — `BODYWORK_WINDOW_DAYS_OUT = 5`

**[ADAPTED: general-endurance] Confidence: medium** for the underlying
soreness/psychological-benefit claim; **Coach judgment / practitioner
convention, NOT a performance citation** for the specific 3-5-day timing.
`Weerapong, Hume & Kolt (2005)` — "The Mechanisms of Massage and Effects on
Performance, Muscle Recovery and Injury Prevention" — *Sports Medicine*,
35(3):235-256 — and the more recent `Dakić et al. (2023)` systematic
review, "The Effects of Massage Therapy on Sport and Exercise Performance"
— *Sports*, 11(6):110 — both converge: massage shows **little to no
evidence of a direct performance benefit**, but a real, consistent
reduction in perceived soreness/fatigue and psychological benefit (lower
anxiety/stress, improved mood and perceived recovery). Both verified by
direct web search this session. This is deliberately **not** oversold as a
performance intervention anywhere it's surfaced athlete-facing (see
`plan.py`'s `BODYWORK_WINDOW_DAYS_OUT` comment and the checklist item's own
label text).

The specific "3-5 days out, light activation/relaxation rather than deep/
aggressive work" TIMING is separate and weaker: it is widespread
sports-massage-practitioner convention (deep work needs recovery time of
its own; too close to race day risks race-day soreness; too far out loses
the perceived-relaxation benefit) — **not independently verified against a
journal source this session**. `generate_week` picks the window's earlier
edge (5 days out, matching `CARB_LOAD_WINDOW_START_DAYS_OUT`'s own
earlier-edge choice above, for the same more-buffer rationale) — for a
Friday race like Renee's, this happens to coincide with the final taper
week's own last (Sunday, recovery-day) session, though that's a consequence
of her race's specific weekday, not a designed alignment. **Test:** if a
future athlete's own feedback (soreness reported the following days,
wellness-composite dip) suggests this window runs too close to race day for
her, treat it as this-athlete-specific evidence to push the window earlier,
not as evidence against the mechanism itself.

## Logistics checklist — generic, event-data-driven (not hardcoded to one athlete)

**Coach judgment**, not evidence-tagged at all — these three-to-four items
(`plan.py`'s `RACE_WEEK_LOGISTICS_LABELS`, plus a conditional
water-temperature/wetsuit item when `Event.water_temp_c` is set) are
generic race-day-logistics prompts derived from the `Event` model's own
generic fields (travel/time-zone/water-temperature acclimatization, a final
fueling-plan rehearsal against whatever in-race carbohydrate protocol the
athlete has actually practiced, on-water support-crew/kayak confirmation).
They read as directly relevant to Renee's own Greece trip specifically
because her real `Event` data (open-water, 24°C, no wetsuit, requiring
travel and kayak support — see `athletes/renee/notes/decisions.md`'s
2026-07-05 entries and `athletes/renee/plan/weeks/2026-W29.yaml`'s existing
"kayak support" dress-rehearsal precedent) is what it is, not because any
athlete-specific noun is hardcoded into the engine. Anchored to the final
taper week's own Monday (`week_start`) rather than a computed date from
`event.event_date` — deliberately: these have no single
physiologically-critical day the way carb-load/bodywork above do, so Coach
judgment says settle them EARLY in the final week, clearly separated in
time from the two evidence-timed windows above.

## Bike pre-race primer — `_bike_prerace_primer_session` (Build E)

**Sport scope: `bike`.** Grounds `plan.py`'s standalone pre-race primer
session (`engine/race-week-content-refinement`) -- a real defect found in
Andrew's first real taper/race week: the engine's only "openers" content
was a swap of the week's REGULAR hard-day session (`_bike_openers_main`,
`24-cycling-periodization-intervals.md`'s own "Openers" section), which
lands wherever `training_days["bike"]` already puts the hard day -- for
Andrew, 4 days before a Saturday race, not the day before (Friday) as
real pre-race practice expects. `_bike_prerace_primer_session` is a
SEPARATE, additive session placed exactly one day before EACH race date
in `in_week_race_dates` (or the following week's Monday-race edge case,
via `generate_week`'s own lookahead check) -- it does not replace the
regular hard-day swap, which still governs the rest of a taper block that
has no race in the current week.

**Timing — the day before, not "sometime in taper week":**
**`[ADAPTED: general-endurance/multi-sport] Confidence: medium.**` Per
`Pereira et al. (2025)`, "Priming Exercises and Their Potential
Impact on Speed and Power Performance: A Narrative Review," *Journal of
Human Kinetics*, 98:153-168 (see `reference_list.md`): a brief,
non-fatiguing high-intensity "priming" bout produces its most pronounced
neuromuscular-readiness effect at specifically the 6h and 24h marks
before competition, distinct from an ordinary warm-up closer to the
event. Placing this session exactly one day (~24h) before the race sits
directly on that window. **Confidence: medium** — the review's own
population is mostly team-sport speed/power athletes, not endurance
cyclists, and no cycling-specific priming trial was located; the timing
principle (not the cycling-specific shape) is what transfers. **Test:**
if this athlete's race-day form/legs feel flat specifically after a
day-before primer versus a race with no primer at all, that's
athlete-specific signal against the ~24h timing, not against priming as a
concept.

**Shape and duration:** reuses `24-cycling-periodization-intervals.md`'s
own progressive-ramp unit (`BIKE_OPENERS_RAMP_Z3_S`/`_Z4_S`/`_Z5_S`) —
`BIKE_PRERACE_PRIMER_REPS` = 3 ramps, full recovery between, wrapped in a
short easy warm-up/cool-down (~25-30 min total). `Coach judgment:` the
exact rep count and total duration — deliberately NOMINAL (not
proportional to weekly volume, same posture `27-cyclocross-skills.md`'s
skills day already takes), since the day-before-race point is
neuromuscular readiness, not a training stimulus. Counts as a "hard" bike
day structurally (top-level `BIKE_OPENERS_ZONE`/"Z4") so it still
protects itself under `_strength_offsets_after_hard` and the hard-day
guardrail — a real, if brief, intensity-touching session, not a rest day.

## Race-week midweek fill — light content instead of an empty week

**Sport scope: `bike`.** Grounds `plan.py`'s race-week midweek fill
(`_bike_midweek_quality_session`/`_bike_midweek_easy_session`/
`_bike_race_week_fill_offsets`, `engine/race-week-fill`). Real gap found
comparing this engine's output against a real, already-validated AI coach
tool (a sibling app Andrew also uses) for the identical week shape
(skills day, openers-adjacent day, easy day, rest day, pre-race primer,
two race days): `generate_week`'s `in_week_race_dates` branch built
`core_bike_sessions` as ONLY the pre-race primer above -- every other
weekday was silently empty. The reference tool's real output for that
shape kept a light two-tier structure through the week instead:

| Day | Reference tool | Content this fixes it to |
|---|---|---|
| Mon | easy + skills primer | skills day (already correct, unchanged) |
| Tue | openers, ~30 min | midweek quality touch |
| Wed | easy spin, ~45 min | midweek easy spin |
| Thu | rest | (no session -- implicit rest) |
| Fri | pre-race openers | pre-race primer (already correct, unchanged) |
| Sat/Sun | race | race (already correct, unchanged) |

The reference tool's own minute/load numbers are `Coach judgment`
REFERENCE POINTS for shape and rough scale, not a spec matched exactly --
its load units aren't this engine's sRPE-based ones, so "close in spirit"
is the right bar, not byte-for-byte parity.

**Midweek quality touch:** reuses the SAME progressive-ramp unit as the
Friday primer (`_bike_openers_ramp_unit`, this file's own section above,
grounded in `24-cycling-periodization-intervals.md`'s Openers section) at
`BIKE_MIDWEEK_QUALITY_REPS` = 4 -- one more rep than the primer's 3, so it
reads as genuinely MORE quality contact than the day-before-race session
while staying well short of a real interval day. `Coach judgment:` the
exact rep count -- the reference tool's numbers for this slot (its own
load units, ~30 min) sit between its easy spin and a normal hard day,
which is the qualitative target this hits, not a number to reproduce
exactly.

**Midweek easy spin:** `BIKE_MIDWEEK_EASY_MIN` = 40 min at Z2, reusing
`_bike_session_structure` -- the SAME flat-single-zone builder
`_bike_final_taper_sessions`'s own easy day already uses (no new
easy-session builder invented). `Coach judgment:` 40 min sits in the
reference tool's ~30-45 min range for this slot, erring slightly lighter
since this is still a taper/race-proximate week.

**Rest day:** deliberately NO synthesized placeholder session -- matches
this engine's own existing convention (a swim week's rest day is simply a
day with no `Session`, not a zero-load stub). The reference tool's own
"rest + halo" convention names a specific shoulder-mobility routine this
engine has no equivalent content for; inventing halo-specific content was
explicitly out of scope for this pass.

**Placement:** up to 2 days (quality touch, then easy spin, in that
order), chosen from whatever days aren't already claimed by a race date,
the primer, or a skills day. When the athlete has a `training_days
["bike"]` weekday pattern, its declared order is honored (filtered to
free days); without one, the earliest free days in the week are used
(Mon->Sun ascending) -- same "respect the pattern when set, else spread
early" precedent `_spread_days_evenly` already establishes elsewhere in
this file's own bike-week machinery. Deliberately capped at 2, not "fill
every free day": this adds LIGHT touches on top of an already-cut taper
week, not a second normal week's worth of content -- any further free day
stays genuinely empty. The taper's own volume-cut principle (Bosquet
2007, this file's primer section above) stays intact: a race week's total
non-race bike training minutes remain well below a normal week's, even
with these two light additions.

## Gating: active, priority "A", same event as the macro, final taper week only

`generate_week`'s optional `event` parameter only populates
`race_week_checklist` when ALL of: `event.active` is `True`, `event.priority`
(case-insensitively) is `"A"` (`RACE_WEEK_PRIORITY`), `event.id ==
macro.event_id` (the macro this week belongs to was actually scaffolded
toward this same event, not a different one on the athlete's calendar), AND
this is the taper block's LAST week. `Event.priority`/`Event.active` are
otherwise never gated on anywhere else in this engine (see each field's own
docstring in `models.py` — `active` explicitly "changes how the coach
*talks about* events ... never which events lookups find") — this is a
deliberate, new departure from that precedent: firing an athlete-facing
race-week checklist for a B-priority tune-up race, or for an event that's
been soft-deleted/deactivated, would be actively wrong content, not merely
stale data. An ordinary taper week (any week that isn't the block's last),
any non-taper week, a missing `event` argument, a wrong/inactive/non-"A"
event, or an event that doesn't match the macro's own `event_id` all leave
`race_week_checklist` at its default empty list — see
`tests/unit/test_plan.py`'s race-week test section for the full matrix.
