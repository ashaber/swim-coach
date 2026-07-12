"""Tests for swim_coach.parse_files (.tcx / .csv / .fit ingest).

No LLM, no network. .fit tests that need real content are guarded with
pytest.mark.skipif on a real fixture that doesn't exist yet -- see
tests/unit/fixtures/fit/README.md.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from swim_coach.models import WorkoutPause
from swim_coach.parse_files import (
    WorkoutDraft,
    _fit_sport,
    _is_cycling_sport,
    _merge_pauses,
    _sport_detail,
    parse_csv,
    parse_fit,
    parse_tcx,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
TCX_FIXTURE = FIXTURES_DIR / "tcx" / "sample_pool_swim.tcx"
TCX_NO_LAPS_FIXTURE = FIXTURES_DIR / "tcx" / "no_laps.tcx"
CSV_FIXTURE = FIXTURES_DIR / "csv" / "sample_garmin_export.csv"
FIT_FIXTURE = FIXTURES_DIR / "fit" / "real_swim.fit"
FIT_KAYAK_FIXTURE = FIXTURES_DIR / "fit" / "real_kayak.fit"
FIT_MTB_RACE_FIXTURE = FIXTURES_DIR / "fit" / "real_mtb_race.fit"
FIT_MTB_0709_FIXTURE = FIXTURES_DIR / "fit" / "real_mtb_0709.fit"


# --- WorkoutDraft shape --------------------------------------------------------------


def test_workout_draft_has_no_id_or_athlete_id_fields():
    fields = WorkoutDraft.model_fields
    assert "id" not in fields
    assert "athlete_id" not in fields
    assert "warnings" in fields


# --- parse_tcx -------------------------------------------------------------------------


def test_parse_tcx_extracts_totals_and_laps_as_sets():
    draft = parse_tcx(TCX_FIXTURE)
    assert isinstance(draft, WorkoutDraft)
    assert draft.source == "tcx"
    assert draft.date == date(2026, 2, 1)
    assert draft.distance_m == 600
    assert draft.duration_min == 12.0
    assert draft.avg_pace_s_per_100m == pytest.approx(120.0)
    assert len(draft.sets) == 3
    assert [s.distance_m for s in draft.sets] == [100, 200, 300]


def test_parse_tcx_defaults_sport_to_pool_and_documents_assumption():
    draft = parse_tcx(TCX_FIXTURE)
    assert draft.sport == "swim_pool"
    assert any("assumed swim_pool" in w for w in draft.warnings)


def test_parse_tcx_no_laps_warns_and_zeros_out():
    draft = parse_tcx(TCX_NO_LAPS_FIXTURE)
    assert draft.distance_m == 0
    assert draft.sets == []
    assert draft.duration_min == 0.1  # floored to satisfy Workout's duration_min > 0
    assert any("no <Lap>" in w for w in draft.warnings)


def test_parse_tcx_missing_file_raises():
    with pytest.raises(OSError):
        parse_tcx(FIXTURES_DIR / "tcx" / "does_not_exist.tcx")


# --- parse_csv -------------------------------------------------------------------------


def test_parse_csv_extracts_from_common_headers():
    draft = parse_csv(CSV_FIXTURE)
    assert draft.source == "csv"
    assert draft.date == date(2026, 2, 3)
    assert draft.sport == "swim_pool"
    assert draft.distance_m == 2500
    assert draft.duration_min == pytest.approx(45.5)
    assert draft.avg_pace_s_per_100m == pytest.approx(109.0)
    assert draft.sets == []  # summary CSV rows carry no per-lap detail


def test_parse_csv_tolerates_missing_columns(tmp_path):
    csv_path = tmp_path / "minimal.csv"
    csv_path.write_text("Distance,Time\n1000,20:00\n", encoding="utf-8")

    draft = parse_csv(csv_path)
    assert draft.distance_m == 1000
    assert draft.duration_min == pytest.approx(20.0)
    assert draft.sport == "swim_pool"
    assert draft.date == date.today()
    assert any("no recognizable date column" in w for w in draft.warnings)
    assert any("no recognizable activity-type column" in w for w in draft.warnings)
    # No avg pace column -- derived from distance/duration instead.
    assert draft.avg_pace_s_per_100m == pytest.approx(120.0)


def test_parse_csv_no_data_rows_raises(tmp_path):
    csv_path = tmp_path / "empty.csv"
    csv_path.write_text("Distance,Time\n", encoding="utf-8")
    with pytest.raises(ValueError):
        parse_csv(csv_path)


def test_parse_csv_infers_open_water_from_activity_type(tmp_path):
    csv_path = tmp_path / "ow.csv"
    csv_path.write_text(
        "Date,Activity Type,Distance,Time\n2026-03-01,Open Water Swimming,3000,50:00\n",
        encoding="utf-8",
    )
    draft = parse_csv(csv_path)
    assert draft.sport == "swim_ow"


# --- parse_fit ---------------------------------------------------------------------------


def test_fit_sport_open_water_sub_sport_wins():
    warnings: list[str] = []
    assert _fit_sport("swimming", "open_water", warnings) == "swim_ow"
    assert warnings == []


def test_fit_sport_swimming_maps_to_pool():
    warnings: list[str] = []
    assert _fit_sport("swimming", "lap_swimming", warnings) == "swim_pool"
    assert warnings == []


def test_fit_sport_missing_defaults_to_pool_with_warning():
    warnings: list[str] = []
    assert _fit_sport(None, None, warnings) == "swim_pool"
    assert len(warnings) == 1
    assert "assumed swim_pool" in warnings[0]


def test_fit_sport_non_swim_maps_to_cross_train_with_warning():
    # A kayak/paddle/run/ride .fit must never be silently logged as a swim --
    # it would pollute swim-volume math (first real .fit file, 2026-07-09,
    # was a kayak session the old code labeled swim_pool with no warning).
    warnings: list[str] = []
    assert _fit_sport("kayaking", None, warnings) == "cross_train"
    assert len(warnings) == 1
    assert "kayaking" in warnings[0]
    assert "cross_train" in warnings[0]


def test_fit_sport_training_sub_sport_strength_maps_to_strength():
    # Garmin encodes a logged strength workout as session.sport="training",
    # sub_sport="strength_training" (surfaces in intervals.icu as
    # "WeightTraining"). This must land on the engine's own "strength" Sport,
    # not cross_train, so it doesn't get lumped in with kayak/run/ride
    # sessions -- it still counts toward sRPE load, never swim volume,
    # exactly like cross_train does.
    warnings: list[str] = []
    assert _fit_sport("training", "strength_training", warnings) == "strength"
    assert warnings == []


def test_fit_sport_training_no_sub_sport_maps_to_strength():
    # session.sport=="training" alone (no sub_sport) is unambiguous enough
    # on its own -- Garmin doesn't use "training" for anything else.
    warnings: list[str] = []
    assert _fit_sport("training", None, warnings) == "strength"
    assert warnings == []


def test_fit_sport_rowing_still_maps_to_cross_train_with_warning():
    # Non-training, non-swim sports are unaffected by the strength carve-out.
    warnings: list[str] = []
    assert _fit_sport("rowing", None, warnings) == "cross_train"
    assert len(warnings) == 1
    assert "rowing" in warnings[0]
    assert "cross_train" in warnings[0]


def test_parse_fit_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        parse_fit(FIXTURES_DIR / "fit" / "does_not_exist.fit")


@pytest.mark.skipif(
    not FIT_FIXTURE.exists(),
    reason=(
        "no real .fit fixture -- export a real pool swim .fit from Garmin "
        "Connect and drop it at tests/unit/fixtures/fit/real_swim.fit to "
        "activate this test (see fixtures/fit/README.md)"
    ),
)
def test_parse_fit_real_fixture_extracts_session_and_laps():
    draft = parse_fit(FIT_FIXTURE)
    assert draft.source == "fit"
    assert draft.distance_m > 0
    assert draft.duration_min > 0
    assert len(draft.sets) > 0


# --- parse_fit: real pool-swim fixture (lengths, SWOLF, no HR, no series) -------------


@pytest.mark.skipif(not FIT_FIXTURE.exists(), reason="no real pool .fit fixture")
def test_parse_fit_pool_extracts_71_active_lengths():
    draft = parse_fit(FIT_FIXTURE)
    assert draft.sport == "swim_pool"
    assert len(draft.lengths) == 71
    assert all(length.stroke is not None for length in draft.lengths)


@pytest.mark.skipif(not FIT_FIXTURE.exists(), reason="no real pool .fit fixture")
def test_parse_fit_pool_lengths_carry_swolf_when_strokes_and_duration_present():
    draft = parse_fit(FIT_FIXTURE)
    swolf_values = [length.swolf for length in draft.lengths if length.swolf is not None]
    assert len(swolf_values) == 71
    assert all(v > 0 for v in swolf_values)


@pytest.mark.skipif(not FIT_FIXTURE.exists(), reason="no real pool .fit fixture")
def test_parse_fit_pool_has_no_heart_rate():
    # Verified via fitdecode against the raw file: the pool swim's record
    # frames carry only temperature+timestamp (see fixtures/fit/README.md).
    draft = parse_fit(FIT_FIXTURE)
    assert draft.avg_hr is None
    assert draft.max_hr is None
    if draft.series is not None:
        assert "hr" not in draft.series


@pytest.mark.skipif(not FIT_FIXTURE.exists(), reason="no real pool .fit fixture")
def test_parse_fit_pool_produces_no_sidecar_series():
    # No hr/speed/dist/lat/lng in this pool file's record frames (only
    # temperature+timestamp) -- no sidecar should be produced.
    draft = parse_fit(FIT_FIXTURE)
    assert draft.series is None


@pytest.mark.skipif(not FIT_FIXTURE.exists(), reason="no real pool .fit fixture")
def test_parse_fit_pool_captures_one_lap_with_num_lengths():
    draft = parse_fit(FIT_FIXTURE)
    assert len(draft.laps) == 1
    assert draft.laps[0].num_lengths == 71
    assert draft.laps[0].stroke == "mixed"


# --- parse_fit: real kayak fixture (HR/GPS/distance series, cross_train) -------------


@pytest.mark.skipif(not FIT_KAYAK_FIXTURE.exists(), reason="no real kayak .fit fixture")
def test_parse_fit_kayak_maps_to_cross_train():
    draft = parse_fit(FIT_KAYAK_FIXTURE)
    assert draft.sport == "cross_train"
    assert any("cross_train" in w for w in draft.warnings)


@pytest.mark.skipif(not FIT_KAYAK_FIXTURE.exists(), reason="no real kayak .fit fixture")
def test_parse_fit_kayak_series_has_hr_and_distance_channels_over_4000_samples():
    draft = parse_fit(FIT_KAYAK_FIXTURE)
    assert draft.series is not None
    assert "hr" in draft.series
    assert "dist_m" in draft.series
    assert "lat" in draft.series
    assert "lng" in draft.series
    assert len(draft.series["t_s"]) > 4000
    assert any(v is not None for v in draft.series["hr"])
    # First record has no GPS lock (see fixtures/fit/README.md) -- lat/lng
    # must tolerate a leading None rather than crash or drop the sample.
    assert draft.series["lat"][0] is None


@pytest.mark.skipif(not FIT_KAYAK_FIXTURE.exists(), reason="no real kayak .fit fixture")
def test_parse_fit_kayak_session_avg_hr_present():
    draft = parse_fit(FIT_KAYAK_FIXTURE)
    assert draft.avg_hr is not None
    assert draft.max_hr is not None


@pytest.mark.skipif(not FIT_KAYAK_FIXTURE.exists(), reason="no real kayak .fit fixture")
def test_parse_fit_kayak_pauses_are_deterministic():
    # Pinned, not just "some number": the real kayak export has no idle
    # lengths, no timer stop/start event pair, and no record-timestamp gap
    # over GAP_THRESHOLD_S (max observed gap ~19s, smart-recording variance)
    # -- so zero pauses is the correct, deterministic answer for this file,
    # not a gap in the detector.
    #
    # Reconciliation note (stationary-pause detector, PR2): this fixture
    # DOES carry a speed_mps series, and running STATIONARY_SPEED_MPS/
    # STATIONARY_MIN_S against it raw (before the cycling-only gate below
    # existed) produced ~50 false-positive "stops" over the single 5-hour
    # trip -- this kayak trip's average speed (11,494m / 18,196s = 0.63
    # m/s) sits right at the 0.5 m/s threshold, so ordinary slow-paddling
    # variance trips it constantly. Verified live against this exact file
    # during development; see library/11-workout-analytics.md's
    # "Stationary-speed pause detection" section for the full writeup. The
    # fix is _is_cycling_sport (below): parse_fit only runs the stationary
    # detector when the raw FIT session.sport is "cycling" (the only sport
    # family this threshold is calibrated against), so this fixture
    # (session.sport="kayaking") never reaches the detector and stays at
    # zero pauses, same as before this feature existed.
    draft = parse_fit(FIT_KAYAK_FIXTURE)
    assert draft.pauses == []
    assert draft.series is not None
    assert "speed_mps" in draft.series


@pytest.mark.skipif(not FIT_KAYAK_FIXTURE.exists(), reason="no real kayak .fit fixture")
def test_parse_fit_kayak_has_no_lengths():
    draft = parse_fit(FIT_KAYAK_FIXTURE)
    assert draft.lengths == []


@pytest.mark.skipif(not FIT_KAYAK_FIXTURE.exists(), reason="no real kayak .fit fixture")
def test_parse_fit_kayak_sport_detail_is_kayaking_not_paddling_kayaking():
    # Real fixture's raw FIT session frame carries sport="kayaking",
    # sub_sport="generic" (verified via fitdecode against the actual file,
    # not assumed) -- NOT "paddling"/"kayaking" as the brief's own example
    # guessed before the real fixture was inspected. A generic sub_sport
    # formats as the sport alone (see _sport_detail's docstring).
    draft = parse_fit(FIT_KAYAK_FIXTURE)
    assert draft.sport_detail == "kayaking"


@pytest.mark.skipif(not FIT_FIXTURE.exists(), reason="no real pool .fit fixture")
def test_parse_fit_pool_sport_detail_is_none():
    # swim_pool/swim_ow always get sport_detail=None -- the Sport enum
    # already distinguishes pool/open-water.
    draft = parse_fit(FIT_FIXTURE)
    assert draft.sport_detail is None


# --- _sport_detail (pure function) -----------------------------------------------------


def test_sport_detail_cycling_mountain():
    assert _sport_detail("cycling", "mountain", "cross_train") == "cycling/mountain"


def test_sport_detail_training_strength_training():
    # Synthetic case (no real fixture): Garmin encodes a logged strength
    # workout as session.sport="training", sub_sport="strength_training".
    assert _sport_detail("training", "strength_training", "strength") == "training/strength_training"


def test_sport_detail_generic_sub_sport_uses_sport_alone():
    # Synthetic case: a "generic" sub_sport (no useful detail) formats as
    # the sport alone, e.g. "walking" not "walking/generic".
    assert _sport_detail("walking", "generic", "cross_train") == "walking"


def test_sport_detail_missing_sub_sport_uses_sport_alone():
    assert _sport_detail("walking", None, "cross_train") == "walking"


def test_sport_detail_none_for_swim_pool_and_swim_ow():
    assert _sport_detail("swimming", "lap_swimming", "swim_pool") is None
    assert _sport_detail("swimming", "open_water", "swim_ow") is None


def test_sport_detail_none_when_session_sport_missing():
    assert _sport_detail(None, None, "cross_train") is None


# --- _is_cycling_sport -----------------------------------------------------------------


def test_is_cycling_sport_true_for_cycling_case_insensitive():
    assert _is_cycling_sport("cycling") is True
    assert _is_cycling_sport("Cycling") is True


def test_is_cycling_sport_false_for_non_cycling_or_missing():
    assert _is_cycling_sport("kayaking") is False
    assert _is_cycling_sport("running") is False
    assert _is_cycling_sport(None) is False


# --- _merge_pauses: stationary is the lowest-precedence source -------------------------


def test_merge_pauses_stationary_dropped_when_overlapping_timer_pause():
    timer = [WorkoutPause(start_offset_s=100.0, duration_s=60.0, source="timer")]
    stationary = [WorkoutPause(start_offset_s=110.0, duration_s=40.0, source="stationary")]
    assert _merge_pauses(timer, [], [], stationary) == timer


def test_merge_pauses_stationary_dropped_when_overlapping_gap_pause():
    gap = [WorkoutPause(start_offset_s=100.0, duration_s=60.0, source="gap")]
    stationary = [WorkoutPause(start_offset_s=90.0, duration_s=20.0, source="stationary")]
    assert _merge_pauses([], gap, [], stationary) == gap


def test_merge_pauses_stationary_dropped_when_overlapping_idle_length_pause():
    idle = [WorkoutPause(start_offset_s=100.0, duration_s=60.0, source="idle_length")]
    stationary = [WorkoutPause(start_offset_s=140.0, duration_s=30.0, source="stationary")]
    assert _merge_pauses([], [], idle, stationary) == idle


def test_merge_pauses_keeps_non_overlapping_stationary_pause():
    timer = [WorkoutPause(start_offset_s=100.0, duration_s=60.0, source="timer")]
    stationary = [WorkoutPause(start_offset_s=5000.0, duration_s=75.0, source="stationary")]
    assert _merge_pauses(timer, [], [], stationary) == timer + stationary


def test_merge_pauses_defaults_stationary_to_empty_for_back_compat():
    # Existing 3-arg call sites (predating this feature) must keep working
    # unchanged.
    timer = [WorkoutPause(start_offset_s=0.0, duration_s=10.0, source="timer")]
    assert _merge_pauses(timer, [], []) == timer


# --- real MTB fixtures: stationary pauses + sport_detail --------------------------------


@pytest.mark.skipif(
    not FIT_MTB_RACE_FIXTURE.exists(),
    reason="no real MTB race .fit fixture -- see fixtures/fit/README.md",
)
def test_parse_fit_mtb_race_sport_detail_is_cycling_mountain():
    draft = parse_fit(FIT_MTB_RACE_FIXTURE)
    assert draft.sport == "cross_train"
    assert draft.sport_detail == "cycling/mountain"


@pytest.mark.skipif(not FIT_MTB_RACE_FIXTURE.exists(), reason="no real MTB race .fit fixture")
def test_parse_fit_mtb_race_has_no_timer_or_gap_pauses():
    # This device records with auto-pause off: exactly one timer start/
    # stop_all pair spanning the whole file, and record frames continue
    # through every physical stop -- so the timer/gap detectors alone find
    # zero pauses here, confirming the stationary detector below is doing
    # real work, not duplicating what those already caught.
    draft = parse_fit(FIT_MTB_RACE_FIXTURE)
    assert not any(p.source in ("timer", "gap") for p in draft.pauses)


@pytest.mark.skipif(not FIT_MTB_RACE_FIXTURE.exists(), reason="no real MTB race .fit fixture")
def test_parse_fit_mtb_race_detects_stationary_bottle_stops():
    # Calibrated against this real 2026-06-13 MTB race (10 laps): the start
    # corral plus five per-lap bottle stops all show up as sustained
    # sub-0.5 m/s spans. ">= 5 after the start corral" is the loose, robust
    # assertion; the specific bottle-stop offset/duration below is the
    # tight one, re-derived by actually running the parser against this
    # file rather than trusted from the wall-clock labels in the task
    # brief (which the brief itself flagged as approximate).
    draft = parse_fit(FIT_MTB_RACE_FIXTURE)
    stationary = [p for p in draft.pauses if p.source == "stationary"]
    assert len(stationary) >= 5
    assert all(p.duration_s >= 30.0 for p in stationary)

    candidates = [p for p in stationary if abs(p.start_offset_s - 5172.0) <= 30.0]
    assert len(candidates) == 1, stationary
    assert candidates[0].duration_s == pytest.approx(75.0, abs=15.0)


@pytest.mark.skipif(
    not FIT_MTB_0709_FIXTURE.exists(),
    reason="no real MTB 0709 .fit fixture -- see fixtures/fit/README.md",
)
def test_parse_fit_mtb_0709_sport_detail_is_cycling_mountain():
    draft = parse_fit(FIT_MTB_0709_FIXTURE)
    assert draft.sport == "cross_train"
    assert draft.sport_detail == "cycling/mountain"


@pytest.mark.skipif(not FIT_MTB_0709_FIXTURE.exists(), reason="no real MTB 0709 .fit fixture")
def test_parse_fit_mtb_0709_detects_stationary_feed_stop():
    # Calibrated against this real 2026-07-09 ride's one clean feed stop.
    draft = parse_fit(FIT_MTB_0709_FIXTURE)
    stationary = [p for p in draft.pauses if p.source == "stationary"]
    candidates = [p for p in stationary if abs(p.start_offset_s - 1328.0) <= 30.0]
    assert len(candidates) == 1, stationary
    assert candidates[0].duration_s == pytest.approx(69.0, abs=15.0)
