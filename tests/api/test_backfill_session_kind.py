"""scripts/backfill_session_kind.py and its classifier, on the real purposes seen in prod."""

from __future__ import annotations

import sys
import uuid
from datetime import date
from pathlib import Path

import pytest
from swim_coach.models import Session, WeekPlan
from swim_coach.session_kind_backfill import propose_kinds, wording_kind
from swim_coach.store import FileStore

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from backfill_session_kind import backfill, main  # noqa: E402

ATHLETE = uuid.uuid4()

WORDING = [
    ("RACE -- Season Opener, Day 2", "race"),
    ("RACE -- Masters Cyclocross Series, Peak Weekend, Day 1", "race"),
    ("RACE — Cross: structured warm-up with 2–3 short openers, then race.", "race"),
    ("race: club crit", "race"),
    ("RACE - Day 3", "race"),
    ("OPENERS -- short/sharp", "opener"),
    ("Openers -- wake the legs", "opener"),
    ("PRE-RACE PRIMER — short progressive-ramp openers", "opener"),
    ("Race-day warm-up", "warmup"),
    ("Warm-up spin", "warmup"),
    ("MTB endurance (Z2) -- trimmed for race week", None),
    ("race-week easy spin — aerobic, keep it light", None),
    ("race-week opener — short, race-intensity-adjacent effort", None),
    ("Build — 40/20s VO2 intervals", None),
    ("Raceday nutrition rehearsal", None),
]


@pytest.mark.parametrize("purpose, expected", WORDING)
def test_wording_nominates_a_kind(purpose, expected):
    assert wording_kind(purpose) == expected


def _s(day: date, purpose: str, sport: str = "bike", **kw) -> Session:
    return Session(
        id=uuid.uuid4(), athlete_id=ATHLETE, date=day, sport=sport, source="ai_coach",
        duration_min=60.0, intensity={"zone": "Z2"}, purpose=purpose, **kw,
    )


def test_prod_purposes_get_the_owners_expected_kinds():
    sep15 = _s(date(2026, 9, 15), "OPENERS -- short/sharp legs, race week")
    sep18 = _s(date(2026, 9, 18), "PRE-RACE PRIMER — short progressive-ramp openers")
    sep19 = _s(date(2026, 9, 19), "RACE -- Season Opener, Day 1")
    sep20 = _s(date(2026, 9, 20), "RACE -- Season Opener, Day 2")
    oct16 = _s(date(2026, 10, 16), "Openers -- wake the legs")
    oct17 = _s(date(2026, 10, 17), "RACE -- Masters Cyclocross Series, Peak Weekend, Day 1")
    oct18 = _s(date(2026, 10, 18), "RACE -- Masters Cyclocross Series, Peak Weekend, Day 2")
    endurance = _s(date(2026, 9, 16), "MTB endurance (Z2) -- trimmed for race week")
    out = propose_kinds([sep15, sep18, sep19, sep20, oct16, oct17, oct18, endurance])
    assert out == {
        sep18.id: "opener", sep19.id: "race", sep20.id: "race",
        oct16.id: "opener", oct17.id: "race", oct18.id: "race",
    }
    assert sep15.id not in out and endurance.id not in out  # no race the next day: stays workout


def test_opener_and_warmup_need_a_race_of_the_same_sport_on_the_right_day():
    opener = _s(date(2026, 10, 16), "Openers -- x")
    warm = _s(date(2026, 10, 17), "Race-day warm-up")
    swim_race = _s(date(2026, 10, 17), "RACE: swim", sport="swim_ow")
    assert propose_kinds([opener, warm, swim_race]) == {swim_race.id: "race"}
    bike_race = _s(date(2026, 10, 17), "RACE -- bike")
    assert propose_kinds([opener, warm, bike_race]) == {
        opener.id: "opener", warm.id: "warmup", bike_race.id: "race"
    }
    # an explicit race anchors even though it is not itself re-proposed
    explicit = _s(date(2026, 10, 17), "Cross day", kind="race")
    assert propose_kinds([opener, explicit]) == {opener.id: "opener"}


@pytest.fixture
def seeded(athletes_dir: Path):
    store = FileStore(base_dir=athletes_dir)
    athlete = store.load_athlete("renee")

    def sess(day, purpose, **kw):
        return Session(
            id=uuid.uuid4(), athlete_id=athlete.id, date=day, sport="bike", source="ai_coach",
            duration_min=60.0, intensity={"zone": "Z2"}, purpose=purpose, **kw,
        )

    # the opener is in W41, its race in W42: the week boundary must not hide the race
    w41 = WeekPlan(
        id=uuid.uuid4(), athlete_id=athlete.id, iso_week="2026-W41", meso_block="build", focus="x",
        target_volume_m=0, sessions=[sess(date(2026, 10, 11), "Openers -- wake the legs"), sess(date(2026, 10, 9), "Z2 endurance")],
    )
    w42 = WeekPlan(
        id=uuid.uuid4(), athlete_id=athlete.id, iso_week="2026-W42", meso_block="build", focus="race",
        target_volume_m=0,
        sessions=[
            sess(date(2026, 10, 12), "RACE -- Masters Cyclocross, Day 1"),
            sess(date(2026, 10, 13), "RACE -- Day 2 (retagged by hand)", kind="free_ride"),
        ],
    )
    store.save_week("renee", w41)
    store.save_week("renee", w42)
    store.save_week_draft("renee", w42.model_copy(update={"id": uuid.uuid4(), "draft": True, "iso_week": "2026-W43"}))
    return store


def _kinds(store, iso):
    return {s.purpose[:10]: s.kind for s in store.load_week("renee", iso).sessions}


def test_dry_run_proposes_but_writes_nothing(seeded):
    rows = backfill(seeded, ["renee"], apply=False)
    assert {(r["date"], r["kind"]) for r in rows} == {("2026-10-11", "opener"), ("2026-10-12", "race")}
    assert _kinds(seeded, "2026-W41")["Openers --"] is None


def test_apply_tags_across_the_week_boundary_and_is_idempotent(seeded):
    assert len(backfill(seeded, ["renee"], apply=True)) == 2
    assert _kinds(seeded, "2026-W41")["Openers --"] == "opener"
    assert _kinds(seeded, "2026-W41")["Z2 enduran"] is None
    k42 = _kinds(seeded, "2026-W42")
    assert k42["RACE -- Ma"] == "race" and k42["RACE -- Da"] == "free_ride"  # explicit never overwritten
    assert backfill(seeded, ["renee"], apply=True) == []
    assert seeded.load_week_draft("renee", "2026-W43").sessions[0].kind is None  # drafts untouched


def test_cli_defaults_to_dry_run(seeded, athletes_dir, capsys):
    assert main(["--athletes-dir", str(athletes_dir), "--athlete", "renee"]) == 0
    out = capsys.readouterr().out
    assert "2 session kind(s) proposed (dry run" in out and "RACE -- Masters" in out
    assert _kinds(seeded, "2026-W42")["RACE -- Ma"] is None
    assert main(["--athletes-dir", str(athletes_dir), "--athlete", "renee", "--apply"]) == 0
    assert _kinds(seeded, "2026-W42")["RACE -- Ma"] == "race"
