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
