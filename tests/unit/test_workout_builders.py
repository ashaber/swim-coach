"""Workout compiler: coach intent in, exact structured workout out (engine/swim_coach/workout_builders)."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from swim_coach.garmin_export import to_garmin_fit_workout
from swim_coach.models import Athlete, WorkoutRepeat, WorkoutStep
from swim_coach.stimulus import planned_dose
from swim_coach.workout_builders import (
    CompiledWorkout,
    WorkoutIntent,
    builders_for,
    compile_workout,
    get_builder,
    list_archetypes,
)
from swim_coach.workout_builders.registry import all_builders
from swim_coach.workout_templates import render_prose


def _athlete(**over) -> Athlete:
    data = {"id": uuid.uuid4(), "slug": "t", "name": "T", "css_pace_s_per_100m": 95.0, "ftp_watts": 250.0}
    data.update(over)
    return Athlete(**data)


def _leaves(items) -> list[WorkoutStep]:
    out: list[WorkoutStep] = []
    for item in items:
        out.extend(_leaves(item.steps) if isinstance(item, WorkoutRepeat) else [item])
    return out


def _repeats(structured) -> list[WorkoutRepeat]:
    return [i for i in structured.items if isinstance(i, WorkoutRepeat)]


def _intent_for(builder) -> WorkoutIntent:
    """A default, in-range intent for any registered archetype."""
    sport = sorted(builder.sports)[0]
    if "total_distance_m" in builder.params:
        return WorkoutIntent(sport=sport, archetype=builder.archetype, total_distance_m=3000)
    return WorkoutIntent(sport=sport, archetype=builder.archetype, total_duration_min=60)


# --- intent validation -----------------------------------------------------------------------


def test_intent_requires_a_size():
    with pytest.raises(ValidationError):
        WorkoutIntent(sport="bike", archetype="endurance")


def test_intent_accepts_explicit_reps_by_size_alone():
    WorkoutIntent(sport="bike", archetype="sustained_threshold", reps=3, rep_duration_s=720)
    WorkoutIntent(sport="swim_pool", archetype="css_threshold", reps=8, rep_distance_m=200)


def test_intent_rejects_reps_without_a_rep_size_or_total():
    with pytest.raises(ValidationError):
        WorkoutIntent(sport="bike", archetype="sustained_threshold", reps=3)


# --- registry --------------------------------------------------------------------------------


def test_registry_lists_bike_and_swim_archetypes():
    rows = list_archetypes()
    sports = {r["sport"] for r in rows}
    assert {"bike", "swim"} <= sports
    bike = {r["archetype"] for r in list_archetypes("bike")}
    assert {
        "sustained_threshold", "over_unders", "short_short_vo2", "race_pace", "openers",
        "endurance", "prerace_primer", "midweek_quality", "ramp_test", "test_2x20",
    } <= bike
    swim = {r["archetype"] for r in list_archetypes("swim")}
    assert {"endurance", "css_threshold"} <= swim
    assert any(a.startswith("ow_") for a in swim)
    assert any(a.startswith("pool_") for a in swim)


def test_list_archetypes_rows_are_compact_and_complete():
    for row in list_archetypes():
        assert set(row) >= {"sport", "archetype", "kind", "summary", "params"}
        assert "\n" not in row["summary"] and len(row["summary"]) <= 160


def test_builders_for_accepts_profile_name_or_session_sport():
    assert builders_for("swim_pool") and builders_for("swim") and builders_for("bike")
    pool_only = {b.archetype for b in builders_for("swim_pool")}
    ow_only = {b.archetype for b in builders_for("swim_ow")}
    assert pool_only != ow_only


def test_unknown_archetype_error_lists_valid_ones():
    with pytest.raises(ValueError) as exc:
        compile_workout(WorkoutIntent(sport="bike", archetype="nope", total_duration_min=60), _athlete())
    assert "sustained_threshold" in str(exc.value) and "over_unders" in str(exc.value)


def test_unknown_sport_error_lists_sports():
    with pytest.raises(ValueError) as exc:
        compile_workout(WorkoutIntent(sport="strength", archetype="x", total_duration_min=60), _athlete())
    assert "bike" in str(exc.value) and "swim" in str(exc.value)


def test_get_builder_rejects_archetype_of_another_swim_discipline():
    pool = next(b for b in builders_for("swim_pool") if b.archetype.startswith("pool_"))
    with pytest.raises(ValueError):
        get_builder("swim_ow", pool.archetype)


# --- every registered archetype compiles, and delivers what it declares ----------------------


@pytest.mark.parametrize("builder", all_builders(), ids=lambda b: f"{b.sport_group}:{b.archetype}")
def test_every_archetype_compiles_and_measures_as_declared(builder):
    compiled = compile_workout(_intent_for(builder), _athlete())
    assert isinstance(compiled, CompiledWorkout)
    assert compiled.structured.items
    assert compiled.duration_min > 0
    assert compiled.dose is not None, builder.archetype
    assert builder.delivers(compiled.dose.kind), (builder.archetype, builder.kind, compiled.dose.kind)
    assert compiled.intensity.get("zone")


@pytest.mark.parametrize("builder", all_builders(), ids=lambda b: f"{b.sport_group}:{b.archetype}")
def test_every_archetype_is_deterministic_and_prose_matches(builder):
    athlete = _athlete()
    a = compile_workout(_intent_for(builder), athlete)
    b = compile_workout(_intent_for(builder), athlete)
    assert a.model_dump() == b.model_dump()
    assert a.prose.strip()
    assert a.prose == render_prose(a.structured)


def test_dose_is_the_stimulus_modules_own_measure():
    athlete = _athlete()
    c = compile_workout(
        WorkoutIntent(sport="bike", archetype="sustained_threshold", total_duration_min=60), athlete
    )
    assert c.dose.kind == "threshold" and c.dose.work_s and c.dose.rep_count >= 2
    assert c.dose.confidence == "structured"


# --- bike: explicit reps, honesty ------------------------------------------------------------


def test_bike_threshold_auto_fit_matches_the_legacy_builder():
    from swim_coach.workout_builders.bike import _bike_hard_session_structure

    c = compile_workout(
        WorkoutIntent(sport="bike", archetype="sustained_threshold", total_duration_min=75), _athlete()
    )
    assert c.structured == _bike_hard_session_structure("sustained_threshold", 75, 250.0)
    assert c.adjustments == []
    assert c.duration_min == pytest.approx(75)


def test_bike_explicit_reps_are_built_exactly_and_total_grows_with_a_record():
    c = compile_workout(
        WorkoutIntent(
            sport="bike", archetype="sustained_threshold", reps=5, rep_duration_s=720, rest_s=300,
            total_duration_min=60,
        ),
        _athlete(),
    )
    repeat = _repeats(c.structured)[0]
    assert repeat.count == 5
    work = [s for s in repeat.steps if s.role == "interval"][0]
    assert work.duration_value == 720
    assert c.duration_min > 60
    assert any("asked 60" in a and "built" in a for a in c.adjustments)


def test_bike_explicit_reps_fill_a_longer_total_with_easy_spin_and_say_so():
    c = compile_workout(
        WorkoutIntent(
            sport="bike", archetype="sustained_threshold", reps=3, rep_duration_s=720, total_duration_min=90
        ),
        _athlete(),
    )
    assert c.duration_min == pytest.approx(90)
    assert _repeats(c.structured)[0].count == 3
    assert any("easy spin" in a for a in c.adjustments)


def test_bike_out_of_range_reps_are_clamped_and_recorded_not_silent():
    c = compile_workout(
        WorkoutIntent(sport="bike", archetype="sustained_threshold", reps=20, rep_duration_s=600), _athlete()
    )
    count = _repeats(c.structured)[0].count
    assert count < 20
    assert any("asked reps=20" in a and f"built {count}" in a for a in c.adjustments)


def test_bike_out_of_range_rep_duration_is_clamped_and_recorded():
    c = compile_workout(
        WorkoutIntent(sport="bike", archetype="sustained_threshold", reps=3, rep_duration_s=60), _athlete()
    )
    work = [s for s in _leaves(c.structured.items) if s.role == "interval"][0]
    assert work.duration_value > 60
    assert any("rep_duration_s" in a for a in c.adjustments)


def test_fields_a_builder_does_not_honour_are_reported_not_dropped():
    c = compile_workout(
        WorkoutIntent(sport="bike", archetype="prerace_primer", total_duration_min=60, target_zone="Z3"),
        _athlete(),
    )
    assert any("target_zone" in a and "not used" in a for a in c.adjustments)
    assert any("total_duration_min" in a for a in c.adjustments)


def test_bike_over_unders_and_short_short_explicit_counts():
    ou = compile_workout(
        WorkoutIntent(sport="bike", archetype="over_unders", sets=3, reps=3, rep_duration_s=120, rest_s=240),
        _athlete(),
    )
    blocks = _repeats(ou.structured)
    assert len(blocks) == 3 and all(b.count == 3 for b in blocks)
    ss = compile_workout(
        WorkoutIntent(sport="bike", archetype="short_short_vo2", sets=2, reps=12, rep_duration_s=40, rest_s=20),
        _athlete(),
    )
    sets = _repeats(ss.structured)
    assert len(sets) == 2 and all(s.count == 12 for s in sets)
    assert [s.duration_value for s in sets[0].steps] == [40, 20]


def test_bike_target_zone_is_honoured_for_threshold_and_endurance():
    c = compile_workout(
        WorkoutIntent(sport="bike", archetype="endurance", total_duration_min=90, target_zone="Z1"), _athlete()
    )
    assert c.intensity["zone"] == "Z1"
    t = compile_workout(
        WorkoutIntent(sport="bike", archetype="sustained_threshold", total_duration_min=60, target_zone="Z3"),
        _athlete(),
    )
    assert t.intensity["zone"] == "Z3" and t.dose.kind == "tempo"


def test_bike_without_ftp_uses_zone_targets():
    c = compile_workout(
        WorkoutIntent(sport="bike", archetype="sustained_threshold", total_duration_min=60),
        _athlete(ftp_watts=None),
    )
    assert all(s.target.basis == "zone" for s in _leaves(c.structured.items) if s.target)


def test_bike_needing_only_a_distance_is_a_clear_error():
    with pytest.raises(ValueError, match="total_duration_min"):
        compile_workout(
            WorkoutIntent(sport="bike", archetype="endurance", total_distance_m=40000), _athlete()
        )


# --- Garmin pushability ----------------------------------------------------------------------


def _push(compiled: CompiledWorkout, sport: str) -> bytes:
    fit = to_garmin_fit_workout(compiled.structured, sport, compiled.prose.splitlines()[0][:30] or "w")
    assert fit[8:12] == b".FIT"
    return fit


@pytest.mark.parametrize(
    "archetype",
    ["sustained_threshold", "over_unders", "short_short_vo2", "race_pace", "openers", "endurance",
     "prerace_primer", "midweek_quality", "ramp_test", "test_2x20"],
)
def test_bike_structures_export_to_garmin_fit(archetype):
    c = compile_workout(WorkoutIntent(sport="bike", archetype=archetype, total_duration_min=60), _athlete())
    _push(c, "bike")


def test_swim_structures_export_to_garmin_fit_when_css_is_known():
    athlete = _athlete()
    for b in builders_for("swim_pool"):
        _push(compile_workout(_intent_for(b), athlete), "swim")
    for b in builders_for("swim_ow"):
        _push(compile_workout(_intent_for(b), athlete), "swim")


# --- swim ------------------------------------------------------------------------------------


def test_swim_css_threshold_honours_explicit_reps_and_rest():
    c = compile_workout(
        WorkoutIntent(
            sport="swim_pool", archetype="css_threshold", total_distance_m=3000, reps=8, rep_distance_m=200,
            rest_s=20,
        ),
        _athlete(),
    )
    repeat = _repeats(c.structured)[0]
    assert repeat.count == 8
    work, rest = repeat.steps
    assert work.duration_value == 200 and work.duration_kind == "distance_m"
    assert rest.duration_value == 20 and rest.role == "rest"
    assert work.target.basis == "absolute" and work.target.low and work.target.high
    assert c.dose.kind == "threshold" and c.dose.rep_count == 8
    assert c.distance_m == 3000


def test_swim_css_threshold_total_grows_when_reps_do_not_fit_and_it_is_recorded():
    c = compile_workout(
        WorkoutIntent(
            sport="swim_pool", archetype="css_threshold", total_distance_m=1500, reps=10, rep_distance_m=200,
            rest_s=20,
        ),
        _athlete(),
    )
    assert _repeats(c.structured)[0].count == 10
    assert c.distance_m > 1500
    assert any("asked 1500" in a for a in c.adjustments)


def test_swim_without_css_gets_zone_targets_and_a_note_not_an_exception():
    athlete = _athlete(css_pace_s_per_100m=None)
    c = compile_workout(
        WorkoutIntent(sport="swim_pool", archetype="css_threshold", total_distance_m=3000, reps=8, rep_distance_m=200),
        athlete,
    )
    targets = [s.target for s in _leaves(c.structured.items) if s.target]
    assert targets and all(t.basis == "zone" for t in targets)
    assert any("CSS" in a for a in c.adjustments)
    assert c.duration_min > 0
    pool = next(b for b in builders_for("swim_pool") if b.archetype.startswith("pool_"))
    p = compile_workout(_intent_for(pool), athlete)
    assert any(s.target.basis == "zone" for s in _leaves(p.structured.items) if s.target)
    assert any("CSS" in a for a in p.adjustments)


def test_swim_pool_template_resolves_against_css():
    athlete = _athlete()
    pool = next(b for b in builders_for("swim_pool") if b.archetype.startswith("pool_"))
    c = compile_workout(_intent_for(pool), athlete)
    assert any(s.target.basis == "absolute" for s in _leaves(c.structured.items) if s.target)
    assert c.distance_m == 3000


def test_swim_pool_distance_out_of_range_is_clamped_and_recorded():
    pool = next(b for b in builders_for("swim_pool") if b.archetype.startswith("pool_"))
    c = compile_workout(
        WorkoutIntent(sport="swim_pool", archetype=pool.archetype, total_distance_m=200), _athlete()
    )
    assert c.distance_m >= 1000
    assert any("total_distance_m" in a for a in c.adjustments)


def test_swim_ow_endurance_floor_template_is_raised_to_its_floor_and_recorded():
    c = compile_workout(
        WorkoutIntent(sport="swim_ow", archetype="ow_race_dress_rehearsal", total_distance_m=1500), _athlete()
    )
    assert c.distance_m > 1500
    assert any("asked 1500" in a for a in c.adjustments)


def test_swim_endurance_is_continuous_and_duration_input_sizes_distance():
    c = compile_workout(
        WorkoutIntent(sport="swim_ow", archetype="endurance", total_duration_min=60), _athlete()
    )
    assert c.distance_m and c.distance_m > 0
    assert any("total_duration_min" in a and "sized" in a for a in c.adjustments)
    assert c.dose.kind in ("endurance", "long")


def test_compiled_workout_attaches_to_a_session_unchanged():
    """The compiled pieces are exactly the Session fields the plan stores."""
    c = compile_workout(
        WorkoutIntent(sport="bike", archetype="over_unders", total_duration_min=60), _athlete()
    )
    athlete = _athlete()
    from datetime import date

    from swim_coach.models import Session

    s = Session(
        id=uuid.uuid4(), athlete_id=athlete.id, date=date(2026, 1, 5), sport="bike", source="ai_coach",
        duration_min=c.duration_min, intensity=c.intensity, purpose="x", structure=c.prose,
        structured=c.structured,
    )
    assert planned_dose(s, athlete).kind == c.dose.kind
