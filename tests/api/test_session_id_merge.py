"""merge_week_plan treats two same-sport sessions on one day as two slots."""

from __future__ import annotations

from swim_coach.store import FileStore

from app.tools import build_tool_handlers

WEEK = "2026-W28"
DAY = "2026-07-10"

PROPOSED_WARM = {"date": DAY, "sport": "bike", "kind": "warmup", "duration_min": 30, "purpose": "Warm-up spin"}
PROPOSED_RACE = {"date": DAY, "sport": "bike", "kind": "race", "duration_min": 90, "purpose": "Road race"}
BOTH = {"iso_week": WEEK, "proposed_sessions": [PROPOSED_WARM, PROPOSED_RACE]}


def _handlers(athletes_dir):
    return build_tool_handlers(FileStore(base_dir=athletes_dir), slug="renee", expert_mode=False)


def _bike_kinds(plan):
    return [r["kind"] for r in plan if r["date"] == DAY and r["sport"] == "bike"]


def test_diff_has_a_slot_per_same_sport_session(athletes_dir) -> None:
    diff = _handlers(athletes_dir)["merge_week_plan"](BOTH)["diff"]
    bike = [d for d in diff if d["date"] == DAY and d["sport"] == "bike"]
    assert sorted(d["kind"] for d in bike) == ["race", "warmup"]
    assert all(d["status"] == "new_in_proposed" for d in bike)


def test_accept_by_date_sport_is_ambiguous_but_kind_picks_one(athletes_dir) -> None:
    h = _handlers(athletes_dir)
    bad = h["merge_week_plan"]({**BOTH, "accept_from_proposed": [{"date": DAY, "sport": "bike"}]})
    assert "error" in bad and "kind" in bad["error"]
    good = h["merge_week_plan"]({**BOTH, "accept_from_proposed": [{"date": DAY, "sport": "bike", "kind": "race"}]})
    assert "error" not in good, good
    assert _bike_kinds(good["merged_plan"]) == ["race"]


def test_accept_by_current_session_id(athletes_dir) -> None:
    h = _handlers(athletes_dir)
    store = FileStore(base_dir=athletes_dir)
    draft = h["patch_week_plan"]({"iso_week": WEEK, "session_overrides": [
        {**PROPOSED_WARM, "add": True}, {**PROPOSED_RACE, "add": True}]})
    h["patch_week_plan"]({"iso_week": WEEK, "confirm": True, "draft_id": draft["draft_id"]})
    race = next(s for s in store.load_week("renee", WEEK).sessions if s.kind == "race")
    longer = {**PROPOSED_RACE, "duration_min": 120}
    got = h["merge_week_plan"]({"iso_week": WEEK, "proposed_sessions": [longer],
                                "accept_from_proposed": [{"session_id": str(race.id)}]})
    assert "error" not in got, got
    rides = {r["kind"]: r for r in got["merged_plan"] if r["date"] == DAY and r["sport"] == "bike"}
    assert rides["race"]["duration_min"] == 120 and rides["warmup"]["duration_min"] == 30
