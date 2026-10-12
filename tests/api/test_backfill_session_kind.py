"""scripts/backfill_session_kind.py and its classifier, on the real purposes seen in prod."""

from __future__ import annotations

import sys
import uuid
from datetime import date
from pathlib import Path

import pytest
from swim_coach.models import Session, WeekPlan
from swim_coach.session_kind_backfill import propose_kind
from swim_coach.store import FileStore

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from backfill_session_kind import backfill, main  # noqa: E402

CASES = [
    ("RACE -- Season Opener, Day 2", "race"),
    ("RACE -- Masters Cyclocross Series, Peak Weekend, Day 1", "race"),
    ("RACE — Cross: structured warm-up with 2–3 short openers, then race.", "race"),
    ("race: club crit", "race"),
    ("RACE - Day 3", "race"),
    ("OPENERS -- short/sharp legs before the weekend", "warmup"),
    ("Openers -- wake the legs", "warmup"),
    ("PRE-RACE PRIMER — short progressive-ramp openers", "warmup"),
    ("Race-day warm-up", "warmup"),
    ("MTB endurance (Z2) -- trimmed for race week", None),
    ("race-week easy spin — aerobic, keep it light", None),
    ("race-week opener — short, race-intensity-adjacent effort", None),
    ("Build — 40/20s VO2 intervals", None),
    ("Raceday nutrition rehearsal", None),
]


@pytest.mark.parametrize("purpose, expected", CASES)
def test_classifier_on_real_purposes(purpose, expected):
    assert propose_kind(purpose) == expected


def test_classifier_falls_back_to_title():
    assert propose_kind("easy", "OPENERS -- x") == "warmup"
    assert propose_kind(None, None) is None


def _session(athlete_id, day: date, purpose: str, **kw) -> Session:
    return Session(
        id=uuid.uuid4(), athlete_id=athlete_id, date=day, sport="bike", source="ai_coach",
        duration_min=60.0, intensity={"zone": "Z2"}, purpose=purpose, **kw,
    )


@pytest.fixture
def seeded(athletes_dir: Path):
    store = FileStore(base_dir=athletes_dir)
    athlete = store.load_athlete("renee")
    sessions = [
        _session(athlete.id, date(2026, 10, 14), "Openers -- wake the legs"),
        _session(athlete.id, date(2026, 10, 17), "RACE -- Masters Cyclocross, Day 1"),
        _session(athlete.id, date(2026, 10, 15), "Z2 endurance"),
        _session(athlete.id, date(2026, 10, 18), "RACE -- Day 2 (retagged by hand)", kind="free_ride"),
    ]
    week = WeekPlan(
        id=uuid.uuid4(), athlete_id=athlete.id, iso_week="2026-W42", meso_block="build", focus="race",
        target_volume_m=0, sessions=sessions,
    )
    store.save_week("renee", week)
    draft = week.model_copy(update={"id": uuid.uuid4(), "draft": True, "iso_week": "2026-W43"})
    store.save_week_draft("renee", draft)
    return store


def _kinds(store) -> dict[str, str | None]:
    return {s.purpose[:10]: s.kind for s in store.load_week("renee", "2026-W42").sessions}


def test_dry_run_proposes_but_writes_nothing(seeded, athletes_dir):
    rows = backfill(seeded, ["renee"], apply=False)
    assert {(r["date"], r["kind"]) for r in rows} == {("2026-10-14", "warmup"), ("2026-10-17", "race")}
    assert all(v is None or v == "free_ride" for v in _kinds(seeded).values())


def test_apply_tags_only_unkinded_sessions_and_is_idempotent(seeded):
    assert len(backfill(seeded, ["renee"], apply=True)) == 2
    kinds = _kinds(seeded)
    assert kinds["Openers --"] == "warmup" and kinds["RACE -- Ma"] == "race"
    assert kinds["Z2 enduran"] is None  # left untagged
    assert kinds["RACE -- Da"] == "free_ride"  # explicit kind never overwritten
    assert backfill(seeded, ["renee"], apply=True) == []
    assert seeded.load_week_draft("renee", "2026-W43").sessions[0].kind is None  # drafts untouched


def test_cli_defaults_to_dry_run(seeded, athletes_dir, capsys):
    assert main(["--athletes-dir", str(athletes_dir), "--athlete", "renee"]) == 0
    out = capsys.readouterr().out
    assert "2 session kind(s) proposed (dry run" in out and "RACE -- Masters" in out
    assert _kinds(seeded)["RACE -- Ma"] is None
    assert main(["--athletes-dir", str(athletes_dir), "--athlete", "renee", "--apply"]) == 0
    assert _kinds(seeded)["RACE -- Ma"] == "race"
