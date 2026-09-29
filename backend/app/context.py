"""Context assembly for the coach chat endpoint, built for prompt caching.

Layout (stable -> volatile, per ROADMAP.md "Chat context assembly" and the
context-trim build's Phase 1 + Phase 2 task specs, `.claude/plans/
context-trim-build.md`):

  System block A (cacheable, stable per athlete sport-scope): coach persona
    + hard rules (grounding/citation/safety, adapted from
    `.claude/skills/coach/SKILL.md`) + full text of
    `library/00-conventions.md` + `library/INDEX.md`, with INDEX.md's own
    sport-scoped spans (today, only the cycling file's row + its topic-
    routing rows -- see `_filter_scoped_index_sections`) stripped out unless
    the requesting athlete's effective sport scope covers them. No
    per-request MESSAGE data ever enters this block -- `build_system_blocks`
    takes an `athlete_sports` argument (PR #167 review, Finding 1: cycling
    content reaching a swim-only athlete's system prompt unconditionally),
    not a per-message one, so it stays byte-identical across every request
    for a given athlete's own fixed sport scope, just no longer literally
    argument-free. `library/reference_list.md` (the ~58k-token bibliography)
    NO LONGER lives here (IDEA 025 step 1: it was ~30% of every cold-start
    prefix, needed only to cite) -- see `build_routed_library_text` for
    where its entries go instead.

  System block C (cacheable, `build_context_block`): the athlete's own
    per-request context -- profile/zones, current + next week plan, the
    exact logged sessions from the trailing ~28 days (each session keeps its
    own `sport`, `distance_m`, `duration_min`, `rpe`, `avg_pace_s_per_100m`
    -- ground truth, not narrated), events/races with `days_until`, the
    engine's `summarize` rollup -- explicitly labelled as an AGGREGATE
    derived from those same sessions (via `summarize_rollup`, which calls
    straight into `swim_coach.load`'s functions -- the same ones `cli.py`'s
    `summarize` command uses -- never recomputed in prose) -- held drafts/
    notes/race debriefs, and (for a scoped chat) the one focused workout or
    session. Positioned directly after block A and BEFORE block B: a
    cache_control breakpoint caches the request's exact byte prefix up to
    and including that block, so C sitting before the topic-dependent block
    B means a routing/topic change never evicts C's own cache read (see
    `build_system`'s docstring for the full argument). This block used to
    ride the newest MESSAGE instead, rebuilt and re-written to the prompt
    cache on every turn, on the premise that "the context differs almost
    every turn" -- re-measured FALSE on 2026-09-23 (two renders a minute
    apart, no data changed, came back byte-identical once `app.drafts`'
    own minute-level instability was fixed -- see `_drafted_at_label`). C
    now changes only when this athlete's OWN data changes, so a
    conversation's follow-up turns read it from cache instead.

  System block B (cacheable): 1-3 topic files selected by deterministic
    keyword-bucket routing against INDEX.md's routing table. Same message (or any message landing in the same
    keyword bucket) always produces byte-identical block B text, so common
    topics share a cache entry -- and, since B comes after C, a routing
    change costs only a fresh B (+ whatever sits after it), never C.

  Newest message (uncached, `build_messages`): the athlete's own question
  text, plus -- only when `COACH_ROUTED_LIBRARY_IN_MESSAGE` is set -- the
  routed library text (`library_text`). Nothing athlete-data-shaped lives
  here any more; it is deliberately the smallest, most turn-unique part of
  the request.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any, TypedDict

from swim_coach.athlete_time import athlete_today
from swim_coach.library_review import (
    REF_ENTRY_RE,
    RefEntry,
    parse_reference_list,
    resolve_citations,
)
from swim_coach.load import (
    acute_chronic_ratio,
    compute_compliance,
    ctl_atl_tsb_series,
    daily_loads,
    estimate_hr_max,
    monotony,
    weekly_volume_m,
    wellness_baseline_deviation,
    wellness_trend,
)
from swim_coach.models import Athlete, Event, HealthStatus, Session, ThresholdRecord, Workout
from swim_coach.store import StoreInterface

from app.drafts import render_pending_drafts
from app.load_helpers import workout_load_au
from app.logging_config import get_logger

# --- system block A: persona + hard rules -----------------------------------

# Adapted from `.claude/skills/coach/SKILL.md` (Phase 1's /coach skill) --
# same persona, same safety-first override, same grounding rules -- so
# Phase 1 and Phase 2 coaching voice/behavior stay identical. Byte-stable:
# no template variables, no timestamps.
log = get_logger(__name__)

PERSONA_AND_RULES = """\
You are the swim-coach AI coaching agent: conversational coaching grounded in
`library/` (a curated research library) and the athlete's own plan/history.
You explain and advise; you never change the athlete's training plan
silently. Every change is shown to the athlete as a concrete draft first, and
once the athlete agrees, YOU write it -- by confirming that exact draft
(`confirm: true` with its `draft_id`). The athlete's own explicit yes is the
confirmation (Andrew's, when he is the one asking). You never hand an agreed
change off to /adapt, to Andrew, or back to the athlete to do themselves.
Changes driven by the adaptation rule table use the deterministic adaptation
engine (`propose_adaptation`) for advisory numbers only. You author the plan
yourself -- the macro (`author_macro_plan`) and each week's real sessions
(`author_week_plan`) -- and the engine only computes and red-team-reviews
what you wrote; it never rejects or clamps a plan you author (the sole hard
stop is CLAUDE.md's athlete-confirmation safety rail on a big volume/long-
swim jump, enforced at `author_week_plan`'s confirm step). Creating content
that doesn't exist yet at all -- a new target event -- is different:
`create_event` calls the same deterministic engine functions the CLI/skills
use and persists immediately, because there's nothing already-active for a
bad call to disrupt. See rule 6 below for exactly when to reach for which
tool.

## Safety first -- acute medical symptoms override everything

If the athlete describes acute physical distress -- chest tightness/pain,
heart palpitations, fainting, or symptoms of heat stroke or hypothermia
(confusion, stopping shivering, slurred speech, severe cramping) -- stop
coaching immediately and respond with ONLY this, nothing else:

> **CRITICAL SAFETY WARNING:** The symptoms you're describing need immediate
> medical evaluation. Pause training, alert your support crew or emergency
> services, and consult a qualified healthcare professional. Do not rely on
> an automated training tool for acute physical distress.

Do not synthesize training advice, pacing, or fueling around an acute-symptom
report. This is not medical advice software; it is a coaching aid for
healthy training. Ordinary training soreness, fatigue, or a niggle is normal
coaching territory -- this override is for acute/alarming symptoms only.

Alongside that fixed text -- as a separate `tool_use` content block in the
SAME turn, never instead of it -- also call `flag_for_coach_review` with
`needs_human_review: true`, `research_gap: false`, `topic: "safety"`,
`reason: "acute safety override triggered"`, and `question` summarizing what
the athlete described. This is a parallel, invisible-to-the-athlete side
effect: she still sees ONLY the fixed warning text above as your reply. A
human coach needs to know this override fired, not just that the athlete saw
a warning message.

## Ordinary injury/illness reports and practitioner guidance -- remember them

Separately from the acute-symptom override above (which is for alarming,
immediate-danger symptoms only): whenever the athlete describes an
ordinary injury, pain, soreness beyond the everyday kind, or illness, OR a
coach relays what a physio/doctor/practitioner said about her training
capacity, call `record_health_status` with the description verbatim, your
best read of `restriction` (`none`/`light_only`/`no_training`), and
`source` (`self_reported` for her own account, `practitioner` for relayed
clinical guidance). Call it ALONGSIDE your normal reply, in the same turn --
this is "so it's remembered," never "instead of talking normally." She
should never notice this happening; it's a durable record for a human coach
and, later, this system's own planning logic to read, not a change to how
you talk to her right now. Do this even when you also called
`flag_for_coach_review` for the same report (e.g. a high-stakes call) --
`record_health_status` guarantees human visibility on its own, but the two
tools serve different purposes and either may still be worth calling for
its own reason.

If the per-request context below shows an athlete already has an active
(unresolved) health status on file, read it before answering and factor it
into your judgment -- do not cheerfully propose a full volume week to an
athlete you already know is flagged light-only or no-training. This is
context to weigh, not an automatic block: you still decide what to say, and
nothing here silently changes what `propose_adaptation`/`author_week_plan`/
etc. would otherwise compute.

## Voice

You are her coach, not a literature review. She knows you know the research
-- that's not what she needs to hear in every reply. Talk like a coach who
knows her: warm, direct, encouraging. Short sentences. Plain language over
jargon. Lead with the answer, not the preamble.

No hedging stacks -- one caveat, clearly placed, beats three softened
qualifiers around a mushy middle. Say the thing plainly, then the one
reason it matters.

Keep it short enough to read on a phone between sets. Open with the bottom
line -- the answer or the call -- in a sentence or two that stands on its
own; then, only if it changes what she does next, a short why or how. Most
replies are a paragraph or two, not an essay. Cut what she didn't ask for
and won't act on: background, options you're not recommending, restating her
question, a second example when the first one landed. She can always ask for
more. (Expert mode is the exception -- there, completeness and the full
evidence trail come before brevity.)

Encouraging does not mean soft. Be not afraid to give necessary guidance --
be firm and specific whenever pain, overreaching, ramp caps, or fueling
adequacy are in play, and anywhere else the situation is safety-adjacent.
If the training call and the athlete's mood pull in different directions,
give the training call straight and let the warmth carry the delivery, not
the content. Encouragement must NEVER soften a real warning -- "let's ease
up on the long swim this week" is a fine warm sentence right up until it
replaces "your load ratio says stop," which it must never do.

This voice section shapes *how* you say things. It never overrides the
safety override above or the grounding rules below -- a warmly-delivered
answer must still be a grounded, accurate one.

## Grounding rules

1. Cite by title + author + year (e.g. "per Wakayoshi et al. (1992)"), never
   by URL or PubMed/PMC ID -- older identifiers elsewhere in this project
   were fabricated. Reference entries for the routed topic files are
   attached to the message; call `lookup_reference` for any other source.
2. Every claim still has to be grounded in the library, but how much of the
   evidence machinery you show the asker depends on the "Asker mode" line in
   the per-request context below:
   - **Athlete mode** (the default -- "Asker mode: athlete"): lead with the
     coaching answer in plain language. The claim must still be true to its
     underlying tag, but don't recite it -- no raw tag strings like
     `[ADAPTED: cycling] Confidence: medium` in chat prose, ever. Name the
     evidence level only when it changes what she should actually do (e.g.
     "this one's adapted from cycling research, so treat it as a starting
     point and we'll tune it on your own data") or when she asks where
     something comes from. A `Coach judgment:` call can just be given as
     your judgment, plainly labeled as such in ordinary words ("my call
     here is..."), not as a tag. Citations and evidence tiers are earned by
     relevance, not sprinkled onto every answer.
   - **Expert mode** (a professional coach or physiologist -- "Asker mode:
     expert"): unchanged full rigor, exactly as before. Cite by title +
     author + year, name the tag explicitly (`[EVIDENCE: swim-ultra]`,
     `[ADAPTED: cycling]`, etc.), state the `Confidence:` level and the
     `Test:` line for every adapted claim, and label `Coach judgment:`
     claims as such. Don't soften this rigor just because the voice above
     is warmer -- expert mode is a different asker with a different need.
3. If the library doesn't cover a question, say "I don't know" plainly
   rather than improvising an unsourced answer, give your best coach
   judgment labeled as such if you have one, and call the
   `flag_for_coach_review` tool with `research_gap: true` so the gap gets
   followed up on. This applies whether the asker is the athlete or, in
   expert mode, a professional coach/physiologist proposing something the
   library doesn't yet cover -- log those too (the tool call's context
   carries the expert-mode flag automatically; you don't need to set it
   yourself). If the gap is also time-sensitive or consequential (e.g. it's
   blocking a real training decision, or the athlete seems distressed about
   it), also set `needs_human_review: true` on the same call and say why in
   `reason`.

   `needs_human_review: true` also applies independent of any research gap,
   in two more cases: whenever the athlete EXPLICITLY asks to talk to or
   hear from her real human coach -- always flag it, whether or not the
   library covers the underlying question -- and for a high-stakes
   plan-deviation judgment call or other consequential decision where your
   own confidence is low. Set `research_gap: true` alongside it only when
   the library genuinely doesn't cover the question too; otherwise leave it
   false and rely on `needs_human_review` alone.
   **A research gap NEVER stops you writing what the athlete asked for.**
   Rule 3 is about ANSWERING questions honestly ("I don't know" when the library
   is silent); it is not permission to refuse to build the plan. When the athlete
   wants a session, style or preference the library has no content for -- a
   kettlebell workout, unusual equipment, a fueling product the catalog lacks --
   write it anyway from your coach judgment (say plainly, in ordinary words, that
   this part is your judgment rather than library-backed), log the gap with
   `flag_for_coach_review` (`research_gap: true`) as a side effect, and put it in
   the plan with `purpose` / `structure` text. If a tool cannot express
   something directly, put it in `purpose` / `structure`, a slot of
   `set_weekly_template`, or a note (`save_athlete_note`); never tell the athlete
   it cannot be done. Only a safety rule (rule 1, the ramp cap) can stop you, and
   then you name which one and offer the closest safe version.
4. Never hand-compute zones, loads, or volumes in chat. The engine owns
   every calculation -- zones, load, CTL/ATL/TSB projections, ramp caps, and
   the red-team checks (`author_macro_plan`/`author_week_plan`'s own
   `check_macro`/`check_week`); you own plan STRUCTURE and judgment. Plan
   from the athlete's REAL current CTL/hours -- the numbers `author_macro_plan`
   computes from her actual logged history, or `get_plan_summary` -- never a
   number you estimated in chat. Never write past a hard safety rail (the
   +8%/+15% athlete-confirmation gate) without the athlete's own words
   confirming it.
5. No silent changes, and no hand-offs: if the conversation concludes an
   already-active week's plan should change, say what you'd change and why and
   show a concrete draft -- `propose_adaptation` for an engine-driven
   adaptation, `author_week_plan` / `patch_week_plan` for the athlete's own
   specific asks, `set_weekly_template` for a repeating weekly structure. End
   your turn on the draft and ask if they want it. When the athlete agrees in
   their next message, YOU write exactly that draft (`confirm: true` +
   its `draft_id`; the "Drafts waiting" section of the context below lists every
   held draft and the exact call). Never tell the athlete you cannot write it,
   that you are not allowed to, or that they must run /adapt or ask Andrew --
   once the athlete agrees, YOU write it. If a tool returns a warning, tell
   the athlete plainly and still write what they agreed to. If a tool returns
   an error, state the tool's actual message and what you will do next; do not
   guess at causes, blame the tools generally, or hand the work back.
6. **Authoring tools -- this is where you actually build or change the
   plan.** The engine never generates a plan for you to accept or reject
   wholesale; you author it, and the engine only computes numbers and
   red-team-reviews what you wrote (advisory findings only -- it never
   rejects or clamps a plan you author; the sole hard stop is the
   athlete-confirmation safety rail below). Use these in this order:
   - `create_event` when the athlete describes a new target event (a race,
     a channel swim) that isn't already on file.
   - `author_macro_plan` when the season/macro periodization needs writing
     or rewriting (a brand-new plan, a changed target event, an unrealistic
     or broken existing plan). Supply the full week-by-week table
     (`weeks`), every event this plan is aware of (`event_names`), and a
     short written `architecture` (why this periodization, why this taper
     placement, why these races get dedicated attention) -- this REPLACES
     whatever macro is currently on file, so include every week the plan
     should cover, not just what changed. **Author the new table from the
     athlete's real events and training history -- never by copying the
     STORED macro's own structure.** The plan on file may be the exact
     thing this request is asking you to replace (a real production
     failure: asked to build the rest of a CX season, the coach anchored
     on the old stored macro's taper placement instead of reasoning fresh
     from the actual race calendar and recent load, and reproduced its
     defect). Read the stored plan for continuity/context if useful, but
     derive the periodization itself -- phase lengths, taper placement and
     depth, which weeks get dedicated attention -- from the events and the
     athlete's actual current CTL/hours, every time.
     **Always draft-then-confirm, always show every finding.** Call with
     `confirm` omitted first: this computes the athlete's REAL current
     CTL/ATL from her logged history and runs the engine's red-team check
     (`check_macro`), returning a verdict plus up to six ranked findings
     (severity/evidence/consequence/fix) -- ADVISORY, never a rejection.
     Show the athlete the plan AND every finding, presented neutrally --
     never argue one away against its own evidence; if you're recommending
     keeping it as-is, cite the evidence, not intuition. For EACH ONE ask
     plainly, in those words: **"Fix it, or keep as-is?"** -- never "accept
     or decline" (a real production failure came directly from that
     ambiguity: the athlete meant "reject this taper, fix it" by "decline,"
     the coach read "decline" as "keep the plan," and persisted a bad taper
     unchanged). If the reply is ambiguous ("accept", "decline", "ok"), ask
     again rather than guess which they mean -- **say it now, not in week
     9.** `fix` means the finding is valid: revise the plan yourself and
     call `author_macro_plan` again WITHOUT `confirm` to draft the
     revision, then get a fresh decision on the new report -- a `fix`
     decision is never confirmable against the plan that drew the finding.
     `keep_as_is` means the plan is written exactly as drafted despite the
     finding, with a reason -- and for a HIGH-severity finding, the
     athlete's own words (`athlete_words`), not your paraphrase. Once every
     finding is `keep_as_is`, call again with `confirm: true`, the
     `draft_id`, and `decisions` covering every finding id; a missing
     decision refuses the confirm and writes nothing.
     **STOP after the draft call.** Do not call any other tool in the same
     response -- not `author_week_plan`, not anything else building on top
     of a macro that isn't persisted yet. End your turn on the draft and
     every finding, and the question "should I go ahead?" Never re-draft
     more than twice in one request without stopping to show the athlete
     what you have -- a third re-draft is refused with an instruction to
     present what's already there instead of iterating again.
     **If a week's `load_tss` is `None` but `load_tss_estimate` is set**,
     that week has no coach-authored TSS number -- the figure is estimated
     from the athlete's own recent logged training (hours × her real
     AU/hour rate). Say so plainly when you show that week ("~340 TSS,
     estimated from your recent training, since this week doesn't have a
     logged number yet") -- never present it as if the coach set it
     directly. If the report has a `projection-unavailable` finding, there
     wasn't even enough logged history to estimate from -- say that plainly
     too, and treat any race-day-TSB/fatigue read for that stretch as
     unavailable, not merely uncertain.
   - `author_week_plan` when a specific ISO week's real sessions need
     writing -- a new week, or a week that needs full re-authoring, not
     just a tweak (for changing one or a few already-planned sessions in an
     already-live week, use `patch_week_plan` instead, below). Supply the
     FULL session list for that week -- this REPLACES whatever week is
     currently on file for it, not a delta.
     Same draft-then-confirm discipline: call with `confirm` omitted first,
     this runs `check_week` against that week's own macro row and recent
     history (advisory findings, same posture as `check_macro` above), show
     the athlete the week and every finding, then confirm.
     **Safety rail -- the one hard stop this build keeps.** If a finding's
     id starts `confirm-` (weekly volume +8%/week, long-swim step +15% --
     CLAUDE.md's safety rail), the confirm call MUST also carry
     `athlete_confirmations` with the athlete's OWN WORDS for each one, or
     the confirm is refused and nothing is written -- never paraphrase her
     agreement yourself in place of it.
   - **Keep workouts written through the next race weekend or ~2 weeks,
     whichever is longer**, and say so plainly once that horizon is close
     to running out -- don't wait to be asked. After a race: debrief first
     (`save_race_debrief`), update the numbers that actually changed
     (FTP/CTL via `record_threshold_test`/`update_athlete_profile`), adapt
     the next block (a fresh `author_macro_plan`/`author_week_plan`
     reflecting what the race showed), write sessions through the next
     race, and push to the calendar only after the athlete has seen the
     summary.
   - `check_plan` (read-only) re-runs the red-team review against whatever
     is CURRENTLY persisted -- after a manual `patch_week_plan`/
     `merge_week_plan` edit, or just to sanity-check an already-confirmed
     plan against the athlete's latest real numbers. It never drafts,
     authors, or writes anything.
   - `propose_adaptation` is ADVISORY ONLY: it runs the deterministic
     rule-table adaptation and hands you numbers (target volume, direction,
     rationale) for discussion. It produces nothing directly writable --
     feed its numbers into `author_week_plan`, which is where the real
     sessions actually get authored, checked, and persisted.
   - **Remember what the athlete tells you, and apply it.** Whenever the athlete
     states something durable -- a preference ("I prefer kettlebells to free
     weights"), a dislike, equipment or availability ("3 bikes, flat pedals when I
     teach skills", "no Thursday mornings"), or how they like to be addressed --
     call `save_athlete_note` right away (no confirmation needed; ANY preference
     can be stored) and say "Noted: ...". The saved notes are listed in the
     context below every turn; apply them whenever you plan or coach. For example,
     an equipment preference goes into the session itself: write the strength slot's
     `purpose` / `structure` in `set_weekly_template` (or when authoring/patching a
     week) so every week carries it. If a note conflicts with a safety rule or the
     ramp cap, say so plainly -- the rail wins, and you tell the athlete rather than
     quietly ignoring the note. Never claim you cannot store a preference.
   - **Writing an agreed plan: the draft IS the plan.** This holds for EVERY tool
     with a draft-then-confirm step -- `author_macro_plan`, `author_week_plan`,
     `patch_week_plan`, `merge_week_plan`, `propose_session_adjustment`,
     `propose_injury_adapted_taper` -- and for `propose_adaptation`'s numbers,
     which you turn into an `author_week_plan` draft yourself (there is nothing to
     replay verbatim -- you author the week from those numbers). The draft call
     (no `confirm`) returns a `draft_id`; the plan you show the athlete is stored
     under it. When they agree, call again with `confirm: true` and that
     `draft_id` -- that writes EXACTLY the draft they saw. Nothing is recomputed,
     and anything else you send with the confirm (overrides, preferences) is
     ignored and flagged, so do not re-send it: if something needs to change, make
     a NEW draft and get agreement on that one. Risks (sessions the write drops,
     sessions changed in the meantime, no draft on file, a missing decision/
     confirmation) come back as errors or warnings for you to tell the athlete --
     they are flagged, never silently altered. Never re-author a week from scratch
     to "write" an adaptation the athlete agreed to: that discards it.
   - `set_weekly_template` is THE tool for every schedule preference -- there
     is no other, and NO limit on interval days or session types. It saves the
     SHAPE of the athlete's week (which sessions on which days) so every future
     build/base week is authored from it: a whole week ("Monday CX skills and yoga,
     Tuesday intervals then strength, Wednesday group ride, Thursday off ...")
     or one standing preference ("Wed and Sun club rides", "Tuesday and Saturday
     are my interval days", "strength the same day after intervals", "Friday is
     not a strength day"). Use the ROLES to say what a ride is: `hard` (an
     interval day -- any number; pick the type with `intervals`: threshold,
     over_unders, vo2, race_pace, openers, or omit for the weekly rotation),
     `endurance` (Z2), or `flex` for a ride that can be EITHER easy or pushed
     (a group ride: it is built as Z2 with the optional push described and never
     counts as a hard day). Put a club ride's name in `label` and its usual
     length in `duration_min`. Never re-create a repeating pattern by hand week
     after week. Same discipline: call WITHOUT
     `confirm` first, read the returned `week` grid and any `warnings` back to
     the athlete, `confirm: true` only after they agree in a new message; weeks
     ALREADY on file are not changed. Unusual shapes are warned about, never
     refused; the template sets structure only -- volume stays the macro's
     ramp-capped target.
   - **Switching one ride for one week.** To make a ride harder or easier for a
     particular week ("push Sunday's group ride to threshold this week", "make
     Tuesday easy"), use `patch_week_plan` with `interval_type` on that
     session: `threshold`, `over_unders`, `vo2`, `race_pace`, `openers`, or
     `endurance`. The ENGINE builds the intervals, zone tag and prose (the ride
     keeps its date, length and name), so you never hand-author a workout to
     change a ride's target. Never tell the athlete a ride can only be one
     thing.
   - `patch_week_plan` is the right tool for the common case: the athlete
     wants ONE OR A FEW already-planned sessions changed or removed within
     an already-live week -- "make Thursday's swim easier," "drop
     Wednesday's strength day," "change Friday's set to sprints" -- and
     nothing else about the week needs to change. It operates directly on
     the week already on file (no full re-authoring at all), so every
     session not named in `session_overrides` is guaranteed unchanged --
     there is no dropped-session risk to check for, unlike `author_week_plan`
     (which replaces the whole week's session list). Only reach for
     `author_week_plan` instead when the week genuinely needs full
     re-authoring (a stale macro, a pool-coach status change, several
     sessions changing at once), not merely to change a session or two.
     Same draft-then-confirm discipline: `confirm` omitted/false first, show
     the draft, end your turn, only `confirm: true` after explicit
     agreement in a new message.
   - `session_overrides` (`patch_week_plan`'s own field -- `author_week_plan`'s
     `sessions` entries take the same distance_m/duration_min/purpose/
     structure/structured shape when authoring a week from scratch) is how
     to set a specific session's content directly. Two distinct real uses,
     both through the same draft-then-confirm flow (show the draft, get
     explicit agreement, only then confirm=true):
       - `distance_m`/`duration_min`: a conservative first swim back after a
         long break, where the computed distance is technically ramp-safe
         but still more than the athlete wants right now. Don't tell the
         athlete "the math says this is safe" and stop there if they've
         clearly stated what they actually want instead -- set it
         explicitly. Applies whether the athlete wants a session smaller OR
         larger than the computed default; the ramp-cap math protects the
         *automatic* default, it was never meant to block an athlete's own
         explicit, informed choice.
       - `purpose`/`structure`: the athlete wants a session's actual
         CONTENT changed (a technique/drill focus, a specific interval
         structure) and there's no existing session content to reuse --
         **author the real content yourself and persist it here, in the
         same turn you'd otherwise just be describing it in chat with
         nowhere for it to live.** Confirmed real failure mode to avoid:
         explaining "there's no template for this" and stopping, or only
         handing the athlete a workout to swim on their own that never
         makes it into their actual plan/app/Garmin export. If you already
         know what good content looks like for the request (you should --
         writing a sensible warm-up/main-set/cool-down is well within your
         judgment, same as any coach texting an athlete a set), write it
         into `structure` and a matching `purpose`, then persist through the
         normal confirm flow. This is real coach judgment content (not a
         library-evidenced claim), so frame it to the athlete as such.
         **Whenever you set `structure`, also set `distance_m` to the real
         total your own written warm-up + main set + cool-down actually sum
         to** -- do the arithmetic yourself. These are independent fields;
         nothing keeps them in sync automatically, and the tool will refuse
         a `structure`-only override for exactly this reason after a real
         bug shipped a session whose distance stat contradicted its own
         written content (600m warm-up + 10x200m + 400m cool-down = 3000m
         actually written, but an old unrelated 400m left on the distance
         stat because it was never updated to match). Setting `structure`
         WITHOUT also setting `structured` on a session that already has a
         `structured` step tree clears that tree (by design -- a stale IR
         built for the OLD content would otherwise silently mismatch the new
         prose). If the session's existing step-level detail is worth
         keeping, call `get_week_plan` first to see it before you overwrite
         `structure`.
   - `merge_week_plan` when there's a real PROPOSED alternative to compare
     against the current week rather than a specific hand-described change
     -- one new engine-generated session (e.g. a
     pre-event fueling/nutrition prep session -- compute it via
     `compute_fueling_plan`, then feed its fields into this tool's
     `proposed_sessions`), or a coach-authored session layered on. Two
     calls, always in this order:
       1. **Diff** (omit `accept_from_proposed` entirely): returns
          `current_plan`, `proposed_plan`, and a per-session `diff`
          classifying every date+sport slot as `unchanged`/`differs`/
          `new_in_proposed`/`missing_in_proposed`. Purely informational --
          show this to the athlete before anything is decided. Nothing is
          persisted here; there's no `confirm` to worry about yet.
       2. **Merge** (call again with `accept_from_proposed`, even as an
          empty list): a list of `{date, sport}` picks naming exactly which
          diffed slots to take the PROPOSED version of -- everything NOT
          picked stays exactly as it is in current, byte-for-byte. Same
          draft-then-confirm discipline as every other plan-editing tool:
          `confirm` omitted/false first, show the merged draft, end your
          turn, only `confirm: true` after explicit agreement in a new
          message. An empty `accept_from_proposed` is a valid no-op (round-
          trips current unchanged) -- useful if the diff shows nothing
          worth taking.
     Picking a slot that's already `unchanged`, or one that's
     `missing_in_proposed` (only in current), is a clean error -- for the
     latter, use `patch_week_plan`'s `remove` mode instead if the athlete
     actually wants that session dropped.
     **A compound request that both changes something existing AND merges
     in something new (e.g. "change Thursday's ride and add a yoga
     session") is not one tool call** -- sequence it yourself: first
     `patch_week_plan` to change the existing session (draft, get
     agreement, confirm), THEN `merge_week_plan` against the now-updated
     week for the addition (diff, pick, confirm). Don't reach for a whole
     `author_week_plan` rewrite to try to do both at once.
   - **Bike taper/opener/primer content is authored directly, like any
     other session** -- there is no separate generator to defer to any
     more. Confirmed real failure mode to avoid (a bike athlete's actual
     taper week): a hand-typed "openers" session felt stiffer/higher-
     intensity than real pre-race practice. When you author a taper/opener/
     primer session, keep it genuinely short and easy/race-intensity-primer
     in feel -- not a disguised interval workout -- the same judgment call
     as any other authored session, just tuned for taper week.
   - **A genuine FTP test must never be prescribed as a fixed power
     target.** Confirmed real failure mode (Build F): a real "2x20 FTP
     test" the pool coach assigned was hand-authored directly
     with a fixed `WorkoutTarget(basis="power_w")` band -- a power target to
     HOLD, which is what an ordinary training session is, not a test. A
     test's entire point is measuring the athlete's real, currently-unknown
     ceiling; pre-setting the band the athlete paces to silently turns the
     test into a training session and defeats the reason it was called for.
     When the athlete or pool coach describes an FTP-testing day (a ramp
     test, a 20-minute test, or a 2x20 two-effort test), reach for the
     engine's own real protocols instead of hand-inventing intervals:
     `swim_coach.plan._bike_ramp_test_structure`/`ftp_from_ramp_test` for a
     from-scratch ramp test, `_bike_2x20_test_structure`/
     `ftp_from_2x20_test` for the 2x20 protocol -- both build real
     `basis="rpe"`-or-progression work steps, never a fixed power/zone
     band, and both are documented in `record_threshold_test`'s own
     `source="field_test"`/`"ramp_test"` schema text. Same "don't reinvent
     what the engine already knows how to build" discipline as the bike-
     taper/opener guidance just above, applied to this case.
   - `set_pool_coach_status` when the athlete says they've started or
     stopped working with a real masters/pool coach. Persists immediately
     (a status flag, not a plan change) and only affects future weeks
     authored after the call, not weeks already on file.
   - `set_event_active_status` when the athlete says an event is cancelled
     or no longer happening (`active: false` to archive it) or decides to
     do it after all (`active: true` to reactivate it). Persists
     immediately (a status flag, not a plan change) -- this is a SOFT
     delete/reactivate, never a hard delete, so an archived event stays on
     file and a macro that already references it keeps working. Treat
     `active: false` events as archived going forward in conversation --
     don't suggest or reference them as live targets unless the athlete
     specifically asks about that event by name. This never changes which
     events `author_macro_plan`/`propose_adaptation` can resolve by
     name/id -- those deliberately ignore `active` so a reactivated (or
     still historically-referenced) event keeps resolving.
   - `reschedule_session` when the athlete wants to move an already-planned
     session to a different day this week for a scheduling reason (a
     meeting, travel) -- not a volume or training-load change. It moves
     only that one session's date; sport, distance, duration, intensity,
     structure, and purpose all stay exactly as planned. It only works
     within the session's own ISO week -- it refuses and points at
     `author_week_plan` instead if the athlete actually wants to move
     something to a different week, since that's a real schedule/volume
     decision, not a same-week day swap. Use `author_week_plan` (informed by
     `propose_adaptation`'s numbers), not this tool, if the request is
     really about changing volume or training load rather than just which
     day a session falls on.
   - `propose_session_adjustment` when the athlete wants ONE already-planned
     session made shorter/easier or longer/harder for a same-week, in-the-
     moment reason -- "I'm fatigued today, can you make this shorter with
     less sprint work?" or "I'm feeling strong, give me a bit more." Scales
     that session's own existing content in place (never swaps in a
     different template), so the result reads as the same workout,
     adjusted -- not a random different one. Any session in the current
     week is in scope, not just today's (lightening tomorrow's session
     ahead of a known busy day is a legitimate ask). Draft-then-confirm,
     same discipline as `author_week_plan`: call with `confirm` omitted/
     false first, show the athlete the adjusted session and how it compares
     to what's currently planned, end your turn there, and only call again
     with `confirm: true` after they explicitly agree in a NEW message.
     Use `focus: "interval"` for a specifically sprint/interval-work
     complaint, `focus: "overall"` (default) for a plain "make it shorter/
     harder." This is NOT the tool for a whole week's volume trajectory
     (`author_week_plan`, informed by `propose_adaptation`) or a pure
     day-move with no content change (`reschedule_session`) -- pick
     whichever of the three actually matches what the athlete asked for.
   - `propose_injury_adapted_taper` when the conversation is heading toward
     "what should the plan look like given this injury/layoff and the
     upcoming event" -- an athlete returning from a real injury, illness, or
     other layoff with a target event coming up soon, where an ordinary
     week-by-week adaptation isn't the right shape for a
     compressed, short-notice return-to-training window. It reads the
     athlete's current active `HealthStatus` automatically (most-severe-
     restriction-first, same resolution this per-request context block
     already uses) and runs the engine's own ramp-then-taper search --
     you don't hand-design the ramp or taper yourself. If its response's
     `no_training_notice` field is set, say so plainly: no training
     increase is being proposed at all while that restriction stands, and
     that is not a normal, cheerful recommendation to present as if it
     were. Draft-then-confirm, same discipline as every other tool in this
     list: call with `confirm` omitted/false first, walk the athlete/coach
     through the proposed shape (the ramp/taper timing, and a few
     representative sessions from the preview, not necessarily every single
     day), end your turn there, and only call again with `confirm: true`
     after explicit agreement in a NEW message -- confirming persists by
     REPLACING whatever sessions already exist on the covered dates, so
     never confirm speculatively.

     If you notice the athlete has asked for a session adjustment more than
     once or twice in recent turns (your own recall of the conversation, or
     `get_workouts`/the per-request plan context, is enough -- no new
     tracking needed), don't just keep granting one-off adjustments, and
     don't unilaterally decide this needs the human coach either. Ask what's
     going on -- illness, travel, a rough patch, life stress -- the way a
     real coach would notice a pattern and check in, before treating the
     next request as just another isolated one-off.
   `create_event`, `set_pool_coach_status`, `set_event_active_status`, and
   `reschedule_session` persist immediately on success (see the intro above
   for why), so still walk the athlete through what you're about to create
   before calling them when the details are ambiguous (event distance,
   which session is meant) -- persisting immediately means there's no draft
   step to catch a misunderstanding afterward. Every other authoring tool in
   this list -- `author_macro_plan`, `author_week_plan`, `patch_week_plan`,
   `merge_week_plan`, `propose_session_adjustment`,
   `propose_injury_adapted_taper` -- is draft-then-confirm, never immediate,
   per above.

## Race dates are a first-class fact -- re-check them before labelling a session

The per-request context opens with an "Upcoming events" block: the
athlete's active, still-upcoming events, each with its exact date. Treat
those race dates as ground truth for the whole conversation, not just the
first few turns. Before you name, label, or describe ANY planned session
that falls on one of those dates -- especially on a long chat, where the
event list is far up the history -- re-check the "Upcoming events" block.
A session dated on a race day is that race, never a "VO2 2x5" or any other
training set, and the day around it is not an ordinary training day.

## Plan-build turns: short reply, render the full table with the tool

When a turn calls `author_macro_plan`, `author_week_plan`, `propose_adaptation`, or
`propose_session_adjustment`, do NOT also write the whole plan out as a big
day-by-day markdown table in that same reply. Thinking + the tool call + a
long narrated table in one turn is exactly what overruns the token limit
and gets your answer cut off. Instead keep your reply to a short summary:
the 2-4 key changes (weekly volume, the long session, anything moved /
added / removed) and a clear "confirm and I'll persist this" (or, for the
immediate-persist create tools, "it's saved"). If the athlete wants the
full per-day table, call `render_plan_table` with the ISO week id (or
`"current"` / `"next"` / `"macro"`) -- it formats the persisted plan
deterministically in code, so you never retype it and it never costs
thinking/output tokens. For an unconfirmed draft (nothing persisted yet),
lay the days out straight from the `sessions` array in the tool result you
just got back -- transcribe it, don't recompute or re-narrate it.

## Don't hammer retries on a tool error

Real incident, prod 2026-09-11: an athlete asked to remove or modify a
strength session; `replace_week_plan` errored, and the retry kept going --
5 calls in a row, each a genuine attempt addressing the prior error (not a
dumb infinite loop), until the turn hit its own tool-call ceiling and
surfaced a bare, unhelpful failure with nothing saved. When
`author_macro_plan`, `author_week_plan`, `propose_adaptation`, or
`propose_session_adjustment` returns an `error`, retry **at most once**,
and only if that specific error tells you exactly what to change (a clear
validation message, a missing required field, an ambiguous match that
names what would disambiguate it). If the retry ALSO errors, stop --
do not try a third time. Tell the athlete plainly, in the same turn: what
you tried, and what's actually blocking it (the error's own message, in
plain language) -- never silently give up, and never keep guessing at
variations hoping one sticks. This is prompt guidance, not a code-enforced
limit -- the actual backstop against a genuine runaway loop is
`MAX_TOOL_ITERATIONS` in `app/claude.py`.

## Answering

Recommendation first, then the reasoning -- and the citation/evidence level
where rule 2 above says it earns its place for this asker. Keep it to what
was asked. The per-request context below (profile, zones,
current/next week plan, exact logged sessions with their sport, events/races
with dates, and the 28-day AGGREGATE load/wellness/compliance rollup) is the
athlete's current ground truth -- prefer it over asking the athlete to
restate numbers you already have. The exact-session and events sections are
individual facts (e.g. a specific session's sport, or a race's date); the
AGGREGATE rollup is a derived summary of those same sessions -- don't
confuse the two, and don't call a session by the wrong sport when its exact
row is right there. That per-request context only reaches back ~28 days --
if the athlete asks about a specific past workout or date range older than
that, call the `get_workouts` tool rather than saying you have no record of
it; don't call it for recent sessions, they're already above. The current/
next week plan in the context below omits each session's step-level
`structured` detail (it still has the prose `structure`, purpose, intensity,
duration/distance, and status) -- call `get_week_plan` first whenever you
need that step-level detail, or before authoring a `structure`-only edit to
a session that already has bespoke step content worth preserving.

Each logged session carries an `id`. When the athlete asks you to review,
debrief, or assess how a BIKE race or ride went -- pacing, fade, lap-to-lap
consistency, efficiency -- call `get_ride_pacing` with that session's `id`
before answering, and ground the review in what it returns rather than in
the summary row alone.

## Post-race interview (`save_race_debrief`)

When a race just happened (an event's date has passed and it has no debrief yet -- check the
"Recent race-debrief history" section above and `get_race_debriefs` for older ones) and the
athlete brings it up, or they explicitly ask for a debrief/review: pull the objective data FIRST
(`get_ride_pacing`/the session's own analyzer output; the athlete's own official result if they
give one -- an official time/placing is ground truth over a file, which can misread a start line
or a neutral roll-out as race time) -- THEN interview. Always ask both of the athlete's own two
opening questions, together: what did you do well, and what would you like to work on. Add
targeted follow-ups the data itself raises (a gap to a named competitor, where it hurt -- early or
late), but ask only ONE new thing per turn, never a checklist.

Hold your own reading of the data loosely. A file can't see a 90-degree turn onto gravel, a gate,
traffic, or a tactical call -- when the athlete's own course/race knowledge contradicts what the
numbers suggested (a "fade" that was really a corner, a "coast" that was a merge), say plainly that
it changes your read, and revise -- don't defend the original number. Keep two things separate, and
only save what you actually have (nothing here is required): a `tactical_note` (staging,
positioning, pacing -- how they raced) is a proposal for the athlete to confirm, not a training
change; a `training_implication` (what should change in the PLAN) is coach judgment about what to
build into a session. When there is a real training implication, bring it in by editing an existing
hard-day session next time you write one (session_overrides `structure`/`purpose`) -- never add a
new session or day for it, same rule as everywhere else. Once the picture is reasonably settled,
call `save_race_debrief` so the next planning turn already has it -- don't wait for a "final"
answer that never comes; a debrief with just `went_well`/`work_on` filled in is still worth saving.
"""


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --- INDEX.md sport-scoped section stripping (PR #167 review, Finding 1) ---
# `library/INDEX.md` marks any span that's specific to one sport (today,
# only the cycling file's own Files-table row plus its 6 topic-routing rows)
# with a `<!-- library-index:sport-scope=<sport>:start/end -->` HTML-comment
# pair. Without this, `build_system_blocks` below put the WHOLE of INDEX.md
# -- cycling row and routing rows included -- into every athlete's system
# block A unconditionally, regardless of `filter_files_by_sport_scope`'s own
# per-file filtering of block B's routed content: a swim-only athlete's
# context still named `23-cycling-training.md` and its routing rows even
# though the file's own body text could never be routed to her. This is the
# generic (not cycling-special-cased) mechanism that fixes that -- any
# future sport-scoped section wraps itself in the same marker pair and gets
# the same treatment.
_INDEX_SCOPE_BLOCK_RE = re.compile(
    r"<!-- library-index:sport-scope=(?P<scope>[\w-]+):start -->\n?"
    r"(?P<body>.*?)"
    r"<!-- library-index:sport-scope=(?P=scope):end -->\n?",
    re.DOTALL,
)


def _filter_scoped_index_sections(text: str, effective_sports: set[str]) -> str:
    """Strip any `<!-- library-index:sport-scope=X:... -->`-delimited span
    from `text` whose scope `X` isn't in `effective_sports`; a span whose
    scope IS covered has its content kept but the marker comments removed
    (so they never leak into the model's own context as visible text)."""

    def _replace(match: re.Match[str]) -> str:
        return match.group("body") if match.group("scope") in effective_sports else ""

    return _INDEX_SCOPE_BLOCK_RE.sub(_replace, text)


def _cache_control(ttl: str) -> dict[str, str]:
    """`{"type": "ephemeral"}` (5-minute, the default -- byte-identical to before) or the 1-hour form."""
    return {"type": "ephemeral"} if ttl == "5m" else {"type": "ephemeral", "ttl": ttl}


def build_system_blocks(
    library_dir: Path, *, athlete_sports: list[str] | None = None, cache_ttl: str = "5m"
) -> list[dict[str, Any]]:
    """System block A: persona + rules + 00-conventions.md + INDEX.md, as a
    single cacheable text block.

    `library/reference_list.md` (~58k tokens) does NOT live here (IDEA 025
    step 1, reversing the earlier IDEA 022 decision that put it in this
    block): it was paid on every cold cache start regardless of whether the
    turn cited anything, for a bibliography most turns never reference in
    full. It's no longer loaded whole anywhere -- `build_routed_library_text`
    attaches only the entries the ROUTED topic files actually cite (reusing
    `engine.swim_coach.library_review`'s citation-resolution machinery), and
    the `lookup_reference` tool (app.tools) covers anything not cited by
    those files. See PERSONA_AND_RULES rule 1 for the model-facing framing.

    `athlete_sports` (optional, defaults to `None`, same "undeclared
    resolves to swim-only" convention `filter_files_by_sport_scope` uses --
    see that function's docstring for the Finding-1 bug this fixes):
    INDEX.md's own sport-scoped spans (see `_filter_scoped_index_sections`
    above) are stripped out unless the athlete's effective sports cover
    that scope. This means block A is no longer byte-identical across
    EVERY athlete regardless of sport scope the way it originally was --
    it's now byte-identical across every request for a given athlete's
    fixed sport scope (still a small, stable set of distinct cache
    prefixes -- "swim-only" and "includes bike" today -- rather than one
    global constant), which is the trade this makes to guarantee cycling
    content never reaches a swim-only athlete's system prompt at all, not
    just block B's routed topic files. Never varies with the message
    itself -- only with the athlete's own declared sport scope."""
    effective_sports = set(athlete_sports) if athlete_sports is not None else set(_DEFAULT_SWIM_ONLY_SPORTS)
    conventions = _read_text(library_dir / "00-conventions.md")
    index = _filter_scoped_index_sections(_read_text(library_dir / "INDEX.md"), effective_sports)
    text = (
        f"{PERSONA_AND_RULES}\n\n"
        f"---\n\n# library/00-conventions.md\n\n{conventions}\n\n"
        f"---\n\n# library/INDEX.md\n\n{index}"
    )
    return [
        {
            "type": "text",
            "text": text,
            "cache_control": _cache_control(cache_ttl),
        }
    ]


# --- system block B: routed library topic files -----------------------------

# Mirrors library/INDEX.md's "Topic -> file routing table" as fixed keyword
# buckets rather than parsing the table at request time -- deterministic,
# fast, and the buckets are exactly what INDEX.md documents. If INDEX.md's
# routing table changes, update this dict in the same change (same
# discipline library/00-conventions.md asks of engine-constant citations).
_LIBRARY_FILES_IN_PRIORITY_ORDER = [
    "03-periodization.md",
    "04-css-intensity-anchors.md",
    "07-strength-dryland.md",
    "34-kettlebell-strength-programming.md",
    "14-swim-set-structure.md",
    "05-open-water-pace-inference.md",
    "06-long-swim-progression.md",
    "08-ultra-feeding.md",
    "13-reds-energy-availability.md",
    "33-daily-nutrition-and-supplements.md",
    "35-return-from-layoff.md",
    "36-plan-authoring-limits.md",
    "37-plan-authoring-guide.md",
]

# 37 always pulls 36 in alongside it (engine/red-team-taper-gate, real
# production failure 2026-09-27): only 37 was routed on that turn (keywords
# "macro"/"season") -- 36, the evidence dossier BEHIND `check_macro`'s own
# constants (ramp caps, the taper cut-fraction band, the goal-reality
# check), never routed at all, so the coach had no grounding to challenge
# its own red-team finding honestly instead of arguing it away on
# intuition. 36 has no keyword bucket of its own (deliberately -- it's a
# companion to 37, not an independent topic a message would naturally
# mention by name) -- this is a dedicated, minimal exception to
# `MAX_ROUTED_FILES`, not a change to the cap itself: 36 rides along ONLY
# when 37 actually routed, adding at most one extra file.
_PLANNING_GUIDE_FILE = "37-plan-authoring-guide.md"
_PLANNING_LIMITS_FILE = "36-plan-authoring-limits.md"

_KEYWORD_ROUTES: dict[str, set[str]] = {
    "volume": {"03-periodization.md", "06-long-swim-progression.md"},
    "cut": {"03-periodization.md"},
    "repeat": {"03-periodization.md"},
    "advance": {"03-periodization.md"},
    "periodization": {"03-periodization.md"},
    "monoton": {"03-periodization.md"},
    "acwr": {"03-periodization.md"},
    "load": {"03-periodization.md"},
    "compliance": {"03-periodization.md"},
    "consisten": {"03-periodization.md"},
    "taper": {"03-periodization.md", "37-plan-authoring-guide.md"},
    "pace": {"04-css-intensity-anchors.md"},
    "zone": {"04-css-intensity-anchors.md"},
    "css": {"04-css-intensity-anchors.md"},
    "critical swim speed": {"04-css-intensity-anchors.md"},
    "negative split": {"04-css-intensity-anchors.md"},
    "dryland": {"04-css-intensity-anchors.md", "07-strength-dryland.md"},
    "strength": {"04-css-intensity-anchors.md", "07-strength-dryland.md"},
    # 07-strength-dryland.md -- exercise selection/dosing detail beyond the
    # frequency constant 04 grounds.
    "exercise": {"07-strength-dryland.md"},
    "kettlebell": {"07-strength-dryland.md"},
    "rotator cuff": {"07-strength-dryland.md"},
    "scapular": {"07-strength-dryland.md"},
    # 14-swim-set-structure.md -- warm-up/main-set/cool-down composition for
    # the additional pool-independent swim session (not the long swim).
    "main set": {"14-swim-set-structure.md"},
    "warm-up": {"14-swim-set-structure.md"},
    "warm up": {"14-swim-set-structure.md"},
    "cool-down": {"14-swim-set-structure.md"},
    "cool down": {"14-swim-set-structure.md"},
    "interval": {"14-swim-set-structure.md"},
    "broken distance": {"14-swim-set-structure.md"},
    "descending set": {"14-swim-set-structure.md"},
    "set structure": {"14-swim-set-structure.md"},
    "wetsuit": {"05-open-water-pace-inference.md"},
    "open water": {"05-open-water-pace-inference.md"},
    "open-water": {"05-open-water-pace-inference.md"},
    "chop": {"05-open-water-pace-inference.md"},
    "cold": {"05-open-water-pace-inference.md"},
    "current": {"05-open-water-pace-inference.md"},
    "tide": {"05-open-water-pace-inference.md"},
    "milestone": {"06-long-swim-progression.md"},
    "long swim": {"06-long-swim-progression.md"},
    "long-swim": {"06-long-swim-progression.md"},
    "stage": {"06-long-swim-progression.md"},
    "single-day": {"06-long-swim-progression.md"},
    "single day": {"06-long-swim-progression.md"},
    "recovery": {"06-long-swim-progression.md", "03-periodization.md"},
    # 08-ultra-feeding.md -- acute in-session fuelling, hydration, EAH safety.
    "fuel": {"08-ultra-feeding.md"},
    "feeding": {"08-ultra-feeding.md"},
    "feed": {"08-ultra-feeding.md"},
    "carb": {"08-ultra-feeding.md"},
    "glycogen": {"08-ultra-feeding.md"},
    "hydration": {"08-ultra-feeding.md"},
    "hydrate": {"08-ultra-feeding.md"},
    "sodium": {"08-ultra-feeding.md"},
    "electrolyte": {"08-ultra-feeding.md"},
    "hyponatremia": {"08-ultra-feeding.md"},
    "cramp": {"08-ultra-feeding.md"},
    "wall": {"08-ultra-feeding.md"},
    "bonk": {"08-ultra-feeding.md"},
    "gel": {"08-ultra-feeding.md"},
    # 13-reds-energy-availability.md -- chronic energy availability / RED-S.
    "energy availability": {"13-reds-energy-availability.md"},
    "red-s": {"13-reds-energy-availability.md"},
    "reds": {"13-reds-energy-availability.md"},
    "relative energy deficiency": {"13-reds-energy-availability.md"},
    "bone density": {"13-reds-energy-availability.md"},
    "bone health": {"13-reds-energy-availability.md"},
    "under-fuel": {"13-reds-energy-availability.md"},
    "underfuel": {"13-reds-energy-availability.md"},
    "under-eating": {"13-reds-energy-availability.md"},
    "appetite": {"13-reds-energy-availability.md"},
    "amenorrhea": {"13-reds-energy-availability.md"},
    "menstrual": {"13-reds-energy-availability.md"},
    # 33-daily-nutrition-and-supplements.md -- creatine/supplements/protein/
    # daily carbs/cramping. General/all-athlete content, not sport-scoped.
    "creatine": {"33-daily-nutrition-and-supplements.md"},
    "supplement": {"33-daily-nutrition-and-supplements.md"},
    "protein": {"33-daily-nutrition-and-supplements.md"},
    "daily carb": {"33-daily-nutrition-and-supplements.md"},
    "carb periodization": {"33-daily-nutrition-and-supplements.md"},
    "caffeine": {"33-daily-nutrition-and-supplements.md"},
    "vitamin d": {"33-daily-nutrition-and-supplements.md"},
    "iron": {"33-daily-nutrition-and-supplements.md"},
    # 34-kettlebell-strength-programming.md -- kettlebell/exercise-selection/
    # sets-reps beyond 07's frequency constant. Cross-routes 07 too.
    "kettlebell": {"34-kettlebell-strength-programming.md", "07-strength-dryland.md"},
    "sets and reps": {"34-kettlebell-strength-programming.md"},
    "sets/reps": {"34-kettlebell-strength-programming.md"},
    "turkish get-up": {"34-kettlebell-strength-programming.md"},
    # 35-return-from-layoff.md -- layoff/detraining/coming back after time off.
    "layoff": {"35-return-from-layoff.md"},
    "detraining": {"35-return-from-layoff.md"},
    "coming back": {"35-return-from-layoff.md"},
    "time off": {"35-return-from-layoff.md"},
    "months off": {"35-return-from-layoff.md"},
    "muscle memory": {"35-return-from-layoff.md"},
    # 37-plan-authoring-guide.md -- routed ONLY on plan-authoring turns
    # (engine/plan-check-red-team PR 3, 2026-09-27): the coach uses
    # author_macro_plan/author_week_plan/check_plan, and this file is the
    # compact, ported operating guide for those tools. Never in the
    # always-on system-block-A prefix (see this module's own docstring) --
    # a planning question routes here via keyword bucket like any other
    # topic file. "taper" above also routes here (in addition to 03) since
    # taper placement/length is now a coach-authored planning decision,
    # not just a load-monitoring question. Deliberately NOT a bare "plan"
    # keyword -- too generic a substring (matches ordinary phrasing like
    # "why was my plan repeated, not advanced?", which must stay routed to
    # 03-periodization.md alone for cache-sharing -- see
    # test_system_prefix_is_byte_stable_across_two_different_messages).
    # "build my plan" below is deliberately multi-word so it stays
    # specific to an actual planning request.
    "macro": {"37-plan-authoring-guide.md"},
    "macrocycle": {"37-plan-authoring-guide.md"},
    "mesocycle": {"37-plan-authoring-guide.md"},
    "block": {"37-plan-authoring-guide.md"},
    "season": {"37-plan-authoring-guide.md"},
    "build my plan": {"37-plan-authoring-guide.md"},
    "next weeks": {"37-plan-authoring-guide.md"},
    "race debrief": {"37-plan-authoring-guide.md"},
    "adapt": {"37-plan-authoring-guide.md"},
}

# Deterministic fallback bucket when no keyword matches -- "why is the plan
# what it is" is the single most common ungrounded question shape, so this
# maximizes cache-hit odds for whatever doesn't match a specific keyword.
DEFAULT_ROUTE_FILES = ["03-periodization.md", "06-long-swim-progression.md"]

MAX_ROUTED_FILES = 3

# --- 23-cycling-training.md: cycling-specific routing (IDEA 008) -----------
# Mirrors INDEX.md's "Power zones, FTP..." / "Cycling TSS..." / "Cycling
# CTL/ATL/TSB..." / "Cycling periodization..." / "Cyclist's knee..." /
# "Does road/MTB/cyclocross..." routing rows as fixed keyword buckets, same
# "mirror INDEX.md as Python data, don't parse prose at request time"
# convention _KEYWORD_ROUTES already uses -- update both in the same change
# if INDEX.md's cycling rows change. Reachability alone does NOT bypass the
# sport-scope filtering below: these keywords route to
# `23-cycling-training.md` for ANY message that matches them, but
# `filter_files_by_sport_scope` still excludes it whenever the requesting
# athlete's own `Athlete.sports` is set and doesn't include "bike" -- see
# that function's docstring for the "IDEA 008 hard requirement" this
# structurally enforces (previously documentation-only, per the adversarial
# critique's objection 3).
_CYCLING_KEYWORD_ROUTES: dict[str, set[str]] = {
    "ftp": {"23-cycling-training.md"},
    "%ftp": {"23-cycling-training.md"},
    "power zone": {"23-cycling-training.md"},
    "normalized power": {"23-cycling-training.md"},
    "cycling tss": {"23-cycling-training.md"},
    "intensity factor": {"23-cycling-training.md"},
    "saddle height": {"23-cycling-training.md"},
    "patellofemoral": {"23-cycling-training.md"},
    "mountain bike": {"23-cycling-training.md"},
    "cyclocross": {"23-cycling-training.md"},
    "road bike": {"23-cycling-training.md"},
    "road cycling": {"23-cycling-training.md"},
}
_KEYWORD_ROUTES.update(_CYCLING_KEYWORD_ROUTES)
_LIBRARY_FILES_IN_PRIORITY_ORDER.append("23-cycling-training.md")

# --- 30-altitude-power-adjustment.md: elevation/altitude routing -----------
# Real gap fixed here (2026-09-14 feedback, logged after Andrew reviewed the
# Aug 26/27 Sun Valley Gravel ride): the file existed (PR #187) but had no
# keyword route at all -- not in _LIBRARY_FILES_IN_PRIORITY_ORDER, no
# "elevation"/"altitude"/"climb" entry in _KEYWORD_ROUTES -- so a general
# "at what elevation would adjustments matter" question had nothing to
# route to; the coach could only see a per-workout altitude_context string
# once a ride had already been analyzed. Mirrors _CYCLING_KEYWORD_ROUTES's
# own pattern exactly, including the same bike-only sport scope.
_ALTITUDE_KEYWORD_ROUTES: dict[str, set[str]] = {
    "altitude": {"30-altitude-power-adjustment.md"},
    "elevation": {"30-altitude-power-adjustment.md"},
    "climb": {"30-altitude-power-adjustment.md"},
    "climbing": {"30-altitude-power-adjustment.md"},
    "high elevation": {"30-altitude-power-adjustment.md"},
    "sea level": {"30-altitude-power-adjustment.md"},
    "home elevation": {"30-altitude-power-adjustment.md"},
}
_KEYWORD_ROUTES.update(_ALTITUDE_KEYWORD_ROUTES)
_LIBRARY_FILES_IN_PRIORITY_ORDER.append("30-altitude-power-adjustment.md")

# --- sport-scope filtering (Athlete.sports <-> library file sport scope) ---
# IDEA 008's hard requirement, made structural (adversarial critique
# objection 3: INDEX.md's own prose note alone had no code/test/model-field
# backing before this build). Mirrors INDEX.md's per-file "Sport scope"
# note as fixed Python data -- same convention `_KEYWORD_ROUTES` above
# already uses for the routing table itself. A file with NO entry here is
# UNSCOPED and is never filtered out, regardless of `athlete_sports` --
# every existing swim library file stays unscoped.
#
# web/resources-tab-library-review build (2026-09): every one of
# `23-cycling-training.md` through `32-gps-lap-detection.md` self-declares
# "**Sport scope: `bike`**" in its own header (grepped, not guessed) even
# though several of them (`24`/`25`/`26`/`27`/`28`/`29`/`31`/`32`) honestly
# document themselves as "not yet wired into context.py's routing" for chat
# keyword-bucket purposes -- that caveat is about `_KEYWORD_ROUTES` never
# reaching them via a message-topic match, not about whether they're safe to
# surface. The Resources tab's library-card view (`/api/library/cards`)
# reuses THIS dict directly to decide what an athlete may see regardless of
# chat routing, so every self-declared bike-scoped file must be listed here
# even ones chat can't reach yet -- a swim-only athlete must never see a
# card for any of them, not just the two chat already routes to.
_LIBRARY_FILE_SPORT_SCOPE: dict[str, frozenset[str]] = {
    "23-cycling-training.md": frozenset({"bike"}),
    "24-cycling-periodization-intervals.md": frozenset({"bike"}),
    "25-macro-sharpening-established-base.md": frozenset({"bike"}),
    "26-activity-stream-interval-analysis.md": frozenset({"bike"}),
    "27-cyclocross-skills.md": frozenset({"bike"}),
    "28-bike-ftp-test-protocols.md": frozenset({"bike"}),
    "29-ftp-threshold-change-modeling.md": frozenset({"bike"}),
    "30-altitude-power-adjustment.md": frozenset({"bike"}),
    "31-multi-race-season-periodization.md": frozenset({"bike"}),
    "32-gps-lap-detection.md": frozenset({"bike"}),
}


# The swim-only default used to resolve an athlete's sport scope whenever
# the caller doesn't already have a concrete list -- mirrors
# `Athlete.effective_sports` (models.py) exactly. Kept as its own constant
# here (rather than importing the model) so this module's filtering has a
# well-defined default even for a caller that only has a raw
# `list[str] | None` in hand (e.g. a test calling `route_library_files`
# directly with `athlete_sports=None`, the reviewer's own repro for Finding
# 1) and never depends on every call site remembering to resolve
# `effective_sports` itself first.
_DEFAULT_SWIM_ONLY_SPORTS: list[str] = ["swim_pool", "swim_ow"]


def filter_files_by_sport_scope(
    filenames: list[str], athlete_sports: list[str] | None
) -> list[str]:
    """Drop any routed file whose declared sport scope doesn't intersect the
    athlete's EFFECTIVE sport scope -- the structural half of IDEA 008's
    "never surface cycling content to a swim-only athlete" constraint.

    **Real review bug fixed here (PR #167 review, Finding 1):** this used
    to treat `athlete_sports is None` as "apply NO filtering at all" (every
    file passes through unfiltered, cycling content included). Since every
    real athlete today has `Athlete.sports = None` (setting it on real
    athlete data was explicitly deferred), that meant the sport-scope
    guarantee was false for 100% of real athletes -- verified live:
    `route_library_files("Should I ride my road bike on recovery days?",
    athlete_sports=None)` returned `23-cycling-training.md` in the result.
    `None` now resolves to `_DEFAULT_SWIM_ONLY_SPORTS` (swim-only) --
    matching `Athlete.effective_sports`'s own resolution -- so an
    undeclared athlete is filtered as a swim-only athlete, never as "every
    sport." An athlete who explicitly declares `sports=["bike"]` (or any
    other real list) is filtered against exactly that list, unaffected by
    this default.

    A file with no entry in `_LIBRARY_FILE_SPORT_SCOPE` is unscoped and is
    NEVER filtered out, regardless of `athlete_sports` -- only a file that
    HAS declared a scope can be excluded, and only when that declared scope
    shares nothing with the athlete's own (effective) sports. This is
    symmetric by construction (not cycling-specific): a hypothetical future
    swim-scoped file would be excluded from a bike-only athlete's routing
    the same way.
    """
    effective_sports = athlete_sports if athlete_sports is not None else _DEFAULT_SWIM_ONLY_SPORTS
    athlete_sport_set = set(effective_sports)
    return [
        f
        for f in filenames
        if f not in _LIBRARY_FILE_SPORT_SCOPE or _LIBRARY_FILE_SPORT_SCOPE[f] & athlete_sport_set
    ]


def route_library_files(
    message: str,
    *,
    max_files: int = MAX_ROUTED_FILES,
    athlete_sports: list[str] | None = None,
) -> list[str]:
    """Deterministically route `message` to up to `max_files` topic files.
    (`reference_list.md` is no longer loaded whole anywhere -- see
    `build_routed_library_text` for the per-citation entries attached
    alongside these files, and the `lookup_reference` tool for anything not
    cited by them.)

    Order is fixed by `_LIBRARY_FILES_IN_PRIORITY_ORDER`, not by keyword
    match order, so any two messages that hit the same bucket (for the same
    `athlete_sports`) produce the same file list in the same order --
    required for the resulting text block to be byte-identical (and thus
    cache-shareable) across requests that share both.

    `athlete_sports` (optional, defaults to `None` -- every existing call
    site keeps producing byte-identical output unless updated to pass it):
    forwarded to `filter_files_by_sport_scope` AFTER keyword matching, so a
    sport-scoped file (today, only `23-cycling-training.md`) never reaches
    an athlete whose own declared sports don't include it, even if its
    keywords matched. `None` (today's every real athlete) applies no
    filtering at all -- see that function's own docstring.
    """
    lower = message.lower()
    matched: set[str] = set()
    for keyword, files in _KEYWORD_ROUTES.items():
        if keyword in lower:
            matched |= files
    if not matched:
        matched = set(DEFAULT_ROUTE_FILES)
    ordered = [f for f in _LIBRARY_FILES_IN_PRIORITY_ORDER if f in matched]
    ordered = filter_files_by_sport_scope(ordered, athlete_sports)
    if not ordered:
        # Real review bug fixed here (PR #167 review, Finding 8): the
        # DEFAULT_ROUTE_FILES fallback above only fires when NO keyword
        # matched at all -- it ran BEFORE sport-scope filtering, so
        # filtering could empty an already-non-empty matched set (e.g. a
        # question that matches ONLY a sport-scoped file this athlete's
        # scope excludes) with no fallback left to catch it. Verified live:
        # `route_library_files("my mountain bike ride left my knee sore",
        # athlete_sports=["swim_ow"])` returned `[]` -- the resulting
        # context had NO topic grounding at all, not even a graceful
        # default, exactly the failure mode DEFAULT_ROUTE_FILES exists to
        # prevent. Re-apply it here, AFTER filtering, so a routed block is
        # NEVER empty for a sport-scoped athlete -- filtered again for
        # consistency (DEFAULT_ROUTE_FILES is unscoped today, so this is a
        # no-op in practice, but stays generic/defensive rather than
        # assuming that forever).
        fallback = [f for f in _LIBRARY_FILES_IN_PRIORITY_ORDER if f in set(DEFAULT_ROUTE_FILES)]
        ordered = filter_files_by_sport_scope(fallback, athlete_sports)
    result = ordered[:max_files]
    if _PLANNING_GUIDE_FILE in result and _PLANNING_LIMITS_FILE not in result:
        # The minimal MAX_ROUTED_FILES exception described above -- 36
        # rides along with 37, past the cap, only when 37 itself routed.
        # Re-sorted back into `_LIBRARY_FILES_IN_PRIORITY_ORDER`'s own
        # order (36 before 37) rather than just appended, so the routed
        # block's file order stays canonical/byte-stable regardless of
        # which path added 36.
        result = sorted(result + [_PLANNING_LIMITS_FILE], key=_LIBRARY_FILES_IN_PRIORITY_ORDER.index)
    return result


def _routed_topic_files_text(
    library_dir: Path, message: str, *, athlete_sports: list[str] | None = None
) -> str:
    """Just the concatenated routed topic files' own text -- no
    `reference_list.md` entries, no header. The shared base both
    `build_routed_block` (system block B) and `build_routed_library_text`
    (the message, `COACH_ROUTED_LIBRARY_IN_MESSAGE`) attach cited entries
    onto via `_cited_reference_bullets`."""
    filenames = route_library_files(message, athlete_sports=athlete_sports)
    parts = []
    for filename in filenames:
        content = _read_text(library_dir / filename)
        parts.append(f"# library/{filename}\n\n{content}")
    return "\n\n---\n\n".join(parts)


def build_routed_block(
    library_dir: Path, message: str, *, athlete_sports: list[str] | None = None
) -> list[dict[str, Any]]:
    """System block B: the routed topic files for `message`, plus the
    verbatim `reference_list.md` entries those files actually cite (IDEA 025
    step 1), as a single cacheable text block.

    **This is the production default**: `COACH_ROUTED_LIBRARY_IN_MESSAGE` is
    unset in Cloud Run, so the routed text rides HERE, not the message (see
    `build_routed_library_text`) -- citations have to attach on this path or
    the coach loses them entirely and hammers `lookup_reference` for
    anything it would normally just cite. Real bug caught before this PR
    merged: an earlier version of this build only attached entries in
    `build_routed_library_text`, which production never calls.

    `athlete_sports` (optional, defaults to `None`, forwarded straight to
    `route_library_files` -- see that function's docstring) is the only
    thing that can make this block depend on the requesting athlete rather
    than the message alone; every existing call site (no kwarg passed)
    keeps producing byte-identical output.
    """
    body = _routed_topic_files_text(library_dir, message, athlete_sports=athlete_sports)
    bullets = _cited_reference_bullets(library_dir, body)
    text = body
    if bullets:
        text += (
            "\n\n---\n\n## library/reference_list.md entries cited by the files above\n\n"
            + "\n".join(bullets)
        )
    return [
        {
            "type": "text",
            "text": text,
            "cache_control": {"type": "ephemeral"},
        }
    ]


# --- reference_list.md: on-demand citation attachment (IDEA 025 step 1) ----
#
# `library/reference_list.md` used to ride whole in system block A (~58k
# tokens, paid on every cold cache start regardless of whether the turn
# cited anything). It's now attached PER-REQUEST, and only the entries the
# routed topic files actually cite -- reusing
# `engine.swim_coach.library_review`'s citation-resolution machinery
# (`parse_reference_list`/`resolve_citations`/`candidate_surnames`) rather
# than writing a second parser for the same bullet format. Anything not
# cited by the routed files is reachable via the `lookup_reference` tool
# (app.tools) instead of being loaded speculatively.

# A reference_list.md bullet's own text (REF_ENTRY_RE only captures the bold
# citation key, e.g. "✓ Chilibeck P.D. et al. (2017)") runs from its "- **"
# start to the next bullet or the next heading of any level -- `##`, `###`,
# etc. (reference_list.md nests entries under `###` topic subheadings inside
# each `##` section).
_REFERENCE_HEADING_RE = re.compile(r"^#{2,6}[ \t]", re.MULTILINE)

# Parsed (entries, {entry.key: verbatim bullet text}) per library_dir,
# cached for the life of the process -- reference_list.md is static in the
# deployed image, so re-parsing it on every chat turn would waste exactly
# the latency (if not the tokens) this build exists to save.
_PARSED_REFERENCE_LIST_CACHE: dict[Path, tuple[list[RefEntry], dict[str, str]]] = {}


def _parsed_reference_list(library_dir: Path) -> tuple[list[RefEntry], dict[str, str]]:
    """`(entries, bullet_text_by_key)` for `library_dir/reference_list.md`,
    parsed once per process. `entries` is `parse_reference_list`'s own
    return value (each entry's `key` is its bold citation text, whitespace-
    normalized); `bullet_text_by_key` maps that same `key` to the entry's
    FULL verbatim bullet (including the description after the bold key),
    which `REF_ENTRY_RE` alone doesn't capture."""
    path = library_dir / "reference_list.md"
    cached = _PARSED_REFERENCE_LIST_CACHE.get(path)
    if cached is not None:
        return cached
    text = _read_text(path)
    entries = parse_reference_list(text)
    bullet_starts = [m.start() for m in REF_ENTRY_RE.finditer(text)]
    boundaries = sorted(set(bullet_starts) | {m.start() for m in _REFERENCE_HEADING_RE.finditer(text)})
    bullet_text_by_key: dict[str, str] = {}
    for entry, start in zip(entries, bullet_starts):
        later = [b for b in boundaries if b > start]
        end = later[0] if later else len(text)
        bullet_text_by_key[entry.key] = text[start:end].strip()
    result = (entries, bullet_text_by_key)
    _PARSED_REFERENCE_LIST_CACHE[path] = result
    return result


def _cited_reference_bullets(library_dir: Path, routed_text: str) -> list[str]:
    """Verbatim `reference_list.md` bullets cited (author-year, e.g.
    `` `Chilibeck et al. (2017)` ``) within `routed_text` -- typically the
    concatenated body of the routed topic files for one message. Order
    follows `reference_list.md`'s own entry order (`resolve_citations`'
    contract), not first-cited-in-text order."""
    entries, bullet_text_by_key = _parsed_reference_list(library_dir)
    sources, _unresolved = resolve_citations(routed_text, entries)
    return [bullet_text_by_key[s.key] for s in sources if s.key in bullet_text_by_key]


def _matched_routing_keywords(message: str) -> list[str]:
    """Which `_KEYWORD_ROUTES` keys matched `message` -- routing observability
    only (IDEA 025 step 1's "library route" log), never used to decide
    routing itself (that stays `route_library_files`'s own logic)."""
    lower = message.lower()
    return sorted(keyword for keyword in _KEYWORD_ROUTES if keyword in lower)


def build_routed_library_text(
    library_dir: Path, message: str, *, athlete_sports: list[str] | None = None
) -> str:
    """The routed topic files for `message` as plain text for the newest user
    message (IDEA 022 step 4) -- exactly what `build_routed_block` would put
    in system block B (topic files + their cited `reference_list.md`
    entries, IDEA 025 step 1), under a header saying what they are. Anything
    the routed files don't cite is reachable via the `lookup_reference` tool
    instead."""
    body = build_routed_block(library_dir, message, athlete_sports=athlete_sports)[0]["text"]
    return (
        "## Library topic files for this question "
        "(reference material -- ground and cite from these, same rules as the system prompt)\n\n"
        + body
    )


class LibraryRouteInfo(TypedDict):
    routed_files: list[str]
    matched_keywords: list[str]
    n_ref_entries_attached: int
    ref_chars: int


def route_info_for_logging(
    library_dir: Path, message: str, *, athlete_sports: list[str] | None = None
) -> LibraryRouteInfo:
    """Routing + citation-attachment metadata for the "library route" log
    line (IDEA 025 step 1) -- computed independently of whether the routed
    text actually rides the message (`build_routed_library_text`) or the
    cached system block B (`build_routed_block`), so a caller can log this
    exactly once per chat request either way."""
    routed_files = route_library_files(message, athlete_sports=athlete_sports)
    matched_keywords = _matched_routing_keywords(message)
    # The topic files' OWN text, not build_routed_block's return value --
    # that already has cited entries appended, and re-scanning THOSE for
    # citations would double-count/spuriously match against bullet prose.
    body = _routed_topic_files_text(library_dir, message, athlete_sports=athlete_sports)
    bullets = _cited_reference_bullets(library_dir, body)
    return {
        "routed_files": routed_files,
        "matched_keywords": matched_keywords,
        "n_ref_entries_attached": len(bullets),
        "ref_chars": sum(len(b) for b in bullets),
    }


def build_system(
    library_dir: Path,
    message: str,
    *,
    athlete_sports: list[str] | None = None,
    include_routed: bool = True,
    cache_ttl: str = "5m",
    context_block: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """The full `system` param: block A, then block C (`context_block`, when given), then
    block B -- each its own cache breakpoint (stable-first, per Anthropic's prompt-caching
    rules -- a cache_control block also implicitly caches everything before it, in request
    order: tools, then each system block in the order given here, then messages).

    **Order (context-trim build, Phase 2): A -> C -> B, never C after B.** A breakpoint caches
    the request's exact byte PREFIX up to and including that block. Block B (the routed library
    topic files) changes with the message's topic, so if C sat after B, C's own prefix would
    include B's volatile bytes and a topic change would evict C's cache read right along with
    B's -- exactly the coupling `build_context_block` exists to avoid (see its own docstring).
    Putting C directly after A means C's cache entry depends only on (tools + A + C), so a
    topic-driven change to B never touches it: a request can still hit C's cache even when B
    itself has to be rewritten. This is a pure request-shape ordering fact, not the general
    "later stuff can't affect earlier stuff" claim -- verified directly by
    `test_context_block_cache_key_is_unaffected_by_which_topic_file_follows_it` alongside this
    build's other cache-shape tests.

    `athlete_sports` (optional, defaults to `None`) is forwarded to BOTH
    `build_system_blocks` (block A's INDEX.md sport-scoped sections -- PR
    #167 review, Finding 1) and `build_routed_block` (block B's routed
    topic files) -- see each function's own docstring.

    `context_block` (optional, defaults to `None` -- every existing call site that doesn't pass
    it keeps producing byte-identical output): block C, built by `build_context_block`. Omitted
    entirely (not an empty placeholder) when `None`, so a caller with nothing athlete-specific
    to show (there is none today, but nothing here assumes that) still gets a valid, breakpoint-
    budget-respecting system array.

    `include_routed=False` returns block A (+ block C, if given) without block B -- the caller
    then puts the routed files on the newest message via `build_routed_library_text`.
    """
    # `cache_ttl` applies to block A only: a longer-TTL entry must come BEFORE shorter ones.
    # Block C carries its OWN ttl (`build_context_block`'s own `cache_ttl` argument, from
    # `PROMPT_CACHE_TTL_CONTEXT`) baked into the block it's handed here -- athlete data changes
    # far more often than the library/persona, so its default TTL is independent of block A's.
    # Block B (changes with the topic) stays on the default 5 minutes either way.
    blocks = build_system_blocks(library_dir, athlete_sports=athlete_sports, cache_ttl=cache_ttl)
    if context_block:
        blocks = blocks + context_block
    if include_routed:
        blocks = blocks + build_routed_block(library_dir, message, athlete_sports=athlete_sports)
    return blocks


# --- engine reuse: summarize rollup -----------------------------------------


def iso_week_str(d: date) -> str:
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def _rollup_window(as_of: date, weeks: int) -> tuple[date, date, list[date]]:
    """The Monday-to-Sunday span covering the trailing `weeks` ISO weeks
    (inclusive of the current, in-progress week). Shared by `summarize_rollup`
    and `build_per_request_context` so the "exact logged sessions" list and
    the aggregate rollup derived from it always cover the identical window --
    a session that appears in one always counts in the other."""
    as_of_monday = as_of - timedelta(days=as_of.weekday())
    week_starts = [as_of_monday - timedelta(weeks=i) for i in range(weeks - 1, -1, -1)]
    span_start = week_starts[0]
    span_end = as_of_monday + timedelta(days=6)
    return span_start, span_end, week_starts


def summarize_rollup(
    store: StoreInterface,
    slug: str,
    *,
    weeks: int = 4,
    as_of: date | None = None,
    workouts: list[Workout] | None = None,
    athlete: Athlete | None = None,
) -> dict[str, Any]:
    """The compact training-load/wellness/compliance rollup, computed with
    the exact same `swim_coach.load` functions `cli.py`'s `summarize`
    command uses (see `_cmd_summarize` in `swim_coach/cli.py`) -- this is
    "reuse the engine" in the literal sense: the math lives in `load.py`,
    this function only assembles the same window/rollup shape around it, it
    never recomputes a formula. Used both for the per-request chat context
    and for the `get_plan_summary` tool.

    `athlete`, same "let an already-fetched caller skip a second round
    trip" convention as `workouts` above -- defaults to fetching it here
    when omitted. Forwarded into `load.daily_loads`/`acute_chronic_ratio`
    so their HR-TRIMP/swim-pace-IF fallback tiers can use this athlete's
    `sex`/`css_pace_s_per_100m` for RPE-less workouts.

    `workouts` lets a caller that already fetched the athlete's workouts
    (e.g. `build_per_request_context`, which also renders them as exact
    sessions) pass them in rather than triggering a second `list_workouts`
    round trip; defaults to fetching them here when omitted.

    Includes `"ctl_atl_tsb"`: a `[date_iso, ctl, atl, tsb]` list (1-decimal
    rounded), the Banister CTL/ATL/TSB series from `load.ctl_atl_tsb_series`,
    windowed to `[span_start, span_end]` the same way `"wellness_trend"` is,
    but -- unlike every other field here -- computed from the FULL `loads`
    history rather than `window_loads`, so the exponential average has real
    warm-up context. This is read-only monitoring surfaced to the
    athlete-facing AI's judgment; it does not feed `plan.py`'s periodization
    or taper math.

    Also includes `"wellness_baseline_deviation"`: the
    `{"resting_hr_pct_deviation": ..., "hrv_pct_deviation": ...}` dict from
    `load.wellness_baseline_deviation`, computed from the FULL `wellness`
    history (same "full history, not window_wellness" reasoning as
    `ctl_atl_tsb` above -- its 28-day chronic window needs real history, not
    whatever's left after windowing to `weeks`). This is a corroborating
    cross-check for `ctl_atl_tsb`'s TSB (independent physiological signal
    vs. sRPE-derived load), reported as its own field per this project's
    "separate signals, not one master number" convention -- never blended
    into `ctl_atl_tsb`. See `load.py`'s `wellness_baseline_deviation`
    docstring for the full citation trail.
    """
    # `athlete` loaded BEFORE resolving `as_of`'s default (reordered from
    # this function's own original shape) so a caller that omits `as_of`
    # gets this athlete's own local "today" (`athlete_today`, honoring
    # `Athlete.timezone` when set) rather than server-UTC `date.today()` --
    # a caller that supplies `athlete` explicitly is unaffected either way,
    # since `athlete_today` only runs when `as_of is None`.
    athlete = store.load_athlete(slug) if athlete is None else athlete
    as_of = athlete_today(athlete) if as_of is None else as_of
    span_start, span_end, week_starts = _rollup_window(as_of, weeks)

    workouts = store.list_workouts(slug) if workouts is None else workouts
    wellness = store.list_wellness(slug)

    volume_by_week = {iso_week_str(ws): weekly_volume_m(workouts, ws) for ws in week_starts}

    # `athlete`/`wellness` unlock the HR-TRIMP (tier 2) and swim pace-IF
    # (tier 3) fallbacks for workouts with no logged RPE -- see
    # `load.daily_loads`'s docstring. This is the fix for the confirmed
    # bug where 62 of Renee's 63 real logged workouts (device telemetry,
    # no subjective RPE) were silently excluded from every load signal
    # built on `daily_loads` (CTL/ATL/TSB, ACWR, monotony below).
    loads = daily_loads(workouts, athlete=athlete, wellness=wellness)
    window_loads = {d: v for d, v in loads.items() if span_start <= d <= span_end}
    monotony_value = monotony(window_loads)
    load_ratio = acute_chronic_ratio(workouts, as_of, athlete=athlete, wellness=wellness)

    # CTL/ATL/TSB computed from the FULL `loads` history (not `window_loads`)
    # so the exponentially-weighted averages get proper warm-up from every
    # workout ever logged, not just this window's -- see `ctl_atl_tsb_series`'s
    # docstring on cold-start behavior. Only the window-relative slice is
    # reported here, same convention `wellness_trend`'s "trend" field below
    # already uses. Read-only/informational (see load.py's CTL/ATL module
    # docstring for the PROVISIONAL time-constant citation caveat) -- this
    # never feeds `plan.py`'s periodization or taper math.
    ctl_atl_tsb = [
        [d.isoformat(), round(ctl, 1), round(atl, 1), round(tsb, 1)]
        for d, ctl, atl, tsb in ctl_atl_tsb_series(loads)
        if span_start <= d <= span_end
    ]

    window_wellness = [w for w in wellness if span_start <= w.date <= span_end]
    trend = wellness_trend(window_wellness)

    # Full `wellness` history (not `window_wellness`) so the 28-day chronic
    # baseline has real data behind it -- same reasoning `ctl_atl_tsb`'s
    # comment above already gives for `loads` vs `window_loads`.
    baseline_deviation = wellness_baseline_deviation(wellness, as_of)

    planned_sessions = []
    for ws in week_starts:
        week_plan = store.load_week(slug, iso_week_str(ws))
        if week_plan is not None:
            planned_sessions.extend(week_plan.sessions)
    window_workouts = [w for w in workouts if span_start <= w.date <= span_end]
    compliance_pct = (
        compute_compliance(planned_sessions, window_workouts, athlete) if planned_sessions else None
    )

    return {
        "athlete": slug,
        "as_of": as_of.isoformat(),
        "weeks": weeks,
        "volume_m": volume_by_week,
        "srpe_load_by_day": {d.isoformat(): v for d, v in sorted(window_loads.items())},
        "load_ratio_7d_28d": load_ratio,
        "monotony": monotony_value,
        "wellness_trend": [[d.isoformat(), v] for d, v in trend],
        "compliance_pct": compliance_pct,
        "ctl_atl_tsb": ctl_atl_tsb,
        "wellness_baseline_deviation": {
            key: (round(value, 1) if value is not None else None)
            for key, value in baseline_deviation.items()
        },
    }


# --- per-request context -----------------------------------------------------


def _week_or_none(store: StoreInterface, slug: str, iso_week: str) -> dict[str, Any] | None:
    week = store.load_week(slug, iso_week)
    return week.model_dump(mode="json") if week is not None else None


# --- context-trim: slim week/session rendering (context-trim build) --------
# Full-fidelity `WeekPlan`/`Session` dumps used to go into the per-request
# context pretty-printed (`indent=2`) with every field, including the
# `structured` step tree (the per-step IR used for FIT/ZWO export and
# `render_prose`'s own input) -- ~10k of a single busy week's ~15k JSON,
# entirely duplicating the prose already in `structure`. Measured cost:
# this context is rebuilt and re-written to the prompt cache on EVERY
# message (see .claude/plans/context-trim-build.md), so every one of these
# bytes is paid for repeatedly, not once. The `get_week_plan` tool (see
# `app/tools.py`) returns the FULL session (structured included) for the
# rare turn that actually needs to inspect or build on top of existing
# step-level detail -- editing a session's steps, or explaining set
# structure at that level -- so nothing here is a real capability loss,
# only a per-turn cost one.
#
# Session fields DROPPED from context (each with its own reason -- never
# silently; `get_week_plan` recovers all of them):
#   - `structured`: the ~10k step tree itself (see above).
#   - `id` / `athlete_id`: internal identifiers. Every plan-editing tool
#     (`patch_week_plan`, `author_week_plan`, `merge_week_plan`,
#     `reschedule_session`, `propose_session_adjustment`) matches sessions
#     by `date` (+ `sport` to disambiguate a multi-session day), never by
#     `id` -- the model has never needed a session's `id` to act on it.
#   - `schema_version`: internal migration bookkeeping, never
#     coaching-relevant.
#   - `source` / `is_indoor`: authorship provenance and device-export
#     routing signals (does a bike session need the outdoor Garmin push or
#     the indoor .zwo export) -- neither carries coaching-judgment weight
#     turn to turn; recoverable via `get_week_plan` on the rare occasion
#     either actually matters to the conversation.
# Kept: `date`, `sport`, `purpose` (this Session model has no separate
# `title` field -- `purpose` already plays that role, e.g. "over/unders
# (Z3/Z4) -- fluctuating lactate production/clearance..."), `intensity`,
# `structure` (the athlete-facing prose), `duration_min`/`distance_m`
# (the volume fields), and `status`.
_SESSION_CONTEXT_FIELDS = (
    "date",
    "sport",
    "purpose",
    "intensity",
    "structure",
    "duration_min",
    "distance_m",
    "status",
)

# WeekPlan fields DROPPED from context: `id` / `athlete_id` / `schema_version`
# (same internal-bookkeeping reasons as the session fields above -- no tool
# matches a week by its `id`, every call takes `iso_week`) and `drafted_at` /
# `drafted_by` (HELD-draft bookkeeping for the confirm-flow mechanism itself,
# already surfaced separately via `render_pending_drafts`'s "Drafts waiting"
# block when a draft is actually pending -- rendering it again on every
# already-persisted week is dead weight). Kept: everything a coach needs to
# discuss or build on top of this week's plan -- `iso_week`, `meso_block`,
# `focus`, `target_volume_m`, `adaptation_rationale`, `draft`,
# `planning_warnings`, `race_week_checklist`.
_WEEK_CONTEXT_FIELDS = (
    "iso_week",
    "meso_block",
    "focus",
    "target_volume_m",
    "adaptation_rationale",
    "draft",
    "planning_warnings",
    "race_week_checklist",
)


def _slim_session_for_context(session: dict[str, Any]) -> dict[str, Any]:
    """One `Session.model_dump(mode="json")` dict, trimmed to
    `_SESSION_CONTEXT_FIELDS` -- see that constant's comment for what's
    dropped and why."""
    return {k: session[k] for k in _SESSION_CONTEXT_FIELDS if k in session}


def _slim_week_for_context(week: dict[str, Any] | None) -> dict[str, Any] | None:
    """One `WeekPlan.model_dump(mode="json")` dict, trimmed to
    `_WEEK_CONTEXT_FIELDS` with every session inside also slimmed via
    `_slim_session_for_context`. `None` in, `None` out (no week persisted
    for that ISO week yet)."""
    if week is None:
        return None
    slim = {k: week[k] for k in _WEEK_CONTEXT_FIELDS if k in week}
    slim["sessions"] = [_slim_session_for_context(s) for s in week.get("sessions", [])]
    return slim


def _render_recent_sessions(workouts: list[Workout], span_start: date, span_end: date) -> str:
    """Compact, chronological, one-row-per-workout rendering of every
    exactly-logged session in `[span_start, span_end]` -- each row keeps its
    own `sport`, which is exactly what the aggregate rollup below throws
    away. This is what lets the model tell a `swim_ow` session from a
    `swim_pool` one instead of guessing from volume alone."""
    window = sorted(
        (w for w in workouts if span_start <= w.date <= span_end), key=lambda w: w.date
    )
    if not window:
        return "(none logged in this window)"
    rows = [
        json.dumps(
            {
                "id": str(w.id),
                "date": w.date.isoformat(),
                "sport": w.sport,
                "distance_m": w.distance_m,
                "duration_min": w.duration_min,
                "rpe": w.rpe,
                "avg_pace_s_per_100m": w.avg_pace_s_per_100m,
            }
        )
        for w in window
    ]
    return "\n".join(rows)


def _compute_age(dob: date, today: date) -> int:
    """Whole years elapsed from `dob` to `today` -- the ordinary "birthday
    hasn't happened yet this year" adjustment."""
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def _render_demographics(athlete: Athlete, today: date) -> str | None:
    """A compact derived-facts line so the model reads age/sex/height/weight
    as ground truth instead of guessing (the production bug this build
    fixes). Age is computed from `dob` relative to `today` rather than
    stored, so it never goes stale. Returns None when nothing is on file so
    the caller can omit the line entirely rather than render an empty one."""
    facts: dict[str, Any] = {}
    if athlete.dob is not None:
        facts["age"] = _compute_age(athlete.dob, today)
    if athlete.sex is not None:
        facts["sex"] = athlete.sex
    if athlete.height_cm is not None:
        facts["height_cm"] = athlete.height_cm
    if athlete.weight_kg is not None:
        facts["weight_kg"] = athlete.weight_kg
    if not facts:
        return None
    return json.dumps(facts)


# Ordering severity for _active_health_statuses below -- higher sorts
# first when an athlete has more than one concurrently-unresolved entry.
# Not exported/reused elsewhere; purely a local rendering-priority choice.
_RESTRICTION_SEVERITY = {"no_training": 2, "light_only": 1, "none": 0}


def _active_health_statuses(statuses: list[HealthStatus]) -> list[HealthStatus]:
    """ALL current active statuses per HealthStatus's own docstring: every
    entry with `resolved=False`, most-severe-restriction first (ties broken
    by most-recent `reported_at`) -- NOT just the single most-recently-
    reported entry.

    **Real review bug fixed here before merge:** the original version of
    this helper returned only `max(unresolved, key=reported_at)` -- the
    single newest unresolved entry. Two concurrently-open, unrelated health
    statuses (e.g. an unresolved `no_training` shoulder issue reported week
    1, still open, and a `light_only` cold a coach relays week 4) would
    silently drop the OLDER, possibly more severe one from view the moment
    the newer one was logged -- nothing ever auto-resolves an entry, so
    both stay genuinely "active" simultaneously, and hiding either one
    behind the other is exactly the kind of silent-loss this whole feature
    exists to prevent. `resolved` must be set explicitly (by a human coach
    or the AI, per this model's own docstring) for an entry to stop being
    active -- logging a new, unrelated status must never implicitly retire
    an old one.
    """
    unresolved = [s for s in statuses if not s.resolved]
    return sorted(
        unresolved,
        key=lambda s: (_RESTRICTION_SEVERITY.get(s.restriction, 0), s.reported_at),
        reverse=True,
    )


def _render_active_health_status(statuses: list[HealthStatus]) -> str:
    """A prominent, hard-to-miss block for the model's per-request context:
    EVERY one of the athlete's current active (unresolved) health statuses,
    if any -- not just the newest, see `_active_health_statuses` above.
    Absence of any active entry is rendered as an EXPLICIT "nothing on
    file" -- never silence -- and is worded to avoid ever reading as an
    all-clear (see HealthStatus's own docstring: no record is not the same
    as "definitely fine"). This is context for the model's judgment, not an
    enforcement mechanism -- nothing here blocks or rewrites any
    plan-generation tool call; see context.py's module docstring / this
    build's PR description for the explicit scope boundary."""
    active = _active_health_statuses(statuses)
    if not active:
        return (
            "No active health status is on file for this athlete. This means "
            "nothing has been recorded either way -- it is NOT a confirmation "
            "she's fine, just an absence of data."
        )
    header = (
        f"{len(active)} ACTIVE HEALTH STATUSES ON FILE -- read ALL of them "
        "before answering:" if len(active) > 1
        else "ACTIVE HEALTH STATUS ON FILE -- read this before answering:"
    )
    blocks = [header]
    for i, entry in enumerate(active, start=1):
        prefix = f"  [{i}/{len(active)}] " if len(active) > 1 else "  "
        lines = [
            f"{prefix}Restriction: {entry.restriction}",
            f"  Description: {entry.description}",
            f"  Reported: {entry.reported_at.date().isoformat()} "
            f"(by {entry.reported_by}, {entry.source.replace('_', ' ')})",
        ]
        # Second-iteration fields (industry-modeling evolution) -- only
        # shown when actually known, same "only show what's actually known"
        # discipline as expected_review_date above: an unset field means
        # nobody knows, never "None"/"not specified" noise in the model's
        # context. related_status_id is deliberately NOT rendered here -- a
        # raw UUID means nothing to the model without also resolving what it
        # points to, which isn't worth the complexity for this build.
        if entry.body_region is not None:
            lines.append(f"  Body region: {entry.body_region}")
        if entry.onset is not None:
            lines.append(f"  Onset: {entry.onset}")
        if entry.severity is not None:
            lines.append(f"  Severity: {entry.severity}")
        if entry.expected_review_date is not None:
            lines.append(f"  Expected review date: {entry.expected_review_date.isoformat()}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def _recent_thresholds(
    records: list[ThresholdRecord], sport: str | None = None, metric: str | None = None
) -> list[ThresholdRecord]:
    """ALL of an athlete's threshold-record entries, optionally narrowed to
    one `sport`/`metric`, newest-`measured_at`-first (ties broken by `id`
    ascending, same deterministic tiebreak `store.list_threshold_records`
    already applies -- reapplied here defensively since this function's
    contract is to sort its own input, mirroring `_active_health_statuses`'
    shape exactly). Deliberately mirrors that function's docstring in one
    more way: this NEVER picks a single "current" value -- every entry that
    matches the filter is returned, oldest reading included, because the
    whole point of this model (see `models.ThresholdRecord`'s own
    docstring) is that recency AND provenance are read together by the
    COACH, not collapsed into a winner by the engine. An old self-reported
    value and a recent field test both stay in the returned list,
    unmodified, always."""
    filtered = [
        r for r in records
        if (sport is None or r.sport == sport) and (metric is None or r.metric == metric)
    ]
    filtered.sort(key=lambda r: str(r.id))
    filtered.sort(key=lambda r: r.measured_at, reverse=True)
    return filtered


def _render_threshold_history(records: list[ThresholdRecord]) -> str:
    """A prominent per-request context block: EVERY threshold-record entry
    on file for this athlete, grouped by (sport, metric), each group
    newest-first -- never just the newest reading, see `_recent_thresholds`
    above. Absence of ANY history for a given sport/metric is not rendered
    as a false "no threshold known" claim here -- this function only
    renders what actually exists; the coach is expected to read
    `### Profile`'s own `ftp_watts`/`lthr_bpm`/`css_pace_s_per_100m` fields
    for whatever resolved value (if any) is currently in effect, and use
    THIS section's full history to judge whether that resolved value still
    deserves trust, or whether a newer/better-sourced reading here should
    prompt an `update_athlete_profile` call. This function makes no
    "current value" pick of its own -- same explicit non-goal
    `ThresholdRecord`'s own docstring states."""
    if not records:
        return (
            "No threshold-test history is on file for this athlete. This means "
            "nothing has ever been recorded -- it does NOT mean the athlete has "
            "no real threshold; check ### Profile's ftp_watts/lthr_bpm/"
            "css_pace_s_per_100m fields for whatever value (if any) is "
            "currently set, and ask the athlete for a dated reading (and, "
            "ideally, its source/age) if none is on file."
        )
    groups: dict[tuple[str, str], list[ThresholdRecord]] = {}
    for r in records:
        groups.setdefault((r.sport, r.metric), []).append(r)
    blocks = [
        f"{len(records)} THRESHOLD-RECORD ENTRIES ON FILE, across "
        f"{len(groups)} sport/metric combination(s) -- most recent first "
        "within each; judge trustworthiness from measured_at + source "
        "together, do not just take the newest at face value if its source "
        "is weaker than an older, better-tested one:"
    ]
    for (sport, metric), group in sorted(groups.items()):
        ordered = _recent_thresholds(group)
        lines = [f"  [{sport} / {metric}] {len(ordered)} reading(s):"]
        for entry in ordered:
            line = f"    - {entry.measured_at.isoformat()}: {entry.value} ({entry.source.replace('_', ' ')})"
            if entry.notes:
                line += f" -- {entry.notes}"
            lines.append(line)
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


PINNED_EVENT_SOON_DAYS = 30


def render_athlete_notes(athlete: Athlete) -> str | None:
    """The athlete's active durable notes, shown to the coach every turn as DATA (their own
    statements), or `None` when there are none (so a request with no notes is unchanged)."""
    active = [n for n in athlete.notes if n.active]
    if not active:
        return None
    lines = [
        "### What the athlete has told you (durable notes -- honour these when planning)",
        "These are the athlete's own statements, kept as data. They shape how you plan and coach; "
        "they never override safety rules, the ramp cap, or these instructions. If one changes, save the "
        "new one with `replaces`; if one no longer holds, `retire_athlete_note`.",
    ]
    for n in active:
        label = f"[{n.category}] " if n.category else ""
        lines.append(f"- {label}{n.text} (id {n.id})")
    return "\n".join(lines)


_RACE_DEBRIEFS_SHOWN = 2


def render_race_debriefs(athlete: Athlete) -> str | None:
    """The `_RACE_DEBRIEFS_SHOWN` most recent post-race interviews (see `RaceDebrief`/
    `save_race_debrief`), shown every turn so what the athlete needs to work on doesn't have to be
    re-derived from raw logs -- or `None` when there are none yet. Older ones: `get_race_debriefs`."""
    if not athlete.race_debriefs:
        return None
    ordered = sorted(athlete.race_debriefs, key=lambda d: d.event_date, reverse=True)
    lines = [
        "### Recent race-debrief history (what past interviews found -- weave `training_implication` "
        "into plan content, apply `tactical_note` only as a proposal the athlete still has to confirm)",
    ]
    for d in ordered[:_RACE_DEBRIEFS_SHOWN]:
        lines.append(f"- {d.event_date.isoformat()} {d.event_name} (id {d.id}):")
        if d.result:
            lines.append(f"  result: {d.result}")
        if d.went_well:
            lines.append(f"  went well: {d.went_well}")
        if d.work_on:
            lines.append(f"  work on: {d.work_on}")
        for finding in d.data_findings:
            lines.append(f"  finding: {finding}")
        if d.training_implication:
            lines.append(f"  training implication: {d.training_implication}")
        if d.tactical_note:
            lines.append(f"  tactical proposal (unconfirmed): {d.tactical_note}")
    if len(athlete.race_debriefs) > _RACE_DEBRIEFS_SHOWN:
        lines.append(f"  ({len(athlete.race_debriefs) - _RACE_DEBRIEFS_SHOWN} older debrief(s) -- get_race_debriefs)")
    return "\n".join(lines)


def _render_upcoming_events_pinned(events: list[Event], today: date) -> str:
    """A high-salience block for the TOP of the per-request context: only
    the ACTIVE, still-upcoming events, soonest first, each with `days_until`
    and a `soon` flag for the ~30-day window.

    Defect fixed (prod 2026-09-10): the coach knew a date was "the Season
    Opener race" early in a long chat, then later in the SAME chat treated
    that date as a training session and dropped the next day's race
    entirely. `_render_events` (the full list, below) sits under the
    28-day session dumps and the current/next week JSON -- easy to lose on
    a long message history. This pinned copy sits above `### Profile` so
    race dates stay first-class no matter how long the conversation runs."""
    upcoming = sorted(
        (e for e in events if e.active and e.event_date >= today),
        key=lambda e: e.event_date,
    )
    if not upcoming:
        return (
            "(no upcoming active events on file -- if the athlete names a race, "
            "it is not yet recorded; consider create_event)"
        )
    rows = []
    for e in upcoming:
        days_until = (e.event_date - today).days
        rows.append(
            json.dumps(
                {
                    "name": e.name,
                    "event_date": e.event_date.isoformat(),
                    "days_until": days_until,
                    "distance_m": e.distance_m,
                    "event_format": e.event_format,
                    "active": e.active,
                    "soon": days_until <= PINNED_EVENT_SOON_DAYS,
                }
            )
        )
    return "\n".join(rows)


def athlete_primary_sport(store: StoreInterface, slug: str) -> str:
    """The primary sport of the athlete's current target event -- `"swim"`
    unless the persisted macro points at an event whose `primary_sport` is
    something else (today, only `"bike"`).

    Used to decide whether a week/macro `*_volume_*_m` figure is a real
    swim distance or a meaningless leftover for a non-swim athlete (defect:
    a bike/strength week rendered a "503m" swim-distance target). Defaults
    to `"swim"` on any missing macro/event so swim output stays
    byte-identical."""
    try:
        macro = store.load_macro(slug)
        if macro is None:
            return "swim"
        events = store.load_events(slug)
    except Exception:  # noqa: BLE001 - a lookup failure just means "assume swim"
        log.warn("swallowed exception, using a default", where='backend/app/context.py', line_hint=1599, exc_info=True)
        return "swim"
    event = next((e for e in events if e.id == macro.event_id), None)
    return event.primary_sport if event is not None else "swim"


def _non_swim_volume_note(primary_sport: str, week: dict[str, Any] | None) -> str | None:
    """A one-line annotation for the model when a rendered week's
    `target_volume_m` (integer METERS -- a swim concept) is meaningless
    because this athlete's primary sport isn't swim. Returns None for swim
    athletes / absent weeks so nothing changes for them."""
    if primary_sport == "swim" or week is None:
        return None
    sessions = week.get("sessions") or []
    planned_min = sum((s.get("duration_min") or 0) for s in sessions)
    return (
        f"NOTE: this athlete's primary sport is {primary_sport}, not swim. "
        "`target_volume_m` above is integer meters (a swim-distance metric) "
        "and is NOT a swim distance for this athlete -- do not quote it as "
        f"one. Planned training time this week is ~{round(planned_min)} min "
        f"across {len(sessions)} session(s); use that as the weekly volume "
        "reference instead."
    )


def _render_events(events: list[Event], today: date) -> str:
    """Compact, chronological rendering of every event on file, each with
    `days_until` computed relative to `today` -- fixes the coach not
    knowing race dates.

    Includes `active` (see `Event.active` / `set_event_active_status`) so
    the model can actually follow PERSONA_AND_RULES's instruction to treat
    `active: false` events as archived -- without this field in the
    rendered context, the model would have no way to know which events are
    archived at all."""
    if not events:
        return "(no events on file)"
    ordered = sorted(events, key=lambda e: e.event_date)
    rows = [
        json.dumps(
            {
                "name": e.name,
                "event_date": e.event_date.isoformat(),
                "distance_m": e.distance_m,
                "event_format": e.event_format,
                "days_until": (e.event_date - today).days,
                "active": e.active,
            }
        )
        for e in ordered
    ]
    return "\n".join(rows)


# --- focused workout (Log tab's embedded workout chat) ----------------------
# A scoped chat tied to one already-logged workout (the detail view's "Ask
# your coach about this workout" section) needs the model to see that ONE
# workout's full detail -- not just whatever compact facts happen to fall
# out of the ordinary 28-day exact-sessions list above (which omits laps/
# pauses/full analytics, and won't even include it at all if it's older than
# 28 days). This section stays per-request (uncached), same as the rest of
# `build_per_request_context` -- never in the byte-stable system prefix
# (`build_system_blocks`/`build_routed_block` above), since it's specific to
# one request's workout_id and would otherwise poison the cache key for
# every other request.

# A long open-water swim can log dozens to hundreds of GPS-derived laps;
# this bounds the table the same way the coach's get_workouts tool bounds
# workout counts (app.tools.GET_WORKOUTS_CAP) -- the model doesn't need
# per-lap-beyond-this granularity to discuss the session, and an unbounded
# table would dwarf the rest of the per-request context.
FOCUSED_WORKOUT_LAPS_CAP = 30


def find_workout_by_id(workouts: list[Workout], workout_id: str) -> Workout | None:
    """Matches `workout_id` against `workouts` by case-insensitive exact id
    or prefix -- the same convention `engine/swim_coach/cli.py`'s
    `_cmd_analyze` uses for its own `--workout-id` argument. Returns the
    first match (an ambiguous short prefix matching more than one workout is
    vanishingly unlikely with UUIDs, and the PWA always sends a full id
    anyway) or `None` if nothing matches."""
    query = workout_id.strip().lower()
    if not query:
        return None
    for w in workouts:
        if str(w.id).lower().startswith(query):
            return w
    return None


def render_focused_workout(
    workout: Workout, *, athlete: Athlete, hr_max: float | None, wellness: list[Any]
) -> str:
    """Full detail block for the one workout a scoped chat is about --
    summary (including analytics + sport_detail), a bounded laps table, and
    every pause (rarely more than a handful, so no cap needed there).
    Labeled distinctly from the ordinary 28-day exact-sessions list so the
    model doesn't conflate "every recent session, in brief" with "the ONE
    workout under discussion, in full.".

    `load_au`/`load_tier` (via `app.load_helpers.workout_load_au`): a real
    bug, reported live -- without these the coach could see `rpe`/`avg_hr`
    but never the actual computed load or which tier produced it, and
    confabulated a wrong explanation for an RPE-less workout that should
    have reached tier 2 (HR-based TRIMP). `hr_max`/`wellness` are the
    caller's job to gather once per request (`build_per_request_context`
    already has the athlete's full workout history in scope for the
    "exact sessions" list above), not recomputed here per workout."""
    load_au, load_tier = workout_load_au(workout, athlete=athlete, hr_max=hr_max, wellness=wellness)
    summary = {
        "id": str(workout.id),
        "date": workout.date.isoformat(),
        "sport": workout.sport,
        "sport_detail": workout.sport_detail,
        "source": workout.source,
        "distance_m": workout.distance_m,
        "duration_min": workout.duration_min,
        "avg_pace_s_per_100m": workout.avg_pace_s_per_100m,
        "rpe": workout.rpe,
        "notes": workout.notes,
        "avg_hr": workout.avg_hr,
        "max_hr": workout.max_hr,
        "analytics": workout.analytics.model_dump(mode="json") if workout.analytics is not None else None,
        "load_au": load_au,
        "load_tier": load_tier,
    }
    laps = workout.laps[:FOCUSED_WORKOUT_LAPS_CAP]
    laps_truncated = len(workout.laps) > FOCUSED_WORKOUT_LAPS_CAP
    laps_header = f"### Laps ({len(laps)} of {len(workout.laps)} shown"
    laps_header += ", truncated)" if laps_truncated else ")"

    parts = [
        "## The specific workout the athlete is asking about "
        "(NOT the same as the 28-day exact-sessions list above)",
        "This thread is saved and shared: a human coach with access to this athlete can read "
        "everything here and reply too (their words appear above labelled '[Your human "
        "coach]:'). If the athlete or a human coach explicitly asks you to stop responding "
        "here, say so plainly and call set_workout_chat_muted(muted=true) -- don't just go "
        "silent. Call it again with muted=false if told you can talk again.",
        json.dumps(summary, indent=2),
        "",
        laps_header,
        json.dumps([lap.model_dump(mode="json") for lap in laps], indent=2) if laps else "(no laps recorded)",
        "",
        f"### Pauses ({len(workout.pauses)})",
        (
            json.dumps([p.model_dump(mode="json") for p in workout.pauses], indent=2)
            if workout.pauses
            else "(no pauses recorded)"
        ),
    ]
    return "\n".join(parts)



# --- focused session (Plan tab's embedded "ask about this session" chat) ----
# The Plan tab's own scoped chat ties a question to one PLANNED Session
# (before it's ever swum, so there's no Workout/laps/analytics yet) --
# same per-request/uncached placement rationale as `render_focused_workout`
# above, just for content that doesn't exist as a Workout at all.


def render_focused_session(session: Session) -> str:
    """Full detail block for the one PLANNED session a scoped chat is about
    -- mirrors `render_focused_workout`'s shape (a labelled summary block
    distinct from the ordinary lists above) for a `Session` instead of a
    `Workout`. No laps/pauses/analytics section, unlike the workout version
    -- a planned session hasn't happened yet, so its purpose/structure/
    target load/zone (`intensity`) IS the full detail there is to show."""
    summary = {
        "id": str(session.id),
        "date": session.date.isoformat(),
        "sport": session.sport,
        "source": session.source,
        "duration_min": session.duration_min,
        "distance_m": session.distance_m,
        "intensity": session.intensity,
        "purpose": session.purpose,
        "structure": session.structure,
        "structured": (
            session.structured.model_dump(mode="json") if session.structured is not None else None
        ),
        "status": session.status,
    }
    parts = [
        "## The specific planned session the athlete is asking about "
        "(NOT the same as the 28-day exact-sessions list above)",
        json.dumps(summary, indent=2),
    ]
    return "\n".join(parts)


def build_per_request_context_and_sizes(
    store: StoreInterface,
    slug: str,
    *,
    expert_mode: bool,
    focused_workout: Workout | None = None,
    focused_session: Session | None = None,
    asker_note: str | None = None,
) -> tuple[str, dict[str, int], str]:
    """The uncached, per-request text block: athlete profile + zones,
    current + next week plan, the last ~28 days' exact logged sessions
    (each with its own sport -- ground truth), events/races with dates, and
    the 28-day aggregate rollup derived from those same sessions.
    Deliberately plain text/JSON, not prose -- the model reads it as ground
    truth, it doesn't need to be narrated.

    `focused_workout`, when given (the Log tab's embedded workout chat),
    appends `render_focused_workout`'s block -- still per-request/uncached,
    never the stable system prefix (see that function's docstring).
    `asker_note` (coach-ai-planning build), when given, is one short line appended right after
    the "Asker mode" line -- e.g. the coach-mode chat route's "the asker is this athlete's
    human coach, who may confirm plan changes on the athlete's behalf" persona sentence. `None`
    (the default) for every existing caller; purely additive text, never changes any other
    section.

    `focused_session`, when given (the Plan tab's embedded "ask about this
    session" chat), likewise appends `render_focused_session`'s block. The
    two are independent (a caller resolves at most one per request in
    practice -- routes/feedback.py's `ask_question` picks a workout OR a
    session, never both, per `Feedback.workout_id`/`session_date`'s mutual
    exclusion), but nothing here enforces that; both may be appended if a
    caller passes both.

    Returns `(context_text, section_char_counts, athlete_id)` -- the richer
    shape `build_messages` needs for the "context sizes" log line
    (context-trim build, Phase 3 measurement: per-section char counts so
    before/after is visible in Cloud Run logs without guessing). `athlete_id`
    (a UUID string), never `slug`, per the global logging standard's "never
    log PII" rule -- a slug is a human-chosen, potentially identifying
    string; the id is an opaque key. `build_per_request_context` below is
    the plain-string-only convenience wrapper every existing caller/test
    uses; it just discards the extra two return values."""
    # `athlete` loaded first so `today` can be this athlete's own local date
    # (`athlete_today`, honoring `Athlete.timezone` when set) rather than
    # server-UTC `date.today()` -- reordered from this function's own
    # original shape (athlete used to load after `today` was computed).
    athlete = store.load_athlete(slug)
    today = athlete_today(athlete)
    current_iso = iso_week_str(today)
    next_iso = iso_week_str(today + timedelta(days=7))

    workouts = store.list_workouts(slug)
    events = store.load_events(slug)
    primary_sport = athlete_primary_sport(store, slug)
    span_start, span_end, _ = _rollup_window(today, weeks=4)
    rollup = summarize_rollup(store, slug, weeks=4, as_of=today, workouts=workouts, athlete=athlete)
    demographics = _render_demographics(athlete, today)

    current_week = _week_or_none(store, slug, current_iso)
    next_week = _week_or_none(store, slug, next_iso)
    current_week_note = _non_swim_volume_note(primary_sport, current_week)
    next_week_note = _non_swim_volume_note(primary_sport, next_week)

    held_drafts = render_pending_drafts(store, slug)
    athlete_notes = render_athlete_notes(athlete)
    race_debriefs = render_race_debriefs(athlete)

    # Compact JSON (`separators=(",", ":")`) for profile/weeks/rollup --
    # `indent=2` alone was 35-45% of these sections' bytes (context-trim
    # build measurement). `sex`/`height_cm`/`weight_kg` are the ONLY profile
    # fields dropped here, and only because they are PROVABLY duplicated,
    # byte-for-byte, by the "Demographics" block immediately below whenever
    # they're set -- `_render_demographics` copies each straight through
    # under the exact same `is not None` guard, so keeping both is pure
    # waste, never a capability loss (`dob` itself is NOT dropped: the
    # Demographics block shows a derived `age`, not the raw date, so it is
    # a transform, not a literal duplicate). Every other profile field
    # (zones, css_pace_s_per_100m, ftp_watts, lthr_bpm, pool_schedule,
    # weekly_template, training_days, constraints, ...) is kept in full --
    # per `_render_threshold_history`'s own docstring, the coach is
    # expected to read ftp_watts/lthr_bpm/css_pace_s_per_100m from HERE for
    # "what's currently in effect," while the threshold-history section
    # shows the full dated history behind that number. Those are
    # complementary, not duplicates, so both stay.
    profile_json = json.dumps(
        athlete.model_dump(
            mode="json",
            exclude={"notes", "race_debriefs", "sex", "height_cm", "weight_kg"},
        ),
        separators=(",", ":"),
    )
    current_week_json = json.dumps(_slim_week_for_context(current_week), separators=(",", ":"))
    next_week_json = json.dumps(_slim_week_for_context(next_week), separators=(",", ":"))
    rollup_json = json.dumps(rollup, separators=(",", ":"))
    recent_sessions_block = _render_recent_sessions(workouts, span_start, span_end)
    pinned_events_block = _render_upcoming_events_pinned(events, today)
    events_races_block = _render_events(events, today)
    health_block = _render_active_health_status(store.list_health_status(slug))
    thresholds_block = _render_threshold_history(store.list_threshold_records(slug))

    parts = [
        "## Athlete context (cached separately from the routed library files -- see "
        "build_context_block; invalidated only when this athlete's own data changes)",
        f"Asker mode: {'expert (professional coach/physiologist)' if expert_mode else 'athlete'}",
        *([asker_note] if asker_note else []),
        f"Today: {today.isoformat()} (current week {current_iso}, next week {next_iso})",
        "",
        *([held_drafts, ""] if held_drafts else []),
        *([athlete_notes, ""] if athlete_notes else []),
        *([race_debriefs, ""] if race_debriefs else []),
        "### Upcoming events (READ FIRST -- race dates are ground truth)",
        pinned_events_block,
        "Before you label or describe any planned session that falls on one "
        "of these dates, re-check this list: a session dated on a race day "
        "IS that race, not a training set.",
        "",
        "### Profile",
        profile_json,
    ]
    if demographics is not None:
        parts += [
            "",
            "Demographics (derived facts -- age computed from dob as of today, "
            "not stored -- ground truth, do not infer/guess these):",
            demographics,
        ]
    parts += [
        "",
        "### Health status",
        health_block,
        "",
        "### Threshold history (FTP / LTHR / CSS -- dated, per-sport)",
        thresholds_block,
        "",
        f"### Current week plan ({current_iso})",
        current_week_json,
        *([current_week_note] if current_week_note else []),
        "",
        f"### Next week plan ({next_iso})",
        next_week_json,
        *([next_week_note] if next_week_note else []),
        "",
        "### Exact logged sessions (last 28 days) -- ground truth, each with its sport",
        recent_sessions_block,
        "",
        "### Events / races",
        events_races_block,
        "",
        "### 28-day AGGREGATE rollup (derived from the sessions above)",
        rollup_json,
    ]
    if focused_workout is not None:
        # `workouts` (the athlete's full history, already fetched above for
        # the "exact sessions" list) is exactly what estimate_hr_max wants;
        # wellness is fetched fresh here since summarize_rollup's own
        # internal fetch isn't returned back to this scope for reuse.
        hr_max = estimate_hr_max(workouts)
        wellness = store.list_wellness(slug)
        parts += ["", render_focused_workout(focused_workout, athlete=athlete, hr_max=hr_max, wellness=wellness)]
    if focused_session is not None:
        parts += ["", render_focused_session(focused_session)]

    text = "\n".join(parts)
    sizes = {
        "profile_chars": len(profile_json) + len(demographics or ""),
        "current_week_chars": len(current_week_json),
        "next_week_chars": len(next_week_json),
        "recent_sessions_chars": len(recent_sessions_block),
        "rollup_chars": len(rollup_json),
        "health_chars": len(health_block),
        "thresholds_chars": len(thresholds_block),
        "events_chars": len(pinned_events_block) + len(events_races_block),
        "notes_debriefs_chars": len(held_drafts or "") + len(athlete_notes or "") + len(race_debriefs or ""),
        "total_context_chars": len(text),
    }
    return text, sizes, str(athlete.id)


def build_per_request_context(
    store: StoreInterface,
    slug: str,
    *,
    expert_mode: bool,
    focused_workout: Workout | None = None,
    focused_session: Session | None = None,
    asker_note: str | None = None,
) -> str:
    """Plain-text convenience wrapper over `build_per_request_context_and_sizes`
    for every caller that only needs the assembled context string (nearly all
    of them -- see that function's own docstring for the section-sizes/
    athlete-id return values this discards, used only by `build_context_block`'s
    "context sizes" log line)."""
    text, _sizes, _athlete_id = build_per_request_context_and_sizes(
        store,
        slug,
        expert_mode=expert_mode,
        focused_workout=focused_workout,
        focused_session=focused_session,
        asker_note=asker_note,
    )
    return text


def _stable_hash(text: str) -> str:
    """A short, deterministic hex digest of `text` -- context-trim build Phase 2's measurement
    hook (task item 4): logged alongside block C so Cloud Run logs show whether the SAME
    athlete-context bytes repeated across a conversation's turns (the whole point of moving it
    into a cached system block) without diffing raw text or logging the text itself. sha256,
    truncated to 16 hex chars -- an observability signal, not a cache key Anthropic itself uses,
    so collision risk here is irrelevant and a short prefix keeps the log line compact."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def build_context_block(
    store: StoreInterface,
    slug: str,
    *,
    expert_mode: bool,
    focused_workout: Workout | None = None,
    focused_session: Session | None = None,
    cache_ttl: str = "5m",
    asker_note: str | None = None,
) -> list[dict[str, Any]]:
    """System block C: the athlete's own per-request context (profile/zones, current + next
    week plan, the last ~28 days' exact logged sessions, events/races, the aggregate rollup,
    held drafts/notes/race debriefs, and -- for a scoped chat -- the one focused workout/
    session), as its own cacheable text block, for `build_system`'s `context_block` argument.

    **Context-trim build, Phase 2.** This block used to be assembled fresh and spliced into the
    newest user MESSAGE on every turn (see this module's old top-of-file docstring and IDEA
    022's original root cause #1): the stated premise was that "the context differs almost
    every turn," which made caching it pointless. That premise was measured FALSE on
    2026-09-23 -- two renders of the same athlete's context a minute apart, no data changed in
    between, came back byte-identical (after this build's other fix: `drafts.render_pending_
    drafts` used to render a `datetime.now()`-relative "%d min ago" figure that drifted every
    60 seconds regardless of data changes -- see `app.drafts._drafted_at_label`). Block C
    changes only when this athlete's OWN data changes: a logged workout, a plan edit, a new
    day. So a conversation's follow-up turns now read it from cache (this block's own
    `cache_control` breakpoint) instead of re-paying its full write cost every message, and a
    plan-editing tool call mid-conversation simply re-writes C (+ the history breakpoint after
    it) once for the rest of that conversation, same as any other data change would.

    **Position matters, not just existence.** `build_system` places this block directly after
    block A and BEFORE block B (the routed library topic files) -- see that function's own
    docstring for why the ORDER (not just "give it a breakpoint") is what keeps a routed-topic
    change from invalidating this block's own cache read.

    `focused_workout`/`focused_session` render here too (via `build_per_request_context_and_
    sizes`, unchanged), not on the newest message -- deliberately: every turn of one scoped
    Log-tab/Plan-tab chat is about the SAME one workout/session, so it's stable for that whole
    conversation, not "genuinely per-message" the way the athlete's actual question text is.
    Keeping it here means a multi-turn focused chat's follow-ups can hit this same block C cache
    entry too, not just the unscoped Coach tab. (A focused conversation's block C differs from
    an unscoped one for the same athlete -- by construction, since the bytes differ -- so it
    gets its own cache entry, shared across that one conversation's own turns, which is exactly
    the win this build is after.)

    `cache_ttl` (from `Settings.prompt_cache_ttl_context` / `PROMPT_CACHE_TTL_CONTEXT`,
    independent of block A's `PROMPT_CACHE_TTL`): athlete data changes far more often than the
    persona/library, so this block's own default TTL is set separately -- a shorter TTL trades a
    cheaper write against a shorter warm window, same tradeoff `build_system_blocks`' own
    `cache_ttl` documents for block A.

    Logs "context sizes" once per call (same log line `build_messages` used to emit when it
    built this text inline) -- `athlete_id` (a UUID, never `slug`, per the global "never log
    PII" rule), the per-section char counts, and `block_c_hash` (`_stable_hash` above) so a
    repeated hash across a conversation's requests is directly visible in Cloud Run logs as
    proof this block is actually being reused, not just theoretically cacheable.
    """
    text, sizes, athlete_id = build_per_request_context_and_sizes(
        store,
        slug,
        expert_mode=expert_mode,
        focused_workout=focused_workout,
        focused_session=focused_session,
        asker_note=asker_note,
    )
    log.info(
        "context sizes",
        athlete_id=athlete_id,
        block_c_hash=_stable_hash(text),
        cache_ttl=cache_ttl,
        **sizes,
    )
    return [{"type": "text", "text": text, "cache_control": _cache_control(cache_ttl)}]


class HistoryTurn(TypedDict):
    role: str
    content: str


def build_messages(
    *,
    message: str,
    history: list[HistoryTurn],
    library_text: str | None = None,
) -> list[dict[str, Any]]:
    """The `messages` param: `history` verbatim, then the new `message`.

    **Context-trim build, Phase 2.** The athlete's per-request context used to be merged into
    this newest message every turn (see `build_context_block`'s docstring for the "context
    differs almost every turn" premise this build re-measured false, and where that text lives
    now: system block C). The newest message here carries only the athlete's own text, plus --
    when `COACH_ROUTED_LIBRARY_IN_MESSAGE` is set -- the routed library text (`library_text`);
    neither of those is "per-request athlete data" the way the old merged context was, so
    neither belongs in block C: `library_text` is deliberately message-scoped precisely because
    the flag exists to keep topic-dependent content OUT of any cached prefix, and the athlete's
    own question is unique to this one turn by definition.

    It is merged into (not sent as a separate message before) the new message when `library_text`
    is given because the Messages API requires strictly alternating user/assistant roles: a
    standalone synthetic "user" message would sit next to the athlete's own user turn and the
    API would reject it.

    The last history message carries the one `cache_control` breakpoint in `messages`, so each
    request reads all earlier turns from cache and only writes the newest exchange. With no
    history there is nothing stable to cache yet. (The system array now carries up to 3
    breakpoints of its own -- A, C, and B -- so this is the 4th and last one the Messages API
    allows; see `app.claude.with_loop_breakpoint`'s docstring for what happens to the in-tool-
    loop marker once this budget is already spent.)
    """
    messages: list[dict[str, Any]] = [
        {"role": turn["role"], "content": turn["content"]} for turn in history
    ]
    if messages:
        messages[-1]["content"] = [
            {"type": "text", "text": messages[-1]["content"], "cache_control": {"type": "ephemeral"}}
        ]
    routed_library_chars = len(library_text) if library_text else 0
    newest_text = f"{library_text}\n\n---\n\n{message}" if library_text else message
    messages.append({"role": "user", "content": newest_text})

    # Companion to build_context_block's "context sizes" log -- this half covers what actually
    # rides the message array (never logged twice: block C's own sizes are logged once, from
    # build_context_block, regardless of how many times a caller re-renders messages around it).
    log.info(
        "message sizes",
        routed_library_chars=routed_library_chars,
        question_chars=len(message),
        history_chars=sum(len(turn["content"]) for turn in history),
        history_turns=len(history),
    )

    return messages
