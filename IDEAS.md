# Ideas for Swim Coach App
## IDEA 001 - Dragon Fly as theme image
When designing and creating logos, use dragon flies as a theme inspiration

---

## IDEA 002 - Add Daily checkin to PWA.  Ask HRV or body battery, resting heart rate etc.
Expect future integration to source this data from Garmin or Oura
- RHR
- BB/HRV
- Sleep
- How you feel


## IDEA 003 - PWA layout
Tabbed view with these tabs:
- Daily Checkin: Morning stats (IDEA 002)
- Load workout: upload .fit or daily workout image
- Coach Chat: chat bot with coach 
- Plan: show training plan, daily, weekly, periodization, event specific (could merge swim crew features)
- Library: videos, research
- Athlete (may be settings from gear instead of tab): zones, pace, etc.

## IDEA 004 - expansion of research and validation
When new research data is added, agent takes the new data into account on answers

## IDEA 005 - chat agent "I don't know"
when questions asked don't have supporting data - answer clearly - I don't know.  But, record 
the question to trigger developer to do further research.  Ideally follow-up to athlete when further
research answers the question.  Related to this, have expert mode - allow physiologist or professional 
coach ask questions to train the research.

---

## IDEA 006 - RESOLVED (2026-08-25) - research and redesign "compliance" (per-workout vs weekly vs mesocycle)

**Resolution:** renamed the per-workout module/concept away from
"compliance" -- `engine/swim_coach/compliance.py` -> `quality.py`,
`WorkoutCompliance` -> `WorkoutQuality`, `workout_compliance()` ->
`workout_quality()`, and the coach-workouts API's nested JSON key
`"compliance"` -> `"quality"` (`backend/app/routes/coach.py`, consumed by
`web/src/views.js`'s roster tab). `engine/swim_coach/load.py`'s
`compliance()` -- the WEEKLY aggregate with the real 70%/90% thresholds
that drive `/adapt`'s repeat/hold/advance decision -- is untouched and
remains this codebase's sole authoritative "compliance." Naming collision
(problem 1 below) is fixed. Conflated-concepts (problem 2) is addressed by
the rename itself, per this idea's own recommended shape: the per-workout
bundle (distance/duration delta, intensity_match, quality-flag summary) is
kept as one "quality" concept rather than split further, matching the
"keep per-workout signals as quality/execution" recommendation below. No
thresholds, computations, or field semantics changed -- naming and
docstrings only.

Original problem statement, kept for context:

Coach-mode Phase 1 (2026-08) added `engine/swim_coach/compliance.py`'s
`WorkoutCompliance` -- a PER-WORKOUT distance/duration-delta + quality-signal
bundle -- without checking that `engine/swim_coach/load.py` already has an
authoritative, library-cited `compliance()`: a WEEKLY aggregate
(`completed swim distance / planned swim distance * 100`,
`library/03-periodization.md`'s "Compliance" section), with real 70%/90%
thresholds that drive `/adapt`'s actual repeat/hold/advance decision.

Two problems to research and fix, not just rename:
1. **Naming collision** -- two different things in this codebase are both
   called "compliance" today (the new per-workout one has no library
   citation of its own).
2. **Conflated concepts** -- the per-workout module bundles genuinely
   plan-matching fields (distance/duration delta, intensity_match) together
   with genuinely QUALITY fields (cardiac_drift_pct-derived, SWOLF
   degradation) under one name. Standard training-science usage treats these
   as different axes: quality = how well a single session was executed
   (legitimately per-workout); compliance/adherence = did the athlete do
   what was prescribed, normally measured as a PERIOD aggregate (weekly is
   the standard cadence in both research and applied coaching; sometimes
   rolled up to a mesocycle/block for periodization review) -- volume/load
   compliance, session-count adherence, and (less commonly implemented)
   intensity-distribution/time-in-zone compliance.

Before redesigning: research actual standard definitions/citations (Foster
sRPE, the periodization/monitoring literature `load.py`'s existing
monotony/ACWR machinery already draws on) rather than inventing thresholds
again. Likely shape: keep per-workout signals as "quality"/"execution", not
"compliance"; either surface the existing weekly `load.compliance()` in the
coach view as-is, or extend THAT one with intensity-distribution matching if
a richer weekly number is wanted -- don't add a third parallel definition.

---

## IDEA 007 - PAR-Q+ pre-participation health screening

The Physical Activity Readiness Questionnaire for Everyone (PAR-Q+
Collaboration, eparmedx.com): 7 general-health yes/no questions on page 1;
all-NO clears for unrestricted activity, any-YES routes to condition-specific
follow-up (pages 2-3) and potentially the ePARmed-X+ assessment or a
Qualified Exercise Professional referral. Sources: eparmedx.com, PMC
("Public Perceptions on the Use of the Physical Activity Readiness
Questionnaire"), Health & Fitness Journal of Canada's 2023 PAR-Q+ writeup.

Explicitly distinct from the existing `HealthStatus` model: PAR-Q+ is a
one-time (~12-month-valid) **pre-participation** screen done *before*
training starts; `HealthStatus` is the durable, append-only **ongoing**
injury/restriction log used *during* training. Complementary, not
overlapping.

Where it could plug in (options, not decided): onboarding (every new
athlete, any sport), and/or specifically for a true-beginner client (see
IDEA 008's equestrian use case, "middle-aged woman, no fitness base") where
a real pre-participation screen matters more than it does for an
already-training athlete like Renee/Tim.

**Bundles with IDEA 010a (goal-setting's feasibility half):** readiness-to-
train (PAR-Q+) and per-sport starting-state/goal-feasibility are the same
"where is this athlete actually starting from" question, asked from two
angles -- safety vs. capability. Worth building as one coherent "starting
state" capability rather than two unrelated features that happen to both
touch onboarding. See IDEA 008's "Agreed first build" note.

## IDEA 008 - Multi-sport expansion

Motivation: given the friction getting Renee comfortable with the app,
worth exploring other use cases rather than betting everything on one
athlete/one sport as the validation case. Came out of a long conversation
with Tim.

**Five use cases:**
1. **Tim: rucking + running as primary training focus, cycling as
   recreational mixing-in (not a focus).** Tim is already a live athlete
   (currently swim-tracked) -- real, motivated, immediately available test
   case for a second primary-sport discipline.
2. **General fitness support for a primary sport the engine doesn't itself
   manage** -- e.g. strength+mobility programming for a golfer or
   equestrian, where the golf/riding activity itself isn't planned by this
   system, only the supporting conditioning work.
3. **Horse-riding, skills-first**: amateur riders bring their horse to
   lessons with a human trainer, then follow a home training plan between
   lessons -- more skills-progression than fitness-progression, but could
   also serve a true fitness-beginner (a middle-aged woman with no fitness
   base) who needs a real strength/core-building progression to support
   riding mechanics (remounting, sitting a trot correctly).
4. **Expand the research agent** (already IDEA 004) -- becomes more
   necessary once multiple primary disciplines exist, since each needs its
   own evidence-grounded library content rather than everything flowing
   through swim's `[ADAPTED: cycling|running|tri|general-endurance]`
   one-directional tagging convention.
5. **Andrew himself, as a cyclist (mountain bike + cyclocross) + strength.**
   Real and time-sensitive, not hypothetical -- final stretch leading into
   cyclocross season, wants to tighten up his own plan soon, interest on par
   with Tim's. MTB/CX has its own intensity model (power/HR-anchored, not
   pace-anchored like swim or running) and its own injury/load concerns --
   a genuinely different test of "generalize the one engine" than Tim's
   case, not a duplicate.

**Hard constraint, motivated by a real, current trust problem:** an
athlete must only ever receive guidance matching their own sport(s).
Renee already doesn't trust the app because she perceives it to be cycling
specific -- notably while the system is still swim-only today, which is
worth a separate, small look independent of this roadmap (UI copy, a stray
reference, something in the coach persona). If she decides to use the app
and it ever surfaces cycling guidance to her, that misperception becomes
justified and trust gets worse, not better. Whatever multi-sport work
ships must scope guidance/grounding strictly to each athlete's own
configured sport(s) -- this is a first-class acceptance criterion, not a
nice-to-have, from the very first build, not retrofitted later.

**On the `mtb-skills` repo** (Andrew's other project, currently used only
as a template source for this project's Vite/CI scaffolding): it has
genuinely stronger infrastructure worth mining separately for swim-coach's
own roadmap -- a real ITG/prod environment split, RLS (swim-coach's own
Supabase setup currently defers this -- service-role-only from the backend
today), and magic-link email auth (swim-coach uses Google sign-in). More
directly relevant to use case 3 (horse-riding): `mtb-skills` is built
around **skills progression** -- tracking skill acquisition within a
progression and providing guidance for advancing further along it. A
strong candidate architectural template for a "skill session" concept this
codebase doesn't have yet (no existing session type distinct from
swim/strength/recovery/cross_train captures skill-acquisition progress).
Worth a real look at `mtb-skills`' design before inventing this from
scratch, whenever that use case is taken up.

**Architecture direction (confirmed):** generalize the *same* engine
rather than bolt on a separate simplified track for non-swim clients --
but with genuine per-discipline research grounding where the physiology
actually differs (rucking's load-carriage/connective-tissue progression is
its own evidence domain, the same *shape* of concern as swim
shoulder-loading but not the same research, not a copy-paste). By
contrast, generic strength+mobility work *supporting* a primary sport the
engine doesn't manage (golfer, equestrian) can be more genuinely
shared/reusable across disciplines -- though published strength-and-
conditioning research depth varies a lot by discipline (much more exists
for golf than for recreational riding), so a shared library file can't
pretend to equal evidentiary footing across every sport it covers.

**Technical grounding** (direct codebase investigation, so a future
reader doesn't have to re-derive it):
- *Already sport-agnostic, reusable as-is*: `load.py`'s sRPE/HR-TRIMP/
  duration-only load tiers, `daily_loads()`, `monotony()`,
  `acute_chronic_ratio()`/ACWR, `ctl_atl_tsb_series()` (pure math over
  `dict[date, float]`, no `Sport` references); the `WorkoutStructure`/
  `WorkoutStep`/`WorkoutRepeat` structured-workout IR mechanism;
  `adapt.py`'s top-level decision-table skeleton (wellness + load-ratio +
  compliance -> cut/repeat/hold/advance); `scaffold_macro`'s block-share/
  ramp-cap/taper-decay arithmetic; the `_pick_days` scheduling helper;
  `Athlete`'s pydantic model itself (CSS pace / pool_schedule already
  optional, nothing hard-required at the model level).
- *Swim-hardcoded, real work needed*: `Sport` is a closed
  `Literal["swim_pool","swim_ow","strength","recovery","cross_train"]`
  (`models.py`) -- `cross_train` is explicitly a logging-only catch-all
  ("the planner never schedules it"), not usable as a real second primary
  sport; `WorkoutStep.modality` is closed to `Literal["swim","strength"]`,
  an even harder constraint since it's per-step, not per-session;
  `zones.py` is 100% CSS-pace-anchored, no HR- or RPE-anchored zone table
  actually implemented (despite the schema already tolerating `"hr"`/
  `"rpe"` as valid anchor values); `plan.py`'s `generate_week` swim
  content (pool-day placeholders, CSS-driven session durations, the
  long-swim ladder) is swim-specific by *content*, not just parameter --
  needs a parallel implementation per discipline, not a config flag;
  `load.compliance()` and `weekly_volume_m()` are hardcoded to swim
  distance (`_SWIM_SPORTS` filter) -- a non-swim-primary athlete would
  show 0% compliance every week regardless of real training delivered;
  `provision.py` hard-raises `ValueError` on a missing CSS pace, blocking
  onboarding of any non-swim-primary athlete today; `Event.distance_m` is
  required (`gt=0`) and is `scaffold_macro`'s only entry point -- a
  non-distance goal (general fitness, riding skills) has no macro-plan
  path at all without inventing a fake distance; the library's
  `[ADAPTED: ...]` tag convention is directionally built assuming swim is
  always the discipline being adapted *to* (65x
  `[ADAPTED: general-endurance]`, all flowing into swim conclusions -- no
  reciprocal tag exists); the coach system prompt (`backend/app/
  context.py`'s `PERSONA_AND_RULES`) opens "You are the swim-coach AI
  coaching agent," and both `INDEX.md`'s routing table and `context.py`'s
  keyword router are 100% swim-vocabulary, including the *default*
  fallback grounding.
- *Closest existing analog for horse-riding*: the already-shipped
  `has_pool_coach`/`pool_coach`-source/`set_pool_coach_status` pattern -- a
  real external human (the pool coach) hands out content reactively, the
  engine plans the periodization around it. Conceptually exactly the shape
  needed for "trainer gives a lesson, engine plans the home training
  between lessons," but currently named and scoped entirely to pool
  swimming across `plan.py`/`models.py`/`backend/app/tools.py`/
  `library/06-long-swim-progression.md`.

**Rough relative sizing** (future prioritization, not a commitment):
- Smallest lift: general strength+mobility-only client (golfer/equestrian)
  -- most machinery already works; main blockers are `Event.distance_m`
  required and `compliance()`'s swim-distance hardcoding, both narrow.
- Largest lift: a second full primary-sport discipline with its own
  zones/pace system and periodization content (Tim's rucking+running) --
  touches `Sport`/`modality` enums, `zones.py`, `plan.py` content,
  `adapt.py`'s downstream, library, persona/routing. But real and live
  today, unlike a hypothetical.
- Different shape, not strictly bigger/smaller: horse-riding --
  generalizing the pool-coach pattern, but needs a new "skill session"
  concept and no distance-free progression model exists yet; pushes
  furthest from the current swim-only framing.

**Agreed first build:** relax `Event.distance_m`-required so
`scaffold_macro` has a path for a non-distance/per-discipline goal,
alongside generalizing `compliance()`/`weekly_volume_m()` beyond
swim-only. This is also where PAR-Q+ (IDEA 007) and goal-setting's
feasibility half (IDEA 010a) naturally bundle in -- per-sport starting
state, readiness-to-train, and a non-distance goal path are really one
"establish where this athlete actually is" capability, not three separate
ones. This is a confirmed starting point, not just the cheapest option on
a list.

**Ordering after that, confirmed (2026-09):** 2) **Andrew's own cyclist
case goes first**, deliberately, over Tim's rucking/running case --
Andrew's own reasoning: cycling is different enough from swim to expose
real multi-sport design limitations, but well-grounded enough (unlike
rucking) to build with confidence rather than guessing. A source-verifying
research pass this session (see IDEA 010's sibling research note, or ask
for it directly) confirmed this reasoning is sound: cycling has a real,
deep, well-established zone framework (Coggan/Allen power zones) and,
notably, the engine's OWN existing CTL/ATL/TSB machinery (Banister
model, adapted into TrainingPeaks' TSS by Andrew Coggan) is confirmed to
be genuinely cycling-native and well-grounded -- the code's existing
"unverified for swimming" flag on those constants is precisely accurate,
not overcautious. Rucking, by contrast, has a real, solid injury/
load-carriage literature (Knapik et al. 2004, *Military Medicine*,
confirmed) but **no validated zone framework or progression-rate research
at all** -- exactly the "library gap to fill" Andrew is deferring to
after cycling exposes the platform's general shape.
3) **Tim's rucking+running case follows**, explicitly expected to need
more original library work (no borrowed zone/progression framework to
lean on for rucking specifically -- running itself is well-grounded, Jack
Daniels' VDOT zones, real research on both sides of the "10% rule" debate).
4) horse-riding, once the platform is proven on a second real primary
sport. 5) research-agent expansion (IDEA 004), higher-value once 2/3
create real cross-discipline research need, though technically
independent and could be pulled forward earlier -- Tim's own app (IDEA
009) and any real training data he shares are direct inputs here.

**Cycling build's concrete technical requirements (Andrew, 2026-09), to
ground the next planning pass rather than re-derive them:**
- **Power-based training** -- Andrew trains with a power meter; the zone
  model should be FTP/Coggan-based, not HR/RPE-only (confirmed
  well-grounded research above), though HR/RPE-only must stay supported
  for other athletes (Tim has no outdoor power meter, only HR/RPE outdoors
  and power when on a trainer -- the zone model can't assume power is
  always available).
- **Two distinct structured-workout delivery paths, not one:**
  - **Indoor/trainer** -- workouts come from TrainerRoad or need to be
    delivered as a `.zwo` file for MyWhoosh (a smart-trainer app). A real,
    working, already-built skill for exactly this exists in a sibling repo:
    `workout-to-zwo` (`/home/ashaber/projects/workout-to-zwo`) --
    TrainerRoad-description-or-structured-block-list -> valid `.zwo` XML,
    with real parsing rules for repeats/ramps/steady-state/cadence and a
    worked example. Currently a prompt-driven Claude Code skill (SKILL.md
    parsing rules for an LLM to follow), not deterministic Python -- if
    reused inside swim-coach, matching this project's own "engine owns all
    plan math, never hand-compute in chat" standing rule would mean porting
    the parsing logic to deterministic Python (`engine/swim_coach/`,
    alongside `garmin_export.py`), not just invoking the skill as-is.
  - **Outdoor** -- must go to Garmin, which is exactly what this project's
    existing intervals.icu bulk-push pipeline already does for swim/
    strength (`garmin_export.to_garmin_fit_workout`, base64 + POST to
    intervals.icu's `events/bulk` endpoint, "Push to Garmin" button/tool --
    see ROADMAP.md's "Now/Next" section). Extending that existing pipeline
    to a new sport, not building a new one.

**Cross-cutting, applies regardless of order:** the guidance-scoping
constraint above must hold from the first build onward, not be retrofitted
later.

**Cross-cutting addendum (2026-09-12), confirmed with Andrew: bundle the
sports-registry refactor into whichever build adds the next real sport(s),
not before.** Live defect-round work this session found the same
"scattered per-sport facts, no single source of truth" pattern in the PWA
(`web/src/plan.js`'s dot-color map, `workouts.js`'s label/detail maps,
`views.js`'s distance-display check -- each maintained separately, and
`bike`'s dot color had already silently drifted when it was added
engine-side). Consolidated into a new `web/src/sports.js` registry
(PR #183) -- but a matching backend check found the pattern is smaller and
narrower there: most `sport == "bike"`-style branches in `plan.py`/
`adapt.py`/`tools.py` are legitimate algorithm dispatch (swim vs. bike
generate real different plans, not a data-driven variation), not
display-fact duplication. Only two genuine per-sport facts are actually
duplicated backend-side -- the FTP-vs-CSS threshold lookup (identical
`ftp_watts = athlete.ftp_watts if primary_sport == "bike" else None` at
`backend/app/tools.py:2018,3614,4133`) and the distance-vs-duration volume
unit (`tools.py:4749,4786`, `backend/app/context.py:1362`, all three
independently re-deriving the same "is this a swim-distance sport" fact).
`backend/app/routes/garmin.py`'s `_SESSION_SPORT_TO_GARMIN_SPORT` is
already the right shape for this -- a small, real per-sport table -- and is
the pattern to extend, not the full frontend registry's shape ported
verbatim.

Andrew's own framing for why this waits: *"It would have been ideal to
validate the refactor when adding two sports but will suffice doing
together"* -- swim+bike alone can't prove a registry design generalizes;
run/ruck (this idea's own item 3) actually adding two more real, different
sports is the right moment to build AND validate the backend registry at
once, not retrofit it onto two sports now and hope it holds for a third.
Also fold in then: the API-layer question of whether the Python and JS
registries need a shared source of truth (today they're two independently-
maintained copies that can only drift, not two views of one truth -- e.g.
`web/src/views.js`'s `SPORT_OPTIONS` array, the manual-log-workout form's
sport dropdown, is a FOURTH undiscovered copy PR #183 itself missed,
found only while writing this note) -- at minimum a contract test pinning
the Python `Sport` literal against the JS registry's keys, at most serving
sport metadata from the API so the frontend derives from backend truth
instead of mirroring it (a real architectural change: new/extended
endpoint, frontend refactor, and PWA offline-cache design since this app
is offline-first -- genuinely part of the same "add real sports" body of
work, not before it).

## IDEA 009 - Lessons from Tim's own AI coach app (not a document -- a real, running app)

**Correction (2026-09):** IDEA 009 originally assumed Tim would send an
updated panel-of-experts *plan document*. What actually arrived is
different and more interesting: the source of a real Claude-Code-based
training-coach app Tim built and is *currently using for his own live
training* (`AI Coach - Sharing Version`, a sibling project, not part of
this repo) -- general-purpose across endurance sports (intervals.icu-
integrated, not swim-specific), with an athlete-facing UX built around
slash commands (`/intake`, `/plan`, `/block`, `/checkin`, `/redteam`, ...)
and Claude Code skills/agents rather than a bespoke PWA. Reviewed
read-only this session; nothing copied in -- the concepts below are worth
learning from, not the code or prose itself.

**Architectural contrast worth naming plainly** (Andrew's own observation):
Tim's app has comparatively little of an explicit, curated research
library the way this project's `library/` does -- it leans instead on
"the data available to Claude" (the model's own latent sports-science
knowledge) wrapped in a set of behavioral constraints and review layers,
rather than pre-curated, cited evidence files. Two real, defensible
strategies for the same underlying goal (don't let the coach say something
ungrounded) -- worth being aware this project chose the more expensive,
more auditable path (explicit citations, `[EVIDENCE]`/`[ADAPTED]` tags,
`Confidence:`/`Test:` lines) rather than assuming it's the only reasonable
one. Not a recommendation to switch -- this project's evidence discipline
exists for good, already-documented reasons (see `library/00-conventions.md`'s
account of a past fabricated-citation incident) -- just an honest
comparison point.

**The "four experts including red team" turned out to be two different,
genuinely worth-noting things, not one:**

a. **The "four experts" (physiology, coaching craft, psychology, sports
   medicine) are NOT four separate model calls.** Tim's own `CLAUDE.md`
   is explicit: *"Speak as 'I'. You are one coach, not a team... The
   `coach` skill reasons from four perspectives... That is internal."*
   One model, one call, instructed to reason through four lenses --
   cheap, not a multi-agent fan-out. Directly answers the token-cost
   worry this idea originally raised.
b. **Red team IS a separate subagent call, but bounded by design to
   exactly the moment Andrew already guessed -- plan build/revision, not
   chat.** `.claude/agents/red-team.md`: a single Sonnet subagent,
   invoked only "before a macrocycle or training block is shown to the
   athlete, and before any significant plan adjustment," never
   per-message. Notably well-disciplined as a prompt: explicit
   anti-padding instruction ("a plan with one real problem and six padded
   ones is a bad review, because the coach learns to discount you"),
   capped at 6 objections, terse structured output (verdict, ranked
   objections with severity/evidence/consequence/suggested-fix, a
   "fragile points" closer). **This is the one genuinely transferable
   idea**: an adversarial review pass before a plan reaches the athlete,
   bounded to plan-build/revision moments -- maps cleanly onto this
   project's existing draft-then-confirm tools
   (`propose_injury_adapted_taper`, `draft_macro_plan`) as a real, new,
   cost-bounded capability, not replacing the coach's own reasoning.

**Independently valuable, separate from the panel/red-team question:**
Tim's `docs/lessons.md` (real, hard-won intervals.icu integration
findings, not athlete-specific) has at least one finding worth checking
against this project's own code directly: *"intervals.icu stores
`hr_zones` as absolute bpm but `power_zones`/`pace_zones` as percentages
of threshold. Treating them uniformly produced heart-rate zone tops well
above the athlete's actual maximum -- physiologically impossible, but
plausible-looking output... silent, looked plausible until checked against
physiology."* Also flagged there: inherited/estimated threshold values
silently masquerading as measured ones (directly relevant to CSS-pace and
any future FTP onboarding under IDEA 008), and CTL/ATL reading
artificially low for "today" while the day's data is still uploading.
Worth a real check whether this project's own intervals.icu sync
(`backend/app/sync.py`) has either latent bug, independent of anything
else in this idea.

**Original two uses, still real, once/if Tim shares actual training
content from his history rather than just the app's source:**

a. **Source identification** -- who are the real coaches/physiologists/
   methodologies behind Tim's training that this project's library should
   be citing and thinking like, for rucking/running -- direct input to
   IDEA 004 (research-agent expansion) and to any new discipline-specific
   library files under IDEA 008.
b. **Workout generation/validation** -- Tim's own real workouts (not the
   app's code) as a candidate source for enriching library session-
   template content or as a validation benchmark for this engine's own
   generated/ad-hoc workouts, same validate-don't-copy discipline already
   proven on Renee's taper.

## IDEA 010 - Goal-setting module

Motivating gap, concrete and real: Tim told the AI coach his goal was to
run a 3:45 mile by end of year, and the coach responded "great goal" -- no
grounding at all in whether that's realistic given his actual starting
state. Arguably a real instance of this project's own standing principle
being violated in spirit (deterministic engine owns all plan math, never
hand-compute/eyeball in chat) -- the coach made an implicit feasibility
judgment with zero engine backing.

Two distinct halves, worth keeping conceptually separate in any future
build:

a. **Feasibility grounding (deterministic, engine-side).** Given an
   athlete's actual starting state, assess whether a stated goal is
   realistic in the stated timeframe, the same way
   `propose_injury_adapted_taper` grounds a taper in real CTL/ATL math
   rather than vibes. Real data already available to draw from:
   `Athlete.dob` (age, already a model field), the athlete's real logged
   training history and current fitness trajectory
   (`load.ctl_atl_tsb_series`, `daily_loads`, `weekly_volume_m`/
   `monotony`), and whatever discipline-specific progression norms the
   library ends up holding once IDEA 008's multi-sport work lands.
   Extends "the engine owns plan math" to "the engine also owns
   goal-feasibility math," not just week-to-week planning. Bundles with
   IDEA 007 (PAR-Q+) -- see IDEA 008's "Agreed first build."
b. **Goal ideation (conversational, coach-side).** SMART goals are a
   *validation/structuring* framework for a goal you already have -- they
   don't help you find the right goal in the first place. E.g. "I want to
   podium at CX races this year" is a real aspiration but underspecified;
   before SMART-izing it there's a needed step of turning a vague
   aspiration into candidate concrete goals (which race, what field
   size/category is realistically competitive, what does "podium"
   actually require relative to current state) -- informed by (a)'s
   feasibility grounding -- and only then SMART-validating the result. A
   conversational "goal discovery" capability sitting *before*
   SMART-goal-setting, not instead of it.

## IDEA 011 - Goal-specific interval-structure research (the sharpen-phase content gap)

Found live, not speculated: the established-base "sharpening" macro shape
(built for Andrew's real cyclocross case -- `scaffold_sharpening_macro`,
`hold -> sharpen -> taper`) correctly recognizes *whether* an athlete needs
a base-building phase at all (a real, goal-independent signal derived from
logged training history), but the actual session CONTENT generated within
the sharpen phase is not goal-aware -- it's the four interval templates
built specifically for CX (sustained threshold, over/unders, short-short
VO2, race-pace), and would be wrong for a structurally different goal (e.g.
a hypothetical ultra-endurance event needing extended steady-state work and
fueling rehearsal instead of short high-intensity efforts). Andrew's own
framing: this needs real research into how interval STRUCTURE should map
to (a) the specific physiological adaptation being targeted and (b) how
that adaptation serves a given goal's actual demands -- not assumed to
generalize from one goal (CX) to a structurally different one.

Confirmed hypothetical for now (Andrew has no actual competing goal today)
-- captured so it's not lost, not because it's urgent. Natural next step
once a second, genuinely different goal type is real (a distance-endurance
event, a skills-based goal, etc.): research the interval taxonomy for THAT
goal type the same way `library/24-cycling-periodization-intervals.md` did
for CX, rather than assuming the existing four templates transfer.

## IDEA 012 - Autoregulation: adapting future workouts from real performance/RPE signal

Andrew's stretch-goal framing, verbatim in spirit: analyze the quality and
RPE of a completed workout to adapt FUTURE workouts to match what the
athlete is actually ready for -- and skepticism, also verbatim in spirit,
that TrainerRoad's marketing (positioning this as achievable only through
their proprietary ML) is overselling a simpler mechanism.

**That skepticism is well-founded, checked against real research this
session, not just asserted:** autoregulation (adjusting training load in
real time based on RPE, reps-in-reserve, or session performance) is a
real, peer-reviewed exercise-science concept -- used in BOTH strength and
endurance training, not ML-exclusive or proprietary. The core mechanism
(use a completed session's real performance/RPE signal to inform the next
prescription) is achievable with rule-based, deterministic methods, matching
this project's own "engine owns plan math, agent applies judgment"
architecture. Where ML *could* add real value -- large-scale pattern
detection across many athletes' data, fine-grained personalization -- swim
coach doesn't have that data volume and isn't claiming to compete on it;
the honest, achievable version here is a principled autoregulation rule,
not a marketing-scale claim.

**Real, already-existing foundation to build on, not a green field:**
`engine/swim_coach/quality.py`'s `workout_quality`/`session_target_load_au`
already compute a per-workout planned-vs-actual load delta (`load_delta_
pct`) -- but that module's own docstring states plainly it is "purely
informational... never wired into weekly rollups or adaptation decisions."
This is exactly the raw signal autoregulation needs, already built,
deliberately inert.

**The real precedent for how to wire it in safely already exists too, and
should be followed, not reinvented:** `library/17-wellness-load-integration.md`'s
own "Recommendation, not yet built" section (a different question --
wellness/HRV contradiction signals -- but the same underlying caution)
explicitly argues AGAINST auto-wiring an unvalidated signal into
`adapt_week`'s decision path, recommending instead a purely informational
flag (`"confirming"|"contradicting"|"insufficient-data"`-shaped) that a
human/coach reviews, never an automatic plan rewrite. Apply the same
posture here: a real autoregulation build should start as an informational
signal surfaced to the coach (e.g. "this athlete has consistently under/
over-performed prescribed RPE for N sessions -- consider adjusting"), not
an automatic engine decision from day one.

Not built here -- captured as a real, well-grounded stretch goal, with its
building block already in the codebase and its safe-wiring precedent
already proven correct once.

## IDEA 013 - The 5-session-slot ceiling on a generated bike-primary week

Found live, not speculated: building Andrew's real first cyclocross week
(2026-W38) through the coach, the generator produced exactly 5 sessions and
there was no mechanism to represent a 6th day. Root cause is two flat
constants plus a modify-only override path:

- `plan.BIKE_SESSIONS_PER_WEEK = 3` -- a hard cap on bike sessions per
  week, independent of how many days the athlete actually rides. Andrew
  rides 4-5 (Tue intervals, Wed MTB, Sat, Sun group ride) on top of Mon
  skills.
- `plan.STRENGTH_SESSIONS_PER_WEEK = 2` -- added on days the 3 bike
  sessions didn't use (`_bike_week_sessions_with_strength`).
- 3 + 2 = 5 is the whole week. `_apply_session_overrides` in
  `backend/app/tools.py` matches each override to exactly one *existing*
  session by date+sport and errors ("no session matching date ...") when
  none exists -- it can modify a generated slot but cannot append a new
  one. So the coach could not add Sunday 2026-09-20 (day 2 of the Season
  Opener race weekend); it had to be left for manual post-hoc logging.

Contributing gap: a bike-primary athlete has no `pool_schedule`-equivalent
field for weekly training-day pattern / frequency (the `_bike_week_sessions`
and `_spread_days_evenly` docstrings both note this explicitly). Without it
the engine can't know Andrew's Mon/Tue/Wed/Sat/Sun rhythm, so it both caps
the count and places days generically (`_spread_days_evenly` -- evenly
spaced, not the athlete's real pattern).

Related but distinct (same live session): generated skills/race days carry
the right `purpose` label but the wrong prescribed `structure` -- e.g. a CX
skills Monday still shows "3x10min threshold interval" content because
there is no skills-day content template, only the 4 CX interval templates
from `library/24`. A `structured` override can hand-author it, but there's
no generated starting point.

Natural fix direction (a "cleanup" build, per Andrew's own framing): an
athlete bike-frequency/day-pattern field feeding a non-flat
`BIKE_SESSIONS_PER_WEEK`, plus either an add-session path in
`session_overrides` or an explicit day-count parameter on
`create_week_plan`/`replace_week_plan`. Captured now so the concrete
repro (W38, the missing Sunday race day) isn't lost.


## IDEA 014 - Intervals as a progression rather than rotation

Intervals are made up of a zone target - e.g., VO2 where sets are made up of 
durations and repeats.  An athlete has to build the fitness and mental
fortitude to complete longer set durations.  Before prescribing a 5x2min VO2, 
the athlete should have worked up to it with 15x15, 30x30 float sets, 7x1min vo2 
and other shorter durations to be ready.  In addition, interval types can target
expected demands - like hard starts for short sprint racing demands.

## IDEA 015 - Challenges

The monotony of just doing intervals can take the fun out of training.  Mix 
it up with a challenge to inspire or keep it interesting.


## IDEA 016 - Coach mode - continued

There is a longer design and phasing somewhere.  Key next step is coach to athlete
chat.  If I have another athlete on this app, I want the more direct feedback
where they can ask questions and for adjustments.  I also see this as a 
compelling feature for a coach to augment their work instead of replace 
them.  

## IDEA 017 - Trainer Road collaboration mode

TR has significant workout library and primary goal to give the right workout 
at the right level for the athlete.  If this app achieves that goal, good
enough.  But, if the workout targeting isn't dialed, continue with TR
as workout generator and this app as guidance coach.  Need to thoughtfully
know the TR training plan without stealing their workouts.  Possible model
is like the master swim model where on-deck coach provides the workout and
swim coach interprets the load and benefit and adapts around it.

## IDEA 018 - Season-macro chain aborts entirely on race 1's stale runway, instead of extending an already-built plan

Found live, real repro (2026-09-18, Andrew's own bike/CX season). He built
a season-spanning macro across three real races (Peak Weekend Oct 17 /
Halloween Weekend Oct 31 / Season Finale Nov 21) a few days earlier
(`start_date=2026-09-14`). That persist never actually landed (separate
issue, see feedback `0b02c780` and the diagnostics landed in PR #198) --
what's captured here is what happened when he asked the coach to just
retry the same build tonight: it failed outright, and the failure reveals
a real architecture gap, not just a persistence bug.

**Root cause, exact code (`engine/swim_coach/plan.py`,
`scaffold_season_macro`'s per-race loop, ~line 1804-1841):** for an
`"A"`-priority race, the runway-too-short case is a hard `raise
ValueError` that aborts the WHOLE chain -- races 2 and 3 (Halloween,
Season Finale), both with plenty of runway, never get scaffolded either,
even though nothing is wrong with either of them:

```python
if tier == "A":
    if weeks_available >= MIN_MACRO_WEEKS:                     # 8 weeks
        sub_macro = scaffold_macro(...)
    elif established_base and weeks_available >= SHARPENING_MIN_MACRO_WEEKS:  # 4 weeks
        sub_macro = scaffold_sharpening_macro(...)
    else:
        raise ValueError(...)   # kills the entire season build
```

Compare the `"B"`/`"C"` branches a few lines below: below their own
minimum runway, they degrade gracefully -- no dedicated block, folded
into whatever's already covering that race's date (exactly the mechanism
that correctly gives Halloween Weekend no dedicated cycle). The A-tier
branch's hard-refuse posture is inherited unchanged from the single-race
`draft_macro_plan` handler this whole season-macro feature (PR #192,
`multi-race-season-macro` build) was built to go beyond -- reasonable for
"build ONE race's cycle," wrong blast radius inside a multi-race chain.
The function's own docstring even states the posture deliberately: *"an
A-race this function cannot safely periodize into is a real refusal, not
silently downgraded to a lesser shape."* That sentence was written before
this function had to coexist with a race that was already mid-cycle.

**The deeper issue, in Andrew's own words:** *"me asking coach to fill in
the details for the race roster loaded a long time ago shouldn't trip
guardrails of going from couch to race in a few weeks."* Peak Weekend
already has a real, valid, currently-persisted sharpen->taper cycle (built
`start_date=2026-09-14`, still correct, still being followed this week --
confirmed directly against the DB). Recomputing race 1's shape from a
fresh `start=today` is the wrong operation entirely when a real cycle for
it already exists on file: the athlete isn't asking to cold-start a
macro for an imminent race, they're asking to EXTEND an already-built
plan forward to cover the rest of a roster that was loaded well in
advance. `MIN_MACRO_WEEKS`/`SHARPENING_MIN_MACRO_WEEKS` are the right
guardrail for "can I safely build a NEW cycle from scratch" -- they are
the wrong question when a cycle already exists and the real ask is "keep
what's there, add what's missing."

**Correction (2026-09-19, Andrew, morning before the race -- read this
before building):** the 12-week-vs-7-month point below was slightly off
target as originally written. The real defect isn't that the evidence
gate needs more credit for a longer history -- it's that the runway check
is the wrong check ENTIRELY for this call, because Andrew is editing an
ACTIVE plan this same coach is already running, not proving he trains.
Bullet 1 above (preserve race 1's existing coverage, don't re-derive it)
already correctly identifies this. History-length (12 weeks vs. ~7
months back to February) is a real, separate axis -- it only bears on RAMP
RATE (how fast volume can climb, the existing +8%/week progression caps
elsewhere in the engine), not on whether the runway-length gate should
apply at all here. Keep those two questions separate: don't loosen
`SHARPENING_MIN_MACRO_WEEKS` because of history length; fix WHEN the
runway check applies at all.

**Design philosophy for the fix, Andrew's own framing:** *"error on the
side of letting a good plan record vs 3 weeks of arguing with coach to
load the plan because of a technical nuance -- coach can raise concerns
and proceed vs hard blocks in instances like this. This differs from
[a] 2 week training plan from couch or [a] goal to set world record in 6
months."* Concretely: an athlete with a real `established_base` extending
an already-active plan should get a WARNING it can proceed past, not a
hard refusal, even when a race's runway is genuinely tight -- the couch-
to-5k / unrealistic-goal case (no established base, or a genuinely fresh
cold-start build) keeps today's hard-refuse behavior unchanged. The
discriminator is `established_base` (already computed, already the real
safety signal) combined with whether this is an extend-existing-plan call
vs. a fresh build -- not a new signal to invent.

**Natural fix direction (being built now, 2026-09-19 -- see the PR this
idea resolves into for the actual implementation):**
1. Give `scaffold_season_macro` (or its caller,
   `_handle_draft_season_macro_plan`) an "extend existing macro" mode:
   when `store.load_macro` already covers race 1 with real blocks, don't
   re-derive race 1's shape from `start` at all -- preserve its existing
   coverage as the season's first cycle, and chain races 2+ forward from
   wherever that existing macro's coverage actually ends (same cursor-
   continuity math the function already does between races, just seeded
   from real persisted data instead of a fresh `scaffold_macro` call).
2. When `established_base` is true AND this is an extend-existing-plan
   call (item 1's detection), a tier's runway-too-short case degrades to
   the SAME warn-and-fold-in posture the B/C tiers already have -- for
   every tier, not just B/C -- instead of a hard `raise`. The existing
   hard-refuse behavior is UNCHANGED for a fresh/cold-start build (no
   matching existing macro) or when `established_base` is false -- that's
   the real guardrail protecting the couch-to-race/unrealistic-goal case,
   and it must not get weaker.
3. ~~Revisit whether `established_base`'s binary gate should have a
   second, stronger tier for a materially longer real history~~ --
   **superseded by the correction above.** History length is a ramp-rate
   question, not a runway-gate question; not part of this fix.

## IDEA 019 - Race-week checklist content is broken for EVERY race in a season-spanning macro, not just intermediate ones (corrected 2026-09-19)

**Correction, same evening, after empirically verifying against the real
engine (not just reading the docstring the first time):** this idea's
original write-up undersold the real severity. Verified directly by
calling `generate_week` with Andrew's real, live, currently-persisted
season macro (`STORE_BACKEND=db`, real DB) for two different real weeks:

- Halloween Weekend's own week (folded in, no dedicated cycle) --
  `race_week_checklist` empty. Expected, per the original write-up below.
- **Peak Weekend's own real, dedicated taper week (Oct 5-11) -- the week
  a real A-priority race's real carb-load/bodywork/logistics content
  should obviously fire for -- ALSO empty.**

Root cause, precise: `generate_week`'s real callers
(`create_week_plan`/`replace_week_plan`, `backend/app/tools.py`) always
resolve `event = next(e for e in events if e.id == macro.event_id)` --
and `MacroPlan.event_id`'s own documented convention (`models.py`) is
"the LAST race in the season" for any season-spanning macro. So `event`
is ALWAYS Season Finale for every week generated inside this macro,
regardless of which block/race a given week actually belongs to.
`is_qualifying_race_week` (`plan.py`, `generate_week`) requires `event.id
== macro.event_id` (trivially true by construction -- it's checking the
same value against itself) AND `event.priority == "A"`. Andrew's real
season: Peak Weekend is "A", Season Finale is "B" -- so the priority gate
ALSO fails for Season Finale's own real taper week. Net result: **zero
weeks in this real, live season macro can ever get race-week checklist
content**, not "intermediate races don't get it" -- the ONE race
(Peak Weekend) that unambiguously should is silently skipped too, because
`event` is never actually about the block being generated.

**Corrected fix direction, cleaner than the original write-up's guess
(no need to thread anything through every caller):** `generate_week`
already resolves the covering `MacroBlock` for the week being generated
(`block`, in scope at the exact point `is_qualifying_race_week` is
computed) -- and `MacroBlock.race_event_id` already tags which race THAT
block is dedicated to (`None` for a single-race macro's blocks, a real
id for a season macro's dedicated blocks). Resolve the qualifying event
FROM the covering block, inside `generate_week` itself, instead of from
the single `event` parameter:

```python
qualifying_event = event
if events is not None and block.race_event_id is not None:
    qualifying_event = next((e for e in events if e.id == block.race_event_id), event)
```

Then use `qualifying_event` (not `event`) for both `is_qualifying_race_week`'s
checks and the `_race_week_checklist(qualifying_event, week_start)` call --
and drop the now-redundant `event.id == macro.event_id` comparison
(`qualifying_event` already IS this block's own target race by
construction). `None` (a single-race macro's untagged blocks) falls back
to today's exact existing behavior, byte-for-byte -- zero change for
every macro predating the season-macro build. No caller
(`create_week_plan`/`replace_week_plan`/anything else) needs to change at
all -- this lives entirely inside `generate_week`, using data it already
has in scope.

**Deliberately logged separately from IDEA 018's own build** (distinct
mechanism, distinct file region, avoids overlapping edits while that
build was in flight) -- IDEA 018 has since shipped (PR #199), so this is
now unblocked and ready to build on its own.

## IDEA 020 - The macro plan shows no marker for an imminent race outside its own scope

Found live (2026-09-19, Andrew, testing the freshly-persisted 3-race
season macro the night before his own actual race). His real race THIS
weekend (Sep 19-20) doesn't appear anywhere on the macro timeline -- the
first race marker after the current "NOW" block is "Peak Weekend Oct 17",
making it look like that's the next thing happening, when there's a real
race this weekend the view says nothing about. Andrew's own words: *"This
weekend is mislabeled Oct 17."*

**Root cause:** the season macro built via `draft_season_macro_plan` was
deliberately scoped to just the 3 forward-looking races Andrew named
(Peak Weekend / Halloween Weekend / Season Finale) -- `scaffold_season_
macro` explicitly refuses a race on or before `start` ("only plans
forward"), so this weekend's already-imminent race could never have been
one of the `event_names` in that call, and correctly isn't in
`macro.event_ids`. `macroRaceMarkers` (`web/src/plan.js`, IDEA 018's own
PR #197 sibling) only ever renders a marker for a race in `macro.event_ids`
-- exactly right for "which races is THIS macro periodizing around," but
it means any OTHER real, known event (already tracked in `events`, which
the renderer already receives) -- including one happening THIS weekend --
gets no marker at all, silently. The gap isn't a bug in either piece on
its own; it's that nothing plugs the space between "races this macro
scaffolds around" and "every real race the athlete has on the books."

**Natural fix direction (not built here):** render a marker for every
real, upcoming `Event` inside the visualized window, not only the ones in
`macro.event_ids` -- distinguished visually (e.g. a plain/muted marker,
vs. the existing dashed-red styling for a race this macro actually plans
around) so it's clear at a glance which races this specific macro's
blocks are built for and which are just nearby and real. `events` is
already threaded into `renderMacroSection` (PR #197) -- this is a
rendering-layer addition, no new data needed.

## IDEA 021 - Race-week checklist logistics text is swim-specific, even for a bike race

Found live (2026-09-19, verifying IDEA 019's real fix against Andrew's
real, live bike season macro): the checklist now correctly fires for Peak
Weekend's real taper week -- but its "logistics" items read "arrive with
enough days to spare to acclimatize to the local time zone **and water
conditions**", "confirm **on-water support (kayak/boat escort, sighting/
navigation plan)**" -- open-water-swim-specific language, for a
cyclocross race. `RACE_WEEK_LOGISTICS_LABELS` (`engine/swim_coach/
plan.py`) is a single hardcoded, athlete-agnostic tuple, documented in its
own comment as "GENERIC... not hardcoded to any one athlete's race" --
true for swim, never actually exercised for a bike race until IDEA 019's
fix, since the checklist never fired for any bike-primary season macro
before that (silently invisible, not previously wrong-and-unnoticed).

**Deliberately out of scope for IDEA 019's own fix** -- that build was
entirely about WHETHER the checklist fires (a real, severe bug: it never
fired for ANY race in a season macro, verified against production), not
WHAT it says once it does. Distinct problem, distinct fix.

**Natural fix direction (not built here):** `RACE_WEEK_LOGISTICS_LABELS`
needs a bike-primary variant (travel/timezone acclimatization stays
generic; fueling-plan rehearsal stays generic; the on-water-support item
needs a real bike-equivalent -- course recon, bike/equipment check,
support-crew or feed-zone logistics) -- same `event.primary_sport`
branch-point `_race_week_checklist`'s own caller already has access to
via `event`. `carb_load`/`bodywork` category labels/citations
(`CARB_LOAD_WINDOW_START_DAYS_OUT`/`BODYWORK_WINDOW_DAYS_OUT`) are sport-
agnostic exercise-physiology findings already -- likely fine unchanged;
only the `logistics` category's actual label TEXT is swim-specific.

## IDEA 022 - Coach API cost audit: ~$20/week, two real root causes found, execution deferred to next week

Andrew, 2026-09-20: *"coach burned through $20 in tokens in about a week.
Will need to audit usage and optimize."* This is the swim-coach app's OWN
Anthropic API billing for real athlete coach-chat conversations
(`backend/app/claude.py`, deployed Cloud Run) -- a separate cost meter
from Andrew's own Claude Code CLI usage. Audited real (not estimated)
data via `gcloud logging read` against the live `open-swim-coach-ashaber`
service; two real root causes identified with exact code citations.
**Explicit scope for tonight, per Andrew's own direction:** findings only,
no code changes -- execution deferred to next week.

**Real 7-day totals** (`"claude turn complete"` log lines,
`backend/app/claude.py:206-214`, 116 real logged turns, 2026-09-13
through 2026-09-20):

```
input_tokens               5,210,776   (fresh, full-price input)
output_tokens                140,550   (full-price output)
cache_read_input_tokens    9,921,123   (cheap, ~10% of input price)
cache_creation_input_tokens 4,846,759  (expensive -- writing NEW cache entries)
```

Per-day breakdown tracks real conversation activity closely (heaviest on
09-18/09-19, the two long coach-build sessions that week) -- not a
runaway process or a bug causing silent looping; the spend is real,
driven by real, long, tool-heavy conversations. **The headline concern:**
`cache_creation_input_tokens` (4.85M) is nearly as large as raw
`input_tokens` (5.21M) -- a cache mostly being CREATED rather than REUSED
provides little of its intended savings while adding real cost on top.

**Root cause #1 (high confidence) -- the conversation history's cache
prefix is broken by design, not by omission.** `backend/app/context.py`'s
`build_messages`:

```python
if history:
    first = history[0]
    messages.append(
        {"role": first["role"], "content": f"{context_text}\n\n---\n\n{first['content']}"}
    )
    for turn in history[1:]:
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": message})
```

`context_text` (`build_per_request_context`) is explicitly documented as
"the uncached, per-request text block" -- athlete profile, current+next
week plan, last ~28 days of logged sessions, events, load rollup --
genuinely live data the model needs accurate every turn. That design
intent is correct. **The problem is WHERE it's spliced in: `history[0]`,
the very FIRST message, rewritten fresh on every single turn.** Anthropic
prompt caching requires an exact, stable byte-prefix match from the
start of the request -- since message[0]'s content changes almost every
turn, the entire `messages` array is effectively never cacheable from
that point forward, not just message[0]. Also confirmed: no
`cache_control` breakpoint exists anywhere in the `messages` array today
at all (only the two `system` blocks attempt caching).

**Why this looks fixable without sacrificing freshness:** the code's own
docstring explains context is merged (not inserted as a separate leading
message) because the Messages API requires strictly alternating
user/assistant roles -- but that constraint is equally satisfied by
merging `context_text` into the LATEST message (the new `message`,
appended at the end) instead of `history[0]`. That would keep per-turn
freshness exactly as-is, while leaving the entire prior `history` array
byte-identical across calls -- a real, stable, cacheable prefix for the
first time. Arguably also improves answer quality (context immediately
before the question it supports, rather than buried at conversation
start). **Not implemented or tested -- flagged as the strongest
candidate for the next build, not a decision made here.**

**Root cause #2 (medium confidence) -- system block B's cache breakpoint
churns on topic changes.** `build_system` sends two cached blocks: block
A (`build_system_blocks` -- persona/rules/conventions/INDEX, stable per
athlete-sport-scope) and block B (`build_routed_block` --
`reference_list.md` + `route_library_files(message, ...)`, routed by
keyword-matching the CURRENT message). A conversation that shifts topic
(macro-planning, then fueling, then a bug report -- exactly this
session's own pattern, repeatedly) changes block B's text on nearly
every such shift. Per this file's own docstring ("a cache_control block
also implicitly caches everything before it"), a block B miss forces the
WHOLE combined system-prompt cache write to redo, even though block A
alone would still have matched -- contributing to the large
`cache_creation_input_tokens` total on top of root cause #1. Lower
confidence on relative sizing than #1 -- would need real before/after
data or per-block instrumentation to size precisely. Worth investigating
further, not concluded here.

**Secondary factor, already partly addressed for reliability (worth
noting the cost angle too):** `MAX_TOOL_ITERATIONS = 5` -- each iteration
is a full, separate API call with growing tool-result context appended.
Real log data confirms iterations up to 4 occurring in practice (matches
this session's own live incidents: `replace_week_plan` erroring and
retrying multiple times). PR #198 (merged) added real error/persisted
diagnostics for this pattern aimed at RELIABILITY -- worth remembering
every failed/retried tool call is also a full-price extra turn,
compounding whatever the caching issues above already cost.

**Verification, for whoever picks this up:** before/after comparison
using the SAME real log query this audit used (`gcloud logging read` on
`"claude turn complete"`, aggregating
`input_tokens`/`cache_read_input_tokens`/`cache_creation_input_tokens`
by day) -- a real fix should show `cache_read_input_tokens` rising
relative to `cache_creation_input_tokens`, and raw `input_tokens` falling
for turns beyond the first few in a conversation. Correctness matters at
least as much as cost here: confirm per-turn context freshness is
preserved exactly (a newly-logged workout, or a just-updated plan, must
still show up correctly in the very next turn) via real end-to-end chat
tests, not just token-count comparisons -- a caching change that
silently breaks context freshness would be a much worse outcome than the
cost problem it was meant to fix.