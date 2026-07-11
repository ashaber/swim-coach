"""Tests for swim_coach.cli.

Drives `main([...])` directly against a tmp_path base dir. No LLM calls, no
network, no subprocess -- just argparse + FileStore + models.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, timedelta

import yaml

from swim_coach.cli import main, parse_time_to_s
from swim_coach.models import Wellness, Workout
from pathlib import Path
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _run(base_dir, *args):
    return main(["--base-dir", str(base_dir), *args])


def _out(capsys):
    return json.loads(capsys.readouterr().out.strip())


# --- parse_time_to_s -----------------------------------------------------------


def test_parse_time_to_s_mm_ss():
    assert parse_time_to_s("5:40") == 340.0


def test_parse_time_to_s_plain_seconds():
    assert parse_time_to_s("340") == 340.0


def test_parse_time_to_s_mm_ss_fractional():
    assert parse_time_to_s("1:05.5") == 65.5


# --- validate --------------------------------------------------------------------


def test_validate_success_reports_counts(athlete_tree, capsys):
    code = _run(athlete_tree["base_dir"], "validate", "--athlete", athlete_tree["slug"])
    assert code == 0
    result = _out(capsys)
    assert result["athlete"] == athlete_tree["slug"]
    assert result["counts"]["events"] == 1
    assert result["counts"]["macro"] == 0
    assert result["counts"]["weeks"] == 0
    assert result["counts"]["workouts"] == 0
    assert result["counts"]["wellness"] == 0


def test_validate_missing_athlete_returns_1(tmp_path, capsys):
    code = _run(tmp_path, "validate", "--athlete", "nobody")
    assert code == 1
    result = _out(capsys)
    assert "error" in result
    assert "file" in result


def test_validate_reports_bad_workout_file_with_path(athlete_tree, capsys):
    workouts_dir = athlete_tree["base_dir"] / athlete_tree["slug"] / "logs" / "workouts"
    workouts_dir.mkdir(parents=True, exist_ok=True)
    bad_path = workouts_dir / "2026-01-01-swim_pool-badbad12.yaml"
    bad_path.write_text(yaml.safe_dump({"not": "a valid workout"}), encoding="utf-8")

    code = _run(athlete_tree["base_dir"], "validate", "--athlete", athlete_tree["slug"])
    assert code == 1
    result = _out(capsys)
    assert "error" in result
    assert str(bad_path) == result["file"]


def test_validate_counts_workouts_and_wellness(athlete_tree, capsys):
    store = athlete_tree["store"]
    slug = athlete_tree["slug"]
    workout = Workout(
        id=uuid.uuid4(),
        athlete_id=athlete_tree["athlete"].id,
        date=date(2026, 1, 6),
        sport="swim_pool",
        source="manual",
        distance_m=3000,
        duration_min=60.0,
    )
    store.save_workout(slug, workout)

    code = _run(athlete_tree["base_dir"], "validate", "--athlete", slug)
    assert code == 0
    result = _out(capsys)
    assert result["counts"]["workouts"] == 1


# --- zones -----------------------------------------------------------------------


def test_zones_without_test_times_uses_profile_css(athlete_tree, capsys):
    code = _run(athlete_tree["base_dir"], "zones", "--athlete", athlete_tree["slug"])
    assert code == 0
    result = _out(capsys)
    assert result["css_pace_s_per_100m"] == 95.0
    assert set(result["zones"].keys()) == {"Z1", "Z2", "Z3", "Z4", "Z5"}


def test_zones_with_test_times_computes_css(athlete_tree, capsys):
    code = _run(
        athlete_tree["base_dir"],
        "zones",
        "--athlete",
        athlete_tree["slug"],
        "--test-400",
        "6:40",
        "--test-200",
        "2:55",
    )
    assert code == 0
    result = _out(capsys)
    assert result["css_pace_s_per_100m"] == 112.5


def test_zones_requires_both_test_times_together(athlete_tree, capsys):
    code = _run(
        athlete_tree["base_dir"], "zones", "--athlete", athlete_tree["slug"], "--test-400", "6:40"
    )
    assert code == 1
    result = _out(capsys)
    assert "error" in result


def test_zones_write_persists_to_profile(athlete_tree, capsys):
    code = _run(
        athlete_tree["base_dir"],
        "zones",
        "--athlete",
        athlete_tree["slug"],
        "--test-400",
        "6:40",
        "--test-200",
        "2:55",
        "--write",
    )
    assert code == 0
    reloaded = athlete_tree["store"].load_athlete(athlete_tree["slug"])
    assert reloaded.css_pace_s_per_100m == 112.5
    assert reloaded.zones is not None
    assert set(reloaded.zones.keys()) == {"Z1", "Z2", "Z3", "Z4", "Z5"}


# --- scaffold-macro ----------------------------------------------------------------


def test_scaffold_macro_creates_macro_file_matching_by_name(athlete_tree, capsys):
    code = _run(
        athlete_tree["base_dir"],
        "scaffold-macro",
        "--athlete",
        athlete_tree["slug"],
        "--event",
        "catalina channel",
        "--current-volume",
        "6000",
    )
    assert code == 0
    result = _out(capsys)
    assert len(result["blocks"]) == 4
    macro_path = athlete_tree["base_dir"] / athlete_tree["slug"] / "plan" / "macro.yaml"
    assert macro_path.exists()


def test_scaffold_macro_matches_event_by_id_prefix(athlete_tree, capsys):
    id_prefix = str(athlete_tree["event"].id)[:8]
    code = _run(
        athlete_tree["base_dir"],
        "scaffold-macro",
        "--athlete",
        athlete_tree["slug"],
        "--event",
        id_prefix,
        "--current-volume",
        "6000",
    )
    assert code == 0


def test_scaffold_macro_missing_current_volume_errors(athlete_tree, capsys):
    code = _run(
        athlete_tree["base_dir"],
        "scaffold-macro",
        "--athlete",
        athlete_tree["slug"],
        "--event",
        "catalina channel",
    )
    assert code == 1
    result = _out(capsys)
    assert "error" in result


def test_scaffold_macro_unknown_event_errors(athlete_tree, capsys):
    code = _run(
        athlete_tree["base_dir"],
        "scaffold-macro",
        "--athlete",
        athlete_tree["slug"],
        "--event",
        "does not exist",
        "--current-volume",
        "6000",
    )
    assert code == 1
    result = _out(capsys)
    assert "error" in result


def test_scaffold_macro_too_short_runway_errors(athlete_tree, capsys):
    store = athlete_tree["store"]
    slug = athlete_tree["slug"]
    events = store.load_events(slug)
    events[0].event_date = date.today() + timedelta(weeks=5)
    store.save_events(slug, events)

    code = _run(
        athlete_tree["base_dir"],
        "scaffold-macro",
        "--athlete",
        slug,
        "--event",
        "catalina channel",
        "--current-volume",
        "6000",
    )
    assert code == 1
    result = _out(capsys)
    assert "error" in result


# --- plan-week ---------------------------------------------------------------------


def _scaffold(athlete_tree, capsys):
    _run(
        athlete_tree["base_dir"],
        "scaffold-macro",
        "--athlete",
        athlete_tree["slug"],
        "--event",
        "catalina channel",
        "--current-volume",
        "6000",
    )
    capsys.readouterr()  # drain
    macro = athlete_tree["store"].load_macro(athlete_tree["slug"])
    return macro


def _iso_week(d: date) -> str:
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def test_plan_week_without_macro_errors(athlete_tree, capsys):
    code = _run(
        athlete_tree["base_dir"],
        "plan-week",
        "--athlete",
        athlete_tree["slug"],
        "--week",
        "2026-W01",
    )
    assert code == 1
    result = _out(capsys)
    assert "error" in result


def test_plan_week_generates_and_saves(athlete_tree, capsys):
    macro = _scaffold(athlete_tree, capsys)
    week_start = macro.blocks[0].start_date
    iso_week = _iso_week(week_start)

    code = _run(
        athlete_tree["base_dir"], "plan-week", "--athlete", athlete_tree["slug"], "--week", iso_week
    )
    assert code == 0
    result = _out(capsys)
    assert result["iso_week"] == iso_week
    assert len(result["sessions"]) > 0

    week_path = (
        athlete_tree["base_dir"] / athlete_tree["slug"] / "plan" / "weeks" / f"{iso_week}.yaml"
    )
    assert week_path.exists()


def test_plan_week_invalid_iso_week_format_errors(athlete_tree, capsys):
    _scaffold(athlete_tree, capsys)
    code = _run(
        athlete_tree["base_dir"], "plan-week", "--athlete", athlete_tree["slug"], "--week", "nope"
    )
    assert code == 1
    result = _out(capsys)
    assert "error" in result


def test_plan_week_refuses_overwrite_without_force(athlete_tree, capsys):
    macro = _scaffold(athlete_tree, capsys)
    week_start = macro.blocks[0].start_date
    iso_week = _iso_week(week_start)

    _run(athlete_tree["base_dir"], "plan-week", "--athlete", athlete_tree["slug"], "--week", iso_week)
    capsys.readouterr()

    code = _run(
        athlete_tree["base_dir"], "plan-week", "--athlete", athlete_tree["slug"], "--week", iso_week
    )
    assert code == 1
    result = _out(capsys)
    assert "error" in result

    code = _run(
        athlete_tree["base_dir"],
        "plan-week",
        "--athlete",
        athlete_tree["slug"],
        "--week",
        iso_week,
        "--force",
    )
    assert code == 0


# --- summarize ---------------------------------------------------------------------


def test_summarize_reports_compact_rollup(athlete_tree, capsys):
    slug = athlete_tree["slug"]
    store = athlete_tree["store"]
    athlete = athlete_tree["athlete"]
    as_of = date(2026, 2, 2)  # a Monday

    store.save_workout(
        slug,
        Workout(
            id=uuid.uuid4(),
            athlete_id=athlete.id,
            date=as_of - timedelta(days=1),
            sport="swim_pool",
            source="manual",
            distance_m=3000,
            duration_min=60.0,
            rpe=5,
        ),
    )
    store.save_wellness(
        slug,
        Wellness(
            id=uuid.uuid4(),
            athlete_id=athlete.id,
            date=as_of - timedelta(days=1),
            sleep_quality=4,
            sleep_hours=7.5,
            stress=2,
            soreness=2,
            motivation=4,
        ),
    )

    code = _run(
        athlete_tree["base_dir"],
        "summarize",
        "--athlete",
        slug,
        "--weeks",
        "4",
        "--as-of",
        as_of.isoformat(),
    )
    assert code == 0
    result = _out(capsys)
    assert result["athlete"] == slug
    assert result["as_of"] == as_of.isoformat()
    assert result["weeks"] == 4
    assert len(result["volume_m"]) == 4
    assert result["srpe_load_by_day"]
    assert "load_ratio_7d_28d" in result
    assert "monotony" in result
    assert len(result["wellness_trend"]) == 1
    assert result["wellness_trend"][0][0] == (as_of - timedelta(days=1)).isoformat()


def test_summarize_missing_athlete_returns_1(tmp_path, capsys):
    code = _run(tmp_path, "summarize", "--athlete", "nobody")
    assert code == 1
    result = _out(capsys)
    assert "error" in result


def test_summarize_defaults_weeks_to_four(athlete_tree, capsys):
    code = _run(
        athlete_tree["base_dir"],
        "summarize",
        "--athlete",
        athlete_tree["slug"],
        "--as-of",
        "2026-02-02",
    )
    assert code == 0
    result = _out(capsys)
    assert result["weeks"] == 4


# --- adapt ---------------------------------------------------------------------------


def test_adapt_generates_draft_week_and_saves(athlete_tree, capsys):
    macro = _scaffold(athlete_tree, capsys)
    slug = athlete_tree["slug"]
    week1_start = macro.blocks[0].start_date
    week1_iso = _iso_week(week1_start)

    code = _run(athlete_tree["base_dir"], "plan-week", "--athlete", slug, "--week", week1_iso)
    assert code == 0
    capsys.readouterr()

    week2_start = week1_start + timedelta(weeks=1)
    week2_iso = _iso_week(week2_start)

    code = _run(athlete_tree["base_dir"], "adapt", "--athlete", slug, "--week", week2_iso)
    assert code == 0
    result = _out(capsys)
    assert result["athlete"] == slug
    assert result["iso_week"] == week2_iso
    assert result["draft"] is True
    assert result["rationale"]["action"] in ("cut", "repeat", "hold", "advance")

    saved = athlete_tree["store"].load_week(slug, week2_iso)
    assert saved.draft is True
    assert saved.adaptation_rationale is not None


def test_adapt_without_macro_errors(athlete_tree, capsys):
    code = _run(
        athlete_tree["base_dir"], "adapt", "--athlete", athlete_tree["slug"], "--week", "2026-W02"
    )
    assert code == 1
    result = _out(capsys)
    assert "error" in result


def test_adapt_without_current_week_errors(athlete_tree, capsys):
    macro = _scaffold(athlete_tree, capsys)
    week1_start = macro.blocks[0].start_date
    week2_start = week1_start + timedelta(weeks=1)
    week2_iso = _iso_week(week2_start)

    # No plan-week was ever run for week1 -- adapt has nothing to adapt from.
    code = _run(athlete_tree["base_dir"], "adapt", "--athlete", athlete_tree["slug"], "--week", week2_iso)
    assert code == 1
    result = _out(capsys)
    assert "error" in result


def test_adapt_refuses_overwrite_without_force(athlete_tree, capsys):
    macro = _scaffold(athlete_tree, capsys)
    slug = athlete_tree["slug"]
    week1_start = macro.blocks[0].start_date
    week1_iso = _iso_week(week1_start)
    _run(athlete_tree["base_dir"], "plan-week", "--athlete", slug, "--week", week1_iso)
    capsys.readouterr()

    week2_start = week1_start + timedelta(weeks=1)
    week2_iso = _iso_week(week2_start)

    # First adapt run creates a draft week2.
    code = _run(athlete_tree["base_dir"], "adapt", "--athlete", slug, "--week", week2_iso)
    assert code == 0
    capsys.readouterr()

    # Finalize it (non-draft) by running plan-week --force over it.
    _run(athlete_tree["base_dir"], "plan-week", "--athlete", slug, "--week", week2_iso, "--force")
    capsys.readouterr()

    code = _run(athlete_tree["base_dir"], "adapt", "--athlete", slug, "--week", week2_iso)
    assert code == 1
    result = _out(capsys)
    assert "error" in result

    code = _run(
        athlete_tree["base_dir"], "adapt", "--athlete", slug, "--week", week2_iso, "--force"
    )
    assert code == 0


def test_plan_week_uses_event_format_from_events_yaml(athlete_tree, capsys):
    # The fixture event defaults to event_format="single_day"; flip it to
    # multi_day_stage and confirm plan-week picks that up from events.yaml
    # (via the macro's event_id) rather than hard-defaulting to single_day.
    store = athlete_tree["store"]
    slug = athlete_tree["slug"]
    events = store.load_events(slug)
    events[0].event_format = "multi_day_stage"
    store.save_events(slug, events)

    macro = _scaffold(athlete_tree, capsys)
    week_start = macro.blocks[0].start_date
    iso_week = _iso_week(week_start)

    code = _run(
        athlete_tree["base_dir"], "plan-week", "--athlete", slug, "--week", iso_week
    )
    assert code == 0
    capsys.readouterr()
    week = store.load_week(slug, iso_week)
    long_swims = [s for s in week.sessions if s.sport == "swim_ow"]
    assert {s.date.weekday() for s in long_swims} == {5, 6}


# --- parse-coach-text ----------------------------------------------------------------


def test_parse_coach_text_saves_verbatim_and_prints_parse(athlete_tree, capsys, tmp_path):
    coach_text_file = tmp_path / "coach_text.txt"
    coach_text_file.write_text("8x100 @ 1:40\n300 warm up\n", encoding="utf-8")

    code = _run(
        athlete_tree["base_dir"],
        "parse-coach-text",
        "--athlete",
        athlete_tree["slug"],
        "--file",
        str(coach_text_file),
        "--date",
        "2026-02-01",
    )
    assert code == 0
    result = _out(capsys)
    assert result["athlete"] == athlete_tree["slug"]
    assert result["total_distance_m"] == 1100
    assert result["unparsed_lines"] == []
    assert len(result["sets"]) == 2

    saved_path = (
        athlete_tree["base_dir"] / athlete_tree["slug"] / "logs" / "coach-texts" / "2026-02-01.md"
    )
    assert saved_path.exists()
    assert saved_path.read_text(encoding="utf-8") == "8x100 @ 1:40\n300 warm up\n"


def test_parse_coach_text_refuses_silent_overwrite(athlete_tree, capsys, tmp_path):
    coach_text_file = tmp_path / "coach_text.txt"
    coach_text_file.write_text("8x100 @ 1:40\n", encoding="utf-8")

    _run(
        athlete_tree["base_dir"],
        "parse-coach-text",
        "--athlete",
        athlete_tree["slug"],
        "--file",
        str(coach_text_file),
        "--date",
        "2026-02-01",
    )
    capsys.readouterr()

    code = _run(
        athlete_tree["base_dir"],
        "parse-coach-text",
        "--athlete",
        athlete_tree["slug"],
        "--file",
        str(coach_text_file),
        "--date",
        "2026-02-01",
    )
    assert code == 1
    result = _out(capsys)
    assert "error" in result

    code = _run(
        athlete_tree["base_dir"],
        "parse-coach-text",
        "--athlete",
        athlete_tree["slug"],
        "--file",
        str(coach_text_file),
        "--date",
        "2026-02-01",
        "--force",
    )
    assert code == 0


def test_parse_coach_text_missing_file_errors(athlete_tree, capsys):
    code = _run(
        athlete_tree["base_dir"],
        "parse-coach-text",
        "--athlete",
        athlete_tree["slug"],
        "--file",
        "/no/such/file.txt",
    )
    assert code == 1
    result = _out(capsys)
    assert "error" in result


def test_parse_coach_text_defaults_date_to_today(athlete_tree, capsys, tmp_path):
    coach_text_file = tmp_path / "coach_text.txt"
    coach_text_file.write_text("1 x 100 Freestyle\n", encoding="utf-8")

    code = _run(
        athlete_tree["base_dir"],
        "parse-coach-text",
        "--athlete",
        athlete_tree["slug"],
        "--file",
        str(coach_text_file),
    )
    assert code == 0
    saved_path = (
        athlete_tree["base_dir"]
        / athlete_tree["slug"]
        / "logs"
        / "coach-texts"
        / f"{date.today().isoformat()}.md"
    )
    assert saved_path.exists()


# --- ingest ------------------------------------------------------------------------------


def test_ingest_tcx_prints_draft_without_saving(athlete_tree, capsys):
    tcx_path = FIXTURES_DIR / "tcx" / "sample_pool_swim.tcx"
    code = _run(
        athlete_tree["base_dir"], "ingest", "--athlete", athlete_tree["slug"], "--file", str(tcx_path)
    )
    assert code == 0
    result = _out(capsys)
    assert result["source"] == "tcx"
    assert result["distance_m"] == 600
    assert result["saved"] is False

    workouts_dir = athlete_tree["base_dir"] / athlete_tree["slug"] / "logs" / "workouts"
    assert not workouts_dir.exists() or list(workouts_dir.glob("*.yaml")) == []


def test_ingest_csv_with_save_persists_workout(athlete_tree, capsys):
    csv_path = FIXTURES_DIR / "csv" / "sample_garmin_export.csv"
    code = _run(
        athlete_tree["base_dir"],
        "ingest",
        "--athlete",
        athlete_tree["slug"],
        "--file",
        str(csv_path),
        "--rpe",
        "6",
        "--save",
    )
    assert code == 0
    result = _out(capsys)
    assert result["saved"] is True
    assert "workout_id" in result

    workouts = athlete_tree["store"].list_workouts(athlete_tree["slug"])
    assert len(workouts) == 1
    assert workouts[0].source == "csv"
    assert workouts[0].distance_m == 2500
    assert workouts[0].rpe == 6
    assert workouts[0].athlete_id == athlete_tree["athlete"].id


def test_ingest_overrides_date_and_sport(athlete_tree, capsys):
    csv_path = FIXTURES_DIR / "csv" / "sample_garmin_export.csv"
    code = _run(
        athlete_tree["base_dir"],
        "ingest",
        "--athlete",
        athlete_tree["slug"],
        "--file",
        str(csv_path),
        "--date",
        "2026-05-05",
        "--sport",
        "swim_ow",
    )
    assert code == 0
    result = _out(capsys)
    assert result["date"] == "2026-05-05"
    assert result["sport"] == "swim_ow"


def test_ingest_unsupported_extension_errors(athlete_tree, capsys, tmp_path):
    bogus = tmp_path / "workout.json"
    bogus.write_text("{}", encoding="utf-8")
    code = _run(
        athlete_tree["base_dir"], "ingest", "--athlete", athlete_tree["slug"], "--file", str(bogus)
    )
    assert code == 1
    result = _out(capsys)
    assert "error" in result


def test_ingest_missing_file_errors(athlete_tree, capsys):
    code = _run(
        athlete_tree["base_dir"],
        "ingest",
        "--athlete",
        athlete_tree["slug"],
        "--file",
        "/no/such/file.tcx",
    )
    assert code == 1
    result = _out(capsys)
    assert "error" in result


def test_ingest_invalid_rpe_errors_on_save(athlete_tree, capsys):
    csv_path = FIXTURES_DIR / "csv" / "sample_garmin_export.csv"
    code = _run(
        athlete_tree["base_dir"],
        "ingest",
        "--athlete",
        athlete_tree["slug"],
        "--file",
        str(csv_path),
        "--rpe",
        "99",
        "--save",
    )
    assert code == 1
    result = _out(capsys)
    assert "error" in result

    # No orphaned raw-file copy or files/ dir left behind on a failed save.
    files_dir = athlete_tree["base_dir"] / athlete_tree["slug"] / "logs" / "files"
    assert not files_dir.exists() or list(files_dir.glob("*")) == []


# --- ingest .fit + analyze (.fit workout-analytics Slice 1) --------------------------

FIT_KAYAK = FIXTURES_DIR / "fit" / "real_kayak.fit"
FIT_POOL = FIXTURES_DIR / "fit" / "real_swim.fit"


def test_ingest_fit_with_save_copies_raw_file_and_computes_analytics(athlete_tree, capsys):
    code = _run(
        athlete_tree["base_dir"],
        "ingest",
        "--athlete",
        athlete_tree["slug"],
        "--file",
        str(FIT_KAYAK),
        "--save",
    )
    assert code == 0
    result = _out(capsys)
    assert result["saved"] is True
    assert "series" not in result  # never dumped to stdout

    raw_ref = Path(result["raw_ref"])
    assert raw_ref.exists()
    assert raw_ref == (
        athlete_tree["base_dir"] / athlete_tree["slug"] / "logs" / "files" / FIT_KAYAK.name
    )

    series_ref = Path(result["series_ref"])
    assert series_ref.exists()
    import json as _json

    series = _json.loads(series_ref.read_text(encoding="utf-8"))
    assert "hr" in series
    assert len(series["t_s"]) > 4000

    assert result["analytics"]["pause_count"] == 0
    assert "summary" in result

    workouts = athlete_tree["store"].list_workouts(athlete_tree["slug"])
    assert len(workouts) == 1
    saved = workouts[0]
    assert saved.sport == "cross_train"
    assert saved.avg_hr is not None
    assert saved.series_ref == result["series_ref"]
    assert saved.analytics is not None


def test_ingest_fit_pool_swim_has_lengths_and_no_sidecar(athlete_tree, capsys):
    code = _run(
        athlete_tree["base_dir"],
        "ingest",
        "--athlete",
        athlete_tree["slug"],
        "--file",
        str(FIT_POOL),
        "--save",
    )
    assert code == 0
    result = _out(capsys)
    assert result["saved"] is True
    assert result["series_ref"] is None

    workouts = athlete_tree["store"].list_workouts(athlete_tree["slug"])
    assert len(workouts) == 1
    saved = workouts[0]
    assert len(saved.lengths) == 71
    assert saved.avg_hr is None
    assert saved.series_ref is None


def test_ingest_fit_without_save_does_not_copy_raw_file(athlete_tree, capsys):
    code = _run(
        athlete_tree["base_dir"],
        "ingest",
        "--athlete",
        athlete_tree["slug"],
        "--file",
        str(FIT_KAYAK),
    )
    assert code == 0
    result = _out(capsys)
    assert result["saved"] is False
    assert "series" not in result

    files_dir = athlete_tree["base_dir"] / athlete_tree["slug"] / "logs" / "files"
    assert not files_dir.exists()


def _ingest_fit(athlete_tree, capsys, fit_path):
    code = _run(
        athlete_tree["base_dir"],
        "ingest",
        "--athlete",
        athlete_tree["slug"],
        "--file",
        str(fit_path),
        "--save",
    )
    assert code == 0
    result = _out(capsys)
    return result["workout_id"]


def test_analyze_all_recomputes_and_updates_existing_workout(athlete_tree, capsys):
    workout_id = _ingest_fit(athlete_tree, capsys, FIT_KAYAK)
    capsys.readouterr()

    # Blow away the analytics-derived fields to prove --all actually
    # recomputes rather than trivially matching what's already there.
    store = athlete_tree["store"]
    slug = athlete_tree["slug"]
    workout = next(w for w in store.list_workouts(slug) if str(w.id) == workout_id)
    workout.analytics = None
    workout.laps = []
    store.save_workout(slug, workout)

    code = _run(athlete_tree["base_dir"], "analyze", "--athlete", slug, "--all")
    assert code == 0
    result = _out(capsys)
    assert result["analyzed"] == 1
    assert result["skipped"] == 0

    reloaded = next(w for w in store.list_workouts(slug) if str(w.id) == workout_id)
    assert reloaded.analytics is not None
    assert len(reloaded.laps) == 1
    # Untouched fields preserved.
    assert reloaded.id == workout.id
    assert reloaded.date == workout.date
    assert reloaded.sport == workout.sport


def test_analyze_workout_id_prefix_matches(athlete_tree, capsys):
    workout_id = _ingest_fit(athlete_tree, capsys, FIT_POOL)
    capsys.readouterr()

    code = _run(
        athlete_tree["base_dir"],
        "analyze",
        "--athlete",
        athlete_tree["slug"],
        "--workout-id",
        workout_id[:8],
    )
    assert code == 0
    result = _out(capsys)
    assert result["analyzed"] == 1
    assert result["results"][0]["n_lengths"] == 71


def test_analyze_missing_raw_file_warns_and_skips(athlete_tree, capsys):
    workout_id = _ingest_fit(athlete_tree, capsys, FIT_KAYAK)
    capsys.readouterr()

    store = athlete_tree["store"]
    slug = athlete_tree["slug"]
    # Simulate the raw file having been deleted/moved out from under us.
    raw_path = Path(next(w for w in store.list_workouts(slug) if str(w.id) == workout_id).raw_ref)
    raw_path.unlink()

    code = _run(athlete_tree["base_dir"], "analyze", "--athlete", slug, "--all")
    assert code == 0
    result = _out(capsys)
    assert result["analyzed"] == 0
    assert result["skipped"] == 1
    assert "skipped" in result["results"][0]

    # Workout file must still exist -- analyze never deletes.
    assert len(store.list_workouts(slug)) == 1


def test_analyze_unknown_workout_id_errors(athlete_tree, capsys):
    code = _run(
        athlete_tree["base_dir"],
        "analyze",
        "--athlete",
        athlete_tree["slug"],
        "--workout-id",
        "deadbeef",
    )
    assert code == 1
    result = _out(capsys)
    assert "error" in result


def test_analyze_requires_workout_id_or_all(athlete_tree):
    import pytest as _pytest

    with _pytest.raises(SystemExit):
        _run(athlete_tree["base_dir"], "analyze", "--athlete", athlete_tree["slug"])
