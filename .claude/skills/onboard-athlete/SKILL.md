---
name: onboard-athlete
description: Onboard a new athlete — interview for CSS/pace, pool schedule, HRV device, target event(s) and format, then create their data tree, compute zones, scaffold the macro plan, and generate the first week. Use once per new athlete, at the very start (before any /plan-week, /adapt, /log-workout, or /check-in call makes sense — those all assume an athlete tree already exists).
---

# onboard-athlete

Interview → create the athlete tree → `cli zones --write` → `scaffold-macro`
→ first `/plan-week`. This is the one-time setup every other skill assumes
already happened.

**Never hand-compute CSS, zones, macro volumes, or session numbers in chat**
(CLAUDE.md standing rule) — every number here comes from
`python -m swim_coach.cli`.

## 1. Interview

Ask (conversationally, not as a rigid form — skip what's already obvious
from context):

1. **Slug and name.** A short filesystem-safe slug (`athletes/<slug>/`) and
   a display name.
2. **Pace anchor.** Either:
   - A recent 400m/200m time-trial pair (for `cli zones --test-400 --test-200`
     to derive CSS), or
   - A known CSS pace directly (s/100m), if no fresh test exists — note in
     `notes/decisions.md` that a real CSS test is still owed within the next
     4-6 weeks, and set a re-test cadence (CSS drifts; ROADMAP.md risk #4).
3. **Pool schedule.** Which day(s)/week are coached pool practice, the
   typical duration, and the source (masters/USMS/private coach, etc). Also
   ask: **does the pool coach ever share the session's focus/content in
   advance**, or is it always reactive (handed out after the session)? If
   sometimes-in-advance, note that as an `expected_pool_focus` convention in
   `constraints` so `/plan-week`/`/adapt` know to look for it rather than
   always defaulting to the generic placeholder.
4. **HRV / recovery device.** Oura, Garmin, Whoop, none? This determines
   what `/check-in` can capture (resting HR, HRV) beyond the core subjective
   fields (sleep, stress, soreness, motivation).
5. **Target event(s).** For each: name, date, distance (meters), water
   temp if known, wetsuit-legal or not, priority (A/B/C), and critically
   **`event_format`**:
   - `single_day` — one continuous swim (e.g. a channel/marathon swim). The
     long-swim progression becomes an escalating ladder toward ~60-70% of
     event distance.
   - `multi_day_stage` — a multi-day event with back-to-back long swims
     (e.g. a "4-day option" stage race). The long-swim progression instead
     builds toward back-to-back Saturday+Sunday swims, no single swim above
     ~30-40% of total distance.
   If the athlete is genuinely undecided (a real, common case — format
   choice can hinge on how a training block goes), record both the current
   choice and the switch condition in `constraints`/`notes/decisions.md` —
   `event_format` is a cheap re-scaffold later (`cli scaffold-macro` again
   with the corrected event; see ROADMAP.md "Event format parameter").
6. **Current training volume.** Approximate current weekly swim
   distance (meters) — this becomes `scaffold-macro`'s `--current-volume`
   and anchors the ramp-cap math; also ask about **recent training
   history/interruptions** (injury, illness, layoffs) — this doesn't feed
   the engine directly but belongs in `notes/decisions.md` as context for
   every future `/adapt` judgment call (a "freshly rebuilt" base should bias
   conservative even when the engine's numbers look permissive).

## 2. Create the athlete tree

Write, by hand (these aren't yet CLI-generated — `store.py`'s `FileStore`
just needs valid YAML at the right paths):

- `athletes/<slug>/profile.yaml` — `Athlete` model: `id` (new UUID), `slug`,
  `name`, `constraints` (incl. `expected_pool_focus` if applicable, HRV
  device, training-history notes), `pool_schedule`. Leave
  `css_pace_s_per_100m`/`zones` unset for now — step 3 fills them in via the
  CLI, not by hand.
- `athletes/<slug>/events.yaml` — one `Event` entry per target event,
  including `event_format`.
- `athletes/<slug>/notes/decisions.md` — an initial dated entry recording
  the interview answers and any open questions/decisions (event format
  choice + switch condition, training-history caveats, CSS-test-still-owed
  note, etc).

## 3. Compute zones

```
python -m swim_coach.cli zones --athlete <slug> --write \
  [--test-400 <MM:SS> --test-200 <MM:SS>]
```

Omit `--test-400`/`--test-200` if you already wrote a known
`css_pace_s_per_100m` into `profile.yaml` by hand in step 2 (the CLI will
use the profile's existing value and just write the zone table).

## 4. Scaffold the macro plan

```
python -m swim_coach.cli scaffold-macro --athlete <slug> --event <name-or-id> \
  --current-volume <m/week> [--peak-volume <m/week>]
```

For an athlete with multiple events, scaffold against the nearest A-priority
event first. If the CLI raises a "too few weeks" error, that's real
information — say so plainly (the runway is too short to periodize safely
per `MIN_MACRO_WEEKS`), don't work around it by inventing a shorter
macro by hand.

## 5. Generate the first week

Hand off to `/plan-week` for the macro's first week (its `start_date`).
Don't regenerate the plan-week logic here — this skill's job stops at
having a valid macro; `/plan-week` (or `/adapt` once a first week exists to
react to) owns weekly generation from here on.

## 6. Validate and commit

```
python -m swim_coach.cli validate --athlete <slug>
```

Must exit 0. Then commit **directly to main** and push immediately
(CLAUDE.md: athlete daily data — including a brand-new athlete tree —
commits straight to main, not a feature branch/PR; pull before write).

## If the push fails

**Report the failure and stop — do not loop, retry silently, or
force-push.** The new athlete tree is still on disk locally; tell
Andrew/the athlete what happened and wait for direction.
