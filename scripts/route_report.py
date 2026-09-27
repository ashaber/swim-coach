#!/usr/bin/env python3
"""Per-day report on library routing/citation misses and their extra cost,
from Cloud Run's own structured logs (IDEA 025 step 1).

Reads three structured JSON log lines this codebase already emits (see
`backend/app/context.py`'s `route_info_for_logging`/"library route",
`backend/app/tools.py`'s "route miss", and `backend/app/claude.py`'s "claude
turn complete") via `gcloud logging read` against the Cloud Run service's
stdout, and aggregates them per UTC calendar day:

  - chat requests: one "library route" line per `POST /api/chat` or
    `POST /api/feedback/questions` request.
  - route misses by kind ("reference": `lookup_reference` was called;
    "topic": `flag_for_coach_review` was called with `research_gap=true`),
    and the miss rate (the fraction of that day's chat requests that had at
    least one miss).
  - the extra cost (USD, Sonnet 5 rates) of requests that had a miss: the
    sum of every `iteration > 0` "claude turn complete" call's cost for
    those request_ids -- the extra tool-loop round trips a routing/citation
    gap caused, on top of the turn's own first (iteration 0) call.

`request_id` (added to every one of these three log lines by
`app.routes.chat`/`app.routes.feedback`/`app.claude`) is what joins them
back together here -- see those modules for where it's generated/threaded.

Usage:
    python scripts/route_report.py
    python scripts/route_report.py --since 24h
    python scripts/route_report.py --project open-swim-coach-ashaber --since 30d

No network calls happen in this repo's tests -- `build_report`/
`extract_payloads` (the parsing/aggregation) are pure functions tested
against a small fixture in tests/api/test_route_report.py; only
`fetch_log_entries` touches `gcloud`, and it is not exercised by tests.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

DEFAULT_PROJECT = "open-swim-coach-ashaber"
SERVICE_NAME = "swim-coach-api"  # .github/workflows/deploy-backend.yml's SERVICE_NAME

# Sonnet 5 pricing, USD per MTok (IDEA 022's own figures -- see
# backend/app/config.py's PROMPT_CACHE_TTL comment and IDEAS.md's "IDEA 022
# -- RESULTS" section). Kept as constants here, not imported from the
# backend package, so this script has no dependency on it.
INPUT_PRICE_PER_MTOK = 2.0
OUTPUT_PRICE_PER_MTOK = 10.0
CACHE_READ_MULTIPLIER = 0.1
CACHE_WRITE_5M_MULTIPLIER = 1.25
CACHE_WRITE_1H_MULTIPLIER = 2.0  # not applied below -- see _call_cost_usd's docstring


def _call_cost_usd(entry: dict[str, Any]) -> float:
    """USD cost of one "claude turn complete" log line's `usage`, Sonnet 5
    rates. Cache writes are priced at the 5-minute multiplier
    (`CACHE_WRITE_5M_MULTIPLIER`) unconditionally -- a "claude turn
    complete" line's usage counters don't say whether that write happened
    under a 5-minute or 1-hour TTL (`PROMPT_CACHE_TTL`), so this can't tell
    them apart from the log alone. `CACHE_WRITE_1H_MULTIPLIER` is kept as a
    constant for when that becomes loggable, not silently applied here."""
    input_tokens = entry.get("input_tokens") or 0
    output_tokens = entry.get("output_tokens") or 0
    cache_read_tokens = entry.get("cache_read_input_tokens") or 0
    cache_write_tokens = entry.get("cache_creation_input_tokens") or 0
    total = (
        input_tokens * INPUT_PRICE_PER_MTOK
        + output_tokens * OUTPUT_PRICE_PER_MTOK
        + cache_read_tokens * INPUT_PRICE_PER_MTOK * CACHE_READ_MULTIPLIER
        + cache_write_tokens * INPUT_PRICE_PER_MTOK * CACHE_WRITE_5M_MULTIPLIER
    )
    return total / 1_000_000


def _day_of(ts: str | None) -> str | None:
    """The UTC calendar date (`YYYY-MM-DD`) of a log line's own `ts` field
    (`datetime.now(timezone.utc).isoformat()`, per
    `app.logging_config.JsonLogger`) -- always UTC, so the first 10
    characters of the ISO string are the date, no parsing library needed."""
    if not ts or len(ts) < 10:
        return None
    return ts[:10]


@dataclass
class DayStats:
    chat_requests: int = 0
    misses_by_kind: dict[str, int] = field(default_factory=dict)
    requests_with_miss: set[str] = field(default_factory=set)
    extra_cost_usd: float = 0.0

    @property
    def total_misses(self) -> int:
        return sum(self.misses_by_kind.values())

    @property
    def miss_rate(self) -> float:
        return len(self.requests_with_miss) / self.chat_requests if self.chat_requests else 0.0


def extract_payloads(raw_entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """The `jsonPayload` of each `gcloud logging read --format=json` entry
    that has one -- an entry gcloud couldn't parse as JSON (shouldn't happen
    for this codebase's own structured logger, but real logs carry other
    noise too -- health-check access logs, platform events) has no
    `jsonPayload` and is skipped rather than raising."""
    return [
        entry["jsonPayload"]
        for entry in raw_entries
        if isinstance(entry, dict) and isinstance(entry.get("jsonPayload"), dict)
    ]


def build_report(payloads: Iterable[dict[str, Any]]) -> dict[str, DayStats]:
    """Per-day `DayStats`, keyed by UTC date string, sorted ascending.

    Two passes are needed, not one: a "route miss"/"claude turn complete"
    line's own `request_id` says which chat request it belongs to, but only
    the "library route" line (always the first of the three for a given
    request) pins that request_id to a calendar day -- so which day a
    miss's "extra cost" counts against is resolved from the request's own
    "library route" day, not the (usually same, but not guaranteed) day of
    the later lines themselves.
    """
    request_day: dict[str, str] = {}
    request_has_miss: set[str] = set()
    # request_id -> [(iteration, cost_usd), ...] for every "claude turn
    # complete" line seen, regardless of whether that request turns out to
    # have a miss -- resolved against `request_has_miss` in the second pass.
    turn_calls: dict[str, list[tuple[int, float]]] = defaultdict(list)
    reports: dict[str, DayStats] = defaultdict(DayStats)

    for entry in payloads:
        msg = entry.get("msg")
        day = _day_of(entry.get("ts"))
        request_id = entry.get("request_id")

        if msg == "library route":
            if day is not None:
                reports[day].chat_requests += 1
                if request_id:
                    request_day[request_id] = day
        elif msg == "route miss":
            kind = entry.get("kind") or "unknown"
            if day is not None:
                reports[day].misses_by_kind[kind] = reports[day].misses_by_kind.get(kind, 0) + 1
            if request_id:
                request_has_miss.add(request_id)
        elif msg == "claude turn complete":
            if request_id:
                turn_calls[request_id].append((entry.get("iteration") or 0, _call_cost_usd(entry)))

    for request_id in request_has_miss:
        day = request_day.get(request_id)
        if day is None:
            continue
        reports[day].requests_with_miss.add(request_id)
        reports[day].extra_cost_usd += sum(
            cost for iteration, cost in turn_calls.get(request_id, []) if iteration > 0
        )

    return dict(sorted(reports.items()))


def format_report(report: dict[str, DayStats]) -> str:
    if not report:
        return "no chat requests in this window"
    lines = []
    for day, stats in report.items():
        misses_str = (
            ", ".join(f"{kind}: {count}" for kind, count in sorted(stats.misses_by_kind.items()))
            or "none"
        )
        lines.append(
            f"{day}: {stats.chat_requests} chat requests, "
            f"{stats.total_misses} route misses ({misses_str}), "
            f"miss rate {stats.miss_rate * 100:.1f}%, "
            f"extra cost from missed-turn requests: ${stats.extra_cost_usd:.4f}"
        )
    return "\n".join(lines)


def fetch_log_entries(*, project: str, since: str) -> list[dict[str, Any]]:
    """Runs `gcloud logging read` for `SERVICE_NAME`'s Cloud Run stdout,
    filtered to this codebase's own three routing/cost log lines, over the
    trailing `since` window (gcloud's `--freshness` duration syntax, e.g.
    `"24h"`, `"7d"`, `"30d"`). Not exercised by tests -- the only function
    here that touches the network (via `gcloud`, itself already
    authenticated against GCP outside this script's concern)."""
    query = (
        'resource.type="cloud_run_revision" '
        f'resource.labels.service_name="{SERVICE_NAME}" '
        'jsonPayload.msg=("claude turn complete" OR "library route" OR "route miss")'
    )
    result = subprocess.run(
        [
            "gcloud",
            "logging",
            "read",
            query,
            f"--project={project}",
            f"--freshness={since}",
            "--format=json",
            "--order=asc",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    raw = json.loads(result.stdout) if result.stdout.strip() else []
    return extract_payloads(raw)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--project", default=DEFAULT_PROJECT, help=f"GCP project (default: {DEFAULT_PROJECT})"
    )
    parser.add_argument(
        "--since",
        default="7d",
        help="gcloud logging --freshness window, e.g. '24h', '7d', '30d' (default: 7d)",
    )
    args = parser.parse_args(argv)

    try:
        payloads = fetch_log_entries(project=args.project, since=args.since)
    except FileNotFoundError:
        print("error: gcloud CLI not found on PATH", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"error: gcloud logging read failed: {exc.stderr}", file=sys.stderr)
        return 1

    print(format_report(build_report(payloads)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
