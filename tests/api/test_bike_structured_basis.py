"""Tool-level data-validity guard: a `structured` tree on a bike session may not
use a swim-pace basis (`absolute` / `percent_css`). Real incident, prod
2026-10-10: watts written as basis "absolute"."""

from __future__ import annotations

from test_override_defects import D, _week

from app.tools import _apply_session_overrides, _session_from_add_fields


def _tree(basis: str) -> dict:
    return {
        "items": [
            {
                "kind": "step", "label": "Main", "role": "interval", "modality": "bike",
                "duration_kind": "time_s", "duration_value": 600,
                "target": {"basis": basis, "low": 278, "high": 286},
            }
        ]
    }


def test_modify_rejects_absolute_basis_on_bike_with_clear_error() -> None:
    a, w = _week()
    err, _ = _apply_session_overrides(w, [{"date": D.isoformat(), "sport": "bike", "structured": _tree("absolute")}], a)
    assert err and "power_w" in err and "zone" in err
    assert w.sessions[0].structured is None


def test_modify_rejects_percent_css_on_bike() -> None:
    a, w = _week()
    err, _ = _apply_session_overrides(w, [{"date": D.isoformat(), "sport": "bike", "structured": _tree("percent_css")}], a)
    assert err and "power_w" in err


def test_modify_accepts_power_w_on_bike() -> None:
    a, w = _week()
    err, _ = _apply_session_overrides(w, [{"date": D.isoformat(), "sport": "bike", "structured": _tree("power_w")}], a)
    assert err is None
    assert w.sessions[0].structured is not None


def test_add_rejects_absolute_basis_on_bike() -> None:
    a, w = _week()
    err, _ = _apply_session_overrides(
        w,
        [{"date": D.isoformat(), "sport": "bike", "add": True, "duration_min": 60, "purpose": "x",
          "structured": _tree("absolute")}],
        a,
    )
    assert err and "power_w" in err
    assert len(w.sessions) == 1


def test_proposed_session_fields_reject_absolute_basis_on_bike() -> None:
    a, _ = _week()
    session, err = _session_from_add_fields(
        {"date": D.isoformat(), "sport": "bike", "duration_min": 60, "purpose": "x", "structured": _tree("absolute")},
        athlete=a,
    )
    assert session is None and err and "power_w" in err


def test_swim_session_keeps_absolute_basis() -> None:
    a, _ = _week()
    tree = _tree("absolute")
    tree["items"][0]["modality"] = "swim"
    session, err = _session_from_add_fields(
        {"date": D.isoformat(), "sport": "swim_pool", "duration_min": 60, "purpose": "x", "structured": tree}, athlete=a
    )
    assert err is None and session is not None
