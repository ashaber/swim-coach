"""scripts/backfill_library_added_dates.py -- stamps `added: YYYY-MM-DD` onto
each library review-card YAML from the git date the library .md first landed.
Uses a throwaway local git repo (no network)."""

from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "backfill_library_added_dates", REPO / "scripts" / "backfill_library_added_dates.py"
)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _git(repo: Path, *args: str, date: str | None = None) -> None:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = f"{date}T12:00:00+00:00"
    subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True)


CARD = "schema_version: 1\nfile: 01-a.md\ncards:\n- section: s\n  heading: S\n"


def _make_repo(tmp_path: Path) -> Path:
    (tmp_path / "library" / "review-cards").mkdir(parents=True)
    _git(tmp_path, "init", "-q")
    (tmp_path / "library" / "01-a.md").write_text("# a\n")
    (tmp_path / "library" / "review-cards" / "01-a.yaml").write_text(CARD)
    _git(tmp_path, "add", "-A", date="2026-01-05")
    _git(tmp_path, "commit", "-qm", "add a", date="2026-01-05")
    (tmp_path / "library" / "01-a.md").write_text("# a edited\n")
    _git(tmp_path, "commit", "-qam", "edit a", date="2026-03-09")
    return tmp_path


def test_first_added_date_is_the_adding_commit_not_later_edits(tmp_path):
    repo = _make_repo(tmp_path)
    assert mod.first_added_date(repo, "library/01-a.md") == "2026-01-05"


def test_first_added_date_none_for_untracked_file(tmp_path):
    repo = _make_repo(tmp_path)
    assert mod.first_added_date(repo, "library/nope.md") is None


def test_stamp_inserts_after_file_line_and_preserves_the_rest():
    out = mod.stamp_added(CARD, "2026-01-05")
    assert out == "schema_version: 1\nfile: 01-a.md\nadded: 2026-01-05\ncards:\n- section: s\n  heading: S\n"


def test_stamp_is_idempotent_and_never_overwrites():
    once = mod.stamp_added(CARD, "2026-01-05")
    assert mod.stamp_added(once, "2030-01-01") == once


def test_backfill_writes_yaml_and_reports_table(tmp_path):
    repo = _make_repo(tmp_path)
    result = mod.backfill(repo)
    assert result == {"01-a.md": "2026-01-05"}
    text = (repo / "library" / "review-cards" / "01-a.yaml").read_text()
    assert "added: 2026-01-05" in text
