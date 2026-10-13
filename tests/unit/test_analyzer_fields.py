"""Each sport's analyzer owns its `WorkoutAnalytics` fields and its coach view."""

from __future__ import annotations

from typing import get_args

from swim_coach.analysis import (
    ANALYZERS,
    BASE_FIELDS,
    BIKE_FIELDS,
    DEFAULT_ANALYZER,
    SWIM_FIELDS,
    analytics_for_coach,
)
from swim_coach.models import Sport, WorkoutAnalytics


def _all_analyzers():
    return {id(a): a for a in [*ANALYZERS.values(), DEFAULT_ANALYZER]}.values()


def test_every_analytics_field_is_base_or_owned():
    owned = set(BASE_FIELDS).union(*(a.fields for a in _all_analyzers()))
    assert set(WorkoutAnalytics.model_fields) == owned


def test_base_and_own_fields_are_disjoint():
    for a in _all_analyzers():
        assert not (BASE_FIELDS & a.fields), type(a).__name__
    assert not (SWIM_FIELDS & BIKE_FIELDS)


def test_registry_owners():
    assert ANALYZERS["swim_pool"].fields == SWIM_FIELDS == ANALYZERS["swim_ow"].fields
    assert ANALYZERS["bike"].fields == BIKE_FIELDS
    assert set(get_args(Sport)) >= set(ANALYZERS)


_FULL = WorkoutAnalytics(
    cardiac_drift_pct=2.0,
    elapsed_min=60.0,
    split_label="even",
    first_half_pace_s_per_100m=95.0,
    swolf_first_quarter=40.0,
    avg_power_w=200.0,
    normalized_power_w=210.0,
)


def test_swim_view_has_swim_fields_and_no_power():
    out = analytics_for_coach(_FULL, sport="swim_ow")
    assert out == {
        "cardiac_drift_pct": 2.0,
        "elapsed_min": 60.0,
        "split_label": "even",
        "first_half_pace_s_per_100m": 95.0,
        "swolf_first_quarter": 40.0,
    }


def test_bike_view_has_power_and_no_swim():
    out = analytics_for_coach(_FULL, sport="bike")
    assert out == {"cardiac_drift_pct": 2.0, "elapsed_min": 60.0, "avg_power_w": 200.0, "normalized_power_w": 210.0}


def test_other_sports_get_base_only():
    for sport in ("strength", "recovery", "cross_train"):
        assert analytics_for_coach(_FULL, sport=sport) == {"cardiac_drift_pct": 2.0, "elapsed_min": 60.0}


def test_none_analytics_is_none():
    assert analytics_for_coach(None, sport="bike") is None
