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
      --project=open-swim-coach-ashaber --format=json --order=asc   # + timestamp>= (see fetch_log_entries)

or read a saved export:  python scripts/router_shadow_report.py --from-file logs.json

The aggregation (`build_report` / `format_report`) is pure and tested without a network
(tests/api/test_router_shadow_report.py); only `fetch_log_entries` shells out to gcloud.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

DEFAULT_PROJECT = "open-swim-coach-ashaber"
SERVICE_NAME = "swim-coach-api"  # .github/workflows/deploy-backend.yml's SERVICE_NAME
THRESHOLDS = (0.7, 0.8, 0.9)
SONNET_THRESHOLD_COMPLEXITY = 0.5  # the gauge's Sonnet mark
TARGET_TOKENS = 78_000
CEILING_TOKENS = 95_000
CONFIDENCE_BINS = [round(i / 10, 1) for i in range(10)]  # 0.0 .. 0.9, each bin is [b, b+0.1)
CACHE_TTL = timedelta(hours=1)  # matches PROMPT_CACHE_TTL=1h; a call within this of the last one reads the cache
SESSION_GAP = timedelta(hours=1)  # messages closer together than this belong to one session


def _load_model_prices() -> Any:
    """backend/app/model_prices.py loaded by file path: it is stdlib-only, but importing it as
    `app.model_prices` would run backend/app/__init__ and need the backend on sys.path."""
    path = Path(__file__).resolve().parents[1] / "backend" / "app" / "model_prices.py"
    spec = importlib.util.spec_from_file_location("_router_report_model_prices", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # @dataclass resolves its module through sys.modules
    spec.loader.exec_module(module)
    return module


model_prices = _load_model_prices()


def extract_payloads(raw_entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """The `jsonPayload` of each entry that has one (platform/access lines have none), with the
    entry's own timestamp kept as `_ts` (Cloud Logging's, not the app's `ts`) when present."""
    out = []
    for e in raw_entries:
        if isinstance(e, dict) and isinstance(e.get("jsonPayload"), dict):
            out.append({**e["jsonPayload"], "_ts": e["timestamp"]} if e.get("timestamp") else e["jsonPayload"])
    return out


def parse_time(value: str) -> datetime:
    """ISO-8601 (with `Z` or an offset; naive means UTC) -> aware datetime. Cloud Logging emits
    nanosecond fractions, which datetime can't hold, so the fraction is cut to microseconds."""
    text = re.sub(r"(\.\d{6})\d+", r"\1", value.strip().replace("Z", "+00:00"))
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_since(value: str) -> timedelta:
    match = re.fullmatch(r"(\d+)([mhdw])", value.strip())
    if not match:
        raise ValueError(f"--since must look like 90m, 12h, 4d or 1w, got {value!r}")
    unit = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}[match.group(2)]
    return timedelta(**{unit: int(match.group(1))})


def resolve_window(*, since: str | None, from_ts: str | None, to_ts: str | None,
                   now: datetime) -> tuple[datetime | None, datetime | None]:
    """(start, end): --from/--to win over --since; end None = open."""
    start = parse_time(from_ts) if from_ts else (now - parse_since(since) if since else None)
    return start, parse_time(to_ts) if to_ts else None


def filter_entries(entries: Iterable[dict[str, Any]], *, start: datetime | None,
                   end: datetime | None) -> list[dict[str, Any]]:
    """Entries whose own `timestamp` is in [start, end]. An entry with no timestamp is dropped when
    a bound is set (it can't be shown to be inside the window)."""
    kept = []
    for e in entries:
        if start is None and end is None:
            kept.append(e)
            continue
        raw = e.get("timestamp") if isinstance(e, dict) else None
        if not raw:
            continue
        t = parse_time(raw)
        if (start is None or t >= start) and (end is None or t <= end):
            kept.append(e)
    return kept


def fetch_log_entries(*, project: str, start: datetime | None, end: datetime | None) -> list[dict[str, Any]]:
    """Raw entries. The window is a `timestamp` clause in the filter: `gcloud logging read
    --freshness` is documented as working only with --order=desc and is silently ignored with
    --order=asc, which returned ~30 days for `--since 4d`."""
    clauses = [
        'resource.type="cloud_run_revision"',
        f'resource.labels.service_name="{SERVICE_NAME}"',
        'jsonPayload.msg=("router shadow" OR "claude turn complete")',
    ]
    if start:
        clauses.append(f'timestamp>="{start.astimezone(timezone.utc).isoformat()}"')
    if end:
        clauses.append(f'timestamp<="{end.astimezone(timezone.utc).isoformat()}"')
    result = subprocess.run(
        ["gcloud", "logging", "read", " ".join(clauses), f"--project={project}",
         "--format=json", "--order=asc", "--limit=100000"],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout) if result.stdout.strip() else []


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


def _time(p: dict[str, Any]) -> datetime | None:
    raw = p.get("_ts") or p.get("ts")
    return parse_time(raw) if raw else None


def _athlete_by_request(shadow: list[dict[str, Any]]) -> dict[str, str]:
    """`claude turn complete` lines carry no athlete; `router shadow` lines do (athlete_id), and
    both carry request_id, so that is the join. Turns of requests with no shadow line (ineligible
    messages) are not attributed to anyone and are left out of the replay."""
    return {p["request_id"]: str(p.get("athlete_id") or "unknown") for p in shadow if p.get("request_id")}


def _sonnet_turns(payloads: list[dict[str, Any]], athlete_of: dict[str, str]) -> list[dict[str, Any]]:
    turns = []
    for p in payloads:
        model = str(p.get("model", ""))
        if p.get("msg") != "claude turn complete" or not model.startswith("claude-sonnet"):
            continue
        rid, when = p.get("request_id"), _time(p)
        if rid in athlete_of and when is not None:
            turns.append({"athlete": athlete_of[rid], "rid": rid, "time": when, "model": model,
                          "read": int(p.get("cache_read_input_tokens") or 0)})
    return sorted(turns, key=lambda t: t["time"])


def _cache_penalty(turns: list[dict[str, Any]], removed: set[str]) -> tuple[float, int]:
    """Extra Sonnet cost the calls that still happen pay once `removed` requests no longer warm the
    cache. A remaining call loses its cache reads (they become 1h cache writes) only if, originally,
    some call was within CACHE_TTL before it (so it was warm) and now no remaining call is."""
    penalty, repriced = 0.0, 0
    by_athlete: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in turns:
        by_athlete[t["athlete"]].append(t)
    for athlete_turns in by_athlete.values():
        last_any: datetime | None = None
        last_kept: datetime | None = None
        for t in athlete_turns:
            kept = t["rid"] not in removed
            was_warm = last_any is not None and t["time"] - last_any <= CACHE_TTL
            now_warm = last_kept is not None and t["time"] - last_kept <= CACHE_TTL
            price = model_prices.price_for(t["model"])
            if kept and was_warm and not now_warm and t["read"] and price is not None:
                penalty += t["read"] * (price.cache_write_1h - price.cache_read) / 1_000_000
                repriced += 1
            last_any = t["time"]
            if kept:
                last_kept = t["time"]
    return penalty, repriced


def _sessions(shadow: list[dict[str, Any]], sonnet_cost: dict[str, float]) -> list[dict[str, Any]]:
    """Per athlete, messages in time order, a new session when the gap to the previous message is
    SESSION_GAP or more. A message with no time is its own session."""
    sessions: list[dict[str, Any]] = []
    by_athlete: dict[str, list[tuple[datetime, dict[str, Any]]]] = defaultdict(list)
    for p in shadow:
        when = _time(p)
        athlete = str(p.get("athlete_id") or "unknown")
        if when is None:
            sessions.append({"athlete": athlete[:8], "start": None, "request_ids": [p.get("request_id")]})
        else:
            by_athlete[athlete].append((when, p))
    for athlete, items in by_athlete.items():
        current: dict[str, Any] | None = None
        previous: datetime | None = None
        for when, p in sorted(items, key=lambda x: x[0]):
            if current is None or previous is None or when - previous >= SESSION_GAP:
                current = {"athlete": athlete[:8], "start": when, "request_ids": []}
                sessions.append(current)
            current["request_ids"].append(p.get("request_id"))
            previous = when
    for s in sessions:
        costs = [sonnet_cost.get(r, 0.0) for r in s["request_ids"]]
        s["messages"], s["sonnet_usd"], s["first_message_usd"] = len(costs), sum(costs), costs[0]
    floor = datetime.min.replace(tzinfo=timezone.utc)
    return sorted(sessions, key=lambda s: (s["start"] is None, s["start"] or floor))


def session_lines(sessions: list[dict[str, Any]]) -> list[str]:
    return [
        f"  {s['athlete']} {s['start'].strftime('%m-%d %H:%MZ') if s['start'] else 'no time   '}: "
        f"{s['messages']} msgs, Sonnet ${s['sonnet_usd']:.3f}, first message ${s['first_message_usd']:.3f}"
        for s in sessions
    ]


def build_report(payloads: list[dict[str, Any]],
                 window: tuple[datetime | None, datetime | None] = (None, None)) -> dict[str, Any]:
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

    athlete_of = _athlete_by_request(shadow)
    turns = _sonnet_turns(payloads, athlete_of)
    sessions = _sessions(shadow, sonnet_cost)
    session_of = {r: i for i, sess in enumerate(sessions) for r in sess["request_ids"]}
    times = sorted(t for t in (_time(p) for p in shadow) if t is not None)

    savings = {}
    for t in THRESHOLDS:
        chosen = [p for p in decided if _would_answer(p, t)]
        safe = [p for p in chosen if not _disagrees(p)]
        gross = sum(sonnet_cost.get(p.get("request_id"), 0.0) for p in safe)
        removed = {p.get("request_id") for p in safe}
        penalty, repriced = _cache_penalty(turns, removed)
        hit_sessions = {session_of[r] for r in removed if r in session_of}
        best_gross = sum(sessions[i]["sonnet_usd"] for i in hit_sessions)
        savings[t] = {
            "cache_aware_net_saved": gross - penalty - haiku_cost_all,
            "cache_penalty_usd": penalty,
            "repriced_turns": repriced,
            "best_case_net_saved": best_gross - haiku_cost_all,
            "answered": len(chosen),
            "of_which_sonnet_wrote": len(chosen) - len(safe),
            "gross_sonnet_cost_avoided": gross,
            "haiku_cost_all_triaged": haiku_cost_all,
            "net_saved": gross - haiku_cost_all,
            "missing_sonnet_cost": sum(1 for p in safe if p.get("request_id") not in sonnet_cost),
        }

    # Health cross-check. Haiku only judges messages no keyword rule caught (triaged) plus health-keyword
    # hits it is run on as a probe, so both directions are measurable.
    probes = [p for p in shadow if p.get("pre_rule") and p.get("haiku_probe") and p.get("status") == "ok"]
    health = {
        "haiku_caught_keywords_missed": sum(1 for p in triaged if p.get("haiku_health_escalate")),
        "keywords_caught_haiku_nonhealth": sum(1 for p in probes if not p.get("haiku_health_escalate")),
        "probes": len(probes),
    }

    fallbacks = [p for p in triaged if p.get("triage_fallback")]
    return {
        "window": {"start": window[0], "end": window[1], "first_message": times[0] if times else None,
                   "last_message": times[-1] if times else None},
        "sessions": sessions,
        "triage_fallback": {
            "count": len(fallbacks),
            "cost_usd": sum(p.get("triage_fallback_cost_usd") or 0 for p in fallbacks),
        },
        "health": health,
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
    w = report["window"]

    def iso(t: datetime | None, default: str) -> str:
        return t.astimezone(timezone.utc).isoformat(timespec="seconds") if t else default

    lines = [
        f"Window: {iso(w['start'], 'open')} .. {iso(w['end'], 'now')}  |  "
        f"first message {iso(w['first_message'], 'none')}, last message {iso(w['last_message'], 'none')}",
        f"Messages shadowed: {report['messages']}",
        f"  forced to Sonnet by a pre-rule: {pr['count']} ({pr['share']:.0%})  {pr['by_category']}",
        f"  triaged by Haiku: {report['triaged']}  (with a decision: {report['decided']}; "
        f"no decision: {report['not_decided']})",
        f"Haiku routed: answer {report['answer_share']:.0%} / escalate {report['escalate_share']:.0%}",
        f"  Forced-triage fallbacks: {report['triage_fallback']['count']} "
        f"(${report['triage_fallback']['cost_usd']:.4f})",
        "",
        "Health cross-check:",
        f"  Haiku caught health the keywords missed: {report['health']['haiku_caught_keywords_missed']}",
        f"  keywords caught what Haiku called non-health: {report['health']['keywords_caught_haiku_nonhealth']}"
        f" (of {report['health']['probes']} probed keyword hits)",
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
        "Haiku cost on every triaged message charged against it; write/draft-tool turns not counted).",
        "HEADLINE = cache-aware: replays each athlete's Sonnet calls without the Haiku-answered ones; a call that",
        "was warm only because an answered call preceded it (within 1h) re-pays its cache reads as 1h writes.",
        "naive = each answered message credited its full Sonnet cost (overstates: ignores that cache write).",
        "best case = every message in any session with an answered message avoided Sonnet entirely.",
    ]
    for t, s in report["savings"].items():
        lines.append(
            f"  T={t}: would answer {s['answered']} ({s['of_which_sonnet_wrote']} touched write tools)\n"
            f"      cache-aware net ${s['cache_aware_net_saved']:.4f}  "
            f"(cache re-write penalty ${s['cache_penalty_usd']:.4f} on {s['repriced_turns']} calls)\n"
            f"      naive net ${s['net_saved']:.4f}  (Sonnet cost credited ${s['gross_sonnet_cost_avoided']:.4f})  "
            f"best case net ${s['best_case_net_saved']:.4f}"
            + (f"  [{s['missing_sonnet_cost']} without a joined Sonnet cost]" if s["missing_sonnet_cost"] else "")
        )
    lines += ["", "Sessions (messages < 1h apart, per athlete; Sonnet $ is what it really cost):",
              *session_lines(report["sessions"])]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--since", default=None,
                        help="window start as an age: 90m, 12h, 4d, 1w (default 7d for gcloud; no window for "
                             "--from-file unless given)")
    parser.add_argument("--from", dest="from_ts", help="window start, ISO-8601 (wins over --since)")
    parser.add_argument("--to", dest="to_ts", help="window end, ISO-8601")
    parser.add_argument("--from-file", help="a saved `gcloud logging read --format=json` export")
    args = parser.parse_args(argv)
    try:
        since = args.since or (None if args.from_file else "7d")
        start, end = resolve_window(since=since, from_ts=args.from_ts, to_ts=args.to_ts,
                                    now=datetime.now(timezone.utc))
        if args.from_file:
            with open(args.from_file, encoding="utf-8") as fh:
                entries = json.load(fh)
        else:
            entries = fetch_log_entries(project=args.project, start=start, end=end)
        entries = filter_entries(entries, start=start, end=end)
    except (subprocess.CalledProcessError, OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"could not read logs: {exc}", file=sys.stderr)
        return 1
    print(format_report(build_report(extract_payloads(entries), window=(start, end))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
