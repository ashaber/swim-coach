# Cyclocross skills-day session content

See `00-conventions.md` for the evidence-tagging scheme and
`reference_list.md` for full citations. This file grounds the `SKILLS_*`
constants and the `_skills_session_structure` / `_select_skills_drills` /
`_skills_sessions` builders in `engine/swim_coach/plan.py`.

**UNREVIEWED.** `engine/cx-skills-day-content` branch. A "CX skills" day is
bike-**handling** practice — dismounts, barriers, cornering on loose and
off-camber ground, run-ups — not a training-load session. The defect this
closes: a real cyclocross week had a Monday "CX skills" session whose
prescribed structure was the generic bike interval script ("3×10 min
threshold"). There was no skills session type in the engine at all.

**Sport scope: `bike`.** Same guidance-scoping intent as
`23-cycling-training.md` and `24-cycling-periodization-intervals.md` — this
content is never meant to surface to a swim-only athlete. The `/coach`
routing and `context.py` `filter_files_by_sport_scope` wiring is
**deferred to a future build stage**, exactly as
`24-cycling-periodization-intervals.md`'s own header records for itself;
this pass adds the engine builder plus this grounding file only.

## Why a skills day is not an interval day

Cyclocross racing is a repeated-surge, high-technical-load effort:
mechanical power output alone does not describe the demand, because
technical terrain (off-camber, ruts, sand, barriers, run-ups) imposes
real physiological and neuromuscular cost on top of it.
**[ADAPTED: cycling] Confidence: medium.** The nearest cited demand
profile is Protzen et al. (2026) for Olympic cross-country mountain
biking: ~25% of race time above maximal aerobic power, 3–10 s surges
repeated 15–20×/lap, and technical terrain imposing stress independent of
power. Cyclocross is a close cousin (shorter laps, more dismounts) but has
no equivalent full systematic review, so this is an adaptation, not direct
evidence. **Test:** on this athlete's own race `.fit` files, confirm the
power trace is highly variable (many short spikes, low
normalized-power-to-average ratio) rather than a steady threshold hold; if
races are actually steady-state, revisit whether a dedicated skills day
earns its place.

Practising handling under threshold or VO2 load is
counter-productive: fatigue degrades motor learning, and the point of the
session is clean, repeatable technique.
**[ADAPTED: general-endurance] Confidence: medium.** Seiler (2010)'s
polarized-distribution synthesis argues that adding moderate-to-hard work
to an already-trained endurance athlete's week does not reliably improve
long-term performance and can crowd out easy volume; a skills day placed
at RPE 5–7 keeps the week's hard-day budget intact for the actual interval
session. **Test:** if the athlete's weekly hard-day count (Z3–Z5 bike
sessions) exceeds three once a skills day is added, the skills day has
drifted into interval territory and its RPE cap is not being honoured.

## The drill catalogue

Coach judgment: five drill families, each run as one ~10-minute block:

1. **Dismount / remount reps** — step-through dismount at jogging pace, a
   few running steps, smooth remount; alternate the lead foot.
2. **Barrier / hurdle practice** — 2–3 barriers a few metres apart:
   dismount, carry, remount; a bunny-hop attempt only on the last pass.
3. **Tight cornering — off-camber and 180s** — figure-8s and switchback
   180s on grass; brake before the apex, look through the exit, weight the
   outside pedal.
4. **Loose-surface / low-traction handling** — gravel, sand or wet grass:
   light hands, hips back, feather the rear brake, pick the firm line.
5. **Run-ups / short shoulder-carry** — shoulder the bike, run a short
   steep pitch, remount cleanly on the flat; keep the running to 20–30 s.

These are the standard cyclocross handling curriculum taught in
practitioner skills coaching — Simon Burney's cyclocross technique
writing, and the USA Cycling and British Cycling skills-coaching
materials. No peer-reviewed source programmes bike-handling drills at this
level of detail; drill selection and cueing are coaching craft, recorded
here as judgment rather than dressed up with a citation.

## Session shape

Coach judgment: `SKILLS_WARMUP_MIN` = 10 min easy spin (with a few
slow-speed balance / track-stand touches — cold and stiff means more
falls), then `SKILLS_BLOCKS_PER_SESSION` = 4 drill blocks of
`SKILLS_BLOCK_MIN` ≈ 10 min each with easy spinning between, then
`SKILLS_COOLDOWN_MIN` = 5 min spin-down. Total ≈ 55 min. Ten minutes is
long enough for many repetitions of one skill and short enough to rotate
several skills while an amateur's concentration and movement quality stay
high; a longer block turns into sloppy reps. A skills day is not sized
from the week's volume target — its distance and power are nominal by
definition.

## Why RPE 5–7, not a power target

Coach judgment: `SKILLS_RPE_LOW` = 5, `SKILLS_RPE_HIGH` = 7. The blocks
involve accelerations (out of corners, up run-ups) so the session is not
trivially easy, but it must stay well short of a threshold or VO2 effort.
The drill steps carry `WorkoutTarget(basis="rpe")`; the session's nominal
`Session.intensity["zone"]` is `SKILLS_SESSION_ZONE` = "Z2" only, to label
it honestly as a non-hard day and keep it out of any hard-day count. No
watts are attached.
**[ADAPTED: general-endurance] Confidence: medium.** Buchheit & Laursen
(2013) frame interval prescription as work-bout duration and work:rest
ratio setting the physiological target — a skills block is deliberately
*none* of those shapes (no fixed ratio, no power target), which is the
clearest way to state "this is not an interval session." **Test:** if a
skills session ever exports with a power/zone target band on a work step,
or its purpose text mentions threshold / VO2 / FTP, the builder has
regressed.

## Rotate the subset, don't drill the same thing every week

Coach judgment: `_select_skills_drills` picks
`SKILLS_BLOCKS_PER_SESSION` drills by rotating a fixed window over the
five-entry catalogue, keyed on the session's index, so two skills days in
a row are not identical yet every drill comes round regularly — the same
deterministic-rotation idea `_select_bike_interval_template` already uses
for interval templates. This also reflects the motor-learning
contextual-interference principle: varied practice across sessions retains
better than blocked repetition of a single skill. The rotation is
deliberately simple and citation-free — it is a scheduling heuristic, not
a claim about the world.

## Crash-risk rationale

Skills practice at a controlled effort is itself injury mitigation:
cyclocross injuries are predominantly crash-driven acute injuries, and the
race-day skills most likely to cause a crash (dismounts, off-camber
corners, barriers) are exactly the ones a skills day rehearses.
**[ADAPTED: cycling] Confidence: low-medium.** Fallon et al. (2025)'s
preliminary cyclocross study (2025 British National Championships, 534
riders, 6.7% injury rate, predominantly moderate acute injuries) is the
only cyclocross-specific epidemiology available and is self-described as
preliminary; the causal link from drill practice to lower race-day crash
rate is coach inference, not measured. **Test:** track this athlete's
self-reported near-misses / falls in races over a season with vs. without
a weekly skills day.
