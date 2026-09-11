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

## Why RPE 2–4, not a power target

**Build E (`engine/race-week-content-refinement`) revision, replacing this
section's original 5-7 figure.** `SKILLS_RPE_LOW` = 2, `SKILLS_RPE_HIGH` =
4, recorded as a **SESSION-level** (whole-workout) rating, not a
per-block peak-effort read. The original 5-7 band described how a single
~10-min drill block's accelerations (out of corners, up run-ups) can feel
in the instant — a real, defensible per-block observation on its own. The
defect: this app's load model never consumes a per-block number. Session-
RPE is deliberately a single global 0-10 rating for the ENTIRE session
("how hard was your workout overall?"), not a differentiated per-
interval/per-segment score — see `19-srpe-protocol.md`'s "The question:
one global rating per session," itself grounding `engine/swim_coach/
load.py`'s tier-1 `session_load` formula (`duration_min * rpe`, Foster et
al. 2001). A ~55-min skills day is mostly easy spinning and standing
around between brief technical efforts; rated honestly on a whole-session
basis (not "what did the hardest 2 seconds feel like") that reads as
sRPE 2-4, not 5-7 — confirmed directly against real coach usage (Andrew's
own estimate, live session, 2026-09). Recording the old, higher per-block
number as if it were the session's sRPE would silently inflate this
athlete's `session_load`-derived training load for every skills day by
roughly 2x, purely from a scale-category mismatch, not any real change in
training stress.

`[ADAPTED: general-endurance] Confidence: high` for the "session-RPE is
one global rating, not a per-segment score" fact itself (`19-srpe-
protocol.md`'s own citation, Foster et al. 2001, directly states this).
**Test:** if this engine, or a future rewrite of it, ever starts asking
for or recording more than one RPE value per logged workout (a
per-interval or per-block rating), this citation's own "single global
question" framing no longer applies and `session_load`'s `duration_min *
rpe` formula would need a different aggregation to match — that would be
the signal this fact needs revisiting, not just the 2-4 figure below.
**Confidence: medium** for the specific 2-4 figure itself (Andrew's own
estimate for THIS drill mix/pacing, not a separately validated number —
another athlete's easy-spin/effort ratio on a skills day could differ).
The drill steps still carry `WorkoutTarget(basis="rpe")` at this new,
corrected 2-4 band (an athlete-facing cue for how hard the drill blocks
themselves should feel, kept intentionally conservative/easy rather than
re-introduced as a separate "per-block peak" scale the app has nowhere to
record); the session's nominal `Session.intensity["zone"]` stays
`SKILLS_SESSION_ZONE` = "Z2" only, honestly labeling it a non-hard day and
keeping it out of any hard-day count. No watts are attached.
**[ADAPTED: general-endurance] Confidence: medium.** Buchheit & Laursen
(2013) frame interval prescription as work-bout duration and work:rest
ratio setting the physiological target — a skills block is deliberately
*none* of those shapes (no fixed ratio, no power target), which is the
clearest way to state "this is not an interval session." **Test:** if a
skills session ever exports with a power/zone target band on a work step,
or its purpose text mentions threshold / VO2 / FTP, the builder has
regressed. **New test (Build E):** if this athlete's own logged sRPE for a
real skills day consistently lands outside 2-4 (either direction), that's
the athlete-specific falsification signal for the 2-4 figure specifically
— revisit the number, not the session-level-vs-peak framing above (that
part is the cited, not-athlete-specific fact).

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
