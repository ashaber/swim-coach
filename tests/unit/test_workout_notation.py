"""Compact bike workout notation -> WorkoutStructure (engine/swim_coach/workout_notation.py)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from swim_coach.garmin_export import to_garmin_fit_workout
from swim_coach.models import WorkoutRepeat, WorkoutStep
from swim_coach.workout_notation import NotationError, parse_workout_notation
from swim_coach.zwo_export import to_zwo_workout

FTP = 250.0
TIM = "12m ramp 50-70%; 2x[3m 91-96% / 2m 52%]; 3x[20s free / 1m40s 50%]; 5m 50%"
THRESHOLD = "15m 55%; 3x[10m 95-100% / 5m 50%]; 10m 50%"


def test_tims_warmup_structure() -> None:
    s = parse_workout_notation(TIM, ftp_watts=FTP)
    wu, r1, r2, cd = s.items
    assert isinstance(wu, WorkoutStep) and wu.role == "warmup"
    assert wu.duration_value == 720 and (wu.target.low, wu.target.high) == (125, 175)
    assert isinstance(r1, WorkoutRepeat) and r1.count == 2
    work, rec = r1.steps
    assert (work.role, work.duration_value) == ("interval", 180)
    assert (work.target.basis, work.target.low, work.target.high) == ("power_w", 228.0, 240.0)
    assert (rec.role, rec.target.low) == ("recovery", 130.0)
    assert isinstance(r2, WorkoutRepeat) and r2.steps[0].target.basis == "open"
    assert r2.steps[1].duration_value == 100
    assert isinstance(cd, WorkoutStep) and cd.role == "cooldown" and cd.duration_value == 300
    assert all(st.modality == "bike" for st in r1.steps)


def test_durations_watts_zones_labels_roles() -> None:
    s = parse_workout_notation('wu: 1h30m z2 "easy spin"; 20m 230-250W; 90s 300W; cd: 10m z1', ftp_watts=FTP)
    wu, mid, short, cd = s.items
    assert wu.duration_value == 5400 and wu.label == "easy spin" and wu.role == "warmup"
    assert (wu.target.low, wu.target.high) == (138.0, 188.0)  # Coggan Z2 of 250 FTP
    assert (mid.role, mid.target.low, mid.target.high) == ("steady", 230, 250)
    assert short.duration_value == 90 and short.target.low == 300
    assert cd.role == "cooldown"


def test_zone_without_ftp_stays_zone_and_percent_needs_ftp() -> None:
    s = parse_workout_notation("10m z2; 20m z3")
    assert s.items[0].target.basis == "zone" and s.items[0].target.zone == "Z2"
    with pytest.raises(NotationError, match="needs the athlete's FTP"):
        parse_workout_notation("10m 55%")
    with pytest.raises(NotationError, match="Z7"):
        parse_workout_notation("10m Z7")


def test_mid_ramp_gets_ramp_role() -> None:
    s = parse_workout_notation("10m 55%; 20m ramp 60-90%; 10m 50%", ftp_watts=FTP)
    assert s.items[1].role == "ramp"


def test_nested_repeat() -> None:
    s = parse_workout_notation("2x[2x[30s 120% / 30s 50%] / 4m 50%]", ftp_watts=FTP)
    outer = s.items[0]
    assert isinstance(outer.steps[0], WorkoutRepeat) and outer.steps[0].count == 2
    with pytest.raises(NotationError, match="one level"):
        parse_workout_notation("2x[2x[2x[30s 120%] / 1m 50%] / 4m 50%]", ftp_watts=FTP)


@pytest.mark.parametrize(
    "text,fragment",
    [
        ("10m 55%; 3m 9x%", "step 2"),
        ("10m 55%; 3m 9x%", "unknown target '9x%'"),
        ("10x 55%", "malformed repeat"),
        ("3x[3m 90% / ", "malformed repeat"),
        ("10m", "missing target"),
        ("xx: 10m 55%", "unknown role"),
        ("20m ramp 90-60%", "ramp must climb"),
        ("", "empty notation"),
    ],
)
def test_clear_errors(text: str, fragment: str) -> None:
    with pytest.raises(NotationError, match=fragment):
        parse_workout_notation(text, ftp_watts=FTP)


def test_error_reports_char_offset() -> None:
    with pytest.raises(NotationError, match=r"step 2 \(char 9\)"):
        parse_workout_notation("10m 55%; 3m 9x%", ftp_watts=FTP)


def test_threshold_session_exports_to_zwo_and_garmin() -> None:
    s = parse_workout_notation(THRESHOLD, ftp_watts=FTP)
    root = ET.fromstring(to_zwo_workout(s, ftp_watts=FTP, name="t"))
    tags = [c.tag for c in root.find("workout")]
    assert tags == ["Warmup", "IntervalsT", "Cooldown"]
    interval = root.find("workout/IntervalsT")
    assert interval.get("Repeat") == "3" and interval.get("OnDuration") == "600"
    assert to_garmin_fit_workout(s, "bike", "t")


def test_tims_warmup_exports_to_garmin() -> None:
    s = parse_workout_notation(TIM, ftp_watts=FTP)
    assert to_garmin_fit_workout(s, "bike", "tim")
