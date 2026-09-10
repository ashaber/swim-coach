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