"""scripts/router_shadow_report.py: pure aggregation over synthetic log payloads (no network)."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from router_shadow_report import build_report, extract_payloads, format_report  # noqa: E402


def shadow(rid, **kw):
    base = dict(msg="router shadow", request_id=rid, pre_rule=None, status="ok", haiku_route="answer",
                confidence=0.85, complexity=0.2, haiku_prompt_tokens=60_000, haiku_cost_usd=0.01,
                sonnet_write_tool=False, sonnet_draft_tool=False, trimmed=[])
    base.update(kw)
    return base


def turn(rid, cost):
    return dict(msg="claude turn complete", request_id=rid, model="claude-sonnet-5-5", est_cost_usd=cost)


PAYLOADS = [
    shadow("a"), turn("a", 0.20),
    shadow("b", confidence=0.75), turn("b", 0.10),
    shadow("c", haiku_route="escalate", confidence=0.95, complexity=0.8), turn("c", 0.30),
    shadow("d", sonnet_write_tool=True), turn("d", 0.40),  # disagreement
    shadow("e", pre_rule="health_safety", status="skipped_pre_rule", haiku_route=None, confidence=None,
           haiku_prompt_tokens=None, haiku_cost_usd=None), turn("e", 0.15),
    shadow("f", status="over_budget", haiku_route=None, confidence=None, haiku_prompt_tokens=None,
           haiku_cost_usd=None),
    shadow("g", haiku_prompt_tokens=96_000, trimmed=["routed_library"]),
    {"msg": "claude turn complete", "request_id": "x", "model": "claude-haiku-5-5", "est_cost_usd": 9.0},
]


def test_shares_and_prerules() -> None:
    r = build_report(PAYLOADS)
    assert r["messages"] == 7
    assert r["pre_rule"]["count"] == 1 and r["pre_rule"]["by_category"] == {"health_safety": 1}
    assert r["triaged"] == 6 and r["decided"] == 5
    assert r["answer_share"] == 4 / 5 and r["not_decided"]["over_budget"] == 1


def test_disagreement_and_prompt_distribution() -> None:
    r = build_report(PAYLOADS)
    assert r["disagreements"] == ["d"]
    assert r["prompt_tokens"]["max"] == 96_000 and r["prompt_tokens"]["over_ceiling"] == 1
    assert r["prompt_tokens"]["over_100k"] == 0 and r["prompt_tokens"]["trimmed_share"] == 1 / 6


def test_histogram_bins() -> None:
    h = build_report(PAYLOADS)["confidence_histogram"]
    assert h[0.8] == 3 and h[0.7] == 1 and h[0.9] == 1


def test_savings_by_threshold_charges_haiku_on_everything_and_skips_write_turns() -> None:
    s = build_report(PAYLOADS)["savings"]
    # haiku cost over 5 triaged-with-cost lines (a,b,c,d,g) = 0.05
    assert s[0.7]["answered"] == 4 and s[0.7]["of_which_sonnet_wrote"] == 1
    assert s[0.7]["gross_sonnet_cost_avoided"] == 0.20 + 0.10 + 0.0  # g has no joined sonnet cost
    assert s[0.7]["missing_sonnet_cost"] == 1
    assert round(s[0.7]["net_saved"], 6) == round(0.30 - 0.05, 6)
    assert s[0.9]["answered"] == 0 and s[0.8]["answered"] == 3


def test_format_and_extract() -> None:
    text = format_report(build_report(PAYLOADS))
    for needle in ("Confidence histogram", "Disagreements", "request_id=d", "T=0.7", "T=0.9", "max=96000"):
        assert needle in text
    assert extract_payloads([{"jsonPayload": {"msg": "x"}}, {"textPayload": "y"}]) == [{"msg": "x"}]


def test_empty_input_does_not_crash() -> None:
    assert "Messages shadowed: 0" in format_report(build_report([]))


def test_health_cross_check_counts_both_directions() -> None:
    payloads = [
        shadow("h1", haiku_health_escalate=True, haiku_route="escalate", category="health"),  # keywords missed
        shadow("h2"),
        shadow("p1", pre_rule="health_safety", haiku_probe=True, haiku_health_escalate=True),
        shadow("p2", pre_rule="health_safety", haiku_probe=True, haiku_health_escalate=False),  # Haiku disagreed
        shadow("p3", pre_rule="write_intent", haiku_probe=False, status="skipped_pre_rule"),
    ]
    health = build_report(payloads)["health"]
    assert health == {"haiku_caught_keywords_missed": 1, "keywords_caught_haiku_nonhealth": 1, "probes": 2}
    assert "Haiku caught health the keywords missed: 1" in format_report(build_report(payloads))


def test_report_counts_triage_fallbacks_and_their_cost() -> None:
    payloads = [
        shadow("f1", triage_fallback=True, triage_fallback_cost_usd=0.002),
        shadow("f2", triage_fallback=True, triage_fallback_cost_usd=0.003),
        shadow("f3", triage_fallback=False),
    ]
    report = build_report(payloads)
    assert report["triage_fallback"]["count"] == 2
    assert abs(report["triage_fallback"]["cost_usd"] - 0.005) < 1e-9
    assert "Forced-triage fallbacks: 2" in format_report(report)


# ---- window filtering -------------------------------------------------------------------------

from datetime import datetime, timedelta, timezone  # noqa: E402

from router_shadow_report import (  # noqa: E402
    filter_entries, parse_since, resolve_window, session_lines,
)


def entry(ts, **payload):
    return {"timestamp": ts, "jsonPayload": payload}


def test_filter_entries_drops_outside_window_on_entry_timestamp() -> None:
    entries = [
        entry("2026-10-20T19:00:00.5Z", msg="a"),
        entry("2026-10-31T00:23:47.138971Z", msg="b"),
        entry("2026-10-31T01:43:39Z", msg="c"),
        {"jsonPayload": {"msg": "no timestamp"}},
    ]
    start = datetime(2026, 10, 31, tzinfo=timezone.utc)
    kept = filter_entries(entries, start=start, end=None)
    assert [e["jsonPayload"]["msg"] for e in kept] == ["b", "c"]
    kept = filter_entries(entries, start=None, end=datetime(2026, 10, 31, 1, tzinfo=timezone.utc))
    assert [e["jsonPayload"]["msg"] for e in kept] == ["a", "b"]


def test_extract_payloads_keeps_entry_timestamp() -> None:
    out = extract_payloads([entry("2026-10-31T00:00:00Z", msg="x")])
    assert out == [{"msg": "x", "_ts": "2026-10-31T00:00:00Z"}]


def test_resolve_window_since_from_to() -> None:
    now = datetime(2026, 10, 31, 4, 0, tzinfo=timezone.utc)
    assert parse_since("4d") == timedelta(days=4) and parse_since("90m") == timedelta(minutes=90)
    start, end = resolve_window(since="4d", from_ts=None, to_ts=None, now=now)
    assert start == now - timedelta(days=4) and end is None
    start, end = resolve_window(since="4d", from_ts="2026-10-31T00:00:00Z", to_ts="2026-10-31T02:00:00Z", now=now)
    assert start == datetime(2026, 10, 31, tzinfo=timezone.utc) and end == datetime(2026, 10, 31, 2, tzinfo=timezone.utc)


# ---- cache-aware saving -----------------------------------------------------------------------

T0 = datetime(2026, 10, 30, 22, 0, tzinfo=timezone.utc)


def at(minutes):
    return (T0 + timedelta(minutes=minutes)).isoformat()


def cturn(rid, minutes, creation, read, output):
    # Sonnet 5.5 prices ($/M): input 2, read 0.10, write(1h) 4.0, output 10.
    cost = (creation * 4.0 + read * 0.10 + output * 10.0 + 15 * 2.0) / 1e6
    return dict(msg="claude turn complete", request_id=rid, model="claude-sonnet-5-5", est_cost_usd=cost,
                cache_creation_input_tokens=creation, cache_read_input_tokens=read, input_tokens=15,
                output_tokens=output, _ts=at(minutes))


def cshadow(rid, minutes, athlete="ath1", **kw):
    return shadow(rid, athlete_id=athlete, _ts=at(minutes), haiku_cost_usd=0.001, **kw)


ESC = dict(haiku_route="escalate", confidence=0.9, complexity=0.9)


def night_1030():
    """First message expensive (cold cache), 7 cheap follow-ups, final one escalated."""
    p = [cshadow("m0", 0), cturn("m0", 0, 110_187, 0, 1274)]
    for i in range(1, 8):
        p += [cshadow(f"m{i}", i * 5), cturn(f"m{i}", i * 5, 300, 110_000, 250)]
    p += [cshadow("m8", 45, **ESC), cturn("m8", 45, 20_466, 89_446, 700)]
    return p


def test_cache_aware_saving_is_well_under_naive_on_the_1030_night() -> None:
    s = build_report(night_1030())["savings"][0.7]
    assert s["answered"] == 8
    assert s["gross_sonnet_cost_avoided"] > 0.5  # naive credits the cold first message in full
    # the escalated final message now pays the cache write the first message would have paid
    assert s["cache_aware_net_saved"] < s["net_saved"] - 0.25
    assert s["cache_aware_net_saved"] > 0
    assert s["repriced_turns"] == 1
    assert s["best_case_net_saved"] >= s["net_saved"] - 1e-9


def test_session_without_escalation_has_no_cache_penalty() -> None:
    p = [cshadow("a", 0), cturn("a", 0, 100_000, 0, 500), cshadow("b", 5), cturn("b", 5, 200, 100_000, 300)]
    s = build_report(p)["savings"][0.7]
    assert s["repriced_turns"] == 0
    assert abs(s["cache_aware_net_saved"] - s["net_saved"]) < 1e-9
    assert abs(s["cache_aware_net_saved"] - (s["gross_sonnet_cost_avoided"] - 0.002)) < 1e-9


def test_gap_over_ttl_means_remaining_call_was_already_cold_and_is_not_repriced() -> None:
    # b is escalated, 2h after a (which is answered): b was cold before and stays at its logged cost
    p = [cshadow("a", 0), cturn("a", 0, 100_000, 0, 500), cshadow("b", 120, **ESC), cturn("b", 120, 100_000, 0, 500)]
    report = build_report(p)
    s = report["savings"][0.7]
    assert s["repriced_turns"] == 0
    assert abs(s["cache_aware_net_saved"] - s["net_saved"]) < 1e-9
    assert len(report["sessions"]) == 2


def test_escalated_call_within_ttl_of_another_remaining_call_stays_warm() -> None:
    p = [cshadow("a", 0, **ESC), cturn("a", 0, 100_000, 0, 500),
         cshadow("b", 5), cturn("b", 5, 200, 100_000, 300),
         cshadow("c", 10, **ESC), cturn("c", 10, 200, 100_200, 300)]
    assert build_report(p)["savings"][0.7]["repriced_turns"] == 0


def test_sessions_split_on_gap_and_per_athlete() -> None:
    p = [cshadow("a", 0), cturn("a", 0, 100_000, 0, 500), cshadow("b", 30), cturn("b", 30, 100, 100_000, 100),
         cshadow("c", 100), cturn("c", 100, 100_000, 0, 100), cshadow("d", 5, athlete="ath2"),
         cturn("d", 5, 50_000, 0, 100)]
    sess = build_report(p)["sessions"]
    assert sorted((s["athlete"], s["messages"]) for s in sess) == [("ath1", 1), ("ath1", 2), ("ath2", 1)]
    two = next(s for s in sess if s["messages"] == 2)
    assert abs(two["first_message_usd"] - (100_000 * 4.0 + 500 * 10 + 30) / 1e6) < 1e-9
    assert two["sonnet_usd"] > two["first_message_usd"]
    assert any("msgs" in line for line in session_lines(sess))


def test_report_header_shows_window_and_first_last_message() -> None:
    text = format_report(build_report(night_1030()))
    assert "first message 2026-10-30T22:00:00" in text and "last message 2026-10-30T22:45:00" in text
    assert "cache-aware" in text and "naive" in text
