"""WRITE_TOOLS must track the real tool definitions so a new write tool cannot
silently be missed by the false save-claim guard."""

from __future__ import annotations

import inspect

import pytest

from app import tools as tools_module
from app.save_claims import NON_PLAN_OR_READ_ONLY, WRITE_TOOLS, write_succeeded
from app.tools import TOOLS_SCHEMA

REAL = {t["name"] for t in TOOLS_SCHEMA}


def _handler_source(tool: str) -> str:
    fn = getattr(tools_module, f"_handle_{tool}", None)
    assert fn is not None, f"no _handle_{tool} for real tool {tool}"
    return inspect.getsource(fn)


def test_every_write_tool_is_a_real_tool() -> None:
    assert set(WRITE_TOOLS) <= REAL, sorted(set(WRITE_TOOLS) - REAL)
    assert set(NON_PLAN_OR_READ_ONLY) <= REAL, sorted(set(NON_PLAN_OR_READ_ONLY) - REAL)


def test_every_real_tool_is_classified_exactly_once() -> None:
    both = set(WRITE_TOOLS) & set(NON_PLAN_OR_READ_ONLY)
    assert not both, sorted(both)
    missing = REAL - set(WRITE_TOOLS) - set(NON_PLAN_OR_READ_ONLY)
    assert not missing, f"classify new tool(s) in app/save_claims.py: {sorted(missing)}"


@pytest.mark.parametrize("tool", sorted(REAL))
def test_persisting_handlers_are_write_tools(tool: str) -> None:
    src = _handler_source(tool)
    persists_plan_or_profile = any(
        marker in src
        for marker in ("store.save_week", "store.save_macro", "store.save_events", "store.save_athlete",
                       "store.save_threshold_record", "store.save_health_status",
                       '"persisted": True', '["persisted"] = True')
    )
    if persists_plan_or_profile:
        assert tool in WRITE_TOOLS, f"{tool} persists but is not in WRITE_TOOLS"


@pytest.mark.parametrize("tool,key", sorted(WRITE_TOOLS.items()))
def test_write_tool_success_key_appears_in_its_handler(tool: str, key: str) -> None:
    src = _handler_source(tool)
    assert f'"{key}"' in src, f"{tool}: success key {key!r} not found in handler"


def test_success_shapes() -> None:
    assert write_succeeded("reschedule_session", {"rescheduled": True})
    assert write_succeeded("set_event_active_status", {"updated": True, "active": False})
    assert write_succeeded("set_pool_coach_status", {"updated": True})
    assert write_succeeded("create_event", {"created": True})
    assert not write_succeeded("propose_adaptation", {"persisted": True})  # read-only tool
