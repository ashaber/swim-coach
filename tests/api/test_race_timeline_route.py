"""PATCH /api/race-day/{id}/timeline: per-race timeline replace + reset-to-template."""

from __future__ import annotations

from fakes import auth_headers

TEMPLATE = {
    "sections": [{"id": "kit", "title": "Kit", "items": [{"id": "helmet", "text": "Helmet"}]}],
    "timeline": [
        {"id": "wake", "label": "Wake up", "day": "race", "offset_min": -315, "not_later_than": "07:00"},
        {"id": "lunch", "label": "Lunch", "day": "race", "offset_min": -180, "only_if_start_after": "12:00"},
        {"id": "start", "label": "Start", "day": "race", "offset_min": 0, "is_start": True},
    ],
}


def _open(client, run_tag):
    client.put("/api/race-checklist/template?athlete=renee", json=TEMPLATE, headers=auth_headers())
    return client.get(f"/api/race-day?athlete=renee&date=2026-10-17&session_id=s-{run_tag}", headers=auth_headers()).json()


def test_requires_auth(client) -> None:
    assert client.patch("/api/race-day/x/timeline?athlete=renee", json={"reset": True}).status_code == 401


def test_replace_then_reset_roundtrip(client, run_tag) -> None:
    plan = _open(client, run_tag)
    assert plan["timeline_edited"] is False
    url = f"/api/race-day/{plan['id']}/timeline?athlete=renee"
    edited = [
        {"id": "wake", "label": "Wake (late)", "day": "race", "offset_min": -200},
        {"id": "start", "label": "Start", "day": "race", "offset_min": 0, "is_start": True},
        {"id": "extra", "label": "Coffee", "day": "race", "offset_min": -30, "not_earlier_than": "06:00"},
    ]
    for _ in range(2):  # replay-safe
        r = client.patch(url, json={"timeline": edited}, headers=auth_headers())
        assert r.status_code == 200
    body = r.json()
    assert body["timeline_edited"] is True and [t["id"] for t in body["timeline"]] == ["wake", "start", "extra"]
    assert body["timeline"][2]["not_earlier_than"] == "06:00"
    persisted = client.get(f"/api/race-day?athlete=renee&date=2026-10-17", headers=auth_headers()).json()
    assert persisted["timeline_edited"] is True and persisted["timeline"][0]["label"] == "Wake (late)"
    # template untouched
    tmpl = client.get("/api/race-checklist/template?athlete=renee", headers=auth_headers()).json()
    assert [t["id"] for t in tmpl["timeline"]] == ["wake", "lunch", "start"]
    # reset restores it
    reset = client.patch(url, json={"reset": True}, headers=auth_headers()).json()
    assert reset["timeline_edited"] is False
    assert [t["id"] for t in reset["timeline"]] == ["wake", "lunch", "start"]
    assert reset["timeline"][0]["not_later_than"] == "07:00"


def test_invalid_timelines_rejected(client, run_tag) -> None:
    plan = _open(client, run_tag)
    url = f"/api/race-day/{plan['id']}/timeline?athlete=renee"
    start = {"id": "start", "label": "Start", "day": "race", "offset_min": 0, "is_start": True}
    bad_bodies = [
        {},
        {"timeline": [{"id": "a", "label": "A", "day": "race"}, start]},  # no offset
        {"timeline": [{"id": "a", "label": "A", "offset_min": -5, "not_later_than": "7am"}, start]},
        {"timeline": [start, {**start, "label": "dupe"}]},  # duplicate id
        {"timeline": [{"id": "a", "label": "A", "offset_min": -5}]},  # no start
    ]
    for body in bad_bodies:
        assert client.patch(url, json=body, headers=auth_headers()).status_code == 422, body
    assert client.patch("/api/race-day/missing/timeline?athlete=renee", json={"reset": True}, headers=auth_headers()).status_code == 404
