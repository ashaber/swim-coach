# swim-coach

AI coaching system + PWA for ultra-distance open-water swimmers. First athlete: Andrew's wife (slug chosen at onboarding).

**The full approved plan is in `ROADMAP.md` — read it before doing anything.** Current status: Phase 1, nothing built yet. Start at "Phase 1 build order", Day 1, and work test-first (write the failing test, then the code).

## Standing rules (from the approved plan)
- Deterministic Python engine (`engine/swim_coach/`) owns ALL plan math — zones, load, progression, adaptation. Agent sessions call `python -m swim_coach.cli ...` and apply judgment; never hand-compute zones/loads/volumes in chat.
- Data files: YAML (pydantic-validated, `schema_version` field) for plans/logs/profiles; Markdown for the research library and verbatim pool-coach texts. Coach text is saved verbatim to `logs/coach-texts/` BEFORE any parsing.
- Run `python -m swim_coach.cli validate --athlete <slug>` before committing athlete-data changes.
- Every engine constant (zone offsets, progression caps, adaptation thresholds) must cite its `library/` file.
- Library evidence discipline: claims tagged `[EVIDENCE: swim-ultra|swim]` or `[ADAPTED: cycling|running|tri|general-endurance]`; every `[ADAPTED]` block carries `Confidence:` and a `Test:` line. Unsourced statements labeled `Coach judgment:`.
- Git: engine/library/skill changes via feature branch + PR; athlete daily data (logs, wellness, weekly plans) commits straight to main and pushes immediately; pull before write.
- Safety rails: never delete logs; weekly volume +≤8% and long swim +≤15% without explicit athlete confirmation; any pain report → stop-and-assess.
- Tests: `pytest tests/unit -v` — no LLM or network in tests; all green before any task is "done".
- Reference templates live in `../mtb-skills` (vite.config.js, .github/workflows/{ci,deploy}.yml, tests/e2e/conftest.py, src/{main,views,storage,log}.js).

## Key domain constraint
The athlete attends coached pool practice 3–5 days/week; the pool coach hands out workout text reactively (after practice). This system does NOT replace the pool coach — it ingests those texts post-hoc and plans the ultra periodization around them: open-water sessions, long-swim progression, strength, nutrition, recovery (sleep/stress/RPE).
