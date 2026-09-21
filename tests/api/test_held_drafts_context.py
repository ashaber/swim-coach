"""The coach cannot remember tool results between turns (the client replays only text), so
the server must tell it what is waiting for the athlete's yes -- and how to write it -- on
every request. Also: the prompt must not tell the coach it cannot write plans."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from swim_coach.models import Event
from swim_coach.plan import scaffold_macro
from swim_coach.store import FileStore

from app.context import PERSONA_AND_RULES, build_per_request_context
from app.tools import build_tool_handlers

SECTION = "Drafts waiting for the athlete's yes"
TEMPLATE = {"tue": [{"kind": "bike", "role": "hard"}], "sun": [{"kind": "bike", "role": "endurance"}]}


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
    h["set_weekly_template"]({"template": TEMPLATE, "confirm": True})
    ws = next(b for b in macro.blocks if b.name in ("build", "peak", "base")).start_date + timedelta(weeks=1)
    return store, h, _iso(ws)


def _ctx(store):
    return build_per_request_context(store, "renee", expert_mode=False)


def test_no_drafts_means_no_section(athletes_dir) -> None:
    store, h, iso = _setup(athletes_dir)
    assert SECTION not in _ctx(store)


def test_a_held_week_draft_is_shown_with_exactly_how_to_write_it(athletes_dir) -> None:
    store, h, iso = _setup(athletes_dir)
    draft = h["replace_week_plan"]({"iso_week": iso})

    text = _ctx(store)

    assert SECTION in text
    assert draft["draft_id"] in text and iso in text
    assert '"confirm": true' in text and "replace_week_plan" in text
    assert "do NOT say you cannot write it" in text


def test_the_section_disappears_once_the_draft_is_written(athletes_dir) -> None:
    store, h, iso = _setup(athletes_dir)
    draft = h["replace_week_plan"]({"iso_week": iso})
    assert SECTION in _ctx(store)

    h["replace_week_plan"]({"iso_week": iso, "confirm": True, "draft_id": draft["draft_id"]})

    assert SECTION not in _ctx(store)


def test_a_stale_draft_is_not_offered(athletes_dir) -> None:
    store, h, iso = _setup(athletes_dir)
    h["replace_week_plan"]({"iso_week": iso})
    old = store.load_week_draft("renee", iso).model_copy(update={"drafted_at": datetime.now(timezone.utc) - timedelta(days=2)})
    store.save_week_draft("renee", old)
    assert SECTION not in _ctx(store)


def test_an_adaptation_draft_says_to_write_it_with_replace_week_plan(athletes_dir) -> None:
    store = FileStore(base_dir=athletes_dir)
    h = build_tool_handlers(store, slug="renee", expert_mode=False)
    draft = h["propose_adaptation"]({"iso_week": "2026-W30"})
    text = _ctx(store)
    assert draft["draft_id"] in text and "`replace_week_plan`" in text


def test_a_macro_draft_is_described(athletes_dir) -> None:
    (athletes_dir / "renee" / "plan" / "macro.yaml").unlink()
    store = FileStore(base_dir=athletes_dir)
    h = build_tool_handlers(store, slug="renee", expert_mode=False)
    draft = h["replace_macro_plan"]({"event_name": "UltraSwim 33.3 Greece (Skopelos) — single-day 33.3 km continuous",
                                     "current_weekly_volume_m": 18000, "start_date": "2026-01-05"})
    text = _ctx(store)
    assert draft["draft_id"] in text and "MACRO plan" in text and "replace_macro_plan" in text


def test_the_prompt_no_longer_tells_the_coach_it_cannot_write_plans() -> None:
    text = " ".join(PERSONA_AND_RULES.split())
    assert "you cannot finalize one" not in text
    assert "you never persist a plan change yourself" not in text
    assert "run /adapt to finalize" not in text


def test_the_prompt_makes_the_coach_write_the_agreed_plan_and_forbids_excuses() -> None:
    text = " ".join(PERSONA_AND_RULES.split())
    assert "once the athlete agrees, YOU write it" in text
    assert "Never tell the athlete you cannot write" in text
    assert "state the tool's actual message" in text


def test_the_prompt_teaches_flex_rides_interval_choice_and_the_per_week_switch() -> None:
    text = " ".join(PERSONA_AND_RULES.split())
    assert "`flex`" in text and "interval_type" in text and "NO limit on interval days" in text
    assert "set_schedule_preferences" not in text
    assert "Never tell the athlete a ride can only be one thing" in text
