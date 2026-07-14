#!/usr/bin/env python3
"""Human-eyeball smoke test for the coach's voice against a DEPLOYED backend.

**Needs network + a real LLM call** (every prompt here goes all the way to
Claude through the live `/api/chat` endpoint) -- this is deliberately NOT run
in CI (repo rule: no LLM/network calls in tests). It exists so a human can
read the coach's actual replies and judge tone/voice, which
`tests/api/test_context.py` cannot do (it only asserts prompt *text*, never
what a model does with it).

Fires ~6 representative prompts at `--base-url` (a deployed Cloud Run
backend, or a local `uvicorn` instance) and prints each reply for review.
Run it once against the CURRENT deployment before merging `backend/coach-voice`
(to see the "before" voice), then again after the PR's deploy dispatch lands
(to see the "after") -- that side-by-side is the real acceptance test for a
voice change, per ROADMAP.md's coach-voice slice.

Usage:
    python scripts/coach_smoke.py --base-url https://swim-coach-api.example.run.app --token $API_TOKEN
    API_TOKEN=... COACH_BASE_URL=... python scripts/coach_smoke.py
    python scripts/coach_smoke.py --base-url http://localhost:8000 --token dev-token --expert

Flags:
    --base-url URL   backend root (default: env COACH_BASE_URL)
    --token TOKEN    bearer token (default: env API_TOKEN)
    --athlete SLUG   athlete slug to chat as (default: renee)
    --expert         also (or only, with --expert-only) run every prompt in
                     expert mode, so the athlete-mode/expert-mode voice
                     difference can be read side by side
    --expert-only    skip athlete mode entirely, run only expert mode
    --timeout SECS   per-request read timeout (default: 60)

Exit codes: 0 = every prompt got a response (of whatever content -- this
script does not grade the reply, a human does); 1 = a request errored or a
required arg/env var was missing.

Structured JSON logging to stdout for the request bookkeeping (per the
global standard); the coach's replies themselves are printed as plain
human-readable text -- that output IS the deliverable of this script.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Iterator

import requests

# Six representative prompts (ROADMAP.md coach-voice slice, ordered a-f):
#   (a) fueling question
#   (b) a niggle/soreness report
#   (c) "I feel completely done at 90 minutes every long swim"
#   (d) a plan-change request
#   (e) a question the library definitely doesn't cover
#   (f) an acute-symptom safety case -- confirms the override still fires
#       verbatim regardless of voice/mode
PROMPTS: list[tuple[str, str]] = [
    (
        "(a) fueling question",
        "How much carb should I be taking in per hour on a 3-hour open water swim?",
    ),
    (
        "(b) niggle/soreness report",
        "My left shoulder has felt a little cranky the last two sessions, nothing sharp, "
        "just achy after. Should I back off?",
    ),
    (
        "(c) 90-minute wall",
        "I feel completely done -- like I have nothing left -- at 90 minutes into every "
        "single long swim lately. What's going on?",
    ),
    (
        "(d) plan-change request",
        "This week feels too easy, I want to add another long swim before Saturday. Can we do that?",
    ),
    (
        "(e) out-of-library question",
        "What's the optimal breathing pattern bilateral vs unilateral for reducing "
        "shoulder impingement risk over a multi-year masters career?",
    ),
    (
        "(f) acute-symptom safety case",
        "I've got some chest tightness and my heart is pounding weird, it started mid-swim "
        "and hasn't fully gone away.",
    ),
]


def _log(level: str, msg: str, **meta: object) -> None:
    print(
        json.dumps(
            {"level": level, "msg": msg, **meta, "ts": datetime.now(timezone.utc).isoformat()}
        ),
        file=sys.stderr,
    )


def _iter_sse_text(lines: Iterator[bytes]) -> Iterator[dict[str, Any]]:
    """Parses `data: {...}\\n\\n`-framed SSE lines (see `app.claude._sse`)
    into their decoded JSON payloads, skipping keep-alive blanks."""
    for raw in lines:
        if not raw:
            continue
        line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        if not line.startswith("data: "):
            continue
        yield json.loads(line[len("data: ") :])


def run_prompt(
    base_url: str, token: str, athlete: str, message: str, *, expert_mode: bool, timeout: float
) -> str:
    """POSTs one chat turn and collects the streamed text into a single
    reply string. Raises `requests.HTTPError` / `requests.RequestException`
    on transport or auth failure -- the caller reports and continues rather
    than letting one bad prompt abort the whole smoke run."""
    payload = {
        "message": message,
        "history": [],
        "athlete": athlete,
        "expert_mode": expert_mode,
    }
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    response = requests.post(
        f"{base_url.rstrip('/')}/api/chat",
        json=payload,
        headers=headers,
        stream=True,
        timeout=timeout,
    )
    response.raise_for_status()

    reply_parts: list[str] = []
    for event in _iter_sse_text(response.iter_lines()):
        event_type = event.get("type")
        if event_type == "text":
            reply_parts.append(event["text"])
        elif event_type == "error":
            reply_parts.append(f"\n[STREAM ERROR: {event.get('error')}]")
        elif event_type == "refusal":
            reply_parts.append("\n[MODEL REFUSAL]")
    return "".join(reply_parts)


def _print_reply(label: str, message: str, mode_label: str, reply: str) -> None:
    width = 78
    print("=" * width)
    print(f"{label}  [{mode_label}]")
    print("-" * width)
    print(f"Q: {message}")
    print("-" * width)
    print(reply.strip() or "(empty reply)")
    print("=" * width)
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", default=os.environ.get("COACH_BASE_URL"))
    parser.add_argument("--token", default=os.environ.get("API_TOKEN"))
    parser.add_argument("--athlete", default="renee")
    parser.add_argument(
        "--expert",
        action="store_true",
        help="also run every prompt in expert mode, after athlete mode",
    )
    parser.add_argument(
        "--expert-only",
        action="store_true",
        help="run only expert mode (skip athlete mode entirely)",
    )
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args(argv)

    if not args.base_url:
        _log("error", "missing --base-url / COACH_BASE_URL")
        return 1
    if not args.token:
        _log("error", "missing --token / API_TOKEN")
        return 1

    modes: list[tuple[str, bool]] = []
    if not args.expert_only:
        modes.append(("athlete mode", False))
    if args.expert or args.expert_only:
        modes.append(("expert mode", True))

    _log(
        "info",
        "coach_smoke starting",
        base_url=args.base_url,
        athlete=args.athlete,
        modes=[m[0] for m in modes],
        prompt_count=len(PROMPTS),
    )

    had_error = False
    for label, message in PROMPTS:
        for mode_label, expert_mode in modes:
            try:
                reply = run_prompt(
                    args.base_url,
                    args.token,
                    args.athlete,
                    message,
                    expert_mode=expert_mode,
                    timeout=args.timeout,
                )
            except requests.RequestException as exc:
                _log("error", "prompt failed", label=label, mode=mode_label, error=str(exc))
                _print_reply(label, message, mode_label, f"[REQUEST FAILED: {exc}]")
                had_error = True
                continue
            _log("info", "prompt complete", label=label, mode=mode_label, reply_chars=len(reply))
            _print_reply(label, message, mode_label, reply)

    return 1 if had_error else 0


if __name__ == "__main__":
    sys.exit(main())
