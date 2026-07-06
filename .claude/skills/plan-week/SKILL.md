---
name: plan-week
description: Generate (or regenerate) one week of the training plan from the macro periodization scaffold — the non-adaptive counterpart to /adapt. Use when a macro plan already exists and the athlete needs a specific upcoming week planned (e.g. onboarding's first week, refilling a gap week, or redoing a week that wasn't touched by /adapt).
---

# plan-week

`cli plan-week` → present conversationally → adjust → validate → commit.

**Never hand-compute sessions, volumes, or dates in chat** (CLAUDE.md
standing rule) — this skill's only source of numbers is the CLI.

## When to use this vs. /adapt

- **`/plan-week`**: the athlete has no adaptation history to react to yet
  (the very first week after onboarding), or a specific week needs
  (re)generating from the macro's default schedule with no rule-table
  judgment applied (e.g. filling a gap week, or deliberately resetting a
  week back to the macro's baseline).
- **`/adapt`**: the normal weekly cadence — reacts to last week's actual
  load/wellness/compliance via the engine's rule table. Prefer `/adapt` once
  there's a prior finalized week to react to.

## 1. Generate

```
python -m swim_coach.cli plan-week --athlete <slug> --week <iso_week>
```

This reads the athlete's macro plan, looks up the target event's
`event_format` from `events.yaml` (single continuous long swim vs.
back-to-back Saturday+Sunday stage swims — the engine picks this up
automatically, you don't pass it), and writes/prints the generated
`WeekPlan`. If a non-draft week already exists at that path and you mean to
regenerate it, re-run with `--force` — otherwise the CLI refuses to clobber
a finalized week.

If the CLI errors (no macro plan yet), **report it** — run
`/onboard-athlete`'s macro-scaffolding step or `cli scaffold-macro` first,
don't improvise a plan by hand.

## 2. Present conversationally

Summarize the generated week in plain language: meso block/focus, target
volume, and each session (day, sport, distance/duration, purpose). Call out
anything the athlete should specifically know:
- Pool sessions are placeholders (`source: pool_coach`) — content is
  assigned by the pool coach after the session; the engine only estimates
  duration/distance for planning purposes.
- The long swim's placement/structure (single continuous Saturday swim vs.
  Saturday+Sunday stage swims) follows the event's `event_format` — mention
  which one and why, especially right after a format switch.

## 3. Adjust

If the athlete wants a change that fits within what the engine already
supports (e.g. a different week to plan, a different `--force` regeneration
after correcting the macro or profile), re-run the CLI — don't hand-edit
numbers into the YAML to match a request the CLI doesn't yet expose as a
flag. If the requested change is a genuine one-off exception to the
generated week (e.g. swapping which day carries strength because of a
known schedule conflict), edit the `Session` list directly in the week's
YAML file, keeping every field type-valid, then proceed to validate.

Do not increase weekly volume or long-swim distance beyond what the CLI
generated without the athlete's explicit confirmation (CLAUDE.md safety
rail) — the generated numbers already respect the engine's ramp/long-swim
caps; loosening them by hand defeats the point.

## 4. Validate

```
python -m swim_coach.cli validate --athlete <slug>
```

Must exit 0 before committing. If it doesn't, fix the YAML (or re-run
plan-week) rather than committing an invalid file.

## 5. Commit

Commit **directly to main** and push immediately (CLAUDE.md: athlete daily
data — logs, wellness, weekly plans — commits straight to main, not a
feature branch/PR; pull before write).

## If the push fails

**Report the failure and stop — do not loop, retry silently, or
force-push.** The generated/validated week file is still on disk locally;
tell the athlete/Andrew what happened and wait for direction on how to
reconcile.
