"""Tests for the `set_workout_chat_muted` coach tool (IDEA 016) -- the deterministic mute
switch either party can flip so the AI reliably stops (or resumes) responding in one workout's
chat thread. "Deterministic" is the whole point: this must not depend on the model choosing to
comply on its own, so these tests exercise the actual store write, not just the tool's own
words."""

from __future__ import annotations

from swim_coach.store import FileStore

from app.tools import TOOLS_SCHEMA, build_tool_handlers
from fakes import make_workout


def _h(athletes_dir):
    store = FileStore(base_dir=athletes_dir)
    return store, build_tool_handlers(store, slug="renee", expert_mode=False)


def _seed_workout(store, **overrides):
    athlete = store.load_athlete("renee")
    workout = make_workout(athlete_id=athlete.id, **overrides)
    store.save_workout("renee", workout)
    return workout


def test_muting_a_workout_thread_persists(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    workout = _seed_workout(store)

    result = h["set_workout_chat_muted"]({"workout_id": str(workout.id), "muted": True})

    assert result == {"workout_id": str(workout.id), "chat_ai_muted": True}
    assert store.get_workout("renee", workout.id).chat_ai_muted is True


def test_unmuting_a_workout_thread_persists(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    workout = _seed_workout(store, chat_ai_muted=True)

    result = h["set_workout_chat_muted"]({"workout_id": str(workout.id), "muted": False})

    assert result == {"workout_id": str(workout.id), "chat_ai_muted": False}
    assert store.get_workout("renee", workout.id).chat_ai_muted is False


def test_a_prefix_id_resolves_the_same_as_the_full_id(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    workout = _seed_workout(store)

    result = h["set_workout_chat_muted"]({"workout_id": str(workout.id)[:8], "muted": True})

    assert result["workout_id"] == str(workout.id)
    assert store.get_workout("renee", workout.id).chat_ai_muted is True


def test_unknown_workout_id_is_a_clean_error(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    result = h["set_workout_chat_muted"]({"workout_id": "00000000-0000-0000-0000-000000000000", "muted": True})
    assert "error" in result and "no workout matching id" in result["error"]


def test_missing_workout_id_is_a_clean_error(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    result = h["set_workout_chat_muted"]({"muted": True})
    assert "error" in result


def test_missing_or_non_boolean_muted_is_a_clean_error(athletes_dir) -> None:
    store, h = _h(athletes_dir)
    workout = _seed_workout(store)
    assert "error" in h["set_workout_chat_muted"]({"workout_id": str(workout.id)})
    assert "error" in h["set_workout_chat_muted"]({"workout_id": str(workout.id), "muted": "yes"})


def test_tool_is_registered_and_described_to_the_coach() -> None:
    names = {t["name"] for t in TOOLS_SCHEMA}
    assert "set_workout_chat_muted" in names
