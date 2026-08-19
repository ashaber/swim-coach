"""Tool schemas + handlers for the coach chat tool loop.

This is what makes chat "a primary caller of /adapt" (per this build's
brief): `propose_adaptation` calls `swim_coach.adapt.adapt_week` directly --
the same function `cli.py`'s `adapt` command and the `/adapt` skill call --
and returns the draft for discussion without persisting it. `get_plan_summary`
reuses `context.summarize_rollup` (itself a thin reassembly of `load.py`'s
functions). `log_open_question` implements IDEA 005, persisting through the
durable `store.save_feedback` seam (engine/swim_coach/models.Feedback)
instead of the old ephemeral `research/open-questions.jsonl` file, which was
silently wiped every time Cloud Run scaled to zero.

`create_event`/`draft_macro_plan`/`create_week_plan` are the "chat can create,
not just adapt" tools: they call the exact same deterministic engine
functions the CLI/skills already use (`swim_coach.plan.scaffold_macro`,
`swim_coach.plan.generate_week`) and persist their output directly, rather
than drafting. This is intentionally different from `propose_adaptation`'s
draft-only contract -- these three only ever create content that doesn't
exist yet (a new event, a first macro for an event, a missing week), so
there's nothing already-active for a bad call to disrupt. Adapting an
already-active week stays `propose_adaptation`'s job, unchanged: a human
still confirms via `/adapt` before an active week's volume changes.

`replace_macro_plan` handles the opposite case from `draft_macro_plan`: a
macro that already exists (for the resolved event or a different one), the
target event changing, or an existing macro that's broken/unusable (e.g. an
all-zero-volume macro from the since-fixed zero-current-volume ramp-cap bug
in `swim_coach.plan.scaffold_macro`). Because replacing an already-active
macro can invalidate training the athlete has already done against it, this
tool follows `propose_adaptation`'s draft-then-confirm shape rather than
`draft_macro_plan`'s direct-persist one: `confirm=False` (default) only
computes and returns the candidate, `confirm=True` persists.

`set_pool_coach_status` flips `Athlete.has_pool_coach` (Part 3: no real
masters coach on hand means `swim_coach.plan.generate_week` must author real
pool-session content instead of a `pool_coach` placeholder). Low-risk status
flag, not a plan/volume change, so -- like `create_event` -- it persists
directly, no draft/confirm step.

`reschedule_session` moves one already-planned `Session`'s `date` within the
same ISO week (e.g. a Wednesday swim moved to Thursday for a scheduling
conflict) -- everything else about the session is untouched, and it has no
volume/training-load/safety-rail interaction at all, which is exactly why it
persists directly rather than going through `propose_adaptation`'s
draft-then-confirm shape: unlike an adaptation, there's no rule-table
recompute for a bad call to have gotten wrong.

`replace_week_plan` closes a real structural dead end: `create_week_plan`
refuses if iso_week already has a week on file ("use propose_adaptation
instead"), and `propose_adaptation` refuses if there's no valid prior week to
adapt from. When BOTH are true -- an existing week needs regenerating (e.g.
`has_pool_coach` just changed, or the week was built under a stale/replaced
macro) and there's no valid prior week to adapt from -- neither tool can
touch it. `replace_week_plan` is the same shape as `replace_macro_plan`: it
calls `swim_coach.plan.generate_week` (the same engine function
`create_week_plan` uses) with NO guard against an existing week -- that's
exactly its purpose -- and follows draft-then-confirm rather than
direct-persist, since overwriting an already-active week can invalidate
training the athlete has already done against it: `confirm=False` (default)
only computes and returns the candidate (plus a comparison against whatever
week is currently on file for that iso_week, if any) as JSON with
`"persisted": false`, never calling `store.save_week`; `confirm=True`
recomputes identically (generate_week is a pure function of its inputs, so
this is safe to re-run) and persists, overwriting whatever was there.

`set_event_active_status` is a soft delete/reactivate for an `Event`: flips
`Event.active` (default `True`, purely additive) so a cancelled event can be
archived from conversation without removing it from `events.yaml` -- a
macro's `event_id` can still reference an event after the athlete has moved
on, and hard-deleting risks orphaning that reference. Deliberately NOT a
hard delete, and deliberately reactivatable: `active=False` then
`active=True` again round-trips cleanly. Like `set_pool_coach_status`, this
is a low-risk status flag, not a plan/volume change, so it persists directly
via `store.save_events` (the whole list, matching that store method's
replace-the-list contract) -- no draft/confirm step. Existing event-by-id
lookups elsewhere in this file (`draft_macro_plan`/`replace_macro_plan`/
`propose_adaptation`) deliberately do NOT filter by `active` -- an inactive
event must still resolve if the athlete reactivates it or an old macro still
references it historically. `active` only changes how the model *talks
about* events in conversation (see PERSONA_AND_RULES), never which events
existing engine/tool lookups can find.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from pydantic import ValidationError

from swim_coach.adapt import adapt_week
from swim_coach.models import Event, Feedback, Workout, WorkoutStructure
from swim_coach.plan import _duration_min_for_distance, generate_week, scaffold_macro
from swim_coach.store import StoreInterface
from swim_coach.workout_templates import TemplatePreference

from app.context import iso_week_str, summarize_rollup
from app.logging_config import get_logger
from app.sync import ON_DEMAND_SYNC_WINDOW_DAYS, sync_on_demand

log = get_logger(__name__)

ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]

# get_workouts caps how many sessions it returns to the coach in one call --
# a broad date range on a long-tenured athlete could otherwise dump hundreds
# of full-ish workout summaries into the (uncached, per-turn) tool-result
# context. Matches the PWA history list's own display cap
# (web/src/workouts.js's HISTORY_DISPLAY_CAP).
GET_WORKOUTS_CAP = 20

# sync_workouts uses the same small on-demand window as the PWA Log tab's
# "Sync from watch" button (POST /api/workouts/sync) -- see
# app.sync.ON_DEMAND_SYNC_WINDOW_DAYS's docstring for why. Re-exported under
# this name for backward compatibility (existing tests import it from here).
SYNC_WORKOUTS_WINDOW_DAYS = ON_DEMAND_SYNC_WINDOW_DAYS

# Shared `template_preference` schema for `create_week_plan`/`replace_week_plan`
# (see `_parse_template_preference` below) -- the tool-facing surface for
# `swim_coach.workout_templates.find_templates`/`TemplatePreference`, letting
# the coach honor a request like "more kettlebell work" or "give me a
# threshold set" instead of only ever getting whatever `generate_week`'s
# normally-blind selector%count rotation lands on. Deliberately mirrors
# `TemplatePreference`'s own three fields exactly (not `find_templates`'
# full signature) -- `modality`/`block`/`max_duration_s` don't make sense as
# a model-facing dial here (see `TemplatePreference`'s docstring).
TEMPLATE_PREFERENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "Narrows which workout-library template generate_week's "
        "pool-independent swim sessions use this week. Omit entirely for "
        "the normal default rotation."
    ),
    "properties": {
        "purpose": {
            "type": "string",
            "description": (
                "One of WorkoutTemplate.purpose's values: 'aerobic_base', "
                "'threshold', 'race_pace', 'technique', 'sprint_power', "
                "'recovery', 'strength_endurance', 'max_strength', "
                "'posterior_chain'."
            ),
        },
        "equipment_any": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Match a template using ANY of these equipment items, e.g. "
                "['kettlebell', 'paddles', 'fins']. Note: no shipped swim "
                "main-set template uses structured equipment tagging yet as "
                "of this pass -- this filter is real and tested, but will "
                "currently match nothing for swim sessions until such "
                "templates exist."
            ),
        },
        "interval_style": {
            "type": "string",
            "description": (
                "One of TemplateFacets.interval_style's values: 'straight', "
                "'intervals', 'emom', 'amrap'."
            ),
        },
    },
    "additionalProperties": False,
}

TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "name": "propose_adaptation",
        "description": (
            "Run the deterministic adaptation engine's draft for the given ISO "
            "week (e.g. '2026-W30') and return the draft WeekPlan + machine "
            "rationale as JSON, for discussion with the athlete. Does NOT "
            "persist anything -- only /adapt, with explicit confirmation, "
            "writes a plan change. Requires an existing, non-draft week plan "
            "for the week immediately before iso_week to adapt from."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "iso_week": {
                    "type": "string",
                    "description": "ISO week to draft, formatted 'YYYY-Wnn', e.g. '2026-W30'.",
                }
            },
            "required": ["iso_week"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_plan_summary",
        "description": (
            "Return the engine's compact training-load/wellness/compliance "
            "rollup over the trailing N weeks (volume by week, sRPE load by "
            "day, 7d:28d load ratio, monotony, wellness trend, compliance %)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "weeks": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 12,
                    "description": "Number of trailing weeks to summarize (default 4).",
                }
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "log_open_question",
        "description": (
            "Log a question the research library doesn't support an answer "
            "for, so it can be researched and followed up on later. Call this "
            "whenever you have to say \"I don't know\" because of a library "
            "gap -- for both athlete questions and, in expert mode, a "
            "professional coach/physiologist's proposed correction or "
            "addition the library doesn't yet cover."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The question, verbatim."},
                "topic": {
                    "type": "string",
                    "description": "Short topic label, e.g. 'nutrition', 'taper', 'HRV'.",
                },
            },
            "required": ["question", "topic"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_workouts",
        "description": (
            "Fetch logged workouts for a date range OLDER than what's already "
            "in context -- the per-request context above only includes the "
            "trailing ~28 days of exact sessions, so call this when the "
            "athlete asks about a specific past workout or date range outside "
            "that window (e.g. \"what did I do in January?\"). Do NOT call "
            "this for recent sessions -- they're already in context. Results "
            f"are capped at {GET_WORKOUTS_CAP} workouts (sorted oldest-first "
            "within the range; check `truncated` and narrow the range if "
            "true). Each result is a compact summary (distance, duration, "
            "pace, RPE, HR, analytics, and lap/length/pause counts) -- not "
            "the full per-lap/per-length telemetry."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start of the date range, 'YYYY-MM-DD'.",
                },
                "end_date": {
                    "type": "string",
                    "description": (
                        "End of the date range (inclusive), 'YYYY-MM-DD'. "
                        "Omit for a single-day query -- defaults to start_date."
                    ),
                },
            },
            "required": ["start_date"],
            "additionalProperties": False,
        },
    },
    {
        "name": "sync_workouts",
        "description": (
            "Trigger an on-demand intervals.icu sync for the athlete you're "
            "talking to RIGHT NOW -- call this when the athlete says they "
            "just finished a workout, or explicitly asks you to sync/pull it "
            "in, instead of waiting for the scheduled sync job to catch it "
            "later. Pulls only a small trailing window (today and "
            "yesterday) of THIS athlete's own intervals.icu activities -- "
            "never some other athlete's, and never a substitute for a full "
            "history backfill. Do NOT call this for anything other than a "
            "just-finished or very recent session; older workouts are the "
            "scheduled job's job. This tool's own return value is only "
            "counts (how many activities were listed/new/saved/failed) -- "
            "it does NOT describe the synced workout itself. After calling "
            "it, if `saved` > 0, follow up with get_workouts (or the "
            "per-request context, if today falls inside it) to actually see "
            "what came in before describing it to the athlete."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_event",
        "description": (
            "Add a brand-new target event (a race or channel swim) to the "
            "athlete's events list. Use when the athlete describes a new "
            "event to train toward that isn't already on file -- this is "
            "just metadata about a future goal, so unlike a plan change it "
            "persists immediately (nothing existing to disrupt)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Event name."},
                "event_date": {
                    "type": "string",
                    "description": "Event date, formatted 'YYYY-MM-DD'.",
                },
                "distance_m": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Event distance in meters.",
                },
                "priority": {
                    "type": "string",
                    "description": "Event priority, e.g. 'A' or 'B'.",
                },
                "water_temp_c": {
                    "type": "number",
                    "description": "Expected water temperature in Celsius (optional).",
                },
                "wetsuit": {
                    "type": "boolean",
                    "description": "Whether a wetsuit will be worn (default false).",
                },
                "event_format": {
                    "type": "string",
                    "enum": ["single_day", "multi_day_stage"],
                    "description": (
                        "'single_day' (one continuous swim) or 'multi_day_stage' "
                        "(split across stage days). Default 'single_day'."
                    ),
                },
            },
            "required": ["name", "event_date", "distance_m", "priority"],
            "additionalProperties": False,
        },
    },
    {
        "name": "draft_macro_plan",
        "description": (
            "Scaffold a brand-new base->build->peak->taper macro periodization "
            "plan toward an existing event, calling the exact same "
            "swim_coach.plan.scaffold_macro function the CLI's scaffold-macro "
            "command and /onboard-athlete use -- the 8%/week ramp cap and "
            "taper/peak sizing are enforced inside that function, which is "
            "why a brand-new macro is safe to persist immediately. Use when "
            "the athlete has an event on file but no macro plan for it yet. "
            "Refuses with an error if a macro plan already exists for that "
            "event -- this tool is only for a brand-new macro; use "
            "replace_macro_plan (draft-then-confirm) to revise or replace "
            "an existing one instead."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "event_name": {
                    "type": "string",
                    "description": "Name of an existing event (must match exactly).",
                },
                "current_weekly_volume_m": {
                    "type": "integer",
                    "description": "The athlete's current real weekly swim volume in meters.",
                },
                "peak_weekly_volume_m": {
                    "type": "integer",
                    "description": (
                        "Optional target peak weekly volume in meters. Defaults "
                        "to event distance x 2.5, clamped by the ramp cap over "
                        "the base+build weeks."
                    ),
                },
                "start_date": {
                    "type": "string",
                    "description": "Macro start date, 'YYYY-MM-DD' (default today).",
                },
            },
            "required": ["event_name", "current_weekly_volume_m"],
            "additionalProperties": False,
        },
    },
    {
        "name": "replace_macro_plan",
        "description": (
            "Replace the athlete's macro periodization plan by recomputing "
            "swim_coach.plan.scaffold_macro -- the same engine function "
            "draft_macro_plan uses. Unlike draft_macro_plan, this tool NEVER "
            "refuses because a macro already exists -- that's exactly its "
            "purpose: use it for the case draft_macro_plan's own error "
            "message points at -- an existing macro for the resolved event, "
            "the athlete changing target event, or an existing macro that's "
            "broken/unusable (e.g. an all-zero-volume macro from the "
            "since-fixed zero-current-volume ramp-cap bug). This can "
            "invalidate an already-trained-against macro, so -- like "
            "propose_adaptation -- it is draft-then-confirm, NOT "
            "direct-persist: `confirm` defaults to false, which only "
            "computes and returns the candidate replacement (plus a "
            "comparison against the athlete's current macro, if one exists: "
            "old vs. new target event, old vs. new peak weekly volume) as "
            "JSON with `\"persisted\": false` -- it does NOT call "
            "save_macro. Show this draft to the athlete and get their "
            "explicit agreement before calling this tool again with "
            "`confirm: true` -- only then does it persist "
            "(store.save_macro), overwriting the athlete's active macro "
            "plan. Never pass confirm=true on the first call for a given "
            "request."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "event_name": {
                    "type": "string",
                    "description": "Name of an existing event (must match exactly).",
                },
                "current_weekly_volume_m": {
                    "type": "integer",
                    "description": "The athlete's current real weekly swim volume in meters.",
                },
                "peak_weekly_volume_m": {
                    "type": "integer",
                    "description": (
                        "Optional target peak weekly volume in meters. Defaults "
                        "to event distance x 2.5, clamped by the ramp cap over "
                        "the base+build weeks."
                    ),
                },
                "start_date": {
                    "type": "string",
                    "description": "Macro start date, 'YYYY-MM-DD' (default today).",
                },
                "confirm": {
                    "type": "boolean",
                    "description": (
                        "Default false: compute and return the candidate "
                        "replacement macro as a draft only, never persisting. "
                        "Set true ONLY after the athlete has explicitly agreed "
                        "to the draft shown in a prior turn -- this then "
                        "persists via store.save_macro, overwriting the "
                        "athlete's current macro plan."
                    ),
                },
            },
            "required": ["event_name", "current_weekly_volume_m"],
            "additionalProperties": False,
        },
    },
    {
        "name": "set_pool_coach_status",
        "description": (
            "Set whether the athlete currently has a real masters/pool coach "
            "handing out pool-day workout content, vs. needing the AI coach "
            "to author real pool-session structure itself. Persists "
            "immediately -- a low-risk status flag, not a plan/volume "
            "change, so no draft/confirm step is needed. Use when the "
            "athlete says they've started or stopped working with a pool "
            "coach. Affects future generate_week/create_week_plan output "
            "only -- it does not retroactively change already-generated "
            "weeks."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "has_pool_coach": {
                    "type": "boolean",
                    "description": (
                        "True if a real masters/pool coach hands out this "
                        "athlete's pool-day workouts; false if there is no "
                        "such coach and the AI coach should author real "
                        "pool-session structure instead."
                    ),
                }
            },
            "required": ["has_pool_coach"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_week_plan",
        "description": (
            "Generate and persist one brand-new WeekPlan from the athlete's "
            "existing macro plan, via swim_coach.plan.generate_week -- the "
            "same function /plan-week uses (pool-coach placeholders + a "
            "weekend long open-water swim). Use when iso_week has no week "
            "plan at all yet (e.g. filling a gap so propose_adaptation has "
            "something to adapt from next). Refuses with an error if a week "
            "plan already exists for iso_week -- use propose_adaptation (and "
            "the /adapt skill's human confirmation) to change an existing "
            "week instead. Not the right tool for a week that needs "
            "hand-authored content (no pool coach on hand, real open-water "
            "session structure needed) -- that's judgment-authored, not "
            "generated.\n\n"
            "`template_preference` (optional): honors a request like 'give "
            "me more kettlebell work this week' or 'I want a threshold set' "
            "by narrowing which main-set workout-library template the "
            "generated week's pool-independent swim sessions use, instead "
            "of always landing on whatever the normal deterministic "
            "rotation picks. Fails with a clear error (rather than silently "
            "falling back to the default rotation) if the preference "
            "matches zero library templates for some session's macro block."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "iso_week": {
                    "type": "string",
                    "description": "ISO week to create, formatted 'YYYY-Wnn', e.g. '2026-W30'.",
                },
                "template_preference": TEMPLATE_PREFERENCE_SCHEMA,
            },
            "required": ["iso_week"],
            "additionalProperties": False,
        },
    },
    {
        "name": "reschedule_session",
        "description": (
            "Move an already-planned session to a different day within the "
            "same week -- e.g. the athlete has a scheduling conflict (a "
            "meeting, travel) and needs to move a Wednesday session to "
            "Thursday. Changes only that one session's date -- sport, "
            "distance, duration, intensity, structure, and purpose all stay "
            "exactly as planned. This is a low-risk, single-field edit with "
            "no volume/training-load/safety-rail interaction at all (unlike "
            "propose_adaptation, which recomputes an entire week's volume "
            "via the rule table -- the wrong tool for a simple day move), so "
            "it persists immediately, no draft/confirm step. Only moves a "
            "session within iso_week's own Monday-Sunday span -- refuses "
            "and points at propose_adaptation instead if new_date falls in "
            "a different week, since that's a real schedule/volume "
            "decision, not a same-week day swap."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "iso_week": {
                    "type": "string",
                    "description": "ISO week the session belongs to, formatted 'YYYY-Wnn', e.g. '2026-W30'.",
                },
                "current_date": {
                    "type": "string",
                    "description": "The session's date as currently planned, 'YYYY-MM-DD'.",
                },
                "sport": {
                    "type": "string",
                    "description": (
                        "The session's sport (e.g. 'swim_pool', 'swim_ow', "
                        "'strength', 'recovery') -- disambiguates same-day "
                        "sessions, since a day can have more than one (e.g. "
                        "both a swim and a strength session)."
                    ),
                },
                "new_date": {
                    "type": "string",
                    "description": (
                        "The date to move the session to, 'YYYY-MM-DD' -- "
                        "must fall within the same ISO week as current_date."
                    ),
                },
            },
            "required": ["iso_week", "current_date", "sport", "new_date"],
            "additionalProperties": False,
        },
    },
    {
        "name": "replace_week_plan",
        "description": (
            "Replace one week's plan by recomputing swim_coach.plan.generate_week "
            "-- the same engine function create_week_plan uses. Unlike "
            "create_week_plan, this tool NEVER refuses because a week already "
            "exists for iso_week -- that's exactly its purpose: use it for the "
            "structural dead end where create_week_plan refuses ('use "
            "propose_adaptation instead') AND propose_adaptation also refuses "
            "(no valid prior week to adapt from) -- e.g. the athlete's "
            "has_pool_coach status just changed and the existing week still "
            "has stale placeholder sessions, or the week was built under a "
            "stale/since-replaced macro. This can invalidate an "
            "already-trained-against week, so -- like replace_macro_plan -- it "
            "is draft-then-confirm, NOT direct-persist: `confirm` defaults to "
            "false, which only computes and returns the candidate replacement "
            "(plus a comparison against whatever week is currently on file for "
            "iso_week, if any: old vs. new target_volume_m, old vs. new "
            "session count) as JSON with `\"persisted\": false` -- it does NOT "
            "call save_week. Show this draft to the athlete and get their "
            "explicit agreement before calling this tool again with "
            "`confirm: true` -- only then does it persist (store.save_week), "
            "overwriting whatever week plan is currently on file for iso_week. "
            "Never pass confirm=true on the first call for a given request, "
            "and never chain another tool call in the same response after the "
            "draft -- stop and wait for the athlete's explicit agreement in a "
            "new message, same discipline as replace_macro_plan.\n\n"
            "`session_overrides` (optional): use this to set one or more "
            "sessions' distance_m/duration_min/purpose/structure directly, "
            "applied on top of the otherwise-normal generated week, still "
            "fully gated by the same draft-then-confirm flow -- never call "
            "with confirm=true and a fresh override in the same turn the "
            "athlete hasn't seen yet. Two distinct real uses:\n"
            "  - distance_m/duration_min: the automatic ramp/volume math "
            "won't always land on the exact number an athlete explicitly "
            "wants -- e.g. a conservative first swim back after time off, "
            "where the computed distance is technically ramp-safe but still "
            "more than the athlete wants right now.\n"
            "  - purpose/structure/structured: when the athlete wants a "
            "specific session's actual CONTENT changed (a technique/drill "
            "focus, a specific interval structure, a strength session with "
            "exercises the canned library list doesn't cover) and no "
            "`template_preference` value matches anything in the library "
            "for that macro block -- write the session's real content "
            "yourself (same as you'd describe verbally) rather than only "
            "describing the workout in your chat reply with nowhere for it "
            "to actually live. This is exactly how to unblock a request "
            "like 'give me a technique session Thursday' when the template "
            "library has no technique-purpose entry for that block yet, or "
            "'give me a kettlebell/goblet-squat strength day' when those "
            "exercises aren't in the canned strength list -- don't just "
            "explain the gap and stop, author the content and persist it "
            "here. Two ways to author it, and prefer supplying BOTH "
            "together whenever the workout has real step/rep/exercise "
            "structure (they describe the same session, one for each "
            "audience -- there is nothing to reconcile between them, "
            "neither is derived from the other):\n"
            "    - `structured`: the machine-readable WorkoutStructure IR "
            "-- an ordered list of steps and/or repeat blocks. This is "
            "what renders as the step-by-step tree in the athlete's app "
            "Plan tab and what exports to a Garmin watch as a real "
            "lap-advancing workout (warm-up/interval/rest/cool-down laps, "
            "or strength sets/reps). It is NOT limited to whatever "
            "exercises `engine/swim_coach/plan.py`'s canned strength list "
            "happens to contain -- author any exercise/step directly here, "
            "same as you would in prose. Prefer this whenever the session "
            "has real structure to describe, which is most of the time.\n"
            "    - `structure`: athlete-facing prose -- author real "
            "content here (warm-up/main set/cool-down or whatever shape "
            "fits) exactly as you'd describe it in chat. Supply this "
            "alongside `structured` as the human-readable narration of the "
            "same session whenever you're setting `structured` anyway -- "
            "it costs nothing and reads better in the app than a bare step "
            "list.\n"
            "  Setting `structure` WITHOUT also setting `structured` in "
            "the same entry clears that session's existing `structured` "
            "field (if any) -- this is a deliberate choice, not a side "
            "effect, meaning 'this session is genuinely prose-only, there "
            "is no real step structure to capture'; the cost is that the "
            "athlete's Plan tab tree view and any Garmin export will have "
            "nothing to render/export for this session until it's later "
            "given real `structured` content. Setting BOTH `structure` and "
            "`structured` together in the same entry persists both -- "
            "neither clears the other.\n\n"
            "`template_preference` (optional): honors a request like 'give "
            "me more kettlebell work this week' or 'I want a threshold set' "
            "by narrowing which main-set workout-library template the "
            "recomputed week's pool-independent swim sessions use, instead "
            "of always landing on whatever the normal deterministic "
            "rotation picks. Fails with a clear error (rather than silently "
            "falling back to the default rotation) if the preference "
            "matches zero library templates for some session's macro block."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "iso_week": {
                    "type": "string",
                    "description": "ISO week to replace, formatted 'YYYY-Wnn', e.g. '2026-W30'.",
                },
                "confirm": {
                    "type": "boolean",
                    "description": (
                        "Default false: compute and return the candidate "
                        "replacement week as a draft only, never persisting. "
                        "Set true ONLY after the athlete has explicitly agreed "
                        "to the draft shown in a prior turn -- this then "
                        "persists via store.save_week, overwriting whatever "
                        "week plan is currently on file for iso_week."
                    ),
                },
                "session_overrides": {
                    "type": "array",
                    "description": (
                        "Optional explicit overrides applied to the generated "
                        "week's sessions before it's returned/persisted. Each "
                        "entry must match exactly one session already in the "
                        "generated week (by date, and by sport too if more "
                        "than one session falls on that date) -- an entry "
                        "matching zero or more than one session is an error, "
                        "not a silent no-op or a guess."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "date": {
                                "type": "string",
                                "description": "Session date, 'YYYY-MM-DD', must fall within iso_week.",
                            },
                            "sport": {
                                "type": "string",
                                "description": (
                                    "Disambiguates when more than one session falls on "
                                    "`date`. Omit if only one session that day."
                                ),
                            },
                            "distance_m": {
                                "type": "number",
                                "description": "New distance for this session, in meters.",
                            },
                            "duration_min": {
                                "type": "number",
                                "description": (
                                    "New duration for this session, in minutes. Optional -- "
                                    "if omitted while distance_m is given, duration is "
                                    "re-estimated from the new distance at the athlete's pace, "
                                    "same math the engine itself uses."
                                ),
                            },
                            "purpose": {
                                "type": "string",
                                "description": (
                                    "New purpose/description for this session, athlete-facing "
                                    "(e.g. 'Technique -- freestyle catch and rotation drills')."
                                ),
                            },
                            "structure": {
                                "type": "string",
                                "description": (
                                    "New full session instructions, athlete-facing prose -- "
                                    "author real content here (warm-up/main set/cool-down or "
                                    "whatever shape fits) exactly as you'd describe it in chat, "
                                    "when no library template covers what the athlete asked "
                                    "for. Prefer also supplying `structured` alongside this in "
                                    "the same entry (they describe the same session; neither "
                                    "clears the other when both are set) -- setting `structure` "
                                    "WITHOUT `structured` clears the session's existing "
                                    "structured workout data (see this parameter's parent "
                                    "description), a deliberate 'prose only, no watch export' "
                                    "choice, not a side effect. REQUIRES `distance_m` in this "
                                    "same entry, set to the real total implied by what you just "
                                    "wrote (e.g. warm-up + main set + cool-down summed) -- "
                                    "`distance_m` is a separate field with nothing keeping it "
                                    "in sync with `structure`'s prose automatically; do the "
                                    "arithmetic yourself and pass the matching number, or the "
                                    "athlete sees a distance stat that contradicts the workout "
                                    "you just wrote."
                                ),
                            },
                            "structured": {
                                "type": "object",
                                "description": (
                                    "New machine-readable WorkoutStructure IR for this session "
                                    "-- the canonical structured workout tree that renders as "
                                    "the step-by-step tree in the athlete's app Plan tab and "
                                    "exports to a Garmin watch as a real lap-advancing workout. "
                                    "Prefer setting this whenever the session has real step/"
                                    "rep/exercise structure (most of the time), and supply "
                                    "`structure` alongside it as the matching athlete-facing "
                                    "prose narration -- setting both persists both, neither "
                                    "clears the other. Shape: `{\"items\": [...]}` where each "
                                    "item is either a step -- `{\"kind\": \"step\", \"label\": "
                                    "str, \"role\": \"warmup\"|\"steady\"|\"interval\"|\"rest\"|"
                                    "\"recovery\"|\"cooldown\"|\"open\", \"duration_kind\": "
                                    "\"time_s\"|\"distance_m\"|\"reps\"|\"open\", "
                                    "\"duration_value\": number, \"modality\": \"swim\"|"
                                    "\"strength\" (default \"swim\"), and for swim steps "
                                    "optionally \"stroke\"/\"equipment\" plus a \"target\": "
                                    "{\"basis\": \"zone\"|\"percent_css\"|\"absolute\"|\"rpe\"|"
                                    "\"open\", \"zone\": \"Z1\"-\"Z5\"|null, \"low\": number|"
                                    "null, \"high\": number|null}, or for strength steps "
                                    "optionally \"exercise_name\" plus a \"load\": {\"basis\": "
                                    "\"bodyweight\"|\"percent_1rm\"|\"absolute\"|\"rpe_only\", "
                                    "\"value\": number|null}, and optionally \"reference_url\": "
                                    "str|null on ANY step, swim or strength alike -- a "
                                    "technique/demo link, shown to the athlete as a tappable "
                                    "link on that step and written into the exported Garmin FIT "
                                    "step's notes. It must be a plain http(s) URL; anything else "
                                    "is dropped at render time. Omit it for a step with no such "
                                    "link` -- or a repeat block -- "
                                    "`{\"kind\": \"repeat\", \"repeat_mode\": \"count\"|"
                                    "\"for_duration\"|\"amrap\", \"count\": int|null, "
                                    "\"duration_s\": number|null, \"interval_s\": number|null, "
                                    "\"steps\": [...]}` whose own `steps` list holds more items "
                                    "of either kind (steps or nested repeats -- nesting deeper "
                                    "than one level is allowed but rarely needed in practice). "
                                    "This is NOT limited to whatever exercises the canned "
                                    "strength list in `engine/swim_coach/plan.py` happens to "
                                    "contain -- author any exercise/step directly, same as you "
                                    "would in prose. An invalid payload (wrong `kind`, missing "
                                    "required field, etc.) is rejected with a clear error and "
                                    "nothing is persisted -- fix and retry with a valid payload "
                                    "rather than falling back to prose-only `structure`."
                                ),
                            },
                        },
                        "required": ["date"],
                        "additionalProperties": False,
                    },
                },
                "template_preference": TEMPLATE_PREFERENCE_SCHEMA,
            },
            "required": ["iso_week"],
            "additionalProperties": False,
        },
    },
    {
        "name": "set_event_active_status",
        "description": (
            "Soft delete/reactivate an event: set active=false to archive an "
            "event that's no longer happening (cancelled, athlete changed "
            "their mind), or active=true to reactivate one later. This is "
            "deliberately NOT a hard delete -- a macro's event_id can still "
            "reference an event after the athlete has moved on, and "
            "hard-deleting risks orphaning that reference. Persists "
            "immediately -- a status flag, not a plan/volume change, so no "
            "draft/confirm step is needed. Treat active=false events as "
            "archived in conversation: don't suggest or reference them as "
            "live targets unless the athlete specifically asks about that "
            "event by name. Does not affect draft_macro_plan/"
            "replace_macro_plan/propose_adaptation's own event lookups -- "
            "those still resolve an inactive event correctly by name/id if "
            "the athlete wants to build or rebuild a macro toward it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "event_name": {
                    "type": "string",
                    "description": "Name of an existing event (must match exactly).",
                },
                "active": {
                    "type": "boolean",
                    "description": (
                        "False to archive/deactivate the event (cancelled or "
                        "no longer a target); true to reactivate it."
                    ),
                },
            },
            "required": ["event_name", "active"],
            "additionalProperties": False,
        },
    },
]


def _handle_propose_adaptation(input_data: dict[str, Any], *, store: StoreInterface, slug: str) -> dict[str, Any]:
    iso_week = input_data.get("iso_week")
    if not iso_week:
        return {"error": "iso_week is required"}

    try:
        year_str, week_str = iso_week.split("-W")
        week_start = date.fromisocalendar(int(year_str), int(week_str), 1)
    except (ValueError, IndexError):
        return {"error": f"invalid iso_week {iso_week!r}; expected format 'YYYY-Wnn'"}

    try:
        athlete = store.load_athlete(slug)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"could not load athlete profile: {exc}"}

    try:
        macro = store.load_macro(slug)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"could not load macro plan: {exc}"}
    if macro is None:
        return {"error": "no macro plan for this athlete; run scaffold-macro first"}

    try:
        events = store.load_events(slug)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"could not load events: {exc}"}
    event = next((e for e in events if e.id == macro.event_id), None)
    if event is None:
        return {"error": f"macro's event_id {macro.event_id} not found in events.yaml"}

    current_week_start = week_start - timedelta(days=7)
    current_iso = iso_week_str(current_week_start)
    current_week = store.load_week(slug, current_iso)
    if current_week is None:
        return {
            "error": (
                f"no existing week plan for {current_iso!r} (the week before "
                f"{iso_week!r}) to adapt from"
            )
        }

    # current_week loaded successfully, but that alone doesn't mean it's a
    # valid adaptation baseline -- after replace_macro_plan moves the macro
    # to a new event with a different (later) start date, the OLD week
    # plans from before that start date are still sitting on disk. Without
    # this check, they'd get silently adapted from as if still active,
    # producing a draft that repeats a stale, since-replaced macro's target
    # (confirmed in a live transcript). Same two-line range check
    # plan.py's _find_block uses (block.start_date <= week_start <=
    # block.end_date), applied across the macro's overall span rather than
    # one block, since current_week_start just needs to fall somewhere
    # inside the current macro, not in any particular block.
    macro_start = macro.blocks[0].start_date
    macro_end = macro.blocks[-1].end_date
    if current_week_start < macro_start:
        return {
            "error": (
                f"the week before {iso_week!r} ({current_iso!r}) predates the "
                f"current macro (which starts {macro_start}) -- "
                "expected right after a macro replacement or a fresh start, not a "
                f"gap. Use create_week_plan for {iso_week!r} instead, since it's "
                "effectively the first week of the current plan."
            )
        }
    if current_week_start > macro_end:
        # Distinct from the predates-start case above: here iso_week itself
        # (not just the prior week) is also beyond macro_end, since
        # current_week_start is iso_week's own week_start minus 7 days --
        # create_week_plan would refuse for the same reason (it checks the
        # same macro range), so pointing at it here would just trade one
        # dead end for another. The real fix is a new macro for whatever
        # comes next.
        return {
            "error": (
                f"the week before {iso_week!r} ({current_iso!r}) falls after "
                f"the current macro ends ({macro_end}) -- {iso_week!r} is "
                "beyond this macro's plan entirely, not a gap within it. "
                "Build a new macro (draft_macro_plan or replace_macro_plan) "
                "for whatever comes next, then create_week_plan for its "
                "first week."
            )
        }

    workouts = store.list_workouts(slug)
    wellness = store.list_wellness(slug)
    as_of = week_start - timedelta(days=1)

    try:
        draft = adapt_week(
            athlete, event, macro, iso_week, week_start, current_week, workouts, wellness, as_of
        )
    except ValueError as exc:
        return {"error": str(exc)}

    return {
        "iso_week": draft.iso_week,
        "draft": draft.draft,
        "meso_block": draft.meso_block,
        "focus": draft.focus,
        "target_volume_m": draft.target_volume_m,
        "sessions": [
            {
                "date": s.date.isoformat(),
                "sport": s.sport,
                "source": s.source,
                "distance_m": s.distance_m,
                "duration_min": s.duration_min,
                "purpose": s.purpose,
            }
            for s in draft.sessions
        ],
        "rationale": json.loads(draft.adaptation_rationale) if draft.adaptation_rationale else None,
        "persisted": False,
    }


def _handle_get_plan_summary(input_data: dict[str, Any], *, store: StoreInterface, slug: str) -> dict[str, Any]:
    weeks = input_data.get("weeks") or 4
    try:
        weeks = int(weeks)
    except (TypeError, ValueError):
        return {"error": f"invalid weeks {weeks!r}"}
    return summarize_rollup(store, slug, weeks=weeks, as_of=date.today())


def _handle_log_open_question(
    input_data: dict[str, Any], *, store: StoreInterface, slug: str, expert_mode: bool
) -> dict[str, Any]:
    question = input_data.get("question")
    topic = input_data.get("topic")
    if not question or not topic:
        return {"error": "question and topic are both required"}

    try:
        athlete_id = store.load_athlete(slug).id
    except Exception:  # noqa: BLE001 - a research question must still log even if the
        # athlete profile can't be resolved for some reason; it just goes in unlinked.
        athlete_id = None

    entry = Feedback(
        id=uuid.uuid4(),
        athlete_id=athlete_id,
        type="research_question",
        source="coach",
        body=question,
        context={"topic": topic, "expert_mode": expert_mode},
        status="open",
        created_at=datetime.now(timezone.utc),
    )
    store.save_feedback(entry)

    log.info("open question logged", athlete=slug, topic=topic, expert_mode=expert_mode)
    return {"logged": True, "id": str(entry.id)}


def _summarize_workout(w: Workout) -> dict[str, Any]:
    """The compact per-workout shape `get_workouts` returns -- deliberately
    excludes the unbounded `laps`/`lengths`/`pauses` arrays (a multi-hour
    .fit can carry dozens to hundreds of entries) in favor of counts, same
    spirit as `get_plan_summary` returning an aggregate rather than raw
    rows. `analytics` is small (a handful of scalar fields) so it's passed
    through in full."""
    return {
        "date": w.date.isoformat(),
        "sport": w.sport,
        "source": w.source,
        "distance_m": w.distance_m,
        "duration_min": w.duration_min,
        "avg_pace_s_per_100m": w.avg_pace_s_per_100m,
        "rpe": w.rpe,
        "notes": w.notes,
        "avg_hr": w.avg_hr,
        "max_hr": w.max_hr,
        "analytics": w.analytics.model_dump(mode="json") if w.analytics is not None else None,
        "lap_count": len(w.laps),
        "length_count": len(w.lengths),
        "pause_count": len(w.pauses),
    }


def _handle_get_workouts(input_data: dict[str, Any], *, store: StoreInterface, slug: str) -> dict[str, Any]:
    start_str = input_data.get("start_date")
    if not start_str:
        return {"error": "start_date is required"}
    end_str = input_data.get("end_date") or start_str

    try:
        start = date.fromisoformat(start_str)
    except ValueError:
        return {"error": f"invalid start_date {start_str!r}; expected format 'YYYY-MM-DD'"}
    try:
        end = date.fromisoformat(end_str)
    except ValueError:
        return {"error": f"invalid end_date {end_str!r}; expected format 'YYYY-MM-DD'"}
    if end < start:
        return {"error": f"end_date {end_str!r} is before start_date {start_str!r}"}

    # list_workouts returns [] for an athlete tree with no logs dir (or no
    # such athlete at all) rather than raising -- same non-erroring
    # unknown-athlete behavior get_plan_summary already has, so this stays
    # consistent rather than special-casing it.
    workouts = sorted(store.list_workouts(slug), key=lambda w: w.date)
    matched = [w for w in workouts if start <= w.date <= end]

    truncated = len(matched) > GET_WORKOUTS_CAP
    matched = matched[:GET_WORKOUTS_CAP]

    return {
        "workouts": [_summarize_workout(w) for w in matched],
        "count": len(matched),
        "truncated": truncated,
    }


def _handle_sync_workouts(input_data: dict[str, Any], *, store: StoreInterface, slug: str) -> dict[str, Any]:
    """Delegates to `app.sync.sync_on_demand` (shared with the PWA's `POST
    /api/workouts/sync` route) for the bound request's athlete (never a
    model-supplied slug -- see `build_tool_handlers`), with this tool's own
    2-day on-demand window."""
    return sync_on_demand(store, slug, window_days=SYNC_WORKOUTS_WINDOW_DAYS)


def _handle_create_event(input_data: dict[str, Any], *, store: StoreInterface, slug: str) -> dict[str, Any]:
    """Appends a brand-new `Event` to `events.yaml` (`save_events` replaces
    the whole list, hence load-append-save rather than any partial update).
    Low-risk metadata about a future goal -- unlike a plan change, this
    persists directly, no draft/confirm step needed."""
    name = input_data.get("name")
    if not name:
        return {"error": "name is required"}
    event_date_str = input_data.get("event_date")
    if not event_date_str:
        return {"error": "event_date is required"}
    distance_m = input_data.get("distance_m")
    if distance_m is None:
        return {"error": "distance_m is required"}
    priority = input_data.get("priority")
    if not priority:
        return {"error": "priority is required"}

    try:
        event_date = date.fromisoformat(event_date_str)
    except (TypeError, ValueError):
        return {"error": f"invalid event_date {event_date_str!r}; expected format 'YYYY-MM-DD'"}

    try:
        distance_m = int(distance_m)
    except (TypeError, ValueError):
        return {"error": f"invalid distance_m {distance_m!r}"}
    if distance_m <= 0:
        return {"error": f"distance_m must be > 0, got {distance_m!r}"}

    water_temp_c = input_data.get("water_temp_c")
    if water_temp_c is not None:
        try:
            water_temp_c = float(water_temp_c)
        except (TypeError, ValueError):
            return {"error": f"invalid water_temp_c {water_temp_c!r}"}

    wetsuit = bool(input_data.get("wetsuit", False))
    event_format = input_data.get("event_format") or "single_day"
    if event_format not in ("single_day", "multi_day_stage"):
        return {
            "error": (
                f"invalid event_format {event_format!r}; must be 'single_day' "
                "or 'multi_day_stage'"
            )
        }

    try:
        athlete = store.load_athlete(slug)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"could not load athlete profile: {exc}"}

    try:
        events = store.load_events(slug)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"could not load events: {exc}"}

    try:
        event = Event(
            id=uuid.uuid4(),
            athlete_id=athlete.id,
            schema_version=1,
            name=name,
            event_date=event_date,
            distance_m=distance_m,
            water_temp_c=water_temp_c,
            wetsuit=wetsuit,
            priority=priority,
            event_format=event_format,
        )
    except ValidationError as exc:
        return {"error": str(exc)}

    events.append(event)
    store.save_events(slug, events)

    log.info("event created", athlete=slug, event_name=event.name, event_id=str(event.id))
    return {
        "created": True,
        "id": str(event.id),
        "name": event.name,
        "event_date": event.event_date.isoformat(),
        "distance_m": event.distance_m,
        "water_temp_c": event.water_temp_c,
        "wetsuit": event.wetsuit,
        "priority": event.priority,
        "event_format": event.event_format,
    }


def _handle_draft_macro_plan(input_data: dict[str, Any], *, store: StoreInterface, slug: str) -> dict[str, Any]:
    """Calls `swim_coach.plan.scaffold_macro` directly (the same function
    `cli.py`'s `scaffold-macro` command and the `/onboard-athlete` skill
    use) -- its own ramp-cap/taper/peak sizing is exactly why a brand-new
    macro is safe to persist immediately. Guarded against ever replacing an
    existing macro tied to the same event: revising one is a separate,
    not-yet-built concern."""
    event_name = input_data.get("event_name")
    if not event_name:
        return {"error": "event_name is required"}
    current_weekly_volume_m = input_data.get("current_weekly_volume_m")
    if current_weekly_volume_m is None:
        return {"error": "current_weekly_volume_m is required"}

    try:
        current_weekly_volume_m = int(current_weekly_volume_m)
    except (TypeError, ValueError):
        return {"error": f"invalid current_weekly_volume_m {current_weekly_volume_m!r}"}

    peak_weekly_volume_m = input_data.get("peak_weekly_volume_m")
    if peak_weekly_volume_m is not None:
        try:
            peak_weekly_volume_m = int(peak_weekly_volume_m)
        except (TypeError, ValueError):
            return {"error": f"invalid peak_weekly_volume_m {peak_weekly_volume_m!r}"}

    start_str = input_data.get("start_date")
    if start_str:
        try:
            start = date.fromisoformat(start_str)
        except ValueError:
            return {"error": f"invalid start_date {start_str!r}; expected format 'YYYY-MM-DD'"}
    else:
        start = date.today()

    try:
        athlete = store.load_athlete(slug)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"could not load athlete profile: {exc}"}

    try:
        events = store.load_events(slug)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"could not load events: {exc}"}
    event = next((e for e in events if e.name == event_name), None)
    if event is None:
        known_names = [e.name for e in events]
        return {
            "error": (
                f"no event named {event_name!r} for this athlete; known "
                f"event names: {known_names}"
            )
        }

    try:
        existing_macro = store.load_macro(slug)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"could not load macro plan: {exc}"}
    if existing_macro is not None and existing_macro.event_id == event.id:
        return {
            "error": (
                f"a macro plan already exists for {event_name!r}; "
                "draft_macro_plan is only for a brand-new macro -- use "
                "replace_macro_plan (draft-then-confirm) to revise or "
                "replace it instead"
            )
        }

    try:
        macro = scaffold_macro(athlete, event, start, current_weekly_volume_m, peak_weekly_volume_m)
    except ValueError as exc:
        return {"error": str(exc)}

    store.save_macro(slug, macro)

    log.info("macro plan drafted", athlete=slug, event_name=event_name, macro_id=str(macro.id))
    return {
        "created": True,
        "event_name": event_name,
        "blocks": [
            {
                "name": block.name,
                "start_date": block.start_date.isoformat(),
                "end_date": block.end_date.isoformat(),
                "weekly_volume_target_m": block.weekly_volume_target_m,
                "focus": block.focus,
            }
            for block in macro.blocks
        ],
    }


def _macro_blocks_json(macro) -> list[dict[str, Any]]:
    return [
        {
            "name": block.name,
            "start_date": block.start_date.isoformat(),
            "end_date": block.end_date.isoformat(),
            "weekly_volume_target_m": block.weekly_volume_target_m,
            "focus": block.focus,
        }
        for block in macro.blocks
    ]


def _handle_replace_macro_plan(input_data: dict[str, Any], *, store: StoreInterface, slug: str) -> dict[str, Any]:
    """Computes a candidate replacement macro via `scaffold_macro` (the same
    engine function `draft_macro_plan` uses, now with the zero-current-
    volume ramp-cap fix) for exactly the case `draft_macro_plan` refuses --
    a macro already exists, whether for this event or a different one. No
    guard against an existing macro: that's this tool's whole purpose.

    Follows `propose_adaptation`'s draft-then-confirm shape rather than
    `draft_macro_plan`'s direct-persist one, per Andrew's confirmed policy:
    replacing an already-active macro can invalidate training the athlete
    has already done against it, so `confirm=False` (default) only computes
    and returns the candidate + a comparison against the current macro (if
    any), never calling `store.save_macro`; `confirm=True` recomputes
    identically (scaffold_macro is a pure function of its inputs, so this is
    safe to re-run) and persists.
    """
    event_name = input_data.get("event_name")
    if not event_name:
        return {"error": "event_name is required"}
    current_weekly_volume_m = input_data.get("current_weekly_volume_m")
    if current_weekly_volume_m is None:
        return {"error": "current_weekly_volume_m is required"}

    try:
        current_weekly_volume_m = int(current_weekly_volume_m)
    except (TypeError, ValueError):
        return {"error": f"invalid current_weekly_volume_m {current_weekly_volume_m!r}"}

    peak_weekly_volume_m = input_data.get("peak_weekly_volume_m")
    if peak_weekly_volume_m is not None:
        try:
            peak_weekly_volume_m = int(peak_weekly_volume_m)
        except (TypeError, ValueError):
            return {"error": f"invalid peak_weekly_volume_m {peak_weekly_volume_m!r}"}

    start_str = input_data.get("start_date")
    if start_str:
        try:
            start = date.fromisoformat(start_str)
        except ValueError:
            return {"error": f"invalid start_date {start_str!r}; expected format 'YYYY-MM-DD'"}
    else:
        start = date.today()

    confirm = bool(input_data.get("confirm", False))

    try:
        athlete = store.load_athlete(slug)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"could not load athlete profile: {exc}"}

    try:
        events = store.load_events(slug)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"could not load events: {exc}"}
    event = next((e for e in events if e.name == event_name), None)
    if event is None:
        known_names = [e.name for e in events]
        return {
            "error": (
                f"no event named {event_name!r} for this athlete; known "
                f"event names: {known_names}"
            )
        }

    try:
        existing_macro = store.load_macro(slug)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"could not load macro plan: {exc}"}

    try:
        macro = scaffold_macro(athlete, event, start, current_weekly_volume_m, peak_weekly_volume_m)
    except ValueError as exc:
        return {"error": str(exc)}

    comparison = None
    if existing_macro is not None:
        old_event = next((e for e in events if e.id == existing_macro.event_id), None)
        old_peak = next((b.weekly_volume_target_m for b in existing_macro.blocks if b.name == "peak"), None)
        new_peak = next((b.weekly_volume_target_m for b in macro.blocks if b.name == "peak"), None)
        comparison = {
            "old_event_name": old_event.name if old_event is not None else None,
            "old_peak_weekly_volume_m": old_peak,
            "new_event_name": event_name,
            "new_peak_weekly_volume_m": new_peak,
        }

    if not confirm:
        return {
            "event_name": event_name,
            "blocks": _macro_blocks_json(macro),
            "comparison": comparison,
            "persisted": False,
        }

    store.save_macro(slug, macro)

    log.info("macro plan replaced", athlete=slug, event_name=event_name, macro_id=str(macro.id))
    return {
        "event_name": event_name,
        "blocks": _macro_blocks_json(macro),
        "comparison": comparison,
        "persisted": True,
    }


def _handle_set_pool_coach_status(input_data: dict[str, Any], *, store: StoreInterface, slug: str) -> dict[str, Any]:
    """Flips `Athlete.has_pool_coach` (Part 3 -- see `swim_coach.plan.
    generate_week`'s branch on it). Low-risk status flag, not a plan/volume
    change -- persists directly via `store.save_athlete`, no confirm step."""
    has_pool_coach = input_data.get("has_pool_coach")
    if has_pool_coach is None:
        return {"error": "has_pool_coach is required"}
    if not isinstance(has_pool_coach, bool):
        return {"error": f"invalid has_pool_coach {has_pool_coach!r}; must be a boolean"}

    try:
        athlete = store.load_athlete(slug)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"could not load athlete profile: {exc}"}

    athlete.has_pool_coach = has_pool_coach
    store.save_athlete(athlete)

    log.info("pool coach status set", athlete=slug, has_pool_coach=has_pool_coach)
    return {"updated": True, "has_pool_coach": athlete.has_pool_coach}


def _parse_template_preference(
    raw: dict[str, Any] | None,
) -> tuple[TemplatePreference | None, str | None]:
    """Parses the optional `template_preference` tool-input dict (see
    `TEMPLATE_PREFERENCE_SCHEMA`) into a `TemplatePreference`, returning
    `(preference, error)` where exactly one is non-`None` -- same convention
    as this module's other input-parsing code, surfacing a clean `{"error":
    ...}` instead of a raw pydantic traceback reaching the athlete (e.g. an
    invalid `purpose` value)."""
    if not raw:
        return None, None
    try:
        return (
            TemplatePreference(
                purpose=raw.get("purpose"),
                equipment_any=raw.get("equipment_any"),
                interval_style=raw.get("interval_style"),
            ),
            None,
        )
    except ValidationError as exc:
        return None, f"invalid template_preference: {exc}"


def _handle_create_week_plan(input_data: dict[str, Any], *, store: StoreInterface, slug: str) -> dict[str, Any]:
    """Calls `swim_coach.plan.generate_week` directly (the same function
    `cli.py`'s `plan-week` command and the `/plan-week` skill use) and
    persists the result -- only for a week that doesn't exist yet at all;
    an already-active week stays `propose_adaptation`'s job, unchanged.

    Optional `template_preference` (see `TEMPLATE_PREFERENCE_SCHEMA`) is
    forwarded straight through to `generate_week`, narrowing which main-set
    library template the week's pool-independent swim sessions use instead
    of the default blind rotation (see `swim_coach.workout_templates.
    TemplatePreference`/`find_templates`)."""
    iso_week = input_data.get("iso_week")
    if not iso_week:
        return {"error": "iso_week is required"}

    template_preference, preference_error = _parse_template_preference(
        input_data.get("template_preference")
    )
    if preference_error is not None:
        return {"error": preference_error}

    try:
        year_str, week_str = iso_week.split("-W")
        week_start = date.fromisocalendar(int(year_str), int(week_str), 1)
    except (ValueError, IndexError):
        return {"error": f"invalid iso_week {iso_week!r}; expected format 'YYYY-Wnn'"}

    existing = store.load_week(slug, iso_week)
    if existing is not None:
        return {
            "error": (
                f"a week plan already exists for {iso_week!r}; use "
                "propose_adaptation (and the /adapt skill) to change an "
                "existing week instead"
            )
        }

    try:
        athlete = store.load_athlete(slug)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"could not load athlete profile: {exc}"}

    try:
        macro = store.load_macro(slug)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"could not load macro plan: {exc}"}
    if macro is None:
        return {"error": "no macro plan for this athlete; use draft_macro_plan first"}

    try:
        events = store.load_events(slug)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"could not load events: {exc}"}
    event = next((e for e in events if e.id == macro.event_id), None)
    if event is None:
        return {"error": f"macro's event_id {macro.event_id} not found in events.yaml"}

    event_format = event.event_format or "single_day"

    try:
        week = generate_week(athlete, macro, iso_week, week_start, event_format, template_preference)
    except ValueError as exc:
        return {"error": str(exc)}

    store.save_week(slug, week)

    log.info("week plan created", athlete=slug, iso_week=iso_week)
    return {
        "created": True,
        "iso_week": week.iso_week,
        "meso_block": week.meso_block,
        "focus": week.focus,
        "target_volume_m": week.target_volume_m,
        "sessions": [
            {
                "date": s.date.isoformat(),
                "sport": s.sport,
                "source": s.source,
                "distance_m": s.distance_m,
                "duration_min": s.duration_min,
                "purpose": s.purpose,
            }
            for s in week.sessions
        ],
    }


def _handle_reschedule_session(input_data: dict[str, Any], *, store: StoreInterface, slug: str) -> dict[str, Any]:
    """Moves one already-planned Session's `date` field within the same ISO
    week -- everything else about the session (sport, distance, duration,
    intensity, structure, purpose) is untouched. No volume/training-load/
    safety-rail interaction at all, unlike propose_adaptation -- a low-risk
    single-field edit, so this persists directly via store.save_week, no
    draft/confirm step, matching create_event's/set_pool_coach_status's
    direct-persist convention."""
    iso_week = input_data.get("iso_week")
    if not iso_week:
        return {"error": "iso_week is required"}
    current_date_str = input_data.get("current_date")
    if not current_date_str:
        return {"error": "current_date is required"}
    sport = input_data.get("sport")
    if not sport:
        return {"error": "sport is required"}
    new_date_str = input_data.get("new_date")
    if not new_date_str:
        return {"error": "new_date is required"}

    try:
        year_str, week_str = iso_week.split("-W")
        week_start = date.fromisocalendar(int(year_str), int(week_str), 1)
    except (ValueError, IndexError):
        return {"error": f"invalid iso_week {iso_week!r}; expected format 'YYYY-Wnn'"}

    try:
        current_date = date.fromisoformat(current_date_str)
    except ValueError:
        return {"error": f"invalid current_date {current_date_str!r}; expected format 'YYYY-MM-DD'"}

    try:
        new_date = date.fromisoformat(new_date_str)
    except ValueError:
        return {"error": f"invalid new_date {new_date_str!r}; expected format 'YYYY-MM-DD'"}

    week_end = week_start + timedelta(days=6)
    if not (week_start <= new_date <= week_end):
        return {
            "error": (
                f"new_date {new_date_str!r} falls outside {iso_week!r}'s own "
                f"Monday-Sunday span ({week_start.isoformat()}..{week_end.isoformat()}); "
                "reschedule_session only moves a session within the same week -- "
                "use propose_adaptation instead to move something to a different "
                "week"
            )
        }

    week = store.load_week(slug, iso_week)
    if week is None:
        return {
            "error": (
                f"no existing week plan for {iso_week!r}; use create_week_plan if "
                "it doesn't exist at all yet, or propose_adaptation if it needs a "
                "volume/training-load change"
            )
        }

    matches = [s for s in week.sessions if s.date == current_date and s.sport == sport]
    if len(matches) != 1:
        same_day = [
            {"sport": s.sport, "date": s.date.isoformat()} for s in week.sessions if s.date == current_date
        ]
        return {
            "error": (
                f"expected exactly one session matching current_date "
                f"{current_date_str!r} and sport {sport!r} in {iso_week!r}, found "
                f"{len(matches)}; sessions on {current_date_str!r}: {same_day}"
            )
        }

    session = matches[0]
    session.date = new_date
    store.save_week(slug, week)

    log.info(
        "session rescheduled",
        athlete=slug,
        iso_week=iso_week,
        sport=sport,
        previous_date=current_date_str,
        new_date=new_date_str,
    )
    return {
        "rescheduled": True,
        "iso_week": iso_week,
        "sport": sport,
        "previous_date": current_date_str,
        "new_date": new_date_str,
    }


def _apply_session_overrides(week, overrides: list[dict[str, Any]], css_pace_s: float | None) -> str | None:
    """Applies explicit per-session distance_m/duration_min overrides to an
    already-generated week's sessions, in place. Returns an error string on
    the first override that doesn't match exactly one session (no match, or
    an ambiguous match needing `sport` to disambiguate, same convention as
    `reschedule_session`'s existing date+sport matching above) -- callers
    should treat any non-None return as a full failure, not apply the rest
    and ignore the bad one. `week` is mutated directly (pydantic Session
    objects are not frozen in this codebase); this is only ever called on a
    freshly-computed `generate_week()` result, never a stored object another
    caller might still be holding a reference to.
    """
    for override in overrides:
        raw_date = override.get("date")
        try:
            override_date = date.fromisoformat(raw_date)
        except (TypeError, ValueError):
            return f"invalid session_overrides date {raw_date!r}; expected 'YYYY-MM-DD'"

        sport = override.get("sport")
        matches = [
            s for s in week.sessions
            if s.date == override_date and (sport is None or s.sport == sport)
        ]
        if len(matches) == 0:
            same_day = [{"sport": s.sport, "date": s.date.isoformat()} for s in week.sessions if s.date == override_date]
            return (
                f"session_overrides: no session matching date {raw_date!r}"
                + (f" and sport {sport!r}" if sport else "")
                + f"; sessions on {raw_date!r}: {same_day}"
            )
        if len(matches) > 1:
            return (
                f"session_overrides: {len(matches)} sessions found on {raw_date!r} "
                f"({', '.join(s.sport for s in matches)}) -- pass `sport` to disambiguate"
            )

        session = matches[0]
        distance_m = override.get("distance_m")
        duration_min = override.get("duration_min")
        purpose = override.get("purpose")
        structure = override.get("structure")
        structured = override.get("structured")
        if (
            distance_m is None
            and duration_min is None
            and purpose is None
            and structure is None
            and structured is None
        ):
            return (
                f"session_overrides: entry for {raw_date!r} needs at least one of "
                "distance_m, duration_min, purpose, structure, structured"
            )
        if structure is not None and distance_m is None:
            # Real bug, caught live: `distance_m` is a separate field from
            # `structure`'s free-text total -- nothing keeps them in sync
            # automatically (parsing an arbitrary prose total back out is
            # fragile and wasn't attempted). Without this check, authoring a
            # new structure (e.g. 600m warm-up + 10x200m + 400m cool-down =
            # 3000m) while leaving the session's OLD distance_m in place
            # (e.g. 400m from whatever it replaced) persists a session whose
            # stats header silently disagrees with its own written content.
            # Require the caller to state the real total explicitly rather
            # than let it drift.
            return (
                f"session_overrides: entry for {raw_date!r} sets `structure` "
                "without `distance_m` -- the two are independent fields with "
                "nothing keeping them in sync automatically, so the athlete "
                "would see a distance stat that disagrees with what the "
                "structure text actually describes. Pass the real total "
                "distance implied by the new structure as `distance_m` too."
            )

        if distance_m is not None:
            session.distance_m = distance_m
        if duration_min is not None:
            session.duration_min = duration_min
        elif distance_m is not None and css_pace_s is not None:
            # No explicit duration override -- re-estimate from the new
            # distance at the athlete's own CSS pace, same rough-estimate
            # math the engine itself uses (_duration_min_for_distance),
            # rather than leaving a stale duration paired with a new distance.
            # If the athlete has no CSS pace on file yet, leave duration_min
            # as generate_week originally computed it rather than guessing.
            session.duration_min = max(_duration_min_for_distance(distance_m, css_pace_s), 15.0)

        if purpose is not None:
            session.purpose = purpose
        if structured is not None:
            try:
                session.structured = WorkoutStructure.model_validate(structured)
            except ValidationError as exc:
                return f"invalid session_overrides structured: {exc}"
        if structure is not None:
            session.structure = structure
            if structured is None:
                # The session's structured IR (if any) was built by the
                # template pipeline for the OLD content -- leaving it in
                # place would mean the UI's tree-walk rendering and Garmin
                # .fit export both keep showing/exporting the previous
                # template's workout, silently ignoring the athlete-facing
                # prose the coach (or athlete) just asked to persist here.
                # Clear it so both correctly fall back to the new prose
                # instead of a stale, mismatched structure. This only
                # applies when `structured` was NOT also supplied in this
                # same entry -- when both are given, they describe the same
                # session (prose + machine-readable IR) and neither should
                # clobber the other; see the tool description.
                session.structured = None
    return None


def _week_sessions_json(week) -> list[dict[str, Any]]:
    return [
        {
            "date": s.date.isoformat(),
            "sport": s.sport,
            "source": s.source,
            "distance_m": s.distance_m,
            "duration_min": s.duration_min,
            "purpose": s.purpose,
            "structure": s.structure,
            # Not the full structured IR (keeps this response compact) --
            # just whether one exists, so the coach can tell whether a
            # session_overrides.structure write would be clearing real
            # structured data (Garmin-exportable) vs. an already-prose-only
            # session (nothing to lose).
            "has_structured": s.structured is not None,
        }
        for s in week.sessions
    ]


def _handle_replace_week_plan(input_data: dict[str, Any], *, store: StoreInterface, slug: str) -> dict[str, Any]:
    """Computes a candidate replacement week via `generate_week` (the same
    engine function `create_week_plan` uses) for exactly the case
    `create_week_plan` refuses -- a week already exists for iso_week. No
    guard against an existing week: that's this tool's whole purpose, closing
    the structural dead end where `create_week_plan` refuses AND
    `propose_adaptation` also refuses (no valid prior week to adapt from).

    Follows `replace_macro_plan`'s draft-then-confirm shape rather than
    `create_week_plan`'s direct-persist one: overwriting an already-active
    week can invalidate training the athlete has already done against it, so
    `confirm=False` (default) only computes and returns the candidate + a
    comparison against the week currently on file (if any), never calling
    `store.save_week`; `confirm=True` recomputes identically (generate_week
    is a pure function of its inputs, so this is safe to re-run) and
    persists.

    Optional `session_overrides` applies explicit distance_m/duration_min
    overrides to specific sessions in the freshly-generated week, via
    `_apply_session_overrides`, before the draft/comparison is built or
    anything is persisted -- this is the tool's answer to the real dead end
    where `generate_week`'s own ramp/volume math computes a technically-safe
    number the athlete explicitly doesn't want (e.g. a conservative first
    swim back after time off): there was previously no way to just set a
    specific session's number, only to accept whatever the deterministic
    math produced or replan the whole macro.

    Optional `template_preference` (see `TEMPLATE_PREFERENCE_SCHEMA`) is
    forwarded straight through to `generate_week`, same as `create_week_
    plan` -- narrows which main-set library template the recomputed week's
    pool-independent swim sessions use instead of the default blind
    rotation.
    """
    iso_week = input_data.get("iso_week")
    if not iso_week:
        return {"error": "iso_week is required"}

    template_preference, preference_error = _parse_template_preference(
        input_data.get("template_preference")
    )
    if preference_error is not None:
        return {"error": preference_error}

    try:
        year_str, week_str = iso_week.split("-W")
        week_start = date.fromisocalendar(int(year_str), int(week_str), 1)
    except (ValueError, IndexError):
        return {"error": f"invalid iso_week {iso_week!r}; expected format 'YYYY-Wnn'"}

    confirm = bool(input_data.get("confirm", False))

    try:
        athlete = store.load_athlete(slug)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"could not load athlete profile: {exc}"}

    try:
        macro = store.load_macro(slug)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"could not load macro plan: {exc}"}
    if macro is None:
        return {"error": "no macro plan for this athlete; use draft_macro_plan first"}

    try:
        events = store.load_events(slug)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"could not load events: {exc}"}
    event = next((e for e in events if e.id == macro.event_id), None)
    if event is None:
        return {"error": f"macro's event_id {macro.event_id} not found in events.yaml"}

    event_format = event.event_format or "single_day"

    try:
        existing_week = store.load_week(slug, iso_week)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"could not load existing week plan: {exc}"}

    try:
        week = generate_week(athlete, macro, iso_week, week_start, event_format, template_preference)
    except ValueError as exc:
        return {"error": str(exc)}

    session_overrides = input_data.get("session_overrides")
    if session_overrides:
        override_error = _apply_session_overrides(week, session_overrides, athlete.css_pace_s_per_100m)
        if override_error is not None:
            return {"error": override_error}

    comparison = None
    if existing_week is not None:
        comparison = {
            "old_target_volume_m": existing_week.target_volume_m,
            "old_session_count": len(existing_week.sessions),
            "new_target_volume_m": week.target_volume_m,
            "new_session_count": len(week.sessions),
        }

    if not confirm:
        return {
            "iso_week": week.iso_week,
            "meso_block": week.meso_block,
            "focus": week.focus,
            "target_volume_m": week.target_volume_m,
            "sessions": _week_sessions_json(week),
            "comparison": comparison,
            "persisted": False,
        }

    store.save_week(slug, week)

    log.info("week plan replaced", athlete=slug, iso_week=iso_week)
    return {
        "iso_week": week.iso_week,
        "meso_block": week.meso_block,
        "focus": week.focus,
        "target_volume_m": week.target_volume_m,
        "sessions": _week_sessions_json(week),
        "comparison": comparison,
        "persisted": True,
    }


def _handle_set_event_active_status(input_data: dict[str, Any], *, store: StoreInterface, slug: str) -> dict[str, Any]:
    """Flips one `Event.active` flag and persists via `store.save_events`
    (the whole list, matching that store method's replace-the-list
    contract). Soft delete/reactivate, not a hard delete -- a macro's
    event_id can still reference an event after the athlete has moved on.
    Low-risk status flag, not a plan/volume change -- persists directly, no
    confirm step, same convention as set_pool_coach_status."""
    event_name = input_data.get("event_name")
    if not event_name:
        return {"error": "event_name is required"}
    active = input_data.get("active")
    if active is None:
        return {"error": "active is required"}
    if not isinstance(active, bool):
        return {"error": f"invalid active {active!r}; must be a boolean"}

    try:
        events = store.load_events(slug)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"could not load events: {exc}"}

    matches = [e for e in events if e.name == event_name]
    if len(matches) != 1:
        known_names = [e.name for e in events]
        return {
            "error": (
                f"expected exactly one event named {event_name!r}, found "
                f"{len(matches)}; known event names: {known_names}"
            )
        }

    event = matches[0]
    event.active = active
    store.save_events(slug, events)

    log.info("event active status set", athlete=slug, event_name=event_name, active=active)
    return {"updated": True, "event_name": event_name, "active": event.active}


def build_tool_handlers(
    store: StoreInterface, *, slug: str, expert_mode: bool
) -> dict[str, ToolHandler]:
    """Binds the request's athlete slug / expert_mode / store into closures
    over the tool handlers above, so the tool schema the model sees never
    exposes `expert_mode` as something the model itself sets -- it's a
    client-declared request flag, not a model decision."""
    return {
        "propose_adaptation": lambda input_data: _handle_propose_adaptation(
            input_data, store=store, slug=slug
        ),
        "get_plan_summary": lambda input_data: _handle_get_plan_summary(
            input_data, store=store, slug=slug
        ),
        "log_open_question": lambda input_data: _handle_log_open_question(
            input_data, store=store, slug=slug, expert_mode=expert_mode
        ),
        "get_workouts": lambda input_data: _handle_get_workouts(
            input_data, store=store, slug=slug
        ),
        "sync_workouts": lambda input_data: _handle_sync_workouts(
            input_data, store=store, slug=slug
        ),
        "create_event": lambda input_data: _handle_create_event(
            input_data, store=store, slug=slug
        ),
        "draft_macro_plan": lambda input_data: _handle_draft_macro_plan(
            input_data, store=store, slug=slug
        ),
        "replace_macro_plan": lambda input_data: _handle_replace_macro_plan(
            input_data, store=store, slug=slug
        ),
        "set_pool_coach_status": lambda input_data: _handle_set_pool_coach_status(
            input_data, store=store, slug=slug
        ),
        "create_week_plan": lambda input_data: _handle_create_week_plan(
            input_data, store=store, slug=slug
        ),
        "reschedule_session": lambda input_data: _handle_reschedule_session(
            input_data, store=store, slug=slug
        ),
        "replace_week_plan": lambda input_data: _handle_replace_week_plan(
            input_data, store=store, slug=slug
        ),
        "set_event_active_status": lambda input_data: _handle_set_event_active_status(
            input_data, store=store, slug=slug
        ),
    }
