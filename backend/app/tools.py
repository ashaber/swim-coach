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
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from swim_coach.adapt import adapt_week
from swim_coach.models import Feedback, Workout
from swim_coach.store import StoreInterface

from app.context import iso_week_str, summarize_rollup
from app.logging_config import get_logger

log = get_logger(__name__)

ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]

# get_workouts caps how many sessions it returns to the coach in one call --
# a broad date range on a long-tenured athlete could otherwise dump hundreds
# of full-ish workout summaries into the (uncached, per-turn) tool-result
# context. Matches the PWA history list's own display cap
# (web/src/workouts.js's HISTORY_DISPLAY_CAP).
GET_WORKOUTS_CAP = 20

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
    }
