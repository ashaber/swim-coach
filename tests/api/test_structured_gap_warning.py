"""A bike session written as prose only can't be pushed to Garmin and the analyzer can't match its reps.
The write tools must say so in the same turn (advisory, never blocking), and must say so loudly when a
prose-only patch WIPES `structured` that was already there (the 2026-10 W41/W42 incident)."""

from __future__ import annotations

from datetime import timedelta

from test_interval_type_override import _patch, _session, _setup

PROSE = "Warm-up: 10min easy. Main set: 3 x 9min over/under. Cool-down: 10min"


def _joined(result) -> str:
    return " | ".join(result["planning_warnings"])


def test_structure_only_patch_that_wipes_structured_says_so(athletes_dir) -> None:
    store, h, iso, ws = _setup(athletes_dir)
    tue = ws + timedelta(days=1)
    before = _session(_patch(h, iso, {"date": tue.isoformat(), "sport": "bike", "interval_type": "threshold"}), tue)
    assert before["has_structured"] is True

    result = _patch(h, iso, {"date": tue.isoformat(), "sport": "bike", "structure": PROSE})

    assert _session(result, tue)["has_structured"] is False
    warnings = _joined(result)
    assert "CLEARED" in warnings and tue.isoformat() in warnings
    assert "no structured workout" in warnings


def test_prose_only_bike_write_lists_the_affected_session_but_still_applies(athletes_dir) -> None:
    store, h, iso, ws = _setup(athletes_dir)
    wed = ws + timedelta(days=2)
    result = _patch(h, iso, {"date": wed.isoformat(), "sport": "bike", "structure": PROSE})
    assert "error" not in result, result
    assert _session(result, wed)["structure"] == PROSE
    assert wed.isoformat() in _joined(result) and "no structured workout" in _joined(result)
