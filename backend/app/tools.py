"""Tool schemas + handlers for the coach chat tool loop.

This is what makes chat "a primary caller of /adapt" (per this build's
brief): `propose_adaptation` calls `swim_coach.adapt.adapt_week` directly --
the same function `cli.py`'s `adapt` command and the `/adapt` skill call --
and returns the draft for discussion without persisting it. `get_plan_summary`
reuses `context.summarize_rollup` (itself a thin reassembly of `load.py`'s
functions). `log_open_question` implements IDEA 005.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from swim_coach.adapt import adapt_week
from swim_coach.store import FileStore

from app.context import iso_week_str, summarize_rollup
from app.logging_config import get_logger

log = get_logger(__name__)

ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]

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
]


def _handle_propose_adaptation(input_data: dict[str, Any], *, store: FileStore, slug: str) -> dict[str, Any]:
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


def _handle_get_plan_summary(input_data: dict[str, Any], *, store: FileStore, slug: str) -> dict[str, Any]:
    weeks = input_data.get("weeks") or 4
    try:
        weeks = int(weeks)
    except (TypeError, ValueError):
        return {"error": f"invalid weeks {weeks!r}"}
    return summarize_rollup(store, slug, weeks=weeks, as_of=date.today())


def _handle_log_open_question(
    input_data: dict[str, Any], *, research_dir: Path, slug: str, expert_mode: bool
) -> dict[str, Any]:
    question = input_data.get("question")
    topic = input_data.get("topic")
    if not question or not topic:
        return {"error": "question and topic are both required"}

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "athlete": slug,
        "question": question,
        "topic": topic,
        "expert_mode": expert_mode,
    }
    research_dir.mkdir(parents=True, exist_ok=True)
    path = research_dir / "open-questions.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")

    log.info("open question logged", athlete=slug, topic=topic, expert_mode=expert_mode)
    return {"logged": True, "path": str(path)}


def build_tool_handlers(
    store: FileStore, *, slug: str, research_dir: Path, expert_mode: bool
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
            input_data, research_dir=research_dir, slug=slug, expert_mode=expert_mode
        ),
    }
