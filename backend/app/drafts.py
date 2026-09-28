"""Held drafts: what is waiting for the athlete's yes, and how the coach writes it.

The chat client replays only TEXT turns, so on the turn the athlete says "yes" the coach has
forgotten the tool result that carried the `draft_id`. The server therefore tells the coach, on
every request, which drafts are held (`render_pending_drafts`, injected into the per-request
context) and exactly how to write each one. A draft is PENDING while it is fresh and its plan has
not been written -- a written week/macro keeps the draft's id, so that is how consumption shows.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from swim_coach.models import WeekPlan
from swim_coach.store import StoreInterface

from app.logging_config import get_logger

log = get_logger(__name__)

# A held draft older than this is treated as absent by a confirm that names no draft_id, and is
# no longer offered to the coach as waiting.
DRAFT_MAX_AGE = timedelta(hours=12)

TAPER_CARRIER_WEEK = "9999-W01"
MACRO_CARRIER_WEEK = "9999-W02"

# Which tool WRITES a draft made by each tool, for the rare case a draft's
# own tool cannot confirm itself. Empty now (engine/plan-check-red-team PR
# 2): `propose_adaptation` no longer holds a draft at all (it's advisory
# only -- see its own handler docstring; its old draft used to be written
# via `replace_week_plan`, now retired from TOOLS_SCHEMA), and every
# draft-holding tool below (author_macro_plan, author_week_plan,
# patch_week_plan, merge_week_plan, ...) confirms itself, which the
# `_describe` fallback below already handles without an explicit entry here.
WRITE_TOOL: dict[str, str] = {}


def draft_is_stale(draft: WeekPlan) -> bool:
    return draft.drafted_at is not None and datetime.now(timezone.utc) - draft.drafted_at > DRAFT_MAX_AGE


def _drafted_at_label(draft: WeekPlan) -> str | None:
    """An absolute, byte-stable timestamp for `render_pending_drafts`'s "drafted ... ago" line.

    Context-trim build (Phase 2): this used to be a `datetime.now()`-relative "%d min ago"
    figure, which changed every single minute -- the one thing in the per-request context that
    was NOT stable when the athlete's own data was otherwise unchanged (verified: two renders a
    minute apart, same held draft, produced different bytes). Now that this context is a cached
    system block (`build_context_block`), that minute-level drift alone would evict the cache
    every ~60s regardless of data changes. `drafted_at` is itself an absolute, already-stored
    timestamp, so rendering it directly is exactly as informative (the athlete-facing "Today"
    line elsewhere in this context gives the coach a same-day reference point) and never changes
    between requests unless the draft itself does."""
    if draft.drafted_at is None:
        return None
    return draft.drafted_at.strftime("%Y-%m-%d %H:%M UTC")


def _is_written(store: StoreInterface, slug: str, draft: WeekPlan) -> bool:
    """True once the draft's plan is live (a written plan keeps the draft's id)."""
    try:
        if draft.iso_week == MACRO_CARRIER_WEEK:
            macro = json.loads(draft.adaptation_rationale or "{}").get("macro") or {}
            live = store.load_macro(slug)
            return live is not None and str(live.id) == str(macro.get("id"))
        if draft.iso_week == TAPER_CARRIER_WEEK:
            bundle = json.loads(draft.adaptation_rationale or "{}").get("bundle", [])
            for item in bundle:
                held = store.load_week_draft(slug, item["iso_week"], item["draft_id"])
                live = store.load_week(slug, item["iso_week"])
                if held is None or live is None or live.id != held.id:
                    return False
            return bool(bundle)
        live = store.load_week(slug, draft.iso_week)
        return live is not None and live.id == draft.id
    except Exception:  # noqa: BLE001 - never let a lookup problem hide a draft from the coach
        log.warn("swallowed exception, using a default", where='backend/app/drafts.py', line_hint=57, exc_info=True)
        return False


def _gc_stale_drafts(store: StoreInterface, slug: str, held: list[WeekPlan]) -> None:
    """Opportunistic GC: a draft older than DRAFT_MAX_AGE is already treated as
    absent (never offered to the coach, see `pending_drafts` below) -- delete it
    for real here too, so the table/tree doesn't grow forever without a cron.
    Cheap (runs once per request, only over the already-fetched `held` list) and
    must never turn rendering the coach's context into a failure."""
    for draft in held:
        if not draft_is_stale(draft):
            continue
        try:
            store.delete_week_drafts(slug, draft.iso_week)
        except NotImplementedError:
            pass
        except Exception:  # noqa: BLE001 - opportunistic GC must never block rendering
            log.warn("could not gc stale draft", athlete=slug, iso_week=draft.iso_week, exc_info=True)


def pending_drafts(store: StoreInterface, slug: str) -> list[WeekPlan]:
    try:
        held = store.list_week_drafts(slug)
    except Exception:  # noqa: BLE001
        log.warn("swallowed exception, using a default", where='backend/app/drafts.py', line_hint=64, exc_info=True)
        return []
    _gc_stale_drafts(store, slug, held)
    return [d for d in held if not draft_is_stale(d) and not _is_written(store, slug, d)]


def _describe(draft: WeekPlan) -> tuple[str, str, str]:
    """`(what, tool_to_call, extra_args)` for one held draft."""
    tool = WRITE_TOOL.get(draft.drafted_by or "", draft.drafted_by or "replace_week_plan")
    if draft.iso_week == MACRO_CARRIER_WEEK:
        macro = json.loads(draft.adaptation_rationale or "{}").get("macro") or {}
        blocks = ", ".join(b.get("name", "?") for b in macro.get("blocks", []))
        return f"a MACRO plan ({blocks})", tool, ""
    if draft.iso_week == TAPER_CARRIER_WEEK:
        carried = json.loads(draft.adaptation_rationale or "{}")
        n = len(carried.get("bundle", []))
        return f"an injury-adapted TAPER for {carried.get('event_name', 'the event')} ({n} week(s))", tool, ""
    sessions = "; ".join(
        f"{s.date.strftime('%a')} {s.sport}" for s in sorted(draft.sessions, key=lambda s: (s.date, s.sport))[:10]
    )
    return f"week {draft.iso_week} ({len(draft.sessions)} sessions: {sessions})", tool, f', "iso_week": "{draft.iso_week}"'


def render_pending_drafts(store: StoreInterface, slug: str) -> str | None:
    """The per-request context section, or `None` when nothing is waiting (so a request with no
    drafts is byte-identical to before)."""
    drafts = pending_drafts(store, slug)
    if not drafts:
        return None
    lines = [
        "### Drafts waiting for the athlete's yes (HELD -- NOT yet written)",
        "You proposed these earlier; the athlete has not confirmed them yet. If the athlete's latest "
        "message AGREES to one, WRITE EXACTLY THAT DRAFT now: call the tool shown with `confirm: true` and "
        "its `draft_id` -- nothing else is needed, and nothing is recomputed. Do NOT make a new draft, "
        "do NOT hand it off to /adapt or anyone else, and do NOT say you cannot write it. If they ask for "
        "a CHANGE, make a NEW draft instead. After writing, tell them plainly what was written and pass "
        "on any warnings the tool returned.",
    ]
    for draft in sorted(drafts, key=lambda d: d.drafted_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True):
        what, tool, extra = _describe(draft)
        drafted_at = _drafted_at_label(draft)
        lines.append(
            f"- {what}, drafted at {drafted_at if drafted_at is not None else 'an unknown time'} by "
            f"`{draft.drafted_by or 'unknown'}`. To write it: `{tool}` "
            f'{{"confirm": true, "draft_id": "{draft.id}"{extra}}}'
        )
    return "\n".join(lines)
