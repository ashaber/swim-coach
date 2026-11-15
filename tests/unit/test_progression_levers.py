"""Tests for swim_coach.progression_levers: lever-based interval progression (shapes, policy, candidates)."""

from __future__ import annotations

import ast
import copy
import uuid
from collections import deque
from pathlib import Path

import pytest
import yaml

from swim_coach.models import (
    Athlete,
    WorkoutRepeat,
    WorkoutStep,
    WorkoutStructure,
    WorkoutTarget,
)
from swim_coach.progression import ExecutedStimulus, RecoveryResponse, StimulusDose, StimulusRecord
from swim_coach.progression_levers import (
    DEFAULT_POLICY_PATH,
    LeverPolicy,
    SessionShape,
    classify_move,
    is_at_ceiling,
    next_shapes,
)
from swim_coach.workout_builders import compile_workout, parse_rung

AID = uuid.uuid4()
ATHLETE = Athlete(id=AID, slug="t", name="T", css_pace_s_per_100m=90.0, ftp_watts=250.0)
POLICY = LeverPolicy.load()


def shape(group: str, text: str) -> SessionShape:
    return SessionShape.from_intent(parse_rung(text, group))


def tstep(role: str, kind: str, value: float, zone: str, modality: str) -> WorkoutStep:
    return WorkoutStep(label=role, role=role, duration_kind=kind, duration_value=value,
                       target=WorkoutTarget(basis="zone", zone=zone), modality=modality)


def bike_repeat(count: int, work_s: float, rest_s: float, zone: str = "Z4") -> WorkoutRepeat:
    return WorkoutRepeat(count=count, steps=[tstep("interval", "time_s", work_s, zone, "bike"),
                                             tstep("recovery", "time_s", rest_s, "Z1", "bike")])


# --- SessionShape ----------------------------------------------------------------------------


def test_shape_round_trips_through_intent_and_rung_text() -> None:
    for group, text in [("bike", "2x(3x3 min/1 min)/5 min Z4"), ("bike", "6x15 s/15 s Z5"),
                        ("swim", "8x100 m/15 s Z4"), ("swim", "3x(8x50 m/20 s)/90 s Z5")]:
        s = shape(group, text)
        assert s.describe() == text
        assert SessionShape.from_intent(s.to_intent()) == s


def test_shape_work_and_density() -> None:
    s = shape("bike", "2x(3x3 min/1 min)/5 min Z4")
    assert s.work() == 2 * 3 * 180
    assert s.density() == pytest.approx(1080 / (1080 + 2 * 2 * 60 + 300))
    assert shape("swim", "8x100 m/15 s Z4").work() == 800
    assert shape("swim", "8x100 m/15 s Z4").density() is None


def test_shape_normalises_one_rep_sets_to_a_flat_rung() -> None:
    s = SessionShape(sport_group="bike", zone="Z4", sets=2, reps=1, rep_size=600, rest_s=60, set_rest_s=300)
    assert (s.sets, s.reps, s.rest_s, s.set_rest_s) == (1, 2, 300, None)
    assert s.describe() == "2x10 min/5 min Z4"


def test_shape_rejects_set_rest_below_rest() -> None:
    with pytest.raises(ValueError):
        SessionShape(sport_group="bike", zone="Z4", sets=2, reps=3, rep_size=180, rest_s=120, set_rest_s=60)


def test_from_structure_regular_flat_and_set_workouts() -> None:
    flat = WorkoutStructure(items=[bike_repeat(2, 480, 240, "Z3")])
    assert SessionShape.from_structure(flat, ATHLETE).describe() == "2x8 min/4 min Z3"
    broken = WorkoutStructure(items=[
        WorkoutRepeat(count=3, steps=[tstep("interval", "time_s", 180, "Z4", "bike"), tstep("recovery", "time_s", 60, "Z1", "bike")]),
        tstep("recovery", "time_s", 240, "Z1", "bike"),
        WorkoutRepeat(count=3, steps=[tstep("interval", "time_s", 180, "Z4", "bike"), tstep("recovery", "time_s", 60, "Z1", "bike")]),
    ])
    assert SessionShape.from_structure(broken, ATHLETE).describe() == "2x(3x3 min/1 min)/5 min Z4"


def test_from_structure_nested_repeat_with_warmup_and_cooldown() -> None:
    inner = WorkoutRepeat(count=3, steps=[tstep("interval", "time_s", 30, "Z5", "bike"), tstep("recovery", "time_s", 15, "Z1", "bike")])
    outer = WorkoutRepeat(count=2, steps=[inner, tstep("recovery", "time_s", 180, "Z1", "bike")])
    st = WorkoutStructure(items=[tstep("warmup", "time_s", 600, "Z2", "bike"), outer, tstep("cooldown", "time_s", 300, "Z1", "bike")])
    assert SessionShape.from_structure(st, ATHLETE).describe() == "2x(3x30 s/15 s)/3 min Z5"


def test_from_structure_swim_distance_reps() -> None:
    st = WorkoutStructure(items=[WorkoutRepeat(count=8, steps=[tstep("interval", "distance_m", 100, "Z4", "swim"),
                                                               tstep("rest", "time_s", 15, "Z1", "swim")])])
    assert SessionShape.from_structure(st, ATHLETE).describe() == "8x100 m/15 s Z4"


@pytest.mark.parametrize("items", [
    # mixed rep sizes
    [tstep("interval", "time_s", 300, "Z4", "bike"), tstep("recovery", "time_s", 60, "Z1", "bike"),
     tstep("interval", "time_s", 600, "Z4", "bike")],
    # mixed zones
    [tstep("interval", "time_s", 300, "Z4", "bike"), tstep("recovery", "time_s", 60, "Z1", "bike"),
     tstep("interval", "time_s", 300, "Z5", "bike")],
    # a pyramid of rests
    [tstep("interval", "time_s", 300, "Z4", "bike"), tstep("recovery", "time_s", 60, "Z1", "bike"),
     tstep("interval", "time_s", 300, "Z4", "bike"), tstep("recovery", "time_s", 180, "Z1", "bike"),
     tstep("interval", "time_s", 300, "Z4", "bike"), tstep("recovery", "time_s", 400, "Z1", "bike"),
     tstep("interval", "time_s", 300, "Z4", "bike")],
    # easy only
    [tstep("steady", "time_s", 3600, "Z2", "bike")],
])
def test_from_structure_returns_none_when_irregular(items: list) -> None:
    assert SessionShape.from_structure(WorkoutStructure(items=items), ATHLETE) is None


def executed_record(sports: str, kind: str, sizes: list[float], gaps: list[float] | None, *, planned: bool = True) -> StimulusRecord:
    key = "work_s" if sports == "bike" else "work_m"
    sports = "bike" if sports == "bike" else "swim_pool"
    dose = StimulusDose(sport=sports, kind=kind, confidence="structured", rep_sizes=sizes, rest_gaps_s=gaps,
                        rep_count=len(sizes), **{key: sum(sizes)})
    ex = ExecutedStimulus(dose=dose, planned=planned)
    from datetime import date
    return StimulusRecord(date=date(2026, 11, 1), sport=sports, kind=kind, planned=planned, executed=ex,
                          recovery=RecoveryResponse(status="recovered"))


def test_from_executed_regular_reps_within_tolerance() -> None:
    rec = executed_record("bike", "threshold", [602, 598, 610, 596], [240, 245, 238])
    s = SessionShape.from_executed(rec)
    assert s.describe() == "4x10 min/4 min Z4"


def test_from_executed_finds_sets_from_the_larger_gaps() -> None:
    rec = executed_record("bike", "vo2", [30] * 6, [15, 15, 180, 15, 15])
    assert SessionShape.from_executed(rec).describe() == "2x(3x30 s/15 s)/3 min Z5"


def test_from_executed_swim_metres() -> None:
    rec = executed_record("swim", "threshold", [100.0] * 8, [15.0] * 7)
    assert SessionShape.from_executed(rec).describe() == "8x100 m/15 s Z4"


@pytest.mark.parametrize("sizes,gaps,kind", [
    ([300, 600, 300, 900], [60, 60, 60], "threshold"),     # irregular reps (a club ride)
    ([600, 600, 600], None, "threshold"),                  # no rest detail
    ([600, 600, 600], [60, 400, 61], "threshold"),         # irregular rest
    ([600, 600], [60], "mixed"),                           # no single zone
    ([600, 600], [60], "endurance"),                       # not a quality kind
])
def test_from_executed_returns_none_when_not_regular(sizes: list, gaps: list | None, kind: str) -> None:
    assert SessionShape.from_executed(executed_record("bike", kind, sizes, gaps)) is None


# --- policy ----------------------------------------------------------------------------------


def test_policy_loads_every_group_and_zone_with_valid_entries() -> None:
    assert set(POLICY.groups) == {"bike", "swim"}
    for group, gp in POLICY.groups.items():
        assert set(gp.zones) == {"Z3", "Z4", "Z5"}
        for zone in gp.zones:
            entry = POLICY.entry(group, zone)
            assert (entry.sport_group, entry.zone) == (group, zone)


def test_policy_every_ceiling_has_a_source_and_non_research_numbers_are_labelled() -> None:
    for gp in POLICY.groups.values():
        assert gp.rebase.basis.startswith("Coach judgment:")
        for zp in gp.zones.values():
            for band in zp.ceiling:
                assert band.source.startswith(("Coach judgment:", "Ronnestad", "Seiler", "Dekerle"))
            for rule in zp.levers:
                assert rule.basis.startswith("Coach judgment:")


def test_policy_retest_archetypes_exist_in_the_compiler_registry() -> None:
    from swim_coach.workout_builders import builders_for
    for group, gp in POLICY.groups.items():
        known = {b.archetype for b in builders_for(group)}
        assert set(gp.retest_archetypes) <= known


def test_policy_override_dict_changes_a_ceiling_without_code() -> None:
    patched = LeverPolicy.load(overrides={"groups": {"bike": {"zones": {"Z4": {"ceiling": [{"work": "20 min", "source": "Coach judgment: athlete override."}]}}}}})
    assert patched.zone("bike", "Z4").ceiling[0].work == 1200
    assert POLICY.zone("bike", "Z4").ceiling[0].work == 2400
    assert patched.zone("bike", "Z3").ceiling[0].work == 3600  # untouched siblings survive the merge


def test_policy_rejects_bad_files_with_a_clear_error(tmp_path: Path) -> None:
    raw = yaml.safe_load(DEFAULT_POLICY_PATH.read_text())

    def load_with(mutate) -> None:
        data = copy.deepcopy(raw)
        mutate(data)
        path = tmp_path / "bad.yaml"
        path.write_text(yaml.safe_dump(data))
        LeverPolicy.load(path)

    with pytest.raises(ValueError, match="entry"):
        load_with(lambda d: d["groups"]["bike"]["zones"]["Z4"].update(entry="2x8 min/4 min Z3"))  # wrong zone
    with pytest.raises(ValueError, match="not a rung"):
        load_with(lambda d: d["groups"]["bike"]["zones"]["Z4"].update(entry="lots of threshold"))
    with pytest.raises(ValueError, match="step"):
        load_with(lambda d: d["groups"]["bike"]["zones"]["Z4"]["levers"][0].update(step={"add": "1 min", "mul": 2}))
    with pytest.raises(ValueError, match="set_rest"):
        load_with(lambda d: d["groups"]["bike"]["zones"]["Z4"]["levers"][-1].pop("set_rest"))
    with pytest.raises(ValueError, match="unknown sport group"):
        load_with(lambda d: d["groups"].update(run=d["groups"]["bike"]))
    with pytest.raises(ValueError, match="schema_version"):
        load_with(lambda d: d.update(schema_version=99))
    with pytest.raises(ValueError, match="ceiling"):
        load_with(lambda d: d["groups"]["bike"]["zones"]["Z4"].update(ceiling=[]))


# --- next_shapes -----------------------------------------------------------------------------


def moved(candidates, lever: str):
    return next(c for c in candidates if c.lever == lever)


def test_progress_moves_exactly_one_lever_one_step_in_policy_order() -> None:
    cur = shape("bike", "2x8 min/4 min Z3")
    cands = next_shapes(cur, POLICY, verdict="progress")
    assert [c.lever for c in cands] == ["rep_size", "rest", "reps"]
    assert cands[0].shape.describe() == "2x10 min/4 min Z3"
    assert cands[0].change == "rep 8 min -> 10 min"
    assert cands[0].work_delta_pct == pytest.approx(25.0)
    assert cands[1].shape.describe() == "2x8 min/3 min Z3" and cands[1].density_delta > 0
    assert cands[2].shape.describe() == "3x8 min/4 min Z3"
    for c in cands:
        assert c.direction == "up" and c.basis.startswith("Coach judgment:") and c.rung == c.shape.describe()


def test_no_progress_candidate_equals_the_current_shape() -> None:
    for group in POLICY.groups:
        for zone in ("Z3", "Z4", "Z5"):
            cur = POLICY.entry(group, zone)
            for c in next_shapes(cur, POLICY, verdict="progress"):
                if c.shape is not None:
                    assert c.shape != cur


def test_repeat_returns_only_the_current_shape() -> None:
    cur = shape("bike", "2x10 min/4 min Z4")
    cands = next_shapes(cur, POLICY, verdict="repeat")
    assert [(c.direction, c.shape) for c in cands] == [("repeat", cur)]


@pytest.mark.parametrize("verdict", ["reduce", "rebuild"])
def test_reduce_and_rebuild_step_down_one_lever(verdict: str) -> None:
    cur = shape("bike", "2x12 min/3 min Z4")
    cands = next_shapes(cur, POLICY, verdict=verdict)
    assert cands and all(c.direction == "down" for c in cands)
    assert [c.lever for c in cands] == ["reps", "rest", "rep_size"]  # policy order reversed
    assert moved(cands, "rep_size").shape.describe() == "2x10 min/3 min Z4"
    assert moved(cands, "rest").shape.describe() == "2x12 min/4 min Z4"


def test_reduce_undoes_the_most_recent_lever_first_when_history_is_known() -> None:
    before = shape("bike", "2x10 min/4 min Z4")
    cur = shape("bike", "2x12 min/4 min Z4")
    cands = next_shapes(cur, POLICY, verdict="reduce", history=[before])
    assert cands[0].lever == "rep_size" and cands[0].shape == before


def test_insufficient_data_offers_nothing_and_no_history_offers_the_entry() -> None:
    assert next_shapes(shape("bike", "2x10 min/4 min Z4"), POLICY, verdict="insufficient_data") == []
    cands = next_shapes(None, POLICY, verdict="progress", group="bike", zone="Z5")
    assert [(c.direction, c.rung) for c in cands] == [("entry", "6x15 s/15 s Z5")]


def test_candidates_stay_under_the_ceiling_and_bounds() -> None:
    cur = shape("bike", "2x15 min/5 min Z4")
    cands = next_shapes(cur, POLICY, verdict="progress")
    assert all(c.shape.work() <= 2400 for c in cands)
    assert "2x20 min/5 min Z4" in [c.rung for c in cands]


def test_at_ceiling_promotes_instead_of_progressing() -> None:
    top_tempo = shape("bike", "3x20 min/4 min Z3")
    assert is_at_ceiling(top_tempo, POLICY)
    cands = next_shapes(top_tempo, POLICY, verdict="progress")
    assert [(c.direction, c.rung) for c in cands] == [("promote", "2x(3x3 min/1 min)/5 min Z4")]
    top_threshold = shape("bike", "2x20 min/5 min Z4")
    cands = next_shapes(top_threshold, POLICY, verdict="progress")
    assert [c.direction for c in cands] == ["retest"]
    assert "ramp_test" in cands[0].rung and cands[0].shape is None and cands[0].lever == "retest_threshold"


def test_at_ceiling_for_swim_without_a_test_archetype_still_suggests_a_retest() -> None:
    cands = next_shapes(shape("swim", "10x400 m/40 s Z4"), POLICY, verdict="progress")
    assert [c.direction for c in cands] == ["retest"] and "CSS" in cands[0].change


def test_next_shapes_is_deterministic() -> None:
    cur = shape("bike", "2x(3x3 min/1 min)/5 min Z4")
    runs = [[c.model_dump_json() for c in next_shapes(cur, POLICY, verdict="progress")] for _ in range(3)]
    assert runs[0] == runs[1] == runs[2] and len(runs[0]) > 3


# --- the athlete's own patterns are reachable -------------------------------------------------


def shortest_path(start: SessionShape, target_text: str, group: str, limit: int = 20) -> int | None:
    """Fewest single-lever progress steps from `start` to the rung `target_text`, by breadth-first search."""
    seen = {start.describe()}
    queue = deque([(start, 0)])
    while queue:
        cur, depth = queue.popleft()
        if cur.describe() == target_text:
            return depth
        if depth >= limit:
            continue
        for c in next_shapes(cur, POLICY, verdict="progress"):
            if c.shape is not None and c.rung not in seen:
                seen.add(c.rung)
                queue.append((c.shape, depth + 1))
    return None


def test_bike_threshold_pattern_is_reachable_from_the_entry() -> None:
    steps = shortest_path(POLICY.entry("bike", "Z4"), "2x20 min/5 min Z4", "bike")
    assert steps is not None and steps <= 8
    assert shortest_path(POLICY.entry("bike", "Z4"), "2x10 min/5 min Z4", "bike") <= 4


def test_bike_vo2_pattern_is_reachable_from_the_entry() -> None:
    steps = shortest_path(POLICY.entry("bike", "Z5"), "3x(13x30 s/15 s)/3 min Z5", "bike")
    assert steps is not None and steps <= 10
    assert is_at_ceiling(shape("bike", "3x(13x30 s/15 s)/3 min Z5"), POLICY)


def test_bike_tempo_to_threshold_hand_over() -> None:
    assert shortest_path(POLICY.entry("bike", "Z3"), "3x20 min/4 min Z3", "bike") is not None


def test_policy_names_no_target_list() -> None:
    text = DEFAULT_POLICY_PATH.read_text()
    assert "13x30" not in text and "2x20 min" not in text


def test_swim_threshold_is_climbable_to_its_ceiling() -> None:
    cands = next_shapes(POLICY.entry("swim", "Z4"), POLICY, verdict="progress")
    assert cands and all(c.shape.work() <= 4000 for c in cands)


# --- every candidate compiles cleanly ---------------------------------------------------------


def all_policy_candidates():
    for group in POLICY.groups:
        for zone in ("Z3", "Z4", "Z5"):
            entry = POLICY.entry(group, zone)
            out = [entry]
            for verdict in ("progress", "reduce"):
                out += [c.shape for c in next_shapes(entry, POLICY, verdict=verdict) if c.shape is not None]
            # one more step from each progress candidate
            for c in next_shapes(entry, POLICY, verdict="progress"):
                if c.shape is not None:
                    out += [d.shape for d in next_shapes(c.shape, POLICY, verdict="progress") if d.shape is not None]
                    out += [d.shape for d in next_shapes(c.shape, POLICY, verdict="reduce") if d.shape is not None]
            yield from {s.describe(): s for s in out}.values()


@pytest.mark.parametrize("candidate", list(all_policy_candidates()), ids=lambda s: f"{s.sport_group}-{s.describe()}")
def test_every_candidate_compiles_with_no_adjustments(candidate: SessionShape) -> None:
    compiled = compile_workout(candidate.to_intent(), ATHLETE)
    assert compiled.adjustments == []
    assert compiled.dose is not None
    assert compiled.dose.work_in("s" if candidate.sport_group == "bike" else "m") == pytest.approx(candidate.work(), rel=0.02)


# --- classify_move -----------------------------------------------------------------------------


def test_classify_single_step_is_clean() -> None:
    read = classify_move(shape("bike", "2x10 min/4 min Z4"), shape("bike", "2x12 min/4 min Z4"), POLICY)
    assert read.levers == {"rep_size": 1} and not (read.multi_lever or read.oversized_step or read.over_ceiling)
    assert read.summary == "rep +2 min"


def test_classify_multi_lever_example_from_the_brief() -> None:
    read = classify_move(shape("bike", "2x10 min/4 min Z4"), shape("bike", "3x15 min/3 min Z4"), POLICY)
    assert read.multi_lever and read.levers["reps"] == 1 and read.levers["rep_size"] == 2 and read.levers["rest"] == 1
    assert read.summary == "reps +1, rep +5 min, rest -1 min"


def test_classify_oversized_step_counts_grid_steps() -> None:
    read = classify_move(shape("bike", "2x10 min/4 min Z4"), shape("bike", "2x20 min/4 min Z4"), POLICY)
    assert read.oversized_step and read.levers["rep_size"] == 3 and not read.multi_lever


def test_classify_over_ceiling_names_its_source() -> None:
    read = classify_move(shape("bike", "2x15 min/5 min Z4"), shape("bike", "3x15 min/5 min Z4"), POLICY)
    assert read.over_ceiling and "2 x 20 min" in read.ceiling_source
    swim = classify_move(shape("swim", "10x300 m/20 s Z4"), shape("swim", "10x400 m/20 s Z4"), POLICY)
    assert swim.over_ceiling is False  # exactly the 4000 m ceiling
    assert classify_move(shape("swim", "10x300 m/20 s Z4"), shape("swim", "12x400 m/20 s Z4"), POLICY).over_ceiling


def test_classify_consolidation_is_one_lever_move() -> None:
    read = classify_move(shape("bike", "2x(3x3 min/1 min)/5 min Z4"), shape("bike", "2x(2x5 min/1 min)/5 min Z4"), POLICY)
    assert read.consolidated and not read.multi_lever and read.levers == {"consolidate": 1}


def test_classify_harder_zone_without_base() -> None:
    early = classify_move(shape("bike", "2x8 min/4 min Z3"), shape("bike", "2x(3x3 min/1 min)/5 min Z4"), POLICY)
    assert early.harder_zone_without_base and not early.same_zone
    based = classify_move(shape("bike", "3x20 min/4 min Z3"), shape("bike", "2x(3x3 min/1 min)/5 min Z4"), POLICY)
    assert not based.harder_zone_without_base


def test_classify_unchanged_and_down_moves() -> None:
    same = classify_move(shape("bike", "2x10 min/4 min Z4"), shape("bike", "2x10 min/4 min Z4"), POLICY)
    assert same.levers == {} and not same.multi_lever
    down = classify_move(shape("bike", "2x12 min/4 min Z4"), shape("bike", "2x10 min/4 min Z4"), POLICY)
    assert down.levers == {"rep_size": -1}


# --- structure ---------------------------------------------------------------------------------


def test_module_has_no_sport_name_literals() -> None:
    path = Path(__file__).resolve().parents[2] / "engine" / "swim_coach" / "progression_levers.py"
    tree = ast.parse(path.read_text())
    docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                  if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                  and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    literals = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings]
    assert not [s for s in literals if "bike" in s.lower() or "swim" in s.lower()]
