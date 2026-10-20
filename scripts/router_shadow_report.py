#!/usr/bin/env python3
"""Report on the Haiku coach router's shadow week, from Cloud Run's structured logs.

Reads two log lines the backend emits (backend/app/router_shadow.py, backend/app/claude.py):
  - `router shadow`        one per eligible chat message: pre-rule, Haiku's decision, Haiku's
                           tokens/cost, and what Sonnet actually did (tools, write tools).
  - `claude turn complete` one per Sonnet call: `est_cost_usd`, summed per request_id to get
                           what each message really cost on Sonnet.

and prints: share routed answer vs escalate, pre-rule share, a confidence histogram,
disagreements (Haiku said "answer" but Sonnet called a write/draft tool), Haiku prompt-size
distribution and max, and the estimated net $ saved if the router were enabled at confidence
thresholds 0.7 / 0.8 / 0.9 (Haiku's cost on EVERY triaged message is charged against the saving,
and a message where Sonnet used a write/draft tool is never counted as safely answered).

Fetch the logs with gcloud (the same approach as scripts/route_report.py; this does it for you):

    python scripts/router_shadow_report.py --since 7d
    python scripts/router_shadow_report.py --project open-swim-coach-ashaber --since 7d

which runs:

    gcloud logging read \\
      'resource.type="cloud_run_revision" resource.labels.service_name="swim-coach-api"
       jsonPayload.msg=("router shadow" OR "claude turn complete")' \\
      --project=open-swim-coach-ashaber --freshness=7d --format=json --order=asc

or read a saved export:  python scripts/router_shadow_report.py --from-file logs.json

The aggregation (`build_report` / `format_report`) is pure and tested without a network
(tests/api/test_router_shadow_report.py); only `fetch_log_entries` shells out to gcloud.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from collections import defaultdict
from typing import Any, Iterable

DEFAULT_PROJECT = "open-swim-coach-ashaber"
SERVICE_NAME = "swim-coach-api"  # .github/workflows/deploy-backend.yml's SERVICE_NAME
THRESHOLDS = (0.7, 0.8, 0.9)
SONNET_THRESHOLD_COMPLEXITY = 0.5  # the gauge's Sonnet mark
TARGET_TOKENS = 78_000
CEILING_TOKENS = 95_000
CONFIDENCE_BINS = [round(i / 10, 1) for i in range(10)]  # 0.0 .. 0.9, each bin is [b, b+0.1)


def extract_payloads(raw_entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """The `jsonPayload` of each entry that has one (platform/access lines have none)."""
    return [e["jsonPayload"] for e in raw_entries if isinstance(e, dict) and isinstance(e.get("jsonPayload"), dict)]


def fetch_log_entries(*, project: str, since: str) -> list[dict[str, Any]]:
    query = (
        'resource.type="cloud_run_revision" '
        f'resource.labels.service_name="{SERVICE_NAME}" '
        'jsonPayload.msg=("router shadow" OR "claude turn complete")'
    )
    result = subprocess.run(
        ["gcloud", "logging", "read", query, f"--project={project}", f"--freshness={since}",
         "--format=json", "--order=asc"],
        capture_output=True, text=True, check=True,
    )
    return extract_payloads(json.loads(result.stdout) if result.stdout.strip() else [])


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(pct / 100 * len(ordered)) - 1))]


def _disagrees(line: dict[str, Any]) -> bool:
    return line.get("haiku_route") == "answer" and bool(line.get("sonnet_write_tool") or line.get("sonnet_draft_tool"))


def _would_answer(line: dict[str, Any], threshold: float) -> bool:
    return (
        line.get("haiku_route") == "answer"
        and not line.get("haiku_invalid")
        and (line.get("confidence") or 0) >= threshold
        and (line.get("complexity") if line.get("complexity") is not None else 1) < SONNET_THRESHOLD_COMPLEXITY
    )


def build_report(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    shadow = [p for p in payloads if p.get("msg") == "router shadow"]
    sonnet_cost: dict[str, float] = defaultdict(float)
    for p in payloads:
        if p.get("msg") == "claude turn complete" and str(p.get("model", "")).startswith("claude-sonnet"):
            if p.get("est_cost_usd") is not None and p.get("request_id"):
                sonnet_cost[p["request_id"]] += p["est_cost_usd"]

    pre_rule = [p for p in shadow if p.get("pre_rule")]
    by_pre_rule: dict[str, int] = defaultdict(int)
    for p in pre_rule:
        by_pre_rule[p["pre_rule"]] += 1
    triaged = [p for p in shadow if not p.get("pre_rule")]
    decided = [p for p in triaged if p.get("haiku_route") in ("answer", "escalate")]
    answered = [p for p in decided if p["haiku_route"] == "answer"]

    histogram = {b: 0 for b in CONFIDENCE_BINS}
    for p in decided:
        c = p.get("confidence")
        if c is not None:
            histogram[CONFIDENCE_BINS[min(9, int(c * 10))]] += 1

    prompts = [p["haiku_prompt_tokens"] for p in triaged if p.get("haiku_prompt_tokens")]
    haiku_cost_all = sum(p.get("haiku_cost_usd") or 0 for p in triaged)

    savings = {}
    for t in THRESHOLDS:
        chosen = [p for p in decided if _would_answer(p, t)]
        safe = [p for p in chosen if not _disagrees(p)]
        gross = sum(sonnet_cost.get(p.get("request_id"), 0.0) for p in safe)
        savings[t] = {
            "answered": len(chosen),
            "of_which_sonnet_wrote": len(chosen) - len(safe),
            "gross_sonnet_cost_avoided": gross,
            "haiku_cost_all_triaged": haiku_cost_all,
            "net_saved": gross - haiku_cost_all,
            "missing_sonnet_cost": sum(1 for p in safe if p.get("request_id") not in sonnet_cost),
        }

    return {
        "messages": len(shadow),
        "pre_rule": {"count": len(pre_rule), "share": len(pre_rule) / len(shadow) if shadow else 0.0,
                     "by_category": dict(by_pre_rule)},
        "triaged": len(triaged),
        "decided": len(decided),
        "answer_share": len(answered) / len(decided) if decided else 0.0,
        "escalate_share": 1 - len(answered) / len(decided) if decided else 0.0,
        "not_decided": {s: sum(1 for p in triaged if p.get("status") == s)
                        for s in ("over_budget", "no_triage", "error")},
        "confidence_histogram": histogram,
        "disagreements": [p.get("request_id") for p in decided if _disagrees(p)],
        "prompt_tokens": {
            "n": len(prompts),
            "p50": _percentile(prompts, 50) if prompts else None,
            "p90": _percentile(prompts, 90) if prompts else None,
            "max": max(prompts) if prompts else None,
            "over_target": sum(1 for v in prompts if v > TARGET_TOKENS),
            "over_ceiling": sum(1 for v in prompts if v > CEILING_TOKENS),
            "over_100k": sum(1 for v in prompts if v > 100_000),
            "trimmed_share": (sum(1 for p in triaged if p.get("trimmed")) / len(triaged)) if triaged else 0.0,
        },
        "haiku_cost_total": haiku_cost_all,
        "savings": savings,
    }


def format_report(report: dict[str, Any]) -> str:
    pr, pt = report["pre_rule"], report["prompt_tokens"]
    lines = [
        f"Messages shadowed: {report['messages']}",
        f"  forced to Sonnet by a pre-rule: {pr['count']} ({pr['share']:.0%})  {pr['by_category']}",
        f"  triaged by Haiku: {report['triaged']}  (with a decision: {report['decided']}; "
        f"no decision: {report['not_decided']})",
        f"Haiku routed: answer {report['answer_share']:.0%} / escalate {report['escalate_share']:.0%}",
        "",
        "Confidence histogram (decided messages):",
    ]
    for b, n in report["confidence_histogram"].items():
        lines.append(f"  {b:.1f}-{b + 0.1:.1f}  {n:4d} {'#' * min(n, 60)}")
    lines += [
        "",
        f"Disagreements (Haiku said answer, Sonnet used a write/draft tool): {len(report['disagreements'])}",
        *[f"  request_id={r}" for r in report["disagreements"]],
        "",
        f"Haiku prompt tokens: n={pt['n']} p50={pt['p50']} p90={pt['p90']} max={pt['max']}",
        f"  over {TARGET_TOKENS}: {pt['over_target']}   over {CEILING_TOKENS}: {pt['over_ceiling']}   "
        f"over 100k (5x price): {pt['over_100k']}   trimmed: {pt['trimmed_share']:.0%}",
        f"Haiku cost over the window (all triaged): ${report['haiku_cost_total']:.4f}",
        "",
        "Estimated saving if enabled (answer when route=answer, confidence >= T, complexity < 0.5;",
        "Haiku cost on every triaged message charged against it; write/draft-tool turns not counted):",
    ]
    for t, s in report["savings"].items():
        lines.append(
            f"  T={t}: would answer {s['answered']} ({s['of_which_sonnet_wrote']} touched write tools), "
            f"Sonnet cost avoided ${s['gross_sonnet_cost_avoided']:.4f}, "
            f"net ${s['net_saved']:.4f}"
            + (f"  [{s['missing_sonnet_cost']} without a joined Sonnet cost]" if s["missing_sonnet_cost"] else "")
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--since", default="7d", help="gcloud --freshness window (default 7d)")
    parser.add_argument("--from-file", help="a saved `gcloud logging read --format=json` export")
    args = parser.parse_args(argv)
    try:
        if args.from_file:
            with open(args.from_file, encoding="utf-8") as fh:
                payloads = extract_payloads(json.load(fh))
        else:
            payloads = fetch_log_entries(project=args.project, since=args.since)
    except (subprocess.CalledProcessError, OSError, json.JSONDecodeError) as exc:
        print(f"could not read logs: {exc}", file=sys.stderr)
        return 1
    print(format_report(build_report(payloads)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
