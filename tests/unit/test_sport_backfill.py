"""Yoga re-sport backfill: selection, re-matching, and the legacy cross_train cycling listing.

The match cases are Andrew's real prod dates (Oct 2026): yoga stored as strength matched the
neighbouring "Cycling strength" sessions through the +-1 day window, and two yoga days matched
nothing. As `recovery` they pair with the planned yoga sessions.
"""

from __future__ import annotations

import uuid
from datetime import date

from swim_coach.models import Session, Workout
from swim_coach.quality import match_workout_to_session
from swim_coach.sport_backfill import (
    legacy_cycling_cross_train,
    resport_and_rematch,
    yoga_resport_candidates,
)

ATHLETE = uuid.uuid4()


def _session(day: date, sport: str, purpose: str) -> Session:
    return Session(
        id=uuid.uuid4(), athlete_id=ATHLETE, date=day, sport=sport, source="ai_coach",
        duration_min=30.0, distance_m=0, intensity={"zone": "Z1"}, purpose=purpose,
    )


def _workout(day: date, sport: str = "strength", detail: str | None = "training/yoga", **kw) -> Workout:
    return Workout(
        id=uuid.uuid4(), athlete_id=ATHLETE, date=day, sport=sport, source="fit",
        distance_m=0, duration_min=30.0, sport_detail=detail, **kw,
    )


def _plan() -> dict[str, Session]:
    return {
        "yoga_05": _session(date(2026, 10, 5), "recovery", "Yoga"),
        "str_06": _session(date(2026, 10, 6), "strength", "Cycling strength"),
        "yoga_09": _session(date(2026, 10, 9), "recovery", "Yoga"),
        "str_10": _session(date(2026, 10, 10), "strength", "Cycling strength"),
        "yoga_12": _session(date(2026, 10, 12), "recovery", "Yoga"),
        "yoga_15": _session(date(2026, 10, 15), "recovery", "Yoga"),
    }


def test_candidates_are_strength_workouts_with_mobility_detail_only():
    yoga = _workout(date(2026, 10, 5))
    lift = _workout(date(2026, 10, 6), detail="training/strength_training")
    cardio = _workout(date(2026, 10, 7), detail="training/cardio_training")
    already = _workout(date(2026, 10, 8), sport="recovery")
    bike = _workout(date(2026, 10, 9), sport="bike", detail="cycling/mountain")
    assert yoga_resport_candidates([yoga, lift, cardio, already, bike]) == [yoga]


def test_real_prod_yoga_dates_match_planned_yoga_after_resport():
    plan = _plan()
    sessions = list(plan.values())
    yoga = [_workout(date(2026, 10, d)) for d in (5, 9, 11, 14)]
    # as stored today: the 10/5 and 10/9 workouts were linked to the neighbouring strength sessions
    yoga[0] = yoga[0].model_copy(update={"planned_session_id": plan["str_06"].id})
    yoga[1] = yoga[1].model_copy(update={"planned_session_id": plan["str_10"].id})

    done: list[Workout] = []
    for w in yoga:
        done.append(resport_and_rematch(w, sessions=sessions, others=done))

    assert [w.sport for w in done] == ["recovery"] * 4
    assert [w.planned_session_id for w in done] == [
        plan["yoga_05"].id, plan["yoga_09"].id, plan["yoga_12"].id, plan["yoga_15"].id,
    ]
    # the strength sessions are left uncovered (no workout points at them)
    claimed = {w.planned_session_id for w in done}
    assert plan["str_06"].id not in claimed and plan["str_10"].id not in claimed


def test_link_to_a_recovery_session_is_kept():
    plan = _plan()
    w = _workout(date(2026, 10, 11), planned_session_id=plan["yoga_12"].id)
    out = resport_and_rematch(w, sessions=list(plan.values()), others=[])
    assert out.planned_session_id == plan["yoga_12"].id


def test_stale_link_with_no_recovery_match_is_cleared_not_kept():
    plan = _plan()
    w = _workout(date(2026, 10, 20), planned_session_id=plan["str_10"].id)
    out = resport_and_rematch(w, sessions=list(plan.values()), others=[])
    assert out.sport == "recovery" and out.planned_session_id is None


def test_matching_alone_after_resport_needs_no_special_casing():
    plan = _plan()
    w = _workout(date(2026, 10, 14), sport="recovery")
    assert match_workout_to_session(w, list(plan.values())) is plan["yoga_15"]


def test_legacy_cross_train_cycling_listing():
    old_mtb = _workout(date(2026, 6, 1), sport="cross_train", detail="cycling/mountain")
    old_road = _workout(date(2026, 6, 2), sport="cross_train", detail="cycling")
    kayak = _workout(date(2026, 6, 3), sport="cross_train", detail="kayaking")
    bike = _workout(date(2026, 6, 4), sport="bike", detail="cycling/mountain")
    assert legacy_cycling_cross_train([old_mtb, old_road, kayak, bike]) == [old_mtb, old_road]
