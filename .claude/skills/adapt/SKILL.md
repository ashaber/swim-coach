---
name: adapt
description: The Sunday adaptation ritual — reviews the past week's training load, wellness, and compliance, runs the engine's deterministic adaptation draft, applies coaching judgment on top of it, and finalizes next week's plan. Use when the athlete (or Andrew) says it's time for the weekly check-in/adaptation, or asks "what should next week look like given how this week went?".
---

# adapt

Sunday ritual: `cli summarize` + `cli adapt` → review the draft with
judgment → finalize next week → append rationale to `notes/decisions.md` →
commit.

**Never hand-compute zones, loads, volumes, or ladder steps in chat**
(CLAUDE.md standing rule). Every number in this skill comes from
`python -m swim_coach.cli`; this skill's job is judgment on top of that
output, not arithmetic.

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

## 2. Run the engine's adaptation draft

```
python -m swim_coach.cli adapt --athlete <slug> --week <next_iso_week>
```

This writes `athletes/<slug>/plan/weeks/<next_iso_week>.yaml` with
`draft: true` and prints the machine `rationale` JSON: which rule fired
(`cut` / `repeat` / `hold` / `advance`), the wellness/load-ratio/compliance
signals behind it, and the resulting volume and long-swim numbers (including
which format ladder — `single_day` or `multi_day_stage` — drove the long
swim). If a non-draft week already exists at that path and you deliberately
mean to redo it, re-run with `--force`.

If the CLI errors (e.g. no macro, no finalized prior week to adapt from),
**report the error to the athlete/Andrew — don't try to work around it by
hand-computing a substitute plan.** Fix the underlying data gap (e.g. run
`/plan-week` first, or `scaffold-macro`) and re-run.

## 3. Judgment review — the draft is a draft

The engine enforces the hard caps (it will never exceed the +8%/week volume
ramp, the long-swim step/peak-share caps, or skip a mandated cut on red
wellness/load). Your job is everything the engine can't see:

- **Real fixed events.** Cross-check the drafted week against known races,
  travel, or the pool coach's actual (not estimated) session content if it's
  already been shared. The engine's pool placeholders are estimates
  (`source: pool_coach`, content assigned reactively) — if the pool coach
  has already communicated this week's focus, reconcile it by hand in the
  session's `purpose`/`structure`, don't silently trust the placeholder.
- **Never loosen an engine cap.** If the draft's numbers look conservative
  and you're tempted to push further (e.g. "she's clearly fine, let's add
  more"), don't — the caps encode the safety rails from CLAUDE.md
  (ramp cap, long-swim step cap) and from the athlete's own history
  (injury/illness restarts, anaphylaxis, etc. — check `notes/decisions.md`).
  You may *tighten* (hold back further than the draft suggests) based on
  context the engine doesn't have, but never loosen.
- **Milestone follow-through.** If the rationale's `long_swim.milestone` is
  `true`, the engine has already marked the one post-milestone recovery day
  it can see (Sunday) as easy — but per ROADMAP.md the full recovery window
  is 3-5 days and spans into the *following* week. Note the milestone date
  in `notes/decisions.md` so the *next* `/adapt` run can pass
  `--days-since-last-milestone` accurately (the engine has no persistent
  memory of this across CLI invocations — you are the state that carries
  it forward).
- **Compliance <70% ("repeat")**: read *why* before just repeating the
  progression step — illness, life stress, and "the plan was unrealistic"
  all produce the same number but want different conversations.
- **Wellness or load-ratio red ("cut")**: this is not optional to soften.
  Read the specific wellness fields that flagged red (sleep, stress,
  soreness, motivation) and say so plainly when you present the plan.

If you want to change something inside the engine's caps (e.g. move a
strength day, adjust which day carries the "additional" swim), edit the
`WeekPlan` sessions directly in the YAML, then re-validate (step 4) — don't
regenerate through the CLI a second time with different flags to get a
different number; the CLI's job is the rule table, not knob-turning.

## 4. Finalize

1. Edit `athletes/<slug>/plan/weeks/<next_iso_week>.yaml`: set `draft: false`
   once you're done reviewing (leave it `true` if you're presenting the
   draft to the athlete for confirmation before locking it in — check with
   them first for any week that cuts volume or advances a long-swim
   milestone, per CLAUDE.md's "weekly volume/long-swim caps need explicit
   athlete confirmation" safety rail).
2. Validate: `python -m swim_coach.cli validate --athlete <slug>` — must
   exit 0 before committing.
3. Append a dated entry to `athletes/<slug>/notes/decisions.md` with the
   action taken, the rationale numbers, and any judgment calls you made on
   top of the draft (fixed-event adjustments, tightened caps, milestone
   date recorded for next week).
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
