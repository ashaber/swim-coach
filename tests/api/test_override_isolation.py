"""One bad override entry must never sink the rest of the week (Andrew, 2026-09-21): "the week plan
includes kettlebells, the KB workout dropped to prose but the rest is good -- then go back and rewrite
just that workout", versus "can't write an otherwise correct week plan because the KB workout doesn't
have full detail/structure". Each entry is applied on its own; an entry that fails is degraded to its
text (or, if it cannot be placed at all, reported as NOT APPLIED) and everything else still lands."""

from __future__ import annotations

import json

from swim_coach.store import FileStore

import app.tools as tools
from app.tools import build_tool_handlers

WEEK = "2026-W28"
GARBAGE = {"foo": "bar"}  # not a WorkoutStructure and nothing salvageable in it


def _h(athletes_dir):
    store = FileStore(base_dir=athletes_dir)
    return store, build_tool_handlers(store, slug="renee", expert_mode=False)


def _session(store, day, sport):
    return next(s for s in store.load_week("renee", WEEK).sessions if s.date.isoformat() == day and s.sport == sport)


GOOD = {"date": "2026-07-08", "sport": "swim_pool", "duration_min": 33}
NO_SUCH_DAY = {"date": "2026-08-30", "sport": "bike", "duration_min": 40}  # nothing to modify: cannot be placed


def test_a_bad_entry_does_not_sink_the_good_ones(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    draft = h["patch_week_plan"]({"iso_week": WEEK, "session_overrides": [GOOD, NO_SUCH_DAY]})

    assert "error" not in draft, draft
    assert next(s for s in draft["sessions"] if s["date"] == "2026-07-08" and s["sport"] == "swim_pool")["duration_min"] == 33
    assert [f["date"] for f in draft["not_applied"]] == ["2026-08-30"]
    assert any("NOT APPLIED" in w and "2026-08-30" in w for w in draft["planning_warnings"])
    h["patch_week_plan"]({"iso_week": WEEK, "confirm": True, "draft_id": draft["draft_id"]})
    assert _session(store, "2026-07-08", "swim_pool").duration_min == 33


def test_the_order_of_entries_does_not_matter_for_isolation(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    draft = h["patch_week_plan"]({"iso_week": WEEK, "session_overrides": [NO_SUCH_DAY, GOOD]})
    assert "error" not in draft and len(draft["not_applied"]) == 1
    assert next(s for s in draft["sessions"] if s["date"] == "2026-07-08" and s["sport"] == "swim_pool")["duration_min"] == 33


def test_if_every_entry_fails_the_call_is_an_error_and_writes_nothing(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    result = h["patch_week_plan"]({"iso_week": WEEK, "session_overrides": [NO_SUCH_DAY]})
    assert "error" in result and "2026-08-30" in result["error"]


def test_a_single_entry_call_behaves_as_it_always_did(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    draft = h["patch_week_plan"]({"iso_week": WEEK, "session_overrides": [GOOD]})
    assert "error" not in draft and "not_applied" not in draft


# --- the kettlebell scenario ------------------------------------------------------------------------------------


KB_ADD = {"date": "2026-07-07", "sport": "strength", "purpose": "Kettlebell EMOM", "duration_min": 30,
          "structure": "10 min EMOM: 12 swings / 8 goblet squats", "structured": GARBAGE,
          "intensity": {"zone": "not-a-zone"}}


def test_the_kettlebell_workout_drops_to_prose_and_the_rest_of_the_week_is_written(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    draft = h["patch_week_plan"]({"iso_week": WEEK, "session_overrides": [KB_ADD, GOOD]})

    assert "error" not in draft, draft
    kb = next(s for s in draft["sessions"] if s["date"] == "2026-07-07" and s["sport"] == "strength")
    assert kb["purpose"] == "Kettlebell EMOM" and kb["has_structured"] is False           # the KB workout, as prose
    assert next(s for s in draft["sessions"] if s["date"] == "2026-07-08" and s["sport"] == "swim_pool")["duration_min"] == 33
    assert any("KB" in w or "detailed part" in w or "structured" in w for w in draft["planning_warnings"])
    done = h["patch_week_plan"]({"iso_week": WEEK, "confirm": True, "draft_id": draft["draft_id"]})
    assert done["persisted"] is True
    assert "12 swings" in _session(store, "2026-07-07", "strength").structure


def test_then_just_that_workout_can_be_rewritten_with_full_structure(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    first = h["patch_week_plan"]({"iso_week": WEEK, "session_overrides": [KB_ADD, GOOD]})
    h["patch_week_plan"]({"iso_week": WEEK, "confirm": True, "draft_id": first["draft_id"]})

    good_structure = {"items": [{"kind": "step", "label": "KB EMOM x10", "role": "interval", "duration_kind": "time_s",
                                 "duration_value": 600, "modality": "strength"}]}
    second = h["patch_week_plan"]({"iso_week": WEEK, "session_overrides": [
        {"date": "2026-07-07", "sport": "strength", "structured": good_structure}]})
    h["patch_week_plan"]({"iso_week": WEEK, "confirm": True, "draft_id": second["draft_id"]})

    kb = _session(store, "2026-07-07", "strength")
    assert kb.structured is not None                                            # now fully structured
    assert next(s for s in store.load_week("renee", WEEK).sessions if s.date.isoformat() == "2026-07-08" and s.sport == "swim_pool").duration_min == 33  # rest untouched


def test_a_bad_intensity_keeps_the_rest_of_the_entry_and_says_what_was_dropped(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    draft = h["patch_week_plan"]({"iso_week": WEEK, "session_overrides": [
        {"date": "2026-07-08", "sport": "swim_pool", "purpose": "Easy technique", "intensity": {"zone": "hard"}}]})
    assert "error" not in draft
    assert next(s for s in draft["sessions"] if s["date"] == "2026-07-08" and s["sport"] == "swim_pool")["purpose"] == "Easy technique"
    assert any("detailed part" in w for w in draft["planning_warnings"])


# --- an unexpected exception inside one entry -----------------------------------------------------------------------


def test_an_exception_inside_one_entry_is_isolated_logged_and_degrades_to_text(athletes_dir, monkeypatch, capsys) -> None:
    store, h = _h(athletes_dir)
    real = tools._coerce_structured

    def boom(raw, **kw):
        if raw == {"marker": "explode"}:
            raise RuntimeError("bug in structured handling")
        return real(raw, **kw)

    monkeypatch.setattr(tools, "_coerce_structured", boom)
    entry = {"date": "2026-07-07", "sport": "strength", "purpose": "KB day", "structure": "12 swings",
             "structured": {"marker": "explode"}}

    draft = h["patch_week_plan"]({"iso_week": WEEK, "session_overrides": [entry, GOOD]})

    assert "error" not in draft, draft
    assert next(s for s in draft["sessions"] if s["date"] == "2026-07-07" and s["sport"] == "strength")["purpose"] == "KB day"
    assert next(s for s in draft["sessions"] if s["date"] == "2026-07-08" and s["sport"] == "swim_pool")["duration_min"] == 33
    logged = [json.loads(l) for l in capsys.readouterr().err.splitlines() if l.startswith("{")]
    entry_log = next(e for e in logged if e.get("msg") == "override entry failed")
    assert entry_log["error_type"] == "RuntimeError" and "Traceback" in entry_log["stack"] and entry_log["date"] == "2026-07-07"


def test_a_half_applied_entry_is_rolled_back_before_the_text_only_retry(athletes_dir, monkeypatch) -> None:
    store, h = _h(athletes_dir)

    def boom(session, wanted, ftp):
        raise RuntimeError("interval builder blew up")

    monkeypatch.setattr(tools, "bike_session_as", boom)
    # a bike session so interval_type is attempted; use replace path via an added bike session
    add = h["patch_week_plan"]({"iso_week": WEEK, "session_overrides": [
        {"date": "2026-07-07", "sport": "bike", "add": True, "duration_min": 60, "purpose": "Ride", "interval_type": "threshold"}]})
    assert "error" not in add
    ride = next(s for s in add["sessions"] if s["date"] == "2026-07-07" and s["sport"] == "bike")
    assert ride["purpose"] == "Ride" and ride["duration_min"] == 60          # text-only retry applied
    assert len([s for s in add["sessions"] if s["date"] == "2026-07-07" and s["sport"] == "bike"]) == 1   # no duplicate from the failed attempt


def test_replace_week_plan_isolates_entries_too(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    draft = h["replace_week_plan"]({"iso_week": WEEK, "session_overrides": [GOOD, NO_SUCH_DAY]})
    assert "error" not in draft and [f["date"] for f in draft["not_applied"]] == ["2026-08-30"]
