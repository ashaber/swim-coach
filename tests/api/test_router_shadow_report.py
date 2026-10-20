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
