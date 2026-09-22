"""What the coach receives when a tool hits an INTERNAL error (a bug, not bad input).

A raw exception string ("'WorkoutRepeat' object has no attribute 'role'") tells the coach nothing:
it cannot tell a tool bug from a problem with the request, so it retries the same call (each retry a
full, paid API call) or makes an excuse. `internal_tool_error` turns it into a structured result that
says plainly it is a tool problem, not to repeat the call, and what to do INSTEAD -- so the failure is
better-than-fail. The stack trace is logged separately (see `claude.ClaudeChat._run_turns`).
"""

from __future__ import annotations

from typing import Any

_WEEK_TOOLS = frozenset(
    {"replace_week_plan", "patch_week_plan", "merge_week_plan", "create_week_plan", "propose_session_adjustment"}
)
_MACRO_TOOLS = frozenset({"replace_macro_plan", "draft_macro_plan", "draft_season_macro_plan"})

_NO_EXCUSES = (
    "Never tell the athlete the plan cannot be written or blame the tools in general: say plainly what "
    "you tried and what you did instead."
)


def _guidance(tool: str) -> str:
    if tool in _WEEK_TOOLS:
        return (
            "Do not retry this exact call. Try the same change as plain text: use patch_week_plan with "
            "`structure` (plain text) and NO `structured`, or split it into smaller overrides. If it still "
            "fails, tell the athlete exactly what could not be saved, keep their request with "
            "save_athlete_note, and carry on with the rest of the plan. " + _NO_EXCUSES
        )
    if tool in _MACRO_TOOLS:
        return (
            "Do not retry this exact call. Try once more with simpler input (fewer events, an explicit "
            "start_date); if it still fails, tell the athlete which part could not be built and continue "
            "with the weeks you can write. " + _NO_EXCUSES
        )
    return (
        "Do not retry this exact call. Continue with what you can do, tell the athlete plainly what could "
        "not be done, and keep their request with save_athlete_note. " + _NO_EXCUSES
    )


def internal_tool_error(tool: str, exc: BaseException) -> dict[str, Any]:
    """The structured result for an unexpected exception inside `tool`."""
    return {
        "error": f"{tool} hit an internal problem ({type(exc).__name__}) and did not complete",
        "code": "internal_error",
        "detail": str(exc)[:200],
        "input_problem": False,
        "do_not_retry_same_call": True,
        "what_to_do": _guidance(tool),
    }


def storage_error(what: str, exc: BaseException) -> dict[str, Any]:
    """The structured result when reading `what` (e.g. "macro plan") from storage failed.

    The exception text is NOT passed to the coach -- it is a driver/SQL message that means nothing to it
    and invites excuses. The full stack is in the logs (the caller logs `storage read failed` with
    `what=` and `exc_info=True`, under the tool's `log_context`). The coach gets what it can act on:
    it is a temporary storage problem, retrying once is reasonable, and the athlete's request is not lost.
    """
    return {
        "error": f"could not load {what} (storage problem, not a problem with your request)",
        "code": "storage_error",
        "what": what,
        "retryable": True,
        "input_problem": False,
        "what_to_do": (
            "Retry this call once. If it fails again, tell the athlete plainly that the "
            f"{what} could not be read right now, do the parts of the request that do not need it, "
            "and keep the request with save_athlete_note so nothing is lost. " + _NO_EXCUSES
        ),
    }


def storage_problem_text(what: str) -> str:
    """One-line form of `storage_error` for helpers that return `(value, error_text)` tuples."""
    return f"could not load {what} (storage problem, not a problem with your request); retry once"
