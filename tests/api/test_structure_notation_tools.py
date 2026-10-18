"""`structure_notation` on session-authoring tool entries: parsed server-side into `structured`."""

from __future__ import annotations

import json

from test_override_defects import D, _week

from app.tools import SESSION_ENTRY_SCHEMA, _apply_session_overrides, _session_from_add_fields

NOTATION = "10m 55%; 3x[5m 95-100% / 3m 50%]; 8m 50%"


def _entry(**extra) -> dict:
    return {"date": D.isoformat(), "sport": "bike", "duration_min": 60, "purpose": "x", **extra}


def test_proposed_entry_notation_becomes_structured_and_prose() -> None:
    a, _ = _week()
    a.ftp_watts = 250.0
    session, err = _session_from_add_fields(_entry(structure_notation=NOTATION), athlete=a)
    assert err is None and session.structured is not None
    assert session.structured.items[1].count == 3
    assert session.structured.items[1].steps[0].target.low == 238.0
    assert session.structure


def test_notation_error_names_session_and_position() -> None:
    a, _ = _week()
    a.ftp_watts = 250.0
    session, err = _session_from_add_fields(_entry(structure_notation="10m 55%; 3m 9x%"), athlete=a)
    assert session is None
    assert D.isoformat() in err and "step 2" in err and "unknown target '9x%'" in err


def test_notation_and_structured_together_rejected() -> None:
    a, _ = _week()
    a.ftp_watts = 250.0
    _, err = _session_from_add_fields(_entry(structure_notation=NOTATION, structured={"items": []}), athlete=a)
    assert err and "not both" in err


def test_notation_percent_without_ftp_is_an_error() -> None:
    a, _ = _week()
    a.ftp_watts = None
    _, err = _session_from_add_fields(_entry(structure_notation=NOTATION), athlete=a)
    assert err and "FTP" in err


def test_notation_rejected_for_swim() -> None:
    a, _ = _week()
    _, err = _session_from_add_fields(_entry(sport="swim_pool", structure_notation="10m z2"), athlete=a)
    assert err and "bike-only" in err


def test_patch_override_modify_with_notation() -> None:
    a, w = _week()
    a.ftp_watts = 250.0
    err, _ = _apply_session_overrides(w, [{"date": D.isoformat(), "sport": "bike", "structure_notation": NOTATION}], a)
    assert err is None
    assert w.sessions[0].structured is not None


def test_patch_override_add_with_bad_notation_persists_nothing() -> None:
    a, w = _week()
    a.ftp_watts = 250.0
    n = len(w.sessions)
    err, _ = _apply_session_overrides(
        w,
        [{"date": D.isoformat(), "sport": "bike", "add": True, "duration_min": 60, "purpose": "x",
          "structure_notation": "5m bogus"}],
        a,
    )
    assert err and "step 1" in err
    assert len(w.sessions) == n


def test_schema_exposes_notation_and_is_cheaper_than_json() -> None:
    assert "structure_notation" in SESSION_ENTRY_SCHEMA["properties"]
    a, _ = _week()
    a.ftp_watts = 250.0
    session, _ = _session_from_add_fields(_entry(structure_notation=NOTATION), athlete=a)
    assert len(NOTATION) * 5 < len(json.dumps(session.structured.model_dump(mode="json")))
