"""Tests for swim_coach.zwo_export: encoding a resolved `WorkoutStructure`
(bike modality) as a MyWhoosh/Zwift-compatible `.zwo` XML file.

Ported (structure->ZWO direction only) from the sibling `workout-to-zwo`
Claude Code skill (`/home/ashaber/projects/workout-to-zwo/SKILL.md`) -- see
that skill's "Step 4/5" element-mapping table and worked example, which
every assertion here is checked against verbatim (element names, attribute
casing, the default warm-up/cool-down values, 2-decimal power formatting).

No LLM calls, no network access. Every test round-trips the produced XML
string through stdlib `xml.etree.ElementTree` (a genuinely independent XML
parser) to prove the output is well-formed, not just "didn't raise while
building a string."
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from swim_coach.models import WorkoutRepeat, WorkoutStep, WorkoutStructure, WorkoutTarget
from swim_coach.zwo_export import to_zwo_workout


def _parse(xml_str: str) -> ET.Element:
    assert xml_str.startswith('<?xml version="1.0" encoding="utf-8"?>')
    return ET.fromstring(xml_str)


def _workout_children(root: ET.Element) -> list[ET.Element]:
    workout = root.find("workout")
    assert workout is not None
    return list(workout)


# --- steady-state Z2 ride, with explicit warm-up/cool-down -------------------


def test_steady_state_z2_ride_produces_valid_zwo():
    structured = WorkoutStructure(
        items=[
            WorkoutStep(
                label="Warm-up",
                role="warmup",
                duration_kind="time_s",
                duration_value=300,
                target=WorkoutTarget(basis="power_w", low=100.0, high=150.0),
                modality="bike",
            ),
            WorkoutStep(
                label="Steady Z2",
                role="steady",
                duration_kind="time_s",
                duration_value=1800,
                target=WorkoutTarget(basis="power_w", low=180.0, high=180.0),
                modality="bike",
            ),
            WorkoutStep(
                label="Cool-down",
                role="cooldown",
                duration_kind="time_s",
                duration_value=300,
                target=WorkoutTarget(basis="power_w", low=100.0, high=150.0),
                modality="bike",
            ),
        ]
    )
    xml_str = to_zwo_workout(structured, ftp_watts=250.0, name="Z2 Endurance")
    root = _parse(xml_str)

    assert root.tag == "workout_file"
    assert root.find("n").text == "Z2 Endurance"
    # ElementTree reports an empty element's .text as None, not "" -- a
    # parser quirk, not a claim about what's actually in the XML (confirmed
    # by also checking the raw string below).
    assert root.find("author").text is None
    assert "<author></author>" in xml_str
    assert root.find("sportType").text == "bike"
    assert root.find("ftpOverride").text == "250"

    children = _workout_children(root)
    assert [c.tag for c in children] == ["Warmup", "SteadyState", "Cooldown"]

    warmup = children[0]
    assert warmup.attrib["Duration"] == "300"
    assert warmup.attrib["PowerLow"] == "0.40"
    assert warmup.attrib["PowerHigh"] == "0.60"

    steady = children[1]
    assert steady.attrib["Duration"] == "1800"
    assert steady.attrib["Power"] == "0.72"

    cooldown = children[2]
    assert cooldown.attrib["Duration"] == "300"
    assert cooldown.attrib["PowerHigh"] == "0.60"
    assert cooldown.attrib["PowerLow"] == "0.40"


# --- interval session with repeats -------------------------------------------


def test_interval_session_with_repeats_produces_intervalst():
    structured = WorkoutStructure(
        items=[
            WorkoutStep(
                label="Warm-up",
                role="warmup",
                duration_kind="time_s",
                duration_value=180,
                target=WorkoutTarget(basis="power_w", low=100.0, high=150.0),
                modality="bike",
            ),
            WorkoutRepeat(
                repeat_mode="count",
                count=3,
                steps=[
                    WorkoutStep(
                        label="Sweet Spot",
                        role="interval",
                        duration_kind="time_s",
                        duration_value=720,
                        target=WorkoutTarget(basis="power_w", low=227.5, high=227.5),
                        modality="bike",
                    ),
                    WorkoutStep(
                        label="Recovery",
                        role="rest",
                        duration_kind="time_s",
                        duration_value=180,
                        target=WorkoutTarget(basis="power_w", low=137.5, high=137.5),
                        modality="bike",
                    ),
                ],
            ),
            WorkoutStep(
                label="Cool-down",
                role="cooldown",
                duration_kind="time_s",
                duration_value=180,
                target=WorkoutTarget(basis="power_w", low=100.0, high=150.0),
                modality="bike",
            ),
        ]
    )
    xml_str = to_zwo_workout(structured, ftp_watts=250.0, name="Carson", author="")
    root = _parse(xml_str)
    children = _workout_children(root)
    assert [c.tag for c in children] == ["Warmup", "IntervalsT", "Cooldown"]

    intervals = children[1]
    assert intervals.attrib["Repeat"] == "3"
    assert intervals.attrib["OnDuration"] == "720"
    assert intervals.attrib["OffDuration"] == "180"
    assert intervals.attrib["OnPower"] == "0.91"
    assert intervals.attrib["OffPower"] == "0.55"


# --- warm-up/cool-down-less input needing the defaults applied ---------------


def test_missing_warmup_and_cooldown_get_3_minute_defaults():
    structured = WorkoutStructure(
        items=[
            WorkoutStep(
                label="Steady",
                role="steady",
                duration_kind="time_s",
                duration_value=1200,
                target=WorkoutTarget(basis="power_w", low=180.0, high=180.0),
                modality="bike",
            ),
        ]
    )
    xml_str = to_zwo_workout(structured, ftp_watts=250.0, name="No warmup")
    root = _parse(xml_str)
    children = _workout_children(root)
    assert [c.tag for c in children] == ["Warmup", "SteadyState", "Cooldown"]

    warmup = children[0]
    assert warmup.attrib["Duration"] == "180"
    assert warmup.attrib["PowerLow"] == "0.40"
    assert warmup.attrib["PowerHigh"] == "0.60"

    cooldown = children[2]
    assert cooldown.attrib["Duration"] == "180"
    assert cooldown.attrib["PowerLow"] == "0.30"
    assert cooldown.attrib["PowerHigh"] == "0.55"


def test_explicit_short_warmup_is_not_overridden():
    # "already has warmup/cooldown but very short (<3min)" edge case from the
    # sibling skill: use the stated values verbatim, do not extend them.
    structured = WorkoutStructure(
        items=[
            WorkoutStep(
                label="Warm-up",
                role="warmup",
                duration_kind="time_s",
                duration_value=60,
                target=WorkoutTarget(basis="power_w", low=100.0, high=150.0),
                modality="bike",
            ),
            WorkoutStep(
                label="Steady",
                role="steady",
                duration_kind="time_s",
                duration_value=1200,
                target=WorkoutTarget(basis="power_w", low=180.0, high=180.0),
                modality="bike",
            ),
        ]
    )
    xml_str = to_zwo_workout(structured, ftp_watts=250.0, name="Short warmup")
    root = _parse(xml_str)
    children = _workout_children(root)
    assert [c.tag for c in children] == ["Warmup", "SteadyState", "Cooldown"]
    assert children[0].attrib["Duration"] == "60"
    # cooldown still defaulted since none was given
    assert children[2].attrib["Duration"] == "180"


# --- zone-basis targets (no absolute watts on the step itself) ---------------


def test_zone_basis_target_resolves_via_bike_zone_table():
    structured = WorkoutStructure(
        items=[
            WorkoutStep(
                label="Endurance",
                role="steady",
                duration_kind="time_s",
                duration_value=1800,
                target=WorkoutTarget(basis="zone", zone="Z2"),
                modality="bike",
            ),
        ]
    )
    xml_str = to_zwo_workout(structured, ftp_watts=200.0, name="Zone test")
    root = _parse(xml_str)
    children = _workout_children(root)
    # Z2 spans 55%-75% FTP (library/23-cycling-training.md) -> a real range,
    # not a single fixed value -> Ramp, per the sibling skill's own mapping
    # table ("power progressions ... not at start/end" -- mid-workout range).
    assert children[1].tag == "Ramp"
    assert children[1].attrib["PowerLow"] == "0.55"
    assert children[1].attrib["PowerHigh"] == "0.75"


# --- untargeted / rpe-only block -> FreeRide ---------------------------------


def test_untargeted_block_becomes_freeride():
    structured = WorkoutStructure(
        items=[
            WorkoutStep(
                label="Warm-up",
                role="warmup",
                duration_kind="time_s",
                duration_value=180,
                target=WorkoutTarget(basis="power_w", low=100.0, high=150.0),
                modality="bike",
            ),
            WorkoutStep(
                label="Easy spin, RPE-guided",
                role="recovery",
                duration_kind="time_s",
                duration_value=600,
                target=None,
                modality="bike",
            ),
            WorkoutStep(
                label="Cool-down",
                role="cooldown",
                duration_kind="time_s",
                duration_value=180,
                target=WorkoutTarget(basis="power_w", low=100.0, high=150.0),
                modality="bike",
            ),
        ]
    )
    xml_str = to_zwo_workout(structured, ftp_watts=250.0, name="Freeride test")
    root = _parse(xml_str)
    children = _workout_children(root)
    assert children[1].tag == "FreeRide"
    assert children[1].attrib["Duration"] == "600"


def test_rpe_basis_target_also_becomes_freeride():
    structured = WorkoutStructure(
        items=[
            WorkoutStep(
                label="Warm-up",
                role="warmup",
                duration_kind="time_s",
                duration_value=180,
                target=WorkoutTarget(basis="power_w", low=100.0, high=150.0),
                modality="bike",
            ),
            WorkoutStep(
                label="RPE-guided block",
                role="steady",
                duration_kind="time_s",
                duration_value=600,
                target=WorkoutTarget(basis="rpe", low=3, high=5),
                modality="bike",
            ),
            WorkoutStep(
                label="Cool-down",
                role="cooldown",
                duration_kind="time_s",
                duration_value=180,
                target=WorkoutTarget(basis="power_w", low=100.0, high=150.0),
                modality="bike",
            ),
        ]
    )
    xml_str = to_zwo_workout(structured, ftp_watts=250.0, name="RPE test")
    root = _parse(xml_str)
    children = _workout_children(root)
    assert children[1].tag == "FreeRide"


# --- role="open" annotation steps are skipped, matching garmin_export -------


def test_open_role_step_is_not_exported():
    structured = WorkoutStructure(
        items=[
            WorkoutStep(
                label="Why: Z2 aerobic emphasis",
                role="open",
                duration_kind="open",
                modality="bike",
            ),
            WorkoutStep(
                label="Steady",
                role="steady",
                duration_kind="time_s",
                duration_value=1200,
                target=WorkoutTarget(basis="power_w", low=180.0, high=180.0),
                modality="bike",
            ),
        ]
    )
    xml_str = to_zwo_workout(structured, ftp_watts=250.0, name="Open role test")
    root = _parse(xml_str)
    children = _workout_children(root)
    # just the default warmup + the real steady block + default cooldown
    assert [c.tag for c in children] == ["Warmup", "SteadyState", "Cooldown"]


# --- description / author passthrough ----------------------------------------


def test_description_and_author_are_included():
    structured = WorkoutStructure(
        items=[
            WorkoutStep(
                label="Steady",
                role="steady",
                duration_kind="time_s",
                duration_value=1200,
                target=WorkoutTarget(basis="power_w", low=180.0, high=180.0),
                modality="bike",
            ),
        ]
    )
    xml_str = to_zwo_workout(
        structured,
        ftp_watts=250.0,
        name="Named",
        author="Coach",
        description="A test ride.",
    )
    root = _parse(xml_str)
    assert root.find("author").text == "Coach"
    assert root.find("description").text == "A test ride."


# --- error cases --------------------------------------------------------------


def test_repeat_with_more_than_two_children_raises():
    structured = WorkoutStructure(
        items=[
            WorkoutRepeat(
                repeat_mode="count",
                count=3,
                steps=[
                    WorkoutStep(
                        label="on",
                        role="interval",
                        duration_kind="time_s",
                        duration_value=60,
                        target=WorkoutTarget(basis="power_w", low=200.0, high=200.0),
                        modality="bike",
                    ),
                    WorkoutStep(
                        label="off",
                        role="rest",
                        duration_kind="time_s",
                        duration_value=30,
                        target=WorkoutTarget(basis="power_w", low=100.0, high=100.0),
                        modality="bike",
                    ),
                    WorkoutStep(
                        label="extra",
                        role="rest",
                        duration_kind="time_s",
                        duration_value=30,
                        target=WorkoutTarget(basis="power_w", low=100.0, high=100.0),
                        modality="bike",
                    ),
                ],
            ),
        ]
    )
    with pytest.raises(ValueError, match="on/off"):
        to_zwo_workout(structured, ftp_watts=250.0, name="bad repeat")


def test_non_count_repeat_mode_raises():
    structured = WorkoutStructure(
        items=[
            WorkoutRepeat(
                repeat_mode="amrap",
                duration_s=600.0,
                steps=[
                    WorkoutStep(
                        label="on",
                        role="interval",
                        duration_kind="time_s",
                        duration_value=60,
                        target=WorkoutTarget(basis="power_w", low=200.0, high=200.0),
                        modality="bike",
                    ),
                ],
            ),
        ]
    )
    with pytest.raises(ValueError, match="count"):
        to_zwo_workout(structured, ftp_watts=250.0, name="bad repeat mode")


def test_non_time_duration_kind_raises():
    structured = WorkoutStructure(
        items=[
            WorkoutStep(
                label="bad",
                role="steady",
                duration_kind="distance_m",
                duration_value=1000,
                target=WorkoutTarget(basis="power_w", low=180.0, high=180.0),
                modality="bike",
            ),
        ]
    )
    with pytest.raises(ValueError, match="time"):
        to_zwo_workout(structured, ftp_watts=250.0, name="bad duration kind")
