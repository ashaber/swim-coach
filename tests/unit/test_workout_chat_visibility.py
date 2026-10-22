from datetime import datetime, timezone
from uuid import uuid4

from swim_coach.models import WorkoutChatMessage, visible_workout_chat

COACH_A, COACH_B = uuid4(), uuid4()


def _msg(body: str, visibility: str = "all", coach=None, role: str = "coach") -> WorkoutChatMessage:
    return WorkoutChatMessage(
        id=uuid4(), sender_role=role, body=body, visibility=visibility,
        coach_athlete_id=coach, created_at=datetime.now(timezone.utc),
    )


def test_visibility_defaults_to_all() -> None:
    assert _msg("hi").visibility == "all"


def test_athlete_and_unidentified_viewer_see_only_public() -> None:
    thread = [_msg("public"), _msg("private", "coach_only", COACH_A)]
    assert [m.body for m in visible_workout_chat(thread)] == ["public"]


def test_coach_sees_own_private_but_not_another_coachs() -> None:
    thread = [
        _msg("public"),
        _msg("a-private", "coach_only", COACH_A),
        _msg("a-reply", "coach_only", COACH_A, role="ai_coach"),
        _msg("b-private", "coach_only", COACH_B),
    ]
    assert [m.body for m in visible_workout_chat(thread, viewer_coach_id=COACH_A)] == [
        "public", "a-private", "a-reply",
    ]
