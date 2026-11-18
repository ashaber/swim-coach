"""Every draft-then-confirm tool writes the AGREED draft on confirm -- never a
recomputation (Andrew, 2026-09-21). Week tools: merge_week_plan,
propose_session_adjustment, author_week_plan (engine/plan-check-red-team PR
2 -- propose_adaptation itself is advisory-only now, no longer a writable
draft; see test_tools.py's author_week_plan coverage). Macro tool:
author_macro_plan."""

from __future__ import annotations

from datetime import date, timedelta

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


# --- propose_adaptation (advisory only) --------------------------------------------------------


def test_propose_adaptation_is_advisory_only_and_points_at_author_week_plan(athletes_dir) -> None:
    # engine/plan-check-red-team PR 2: propose_adaptation no longer holds a
    # writable draft -- it returns numbers for the coach to feed into
    # author_week_plan, which is where "write exactly the agreed draft" now
    # lives for a week's sessions (see test_tools.py's own
    # test_author_week_plan_draft_then_confirm_persists for that coverage).
    store, h = _h(athletes_dir)
    draft = h["propose_adaptation"]({"iso_week": "2026-W30"})
    assert draft["persisted"] is False
    assert "draft_id" not in draft
    assert "author_week_plan" in draft["next"]


# --- author_macro_plan ------------------------------------------------------------------------


def _macro_weeks(start: date, n: int = 3, hours: float = 8.0) -> list[dict]:
    return [
        {
            "week_start": (start + timedelta(weeks=i)).isoformat(),
            "phase": "Base" if i == 0 else "Build",
            "focus": "aerobic base" if i == 0 else "race-specific build",
            "hours": hours + i,
            "load_tss": 400.0 + i * 20,
            "ctl_target": 40.0 + i * 2,
            "key_sessions": ["Tue: over/unders 3x8min"],
            "recovery": False,
            "notes": None,
        }
        for i in range(n)
    ]


MACRO = {"event_names": [GREECE], "weeks": _macro_weeks(date(2026, 7, 6)), "architecture": "Base then build toward Greece."}


def _decisions(draft: dict) -> list[dict]:
    return [
        {
            "id": f["id"], "decision": "keep_as_is", "reason": "acceptable for now",
            **({"athlete_words": "fine with this"} if f["severity"] == "high" else {}),
        }
        for f in draft["report"]["findings"]
    ]


def _macro_hours(macro) -> list[float]:
    return [w.hours for w in macro.weeks]


def test_macro_confirm_writes_exactly_the_agreed_macro(athletes_dir) -> None:
    (athletes_dir / "renee" / "plan" / "macro.yaml").unlink()
    store, h = _h(athletes_dir)
    draft = h["author_macro_plan"](MACRO)
    assert draft["persisted"] is False and draft["draft_id"]
    assert store.load_macro("renee") is None

    # confirm re-sends a very different plan by mistake
    done = h["author_macro_plan"]({
        **{**MACRO, "weeks": _macro_weeks(date(2026, 7, 6), hours=2.0)},
        "confirm": True, "draft_id": draft["draft_id"], "decisions": _decisions(draft),
    })

    assert done["persisted"] is True and done["written_from_draft"] is True and done["verified"] is True
    assert _macro_hours(store.load_macro("renee")) == [8.0, 9.0, 10.0]


def test_macro_confirm_without_a_draft_id_writes_the_latest_macro_draft(athletes_dir) -> None:
    (athletes_dir / "renee" / "plan" / "macro.yaml").unlink()
    store, h = _h(athletes_dir)
    draft = h["author_macro_plan"](MACRO)
    done = h["author_macro_plan"]({"confirm": True, "decisions": _decisions(draft)})
    assert done["written_from_draft"] is True
    assert _macro_hours(store.load_macro("renee")) == [8.0, 9.0, 10.0]


def test_an_unknown_macro_draft_id_writes_nothing(athletes_dir) -> None:
    (athletes_dir / "renee" / "plan" / "macro.yaml").unlink()
    store, h = _h(athletes_dir)
    h["author_macro_plan"](MACRO)
    result = h["author_macro_plan"]({**MACRO, "confirm": True, "draft_id": "00000000-0000-0000-0000-000000000000"})
    assert result["persisted"] is False and "draft" in result["error"].lower()
    assert store.load_macro("renee") is None


def test_macro_and_week_drafts_never_appear_as_weeks_or_macros(athletes_dir) -> None:
    (athletes_dir / "renee" / "plan" / "macro.yaml").unlink()
    store, h = _h(athletes_dir)
    before = store.list_week_ids("renee")
    h["author_macro_plan"](MACRO)
    assert store.list_week_ids("renee") == before and store.load_macro("renee") is None


# --- a confirm needs NOTHING but the draft_id (the coach cannot remember anything else) --------
# The client replays only TEXT turns, so on the confirm turn the coach has lost every tool input
# from the draft turn. Confirm must not demand them back.


def test_session_adjustment_confirm_needs_only_the_draft_id(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    draft = h["propose_session_adjustment"](ADJ)
    done = h["propose_session_adjustment"]({"iso_week": "2026-W28", "confirm": True, "draft_id": draft["draft_id"]})
    assert done["persisted"] is True and done["written_from_draft"] is True
    assert next(s for s in store.load_week("renee", "2026-W28").sessions if s.date == date(2026, 7, 6)).distance_m == draft["session"]["distance_m"]


def test_merge_confirm_needs_only_the_draft_id(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    draft = h["merge_week_plan"](MERGE)
    done = h["merge_week_plan"]({"iso_week": "2026-W28", "confirm": True, "draft_id": draft["draft_id"]})
    assert done["persisted"] is True and done["written_from_draft"] is True


def test_author_macro_confirm_needs_only_the_draft_id_and_decisions(athletes_dir) -> None:
    (athletes_dir / "renee" / "plan" / "macro.yaml").unlink()
    store, h = _h(athletes_dir)
    draft = h["author_macro_plan"](MACRO)
    done = h["author_macro_plan"]({"confirm": True, "draft_id": draft["draft_id"], "decisions": _decisions(draft)})
    assert done["persisted"] is True and done["written_from_draft"] is True
    assert store.load_macro("renee") is not None


def test_patch_confirm_needs_only_iso_week_and_the_draft_id(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    t = next(s for s in store.load_week("renee", "2026-W28").sessions if s.date == date(2026, 7, 8))
    draft = h["patch_week_plan"]({"iso_week": "2026-W28", "session_overrides": [
        {"date": "2026-07-08", "sport": t.sport, "duration_min": 33}]})
    done = h["patch_week_plan"]({"iso_week": "2026-W28", "confirm": True, "draft_id": draft["draft_id"]})
    assert done["written_from_draft"] is True
    assert next(s for s in store.load_week("renee", "2026-W28").sessions if s.date == date(2026, 7, 8)).duration_min == 33
