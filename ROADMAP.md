# swim-coach: AI Coaching System + PWA for Ultra-Distance Open-Water Swimmers

## Context

Andrew is building a coaching system for open-water swimmers training for ultra-distance events (10k+/marathon swims). First athlete: his wife (Claude Pro subscriber). Research for this discipline is thin, so the system builds a curated research library that adapts evidence from cycling/running/tri (flagged with confidence levels and testable checks — e.g., no power meters in swimming → anchor intensity to CSS pool pace and infer open-water pace with calibratable correction factors). A chat coach agent grounds itself in this library plus the athlete's plan/history.

**Key domain constraint**: the athlete attends coached pool practice 3–5 days/week where the pool coach hands out workout text *reactively* (after practice). The AI coach does not replace the pool coach — it ingests those workout texts post-hoc and orchestrates the ultra periodization *around* them: open-water sessions, long-swim progression, strength, nutrition, and recovery management (sleep/stress/RPE).

**Decisions made**: Phase 1 = repo-first engine used via Claude Code from the mobile app (validation; wife may or may not tolerate this UX). Phase 2 = PWA (vanilla JS + Vite, mtb-skills patterns, GitHub Pages) + FastAPI on Cloud Run + managed Supabase. Design for multiple swimmers from day one (UUID PKs, athlete_id everywhere); auth-lite in v1, real auth later. Workout intake v1: manual/chat + file upload (.fit/.tcx/.csv); Garmin/Strava API sync later.

**Architecture principle**: deterministic Python engine + agent-as-editor. All plan math (zones, load, progression, adaptation rules) lives in a typed, unit-tested package. Claude (skills in Phase 1, API in Phase 2) calls the engine, applies judgment, never does plan math in prose. Phase 1 → 2 reuse is a packaging exercise, not a rewrite.

**Formats**: YAML (pydantic-validated, `schema_version` field) for plans/logs/profiles — human-readable from mobile, diff-friendly, machine-parseable. Markdown for the library and verbatim coach texts.

## Phase 1 — Repo-first coaching engine (usable in days)

### Repo structure
```
CLAUDE.md, README.md, ROADMAP.md, pyproject.toml, .gitignore
library/                      # research library
  INDEX.md                    # summaries + topic→file routing table (RAG-lite router)
  00-conventions.md           # evidence-tag scheme (below)
  01..12-*.md                 # physiology, polarized/80-20, periodization, CSS anchors,
                              # OW pace inference, long-swim progression, strength,
                              # ultra feeding, heat/cold, recovery/HRV, taper, race execution
athletes/<slug>/              # slug chosen at onboarding; athlete_id UUID in profile
  profile.yaml                # CSS, zones, constraints, pool schedule
  events.yaml
  plan/macro.yaml             # meso blocks toward event date
  plan/weeks/2026-W28.yaml    # one file per ISO week
  logs/workouts/*.yaml  logs/wellness/*.yaml  logs/coach-texts/*.md (verbatim)
  notes/decisions.md          # append-only coaching-decision log
engine/                       # installable package `swim-coach-engine` (own pyproject.toml)
  swim_coach/
    models.py    # pydantic v2: Athlete, Event, MacroPlan, WeekPlan, Session, Workout,
                 # Wellness, CoachText — athlete_id: UUID on everything
    zones.py     # CSS from 400/200 test; zone table Z1–Z5; infer_ow_pace(css, wetsuit,
                 # conditions, temp) with named constants cited to library/05
    load.py      # sRPE load, weekly volume, monotony, 7d:28d acute:chronic ratio
    plan.py      # macro scaffold (base→build→peak→taper) + weekly generation
    adapt.py     # deterministic adaptation rule table (below)
    parse_fit.py         # fitdecode>=0.10 (.fit); stdlib ElementTree (.tcx); stdlib csv
    parse_coach_text.py  # regex/grammar parser for pool notation; returns sets + unparsed_lines
    store.py     # FileStore (YAML tree) behind swappable interface — DbStore in Phase 2
    cli.py       # explicit subcommands (below)
.claude/skills/{onboard-athlete,plan-week,log-workout,check-in,adapt,coach}/SKILL.md
tests/unit/      # pytest, no LLM/network; fixtures: athlete tree, .fit samples, coach-text corpus
```
Deps: `pydantic>=2.7`, `PyYAML>=6`, `fitdecode>=0.10`; dev `pytest>=8`. Python 3.12.

### Library evidence discipline (library/00-conventions.md)
- Claims tagged `[EVIDENCE: swim-ultra]` / `[EVIDENCE: swim]` / `[ADAPTED: cycling|running|tri|general-endurance]`.
- Every `[ADAPTED]` block carries `Confidence: high|medium|low` + a `Test:` line — a concrete check against this athlete's data (e.g., "Z2 at CSS+6s/100 should show RPE drift-down over 6 wks; if not, re-anchor zones").
- Numbered citations per file; unsourced statements labeled `Coach judgment:`.
- Files ≤ ~2,500 words so any 3 fit in context. Agent-authored via web research; human-review checkbox per file in ROADMAP before treated as grounding truth.

### Engine CLI (every skill shells out to these)
`python -m swim_coach.cli`: `validate --athlete <slug>` (pydantic-validate whole tree, nonzero exit on error — runs in CI) · `zones` (CSS + zone table → profile) · `scaffold-macro` · `plan-week` (pool sessions emitted as placeholders `source: pool_coach`) · `ingest --file x.fit|tcx|csv` · `parse-coach-text` · `summarize --weeks 4` (compact JSON: volume, load, wellness trend, compliance — reused by Phase 2 context assembler) · `adapt --week <iso>` (draft next week + machine rationale).

### Adaptation rules (adapt.py — constants cited to library files, all unit-tested)
- Wellness composite red (≤2.0) OR 7d:28d load ratio >1.4 → cut volume 20–30%, hold long swim, add recovery day.
- Compliance <70% → repeat progression step.
- All green + compliance ≥90% → advance (volume +≤8%/wk, long swim +≤10–15%).
- Pool-coach sessions are fixed constraints: engine budgets remaining load around their *actual* delivered load and balances intensity distribution (80/20 across total swim time).
- `/adapt` skill reviews the draft with judgment (may not exceed engine caps), finalizes, appends rationale to notes/decisions.md.

### Skills
| Skill | Behavior |
|---|---|
| /onboard-athlete | Interview (incl. whether pool coach ever shares focus in advance → optional `expected_pool_focus`; HRV device availability) → create tree, scaffold macro + first week |
| /log-workout | Chat description → Workout YAML; pasted coach text → save verbatim, run deterministic parse, finish unparsed lines conversationally, **add new notation to test fixtures**; file → `cli ingest` |
| /check-in | 60-sec wellness capture; red flags → same-day modification suggestion (library/10) |
| /plan-week | `cli plan-week` → present conversationally → adjust → validate → commit |
| /adapt | Sunday ritual: summarize + adapt draft → judgment review → finalize + rationale |
| /coach | Q&A: route via INDEX.md, load 2–4 library files + summarize output; surface evidence tags ("adapted from cycling, medium confidence"); read-only unless asked |

### Project CLAUDE.md contents
Data-flow rules (all changes via CLI + YAML; never hand-compute in chat; `cli validate` before commit; coach text verbatim first), grounding rule (cite library files; gaps → draft section flagged UNREVIEWED), git workflow (engine/library changes via feature branch + PR; athlete daily data commits straight to main + push immediately — per-day files make conflicts near-impossible; pull before write), safety rails (never delete logs; volume/long-swim caps need explicit athlete confirmation; pain report → stop-and-assess).

### Wife's access
Private GitHub repo + collaborator invite; she uses Claude Code (claude.ai → Code) on mobile against the repo. Fallbacks: per-day files avoid conflicts; she can message workouts to Andrew who logs them; .fit files via Garmin Connect export into `athletes/<slug>/inbox/` (or manual logging until PWA upload exists). This friction is exactly why Phase 2 follows quickly.

### CI (adapted from mtb-skills ci.yml)
Python 3.12 → `pip install -e engine .[dev]` → `pytest tests/unit -v` → `cli validate` on the real athlete tree. Node/e2e jobs added in Phase 2.

## Phase 2 — PWA + FastAPI backend

- `backend/app/`: FastAPI, JSON-logging middleware, `/health`, fail-fast config. Routes: `POST /api/chat` (SSE), `GET /api/plan`, `GET|POST /api/workouts` + `POST /api/workouts/upload` (multipart), `POST /api/coach-texts` (two-stage parse), `GET|POST /api/wellness`, `GET /api/athlete/me`.
- **Engine reuse**: container `pip install ./engine`; same models validate API payloads; `store.py` gains `DbStore` (same interface as FileStore — the seam built in Phase 1). Library markdown ships read-only in the image. One-shot `scripts/migrate_files_to_db.py` moves Phase 1 data; DB becomes source of truth, library + engine stay repo-first.
- **Supabase** (psycopg3 against transaction pooler, port 6543; explicit SQL migrations in `supabase/migrations/`): tables `athletes, api_tokens, events, macro_plans, week_plans, sessions, workouts, coach_texts, wellness_checkins, chat_messages, uploaded_files` — all UUID PKs, athlete_id FK, timestamps, schema_version. Raw uploads to Supabase Storage. RLS deferred (service-role only from backend) — noted in migration; enabled with real auth in Phase 3.
- **Chat context assembly** (built for prompt caching, stable→volatile): cached system block A = persona + rules + 00-conventions + INDEX (byte-stable); cached block B = 2–4 routed library files (deterministic route buckets share cache); uncached per-request = profile/zones, macro block, current+next week, engine `summarize` output, last ~20 messages. ~20–30k input tokens/request. Model `claude-sonnet-5` via `CLAUDE_MODEL` env var; `max_tokens` 2048; log `usage` incl. cache reads; on Sonnet 5 omit temperature/top_p. Optional single `log_workout` tool; other writes via explicit endpoints.
- **Auth-lite**: per-athlete opaque bearer token, sha256-hashed in `api_tokens`; dependency resolves token→athlete_id, every query filtered by it; CORS locked to Pages origin; per-token rate limit on /api/chat. Swap for Supabase Auth JWT in Phase 3 without touching routes.
- **PWA** (`web/`, cloned mtb-skills patterns: vite.config.js + vite-plugin-pwa, main.js state machine + data-a delegation, views.js HTML strings, log.js verbatim): views Today (session card + done/RPE), Week, Log (paste coach text / upload / manual), Check-in (5 sliders), Chat, Settings. Offline: precached shell + localStorage write-queue flushed on reconnect (pool decks have bad signal). Deploy via mtb-skills deploy.yml → GitHub Pages.
- **Docker/Cloud Run**: python:3.12-slim, non-root, PORT respected; Artifact Registry → `gcloud run deploy --min-instances=0`; secrets via Secret Manager. Manual deploy first, workflow second.
- **CI additions**: backend-unit (pytest + TestClient w/ fake store); api-integration per global standards — `tests/api/` with `requests`, per-run `run_tag` UUID on created rows, delete-by-tag teardown, exit-code discipline; Playwright e2e reusing mtb-skills conftest.py against `web/dist` with a stub API.

## Phase 3 (sketch)
Strava OAuth webhook sync first (far easier API access than Garmin), Garmin Health API if approved; Supabase Auth magic-link + RLS policies + retire api_tokens; PWA onboarding flow (CSS test wizard) + per-athlete spend caps.

## Phase 1 build order (test-first)
1. **Day 1**: scaffolding (pyproject, gitignore, README, CLAUDE.md, CI) → `test_models.py`→`models.py`+`store.py` YAML round-trip → `test_zones.py`→`zones.py`.
2. **Day 2**: `test_plan.py`→`plan.py`, `cli` (validate/zones/scaffold-macro/plan-week) → onboard the real athlete: profile, events, macro, first week; `cli validate` green in CI on real tree.
3. **Day 3**: collect 5–10 real pool-coach texts (**highest-value fixtures in the project — get these first**) → `test_parse_coach_text.py`→parser → one real .fit export → `test_parse_fit.py`→`parse_fit.py` → skills log-workout + check-in; dry-run from Andrew's phone.
4. **Day 4**: `test_load.py`→`load.py`; `test_adapt.py`→`adapt.py` + cli summarize/adapt → remaining skills → library files 00, INDEX, 03–06 (they ground engine constants; every constant cites its file); rest of library over following week.
5. **Day 5**: add wife as collaborator; she runs /check-in and /log-workout from Claude mobile. First real /adapt the following Sunday.

**Gate to Phase 2**: CI green, real tree validates, one full logged week + one adapted week end-to-end.

## Verification
- Phase 1: `pytest tests/unit -v` all green; `cli validate --athlete <slug>` exit 0 on real data; property checks on adapt (never exceeds caps, red wellness always reduces, output always validates); end-to-end: log a real week, run /adapt, inspect rationale.
- Phase 2: requests+run-tag API harness green locally and in CI; `curl /health`; verified cache hits in usage logs; Playwright e2e on PWA; wife completes check-in + coach-text log + chat round-trip on her phone.

## Risks
1. Claude-mobile friction for the wife (biggest Phase 1 risk) — validate day 5, not later; PWA is the remedy.
2. Coach-text notation may resist regex — if <50% parses deterministically after 2 weeks, accept agent-first parsing with schema validation as the norm.
3. Library leans on [ADAPTED] claims — the Test: discipline only pays if /adapt actually checks them; include a library-review step in the Sunday ritual.
4. CSS drifts — schedule re-test every 4–6 weeks as a session type; OW correction factors are guesses until 3–5 logged OW swims calibrate them.
5. Anthropic spend (Phase 2) — rate limit + per-request usage logging from day one.

## Reference templates (copy from mtb-skills)
`vite.config.js`, `.github/workflows/{ci,deploy}.yml`, `tests/e2e/conftest.py`, `src/{main,views,storage,log}.js`, CLAUDE.md conventions, `app/schema.md` data-model philosophy.
