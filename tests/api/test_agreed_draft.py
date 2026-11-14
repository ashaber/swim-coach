"""Once the coach and the athlete agree to a plan, `confirm` must WRITE THAT PLAN --
not recompute one. (Andrew, 2026-09-21: "plan creates plan; let the coach write it
once agreed. Flag risk, don't block, don't corrupt.") The agreed-draft machinery
(`_hold_draft` / `_confirm_from_draft`) is shared by every draft-then-confirm week
tool; `patch_week_plan` is the vehicle here, `merge_week_plan` the "other tool"."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from fakes import seed_generated_week
from swim_coach.models import Event, Session
from swim_coach.plan import scaffold_macro
from swim_coach.store import FileStore

from app.tools import build_tool_handlers

TEMPLATE_A = {
    "tue": [{"kind": "bike", "role": "hard"}, {"kind": "strength"}],
    "wed": [{"kind": "bike", "role": "endurance", "label": "Club ride"}],
    "sun": [{"kind": "bike", "role": "endurance", "label": "Club ride"}],
}


def _iso(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _setup(athletes_dir):
    store = FileStore(base_dir=athletes_dir)
    h = build_tool_handlers(store, slug="renee", expert_mode=False)
    h["update_athlete_profile"]({"sports": ["bike"], "ftp_watts": 250.0})
    athlete = store.load_athlete("renee")
    start = date.today() - timedelta(days=date.today().weekday()) - timedelta(weeks=1)
    event = Event(id=uuid.uuid4(), athlete_id=athlete.id, name="CX", event_date=start + timedelta(weeks=24),
                  target_metric="duration_min", distance_m=None, target_value=300.0, primary_sport="bike", priority="A")
    macro = scaffold_macro(athlete, event, start, current_weekly_volume_m=200, peak_weekly_volume_m=600)
    store.save_events("renee", [event])
    store.save_macro("renee", macro)
    h["set_weekly_template"]({"template": TEMPLATE_A, "confirm": True})
    ws = next(b for b in macro.blocks if b.name in ("build", "peak", "base")).start_date + timedelta(weeks=1)
    iso = _iso(ws)
    seed_generated_week(store, "renee", iso)  # a live week to edit
    return store, h, iso


def _bike(store, iso):
    return next(s for s in store.load_week("renee", iso).sessions if s.sport == "bike")


def _edit(session, **fields):
    return [{"date": session.date.isoformat(), "sport": "bike", **fields}]


def _shape(sessions):
    return sorted((s["date"], s["sport"], s["purpose"]) for s in sessions)


def _live_purpose(store, iso, target):
    return next(s for s in store.load_week("renee", iso).sessions if s.date == target.date and s.sport == "bike").purpose


def test_draft_is_held_not_written_and_hidden_from_the_weeks_list(athletes_dir) -> None:
    store, h, iso = _setup(athletes_dir)
    target = _bike(store, iso)
    before = _live_purpose(store, iso, target)
    draft = h["patch_week_plan"]({"iso_week": iso, "session_overrides": _edit(target, purpose="agreed: easy spin")})
    assert draft["persisted"] is False and draft["draft_id"]
    assert _live_purpose(store, iso, target) == before
    assert store.list_week_ids("renee").count(iso) == 1  # the held draft is not a second week


def test_confirm_writes_exactly_the_agreed_draft_even_if_the_live_week_drifted(athletes_dir) -> None:
    store, h, iso = _setup(athletes_dir)
    target = _bike(store, iso)
    draft = h["patch_week_plan"]({"iso_week": iso, "session_overrides": _edit(target, purpose="agreed: easy spin")})
    agreed = _shape(draft["sessions"])

    # The world moves between agreement and confirm: the live week's session is edited directly.
    live = store.load_week("renee", iso)
    for s in live.sessions:
        if s.id == target.id:
            s.purpose = "drifted"
    store.save_week("renee", live)

    done = h["patch_week_plan"]({"iso_week": iso, "confirm": True, "draft_id": draft["draft_id"]})

    assert done["persisted"] is True and done["written_from_draft"] is True and done["verified"] is True
    assert _shape(done["sessions"]) == agreed
    saved = store.load_week("renee", iso)
    assert sorted((s.date.isoformat(), s.sport, s.purpose) for s in saved.sessions) == agreed
    assert saved.draft is False


def test_confirm_without_a_draft_id_writes_the_latest_draft(athletes_dir) -> None:
    store, h, iso = _setup(athletes_dir)
    target = _bike(store, iso)
    draft = h["patch_week_plan"]({"iso_week": iso, "session_overrides": _edit(target, purpose="agreed: easy spin")})
    done = h["patch_week_plan"]({"iso_week": iso, "confirm": True})
    assert done["written_from_draft"] is True and _shape(done["sessions"]) == _shape(draft["sessions"])


def test_confirm_writes_the_draft_that_was_agreed_not_a_newer_one(athletes_dir) -> None:
    store, h, iso = _setup(athletes_dir)
    target = _bike(store, iso)
    agreed = h["patch_week_plan"]({"iso_week": iso, "session_overrides": _edit(target, purpose="agreed: easy spin")})
    newer = h["patch_week_plan"]({"iso_week": iso, "session_overrides": _edit(target, purpose="a later exploratory edit")})
    assert _shape(newer["sessions"]) != _shape(agreed["sessions"])

    done = h["patch_week_plan"]({"iso_week": iso, "confirm": True, "draft_id": agreed["draft_id"]})

    assert _shape(done["sessions"]) == _shape(agreed["sessions"])


def test_an_unknown_draft_id_writes_nothing_and_says_how_to_recover(athletes_dir) -> None:
    store, h, iso = _setup(athletes_dir)
    target = _bike(store, iso)
    before = _live_purpose(store, iso, target)
    h["patch_week_plan"]({"iso_week": iso, "session_overrides": _edit(target, purpose="agreed: easy spin")})
    result = h["patch_week_plan"]({"iso_week": iso, "confirm": True, "draft_id": str(uuid.uuid4())})
    assert result["persisted"] is False and "draft" in result["error"].lower()
    assert _live_purpose(store, iso, target) == before


def test_confirm_with_no_draft_on_file_still_writes_and_flags_that_it_was_not_agreed(athletes_dir) -> None:
    store, h, iso = _setup(athletes_dir)
    target = _bike(store, iso)
    done = h["patch_week_plan"]({"iso_week": iso, "confirm": True, "session_overrides": _edit(target, purpose="one shot")})
    assert done["persisted"] is True and not done.get("written_from_draft")
    assert any("one step" in w.lower() for w in done["planning_warnings"])


def test_risk_is_flagged_but_never_blocks_when_the_live_week_has_sessions_the_draft_drops(athletes_dir) -> None:
    store, h, iso = _setup(athletes_dir)
    target = _bike(store, iso)
    draft = h["patch_week_plan"]({"iso_week": iso, "session_overrides": _edit(target, purpose="agreed: easy spin")})

    # Between agreement and confirm the athlete adds a session to the live week -- the draft predates it.
    live = store.load_week("renee", iso)
    extra = date.fromisocalendar(int(iso[:4]), int(iso[6:]), 1) + timedelta(days=3)
    live.sessions.append(Session(
        id=uuid.uuid4(), athlete_id=live.athlete_id, date=extra, sport="recovery", source="ai_coach",
        duration_min=30.0, distance_m=None, intensity={"anchor": "rpe"},
        purpose="extra recovery the athlete added", structure=None, status="planned",
    ))
    store.save_week("renee", live)
    assert not any(d["date"] == extra.isoformat() and d["sport"] == "recovery" for d in draft["sessions"])

    done = h["patch_week_plan"]({"iso_week": iso, "confirm": True, "draft_id": draft["draft_id"]})

    assert done["persisted"] is True  # flagged, not blocked
    assert any("DROPPED" in w for w in done["planning_warnings"])


def test_patch_confirm_writes_the_agreed_patch_not_a_recomputation(athletes_dir) -> None:
    store, h, iso = _setup(athletes_dir)
    target = _bike(store, iso)
    override = _edit(target, purpose="agreed: easy spin", intensity={"zone": "Z1"})
    draft = h["patch_week_plan"]({"iso_week": iso, "session_overrides": override})
    assert draft["persisted"] is False and draft["draft_id"]

    done = h["patch_week_plan"]({
        "iso_week": iso, "confirm": True, "draft_id": draft["draft_id"],
        "session_overrides": _edit(target, purpose="a different edit"),
    })

    assert done["persisted"] is True and done["written_from_draft"] is True
    assert _live_purpose(store, iso, target) == "agreed: easy spin"
    assert any("NOT applied" in w for w in done["planning_warnings"])


def test_patch_confirm_needs_no_overrides_when_a_draft_is_on_file(athletes_dir) -> None:
    store, h, iso = _setup(athletes_dir)
    target = _bike(store, iso)
    draft = h["patch_week_plan"]({"iso_week": iso, "session_overrides": _edit(target, duration_min=45)})

    done = h["patch_week_plan"]({"iso_week": iso, "confirm": True, "draft_id": draft["draft_id"]})

    assert done["persisted"] is True
    assert next(s for s in store.load_week("renee", iso).sessions if s.date == target.date and s.sport == "bike").duration_min == 45


def test_tools_advertise_draft_id_and_the_persona_explains_the_draft_is_the_plan() -> None:
    from app.context import PERSONA_AND_RULES
    from app.tools import TOOLS_SCHEMA

    for name in ("author_week_plan", "patch_week_plan"):
        props = next(t for t in TOOLS_SCHEMA if t["name"] == name)["input_schema"]["properties"]
        assert "draft_id" in props
    assert "the draft IS the plan" in " ".join(PERSONA_AND_RULES.split())


def test_a_missing_draft_id_with_resent_overrides_still_writes_the_agreed_draft(athletes_dir) -> None:
    # The guaranteed-failure case: the coach forgets draft_id and re-sends overrides
    # out of habit. The agreed draft must still be what is written.
    store, h, iso = _setup(athletes_dir)
    target = _bike(store, iso)
    draft = h["patch_week_plan"]({"iso_week": iso, "session_overrides": _edit(target, purpose="agreed: easy spin")})

    done = h["patch_week_plan"]({
        "iso_week": iso, "confirm": True,
        "session_overrides": _edit(target, purpose="a different edit"),
    })

    assert done["written_from_draft"] is True
    assert _shape(done["sessions"]) == _shape(draft["sessions"])
    assert any("NOT applied" in w for w in done["planning_warnings"])


def test_a_stale_draft_is_never_written_by_a_confirm_that_names_no_draft_id(athletes_dir) -> None:
    from datetime import datetime, timedelta, timezone

    store, h, iso = _setup(athletes_dir)
    target = _bike(store, iso)
    draft = h["patch_week_plan"]({"iso_week": iso, "session_overrides": _edit(target, purpose="agreed: easy spin")})
    old = store.load_week_draft("renee", iso).model_copy(
        update={"drafted_at": datetime.now(timezone.utc) - timedelta(days=2)}
    )
    store.save_week_draft("renee", old)

    done = h["patch_week_plan"]({"iso_week": iso, "confirm": True, "session_overrides": _edit(target, purpose="one shot")})

    assert not done.get("written_from_draft")
    assert any("ONE step" in w for w in done["planning_warnings"])
    # ...but naming it explicitly is deliberate and is honoured
    again = h["patch_week_plan"]({"iso_week": iso, "confirm": True, "draft_id": draft["draft_id"]})
    assert again["written_from_draft"] is True


def test_a_draft_from_another_tool_is_never_written_by_a_confirm_that_names_no_draft_id(athletes_dir) -> None:
    store, h, iso = _setup(athletes_dir)
    target = _bike(store, iso)
    before = _live_purpose(store, iso, target)
    h["patch_week_plan"]({"iso_week": iso, "session_overrides": _edit(target, purpose="a PATCH draft is latest")})

    done = h["merge_week_plan"]({"iso_week": iso, "accept_from_proposed": [], "confirm": True})  # no draft_id, wrong tool

    assert not done.get("written_from_draft")
    assert _live_purpose(store, iso, target) == before
