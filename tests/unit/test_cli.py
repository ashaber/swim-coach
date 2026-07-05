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
from swim_coach.models import Workout


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
