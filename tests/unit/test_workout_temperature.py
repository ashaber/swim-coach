"""Device temperature on workouts: FIT parse, None-safe model, unit helper, indoor detection."""

from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path

import pytest

from swim_coach.models import Workout
from swim_coach.parse_files import parse_fit
from swim_coach.temperature import c_to_f, f_to_c, is_indoor_detail

FIT_DIR = Path(__file__).parent / "fixtures" / "fit"


def test_parse_fit_reads_session_temperature() -> None:
    draft = parse_fit(FIT_DIR / "real_mtb_race.fit")
    assert (draft.avg_temp_c, draft.min_temp_c, draft.max_temp_c) == (21, 10, 31)


def test_parse_fit_falls_back_to_record_temperature(monkeypatch: pytest.MonkeyPatch) -> None:
    import swim_coach.parse_files as pf

    real = pf._fit_value

    def no_session_temp(frame, name):
        if name in ("avg_temperature", "min_temperature", "max_temperature"):
            return None
        return real(frame, name)

    monkeypatch.setattr(pf, "_fit_value", no_session_temp)
    draft = parse_fit(FIT_DIR / "real_mtb_race.fit")
    assert draft.min_temp_c is not None and draft.max_temp_c is not None and draft.avg_temp_c is not None
    assert draft.min_temp_c <= draft.avg_temp_c <= draft.max_temp_c


def test_draft_carries_temperature_to_workout() -> None:
    w = parse_fit(FIT_DIR / "real_mtb_race.fit").to_workout(athlete_id=uuid.uuid4())
    assert (w.avg_temp_c, w.min_temp_c, w.max_temp_c) == (21, 10, 31)


def test_workout_without_temperature_still_validates() -> None:
    w = Workout.model_validate(
        {"id": str(uuid.uuid4()), "athlete_id": str(uuid.uuid4()), "date": date(2026, 1, 1).isoformat(),
         "sport": "cross_train", "source": "fit", "distance_m": 0, "duration_min": 10}
    )
    assert w.avg_temp_c is None and w.min_temp_c is None and w.max_temp_c is None


def test_temperature_conversion() -> None:
    assert c_to_f(0) == 32.0
    assert c_to_f(21) == pytest.approx(69.8)
    assert f_to_c(50) == pytest.approx(10.0)
    assert f_to_c(c_to_f(13.5)) == pytest.approx(13.5)


@pytest.mark.parametrize(
    ("detail", "indoor"),
    [("cycling/indoor_cycling", True), ("cycling/virtual_activity", True), ("cycling/spin", True),
     ("cycling/mountain", False), ("cycling/road", False), ("cycling", False), (None, False)],
)
def test_is_indoor_detail(detail: str | None, indoor: bool) -> None:
    assert is_indoor_detail(detail) is indoor


def test_device_temp_view_both_units_and_indoor_flag() -> None:
    from swim_coach.temperature import device_temp_view

    assert device_temp_view(None, None, None) is None
    v = device_temp_view(21, 10, 31, "cycling/mountain")
    assert v == {"avg_c": 21.0, "avg_f": 69.8, "min_c": 10.0, "min_f": 50.0, "max_c": 31.0, "max_f": 87.8}
    assert device_temp_view(21, 20, 22, "cycling/indoor_cycling")["indoor"] is True
