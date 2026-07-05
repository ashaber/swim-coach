"""Tests for scripts/validate_all.py.

Loaded by explicit file path (scripts/ isn't a package on sys.path) so
these tests work regardless of the cwd pytest is invoked from.
"""

from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path

import yaml

from swim_coach.models import Athlete

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "validate_all.py"
_spec = importlib.util.spec_from_file_location("validate_all", _SCRIPT_PATH)
validate_all_module = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(validate_all_module)


def _write_good_athlete(base_dir: Path, slug: str) -> None:
    athlete = Athlete(
        id=uuid.uuid4(),
        slug=slug,
        name="Good Athlete",
        css_pace_s_per_100m=95.0,
        pool_schedule=["tue", "thu", "fri"],
    )
    profile_dir = base_dir / slug
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "profile.yaml").write_text(
        yaml.safe_dump(athlete.model_dump(mode="json")), encoding="utf-8"
    )


def _write_bad_athlete(base_dir: Path, slug: str) -> None:
    profile_dir = base_dir / slug
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "profile.yaml").write_text(
        yaml.safe_dump({"this": "is not a valid athlete profile"}), encoding="utf-8"
    )


def test_validate_all_missing_dir_exits_0(tmp_path, capsys):
    code = validate_all_module.validate_all(tmp_path / "athletes")
    assert code == 0
    result = json.loads(capsys.readouterr().out.strip())
    assert "note" in result


def test_validate_all_empty_dir_exits_0(tmp_path, capsys):
    athletes_dir = tmp_path / "athletes"
    athletes_dir.mkdir()
    code = validate_all_module.validate_all(athletes_dir)
    assert code == 0
    result = json.loads(capsys.readouterr().out.strip())
    assert "note" in result


def test_validate_all_all_good_exits_0(tmp_path, capsys):
    athletes_dir = tmp_path / "athletes"
    _write_good_athlete(athletes_dir, "athlete-one")
    _write_good_athlete(athletes_dir, "athlete-two")
    code = validate_all_module.validate_all(athletes_dir)
    assert code == 0
    output = capsys.readouterr().out.strip().splitlines()
    summary = json.loads(output[-1])
    assert sorted(summary["validated"]) == ["athlete-one", "athlete-two"]


def test_validate_all_one_bad_tree_exits_1(tmp_path, capsys):
    athletes_dir = tmp_path / "athletes"
    _write_good_athlete(athletes_dir, "good-athlete")
    _write_bad_athlete(athletes_dir, "bad-athlete")
    code = validate_all_module.validate_all(athletes_dir)
    assert code == 1
    output = capsys.readouterr().out.strip().splitlines()
    summary = json.loads(output[-1])
    assert summary["athletes"] == ["bad-athlete"]


def test_main_entrypoint_accepts_positional_dir_arg(tmp_path, capsys):
    athletes_dir = tmp_path / "custom-athletes"
    _write_good_athlete(athletes_dir, "solo")
    code = validate_all_module.main([str(athletes_dir)])
    assert code == 0
