"""One-off backfill of the top-level `added: YYYY-MM-DD` key on every
`library/review-cards/*.yaml`, from the date of the git commit that first
added the matching `library/<stem>.md` (`git log --diff-filter=A`).

Text-level insertion (right after the `file:` line) so the rest of each YAML
keeps its exact formatting. Idempotent: a card file that already has `added:`
is left untouched.

Usage:
    python scripts/backfill_library_added_dates.py [--repo .]
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

_ADDED_RE = re.compile(r"^added:", re.MULTILINE)
_FILE_LINE_RE = re.compile(r"^(file:[^\n]*\n)", re.MULTILINE)


def first_added_date(repo: Path, rel_path: str) -> str | None:
    """YYYY-MM-DD of the earliest commit that added `rel_path`, or None."""
    out = subprocess.run(
        ["git", "log", "-m", "--diff-filter=A", "--format=%as", "--", rel_path],
        cwd=repo, check=True, capture_output=True, text=True,
    ).stdout.split()
    return min(out) if out else None


def stamp_added(yaml_text: str, date: str) -> str:
    """Insert `added: <date>` after the `file:` line; no-op if already present."""
    if _ADDED_RE.search(yaml_text):
        return yaml_text
    return _FILE_LINE_RE.sub(lambda m: f"{m.group(1)}added: {date}\n", yaml_text, count=1)


def backfill(repo: Path) -> dict[str, str]:
    """Stamp every card file lacking `added`; returns {library file: date}."""
    stamped: dict[str, str] = {}
    for card_path in sorted((repo / "library" / "review-cards").glob("*.yaml")):
        text = card_path.read_text(encoding="utf-8")
        if _ADDED_RE.search(text):
            continue
        md_name = f"{card_path.stem}.md"
        date = first_added_date(repo, f"library/{md_name}")
        if date is None:
            continue
        card_path.write_text(stamp_added(text, date), encoding="utf-8")
        stamped[md_name] = date
    return stamped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."))
    args = parser.parse_args()
    for name, date in backfill(args.repo).items():
        print(f"{name}\t{date}")


if __name__ == "__main__":
    main()
