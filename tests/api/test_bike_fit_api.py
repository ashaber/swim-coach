"""Bike-fit snapshots: routes, coach tool, context exclusion, old-data validity."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest
from fakes import auth_headers
from swim_coach.models import Athlete
from swim_coach.store import FileStore

from app.context import PERSONA_AND_RULES, build_per_request_context
from app.router_triage import HAIKU_TOOL_ALLOWLIST
from app.save_claims import READ_ONLY_TOOLS
from app.tools import TOOLS_SCHEMA, build_tool_handlers

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))
from bike_fit_synth import CX, MTB, Truth, tapes_for  # noqa: E402

URL = "/api/bike-fit?athlete=renee"


def body(truth: Truth = CX, name: str = "CX", **over) -> dict:
    payload = {
        "bike_name": name, "bike_type": truth.bike_type, "date": "2026-11-02", "note": "garage",
        "tire_front_psi": 28, "tire_rear_psi": 30,
        "inputs": {
            "tape": {k: round(v, 1) for k, v in tapes_for(truth).items()},
            "saddle_tilt_deg": truth.tilt_deg, "saddle_length_mm": truth.saddle_len, "crank_length_mm": 172.5,
            "string_length_mm": truth.string_len,
            "sit_point_from_tip_mm": round(math.dist(truth.st, truth.s), 1), "saddle_model": "Test saddle",
        },
    }
    payload.update(over)
    return payload


def post(client, payload) -> dict:
    res = client.post(URL, json=payload, headers=auth_headers())
    assert res.status_code == 200, res.text
    return res.json()


def test_routes_require_auth(client) -> None:
    assert client.get(URL).status_code == 401
    assert client.post(URL, json=body()).status_code == 401


def test_post_saves_raw_inputs_and_returns_derived_values(client, athletes_dir) -> None:
    snap = post(client, body())
    assert snap["derived"]["closure"]["status"] == "ok"
    sit = next(o for o in snap["derived"]["outputs"] if o["key"] == "setback_sit_mm")
    assert sit["value"] == pytest.approx(140.0, abs=0.5) and sit["sigma"] > 0
    stored = FileStore(base_dir=athletes_dir).load_athlete("renee").bike_fit_snapshots
    assert len(stored) == 1 and stored[0].inputs.tape.bb_fa == pytest.approx(round(tapes_for(CX)["bb_fa"], 1))
    assert "derived" not in stored[0].model_dump()


def test_get_lists_snapshots_with_defaults_and_limits(client) -> None:
    post(client, body())
    post(client, body(MTB, "Trail"))
    data = client.get(URL, headers=auth_headers()).json()
    assert [s["bike_name"] for s in data["snapshots"]] == ["CX", "Trail"]
    assert data["defaults"]["width_mm"]["mtb"]["fa"] == 110.0
    assert "does not recommend" in data["limits"]


@pytest.mark.parametrize("mutate", [
    lambda b: b.update(bike_type="gravel"),
    lambda b: b.update(bike_name="  "),
    lambda b: b["inputs"]["tape"].update(bb_fa=-4),
    lambda b: b["inputs"].pop("crank_length_mm"),
    lambda b: b["inputs"]["tape"].pop("fa_h"),
    lambda b: b["inputs"]["tape"].pop("bb_s"),
    lambda b: b["inputs"]["tape"].pop("bc_s"),
    lambda b: b["inputs"]["tape"].pop("ra_s"),
    lambda b: b["inputs"].pop("sit_point_from_tip_mm"),
    lambda b: b["inputs"].pop("saddle_model"),
    lambda b: b["inputs"].update(pedal_stack_source="measured"),
    lambda b: b["inputs"].pop("string_length_mm"),
    lambda b: b["inputs"].update(saddle_tilt_deg=80),
    lambda b: b["inputs"].update(seated_floor_bb_mm=300),
])
def test_invalid_input_is_an_error_object_and_saves_nothing(client, athletes_dir, mutate) -> None:
    payload = body()
    mutate(payload)
    res = client.post(URL, json=payload, headers=auth_headers())
    assert res.status_code == 422 and isinstance(res.json()["error"], str)
    assert FileStore(base_dir=athletes_dir).load_athlete("renee").bike_fit_snapshots == []


def test_triangle_failure_is_a_clean_error_and_saves_nothing(client, athletes_dir) -> None:
    payload = body()
    payload["inputs"]["tape"]["bb_bc"] = 100
    res = client.post(URL, json=payload, headers=auth_headers())
    assert res.status_code == 422 and "BB-BC" in res.json()["error"]
    assert FileStore(base_dir=athletes_dir).load_athlete("renee").bike_fit_snapshots == []


def test_compare_two_snapshots_flags_error_exceedance(client) -> None:
    a = post(client, body(CX, "CX"))
    shifted = Truth(**{**MTB.__dict__})
    b = post(client, body(shifted, "Trail"))
    res = client.get(f"/api/bike-fit/compare?athlete=renee&a={a['id']}&b={b['id']}", headers=auth_headers())
    assert res.status_code == 200
    rows = {r["key"]: r for r in res.json()["unweighted"]}
    assert rows["setback_tip_mm"]["diff"] == pytest.approx(85.0, abs=1.5)
    assert rows["setback_tip_mm"]["exceeds_error"] is True
    body_ = res.json()
    assert body_["saddle"]["same"] is True and body_["crank"]["diff_mm"] == 0 and body_["pedal_stack"] is None
    assert client.get(f"/api/bike-fit/compare?athlete=renee&a={a['id']}&b=nope", headers=auth_headers()).status_code == 404


def test_snapshot_is_immutable_except_retire_flag_and_never_deleted(client, athletes_dir) -> None:
    snap = post(client, body())
    res = client.patch(f"/api/bike-fit/{snap['id']}?athlete=renee", json={"retired": True, "bike_name": "x"},
                       headers=auth_headers())
    assert res.status_code == 200 and res.json()["retired"] is True
    stored = FileStore(base_dir=athletes_dir).load_athlete("renee").bike_fit_snapshots[0]
    assert stored.retired is True and stored.bike_name == "CX"
    assert client.patch(f"/api/bike-fit/{snap['id']}?athlete=renee", json={}, headers=auth_headers()).status_code == 422
    assert client.delete(f"/api/bike-fit/{snap['id']}?athlete=renee", headers=auth_headers()).status_code == 405
    assert client.patch("/api/bike-fit/not-an-id?athlete=renee", json={"retired": True},
                        headers=auth_headers()).status_code == 404


def test_profile_patch_cannot_overwrite_snapshots(client, athletes_dir) -> None:
    post(client, body())
    res = client.patch("/api/athlete?athlete=renee", json={"bike_fit_snapshots": []}, headers=auth_headers())
    assert res.status_code == 200
    assert len(FileStore(base_dir=athletes_dir).load_athlete("renee").bike_fit_snapshots) == 1


def test_old_athlete_data_validates_with_no_snapshots(athletes_dir) -> None:
    athlete = FileStore(base_dir=athletes_dir).load_athlete("renee")
    assert athlete.bike_fit_snapshots == []
    dumped = athlete.model_dump(mode="json")
    dumped.pop("bike_fit_snapshots")
    assert Athlete.model_validate(dumped).bike_fit_snapshots == []


def test_snapshots_are_not_in_the_per_request_context(client, athletes_dir) -> None:
    post(client, body(name="zzFitBike"))
    store = FileStore(base_dir=athletes_dir)
    text = build_per_request_context(store, "renee", expert_mode=False)
    assert "zzFitBike" not in text and "bike_fit_snapshots" not in text


def test_tool_is_read_only_registered_and_tightly_described() -> None:
    assert "get_bike_fit" in READ_ONLY_TOOLS and "get_bike_fit" in HAIKU_TOOL_ALLOWLIST
    tool = next(t for t in TOOLS_SCHEMA if t["name"] == "get_bike_fit")
    assert len(tool["description"]) < 600 and "does not" in tool["description"].lower()


def test_tool_returns_values_sigma_comparison_and_limits(client, athletes_dir) -> None:
    post(client, body(CX, "CX"))
    post(client, body(MTB, "Trail"))
    h = build_tool_handlers(FileStore(base_dir=athletes_dir), slug="renee", expert_mode=False)
    res = h["get_bike_fit"]({})
    assert {b["bike_name"] for b in res["snapshots"]} == {"CX", "Trail"}
    first = res["snapshots"][0]
    assert first["closure"] == "ok" and first["values"]["setback_tip_mm"]["pm"] > 0
    assert "does not recommend" in res["limits"]
    assert first["coordinates"]["s"]["x"] < 0 and first["saddle_model"] == "Test saddle"
    cmp_ = h["get_bike_fit"]({"compare_a": "CX", "compare_b": "trail"})
    row = next(r for r in cmp_["comparison"]["unweighted"] if r["key"] == "setback_tip_mm")
    assert row["diff"] == pytest.approx(85.0, abs=1.5) and row["exceeds_error"] is True
    assert cmp_["comparison"]["saddle_same"] is True and cmp_["comparison"]["crank_diff_mm"] == 0
    assert h["get_bike_fit"]({"bike": "nope"})["snapshots"] == []
    assert "error" in h["get_bike_fit"]({"compare_a": "CX", "compare_b": "missing"})


def test_prompt_guidance_is_short_and_refers_to_the_fitter() -> None:
    assert "get_bike_fit" in PERSONA_AND_RULES
    line = next(ln for ln in PERSONA_AND_RULES.splitlines() if "get_bike_fit" in ln)
    assert "fitter" in PERSONA_AND_RULES[PERSONA_AND_RULES.index(line):][:900]


def _setup_entry(kind: str, day: str, text: str, front: float | None = None, rear: float | None = None):
    import uuid
    from datetime import date

    from swim_coach.models import SetupLogEntry

    return SetupLogEntry(id=uuid.uuid4(), date=date.fromisoformat(day), kind=kind, text=text,
                         pressure_front_psi=front, pressure_rear_psi=rear)


def _add_setup(athletes_dir, *entries) -> None:
    store = FileStore(base_dir=athletes_dir)
    profile = store.load_athlete("renee")
    profile.setup_log.extend(entries)
    store.save_athlete(profile)


def test_get_returns_only_bike_setup_notes_newest_first(client, athletes_dir) -> None:
    _add_setup(
        athletes_dir,
        _setup_entry("bike_setup", "2025-05-01", "Professional fit, saddle height 75.2 cm", 18, 19),
        _setup_entry("clothing", "2026-10-01", "knee warmers"),
        _setup_entry("tires", "2026-09-01", "tubeless 2.4", 20, 22),
        _setup_entry("bike_setup", "2026-03-01", "New cleats"),
    )
    notes = client.get(URL, headers=auth_headers()).json()["setup_notes"]
    assert [n["date"] for n in notes] == ["2026-03-01", "2025-05-01"]
    assert set(notes[0]) == {"id", "date", "text", "pressure_front_psi", "pressure_rear_psi"}
    assert (notes[1]["pressure_front_psi"], notes[1]["pressure_rear_psi"]) == (18, 19)
    assert notes[0]["pressure_front_psi"] is None


def test_get_setup_notes_empty_when_none(client, athletes_dir) -> None:
    _add_setup(athletes_dir, _setup_entry("clothing", "2026-10-01", "vest"))
    assert client.get(URL, headers=auth_headers()).json()["setup_notes"] == []


def test_tool_includes_setup_notes_even_without_snapshots(athletes_dir) -> None:
    _add_setup(
        athletes_dir,
        _setup_entry("bike_setup", "2025-05-01", "Professional fit, crank 170 mm", 18, 19),
        _setup_entry("tires", "2026-09-01", "tubeless 2.4", 20, 22),
    )
    h = build_tool_handlers(FileStore(base_dir=athletes_dir), slug="renee", expert_mode=False)
    res = h["get_bike_fit"]({})
    assert res["snapshots"] == []
    assert res["setup_notes"] == [{"date": "2025-05-01", "text": "Professional fit, crank 170 mm",
                                   "pressure_front_psi": 18, "pressure_rear_psi": 19}]


def test_tool_description_mentions_fitter_notes_and_stays_short() -> None:
    tool = next(t for t in TOOLS_SCHEMA if t["name"] == "get_bike_fit")
    assert "fit notes" in tool["description"] and len(tool["description"]) < 800
