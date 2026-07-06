"""Tests for scripts/export_plan_json.py.

Loaded by explicit file path (scripts/ isn't a package on sys.path) so
these tests work regardless of the cwd pytest is invoked from -- same
pattern as tests/unit/test_validate_all.py.
"""

from __future__ import annotations

import importlib.util
import json
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest

from swim_coach.models import Athlete, Event, MacroBlock, MacroPlan, Session, WeekPlan
from swim_coach.store import FileStore

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "export_plan_json.py"
_spec = importlib.util.spec_from_file_location("export_plan_json", _SCRIPT_PATH)
export_plan_json = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(export_plan_json)


@pytest.fixture
def full_athlete_tree(tmp_path):
    """A full athlete tree (profile + events + macro + two weeks) under
    tmp_path, so the exporter has every kind of data to round-trip."""
    store = FileStore(base_dir=tmp_path)
    athlete_id = uuid.uuid4()
    athlete = Athlete(
        id=athlete_id,
        slug="testee",
        name="Test Athlete",
        css_pace_s_per_100m=90.0,
        zones={"Z2": {"name": "Z2", "lo_offset": 5.0, "hi_offset": 9.0, "pace_lo_s": 95.0, "pace_hi_s": 99.0}},
        constraints={"note": "fixture athlete"},
        pool_schedule=["mon", "wed", "fri"],
    )
    store.save_athlete(athlete)

    event = Event(
        id=uuid.uuid4(),
        athlete_id=athlete_id,
        name="Fixture Ultra Swim",
        event_date=date.today() + timedelta(weeks=10),
        distance_m=20000,
        water_temp_c=20.0,
        wetsuit=False,
        priority="A",
    )
    store.save_events("testee", [event])

    macro = MacroPlan(
        id=uuid.uuid4(),
        athlete_id=athlete_id,
        event_id=event.id,
        blocks=[
            MacroBlock(
                name="base", start_date=date.today(), end_date=date.today() + timedelta(days=27),
                weekly_volume_target_m=10000, focus="aerobic base",
            ),
            MacroBlock(
                name="taper", start_date=date.today() + timedelta(days=28),
                end_date=date.today() + timedelta(days=41),
                weekly_volume_target_m=5000, focus="taper",
            ),
        ],
    )
    store.save_macro("testee", macro)

    week1 = WeekPlan(
        id=uuid.uuid4(),
        athlete_id=athlete_id,
        iso_week="2026-W10",
        meso_block="base",
        focus="base week one",
        target_volume_m=10000,
        sessions=[
            Session(
                id=uuid.uuid4(), athlete_id=athlete_id, date=date.today(), sport="swim_pool",
                source="pool_coach", duration_min=60.0, distance_m=3000,
                intensity={"anchor": "rpe"}, purpose="coached pool",
            )
        ],
    )
    week2 = WeekPlan(
        id=uuid.uuid4(),
        athlete_id=athlete_id,
        iso_week="2026-W11",
        meso_block="base",
        focus="base week two",
        target_volume_m=11000,
        sessions=[],
    )
    store.save_week("testee", week1)
    store.save_week("testee", week2)

    return {"base_dir": tmp_path, "slug": "testee", "store": store}


def test_discover_slugs_finds_athletes_with_profiles(tmp_path):
    (tmp_path / "has-profile").mkdir()
    (tmp_path / "has-profile" / "profile.yaml").write_text("id: x\n", encoding="utf-8")
    (tmp_path / "no-profile").mkdir()
    assert export_plan_json.discover_slugs(tmp_path) == ["has-profile"]


def test_discover_slugs_missing_dir_returns_empty(tmp_path):
    assert export_plan_json.discover_slugs(tmp_path / "nope") == []


def test_export_athlete_has_expected_keys_and_counts(full_athlete_tree):
    store = full_athlete_tree["store"]
    data = export_plan_json.export_athlete(store, "testee")

    assert data["slug"] == "testee"
    assert data["name"] == "Test Athlete"
    assert set(data) == {"slug", "name", "generated_at", "athlete", "events", "macro", "weeks"}

    assert data["athlete"]["name"] == "Test Athlete"
    assert isinstance(data["athlete"]["id"], str)  # UUID serialized as string

    assert len(data["events"]) == 1
    assert data["events"][0]["distance_m"] == 20000
    assert isinstance(data["events"][0]["event_date"], str)  # date serialized as string

    assert data["macro"] is not None
    assert len(data["macro"]["blocks"]) == 2

    assert len(data["weeks"]) == 2
    assert [w["iso_week"] for w in data["weeks"]] == ["2026-W10", "2026-W11"]
    assert len(data["weeks"][0]["sessions"]) == 1


def test_export_athlete_with_no_macro_or_weeks(tmp_path):
    store = FileStore(base_dir=tmp_path)
    athlete = Athlete(id=uuid.uuid4(), slug="bare", name="Bare Athlete")
    store.save_athlete(athlete)

    data = export_plan_json.export_athlete(store, "bare")
    assert data["macro"] is None
    assert data["weeks"] == []
    assert data["events"] == []


def test_export_all_writes_index_and_athlete_json(full_athlete_tree, tmp_path):
    out_dir = tmp_path / "out"
    result = export_plan_json.export_all(full_athlete_tree["base_dir"], out_dir)
    assert result["exported"] == ["testee"]

    index = json.loads((out_dir / "index.json").read_text(encoding="utf-8"))
    assert index == [{"slug": "testee", "name": "Test Athlete"}]

    athlete_json = json.loads((out_dir / "testee.json").read_text(encoding="utf-8"))
    assert athlete_json["slug"] == "testee"
    assert len(athlete_json["weeks"]) == 2


def test_export_all_defaults_to_every_athlete_found(full_athlete_tree):
    base_dir = full_athlete_tree["base_dir"]
    second = Athlete(id=uuid.uuid4(), slug="second", name="Second Athlete")
    FileStore(base_dir=base_dir).save_athlete(second)

    out_dir = base_dir / "out"
    result = export_plan_json.export_all(base_dir, out_dir)
    assert sorted(result["exported"]) == ["second", "testee"]
    assert (out_dir / "second.json").exists()
    assert (out_dir / "testee.json").exists()


def test_main_missing_athlete_exits_1(full_athlete_tree, tmp_path, capsys):
    code = export_plan_json.main(
        [
            "--base-dir", str(full_athlete_tree["base_dir"]),
            "--out", str(tmp_path / "out"),
            "--athlete", "does-not-exist",
        ]
    )
    assert code == 1
    result = json.loads(capsys.readouterr().out.strip())
    assert result["slugs"] == ["does-not-exist"]


def test_main_exports_named_athlete_exits_0(full_athlete_tree, tmp_path, capsys):
    out_dir = tmp_path / "out"
    code = export_plan_json.main(
        [
            "--base-dir", str(full_athlete_tree["base_dir"]),
            "--out", str(out_dir),
            "--athlete", "testee",
        ]
    )
    assert code == 0
    assert (out_dir / "testee.json").exists()
    assert (out_dir / "index.json").exists()
