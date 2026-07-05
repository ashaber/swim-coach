---
name: check-in
description: Use for the athlete's daily wellness check-in -- capturing sleep, stress, soreness, and motivation. Invoke on phrases like "check-in", "log my wellness", "how I'm feeling today", or at the start of a session when no check-in exists yet for today.
---

# check-in

A ~60-second daily wellness capture, persisted as one `Wellness` YAML per
day. All persistence follows `FileStore` conventions
(`athletes/<slug>/logs/wellness/<date>.yaml`) and gets `cli validate`-ed
before committing -- same standing rules as every other skill (CLAUDE.md:
never hand-compute, always validate before commit).

## 1. Capture everything in one exchange if you can

Ask for all of these together, in a single message, rather than one
question at a time -- most athletes will answer all of them in one reply:

- **sleep_quality** (1-5)
- **sleep_hours** (number, e.g. 7.5)
- **stress** (1-5)
- **soreness** (1-5)
- **motivation** (1-5)
- optional: **resting_hr** (bpm, if they have a device), **hrv** (if
  tracked), **notes** (anything else worth flagging)

If they only answer part of it, ask a single tight follow-up for what's
missing rather than re-asking everything.

## 2. Write and validate

Write `athletes/<slug>/logs/wellness/<date>.yaml` (date = today unless the
athlete says otherwise) matching the `Wellness` schema in
`engine/swim_coach/models.py` (`schema_version: 1`, a fresh UUID `id`,
the athlete's `athlete_id`). Then run
`python -m swim_coach.cli validate --athlete <slug>` and fix the YAML
before committing if it fails.

## 3. Check for red flags -- do not modify the plan yourself

If **any** of the following hold for today's entry:
- `sleep_quality <= 2`
- `stress >= 4`
- `soreness >= 4`

...flag it to the athlete plainly (e.g. "your soreness is high today (4/5)
-- you might want to run `/coach` about adjusting today's session before
you head to practice"). Suggest asking `/coach` for a same-day
modification. **Do not adjust the plan, a session's intensity, or
anything in `plan/` yourself** -- that's `/coach`'s / `/adapt`'s job, with
its own engine-backed rules (ROADMAP.md adaptation rules). This skill only
flags and suggests.

## 4. Commit

Wellness logs are athlete data: commit straight to `main` and push
immediately per CLAUDE.md (`git pull` first, imperative lowercase commit
message, then push). **If the push fails** (auth, network, no remote in
this environment), tell the athlete it failed and stop there -- don't
retry endlessly or pretend it succeeded.
