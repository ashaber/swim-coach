import uuid
from datetime import date

import pytest

from swim_coach.models import Session
from swim_coach.session_lookup import (
    AmbiguousSession,
    SessionNotFound,
    candidates_on,
    find_session,
    short_id,
)

ATHLETE = uuid.uuid4()
DAY = date(2026, 10, 17)


def make(kind=None, sport="bike", day=DAY, title=None) -> Session:
    return Session(
        id=uuid.uuid4(), athlete_id=ATHLETE, date=day, sport=sport, source="ai_coach",
        duration_min=45.0, intensity={"zone": "Z2"}, purpose=f"{kind} ride", kind=kind, title=title,
    )


def test_unique_date_sport_resolves():
    s = make("race")
    assert find_session([s, make(sport="strength")], date=DAY, sport="bike") is s


def test_by_full_id_and_unique_prefix():
    a, b = make("warmup"), make("race")
    assert find_session([a, b], session_id=str(b.id)) is b
    assert find_session([a, b], session_id=short_id(a)) is a


def test_id_wins_over_date_sport():
    a, b = make("warmup"), make("race")
    assert find_session([a, b], session_id=a.id, date=DAY, sport="bike") is a


def test_date_sport_ambiguous_lists_candidates():
    a, b = make("warmup", title="Warm-up"), make("race", title="Race")
    with pytest.raises(AmbiguousSession) as exc:
        find_session([b, a], date=DAY, sport="bike")
    msg = str(exc.value)
    assert short_id(a) in msg and short_id(b) in msg and "kind=warmup" in msg and "kind=race" in msg
    assert exc.value.candidates == [a, b]  # warm-up first


def test_missing_and_short_id():
    with pytest.raises(SessionNotFound):
        find_session([make()], date=date(2026, 1, 1), sport="bike")
    with pytest.raises(SessionNotFound):
        find_session([make()], session_id="ab")
    with pytest.raises(SessionNotFound):
        find_session([make()], session_id="ffffffff")


def test_candidates_ordered_by_kind():
    r, w, o = make("race"), make("warmup"), make("opener")
    assert candidates_on([r, w, o], date=DAY, sport="bike") == [w, o, r]
