"""Free-ride read (`swim_coach.free_ride`, owned by `BikeAnalyzer`): where the time went, notable
efforts, matches burned, cost vs the week, steady-stretch drift, data quality, and the coach view."""

from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path

import pytest

from swim_coach.analysis import AnalysisContext, analytics_for_coach
from swim_coach.free_ride import is_key_session
from swim_coach.models import Athlete, Session, Workout, WorkoutStructure

FIX = Path(__file__).resolve().parents[1] / "fixtures"
FTP = 276.0
RIDE_DAY = date(2026, 9, 29)  # a Tuesday
ATHLETE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _fixture(name: str):
    d = json.loads((FIX / f"ride_2026_{name}_free_ride.json").read_text())
    athlete = Athlete(id=ATHLETE_ID, slug="t", name="T", **d["athlete_profile"])
    return Workout.model_validate(d["workout"]), athlete, d["series"]


def _read(name: str, **ctx_kw):
    workout, athlete, series = _fixture(name)
    analytics = workout.analyze(AnalysisContext(athlete=athlete, kind="free_ride", series=series, **ctx_kw))
    return analytics, analytics.free_ride


# --- the three real rides ------------------------------------------------------------------


@pytest.mark.parametrize("name", ["08_30", "09_13", "09_28"])
def test_zones_plus_coasting_equal_moving_time(name):
    _, fr = _read(name)
    assert sum(z.seconds for z in fr.power_zones) + fr.coasting_s == fr.moving_s
    assert abs(sum(z.pct for z in fr.power_zones) - 100.0) < 0.5


@pytest.mark.parametrize("name", ["08_30", "09_13"])
def test_best_20_min_matches_the_power_curve(name):
    analytics, fr = _read(name)
    curve20 = next(p for p in analytics.power_curve if p.duration_s == 1200)
    e20 = fr.notable_efforts[0]
    assert e20.duration_s == 1200 and abs(e20.avg_w - curve20.watts) <= 2
    assert [e.duration_s for e in fr.notable_efforts] == [1200, 300, 60]
    assert e20.altitude_gain_m > 100 and e20.avg_grade_pct > 2.5  # these rides are climbs


def test_aug_30_reads_a_threshold_climb_and_the_matches_are_stable():
    _, fr = _read("08_30")
    assert fr.notable_efforts[1].label == "threshold climb"
    assert (fr.matches.count, fr.matches.time_above_ftp_s) == (27, 723)
    assert fr.matches.kj_above_ftp == pytest.approx(45.4, abs=0.2)
    assert fr.matches.efforts[0].kj_above_ftp >= fr.matches.efforts[-1].kj_above_ftp


def test_sep_13_matches_are_stable():
    _, fr = _read("09_13")
    assert (fr.matches.count, fr.matches.time_above_ftp_s) == (4, 105)


@pytest.mark.parametrize("name", ["08_30", "09_13"])
def test_no_tempo_verdict_without_a_stated_intent(name):
    _, fr = _read(name)
    assert fr.intent_zone is None and fr.tempo_creep is None and fr.tempo_creep_note is None
    assert fr.z3_plus_pct > 30  # the distribution is still reported


def test_cost_reuses_the_load_models_power_tss():
    analytics, fr = _read("08_30")
    assert fr.cost.tss == round(analytics.normalized_power_w ** 2 / FTP**2 * (158.5 / 60) * 100)
    assert fr.cost.intensity_factor == round(analytics.normalized_power_w / FTP, 2)
    assert fr.cost.note == f"TSS {fr.cost.tss:.0f}, IF {fr.cost.intensity_factor:.2f}"


def test_no_whole_ride_drift_verdict_for_a_stop_start_ride():
    _, fr = _read("08_30")
    assert fr.steady_drift == [] and "No steady stretch" in fr.steady_note


def test_sep_28_is_a_data_quality_case():
    _, fr = _read("09_28")
    assert fr.zero_or_null_power_pct > 60
    assert any("power reads are limited" in n for n in fr.data_quality_notes)
    assert any("Altitude range is only" in n for n in fr.data_quality_notes)
    assert all(e.label is None for e in fr.notable_efforts)
    assert fr.steady_drift == [] and fr.steady_note is None


def test_sep_28_cost_does_not_use_unreliable_power():
    analytics, fr = _read("09_28")
    assert fr.cost.cost_basis == "hr"
    assert fr.cost.tss is None and fr.cost.intensity_factor is None
    assert fr.cost.load_au > 0 and "from hr (power unreliable: no TSS or IF)" in fr.cost.note
    assert analytics.normalized_power_w  # the NP exists; it is just not trusted for cost


def test_reliable_power_cost_is_labelled_power():
    _, fr = _read("08_30")
    assert fr.cost.cost_basis == "power" and fr.cost.tss == fr.cost.load_au


def test_sep_28_gives_no_tempo_verdict_even_with_an_easy_intent():
    workout, athlete, series = _fixture("09_28")
    session = _session(RIDE_DAY, zone="Z2")
    fr = workout.analyze(AnalysisContext(athlete=athlete, session=session, kind="free_ride", series=series)).free_ride
    assert fr.intent_zone == "Z2" and fr.tempo_creep is None


# --- synthetic rides -----------------------------------------------------------------------


def _series(power: list[float], hr: list[float] | None = None, alt: list[float] | None = None) -> dict:
    n = len(power)
    return {
        "t_s": list(range(n)),
        "power_w": power,
        "hr": hr if hr is not None else [140.0] * n,
        "altitude_m": alt if alt is not None else [800.0 + i * 0.05 for i in range(n)],
        "dist_m": [i * 6.0 for i in range(n)],
    }


def _workout(minutes: float, day: date = RIDE_DAY) -> Workout:
    return Workout(
        id=uuid.uuid4(), athlete_id=ATHLETE_ID, date=day, sport="bike", source="fit",
        distance_m=0, duration_min=minutes,
    )


def _session(day: date, *, zone: str | None = "Z2", kind="workout", structured=False, title="Ride") -> Session:
    return Session(
        id=uuid.uuid4(), athlete_id=ATHLETE_ID, date=day, sport="bike", source="ai_coach", duration_min=60.0,
        intensity={"zone": zone} if zone else {}, purpose="easy spin", title=title, kind=kind,
        structured=WorkoutStructure(items=[]) if structured else None,
    )


def _athlete() -> Athlete:
    return Athlete(id=ATHLETE_ID, slug="t", name="T", ftp_watts=FTP, lthr_bpm=172)


def _analyze(power, *, session=None, kind="free_ride", neighbors=(), hr=None, alt=None):
    w = _workout(len(power) / 60)
    ctx = AnalysisContext(
        athlete=_athlete(), session=session, kind=kind, series=_series(power, hr, alt), neighbors=neighbors
    )
    return w.analyze(ctx)


def test_easy_intent_with_lots_of_tempo_triggers_tempo_creep():
    # 40 min Z2 (170 W), 40 min Z3 (230 W = 83% FTP)
    fr = _analyze([170.0] * 2400 + [230.0] * 2400, session=_session(RIDE_DAY, zone="Z2")).free_ride
    assert fr.tempo_creep is True and fr.z3_plus_pct == 50.0
    assert "Planned Z2" in fr.tempo_creep_note


def test_easy_intent_kept_easy_is_not_creep_and_hard_intent_gets_no_verdict():
    easy = _analyze([170.0] * 4800, session=_session(RIDE_DAY, zone="Z2")).free_ride
    assert easy.tempo_creep is False and "fit the intent" in easy.tempo_creep_note
    hard = _analyze([230.0] * 4800, session=_session(RIDE_DAY, zone="Z4")).free_ride
    assert hard.tempo_creep is None


def test_a_short_tempo_burst_on_an_easy_ride_is_below_the_minimum_time():
    fr = _analyze([170.0] * 600 + [230.0] * 300, session=_session(RIDE_DAY, zone="Z2")).free_ride
    assert fr.z3_plus_pct > 20 and fr.tempo_creep is False


def test_matches_burned_counts_efforts_above_ftp_and_merges_short_gaps():
    power = [150.0] * 300 + [450.0] * 40 + [150.0] * 4 + [450.0] * 40 + [150.0] * 300 + [450.0] * 5 + [150.0] * 300
    fr = _analyze(power).free_ride
    # two 40 s blocks 4 s apart merge into one; the 5 s sprint is too short to count
    assert fr.matches.count == 1
    m = fr.matches.efforts[0]
    assert m.start_offset_s == pytest.approx(300, abs=15) and m.duration_s >= 84
    assert m.kj_above_ftp == pytest.approx(80 * (450 - FTP) / 1000, abs=0.8)
    assert fr.matches.time_above_ftp_s == m.duration_s


def test_steady_stretch_drift_is_read_only_over_the_steady_segment():
    n = 2700  # 45 min steady at 200 W, HR climbing 135 -> 150
    hr = [135.0 + 15.0 * i / n for i in range(n)]
    steady = _analyze([200.0] * n, hr=hr).free_ride
    assert len(steady.steady_drift) == 1
    seg = steady.steady_drift[0]
    assert seg.duration_min >= 44 and seg.power_cv_pct < 1 and 4 < seg.drift_pct < 7
    # a stop-start ride (40 s on / 20 s coasting) has no steady stretch
    choppy = _analyze([220.0 if (i // 20) % 3 != 2 else 0.0 for i in range(2700)]).free_ride
    assert choppy.steady_drift == [] and "No steady stretch" in choppy.steady_note


def test_flat_altitude_skips_the_climb_label_but_keeps_the_zone_label():
    flat = _analyze([270.0] * 1500, alt=[800.0] * 1500).free_ride
    assert flat.notable_efforts[0].label == "threshold effort"
    assert any("climb calls skipped" in n for n in flat.data_quality_notes)


def test_a_climb_is_called_a_climb():
    alt = [800.0 + i * 0.3 for i in range(1500)]  # 0.3 m/s at 6 m/s = 5% grade
    fr = _analyze([250.0] * 1500, alt=alt).free_ride
    e = fr.notable_efforts[0]
    assert e.label == "threshold climb" and e.altitude_gain_m == pytest.approx(360, abs=10)
    assert e.avg_grade_pct == pytest.approx(5.0, abs=0.3)


# --- cost vs the week ----------------------------------------------------------------------


def test_cost_note_names_the_key_session_the_day_after():
    tuesday_key = _session(date(2026, 9, 30), zone="Z4", title="3x10 threshold")
    fr = _analyze([200.0] * 3600, neighbors=(tuesday_key,)).free_ride
    assert [(n.relation, n.date) for n in fr.cost.adjacent_key_sessions] == [("after", date(2026, 9, 30))]
    assert fr.cost.note.startswith("TSS ") and "the day before Wednesday's key session (3x10 threshold)" in fr.cost.note


def test_cost_note_names_the_key_session_the_day_before_and_ignores_easy_days():
    key = _session(date(2026, 9, 28), zone="Z5", title="VO2 40/20")
    easy = _session(date(2026, 9, 30), zone="Z2")
    fr = _analyze([200.0] * 3600, neighbors=(key, easy)).free_ride
    assert [n.relation for n in fr.cost.adjacent_key_sessions] == ["before"]
    assert "the day after Monday's key session" in fr.cost.note


def test_what_counts_as_a_key_session():
    assert is_key_session(_session(RIDE_DAY, zone="Z4"))
    assert is_key_session(_session(RIDE_DAY, zone="Z2", structured=True))
    assert is_key_session(_session(RIDE_DAY, zone="Z2", kind="race"))
    assert not is_key_session(_session(RIDE_DAY, zone="Z2"))
    assert not is_key_session(_session(RIDE_DAY, zone="Z5", kind="opener"))


# --- which rides get the read --------------------------------------------------------------


def test_only_unstructured_rides_get_the_free_ride_read():
    power = [180.0] * 1800
    assert _analyze(power, kind="free_ride").free_ride is not None
    assert _analyze(power, kind="workout", session=_session(RIDE_DAY)).free_ride is not None
    assert _analyze(power, kind="workout", session=_session(RIDE_DAY, structured=True)).free_ride is None
    assert _analyze(power, kind="race", session=_session(RIDE_DAY, kind="race")).free_ride is None
    assert _analyze(power, kind="opener", session=_session(RIDE_DAY, kind="opener")).free_ride is None


def test_no_ftp_or_no_power_means_no_read():
    w = _workout(30)
    no_ftp = AnalysisContext(athlete=Athlete(id=ATHLETE_ID, slug="t", name="T"), kind="free_ride", series=_series([200.0] * 1800))
    assert w.analyze(no_ftp).free_ride is None
    no_power = AnalysisContext(athlete=_athlete(), kind="free_ride", series={"t_s": [0, 1], "hr": [100, 101]})
    assert w.analyze(no_power).free_ride is None


# --- coach view ----------------------------------------------------------------------------


def test_coach_view_leads_with_the_compact_free_ride_block():
    analytics, _ = _read("08_30")
    view = analytics_for_coach(analytics, "bike")
    assert list(view)[0] == "free_ride"
    assert "cardiac_drift_pct" not in view  # no whole-ride drift verdict on a free ride
    block = view["free_ride"]
    assert block["coach_note"].startswith("For a free ride, lead with what mattered")
    assert len(block["notable_efforts"]) == 3 and block["notable_efforts"][0].endswith("tempo climb")
    assert block["matches_burned"]["count"] == 27 and len(block["matches_burned"]["top"]) == 3
    assert block["cost_vs_week"].startswith("TSS 151")
    assert "power_zones_pedalling" in block and "hr_zones" in block


def test_coach_view_of_the_data_quality_case_leads_with_the_note():
    analytics, _ = _read("09_28")
    block = analytics_for_coach(analytics, "bike")["free_ride"]
    assert list(block)[:2] == ["coach_note", "data_quality"]


def test_swim_and_race_views_carry_no_free_ride_block():
    workout, athlete, series = _fixture("08_30")
    race = workout.analyze(AnalysisContext(athlete=athlete, kind="race", series=series))
    assert "free_ride" not in analytics_for_coach(race, "bike")
    assert "free_ride" not in analytics_for_coach(race, "swim_pool")
