"""Tests for swim_coach.parse_files (.tcx / .csv / .fit ingest).

No LLM, no network. .fit tests that need real content are guarded with
pytest.mark.skipif on a real fixture that doesn't exist yet -- see
tests/unit/fixtures/fit/README.md.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from swim_coach.parse_files import WorkoutDraft, _fit_sport, parse_csv, parse_fit, parse_tcx

FIXTURES_DIR = Path(__file__).parent / "fixtures"
TCX_FIXTURE = FIXTURES_DIR / "tcx" / "sample_pool_swim.tcx"
TCX_NO_LAPS_FIXTURE = FIXTURES_DIR / "tcx" / "no_laps.tcx"
CSV_FIXTURE = FIXTURES_DIR / "csv" / "sample_garmin_export.csv"
FIT_FIXTURE = FIXTURES_DIR / "fit" / "real_swim.fit"


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
