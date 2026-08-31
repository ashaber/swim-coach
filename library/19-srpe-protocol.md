# The Foster CR-10 session-RPE survey protocol

Grounds the athlete-facing sRPE input this engine collects and feeds into
`engine/swim_coach/load.py`'s tier-1 `session_load` calculation
(`duration_min * rpe`, see `15-tiered-session-load.md`). That file documents
the *load formula*; this file documents the *survey instrument* behind the
number itself -- the scale, its verbal anchors, and the timing convention
for asking the question -- none of which `15-tiered-session-load.md`
covers. See `00-conventions.md` for the tagging scheme and
`reference_list.md` for full citations.

## The problem this fixes

Before this build, the app's only RPE input was a bare `<input type="range"
min="1" max="10">` with no verbal anchors, no guidance on when to answer it
relative to the workout, and a 1-10 range that silently excludes "rest,
nothing at all" as a valid response (a genuinely easy technique or recovery
session has nowhere to report itself at the bottom of the scale). Of
Renee's 63+ logged workouts, only 1 carries an RPE at all -- consistent with
a survey instrument that's unclear about what it's even asking. This file
adopts the actual published session-RPE protocol instead of an ad hoc
slider, and `engine/swim_coach/models.py`'s `Workout.rpe`/
`WorkoutDraft.rpe` bound changes from `ge=1` to `ge=0` to make 0 a valid
response.

## The scale: modified Borg CR-10, 0-10 (not 1-10)

**[ADAPTED: general-endurance] Confidence: high.** **✓ Verified by direct
web search this session** (title/authors/journal/volume/issue/pages
confirmed): **Foster C, Florhaug JA, Franklin J, et al. (2001)**, "A New
Approach to Monitoring Exercise Training," *Journal of Strength and
Conditioning Research*, 15(1):109-115. The paper validated the session-RPE
method (this single global 0-10 rating, multiplied by session duration)
against an objective heart-rate-based training-impulse standard across
multiple exercise modes (cycle ergometry and basketball in the original
study), finding a consistent relationship between the two methods across a
wide variety of exercise types -- not itself a swim-specific validation.
**Test:** if session-RPE-derived load consistently reads as systematically
too low/high relative to this athlete's own HR-based TRIMP-scored sessions
(Tier 2) once enough dual-logged data exists, that's the falsification
signal -- `15-tiered-session-load.md`'s own "known limitation" section
already tracks exactly this cross-tier comparison.

This paper's own cross-discipline (not swim-specific) scope is exactly why
it earns an ADAPTED tag rather than an EVIDENCE one -- and this engine
already separately documents the swim-specific sRPE-*validity* citation
(`15-tiered-session-load.md`'s Tier 1 section: Wallace, Slattery & Coutts
2009) at the higher EVIDENCE tier, rather than re-deriving that distinction
here.

Foster's own instrument modifies Borg's original CR-10 category-ratio scale
(Borg 1962) with plain-English verbal anchors, and -- this is the detail
this app's old bare slider got wrong -- runs from **0 to 10, not 1 to 10**.
0 is a legitimate, frequently-used response (an easy recovery session, or a
technique day with essentially no perceived exertion), not an unreachable
floor.

| Rating | Anchor |
|---|---|
| 0 | Rest / Nothing at all |
| 1 | Very Easy |
| 2 | Easy |
| 3 | Moderate |
| 4 | Somewhat Hard |
| 5 | Hard |
| 6 | *(unanchored)* |
| 7 | Very Hard |
| 8 | *(unanchored)* |
| 9 | *(unanchored)* |
| 10 | Maximal / Exhausting |

Ratings 6, 8, and 9 are deliberately left without a verbal anchor in
Foster's original instrument -- not a gap in this documentation. An athlete
can still choose one of those values (e.g. "harder than Very Hard but not
Maximal"); the scale simply doesn't put a label on every integer, matching
the original published table exactly rather than inventing anchor text
Foster never validated.

## The question: one global rating per session

Session-RPE is deliberately a **single** rating for the entire session, not
a differentiated per-interval or per-segment score: "How hard was your
workout overall?" One number, asked once, covering the whole session from
warm-up through cool-down -- this is what makes `duration_min * rpe` a valid
session-level load calculation in the first place (a differentiated
per-segment RPE would need a different aggregation formula this engine does
not implement).

## Timing: ask ~30 minutes after the workout ends

**Coach judgment**, not itself a separately-cited claim from the 2001
paper: this app asks the sRPE question roughly 30 minutes after a workout's
estimated end time, not immediately at the finish line and not the next
day. The rationale is recency-bias avoidance in both directions --
immediately post-exercise, perceived exertion is dominated by the most
recent few minutes (often the hardest part, a cool-down, or acute relief at
finishing) rather than integrating the whole session; by the next day, the
specific session's effort blurs into general next-day soreness/fatigue and
becomes harder to recall accurately. A ~30-minute window gives the athlete
enough separation to reflect on the session as a whole while it's still
fresh. This project's own architecture treats the exact ask-timing as an
implementation detail of the reminder mechanism, not a claim requiring its
own falsifiable test -- the underlying CR-10 instrument's validity (the
paragraph above) is the part that carries a citation.

## What this file does not cover

This file documents the survey instrument only -- the scale, anchors,
single global question, and ask-timing convention. It does not cover:

- The load formula that consumes the resulting number
  (`duration_min * rpe`) -- see `15-tiered-session-load.md`'s Tier 1.
- The swim-specific evidence that session-RPE itself is a valid load proxy
  for swimming -- also `15-tiered-session-load.md`'s Tier 1 (Wallace,
  Slattery & Coutts 2009).
- Any UI implementation of the slider/reminder -- a separate, frontend-only
  build.
