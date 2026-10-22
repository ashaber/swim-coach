"""Workout.analyze(ctx): golden regression against the pre-refactor path, registry dispatch,
kind derivation, untagged-session defaults and the override."""

from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path

import pytest

from swim_coach import analysis
from swim_coach.analysis import (
    ANALYZERS,
    AnalysisContext,
    DefaultAnalyzer,
    build_analysis_context,
    derive_workout_kind,
)
from swim_coach.analytics import compute_analytics
from swim_coach.models import Athlete, Event, Session, Workout, WorkoutLap, WorkoutLength

FIX = Path(__file__).resolve().parents[1] / "fixtures"
GOLDEN = json.loads((FIX / "golden_analytics_old.json").read_text())
NAMES = sorted(GOLDEN)
ATHLETE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _athlete(profile: dict) -> Athlete:
    return Athlete(id=ATHLETE_ID, slug="t", name="T", **profile)


def _fixture(name: str):
    d = json.loads((FIX / name).read_text())
    session = Session.model_validate(d["planned_session"]) if d.get("planned_session") else None
    return Workout.model_validate(d["workout"]), session, _athlete(d["athlete_profile"]), d["series"]


# Swim pace/set fields added after the goldens were pinned (None/empty on a ride).
_SWIM_ADDED = {
    "pool_unit", "pool_length_m", "moving_pace_s_per_100m", "elapsed_pace_s_per_100m",
    "moving_pace_s_per_100_unit", "elapsed_pace_s_per_100_unit", "rest_total_s", "swim_sets", "segmentation_note",
}


def _without_dynamics(analytics) -> dict:
    """The dump minus the MTB-dynamics, race-efficiency, race-view and canonical-lap blocks (added after the goldens were
    pinned) and the race lap table (now cut from the canonical laps, see test_canonical_laps); these
    fixtures carry no grit/flow, so the dynamics must be absent."""
    assert analytics.mtb_dynamics is None
    return _golden_shape(analytics.model_dump(mode="json", exclude={"mtb_dynamics", "course_sectors", "race_efficiency", "laps", "race_overview", "race_start", "finish_sprint", *_SWIM_ADDED}))


def _golden_shape(dump: dict) -> dict:
    """The dump with the race lap table left out (compared elsewhere). `moving_min` is dropped: the
    goldens pinned the old device-timer value; it is now elapsed minus pauses (test_swim_sets)."""
    dump = {k: v for k, v in dump.items() if k != "moving_min"}
    if dump.get("intervals"):
        dump = {**dump, "intervals": {k: v for k, v in dump["intervals"].items() if k != "race_laps"}}
    return dump


# --- golden: the new path reproduces the old one -------------------------------------------


@pytest.mark.parametrize("name", NAMES)
def test_golden_no_session(name):
    workout, _, athlete, series = _fixture(name)
    kind = "race" if name.startswith("race_") else "free_ride"
    new = workout.analyze(AnalysisContext(athlete=athlete, kind=kind, series=series))
    assert _without_dynamics(new) == _golden_shape(GOLDEN[name]["no_session"])


@pytest.mark.parametrize("name", [n for n in NAMES if "with_session" in GOLDEN[n]])
def test_golden_with_matched_session(name):
    workout, session, athlete, series = _fixture(name)
    ctx = AnalysisContext(athlete=athlete, session=session, kind=session.kind, series=series)
    assert _without_dynamics(workout.analyze(ctx)) == _golden_shape(GOLDEN[name]["with_session"])


@pytest.mark.parametrize("kind", ["opener", "warmup"])
def test_opener_and_warmup_get_base_numbers_and_curve_but_no_intervals(kind):
    workout, session, athlete, series = _fixture("ride_2026_10_10_starts_race_pace.json")
    full = workout.analyze(AnalysisContext(athlete=athlete, session=session, kind="workout", series=series))
    warm = workout.analyze(AnalysisContext(athlete=athlete, session=session, kind=kind, series=series))
    assert full.intervals is not None and warm.intervals is None
    assert warm.power_curve and warm.normalized_power_w == full.normalized_power_w
    assert warm.avg_power_w == full.avg_power_w


# --- other sports: base analytics, no interval layer ----------------------------------------


def _swim() -> Workout:
    laps = [WorkoutLap(index=i, duration_s=120.0, distance_m=100) for i in range(4)]
    lengths = [WorkoutLength(index=i, duration_s=30.0, swolf=50 + i) for i in range(8)]
    return Workout(
        id=uuid.uuid4(), athlete_id=ATHLETE_ID, date=date(2026, 9, 1), sport="swim_pool", source="fit",
        distance_m=400, duration_min=8.0, laps=laps, lengths=lengths,
    )


@pytest.mark.parametrize("sport", ["swim_pool", "swim_ow", "strength", "cross_train"])
def test_non_bike_sports_get_unchanged_base_analytics(sport):
    w = _swim().model_copy(update={"sport": sport})
    old = compute_analytics(
        laps=w.laps, lengths=w.lengths, pauses=w.pauses, series=None, elapsed_min=None,
        moving_min=w.duration_min, sport=sport,
    )
    new = w.analyze(AnalysisContext(athlete=_athlete({"ftp_watts": 250.0}), kind="free_ride"))
    # moving_min (now true moving time) and the swim pace/set fields are covered in test_swim_sets.
    skip = {"moving_min", *_SWIM_ADDED}
    assert new.model_dump(mode="json", exclude=skip) == old.model_dump(mode="json", exclude=skip)
    assert new.intervals is None


def test_registry_dispatch_by_sport(monkeypatch):
    calls: list[str] = []

    class Spy:
        def analyze(self, workout, ctx):
            calls.append(workout.sport)
            return DefaultAnalyzer().analyze(workout, ctx)

    monkeypatch.setitem(ANALYZERS, "swim_pool", Spy())
    _swim().analyze(AnalysisContext())
    _swim().model_copy(update={"sport": "strength"}).analyze(AnalysisContext())
    assert calls == ["swim_pool"]
    assert isinstance(analysis.analyzer_for("strength"), DefaultAnalyzer)
    assert analysis.has_detailed_analyzer("bike") and not analysis.has_detailed_analyzer("strength")


# --- kind derivation ------------------------------------------------------------------------


def _event(day: date, sport: str) -> Event:
    return Event(
        id=uuid.uuid4(), athlete_id=ATHLETE_ID, name="E", event_date=day, distance_m=1000,
        priority="A", primary_sport=sport,
    )


def _session(**kw) -> Session:
    base = dict(
        id=uuid.uuid4(), athlete_id=ATHLETE_ID, date=date(2026, 9, 1), sport="swim_pool", source="ai_coach",
        duration_min=60, intensity={}, purpose="easy",
    )
    return Session(**{**base, **kw})


def test_kind_from_matched_session_wins():
    w = _swim()
    assert derive_workout_kind(w, _session(kind="warmup"), [_event(w.date, "swim")]) == "warmup"
    assert derive_workout_kind(w, _session(kind="opener"), []) == "opener"


def test_event_on_the_date_makes_a_race_for_any_matching_sport():
    w = _swim()
    assert derive_workout_kind(w, None, [_event(w.date, "swim")]) == "race"
    assert derive_workout_kind(w, None, [_event(w.date, "bike")]) == "free_ride"
    assert derive_workout_kind(w, None, [_event(date(2026, 9, 2), "swim")]) == "free_ride"
    ride = w.model_copy(update={"sport": "bike"})
    assert derive_workout_kind(ride, None, [_event(w.date, "bike")]) == "race"


def test_no_session_no_event_is_a_free_ride():
    assert derive_workout_kind(_swim(), None, []) == "free_ride"


def test_effective_kind_override_wins():
    w = _swim().model_copy(update={"kind": "free_ride", "kind_override": "race"})
    assert w.effective_kind == "race"
    assert _swim().effective_kind is None


class _Store:
    def __init__(self, athlete, events=(), workouts=()):
        self.athlete, self.events, self.workouts = athlete, list(events), list(workouts)

    def load_athlete(self, slug):
        return self.athlete

    def load_events(self, slug):
        return self.events

    def list_workouts(self, slug, since=None):
        return self.workouts


def test_build_context_derives_stamps_and_honors_override():
    w = _swim()
    store = _Store(_athlete({"ftp_watts": 260.0}), events=[_event(w.date, "swim")])
    ctx = build_analysis_context(store, "t", w)
    assert ctx.kind == "race" and w.kind == "race" and ctx.athlete.ftp_watts == 260.0
    w.kind_override = "free_ride"
    ctx = build_analysis_context(store, "t", w)
    assert ctx.kind == "free_ride" and w.kind == "race"


def test_build_context_survives_store_failures():
    class Broken(_Store):
        def load_athlete(self, slug):
            raise RuntimeError("boom")

        def load_events(self, slug):
            raise RuntimeError("boom")

    ctx = build_analysis_context(Broken(None), "t", _swim())
    assert ctx.athlete is None and ctx.kind == "free_ride"


def test_power_curve_bests_annotated_inside_analysis():
    workout, _, athlete, series = _fixture("ride_2026_10_10_starts_race_pace.json")
    first = workout.analyze(AnalysisContext(athlete=athlete, kind="free_ride", series=series))
    earlier = workout.model_copy(
        update={"id": uuid.uuid4(), "date": date(2026, 10, 1), "analytics": first}
    ).model_copy(update={"date": date(2026, 10, 1)})
    later = workout.model_copy(update={"date": date(2026, 10, 10)})
    out = later.analyze(
        AnalysisContext(athlete=athlete, kind="free_ride", series=series, prior_workouts=(earlier,))
    )
    base = later.analyze(AnalysisContext(athlete=athlete, kind="free_ride", series=series))
    assert out.model_dump(mode="json")["power_curve"] != base.model_dump(mode="json")["power_curve"]


# --- Session.kind: no string guessing ------------------------------------------------------


@pytest.mark.parametrize("purpose", ["RACE — Cross", "RACE -- Season Opener", "Build — VO2", "prose session"])
def test_untagged_session_stays_none_and_reads_as_workout(purpose):
    s = _session(purpose=purpose, sport="bike")
    assert s.kind is None and s.effective_kind == "workout"


def test_explicit_kind_is_kept_and_roundtrips():
    s = _session(purpose="RACE — x", kind="free_ride")
    assert s.kind == "free_ride" and s.effective_kind == "free_ride"
    assert Session.model_validate(s.model_dump(mode="json")).kind == "free_ride"


def test_untagged_session_on_an_event_day_defers_to_the_event():
    w = _swim()
    assert derive_workout_kind(w, _session(), [_event(w.date, "swim")]) == "race"
    assert derive_workout_kind(w, _session(kind="workout"), [_event(w.date, "swim")]) == "workout"
    assert derive_workout_kind(w, _session(), []) == "workout"
