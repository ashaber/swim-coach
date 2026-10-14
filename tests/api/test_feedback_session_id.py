"""Session-linked questions carry the planned session's id (so two same-sport sessions on one day are
told apart); rows linked only by session_date + session_sport keep working."""

from __future__ import annotations

import uuid
from datetime import date

from fakes import auth_headers, make_final_message, make_session, make_text_block
from swim_coach.models import WeekPlan
from swim_coach.store import FileStore

from app.context import iso_week_str


def _save_race_day(athletes_dir):
    store = FileStore(base_dir=athletes_dir)
    profile = store.load_athlete("renee")
    today = date.today()
    warm = make_session(athlete_id=profile.id, date=today, sport="bike", kind="warmup", purpose="warm-up spin only")
    race = make_session(athlete_id=profile.id, date=today, sport="bike", kind="race", purpose="the actual road race")
    store.save_week("renee", WeekPlan(
        id=uuid.uuid4(), athlete_id=profile.id, iso_week=iso_week_str(today), meso_block="base",
        focus="race", target_volume_m=0, sessions=[warm, race],
    ))
    return today, warm, race


def _system_text(chat) -> str:
    return "\n".join(block["text"] for block in chat.client.messages.calls[0]["system"])


def test_question_by_session_id_focuses_that_session_and_stores_the_link(client, athletes_dir, fake_claude_chat_factory) -> None:
    _today, warm, race = _save_race_day(athletes_dir)
    final = make_final_message([make_text_block("Ride it hard.")], "end_turn")
    chat = fake_claude_chat_factory([(["Ride it hard."], final)])

    response = client.post(
        "/api/feedback/questions?athlete=renee",
        json={"body": "how hard?", "session_id": str(race.id)},
        headers=auth_headers(),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["session_id"] == str(race.id)
    assert body["session_date"] == race.date.isoformat() and body["session_sport"] == "bike"
    focused = _system_text(chat).split("specific planned session the athlete is asking about")[1]
    assert str(race.id) in focused and str(warm.id) not in focused

    stored = FileStore(base_dir=athletes_dir).list_feedback(athlete="renee")[0]
    assert str(stored.session_id) == str(race.id)


def test_date_sport_on_a_two_session_day_is_a_422_listing_the_candidates(client, athletes_dir, fake_claude_chat_factory) -> None:
    today, warm, race = _save_race_day(athletes_dir)
    fake_claude_chat_factory([])
    response = client.post(
        "/api/feedback/questions?athlete=renee",
        json={"body": "how hard?", "session_date": today.isoformat(), "session_sport": "bike"},
        headers=auth_headers(),
    )
    assert response.status_code == 422
    assert str(warm.id)[:8] in response.json()["error"] and str(race.id)[:8] in response.json()["error"]


def test_old_style_date_sport_still_links_a_single_session_day(client, athletes_dir, fake_claude_chat_factory) -> None:
    store = FileStore(base_dir=athletes_dir)
    profile = store.load_athlete("renee")
    today = date.today()
    only = make_session(athlete_id=profile.id, date=today, sport="swim_pool", purpose="only session today")
    store.save_week("renee", WeekPlan(
        id=uuid.uuid4(), athlete_id=profile.id, iso_week=iso_week_str(today), meso_block="base",
        focus="x", target_volume_m=1000, sessions=[only],
    ))
    final = make_final_message([make_text_block("ok")], "end_turn")
    chat = fake_claude_chat_factory([(["ok"], final)])
    response = client.post(
        "/api/feedback/questions?athlete=renee",
        json={"body": "q", "session_date": today.isoformat(), "session_sport": "swim_pool"},
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert response.json()["session_id"] == str(only.id)  # resolved, so the link now survives a same-day add
    assert "only session today" in _system_text(chat)


def test_unknown_session_id_still_answers_without_session_detail(client, athletes_dir, fake_claude_chat_factory) -> None:
    final = make_final_message([make_text_block("General.")], "end_turn")
    fake_claude_chat_factory([(["General."], final)])
    response = client.post(
        "/api/feedback/questions?athlete=renee",
        json={"body": "q", "session_id": str(uuid.uuid4())},
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert response.json()["session_date"] is None
