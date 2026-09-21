"""Every draft-then-confirm tool writes the AGREED draft on confirm -- never a
recomputation (Andrew, 2026-09-21). Week tools: merge_week_plan,
propose_session_adjustment, propose_adaptation (written via replace_week_plan).
Macro tool: replace_macro_plan."""

from __future__ import annotations

from datetime import date

from swim_coach.store import FileStore

from app.tools import build_tool_handlers

GREECE = "UltraSwim 33.3 Greece (Skopelos) — single-day 33.3 km continuous"


def _h(athletes_dir):
    store = FileStore(base_dir=athletes_dir)
    return store, build_tool_handlers(store, slug="renee", expert_mode=False)


ADJ = {"iso_week": "2026-W28", "date": "2026-07-06", "sport": "swim_pool", "direction": "reduce",
       "magnitude_pct": 20, "reason": "fatigued"}


# --- propose_session_adjustment ---------------------------------------------------------


def test_session_adjustment_writes_exactly_the_agreed_draft(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    draft = h["propose_session_adjustment"](ADJ)
    assert draft["persisted"] is False and draft["draft_id"]
    before = store.load_week("renee", "2026-W28")

    # the athlete agreed to 20%; the coach mistakenly re-sends 60% on confirm
    done = h["propose_session_adjustment"]({**ADJ, "magnitude_pct": 60, "confirm": True, "draft_id": draft["draft_id"]})

    assert done["persisted"] is True and done["written_from_draft"] is True and done["verified"] is True
    assert done["session"]["distance_m"] == draft["session"]["distance_m"]  # the AGREED 20%, not 60%
    written = store.load_week("renee", "2026-W28")
    target = next(s for s in written.sessions if s.date == date(2026, 7, 6))
    assert target.distance_m == draft["session"]["distance_m"]
    assert len(written.sessions) == len(before.sessions)


def test_session_adjustment_without_a_draft_id_still_writes_the_agreed_draft(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    draft = h["propose_session_adjustment"](ADJ)
    done = h["propose_session_adjustment"]({**ADJ, "magnitude_pct": 60, "confirm": True})
    assert done["written_from_draft"] is True
    assert done["session"]["distance_m"] == draft["session"]["distance_m"]


def test_session_adjustment_flags_other_changes_made_after_the_draft_and_still_writes(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    draft = h["propose_session_adjustment"](ADJ)
    other = next(s for s in store.load_week("renee", "2026-W28").sessions if s.date == date(2026, 7, 8))
    h["patch_week_plan"]({"iso_week": "2026-W28", "confirm": True, "session_overrides": [
        {"date": "2026-07-08", "sport": other.sport, "duration_min": 20}]})  # changed AFTER the draft

    done = h["propose_session_adjustment"]({**ADJ, "confirm": True, "draft_id": draft["draft_id"]})

    assert done["persisted"] is True  # flagged, never blocked
    assert any("CHANGED" in w and "2026-07-08" in w for w in done["planning_warnings"])


def test_session_adjustment_one_shot_without_any_draft_is_flagged(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    done = h["propose_session_adjustment"]({**ADJ, "confirm": True})
    assert done["persisted"] is True and not done.get("written_from_draft")
    assert any("ONE step" in w for w in done["planning_warnings"])


# --- merge_week_plan ------------------------------------------------------------------------


MERGE = {
    "iso_week": "2026-W28",
    "proposed_sessions": [{"date": "2026-07-07", "sport": "strength", "duration_min": 55,
                           "purpose": "kettlebell-focused dryland strength"}],
    "accept_from_proposed": [{"date": "2026-07-07", "sport": "strength"}],
}


def test_merge_confirm_writes_exactly_the_agreed_merge(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    draft = h["merge_week_plan"](MERGE)
    assert draft["persisted"] is False and draft["draft_id"]

    changed = {**MERGE, "proposed_sessions": [{**MERGE["proposed_sessions"][0], "purpose": "something else", "duration_min": 5}]}
    done = h["merge_week_plan"]({**changed, "confirm": True, "draft_id": draft["draft_id"]})

    assert done["persisted"] is True and done["written_from_draft"] is True
    target = next(s for s in store.load_week("renee", "2026-W28").sessions if s.date == date(2026, 7, 7))
    assert target.purpose == "kettlebell-focused dryland strength" and target.duration_min == 55


def test_merge_confirm_without_a_draft_id_writes_the_latest_merge_draft(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    h["merge_week_plan"](MERGE)
    changed = {**MERGE, "proposed_sessions": [{**MERGE["proposed_sessions"][0], "purpose": "something else"}]}
    done = h["merge_week_plan"]({**changed, "confirm": True})
    assert done["written_from_draft"] is True
    target = next(s for s in store.load_week("renee", "2026-W28").sessions if s.date == date(2026, 7, 7))
    assert target.purpose == "kettlebell-focused dryland strength"


def test_merge_never_picks_up_another_tools_draft(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    target = next(s for s in store.load_week("renee", "2026-W28").sessions if s.date == date(2026, 7, 8))
    h["patch_week_plan"]({"iso_week": "2026-W28", "session_overrides": [
        {"date": "2026-07-08", "sport": target.sport, "duration_min": 10}]})  # a PATCH draft is the latest

    done = h["merge_week_plan"]({**MERGE, "confirm": True})  # no merge draft exists

    assert not done.get("written_from_draft")
    assert next(s for s in store.load_week("renee", "2026-W28").sessions if s.date == date(2026, 7, 8)).duration_min != 10


# --- propose_adaptation (written via replace_week_plan + draft_id) ----------------------------


def test_an_agreed_adaptation_is_written_exactly_not_regenerated(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    draft = h["propose_adaptation"]({"iso_week": "2026-W30"})
    assert draft["persisted"] is False and draft["draft_id"] and "replace_week_plan" in draft["next"]

    done = h["replace_week_plan"]({"iso_week": "2026-W30", "confirm": True, "draft_id": draft["draft_id"]})

    assert done["persisted"] is True and done["written_from_draft"] is True and done["verified"] is True
    saved = store.load_week("renee", "2026-W30")
    assert saved.draft is False
    assert saved.adaptation_rationale is not None  # the adaptation's own rationale survived
    assert sorted((s.date.isoformat(), s.sport, s.purpose) for s in saved.sessions) == sorted(
        (s["date"], s["sport"], s["purpose"]) for s in draft["sessions"]
    )


# --- replace_macro_plan -----------------------------------------------------------------------


MACRO = {"event_name": GREECE, "current_weekly_volume_m": 18000, "start_date": "2026-01-05"}


def test_macro_confirm_writes_exactly_the_agreed_macro(athletes_dir) -> None:
    (athletes_dir / "renee" / "plan" / "macro.yaml").unlink()
    store, h = _h(athletes_dir)
    draft = h["replace_macro_plan"](MACRO)
    assert draft["persisted"] is False and draft["draft_id"]
    assert store.load_macro("renee") is None

    # confirm re-sends a very different volume by mistake
    done = h["replace_macro_plan"]({**MACRO, "current_weekly_volume_m": 5000, "confirm": True, "draft_id": draft["draft_id"]})

    assert done["persisted"] is True and done["written_from_draft"] is True and done["verified"] is True
    saved = store.load_macro("renee")
    assert [b["weekly_volume_target_m"] for b in draft["blocks"]] == [b.weekly_volume_target_m for b in saved.blocks]


def test_macro_confirm_without_a_draft_id_writes_the_latest_macro_draft(athletes_dir) -> None:
    (athletes_dir / "renee" / "plan" / "macro.yaml").unlink()
    store, h = _h(athletes_dir)
    draft = h["replace_macro_plan"](MACRO)
    done = h["replace_macro_plan"]({**MACRO, "current_weekly_volume_m": 5000, "confirm": True})
    assert done["written_from_draft"] is True
    assert [b["weekly_volume_target_m"] for b in draft["blocks"]] == [
        b.weekly_volume_target_m for b in store.load_macro("renee").blocks
    ]


def test_an_unknown_macro_draft_id_writes_nothing(athletes_dir) -> None:
    (athletes_dir / "renee" / "plan" / "macro.yaml").unlink()
    store, h = _h(athletes_dir)
    h["replace_macro_plan"](MACRO)
    result = h["replace_macro_plan"]({**MACRO, "confirm": True, "draft_id": "00000000-0000-0000-0000-000000000000"})
    assert result["persisted"] is False and "draft" in result["error"].lower()
    assert store.load_macro("renee") is None


def test_macro_and_week_drafts_never_appear_as_weeks_or_macros(athletes_dir) -> None:
    (athletes_dir / "renee" / "plan" / "macro.yaml").unlink()
    store, h = _h(athletes_dir)
    before = store.list_week_ids("renee")
    h["replace_macro_plan"](MACRO)
    assert store.list_week_ids("renee") == before and store.load_macro("renee") is None
