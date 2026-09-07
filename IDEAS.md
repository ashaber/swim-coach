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

**Suggested ordering after that** (sequencing to react to, not committed):
2) Andrew's own cyclist case (real, time-sensitive) weighed against 3) Tim
as a second primary-sport athlete (heaviest lift, validates the hardest
part) -- both real and live, worth weighing against each other for which
goes first; 4) horse-riding, once the platform is proven on a second real
primary sport; 5) research-agent expansion (IDEA 004), higher-value once
2/3 create real cross-discipline research need, though technically
independent and could be pulled forward earlier -- Tim's expert-panel
resource (IDEA 009) is a direct input here whenever it arrives.

**Cross-cutting, applies regardless of order:** the guidance-scoping
constraint above must hold from the first build onward, not be retrofitted
later.

## IDEA 009 - Tim's expert-panel resource, when it arrives

Tim is sending an updated, more specific panel-of-experts resource he
personally uses to build his own training (distinct from the ad-hoc
"panel of experts" plan already used once to validate -- never literally
transcribe -- Renee's injury-adapted taper). Two uses once it arrives,
both framed as inputs to judgment, not content to copy in wholesale:

a. **Source identification** -- who are the real coaches/physiologists/
   methodologies behind Tim's training that this project's library should
   be citing and thinking like, for rucking/running (and any other
   discipline it covers) -- direct input to IDEA 004 (research-agent
   expansion) and to any new discipline-specific library files under
   IDEA 008.
b. **Workout generation/validation** -- the resource's own workouts are a
   candidate source for either (i) enriching the library's session-
   template content directly, or (ii) serving as a validation benchmark
   for this engine's own generated/ad-hoc workouts -- "does what we'd
   propose look like what a real panel of experts would prescribe," the
   same validate-don't-copy discipline already established and confirmed
   working for Renee's taper.

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