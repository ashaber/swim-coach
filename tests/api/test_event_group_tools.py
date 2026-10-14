"""Event group coach tools: round trip, peak override, disband, per-athlete scoping."""

from __future__ import annotations

from swim_coach.store import FileStore

from app.save_claims import WRITE_TOOLS
from app.tools import build_tool_handlers


def _two_races(handlers, tag: str) -> tuple[str, str]:
    a, b = f"Sat race [{tag}]", f"Sun race [{tag}]"
    for name, day in ((a, "2027-03-06"), (b, "2027-03-07")):
        r = handlers["create_event"](
            {"name": name, "event_date": day, "priority": "A", "primary_sport": "bike",
             "target_metric": "duration_min", "target_value": 60}
        )
        assert r["created"], r
    return a, b


def test_group_round_trip_peak_override_and_disband(athletes_dir, run_tag) -> None:
    store = FileStore(base_dir=athletes_dir)
    handlers = build_tool_handlers(store, slug="renee", expert_mode=False)
    a, b = _two_races(handlers, run_tag)
    name = f"Weekend [{run_tag}]"

    made = handlers["set_event_group"](
        {"group_name": name, "group_type": "double_header", "event_names": [a, b]}
    )
    assert made["updated"] and made["peak"] == a and made["span"] == ["2027-03-06", "2027-03-07"]

    # persisted in the events store, read back through a fresh store
    read = build_tool_handlers(FileStore(base_dir=athletes_dir), slug="renee", expert_mode=False)["get_event_groups"]({})
    assert [g["group_name"] for g in read["groups"]] == [name]

    moved = handlers["set_event_group"](
        {"group_name": name, "group_type": "double_header", "event_names": [a, b], "peak_event_name": b}
    )
    assert moved["peak"] == b

    assert handlers["set_event_group"]({"group_name": name, "disband": True})["disbanded"] is True
    assert handlers["get_event_groups"]({}) == {"groups": []}
    assert {e.name for e in store.load_events("renee")} >= {a, b}  # events kept


def test_group_tool_errors_and_athlete_scoping(athletes_dir, run_tag) -> None:
    store = FileStore(base_dir=athletes_dir)
    renee = build_tool_handlers(store, slug="renee", expert_mode=False)
    andrew = build_tool_handlers(store, slug="andrew", expert_mode=False)
    a, b = _two_races(renee, run_tag)
    assert "error" in renee["set_event_group"]({"group_name": "G", "group_type": "omnium", "event_names": [a]})
    assert "error" in renee["set_event_group"]({"group_name": "G", "group_type": "bogus", "event_names": [a, b]})
    assert "error" in renee["set_event_group"](
        {"group_name": "G", "group_type": "omnium", "event_names": [a, b], "peak_event_name": "other"}
    )
    # another athlete cannot group (or see) renee's events
    assert "error" in andrew["set_event_group"]({"group_name": "G", "group_type": "omnium", "event_names": [a, b]})
    renee["set_event_group"]({"group_name": "G", "group_type": "omnium", "event_names": [a, b]})
    assert andrew["get_event_groups"]({}) == {"groups": []}


def test_set_event_group_counts_as_a_write_tool() -> None:
    assert WRITE_TOOLS["set_event_group"] == "updated"
