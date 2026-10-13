"""scripts/seed_race_checklist.py: dry-run by default, --apply writes the template; the shipped
andrew template validates."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from swim_coach.models import RaceChecklistTemplate
from swim_coach.store import FileStore

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import seed_race_checklist  # noqa: E402


def test_shipped_andrew_template_is_valid() -> None:
    t = seed_race_checklist.load_template(REPO / "athletes" / "andrew" / "race-checklist-template.json")
    assert sum(len(s.items) for s in t.sections) == 38
    assert sum(1 for e in t.timeline if e.is_start) == 1
    tags = {tag for s in t.sections for i in s.items for tag in i.tags}
    assert tags == {"mud", "cold", "wet", "cool"}


def test_dry_run_writes_nothing_and_apply_writes(tmp_path, capsys) -> None:
    shutil.copytree(REPO / "athletes" / "andrew", tmp_path / "andrew")
    args = ["--athlete", "andrew", "--athletes-dir", str(tmp_path)]
    assert seed_race_checklist.main(args) == 0
    assert json.loads(capsys.readouterr().out)["dry_run"] is True
    assert FileStore(base_dir=tmp_path).load_athlete("andrew").race_checklist_template is None
    assert seed_race_checklist.main(args + ["--apply"]) == 0
    stored = FileStore(base_dir=tmp_path).load_athlete("andrew").race_checklist_template
    assert isinstance(stored, RaceChecklistTemplate) and len(stored.sections) == 6


def test_bad_file_is_an_error(tmp_path, capsys) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text('{"timeline": [{"id": "x", "label": "x", "day": "eve"}]}')
    assert seed_race_checklist.main(["--athlete", "andrew", "--file", str(bad)]) == 1
    assert "error" in json.loads(capsys.readouterr().out)
