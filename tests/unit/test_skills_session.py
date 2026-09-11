"""Tests for the cyclocross skills-day session content
(`engine/cx-skills-day-content`).

A "CX skills" day is bike-handling practice, not a training-load session:
~10-min drill blocks at RPE 5-7, distance/power nominal. See
`library/27-cyclocross-skills.md`.

No LLM calls, no network -- pure model construction + arithmetic.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from swim_coach.models import Athlete, Event
from swim_coach.plan import (
    BIKE_SESSIONS_PER_WEEK,
    SKILLS_BLOCK_MIN,
    SKILLS_BLOCKS_PER_SESSION,
    SKILLS_COOLDOWN_MIN,
    SKILLS_RPE_HIGH,
    SKILLS_RPE_LOW,
    SKILLS_WARMUP_MIN,
    STRENGTH_SESSIONS_PER_WEEK,
    _select_skills_drills,
    _skills_session_structure,
    _skills_sessions,
    generate_week,
    scaffold_macro,
)

ATHLETE_ID = uuid.uuid4()
START = date(2026, 1, 5)  # a Monday -- matches tests/unit/test_plan.py


# --- local fixtures (kept independent of tests/unit/test_plan.py) ----------


def make_athlete(**overrides) -> Athlete:
    data = dict(
        id=ATHLETE_ID,
        slug="wife",
        name="Jane Doe",
        css_pace_s_per_100m=95.0,
        zones=None,
        constraints={},
        pool_schedule=["tue", "thu", "fri"],
    )
    data.update(overrides)
    return Athlete(**data)


def make_event(**overrides) -> Event:
    data = dict(
        id=uuid.uuid4(),
        athlete_id=ATHLETE_ID,
        name="Catalina Channel",
        event_date=START + timedelta(weeks=24),
        distance_m=20000,
        water_temp_c=18.0,
        wetsuit=False,
        priority="A",
    )
    data.update(overrides)
    return Event(**data)


def _iso_week(d: date) -> str:
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def _leaf_steps(items):
    for item in items:
        if item.kind == "step":
            yield item
        else:
            yield from item.steps


def _make_bike_macro(**event_overrides):
    athlete = make_athlete(sports=["bike"])
    event = make_event(
        event_date=START + timedelta(weeks=24),
        target_metric="duration_min",
        distance_m=None,
        target_value=300.0,
        **event_overrides,
    )
    macro = scaffold_macro(
        athlete, event, START, current_weekly_volume_m=200, peak_weekly_volume_m=600
    )
    return athlete, event, macro


# --- drill rotation -------------------------------------------------------


def test_select_skills_drills_rotates_and_covers_catalogue():
    s0 = _select_skills_drills(0)
    s1 = _select_skills_drills(1)
    assert len(s0) == SKILLS_BLOCKS_PER_SESSION
    assert s0 != s1, "consecutive skills sessions must not be identical"
    seen: set[str] = set()
    for i in range(8):
        for name, _cue in _select_skills_drills(i):
            seen.add(name)
    assert len(seen) >= 5, "every drill in the catalogue should come round"


def test_select_skills_drills_is_deterministic():
    assert _select_skills_drills(3) == _select_skills_drills(3)


# --- structure content -------------------------------------------------------


def test_skills_session_structure_has_real_handling_drills():
    structured = _skills_session_structure(0)
    labels = " ".join(step.label.lower() for step in _leaf_steps(structured.items))
    for token in ("dismount", "remount", "barrier", "corner"):
        assert token in labels, f"expected {token!r} in skills structure, got: {labels!r}"
    # run-ups aren't in every rotation window, but must appear across the set
    all_labels = " ".join(
        step.label.lower()
        for i in range(5)
        for step in _leaf_steps(_skills_session_structure(i).items)
    )
    assert "run-up" in all_labels


def test_skills_session_structure_is_not_a_threshold_or_vo2_block():
    structured = _skills_session_structure(0)
    for step in _leaf_steps(structured.items):
        if step.target is not None:
            assert step.target.basis == "rpe", (
                f"skills step {step.label!r} has a non-RPE target "
                f"(basis={step.target.basis!r})"
            )
        low = step.label.lower()
        assert "threshold" not in low
        assert "vo2" not in low
        assert "ftp" not in low
    drill_targets = [
        s.target
        for s in _leaf_steps(structured.items)
        if s.role == "steady" and s.target is not None
    ]
    assert drill_targets, "expected at least one RPE drill block"
    for t in drill_targets:
        assert t.low >= SKILLS_RPE_LOW
        assert t.high <= SKILLS_RPE_HIGH


def test_skills_session_structure_block_count_and_duration():
    structured = _skills_session_structure(0)
    drill_steps = [s for s in _leaf_steps(structured.items) if s.role == "steady"]
    assert len(drill_steps) == SKILLS_BLOCKS_PER_SESSION
    for s in drill_steps:
        assert s.duration_kind == "time_s"
        assert s.duration_value == pytest.approx(SKILLS_BLOCK_MIN * 60)


def test_skills_session_structure_rotates_with_index():
    a = _skills_session_structure(0)
    b = _skills_session_structure(1)
    labels_a = [s.label for s in _leaf_steps(a.items) if s.role == "steady"]
    labels_b = [s.label for s in _leaf_steps(b.items) if s.role == "steady"]
    assert labels_a != labels_b


# --- session objects -------------------------------------------------------


def test_skills_sessions_purpose_intensity_duration():
    athlete = make_athlete(sports=["bike"])
    sessions = _skills_sessions(athlete, START, [1, 3])
    assert len(sessions) == 2
    assert [s.date for s in sessions] == [
        START + timedelta(days=1),
        START + timedelta(days=3),
    ]
    expected = (
        SKILLS_WARMUP_MIN + SKILLS_BLOCKS_PER_SESSION * SKILLS_BLOCK_MIN + SKILLS_COOLDOWN_MIN
    )
    for s in sessions:
        assert s.sport == "bike"
        assert s.source == "ai_coach"
        assert s.distance_m is None
        assert s.status == "planned"
        assert s.structured is not None
        assert "skills" in s.purpose.lower()
        assert s.intensity.get("anchor") == "rpe"
        assert "ftp_watts_lo" not in s.intensity
        assert "ftp_watts_hi" not in s.intensity
        assert s.intensity.get("zone") == "Z2"
        assert s.duration_min == pytest.approx(expected)


# --- generate_week wiring: training_days["skills"] ------------------------


def test_generate_week_bike_places_skills_days_from_training_days():
    athlete, _event, macro = _make_bike_macro()
    athlete = athlete.model_copy(update={"training_days": {"skills": ["mon", "fri"]}})
    week_start = macro.blocks[0].start_date

    week = generate_week(
        athlete, macro, _iso_week(week_start), week_start, primary_sport="bike"
    )
    skills = [
        s for s in week.sessions if s.purpose.lower().startswith("cyclocross skills")
    ]
    assert len(skills) == 2
    offsets = sorted((s.date - week_start).days for s in skills)
    assert offsets == [0, 4]  # Monday + Friday
    for s in skills:
        labels = " ".join(step.label.lower() for step in _leaf_steps(s.structured.items))
        assert "dismount" in labels and "barrier" in labels and "corner" in labels
        for step in _leaf_steps(s.structured.items):
            if step.target is not None:
                assert step.target.basis == "rpe"


def test_generate_week_bike_skills_days_are_additive():
    athlete, _event, macro = _make_bike_macro()
    week_start = macro.blocks[0].start_date

    baseline = generate_week(
        athlete, macro, _iso_week(week_start), week_start, primary_sport="bike"
    )
    with_skills = generate_week(
        athlete.model_copy(update={"training_days": {"skills": ["wed"]}}),
        macro,
        _iso_week(week_start),
        week_start,
        primary_sport="bike",
    )
    n_skills = len(
        [s for s in with_skills.sessions if s.purpose.lower().startswith("cyclocross skills")]
    )
    assert n_skills == 1
    assert len(with_skills.sessions) == len(baseline.sessions) + 1
    non_skills_bike = [
        s
        for s in with_skills.sessions
        if s.sport == "bike" and not s.purpose.lower().startswith("cyclocross skills")
    ]
    assert len(non_skills_bike) == len([s for s in baseline.sessions if s.sport == "bike"])


# --- regression: byte-identical when no "skills" pattern is set -----------


def _norm(week) -> object:
    def strip(obj):
        if isinstance(obj, dict):
            return {k: strip(v) for k, v in obj.items() if k != "id"}
        if isinstance(obj, list):
            return [strip(x) for x in obj]
        return obj

    return strip(week.model_dump(mode="json"))


def test_generate_week_bike_byte_identical_without_skills_pattern():
    athlete, _event, macro = _make_bike_macro()
    week_start = macro.blocks[0].start_date

    def run(a: Athlete):
        return _norm(
            generate_week(a, macro, _iso_week(week_start), week_start, primary_sport="bike")
        )

    base = run(athlete)
    assert run(athlete) == base  # determinism
    assert run(athlete.model_copy(update={"training_days": None})) == base
    assert run(athlete.model_copy(update={"training_days": {}})) == base
    # engine/week-generator-realism (#174, merged) consumes the "bike" key
    # for day placement, so a bike pattern is no longer byte-identical to no
    # pattern -- but with no "skills" key it must still add zero cyclocross
    # skills sessions.
    bike_only = run(athlete.model_copy(update={"training_days": {"bike": ["tue", "thu"]}}))
    assert not any(
        "cyclocross skills" in (s.get("purpose") or "") for s in bike_only["sessions"]
    )


def test_generate_week_swim_byte_identical_without_skills_pattern():
    athlete = make_athlete()
    event = make_event()
    macro = scaffold_macro(
        athlete, event, START, current_weekly_volume_m=6000, peak_weekly_volume_m=20000
    )
    week_start = macro.blocks[0].start_date

    def run(a: Athlete):
        return _norm(generate_week(a, macro, _iso_week(week_start), week_start))

    base = run(athlete)
    assert run(athlete.model_copy(update={"training_days": None})) == base
    assert run(
        athlete.model_copy(update={"training_days": {"skills": ["mon", "wed"]}})
    ) == base, "a swim-primary week must ignore training_days['skills'] entirely"
