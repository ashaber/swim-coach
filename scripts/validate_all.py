#!/usr/bin/env python3
"""Validate every athlete under athletes/ via `swim_coach.cli validate`.

Run from the repo root (CI does this right after `pytest tests/unit -v`):

    python scripts/validate_all.py

Exit codes:
  0 - every athlete tree validated clean, OR athletes/ doesn't exist / is
      empty yet (nothing to validate -- a note is printed either way, not
      an error, since a brand-new checkout has no athlete data yet).
  1 - at least one athlete tree failed validation.

Takes an optional positional arg overriding the athletes/ directory (used
by tests); otherwise defaults to "athletes" relative to the current
working directory.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from swim_coach.cli import main as cli_main


def validate_all(athletes_dir: Path) -> int:
    if not athletes_dir.exists():
        print(json.dumps({"note": f"{athletes_dir} does not exist yet; nothing to validate"}))
        return 0

    slugs = sorted(p.name for p in athletes_dir.iterdir() if p.is_dir())
    if not slugs:
        print(json.dumps({"note": f"{athletes_dir} is empty; nothing to validate"}))
        return 0

    failures = []
    for slug in slugs:
        exit_code = cli_main(["--base-dir", str(athletes_dir), "validate", "--athlete", slug])
        if exit_code != 0:
            failures.append(slug)

    if failures:
        print(json.dumps({"error": "one or more athletes failed validation", "athletes": failures}))
        return 1

    print(json.dumps({"validated": slugs}))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    athletes_dir = Path(argv[0]) if argv else Path("athletes")
    return validate_all(athletes_dir)


if __name__ == "__main__":
    raise SystemExit(main())
