"""Structured JSON logging to stdout/stderr.

Per Andrew's global standard (~/.claude/CLAUDE.md "Logging"): every service
logs structured JSON to stdout, never to files inside containers. The
stdlib `logging` module's `extra=` kwarg merges keys directly into the
`LogRecord.__dict__` rather than nesting them under an `"extra"` key, which
makes a faithful, simple JSON formatter fiddlier than it looks -- so instead
of fighting stdlib's formatter internals, this module exposes a tiny logger
object with the same call shape as the Node.js pattern in the global
standard (`log.info(msg, **fields)`), which is easier to keep correct and to
assert against in tests.

Errors go to stderr, everything else to stdout -- both are captured by
Docker/Cloud Run's log collector identically, so this still satisfies
"never log to files inside containers."
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any


class JsonLogger:
    """A minimal structured logger: one JSON object per line, to stdout
    (info/warn) or stderr (error)."""

    def __init__(self, name: str) -> None:
        self.name = name

    def _emit(self, level: str, msg: str, stream: Any, fields: dict[str, Any]) -> None:
        payload = {
            "level": level,
            "msg": msg,
            "logger": self.name,
            "ts": datetime.now(timezone.utc).isoformat(),
            **fields,
        }
        # default=str so any stray non-JSON-serializable value (Path, UUID,
        # etc.) degrades to its string form instead of raising and losing
        # the whole log line.
        print(json.dumps(payload, default=str), file=stream, flush=True)

    def info(self, msg: str, **fields: Any) -> None:
        self._emit("info", msg, sys.stdout, fields)

    def warn(self, msg: str, **fields: Any) -> None:
        self._emit("warn", msg, sys.stdout, fields)

    def error(self, msg: str, **fields: Any) -> None:
        self._emit("error", msg, sys.stderr, fields)


def get_logger(name: str) -> JsonLogger:
    return JsonLogger(name)
