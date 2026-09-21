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

# A held draft older than this is treated as absent by a confirm that names no draft_id, and is
# no longer offered to the coach as waiting.
DRAFT_MAX_AGE = timedelta(hours=12)

TAPER_CARRIER_WEEK = "9999-W01"
MACRO_CARRIER_WEEK = "9999-W02"

# Which tool WRITES a draft made by each tool (propose_adaptation never writes itself).
WRITE_TOOL = {"propose_adaptation": "replace_week_plan"}


def draft_is_stale(draft: WeekPlan) -> bool:
    return draft.drafted_at is not None and datetime.now(timezone.utc) - draft.drafted_at > DRAFT_MAX_AGE


def _age_minutes(draft: WeekPlan) -> int | None:
    if draft.drafted_at is None:
        return None
    return int((datetime.now(timezone.utc) - draft.drafted_at).total_seconds() // 60)


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
        return False


def pending_drafts(store: StoreInterface, slug: str) -> list[WeekPlan]:
    try:
        held = store.list_week_drafts(slug)
    except Exception:  # noqa: BLE001
        return []
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
        age = _age_minutes(draft)
        lines.append(
            f"- {what}, drafted {'%d min ago' % age if age is not None else 'earlier'} by "
            f"`{draft.drafted_by or 'unknown'}`. To write it: `{tool}` "
            f'{{"confirm": true, "draft_id": "{draft.id}"{extra}}}'
        )
    return "\n".join(lines)
