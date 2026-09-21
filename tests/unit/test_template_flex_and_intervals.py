"""The deterministic interval engine must be USEFUL to the coach, not a single fixed target:
  - a ride that can be either easy Z2 or pushed to threshold (Andrew's Heinous group rides)
    is a `flex` slot: Z2 by default, the optional push described, never counted as a hard day;
  - each hard slot can PICK its interval type (Tue VO2, Sat threshold) instead of only the
    fixed weekly rotation;
  - any bike session can be switched between endurance and a chosen interval type (per-week
    lever, tested at the tool level)."""

from __future__ import annotations

import sys
import uuid
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from swim_coach.models import Athlete  # noqa: E402
from swim_coach.plan import _template_week_sessions, evaluate_week_realism, template_normalization_notes  # noqa: E402

WS = date(2026, 9, 21)


def athlete(template) -> Athlete:
    return Athlete(id=uuid.uuid4(), slug="x", name="X", css_pace_s_per_100m=95.0, zones=None, constraints={},
                   pool_schedule=[], sports=["bike"], ftp_watts=250.0, weekly_template=template)


def build(template, minutes=360.0):
    a = athlete(template)
    return _template_week_sessions(a, WS, minutes, 250.0), a


@pytest.mark.parametrize("word", ["flex", "either", "optional", "flexible", "z2 or threshold"])
def test_flex_words_normalize_to_flex(word) -> None:
    assert athlete({"wed": [{"kind": "bike", "role": word}]}).weekly_template["wed"][0]["role"] == "flex"


def test_a_flex_ride_is_z2_by_default_and_describes_the_optional_push() -> None:
    out, _ = build({"wed": [{"kind": "bike", "role": "flex", "label": "Heinous club ride", "duration_min": 90}]})
    ride = out[0]
    assert ride.intensity.get("zone") == "Z2" and ride.duration_min == 90
    assert "Heinous club ride" in ride.purpose and "optional" in ride.purpose.lower()
    assert "threshold" in ride.structure.lower()  # the default push is a sustained-threshold block


def test_a_flex_ride_can_name_which_push_it_offers() -> None:
    out, _ = build({"sun": [{"kind": "bike", "role": "flex", "intervals": "vo2"}]})
    assert "vo2" in out[0].structure.lower()


def test_a_flex_ride_never_counts_as_a_hard_day() -> None:
    out, _ = build({"tue": [{"kind": "bike", "role": "hard"}], "wed": [{"kind": "bike", "role": "flex"}],
                    "sat": [{"kind": "bike", "role": "hard"}], "sun": [{"kind": "bike", "role": "flex"}]})
    hard = [s for s in out if s.intensity.get("zone") not in (None, "Z2")]
    assert len(hard) == 2
    assert evaluate_week_realism(out) == []


@pytest.mark.parametrize(
    "word, purpose_fragment",
    [("threshold", "sustained threshold"), ("over/unders", "over/unders"), ("vo2", "vo2"),
     ("race pace", "race-pace"), ("openers", "openers")],
)
def test_a_hard_slot_can_pick_its_interval_type(word, purpose_fragment) -> None:
    out, _ = build({"tue": [{"kind": "bike", "role": "hard", "intervals": word}]})
    assert purpose_fragment in out[0].purpose.lower()
    assert out[0].structured is not None


def test_two_hard_days_can_be_two_chosen_types() -> None:
    out, _ = build({"tue": [{"kind": "bike", "role": "hard", "intervals": "vo2"}],
                    "sat": [{"kind": "bike", "role": "hard", "intervals": "threshold"}]})
    by_day = {(s.date - WS).days: s for s in out}
    assert "vo2" in by_day[1].purpose.lower() and "threshold" in by_day[5].purpose.lower()


def test_an_unnamed_hard_slot_still_rotates_and_an_unknown_type_is_noted_not_refused() -> None:
    out, a = build({"tue": [{"kind": "bike", "role": "hard", "intervals": "mystery"}],
                    "sat": [{"kind": "bike", "role": "hard"}]})
    assert len(out) == 2 and out[0].structured is not None
    assert any("mystery" in n for n in template_normalization_notes(a.weekly_template))


def test_intervals_on_a_non_bike_slot_is_ignored_with_a_note() -> None:
    a = athlete({"mon": [{"kind": "yoga", "intervals": "vo2"}]})
    assert "intervals" not in a.weekly_template["mon"][0]
    assert template_normalization_notes(a.weekly_template)


def test_flex_rides_share_the_easy_minutes_not_the_hard_ones() -> None:
    out, _ = build({"tue": [{"kind": "bike", "role": "hard"}], "wed": [{"kind": "bike", "role": "flex"}],
                    "sun": [{"kind": "bike", "role": "flex"}]}, minutes=300.0)
    by_day = {(s.date - WS).days: s for s in out}
    assert by_day[2].duration_min == by_day[6].duration_min and by_day[2].duration_min > by_day[1].duration_min * 0.5
