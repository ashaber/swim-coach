# swim-coach

AI coaching system + PWA for ultra-distance open-water swimmers. Phase 1 is a
deterministic Python engine (`engine/swim_coach/`) that owns all plan math —
zones, load, progression, adaptation — validated against typed YAML athlete
data. See `ROADMAP.md` for the full plan and `CLAUDE.md` for standing rules.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e "engine/[dev]"
```

## Running tests

```bash
pytest tests/unit -v
```

No LLM calls and no network access happen in the test suite.
