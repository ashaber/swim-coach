---
name: log-workout
description: Use when the athlete wants to log a completed workout -- a chat description of what they did, a pasted block of pool-coach workout text, or an uploaded file (.fit/.tcx/.csv). Invoke on phrases like "log my swim", "I just finished practice", "here's what coach gave us today", or when a workout file is attached.
---

# log-workout

Logs one completed workout into `athletes/<slug>/logs/workouts/`. All math
and persistence goes through `python -m swim_coach.cli` -- never hand-compute
distance, pace, or zones in chat (CLAUDE.md standing rule). Always run
`cli validate --athlete <slug>` before committing, and always finish by
trying to match the workout to a planned session in the current ISO week
file.

There are three intake paths. Figure out which one applies from what the
athlete gave you, then follow that path.

## Path A -- chat description ("I swam 3000m easy today, felt like a 5")

1. Ask only for what's missing and load-bearing: date (default today),
   sport (`swim_pool`/`swim_ow`/`strength`/`recovery`), distance_m,
   duration_min (estimate together if only one is known -- do not
   silently invent both), and RPE (1-10) if not given.
2. Do not construct the Workout YAML by hand-computing anything derived
   (pace, etc.) -- pydantic/the CLI owns validation, but you still own
   getting the raw fields right from the athlete's words.
3. Write `athletes/<slug>/logs/workouts/<date>-<sport>-<id[:8]>.yaml`
   directly (id = a fresh UUID you generate), matching the `Workout` schema
   in `engine/swim_coach/models.py` (`schema_version: 1`, `source: manual`).
   There is no `cli log-workout` command -- this path writes YAML directly
   because there's no file/text artifact to hand the CLI.
4. Run `python -m swim_coach.cli validate --athlete <slug>`. If it fails,
   fix the YAML and re-validate -- do not commit an invalid file.

## Path B -- pasted coach text

1. **Save verbatim BEFORE parsing.** This is a hard rule (CLAUDE.md /
   ROADMAP.md): run
   `python -m swim_coach.cli parse-coach-text --athlete <slug> --file <tmp-file-with-the-pasted-text> [--date YYYY-MM-DD]`.
   This single command saves the raw text to
   `athletes/<slug>/logs/coach-texts/<date>.md` and prints the parsed
   result -- it does not create a Workout.
2. Look at `unparsed_lines` in the output. For each one:
   - Ask the athlete conversationally what it means (reps, distance,
     interval/pace, stroke) and build the missing `WorkoutSet` by hand
     from their answer.
   - **Grow the fixture corpus**: append the raw unparsed line as a new
     small fixture file under `tests/unit/fixtures/coach_texts/` (its own
     `.txt`, one notation per file, following the existing fixtures'
     style) so `test_parse_coach_text.py` can be extended to cover it later.
     This is a repo change (not athlete data) -- note it for a follow-up
     engine PR rather than committing it to main directly (see "Committing
     your work" below).
3. Always prompt for RPE (1-10) -- coach text never carries it.
4. Sum `sets` distances (the parser already gives you `total_distance_m`)
   and write the `Workout` YAML directly to
   `athletes/<slug>/logs/workouts/<date>-<sport>-<id[:8]>.yaml` with
   `source: coach_text`, `raw_ref` pointing at the saved coach-text file,
   and `sets` copied from the parse result (plus any you filled in for
   unparsed lines).
5. Run `cli validate --athlete <slug>` before committing.

## Path C -- uploaded file (.fit/.tcx/.csv)

1. Run
   `python -m swim_coach.cli ingest --athlete <slug> --file <path> [--date ...] [--rpe N] [--sport ...] --save`.
   This parses by extension, fills id/athlete_id, and persists the
   `Workout` directly -- there's no separate YAML-writing step.
2. Read the printed draft's `warnings` list out loud to the athlete if
   it's non-empty (unit assumptions, defaulted dates/sport, missing
   columns) -- these are exactly the cases the parser couldn't resolve on
   its own.
3. If RPE wasn't passed and the file format doesn't carry one (none of
   .fit/.tcx/.csv do), ask for it, then re-run with `--rpe` (or `--force`
   an update by re-running `ingest --save` for the same date/sport --
   `FileStore.save_workout` keys files by workout id, so simplest is to
   ask before the first `--save` if at all possible).
4. Run `cli validate --athlete <slug>` before committing regardless.

## Always: match a planned session

After any path succeeds, look for a `Session` in the current ISO week's
`athletes/<slug>/plan/weeks/<iso_week>.yaml` with the same `date` and
`sport` as the just-logged workout, `status: planned`. If found:
- Set the new `Workout.planned_session_id` to that `Session.id`.
- Edit the week file to set that `Session.status` to `completed`.
- Re-run `cli validate --athlete <slug>` after editing the week file too.

If no matching planned session exists (e.g. an unplanned extra swim, or a
pool-coach session logged before `plan-week` ever ran for that week),
that's fine -- leave `planned_session_id` unset and say so.

## Committing your work

Athlete data (the new workout YAML, and the week file if you updated a
session's status) commits straight to `main` and pushes immediately per
CLAUDE.md -- `git pull` first, then commit with an imperative lowercase
message, then push. **If push fails** (auth, network, no remote in this
environment), report the failure to the athlete plainly and stop -- do
not retry in a loop or silently leave it uncommitted without saying so.

A new coach-text fixture file (Path B) is a change to `tests/`, not
athlete data -- do not push it to main as part of this flow; mention it so
it can be picked up in the engine's normal feature-branch workflow.
