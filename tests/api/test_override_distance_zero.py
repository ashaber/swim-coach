"""Real incident, prod 2026-10-10: `distance_m: 0` in a patch_week_plan session
override on a bike session reset its duration to 15 min (the swim-pace
re-estimate `max(_duration_min_for_distance(0, css), 15)` ran for a bike)."""

from __future__ import annotations

from test_override_defects import D, _week

from app.tools import _apply_session_overrides


def test_zero_distance_on_a_bike_session_does_not_reset_duration() -> None:
    a, w = _week()
    err, _ = _apply_session_overrides(w, [{"date": D.isoformat(), "sport": "bike", "distance_m": 0}], a)
    assert err is None
    assert w.sessions[0].duration_min == 90.0
    assert not w.sessions[0].distance_m  # treated as unset


def test_zero_distance_with_other_edits_still_applies_them_and_keeps_duration() -> None:
    a, w = _week()
    err, _ = _apply_session_overrides(
        w, [{"date": D.isoformat(), "sport": "bike", "distance_m": 0, "purpose": "steady ride"}], a
    )
    assert err is None
    assert w.sessions[0].purpose == "steady ride"
    assert w.sessions[0].duration_min == 90.0


def test_nonzero_distance_on_a_bike_does_not_rederive_duration_from_swim_css() -> None:
    a, w = _week()
    err, _ = _apply_session_overrides(w, [{"date": D.isoformat(), "sport": "bike", "distance_m": 40000}], a)
    assert err is None
    assert w.sessions[0].duration_min == 90.0


def test_explicit_duration_always_wins_over_distance() -> None:
    a, w = _week()
    err, _ = _apply_session_overrides(
        w, [{"date": D.isoformat(), "sport": "bike", "distance_m": 0, "duration_min": 120}], a
    )
    assert err is None and w.sessions[0].duration_min == 120


def test_swim_distance_override_still_rederives_duration() -> None:
    a, w = _week(sport="swim_pool")
    err, _ = _apply_session_overrides(w, [{"date": D.isoformat(), "sport": "swim_pool", "distance_m": 3000}], a)
    assert err is None
    assert w.sessions[0].duration_min != 90.0 and w.sessions[0].duration_min > 15.0
