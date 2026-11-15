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


# --- ladder rungs: steady_intervals, kind_for, set rest, rung text ----------------------------

from swim_coach.workout_builders import describe_rung, parse_rung  # noqa: E402

LADDER = [
    ("2x8 min Z3", "tempo", 960.0, 2, 480.0),
    ("2x(3x3 min) Z4", "threshold", 1080.0, 6, 180.0),
    ("2x10 min Z4", "threshold", 1200.0, 2, 600.0),
    ("2x20 min Z4", "threshold", 2400.0, 2, 1200.0),
]


@pytest.mark.parametrize("text,kind,work_s,reps,longest", LADDER)
def test_ladder_rungs_compile_exactly_as_asked(text, kind, work_s, reps, longest):
    c = compile_workout(parse_rung(text, "bike"), _athlete())
    assert c.adjustments == []
    assert c.dose.kind == kind
    assert (c.dose.work_s, c.dose.rep_count, c.dose.longest_rep_s) == (work_s, reps, longest)
    assert c.dose.confidence == "structured"


def test_steady_intervals_names_the_zones_kind_in_labels_and_prose():
    cases = (("2x8 min Z3", "Tempo interval"), ("2x10 min Z4", "Threshold interval"), ("5x4 min Z5", "VO2 interval"))
    for text, word in cases:
        c = compile_workout(parse_rung(text, "bike"), _athlete())
        assert word in c.prose
        assert "sustained threshold" not in c.prose


def test_sustained_threshold_at_z3_reports_tempo_without_a_mismatch_note():
    c = compile_workout(
        WorkoutIntent(sport="bike", archetype="sustained_threshold", reps=2, rep_duration_s=480, target_zone="Z3"),
        _athlete(),
    )
    assert c.dose.kind == "tempo" and c.adjustments == []
    assert "Tempo interval" in c.prose


def test_builder_kind_for_defaults_to_declared_kind_and_follows_the_intent():
    b = get_builder("bike", "steady_intervals")
    kinds = [
        b.kind_of(WorkoutIntent(sport="bike", archetype="steady_intervals", reps=2, rep_duration_s=300, target_zone=z))
        for z in ("Z3", "Z4", "Z5")
    ]
    assert kinds == ["tempo", "threshold", "vo2"]
    other = get_builder("bike", "over_unders")
    assert other.kind_of(WorkoutIntent(sport="bike", archetype="over_unders", total_duration_min=60)) == "mixed"


def _top_level_gaps(structured):
    return [
        i for i in structured.items
        if isinstance(i, WorkoutStep) and i.role not in ("open", "warmup", "cooldown")
    ]


def test_steady_intervals_sets_are_separated_by_total_set_rest_with_none_after_the_last():
    c = compile_workout(
        WorkoutIntent(sport="bike", archetype="steady_intervals", sets=3, reps=2, rep_duration_s=300,
                      rest_s=60, set_rest_s=300, target_zone="Z4"),
        _athlete(),
    )
    repeats = _repeats(c.structured)
    assert len(repeats) == 3 and all(r.count == 2 for r in repeats)
    gaps = _top_level_gaps(c.structured)
    assert [g.duration_value for g in gaps] == [240, 240]  # 300 s total minus the 60 s in-set rest
    assert c.structured.items[-2] is repeats[-1]
    assert c.adjustments == []


def test_steady_intervals_default_rest_and_set_rest_follow_existing_conventions():
    from swim_coach.workout_builders.bike import BIKE_SHORT_SHORT_SET_REST_S

    # default rest is 1:1 with the work capped at 4 min; default total set rest is the short-short set rest
    c = compile_workout(parse_rung("2x(3x3 min) Z4", "bike"), _athlete())
    assert [g.duration_value for g in _top_level_gaps(c.structured)] == [BIKE_SHORT_SHORT_SET_REST_S - 180]
    assert describe_rung(parse_rung("2x(3x3 min) Z4", "bike")) == "2x(3x3 min/3 min)/4 min Z4"
    assert describe_rung(parse_rung("2x8 min Z3", "bike")) == "2x8 min/4 min Z3"


def test_steady_intervals_rep_range_allows_short_and_long_reps():
    short = compile_workout(
        WorkoutIntent(sport="bike", archetype="steady_intervals", reps=10, rep_duration_s=60, target_zone="Z5"), _athlete()
    )
    long_ = compile_workout(
        WorkoutIntent(sport="bike", archetype="steady_intervals", reps=1, rep_duration_s=3600, target_zone="Z3"), _athlete()
    )
    assert short.adjustments == [] and long_.adjustments == []


def test_steady_intervals_fits_reps_to_a_total():
    c = compile_workout(
        WorkoutIntent(sport="bike", archetype="steady_intervals", rep_duration_s=600, total_duration_min=60,
                      target_zone="Z4"),
        _athlete(),
    )
    assert c.duration_min == pytest.approx(60) and c.dose.kind == "threshold"


def test_planned_dose_measures_nested_repeats_by_their_product_and_garmin_accepts_them():
    from datetime import date

    from swim_coach.models import Session, WorkoutStructure, WorkoutTarget

    def step(role, secs):
        zone = "Z4" if role == "interval" else "Z1"
        return WorkoutStep(label=role, role=role, duration_kind="time_s", duration_value=secs,
                           target=WorkoutTarget(basis="zone", zone=zone), modality="bike")

    inner = WorkoutRepeat(repeat_mode="count", count=3, steps=[step("interval", 180), step("recovery", 60)])
    nested = WorkoutStructure(items=[WorkoutRepeat(repeat_mode="count", count=2, steps=[inner, step("recovery", 240)])])
    athlete = _athlete()
    s = Session(id=uuid.uuid4(), athlete_id=athlete.id, date=date(2026, 1, 5), sport="bike", source="ai_coach",
                duration_min=60, intensity={"zone": "Z4"}, purpose="x", structured=nested)
    dose = planned_dose(s, athlete)
    assert (dose.kind, dose.work_s, dose.rep_count, dose.longest_rep_s) == ("threshold", 1080.0, 6, 180.0)
    assert to_garmin_fit_workout(nested, "bike", "nested")[8:12] == b".FIT"


def test_compiled_ladder_rungs_export_to_garmin_fit():
    for text, _, _, _, _ in LADDER:
        _push(compile_workout(parse_rung(text, "bike"), _athlete()), "bike")


def test_swim_css_threshold_sets_zone_and_set_rest():
    c = compile_workout(
        WorkoutIntent(sport="swim_pool", archetype="css_threshold", sets=2, reps=4, rep_distance_m=100,
                      rest_s=15, set_rest_s=60, target_zone="Z3"),
        _athlete(),
    )
    repeats = _repeats(c.structured)
    assert len(repeats) == 2 and all(r.count == 4 for r in repeats)
    assert c.dose.kind == "tempo" and c.dose.rep_count == 8 and c.dose.work_m == 800
    assert not any("declares" in a for a in c.adjustments)
    z5 = compile_workout(
        WorkoutIntent(sport="swim_pool", archetype="css_threshold", reps=8, rep_distance_m=50, target_zone="Z5"),
        _athlete(),
    )
    assert z5.dose.kind == "vo2" and z5.intensity["zone"] == "Z5"
    _push(c, "swim")


RUNGS = [
    ("2x8 min/4 min Z3", "bike"), ("2x(3x3 min/1 min)/5 min Z4", "bike"), ("2x10 min/4 min Z4", "bike"),
    ("2x20 min/5 min Z4", "bike"), ("6x15 s/15 s Z5", "bike"), ("3x(8x30 s/15 s)/4 min Z5", "bike"),
    ("5x7.5 min/3 min Z4", "bike"), ("10x40 s/20 s Z5", "bike"),
    ("8x200 m/20 s Z4", "swim_pool"), ("2x(4x100 m/15 s)/1 min Z3", "swim_pool"), ("6x50 m/10 s Z5", "swim_pool"),
]


@pytest.mark.parametrize("text,sport", RUNGS)
def test_rung_text_round_trips(text, sport):
    intent = parse_rung(text, sport)
    assert describe_rung(intent) == text
    assert parse_rung(describe_rung(intent), sport) == intent


def test_rest_is_carried_by_the_rung_and_printed_even_when_omitted():
    assert parse_rung("2x8 min Z3", "bike").rest_s is None
    assert parse_rung("2x8 min/6 min Z3", "bike").rest_s == 360
    assert describe_rung(parse_rung("8x200 m Z4", "swim")) == "8x200 m/20 s Z4"
    assert parse_rung("2x(3x3 min)/5 min Z4", "bike").set_rest_s == 300
    c = compile_workout(parse_rung("2x8 min/6 min Z3", "bike"), _athlete())
    assert _repeats(c.structured)[0].steps[1].duration_value == 360


@pytest.mark.parametrize("text,on_s,reps", [
    ("6x15 s/15 s Z5", 90.0, 6), ("10x30 s/15 s Z5", 300.0, 10), ("10x40 s/20 s Z5", 400.0, 10),
    ("3x(8x30 s/15 s)/4 min Z5", 720.0, 24), ("5x(12x20 s/10 s)/6 min Z5", 1200.0, 60),
])
def test_short_on_off_vo2_compiles_exactly_with_work_as_the_sum_of_on_time(text, on_s, reps):
    c = compile_workout(parse_rung(text, "bike"), _athlete())
    assert c.adjustments == []
    assert c.dose.kind == "vo2" and c.dose.work_s == on_s and c.dose.rep_count == reps
    _push(c, "bike")


def test_steady_intervals_is_the_canonical_short_on_off_builder_and_short_short_stays_available():
    assert parse_rung("6x15 s/15 s Z5", "bike").archetype == "steady_intervals"
    ss = compile_workout(
        WorkoutIntent(sport="bike", archetype="short_short_vo2", sets=2, reps=8, rep_duration_s=30, rest_s=15),
        _athlete(),
    )
    assert ss.dose.kind == "vo2" and ss.dose.work_s == 480.0


def test_parse_rung_maps_to_the_zone_neutral_archetypes_and_fields():
    i = parse_rung("2x(3x3 min) Z4", "bike")
    assert (i.archetype, i.sets, i.reps, i.rep_duration_s, i.target_zone) == ("steady_intervals", 2, 3, 180, "Z4")
    j = parse_rung("8x200 m Z4", "swim")
    assert (j.sport, j.archetype, j.reps, j.rep_distance_m, j.sets) == ("swim_pool", "css_threshold", 8, 200, None)


@pytest.mark.parametrize("bad", ["", "2x8 Z3", "2x(3x3 min Z4", "2x8 min", "2x8 min Z6", "two x 8 min Z3", "2x8 m Z3", "2x8 min/4 Z3", "2x(3x3 min/1 min Z4"])
def test_parse_rung_rejects_anything_else(bad):
    with pytest.raises(ValueError):
        parse_rung(bad, "bike")
