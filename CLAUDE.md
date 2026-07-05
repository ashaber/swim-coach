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


## Build Guidelines

### Test-driven workflow
- Every module requires test cases before shipping
- Write tests first — confirm they fail — then code until passing
- Never skip tests to move faster
- All tests must pass before a feature is considered done

### Test tooling
**Vitest** — unit tests for JS logic (storage, rubric calculations, trail readiness)
- Lives in `tests/unit/`
- Run with `npm run test`
- Native ES module support — zero config with Vite
- Mocks `localStorage` cleanly

**Playwright (Python)** — e2e/UI tests for full browser flows
- Lives in `tests/e2e/`
- Run with `npm run test:e2e` (uses `.venv/bin/pytest` — no pyenv activation needed)
- `.venv` at project root: Python 3.11.9, recreate with `tests/e2e/requirements.txt` + `playwright install chromium`
- Exit code 0 = all pass, non-zero = failure — safe for CI

### What to test (minimum per feature)
- App loads at root URL
- Feature renders and accepts input correctly
- localStorage persists across page reload (simulate by reloading the page context)
- App functions correctly with network set to offline (`context.set_offline(True)`)
- Mobile viewport: test at 390×844 (iPhone 14) and 412×915 (Android)

### Browsers to cover
- Chromium (Android Chrome proxy)
- WebKit (iOS Safari proxy)
- Real device test on Android and iOS before marking Phase DOD complete

---


## Branching and Release Standards

### Branch workflow
- All work happens on feature branches — never commit directly to `main`
- Branch naming: `phase2/feature-name`, `phase3/feature-name`, etc.
- Merge to `main` via Pull Request only
- PR description must list which DOD items are being checked off
- Do not merge a PR with failing Playwright tests
- Do not delete a branch until CI passes on `main` after the merge — the branch is the rollback point if CI catches a regression post-merge

### PR checklist (every PR)
- [ ] Vitest unit tests written and passing (`npm run test`)
- [ ] Playwright e2e tests passing on Chromium + WebKit (`npm run test:e2e` — runs all of `tests/e2e/`, same as CI)
- [ ] No dead code or commented-out code
- [ ] `src/log.js` used for all logging — no bare `console.*` in app code
- [ ] DOD items addressed are noted in PR description

### Releases
- Tag `main` at the completion of each phase: `git tag v1.0`, `v2.0`, etc.
- Provides a clean rollback point before the next phase begins
- Update README.md and ROADMAP.md before tagging

---


## Logging

PWAs run in the browser — no stdout, no server. Use `src/log.js` for all logging. See file for implementation.

### Rules
- Import and use `log` from `src/log.js` everywhere — never use `console.*` directly in app code
- Log is included in JSON export so a coach can email it for field debugging
- Never log PII (athlete names should use IDs in log entries)
- Ring buffer — max 200 entries, oldest dropped first

### What to log
- App init: version, storage key counts
- Each user action: feature, athlete_id, skill, outcome
- Storage read/write errors with context
- Any caught exception: message + stack

---
