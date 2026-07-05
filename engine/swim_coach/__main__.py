"""Allows `python -m swim_coach <command> ...` as an alias for
`python -m swim_coach.cli <command> ...`."""

from swim_coach.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
