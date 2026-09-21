"""/adapt's bike rebuild used to ignore the athlete's day pattern and any weekly
template, so an adapted week silently lost them. It must honour both, at the
ADAPTED (cut/advance) volume, and yield in a taper block."""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from swim_coach.adapt import CUT_VOLUME_FRACTION, adapt_week  # noqa: E402
from swim_coach.plan import generate_week  # noqa: E402
from test_adapt import (  # noqa: E402
    _iso_week, _setup_bike, make_wellness,
)

TEMPLATE = {
    "tue": [{"kind": "bike", "role": "hard"}, {"kind": "strength"}],
    "wed": [{"kind": "bike", "role": "endurance", "label": "Club ride"}],
    "fri": [{"kind": "yoga"}],
    "sun": [{"kind": "bike", "role": "endurance", "label": "Club ride"}],
}


def _cut(athlete, event, macro, current_week, next_iso, next_start, as_of):
    wellness = [
        make_wellness(date=as_of - timedelta(days=i), sleep_quality=1, stress=5, soreness=5, motivation=1)
        for i in range(7)
    ]
    return adapt_week(athlete, event, macro, next_iso, next_start, current_week, [], wellness, as_of, primary_sport="bike")


def test_adapted_week_keeps_the_weekly_template_at_the_cut_volume() -> None:
    athlete, event, macro, current_week, next_iso, next_start, as_of = _setup_bike()
    athlete = athlete.model_copy(update={"weekly_template": TEMPLATE})
    current_week = generate_week(athlete, macro, _iso_week(current_week.sessions[0].date - timedelta(days=current_week.sessions[0].date.weekday())),
                                 current_week.sessions[0].date - timedelta(days=current_week.sessions[0].date.weekday()), primary_sport="bike")

    week = _cut(athlete, event, macro, current_week, next_iso, next_start, as_of)

    days = {(s.date - next_start).days for s in week.sessions}
    assert days == {1, 2, 4, 6}  # Tue, Wed, Fri, Sun -- the template's shape, not the generic split
    assert any(s.sport == "recovery" for s in week.sessions)
    assert any("Club ride" in s.purpose for s in week.sessions)
    bike_min = sum(s.duration_min for s in week.sessions if s.sport == "bike")
    assert bike_min <= week.target_volume_m * 1.15  # the CUT volume, not the un-adjusted baseline
    assert week.draft is True


def test_a_taper_block_does_not_apply_the_template_when_adapting() -> None:
    athlete, event, macro, current_week, next_iso, next_start, as_of = _setup_bike()
    athlete = athlete.model_copy(update={"weekly_template": TEMPLATE})
    taper = next(b for b in macro.blocks if b.name == "taper")
    start = taper.start_date
    current_week = generate_week(athlete, macro, _iso_week(start), start, primary_sport="bike")
    next_start = start + timedelta(weeks=1)
    week = _cut(athlete, event, macro, current_week, _iso_week(next_start), next_start, next_start - timedelta(days=1))
    assert not any("Club ride" in s.purpose for s in week.sessions)  # the template yielded to the taper
    assert not any("yoga" in s.purpose.lower() for s in week.sessions)


def test_adapt_now_honours_the_training_days_pattern_it_used_to_ignore() -> None:
    athlete, event, macro, current_week, next_iso, next_start, as_of = _setup_bike()
    athlete = athlete.model_copy(update={"training_days": {"bike": ["tue", "thu", "sun"]}})

    week = _cut(athlete, event, macro, current_week, next_iso, next_start, as_of)

    bike_days = sorted((s.date - next_start).days for s in week.sessions if s.sport == "bike")
    assert bike_days == [1, 3, 6]


def test_no_pattern_no_template_adapt_is_unchanged() -> None:
    athlete, event, macro, current_week, next_iso, next_start, as_of = _setup_bike()
    week = _cut(athlete, event, macro, current_week, next_iso, next_start, as_of)
    assert week.target_volume_m == round(current_week.target_volume_m * (1 - CUT_VOLUME_FRACTION))
