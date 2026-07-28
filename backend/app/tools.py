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
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from pydantic import ValidationError

from swim_coach.adapt import adapt_week
from swim_coach.models import Event, Feedback, Workout
from swim_coach.plan import generate_week, scaffold_macro
from swim_coach.store import StoreInterface

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
            "event -- this tool is only for a brand-new macro, never for "
            "revising an existing one."
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
            "generated."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "iso_week": {
                    "type": "string",
                    "description": "ISO week to create, formatted 'YYYY-Wnn', e.g. '2026-W30'.",
                }
            },
            "required": ["iso_week"],
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
                "draft_macro_plan is only for a brand-new macro -- revising "
                "an existing one isn't supported here"
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


def _handle_create_week_plan(input_data: dict[str, Any], *, store: StoreInterface, slug: str) -> dict[str, Any]:
    """Calls `swim_coach.plan.generate_week` directly (the same function
    `cli.py`'s `plan-week` command and the `/plan-week` skill use) and
    persists the result -- only for a week that doesn't exist yet at all;
    an already-active week stays `propose_adaptation`'s job, unchanged."""
    iso_week = input_data.get("iso_week")
    if not iso_week:
        return {"error": "iso_week is required"}

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
        week = generate_week(athlete, macro, iso_week, week_start, event_format)
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
        "create_week_plan": lambda input_data: _handle_create_week_plan(
            input_data, store=store, slug=slug
        ),
    }
