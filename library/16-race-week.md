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
