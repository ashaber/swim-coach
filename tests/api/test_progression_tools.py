"""Progression tools (PROGRESSION_TOOLS_ENABLED, default off): the read-only `get_progression` tool,
compiling session entries from a `rung`, and the progression findings in the week check. Real engine,
isolated athlete tree, no LLM, no network."""

from __future__ import annotations

import dataclasses
import json
import uuid
from datetime import timedelta

import pytest
from fakes import auth_headers, make_final_message, make_text_block
from swim_coach.athlete_time import athlete_today
from swim_coach.garmin_export import to_garmin_fit_workout
from swim_coach.models import IntervalEffort, WorkoutAnalytics, WorkoutIntervals, WorkoutStructure, Workout
from swim_coach.formatting import iso_week_str
from swim_coach.store import FileStore
from swim_coach.workout_builders import compile_workout, parse_rung

from app import progression_tools
from app.config import Settings
from app.save_claims import NON_PLAN_OR_READ_ONLY, PROGRESSION_READ_ONLY_TOOLS, READ_ONLY_TOOLS
from app.router_triage import HAIKU_TOOL_ALLOWLIST
from app.tools import SESSION_ENTRY_SCHEMA, TOOLS_SCHEMA, build_tool_handlers, tools_schema


def _seed(athletes_dir):
    """renee with an FTP and two real threshold sessions (3 x 10 min, 5 min easy between)."""
    store = FileStore(base_dir=athletes_dir)
    athlete = store.load_athlete("renee").model_copy(update={"ftp_watts": 250.0})
    store.save_athlete(athlete)
    today = athlete_today(athlete)
    for days_ago in (3, 10):
        efforts = [IntervalEffort(n=i + 1, start_s=600 + i * 900, duration_s=600, avg_w=250, verdict="ok") for i in range(3)]
        intervals = WorkoutIntervals(efforts_detected=3, detection_basis="power", reps_completed=3,
                                     reps_in_band_pct=100.0, efforts=efforts)
        store.save_workout("renee", Workout(
            id=uuid.uuid4(), athlete_id=athlete.id, date=today - timedelta(days=days_ago), sport="bike", source="fit",
            distance_m=0, duration_min=60, analytics=WorkoutAnalytics(intervals=intervals)))
    return store, athlete, today


def _handlers(store, *, enabled: bool):
    return build_tool_handlers(store, slug="renee", expert_mode=False, progression_tools=enabled)


def _entry(day, **fields):
    base = {"date": day.isoformat(), "sport": "bike", "purpose": "threshold work", "title": "Threshold"}
    base.update(fields)
    return base


# --- config, schema, handlers: flag off is unchanged ---------------------------------------------


def test_setting_defaults_off_and_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("API_TOKEN", "some-token")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id.apps.googleusercontent.com")
    monkeypatch.delenv("PROGRESSION_TOOLS_ENABLED", raising=False)
    assert Settings.from_env().progression_tools_enabled is False
    monkeypatch.setenv("PROGRESSION_TOOLS_ENABLED", "true")
    assert Settings.from_env().progression_tools_enabled is True


def test_flag_off_schema_is_byte_identical_and_has_no_new_surface(athletes_dir) -> None:
    assert tools_schema(False) is TOOLS_SCHEMA
    assert json.dumps(tools_schema(False)) == json.dumps(TOOLS_SCHEMA)
    assert "get_progression" not in {t["name"] for t in TOOLS_SCHEMA}
    assert not {"rung", "archetype"} & set(SESSION_ENTRY_SCHEMA["properties"])
    assert "get_progression" not in build_tool_handlers(FileStore(base_dir=athletes_dir), slug="renee", expert_mode=False)
    assert "get_progression" not in _handlers(FileStore(base_dir=athletes_dir), enabled=False)


def test_flag_on_schema_adds_the_tool_and_session_fields_and_leaves_the_rest(athletes_dir) -> None:
    on = tools_schema(True)
    by_name = {t["name"]: t for t in on}
    assert [t["name"] for t in on][:-1] == [t["name"] for t in TOOLS_SCHEMA]
    assert on[-1]["name"] == "get_progression"
    for tool, key in (("author_week_plan", "sessions"), ("merge_week_plan", "proposed_sessions")):
        props = by_name[tool]["input_schema"]["properties"][key]["items"]["properties"]
        assert {"rung", "archetype"} <= set(props)
    unchanged = [t["name"] for t in TOOLS_SCHEMA if t["name"] not in ("author_week_plan", "merge_week_plan")]
    assert all(by_name[n] == next(t for t in TOOLS_SCHEMA if t["name"] == n) for n in unchanged)
    assert "get_progression" in _handlers(FileStore(base_dir=athletes_dir), enabled=True)


def test_added_schema_stays_small() -> None:
    added = len(json.dumps(tools_schema(True))) - len(json.dumps(TOOLS_SCHEMA))
    tool = json.dumps(progression_tools.GET_PROGRESSION_TOOL)
    assert len(tool.split()) < 120
    assert added < 2200, added


def test_get_progression_is_read_only_and_not_in_light_or_haiku_lists() -> None:
    assert "get_progression" in PROGRESSION_READ_ONLY_TOOLS
    assert "get_progression" not in READ_ONLY_TOOLS | NON_PLAN_OR_READ_ONLY
    assert "get_progression" not in HAIKU_TOOL_ALLOWLIST


def test_route_sends_the_flag_gated_schema(app, client, fake_claude_chat_factory) -> None:
    def ask() -> list[dict]:
        chat = fake_claude_chat_factory([(["ok"], make_final_message([make_text_block("ok")], "end_turn"))])
        body = {"message": "plan my week", "history": [], "athlete": "renee", "expert_mode": False}
        assert client.post("/api/chat", json=body, headers=auth_headers()).status_code == 200
        return chat.client.messages.calls[0]["tools"]

    assert json.dumps(ask()) == json.dumps(TOOLS_SCHEMA)
    app.state.settings = dataclasses.replace(app.state.settings, progression_tools_enabled=True)
    assert "get_progression" in {t["name"] for t in ask()}


# --- get_progression ----------------------------------------------------------------------------


def test_get_progression_is_compact_and_has_the_agreed_shape(athletes_dir) -> None:
    store, athlete, today = _seed(athletes_dir)
    result = _handlers(store, enabled=True)["get_progression"]({})
    assert "error" not in result
    row = next(r for r in result["kinds"] if r["kind"] == "threshold")
    assert set(row) == {"sport", "kind", "verdict", "confidence", "reference", "days_since_last", "why",
                        "candidates", "also_delivered", "rebase", "retest_suggested"}
    assert row["sport"] == "bike" and row["reference"] == "3x10 min/5 min Z4"
    assert 1 <= len(row["candidates"]) <= 4 and set(row["candidates"][0]) == {"rung", "change"}
    assert row["why"].startswith("Last session did") and row["days_since_last"] == 3
    assert result["iso_week"] == iso_week_str(today)
    assert len(json.dumps(result)) < 3000
    assert len(json.dumps(result)) > 100


def test_get_progression_week_review_counts_and_sport_filter(athletes_dir) -> None:
    store, athlete, today = _seed(athletes_dir)
    handlers = _handlers(store, enabled=True)
    result = handlers["get_progression"]({"sport": "bike"})
    assert set(result["week"]["counts"]) == {"planned_done", "planned_missed", "remaining", "unplanned", "substituted"}
    assert isinstance(result["week"]["impacts"], list)
    assert handlers["get_progression"]({"sport": "swim"})["kinds"] == []


def test_get_progression_rejects_a_bad_week(athletes_dir) -> None:
    store, _, _ = _seed(athletes_dir)
    assert "error" in _handlers(store, enabled=True)["get_progression"]({"iso_week": "nonsense"})


# --- rung in session entries --------------------------------------------------------------------


def test_rung_compiles_the_session_and_round_trips_through_garmin_export(athletes_dir) -> None:
    store, athlete, today = _seed(athletes_dir)
    day = today + timedelta(days=2)
    entry = _entry(day, rung="2x12 min/5 min Z4")
    result = _handlers(store, enabled=True)["author_week_plan"]({"iso_week": iso_week_str(day), "sessions": [entry]})
    assert "error" not in result, result
    session = result["sessions"][0]
    assert session["has_structured"] is True and session["duration_min"] > 24
    assert "12" in session["structure"]
    assert result["compiled"][0]["rung"] == "2x12 min/5 min Z4"
    assert result["compiled"][0]["adjustments"] == []
    held = store.list_week_ids("renee")  # nothing persisted by a draft
    assert iso_week_str(day) not in held
    # the held draft carries the compiled IR, which exports to a watch workout
    draft = _handlers(store, enabled=True)["author_week_plan"]({"iso_week": iso_week_str(day), "sessions": [entry]})
    confirmed = _handlers(store, enabled=True)["author_week_plan"](
        {"iso_week": iso_week_str(day), "sessions": [entry], "confirm": True, "draft_id": draft["draft_id"]}
    )
    saved = store.load_week("renee", iso_week_str(day))
    structured = saved.sessions[0].structured
    assert isinstance(structured, WorkoutStructure) and confirmed["persisted"] is True
    assert to_garmin_fit_workout(structured, "bike", "Threshold")[8:12] == b".FIT"


def test_rung_keeps_the_coachs_purpose_title_and_kind(athletes_dir) -> None:
    store, _, today = _seed(athletes_dir)
    day = today + timedelta(days=2)
    entry = _entry(day, rung="2x12 min/5 min Z4", purpose="own purpose", title="Own title", kind="workout")
    result = _handlers(store, enabled=True)["author_week_plan"]({"iso_week": iso_week_str(day), "sessions": [entry]})
    assert result["sessions"][0]["purpose"] == "own purpose"
    assert result["sessions"][0]["kind"] == "workout"


def test_adjustments_are_returned_per_session(athletes_dir, monkeypatch) -> None:
    store, _, today = _seed(athletes_dir)
    day = today + timedelta(days=2)
    real = progression_tools.compile_workout

    def adjusted(intent, athlete):
        compiled = real(intent, athlete)
        return compiled.model_copy(update={"adjustments": ["rest rounded to 5 min"]})

    monkeypatch.setattr(progression_tools, "compile_workout", adjusted)
    result = _handlers(store, enabled=True)["author_week_plan"](
        {"iso_week": iso_week_str(day), "sessions": [_entry(day, rung="2x12 min/5 min Z4")]}
    )
    assert result["compiled"][0]["adjustments"] == ["rest rounded to 5 min"]
    assert result["compiled"][0]["date"] == day.isoformat()


def test_rung_with_an_explicit_structure_is_a_named_conflict(athletes_dir) -> None:
    store, _, today = _seed(athletes_dir)
    day = today + timedelta(days=2)
    entry = _entry(day, rung="2x12 min/5 min Z4", structure="3 x 10 min hard")
    result = _handlers(store, enabled=True)["author_week_plan"]({"iso_week": iso_week_str(day), "sessions": [entry]})
    assert "rung" in result["error"] and "structure" in result["error"] and "sessions[0]" in result["error"]


def test_a_bad_rung_names_the_canonical_format(athletes_dir) -> None:
    store, _, today = _seed(athletes_dir)
    day = today + timedelta(days=2)
    result = _handlers(store, enabled=True)["author_week_plan"](
        {"iso_week": iso_week_str(day), "sessions": [_entry(day, rung="hard 3 by 10")]}
    )
    assert "sessions[0]" in result["error"] and "2x8 min/4 min Z3" in result["error"]


def test_an_archetype_alone_builds_from_duration(athletes_dir) -> None:
    store, _, today = _seed(athletes_dir)
    day = today + timedelta(days=2)
    result = _handlers(store, enabled=True)["author_week_plan"](
        {"iso_week": iso_week_str(day), "sessions": [_entry(day, archetype="no_such_builder", duration_min=60)]}
    )
    assert "no_such_builder" in result["error"] and "available" in result["error"]


def test_merge_week_plan_compiles_proposed_session_rungs(athletes_dir) -> None:
    store, _, today = _seed(athletes_dir)
    day = today + timedelta(days=2)
    iso = iso_week_str(day)
    handlers = _handlers(store, enabled=True)
    draft = handlers["author_week_plan"]({"iso_week": iso, "sessions": [_entry(day + timedelta(days=1), sport="bike", rung="2x8 min/4 min Z3")]})
    handlers["author_week_plan"]({"iso_week": iso, "sessions": [_entry(day + timedelta(days=1), rung="2x8 min/4 min Z3")],
                                  "confirm": True, "draft_id": draft["draft_id"]})
    merged = handlers["merge_week_plan"]({"iso_week": iso, "proposed_sessions": [_entry(day, rung="2x12 min/5 min Z4")]})
    assert "error" not in merged, merged
    assert merged["compiled"][0]["rung"] == "2x12 min/5 min Z4"


def test_flag_off_rung_is_ignored_exactly_like_an_unknown_field(athletes_dir) -> None:
    store, _, today = _seed(athletes_dir)
    day = today + timedelta(days=2)
    iso = iso_week_str(day)
    plain = _entry(day, duration_min=60)
    with_rung = _entry(day, duration_min=60, rung="2x12 min/5 min Z4")
    a = _handlers(store, enabled=False)["author_week_plan"]({"iso_week": iso, "sessions": [plain]})
    b = _handlers(store, enabled=False)["author_week_plan"]({"iso_week": iso, "sessions": [with_rung]})
    for r in (a, b):
        r["sessions"][0].pop("id")
        r.pop("draft_id", None)
        r["report"].pop("id", None)
    assert a == b and "compiled" not in b


# --- progression findings in the week check -------------------------------------------------------


def _big_week(today):
    day = today + timedelta(days=2)
    return iso_week_str(day), [_entry(day, rung="2x30 min/2 min Z4")]


def _ids(result) -> list[str]:
    report = result["report"] if "report" in result else result["week"]
    return [f["id"] for f in report["findings"]]


def test_progression_findings_join_the_author_week_draft_when_on_only(athletes_dir) -> None:
    store, _, today = _seed(athletes_dir)
    iso, sessions = _big_week(today)
    on = _handlers(store, enabled=True)["author_week_plan"]({"iso_week": iso, "sessions": sessions})
    assert any(i.startswith("progression-") for i in _ids(on)), _ids(on)
    # flag off: the same authored structure draws none (the entry must carry its own structure)
    athlete = store.load_athlete("renee")
    built = compile_workout(parse_rung("2x30 min/2 min Z4", "bike"), athlete)
    plain = {k: v for k, v in sessions[0].items() if k != "rung"}
    plain.update(duration_min=built.duration_min, structured=built.structured.model_dump(mode="json"))
    off = _handlers(store, enabled=False)["author_week_plan"]({"iso_week": iso, "sessions": [plain]})
    assert not any(i.startswith(("progression-", "unplanned-")) for i in _ids(off)), _ids(off)


def test_progression_findings_join_check_plan_when_on_only(athletes_dir) -> None:
    store, _, today = _seed(athletes_dir)
    iso, sessions = _big_week(today)
    handlers = _handlers(store, enabled=True)
    draft = handlers["author_week_plan"]({"iso_week": iso, "sessions": sessions})
    handlers["author_week_plan"]({"iso_week": iso, "sessions": sessions, "confirm": True, "draft_id": draft["draft_id"]})
    on = handlers["check_plan"]({"iso_week": iso})
    off = _handlers(store, enabled=False)["check_plan"]({"iso_week": iso})
    assert any(i.startswith("progression-") for i in _ids(on)), on
    assert not any(i.startswith("progression-") for i in _ids(off))


# --- failure isolation --------------------------------------------------------------------------


class _BrokenWorkouts(FileStore):
    def list_workouts(self, slug, *, since=None):  # noqa: ANN001
        raise OSError("disk gone")


def test_a_failing_progression_build_leaves_the_week_check_as_before_and_warns(athletes_dir, capsys) -> None:
    store, _, today = _seed(athletes_dir)
    iso, sessions = _big_week(today)
    plain = {k: v for k, v in sessions[0].items() if k != "rung"} | {"duration_min": 60}
    baseline = _handlers(store, enabled=False)["author_week_plan"]({"iso_week": iso, "sessions": [plain]})
    broken = _BrokenWorkouts(base_dir=athletes_dir)
    capsys.readouterr()
    result = build_tool_handlers(broken, slug="renee", expert_mode=False, progression_tools=True)["author_week_plan"](
        {"iso_week": iso, "sessions": [plain]}
    )
    assert "error" not in result
    assert _ids(result) == _ids(baseline)
    warnings = [json.loads(line) for line in capsys.readouterr().out.splitlines() if '"level": "warn"' in line]
    assert [w["msg"] for w in warnings if "progression" in w["msg"]] == ["progression inputs unavailable"]
