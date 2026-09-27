---
name: adapt
description: The Sunday adaptation ritual — reviews the past week's training load, wellness, and compliance (or runs the race-weekend debrief flow if a race happened), authors next week's real sessions directly, red-teams them with the engine's advisory check, and finalizes the plan. Use when the athlete (or Andrew) says it's time for the weekly check-in/adaptation, or asks "what should next week look like given how this week went?".
---

# adapt

Sunday ritual: gather context → decide race-weekend or ordinary weekly
review → author the week's real sessions directly (the coach's own
judgment, red-teamed by the engine, never a rule-based generator) →
finalize → append rationale to `notes/decisions.md` → commit.

**Primary reference: `library/37-plan-authoring-guide.md`** ("Weekly
review order" and "Race-weekend Sunday flow" sections) — this skill is a
short pointer into that guide plus the file-path/commit mechanics
specific to this offline/agent-session workflow; read it before an
unusual week (a race, an injury, a big compliance gap) rather than relying
on this skill's own summary alone.

**Never hand-compute zones, loads, volumes, or ladder steps in chat**
(CLAUDE.md standing rule). Every number comes from `python -m
swim_coach.cli` or the engine's own `plan_check`/`load` modules; this
skill's job is judgment on top of that output, not arithmetic.

**The old rule-based generator is retired** (engine/plan-check-red-team,
`draft_macro_plan`/`create_week_plan`/`replace_week_plan` and `propose_
adaptation`'s generator path — CLAUDE.md's standing rule now reads "the
coach authors plan structure and judgment; the engine only computes and
red-teams"). `cli adapt`'s cut/repeat/hold/advance rule table and
`cli scaffold-macro` still exist in `plan.py` but are unused scaffold code
kept for one release before deletion — don't reach for either. Author the
week directly instead (this skill's step 3), the same real `Session` list
the chat coach's `author_week_plan` tool persists, checked against the
engine's advisory `plan_check.check_week`/`check_macro`, never a generator
draft.

## 1. Gather context

```
python -m swim_coach.cli summarize --athlete <slug> --weeks 4
```

Read the rollup: volume/week, sRPE load by day, 7d:28d load ratio, monotony,
wellness trend, compliance %. This is the same rollup Phase 2's chat context
assembler reuses — get a feel for the trend, not just the latest number.

Also read (don't recompute):
- `athletes/<slug>/plan/weeks/<last_iso_week>.yaml` — what was actually
  planned last week (sessions, purpose, any prior adaptation_rationale).
- `athletes/<slug>/events.yaml` — the target event(s), `event_format`, and
  date. Note `priority` (A vs B) and how close the event is — a taper block
  or race week the athlete is training around changes what "hold" or
  "advance" should mean in practice, even though the engine handles the
  macro-block volume math.
- `athletes/<slug>/notes/decisions.md` — recent coaching context (e.g. a
  prior injury/illness history, a scheduled long-swim milestone, a known
  format-switch decision point).

## 2. Race weekend, or an ordinary week?

If a race (or key event) happened this week, follow `library/37`'s
**"Race-weekend Sunday flow"** in full: debrief (`save_race_debrief`,
objective data first), update the real FTP/CTL numbers, adapt the next
block's limiter/key sessions with reasons, then go to step 3 to author
sessions through the next race weekend or ~2 weeks (whichever is longer),
not just the coming week.

Otherwise, follow `library/37`'s **"Weekly review order"**: did the work
happen (compliance — which sessions were missed, and were they the right
ones); is fitness moving as planned (CTL vs. the macro row —
`plan_check.check_macro`'s ramp/recovery-cadence findings, not a rule you
compute by hand); is fatigue tolerable (TSB trend + wellness — one bad
night is noise, several consecutive red signals aren't); what do the
sessions say (power/pace holding, hard sessions completed as written or
quietly shortened). **"The plan is working, keep going" is a legitimate
outcome — don't author a change just to have done something.**

If there's no macro row to adapt from at all (no macro plan on file, or no
finalized prior week), **report the gap to the athlete/Andrew — don't
hand-compute a substitute plan.** Author (or ask for) the macro first.

## 3. Author the week, then check it — never a generator draft

Write the coming week's real sessions directly (the same `Session` shape
`author_week_plan` persists over chat): informed by the macro row's
`focus`/`key_sessions`/`hours`/`load_tss`, the step-2 review, and your own
judgment — not a rule table. Then red-team what you wrote, exactly as
`library/37`'s "Handling `check_macro`/`check_week` findings" section
describes:

- Run `swim_coach.plan_check.check_week` against the drafted sessions (the
  macro row, and recent weeks for the volume/long-swim-step comparison).
  It never rejects or clamps — it's advisory, capped at six findings,
  ranked by severity.
- Show the athlete every finding — verdict, severity, evidence,
  consequence, fix — and get an explicit accept-or-decline **with a
  reason** for each. Declining is legitimate; don't manufacture a change
  just because a finding exists.
- **Never loosen a `confirm-*` finding without it** — the +8%/week volume
  and +15% long-swim-step safety rails (CLAUDE.md) require an explicit
  accepted decision before the week persists. You may *tighten* (hold back
  further than the check requires) based on context it can't see — a
  known injury/illness history, a scheduled milestone, an upcoming travel
  week (`notes/decisions.md`) — but never loosen past its findings.
- **Real fixed events and the pool coach's actual content.** Cross-check
  against known races/travel, and reconcile the pool coach's actual
  (not estimated) session content into the session's `purpose`/`structure`
  once it's been shared — don't silently trust a placeholder.
- **Milestone follow-through.** A long-swim milestone's full recovery
  window is 3-5 days and spans into the *following* week (ROADMAP.md) —
  note the milestone date in `notes/decisions.md` so the next review
  accounts for it; there is no persistent engine memory of this across
  sessions, you are the state that carries it forward.
- **Wellness/compliance signals, read plainly.** A red wellness/load-ratio
  signal, or low compliance, is not optional to soften — say so when you
  present the week, and read *why* (illness, life stress, an unrealistic
  plan all look similar in the numbers but want different conversations).

## 4. Finalize

1. Once the athlete has accepted or declined every finding, write the
   final sessions to `athletes/<slug>/plan/weeks/<next_iso_week>.yaml` —
   check with them first for any week a `confirm-*` finding covers, per
   CLAUDE.md's explicit-confirmation safety rail.
2. Validate: `python -m swim_coach.cli validate --athlete <slug>` — must
   exit 0 before committing.
3. Append a dated entry to `athletes/<slug>/notes/decisions.md`: what
   changed and why, each finding's accept/decline and reason, and any
   judgment calls on top (fixed-event adjustments, tightened caps,
   milestone date recorded for next week) — the same record
   `author_week_plan`'s `decisions` would persist over chat.
4. Commit **directly to main** and push immediately (CLAUDE.md: athlete
   daily data — logs, wellness, weekly plans — commits straight to main,
   not a feature branch/PR; pull before write to avoid clobbering a
   concurrent edit).

## If the push fails

**Report the failure and stop — do not loop, retry silently, or force-push.**
Tell the athlete/Andrew what happened (e.g. "push rejected, likely a
concurrent edit — please pull and let me know how you'd like to reconcile")
and wait for direction. The finalized week file and the decisions.md entry
are still on disk locally either way, so nothing is lost by stopping here.
