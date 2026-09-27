"""scripts/route_report.py -- parsing/aggregation only (IDEA 025 step 1).

No network in these tests: `fetch_log_entries` (the only function that
touches `gcloud`) is never called. `extract_payloads`/`build_report`/
`format_report` are pure functions exercised against a small fixture at
tests/api/fixtures/route_report_raw.json, shaped like a real
`gcloud logging read --format=json` response (including a decoy entry with
no `jsonPayload`, same as a real platform/access-log line would be).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from route_report import (  # noqa: E402
    CACHE_READ_MULTIPLIER,
    CACHE_WRITE_5M_MULTIPLIER,
    INPUT_PRICE_PER_MTOK,
    OUTPUT_PRICE_PER_MTOK,
    _call_cost_usd,
    build_report,
    extract_payloads,
    format_report,
)

FIXTURE = REPO_ROOT / "tests" / "api" / "fixtures" / "route_report_raw.json"


def _raw_entries() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_extract_payloads_skips_entries_with_no_json_payload() -> None:
    raw = _raw_entries()
    payloads = extract_payloads(raw)
    # The fixture's first entry is a decoy textPayload-only line.
    assert len(payloads) == len(raw) - 1
    assert all("jsonPayload" not in p for p in payloads)  # unwrapped, not the raw envelope
    assert {p["msg"] for p in payloads} == {"library route", "claude turn complete", "route miss"}


def test_pricing_constants_match_sonnet_5_documented_rates() -> None:
    # IDEAS.md's "IDEA 022 -- RESULTS" section: "$2/$10 per MTok, cache
    # write 1.25x, read 0.1x".
    assert INPUT_PRICE_PER_MTOK == 2.0
    assert OUTPUT_PRICE_PER_MTOK == 10.0
    assert CACHE_READ_MULTIPLIER == 0.1
    assert CACHE_WRITE_5M_MULTIPLIER == 1.25


def test_call_cost_usd_matches_hand_computed_value() -> None:
    entry = {
        "input_tokens": 500,
        "output_tokens": 100,
        "cache_read_input_tokens": 2000,
        "cache_creation_input_tokens": 0,
    }
    # (500*2 + 100*10 + 2000*2*0.1 + 0) / 1e6 = (1000+1000+400)/1e6
    assert _call_cost_usd(entry) == 0.0024


def test_build_report_aggregates_per_day_with_hand_computed_values() -> None:
    payloads = extract_payloads(_raw_entries())
    report = build_report(payloads)

    assert list(report.keys()) == ["2026-09-20", "2026-09-21"]  # sorted ascending

    day1 = report["2026-09-20"]
    assert day1.chat_requests == 2  # req-A, req-B
    assert day1.misses_by_kind == {"reference": 1}
    assert day1.requests_with_miss == {"req-A"}
    assert day1.miss_rate == 0.5
    assert day1.total_misses == 1
    # Only req-A's iteration>0 call counts (req-B had no miss at all).
    assert round(day1.extra_cost_usd, 6) == 0.0024

    day2 = report["2026-09-21"]
    assert day2.chat_requests == 1  # req-C
    assert day2.misses_by_kind == {"topic": 1}
    assert day2.miss_rate == 1.0
    # req-C's iteration>0 call: (300*2 + 50*10 + 1000*2*0.1) / 1e6
    assert round(day2.extra_cost_usd, 6) == 0.0013


def test_build_report_on_empty_input_is_empty() -> None:
    assert build_report([]) == {}


def test_format_report_reads_as_expected_and_handles_empty() -> None:
    payloads = extract_payloads(_raw_entries())
    text = format_report(build_report(payloads))
    assert "2026-09-20: 2 chat requests" in text
    assert "reference: 1" in text
    assert "miss rate 50.0%" in text
    assert "2026-09-21: 1 chat requests" in text
    assert "topic: 1" in text
    assert "miss rate 100.0%" in text
    assert format_report({}) == "no chat requests in this window"
