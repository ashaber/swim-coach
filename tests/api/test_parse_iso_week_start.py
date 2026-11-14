"""Tests for tools._parse_iso_week_start: ISO week string -> Monday date or error dict."""

from __future__ import annotations

from datetime import date

from app.tools import _parse_iso_week_start


def test_valid_iso_week_returns_monday_and_no_error():
    assert _parse_iso_week_start("2026-W07") == (date(2026, 2, 9), None)


def test_malformed_iso_week_returns_error_dict():
    for bad in ("2026-07", "nope", "2026-W99", "2026-Wxx", ""):
        start, error = _parse_iso_week_start(bad)
        assert start is None
        assert error == {"error": f"invalid iso_week {bad!r}; expected format 'YYYY-Wnn'"}
