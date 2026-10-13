"""Race-day checklist routes + race-week item ticks (backend/app/routes/race_day.py)."""

from __future__ import annotations

import uuid

import pytest

from fakes import auth_headers

TEMPLATE = {
    "sections": [
        {"id": "kit", "title": "Kit", "items": [
            {"id": "helmet", "text": "Helmet", "tags": [], "default_checked": True},
            {"id": "covers", "text": "Shoe covers", "tags": ["wet"], "default_checked": False},
        ]},
    ],
    "timeline": [
        {"id": "wake", "label": "Wake up", "day": "race", "offset_min": -300},
        {"id": "start", "label": "Start", "day": "race", "offset_min": 0, "is_start": True},
    ],
}


def _put_template(client, athlete="renee"):
    return client.put(f"/api/race-checklist/template?athlete={athlete}", json=TEMPLATE, headers=auth_headers())


def _open(client, run_tag, date="2026-10-17", athlete="renee"):
    return client.get(
        f"/api/race-day?athlete={athlete}&date={date}&session_id=s-{run_tag}&name=Day%201",
        headers=auth_headers(),
    )


def test_routes_require_auth(client) -> None:
    assert client.get("/api/race-checklist/template?athlete=renee").status_code == 401
    assert client.put("/api/race-checklist/template?athlete=renee", json=TEMPLATE).status_code == 401
    assert client.get("/api/race-day?athlete=renee&date=2026-10-17").status_code == 401
    assert client.patch("/api/race-day/x/items?athlete=renee", json={"states": {"a": True}}).status_code == 401
    assert client.patch("/api/race-day/x?athlete=renee", json={}).status_code == 401
    assert client.patch("/api/plan/weeks/2026-W42/race-week-items/x?athlete=renee", json={"done": True}).status_code == 401


def test_template_roundtrip_and_validation(client) -> None:
    empty = client.get("/api/race-checklist/template?athlete=renee", headers=auth_headers())
    assert empty.status_code == 200 and empty.json()["sections"] == []
    assert _put_template(client).status_code == 200
    got = client.get("/api/race-checklist/template?athlete=renee", headers=auth_headers()).json()
    assert got["sections"][0]["items"][1]["tags"] == ["wet"]
    bad = client.put(
        "/api/race-checklist/template?athlete=renee",
        json={"timeline": [{"id": "x", "label": "x", "day": "eve"}]},
        headers=auth_headers(),
    )
    assert bad.status_code == 422


def test_open_without_template_is_404(client, run_tag) -> None:
    resp = _open(client, run_tag)
    assert resp.status_code == 404 and "error" in resp.json()


def test_open_creates_from_template_once(client, run_tag) -> None:
    _put_template(client)
    first = _open(client, run_tag).json()
    assert first["checked"] == ["helmet"] and first["name"] == "Day 1"
    assert [t["id"] for t in first["timeline"]] == ["wake", "start"]
    again = _open(client, run_tag).json()
    assert again["id"] == first["id"]
    # a second race date under the same weekend is its own plan
    other = _open(client, run_tag + "b", date="2026-10-18").json()
    assert other["id"] != first["id"]
    # a replaced week gives the session a new id: same date still finds the same plan
    moved = client.get("/api/race-day?athlete=renee&date=2026-10-17&session_id=new-id", headers=auth_headers()).json()
    assert moved["id"] == first["id"] and moved["session_id"] == "new-id"


def test_check_uncheck_is_idempotent_and_replay_safe(client, run_tag) -> None:
    _put_template(client)
    plan = _open(client, run_tag).json()
    url = f"/api/race-day/{plan['id']}/items?athlete=renee"
    for _ in range(2):
        r = client.patch(url, json={"states": {"covers": True, "nope": True}}, headers=auth_headers())
        assert r.status_code == 200 and r.json()["checked"] == ["helmet", "covers"]
    # replaying an old queue (check then uncheck, as one ordered batch) converges
    r = client.patch(url, json={"states": {"covers": False}}, headers=auth_headers())
    r = client.patch(url, json={"states": {"covers": False}}, headers=auth_headers())
    assert r.json()["checked"] == ["helmet"]
    persisted = _open(client, run_tag).json()
    assert persisted["checked"] == ["helmet"]


def test_patch_start_time_and_tags(client, run_tag) -> None:
    _put_template(client)
    plan = _open(client, run_tag).json()
    url = f"/api/race-day/{plan['id']}?athlete=renee"
    r = client.patch(url, json={"start_time": "09:30", "active_tags": [" Wet ", "mud"]}, headers=auth_headers())
    assert r.status_code == 200
    assert r.json()["start_time"] == "09:30" and r.json()["active_tags"] == ["wet", "mud"]
    assert client.patch(url, json={"start_time": "9:30"}, headers=auth_headers()).status_code == 422
    cleared = client.patch(url, json={"start_time": None}, headers=auth_headers()).json()
    assert cleared["start_time"] is None and cleared["active_tags"] == ["wet", "mud"]
    assert client.patch(f"/api/race-day/missing?athlete=renee", json={}, headers=auth_headers()).status_code == 404


def test_race_week_item_toggle(client, app_env) -> None:
    from swim_coach.store import FileStore

    store = FileStore(base_dir=app_env)
    week = store.load_week("renee", store.list_week_ids("renee")[0])
    week.race_week_checklist = []
    from swim_coach.models import RaceWeekChecklistItem

    week.race_week_checklist = [
        RaceWeekChecklistItem(date="2026-10-14", category="bike", label="Clean bike"),
        RaceWeekChecklistItem(date="2026-10-15", category="gear", label="Pack kit"),
    ]
    store.save_week("renee", week)
    reloaded = store.load_week("renee", week.iso_week)
    item_id = reloaded.race_week_checklist[1].id
    assert item_id

    url = f"/api/plan/weeks/{week.iso_week}/race-week-items/{item_id}?athlete=renee"
    for _ in range(2):
        r = client.patch(url, json={"done": True}, headers=auth_headers())
        assert r.status_code == 200 and r.json()["done"] is True
    after = store.load_week("renee", week.iso_week)
    assert [i.done for i in after.race_week_checklist] == [False, True]
    assert client.patch(url, json={"done": False}, headers=auth_headers()).json()["done"] is False
    missing = client.patch(
        f"/api/plan/weeks/{week.iso_week}/race-week-items/{uuid.uuid4().hex}?athlete=renee",
        json={"done": True},
        headers=auth_headers(),
    )
    assert missing.status_code == 404
    nowk = client.patch(
        "/api/plan/weeks/2099-W01/race-week-items/x?athlete=renee", json={"done": True}, headers=auth_headers()
    )
    assert nowk.status_code == 404
