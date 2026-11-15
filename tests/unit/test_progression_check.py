"""Tests for swim_coach.progression_check: advisory progression-guardrail findings on an authored week."""

from __future__ import annotations

import json
import uuid
from datetime import date, timedelta

import pytest

from swim_coach.cli import main
from swim_coach.models import (
    Athlete,
    MacroWeek,
    Session,
    WeekPlan,
    WorkoutRepeat,
    WorkoutStep,
    WorkoutStructure,
    WorkoutTarget,
)
from swim_coach.plan_check import check_week
from swim_coach.progression import (
    PROGRESSION_STEP_FRACTION,
    ProgressionRead,
    RecoveryResponse,
    RemainingImpact,
    StimulusRecord,
    WeekStimulusReview,
)
from swim_coach.progression_check import (
    ProgressionInputs,
    build_progression_inputs,
    check_week_progression,
)
from swim_coach.stimulus import ExecutedStimulus, StimulusDose

AID = uuid.uuid4()
ATHLETE = Athlete(id=AID, slug="t", name="T", css_pace_s_per_100m=90.0, ftp_watts=250.0)
AS_OF = date(2026, 11, 14)
MON = date(2026, 11, 9)
STEP = PROGRESSION_STEP_FRACTION

# One scenario table per sport; every scenario below runs through both rows.
SPORTS = {
    "bike": dict(profile="bike", sport="bike", unit="s", key="work_s", rep="longest_rep_s", ref=1800.0, rep_len=600.0),
    "swim": dict(profile="swim", sport="swim_pool", unit="m", key="work_m", rep="longest_rep_m", ref=1200.0, rep_len=100.0),
}


def tstep(role, kind, value, zone, modality):
    return WorkoutStep(label=role, role=role, duration_kind=kind, duration_value=value,
                       target=WorkoutTarget(basis="zone", zone=zone), modality=modality)


def session(sp, work, *, rep=None, day=None, zone="Z4", structured=True, **kw):
    """A planned session of `sp` whose structured work is `work` in the sport's unit."""
    s = SPORTS[sp]
    day = day or MON + timedelta(days=2)
    count = max(round(work / rep), 1) if rep else 3
    step_value = rep or work / count
    modality = "bike" if s["unit"] == "s" else "swim"
    kind = "time_s" if s["unit"] == "s" else "distance_m"
    st = None
    if structured:
        st = WorkoutStructure(items=[WorkoutRepeat(count=count, steps=[
            tstep("interval", kind, step_value, zone, modality), tstep("rest", "time_s", 60, "Z1", modality)])])
    return Session(id=uuid.uuid4(), athlete_id=AID, date=day, sport=s["sport"], source="ai_coach",
                   duration_min=60, distance_m=2000 if modality == "swim" else None,
                   intensity={"zone": zone}, purpose="t", structured=st, **kw)


def dose(sp, work, *, kind="threshold", rep=None):
    s = SPORTS[sp]
    return StimulusDose(sport=s["sport"], kind=kind, confidence="structured",
                        **{s["key"]: work, s["rep"]: rep or s["rep_len"]})


def record(sp, work, *, days_ago=5, kind="threshold", planned=True):
    d = dose(sp, work, kind=kind)
    return StimulusRecord(
        date=AS_OF - timedelta(days=days_ago), sport=SPORTS[sp]["sport"], kind=kind, planned=planned,
        executed=ExecutedStimulus(dose=d, completion_pct=100.0, in_band_pct=90.0, fade_pct=1.0, rpe=7, planned=planned),
        recovery=RecoveryResponse(status="recovered"))


def read(sp, verdict="progress", *, ref=None, confidence="high", kind="threshold", rep_max=None, rng=None, last=None):
    s = SPORTS[sp]
    ref = s["ref"] if ref is None else ref
    last = last or record(sp, ref, kind=kind)
    if rng is None and verdict != "insufficient_data":
        rng = (ref, ref * (1 + STEP)) if verdict == "progress" else (ref * (1 - STEP) * 0.95, ref * (1 - STEP))
    return ProgressionRead(
        sport=s["profile"], kind=kind, verdict=verdict, unit=s["unit"], confidence=confidence,
        reasons=[f"Last session did {ref:.0f} {s['unit']}."], last=last,
        reference_dose=None if verdict == "insufficient_data" else dose(sp, ref, kind=kind),
        suggested_work_range=rng, suggested_longest_rep_max=rep_max, days_since_last=5)


def week(sessions):
    return WeekPlan(id=uuid.uuid4(), athlete_id=AID, iso_week="2026-W46", meso_block="b", focus="f",
                    target_volume_m=0, sessions=sessions)


def run(sp, sessions, reads, **kw):
    return check_week_progression(week(sessions), ATHLETE, reads=reads, **kw)


def ids(findings):
    return [f.id for f in findings]


def top(sp, verdict="progress"):
    return read(sp, verdict).suggested_work_range[1]


# --- jump ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("sp", SPORTS)
class TestJump:
    def test_fires_just_past_one_more_step(self, sp):
        planned = top(sp) * (1 + STEP) * 1.001
        found = run(sp, [session(sp, planned)], [read(sp)])
        assert ids(found) == [f"progression-jump-{SPORTS[sp]['profile']}-threshold"]
        assert found[0].severity == "medium" and found[0].category == "judgment"

    def test_silent_at_the_boundary(self, sp):
        planned = top(sp) * (1 + STEP) * 0.999
        assert run(sp, [session(sp, planned)], [read(sp)]) == []

    @pytest.mark.parametrize("verdict", ["reduce", "rebuild"])
    def test_high_when_reduce_or_rebuild(self, sp, verdict):
        r = read(sp, verdict)
        planned = r.suggested_work_range[1] * (1 + STEP) * 1.05
        found = run(sp, [session(sp, planned)], [r])
        assert found[0].id.startswith("progression-jump-") and found[0].severity == "high"

    def test_evidence_quotes_numbers_and_fix_states_range(self, sp):
        planned = top(sp) * (1 + STEP) * 1.2
        f = run(sp, [session(sp, planned)], [read(sp)])[0]
        unit = SPORTS[sp]["unit"]
        fmt = (lambda v: f"{v / 60:.0f} min") if unit == "s" else (lambda v: f"{v:.0f} m")
        r = read(sp)
        assert fmt(planned) in f.evidence and fmt(r.reference_dose.work_in(unit)) in f.evidence
        assert "progress" in f.evidence and r.reasons[0] in f.evidence
        assert fmt(r.suggested_work_range[0]) in f.fix and fmt(r.suggested_work_range[1]) in f.fix


# --- ignores reduce / rebuild -----------------------------------------------------------------


@pytest.mark.parametrize("sp", SPORTS)
@pytest.mark.parametrize("verdict", ["reduce", "rebuild"])
class TestIgnores:
    def wide(self, sp, verdict):
        """Last (failed) session did more than the last clean one, so the range sits above the reference."""
        ref = SPORTS[sp]["ref"]
        return read(sp, verdict, rng=(1.2 * ref, 1.35 * ref))

    def test_fires_at_the_reference_dose(self, sp, verdict):
        ref = SPORTS[sp]["ref"]
        found = run(sp, [session(sp, ref)], [self.wide(sp, verdict)])
        assert ids(found) == [f"progression-ignores-{verdict}-{SPORTS[sp]['profile']}-threshold"]
        assert found[0].severity == "medium" and found[0].category == "judgment"

    def test_silent_just_below_the_reference(self, sp, verdict):
        ref = SPORTS[sp]["ref"]
        assert run(sp, [session(sp, ref * 0.99)], [self.wide(sp, verdict)]) == []

    def test_jump_outranks_ignores_one_finding_per_kind(self, sp, verdict):
        r = read(sp, verdict)
        planned = r.suggested_work_range[1] * (1 + STEP) * 1.5
        found = run(sp, [session(sp, planned)], [r])
        assert len(found) == 1 and found[0].id.startswith("progression-jump-") and found[0].severity == "high"


# --- stalled ----------------------------------------------------------------------------------


@pytest.mark.parametrize("sp", SPORTS)
class TestStalled:
    def ledger(self, sp, prev, last):
        return [record(sp, prev, days_ago=12), record(sp, last, days_ago=5)]

    def test_fires_after_two_sessions_without_progress(self, sp):
        ref = SPORTS[sp]["ref"]
        found = run(sp, [session(sp, ref)], [read(sp)], ledger=self.ledger(sp, ref, ref))
        assert ids(found) == [f"progression-stalled-{SPORTS[sp]['profile']}-threshold"]
        assert found[0].severity == "low" and found[0].category == "judgment"

    def test_silent_when_planned_exceeds_reference(self, sp):
        ref = SPORTS[sp]["ref"]
        assert run(sp, [session(sp, ref * 1.01)], [read(sp)], ledger=self.ledger(sp, ref, ref)) == []

    def test_silent_when_previous_session_did_progress(self, sp):
        ref = SPORTS[sp]["ref"]
        assert run(sp, [session(sp, ref)], [read(sp)], ledger=self.ledger(sp, ref * 0.9, ref)) == []

    def test_silent_without_a_ledger_or_with_one_record(self, sp):
        ref = SPORTS[sp]["ref"]
        assert run(sp, [session(sp, ref)], [read(sp)]) == []
        assert run(sp, [session(sp, ref)], [read(sp)], ledger=[record(sp, ref)]) == []

    def test_silent_for_repeat_verdict(self, sp):
        ref = SPORTS[sp]["ref"]
        r = read(sp, "repeat", rng=(ref * 0.95, ref))
        assert run(sp, [session(sp, ref)], [r], ledger=self.ledger(sp, ref, ref)) == []

    def test_taper_phase_suppresses(self, sp):
        ref = SPORTS[sp]["ref"]
        for phase in ("Taper 1", "Race week"):
            mw = MacroWeek(week_start=MON, phase=phase, focus="f")
            assert run(sp, [session(sp, ref)], [read(sp)], ledger=self.ledger(sp, ref, ref), macro_week=mw) == []

    def test_build_phase_does_not_suppress(self, sp):
        ref = SPORTS[sp]["ref"]
        mw = MacroWeek(week_start=MON, phase="Build 2", focus="f")
        found = run(sp, [session(sp, ref)], [read(sp)], ledger=self.ledger(sp, ref, ref), macro_week=mw)
        assert len(found) == 1

    def test_race_session_in_week_suppresses(self, sp):
        ref = SPORTS[sp]["ref"]
        race = session(sp, ref, day=MON + timedelta(days=5), kind="race")
        found = run(sp, [session(sp, ref), race], [read(sp)], ledger=self.ledger(sp, ref, ref))
        assert found == []


# --- rep length -------------------------------------------------------------------------------


@pytest.mark.parametrize("sp", SPORTS)
class TestRepLength:
    def r(self, sp):
        ref = SPORTS[sp]["ref"]
        cap = SPORTS[sp]["rep_len"] * (1 + STEP)
        return read(sp, rep_max=cap, rng=(ref, ref)), cap

    def test_fires_past_one_more_step(self, sp):
        r, cap = self.r(sp)
        ref = SPORTS[sp]["ref"]
        found = run(sp, [session(sp, cap * (1 + STEP) * 2.02, rep=cap * (1 + STEP) * 1.01)], [r])
        assert ids(found) == [f"progression-rep-length-{SPORTS[sp]['profile']}-threshold"]
        assert found[0].severity == "low"

    def test_silent_at_the_boundary(self, sp):
        r, cap = self.r(sp)
        ref = SPORTS[sp]["ref"]
        assert run(sp, [session(sp, cap * (1 + STEP) * 1.98, rep=cap * (1 + STEP) * 0.99)], [r]) == []


# --- weak data, estimated doses, one per kind ---------------------------------------------------


@pytest.mark.parametrize("sp", SPORTS)
class TestNoFireOnWeakData:
    def test_insufficient_data_read_is_silent(self, sp):
        r = read(sp, "insufficient_data")
        assert run(sp, [session(sp, SPORTS[sp]["ref"] * 5)], [r]) == []

    @pytest.mark.parametrize("verdict", ["progress", "reduce", "rebuild"])
    def test_low_confidence_read_is_silent(self, sp, verdict):
        r = read(sp, verdict, confidence="low")
        ref = SPORTS[sp]["ref"]
        ledger = [record(sp, ref, days_ago=12), record(sp, ref)]
        assert run(sp, [session(sp, ref * 5)], [r], ledger=ledger) == []
        assert run(sp, [session(sp, ref)], [r], ledger=ledger) == []

    def test_estimated_dose_session_only_unplanned_findings(self, sp):
        sess = session(sp, SPORTS[sp]["ref"] * 5, structured=False)
        review = WeekStimulusReview(week_start=MON, as_of=AS_OF, impacts=[impact(sess, "hard_too_soon")])
        found = run(sp, [sess], [read(sp, "reduce")], review=review)
        assert ids(found) == [f"unplanned-hard_too_soon-{sess.date.isoformat()}"]

    def test_unmatched_kind_or_sport_is_silent(self, sp):
        other = "swim" if sp == "bike" else "bike"
        r = read(other)
        assert run(sp, [session(sp, SPORTS[sp]["ref"] * 5)], [r]) == []
        assert run(sp, [session(sp, SPORTS[sp]["ref"] * 5)], [read(sp, kind="vo2")]) == []


def test_one_finding_per_sport_and_kind_keeps_most_severe():
    sp = "bike"
    r = read(sp, "reduce")
    big = session(sp, r.suggested_work_range[1] * (1 + STEP) * 2, day=MON + timedelta(days=1))
    same_as_ref = session(sp, SPORTS[sp]["ref"], day=MON + timedelta(days=4))
    found = run(sp, [same_as_ref, big], [r])
    assert len(found) == 1 and found[0].severity == "high"
    assert found[0].id == "progression-jump-bike-threshold"


def test_different_kinds_each_get_a_finding():
    ref = SPORTS["bike"]["ref"]
    tempo_read = read("bike", "reduce", kind="tempo")
    thr = read("bike", "reduce")
    thr_s = session("bike", ref)
    tempo_s = session("bike", ref, zone="Z3", day=MON + timedelta(days=4))
    found = run("bike", [thr_s, tempo_s], [thr, tempo_read])
    assert sorted(i.rsplit("-", 1)[1] for i in ids(found)) == ["tempo", "threshold"]


# --- unplanned impacts ---------------------------------------------------------------------------


def impact(sess, kind, evidence=None):
    return RemainingImpact(session_id=sess.id, date=sess.date, sport=sess.sport, kind="threshold",
                           impact=kind, evidence=evidence or [f"{kind} evidence for {sess.date.isoformat()}."])


@pytest.mark.parametrize("sp", SPORTS)
def test_unplanned_impacts_carry_evidence_and_severity(sp):
    sess = session(sp, SPORTS[sp]["ref"])
    review = WeekStimulusReview(week_start=MON, as_of=AS_OF, impacts=[
        impact(sess, "hard_too_soon", ["Hard session 24 h after unplanned long ride."]),
        impact(sess, "duplicate_stimulus"), impact(sess, "load_over_target")])
    found = run(sp, [sess], [], review=review)
    by_id = {f.id: f for f in found}
    d = sess.date.isoformat()
    assert set(by_id) == {f"unplanned-hard_too_soon-{d}", f"unplanned-duplicate_stimulus-{d}", f"unplanned-load_over_target-{d}"}
    hard = by_id[f"unplanned-hard_too_soon-{d}"]
    assert hard.severity == "medium" and "Hard session 24 h after unplanned long ride." in hard.evidence
    assert by_id[f"unplanned-duplicate_stimulus-{d}"].severity == "low"
    assert by_id[f"unplanned-load_over_target-{d}"].severity == "low"
    assert all(f.category == "judgment" for f in found)


def test_impacts_for_sessions_outside_the_week_are_ignored():
    sess = session("bike", 1800.0)
    stray = session("bike", 1800.0)
    review = WeekStimulusReview(week_start=MON, as_of=AS_OF, impacts=[impact(stray, "hard_too_soon")])
    assert run("bike", [sess], [], review=review) == []


# --- check_week wiring ----------------------------------------------------------------------------


def test_check_week_unchanged_without_progression():
    sp = "bike"
    w = week([session(sp, 9000.0)])
    before = check_week(w, None, ATHLETE, recent_weeks=[])
    assert check_week(w, None, ATHLETE, recent_weeks=[], progression=None) == before


def test_check_week_includes_progression_findings():
    sp = "bike"
    r = read(sp, "reduce")
    w = week([session(sp, r.suggested_work_range[1] * (1 + STEP) * 2)])
    report = check_week(w, None, ATHLETE, recent_weeks=[], progression=ProgressionInputs(reads=[r]))
    assert "progression-jump-bike-threshold" in [f.id for f in report.findings]
    assert report.verdict == "fragile"


def test_check_week_progression_judgment_outranks_same_severity_authoring_findings():
    """Ranking is severity first, then judgment before authoring: a medium progression finding
    sorts ahead of medium authoring findings."""
    sp = "bike"
    ref = SPORTS[sp]["ref"]
    r = read(sp, "reduce", rng=(1.2 * ref, 1.35 * ref))
    s = session(sp, ref)
    report = check_week(week([s]), None, ATHLETE, recent_weeks=[], progression=ProgressionInputs(reads=[r]))
    found = [(f.id, f.severity, f.category) for f in report.findings]
    assert found[0] == ("progression-ignores-reduce-bike-threshold", "medium", "judgment")
    assert any(sev == "medium" and cat == "authoring" for _, sev, cat in found[1:])


# --- convenience builder ----------------------------------------------------------------------------


def test_build_progression_inputs_wires_ledger_reads_and_review():
    d1, d2 = AS_OF - timedelta(days=9), AS_OF - timedelta(days=2)
    planned = [session("bike", 1800.0, day=d1), session("bike", 1800.0, day=d2)]
    w = week(planned)
    inputs = build_progression_inputs([], [w], [], ATHLETE, w, as_of=AS_OF)
    assert isinstance(inputs, ProgressionInputs)
    assert inputs.reads == [] and inputs.ledger == []
    assert inputs.review is not None and inputs.review.as_of == AS_OF


# --- CLI ------------------------------------------------------------------------------------------------


def test_cli_progression_prints_reads_review_and_findings(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("STORE_BACKEND", raising=False)
    from swim_coach.store import FileStore

    store = FileStore(base_dir=tmp_path)
    athlete = ATHLETE.model_copy(update={"slug": "cliath"})
    store.save_athlete(athlete)
    sess = session("bike", 1800.0, day=MON + timedelta(days=4))
    store.save_week("cliath", WeekPlan(id=uuid.uuid4(), athlete_id=AID, iso_week="2026-W46", meso_block="b",
                                       focus="f", target_volume_m=0, sessions=[sess]))
    code = main(["--base-dir", str(tmp_path), "progression", "--athlete", "cliath", "--as-of", AS_OF.isoformat()])
    out = json.loads(capsys.readouterr().out.strip())
    assert code == 0
    assert out["athlete"] == "cliath" and out["as_of"] == AS_OF.isoformat() and out["week"] == "2026-W46"
    assert out["reads"] == [] and out["review"]["week_start"] == MON.isoformat()
    assert out["findings"] == []


def test_cli_progression_unknown_athlete_is_a_json_error(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("STORE_BACKEND", raising=False)
    assert main(["--base-dir", str(tmp_path), "progression", "--athlete", "nobody"]) != 0
    assert "error" in json.loads(capsys.readouterr().out.strip())


# --- lever-based findings ---------------------------------------------------------------------

from lever_helpers import ROWS as LEVER_ROWS, lrec  # noqa: E402
from lever_helpers import shape as lever_shape  # noqa: E402
from swim_coach.lever_read import read_levers  # noqa: E402
from swim_coach.workout_builders import compile_workout  # noqa: E402

LEVER_SCENARIOS = {
    # ref: the last clean session; the rest are planned sessions and the finding each should draw.
    "bike": dict(ref="2x10 min/4 min Z4", multi="2x12 min/3 min Z4", big="2x20 min/4 min Z4", ok="2x12 min/4 min Z4",
                 top="2x20 min/5 min Z4", over="3x20 min/5 min Z4", cont="2x15 min/5 min Z4", then=250.0, now=262.0,
                 mid="2x12 min/5 min Z4", athlete=dict(ftp_watts=262.0)),
    "swim": dict(ref="8x100 m/15 s Z4", multi="8x150 m/10 s Z4", big="8x300 m/15 s Z4", ok="8x150 m/15 s Z4",
                 top="10x400 m/40 s Z4", over="12x400 m/40 s Z4", cont="8x300 m/15 s Z4", then=90.0, now=86.0,
                 mid="8x200 m/15 s Z4", athlete=dict(css_pace_s_per_100m=86.0)),
}


def lever_session(group: str, text: str, *, day=None, title=None, kind=None):
    row = LEVER_ROWS[group]
    compiled = compile_workout(lever_shape(group, text).to_intent(), ATHLETE)
    return Session(id=uuid.uuid4(), athlete_id=AID, date=day or MON + timedelta(days=2), sport=row["sport"],
                   source="ai_coach", duration_min=compiled.duration_min, distance_m=compiled.distance_m,
                   intensity=compiled.intensity, purpose="t", structured=compiled.structured, title=title,
                   **({"kind": kind} if kind else {}))


def lever_check(group: str, planned: str, ref: str | None = None, *, anchor=None, known=True, in_band=90.0,
                extra=(), ledger=None, **kw):
    sc = LEVER_SCENARIOS[group]
    athlete = Athlete(id=AID, slug="t", name="T", **sc["athlete"])
    records = [lrec(group, ref or sc["ref"], anchor=anchor, known=known, in_band=in_band)]
    reads = read_levers(records, athlete, as_of=AS_OF)
    sessions = [lever_session(group, planned), *extra]
    return check_week_progression(week(sessions), ATHLETE, reads=reads, ledger=records if ledger is None else ledger, **kw)


@pytest.mark.parametrize("group", LEVER_SCENARIOS)
class TestLeverFindings:
    def tag(self, group):
        return f"{LEVER_ROWS[group]['sport'].split('_')[0]}-threshold"

    def test_a_single_step_draws_nothing(self, group):
        assert lever_check(group, LEVER_SCENARIOS[group]["ok"]) == []

    def test_multi_lever(self, group):
        found = lever_check(group, LEVER_SCENARIOS[group]["multi"])
        assert ids(found) == [f"progression-multi-lever-{self.tag(group)}"]
        assert found[0].severity == "medium" and found[0].category == "judgment"
        sc = LEVER_SCENARIOS[group]
        assert f"last clean {sc['ref']}" in found[0].evidence and f"planned {sc['multi']}" in found[0].evidence
        assert "rest" in found[0].evidence
        assert "Next" in found[0].fix or "->" in found[0].fix

    def test_oversized_step_is_medium_and_high_after_a_poor_session(self, group):
        sc = LEVER_SCENARIOS[group]
        found = lever_check(group, sc["big"])
        assert ids(found) == [f"progression-oversized-step-{self.tag(group)}"] and found[0].severity == "medium"
        poor = lever_check(group, sc["big"], in_band=30.0)
        assert ids(poor)[0] == f"progression-oversized-step-{self.tag(group)}" and poor[0].severity == "high"

    def test_over_ceiling_cites_the_source(self, group):
        sc = LEVER_SCENARIOS[group]
        found = lever_check(group, sc["over"], ref=sc["top"])
        assert ids(found) == [f"progression-over-ceiling-{self.tag(group)}"] and found[0].severity == "medium"
        assert "Coach judgment" in found[0].evidence or "Dekerle" in found[0].evidence

    def test_rebase_ignored(self, group):
        sc = LEVER_SCENARIOS[group]
        found = lever_check(group, sc["cont"], ref=sc["mid"], anchor=sc["then"])
        assert ids(found) == [f"progression-threshold-rebase-{self.tag(group)}"] and found[0].severity == "medium"
        assert "restarting" in found[0].evidence and sc["mid"] in found[0].evidence

    def test_rebase_followed_is_silent(self, group):
        sc = LEVER_SCENARIOS[group]
        athlete = Athlete(id=AID, slug="t", name="T", **sc["athlete"])
        record = lrec(group, sc["mid"], anchor=sc["then"])
        restart = read_levers([record], athlete, as_of=AS_OF)[0].candidates[0].rung
        reads = read_levers([record], athlete, as_of=AS_OF)
        assert check_week_progression(week([lever_session(group, restart)]), ATHLETE, reads=reads, ledger=[record]) == []

    def test_retest_at_the_ceiling_is_low(self, group):
        sc = LEVER_SCENARIOS[group]
        found = lever_check(group, sc["top"], ref=sc["top"])
        sport = LEVER_ROWS[group]["sport"].split("_")[0]
        assert ids(found) == [f"progression-retest-{sport}"] and found[0].severity == "low"

    def test_retest_silent_when_a_test_is_planned_or_in_taper(self, group):
        sc = LEVER_SCENARIOS[group]
        test_day = lever_session(group, sc["top"], day=MON + timedelta(days=4), title="FTP test")
        assert lever_check(group, sc["top"], ref=sc["top"], extra=[test_day]) == []
        taper = MacroWeek(week_start=MON, phase="Taper 1", focus="f")
        assert lever_check(group, sc["top"], ref=sc["top"], macro_week=taper) == []

    def test_a_poor_last_session_with_no_shape_falls_back_to_the_dose_rules(self, group):
        sc = LEVER_SCENARIOS[group]
        athlete = Athlete(id=AID, slug="t", name="T", **sc["athlete"])
        record = lrec(group, sc["ref"])
        record.executed.dose = record.executed.dose.model_copy(update={"rep_sizes": None, "rest_gaps_s": None})
        reads = read_levers([record], athlete, as_of=AS_OF)
        assert reads[0].shape is None
        planned = lever_session(group, sc["big"])
        found = check_week_progression(week([planned]), ATHLETE, reads=reads, ledger=[record])
        assert all(not i.startswith(("progression-multi-lever", "progression-oversized", "progression-over-ceiling")) for i in ids(found))
        assert ids(found) == [f"progression-jump-{self.tag(group)}"]

    def test_only_sessions_still_to_do_are_judged(self, group):
        sc = LEVER_SCENARIOS[group]
        past = lever_session(group, sc["big"], day=AS_OF - timedelta(days=2))
        athlete = Athlete(id=AID, slug="t", name="T", **sc["athlete"])
        record = lrec(group, sc["ref"])
        reads = read_levers([record], athlete, as_of=AS_OF)
        found = check_week_progression(week([past]), ATHLETE, reads=reads, ledger=[record], as_of=AS_OF)
        assert found == []


def cli_lever_store(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("STORE_BACKEND", raising=False)
    from swim_coach.models import IntervalEffort, ThresholdRecord, Workout, WorkoutAnalytics, WorkoutIntervals
    from swim_coach.store import FileStore

    store = FileStore(base_dir=tmp_path)
    store.save_athlete(ATHLETE.model_copy(update={"slug": "cliath", "ftp_watts": 262.0}))
    iv = WorkoutIntervals(efforts_detected=3, detection_basis="power", reps_completed=3, reps_in_band_pct=100.0, efforts=[
        IntervalEffort(n=i + 1, start_s=600 + i * 900, duration_s=600, avg_w=250, verdict="ok") for i in range(3)])
    store.save_workout("cliath", Workout(id=uuid.uuid4(), athlete_id=AID, date=date(2026, 11, 3), sport="bike", source="fit",
                                         distance_m=0, duration_min=60, analytics=WorkoutAnalytics(intervals=iv)))
    store.save_threshold_record("cliath", ThresholdRecord(
        id=uuid.uuid4(), athlete_id=AID, sport="bike", metric="ftp_watts", value=250.0,
        measured_at=date(2026, 10, 1), source="ramp_test"))


def test_cli_progression_prints_shape_candidates_rebase_and_retest_flag(tmp_path, capsys, monkeypatch):
    cli_lever_store(tmp_path, monkeypatch)
    assert main(["--base-dir", str(tmp_path), "progression", "--athlete", "cliath", "--as-of", AS_OF.isoformat()]) == 0
    read = json.loads(capsys.readouterr().out.strip())["reads"][0]
    assert read["reference_rung"] == "3x10 min/5 min Z4"
    assert read["rebase"]["rebased"] is True and "FTP rose 5% (250 -> 262 W)" in read["rebase"]["reason"]
    assert [c["direction"] for c in read["candidates"]] == ["rebase"] and read["candidates"][0]["rung"]
    assert read["retest_suggested"] is False and read["at_ceiling"] is False
    assert all("compiled" not in c for c in read["candidates"])


def test_cli_progression_compile_adds_the_built_workout_to_each_candidate(tmp_path, capsys, monkeypatch):
    cli_lever_store(tmp_path, monkeypatch)
    args = ["--base-dir", str(tmp_path), "progression", "--athlete", "cliath", "--as-of", AS_OF.isoformat(), "--compile"]
    assert main(args) == 0
    cand = json.loads(capsys.readouterr().out.strip())["reads"][0]["candidates"][0]
    assert cand["compiled"]["adjustments"] == [] and cand["compiled"]["duration_min"] > 0
    assert cand["compiled"]["dose"]["work_s"] == pytest.approx(cand["shape"]["reps"] * cand["shape"]["rep_size"] * cand["shape"]["sets"], rel=0.02)
