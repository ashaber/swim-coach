# swim-coach: AI Coaching System + PWA for Ultra-Distance Open-Water Swimmers

## Context

Andrew is building a coaching system for open-water swimmers training for ultra-distance events (10k+/marathon swims). First athlete: his wife (Claude Pro subscriber). Research for this discipline is thin, so the system builds a curated research library that adapts evidence from cycling/running/tri (flagged with confidence levels and testable checks — e.g., no power meters in swimming → anchor intensity to CSS pool pace and infer open-water pace with calibratable correction factors). A chat coach agent grounds itself in this library plus the athlete's plan/history.

**Key domain constraint**: the athlete attends coached pool practice 3–5 days/week where the pool coach hands out workout text *reactively* (after practice). The AI coach does not replace the pool coach — it ingests those workout texts post-hoc and orchestrates the ultra periodization *around* them: open-water sessions, long-swim progression, strength, nutrition, and recovery management (sleep/stress/RPE).

**Decisions made**: Phase 1 = repo-first engine used via Claude Code from the mobile app (validation; wife may or may not tolerate this UX). Phase 2 = PWA (vanilla JS + Vite, mtb-skills patterns, GitHub Pages) + FastAPI on Cloud Run + managed Supabase. Design for multiple swimmers from day one (UUID PKs, athlete_id everywhere); auth-lite in v1, real auth later. Workout intake v1: manual/chat + file upload (.fit/.tcx/.csv); Garmin/Strava API sync later.

**Architecture principle**: deterministic Python engine + agent-as-editor. All plan math (zones, load, progression, adaptation rules) lives in a typed, unit-tested package. Claude (skills in Phase 1, API in Phase 2) calls the engine, applies judgment, never does plan math in prose. Phase 1 → 2 reuse is a packaging exercise, not a rewrite.

**Formats**: YAML (pydantic-validated, `schema_version` field) for plans/logs/profiles — human-readable from mobile, diff-friendly, machine-parseable. Markdown for the library and verbatim coach texts.

---

## Status & current roadmap (updated 2026-07-06)

The sections from "Phase 1" down are the original approved build plan, kept as the build record. This section is the live status and the near-term direction.

### Done — shipped and live

- **Phase 1 engine (Days 1–4): complete.** `engine/swim_coach/` owns all plan math — models/store (YAML `FileStore` behind a swappable interface), CSS zones + open-water pace inference, macro scaffold + weekly generation, sRPE/ACWR/monotony load, deterministic adaptation rules, `.fit`/`.tcx`/`.csv` + coach-text parsers, and the `cli` (validate/zones/scaffold-macro/plan-week/ingest/parse-coach-text/summarize/adapt). Skills wired: `/onboard-athlete /plan-week /log-workout /check-in /adapt /coach`. Library files 00/INDEX/03–06 ground the engine constants; citations are title-only (fabricated URLs/IDs stripped). Test suite green.
- **Renee onboarded.** `athletes/renee/`: profile (CSS 1:30/100m, M/W/F USMS pool, Oura HRV), events (Greece UltraSwim 33.3 — single-day 33.3k, Sep 18 2026; Bear Lake Monster 10K B-race, Jul 18 2026), macro toward Greece, W28/W29 hand-tuned around the Thu 7/9 Lucky Peak 5-hour swim. `event_format` is a first-class parameter (single-day ↔ 4-day stage switchable by mid-Aug; a second event in Dec is TBD format).
- **Phase 2 coach chat: LIVE.** FastAPI backend on GCP Cloud Run (scale-to-zero), model `claude-opus-4-8`, adaptive thinking, prompt-cached stable prefix, SSE streaming, bearer auth + CORS + rate limit. The coach grounds in library + plan + engine `summarize` and can call `/adapt` as a tool; IDEA 005 "I don't know" + research-question logging + expert-mode. **Backend:** https://swim-coach-api-445273334913.us-central1.run.app — **PWA:** https://ashaber.github.io/swim-coach/ (tabs Plan / Coach / Settings; Settings pre-defaults the backend URL so the athlete only pastes her token). Secrets in GCP Secret Manager; the image is secret-free. Verified end-to-end with a real grounded response.

### Now — simmer on real usage (~days to a couple of weeks)

Load real data and let the system run before building more. Goal: real inputs into the coach + first genuine `/adapt`, and honest feedback on the UX.

- Log Renee's real swims (Mon 2–3 hr, Thu 5 hr Lucky Peak, and pool-coach texts) via `/log-workout`; capture wellness via `/check-in`.
- Run the first real `/adapt` off real data (not hand-tuned weeks).
- Get Renee actually using the PWA (share URL + token; single-athlete / single-token for now) and collect what's confusing, wrong, or missing.
- **Known limitation to work around during the simmer:** the live backend reads the `athletes/` tree baked into the image at deploy time. Logging a workout to the repo updates the **Plan** tab on the next Pages deploy, but the **coach chat** won't see it until the backend is redeployed. Redeploy after a data load when the coach needs current data. Phase 2.5 removes this limitation.

### Phase 2.5 — Supabase/DB layer, built during the simmer (careful, non-disruptive)

Build the database while the system simmers, without disrupting Renee's live usage. This also fixes the data-freshness limitation above: the coach and PWA read **live** data instead of a baked snapshot.

- **Behind the existing seam.** Add `DbStore` implementing the same interface as `FileStore` (the seam built in Phase 1). `FileStore` keeps working throughout — no rewrite, a packaging change.
- **Supabase, managed** (per the architecture principles — do not self-host Postgres). psycopg3 against the transaction pooler; explicit SQL migrations in `supabase/migrations/`. Tables per the Phase 2 plan below (athletes, events, macro/week plans, sessions, workouts, coach_texts, wellness, chat_messages, uploaded_files — UUID PKs, `athlete_id` FK, timestamps, `schema_version`). RLS deferred (service-role from backend) until real auth in Phase 3.
- **Migrate cautiously.** One-shot `scripts/migrate_files_to_db.py` copies the current file tree → Supabase; the file tree stays as archive/source-of-truth until the DB is validated. Shadow/dual-read to compare before cutover. Cut the backend over to `DbStore` behind a config flag so rollback is instant; do the cutover during low usage. The PWA and coach stay up the whole time.
- **Payoff:** logged workouts and check-ins reach the live coach with no redeploy, and multi-athlete becomes structurally possible.

### UI design pass (parallelizable — optional, candidate now)

A Claude design pass to tighten the PWA UI. Low-risk and independent of the DB work, so it can run alongside the simmer.

- Design pass on the existing tabs: visual system, spacing, mobile polish, both light/dark themes — consistent with the hosted plan-artifact design language.
- Fill in the remaining IDEA 003 tabs as the data endpoints land (Daily Check-in → wellness; Load workout → workout-log; Library; Athlete/Settings).
- Dragonfly branding (IDEA 001): logo + PWA icons.

### Phase 3 — later (unchanged in intent)

Strava OAuth webhook sync first (Garmin Health API if approved); Supabase Auth magic-link + RLS, retiring the shared bearer token; PWA onboarding wizard (CSS-test) + per-athlete spend caps; multi-swimmer onboarding.

### PROPOSED — feedback-triggered library research loop (design only, not yet built)

Design worked out 2026-07-11; nothing below is implemented. Goal: close the
loop from "the coach couldn't answer" to "the library has a reviewed answer,"
without reintroducing the fabrication failure the library evidence discipline
exists to prevent (see `library/00-conventions.md`'s account of the
Gemini-fabricated URLs/PubMed IDs). Depends on the CI library-evidence gate
being built on branch `ci/library-evidence-gate` — see step 4.

1. **Trigger — already exists.** The chat coach's IDEA-005 "I don't know"
   behavior calls the `log_open_question` tool (`backend/app/tools.py`)
   whenever a library gap blocks an answer, which writes a
   `swim_coach.models.Feedback` row via `store.save_feedback` with
   `type="research_question"`, `source="coach"`, `body` = the question
   verbatim, `context={"topic": ..., "expert_mode": ...}`, `status="open"`.
   PR #20 made this durable (`GET/POST /api/feedback`, `backend/app/routes/
   feedback.py`) — it previously wrote to `research/open-questions.jsonl`,
   an ephemeral file Cloud Run silently wiped on every scale-to-zero.
   Athlete-submitted feedback (`type` = `feature_request` / `comment` / `bug`,
   `source="athlete"`, via the PWA Feedback tab) is a **separate stream, not
   a research trigger** — `routes/feedback.py` explicitly rejects athletes
   submitting `type="research_question"` since only the coach tool logs that
   type.
2. **Batched, rate-limited drafting — not one run per question.** A scheduled
   job (weekly) sweeps `Feedback` rows with `type="research_question"` and
   `status="open"`, clusters related ones by topic, and drafts at most a
   small number of library sections/files per run.
   - *Rationale:* per-question drafting would outrun the human reviewer and
     turn review into rubber-stamping — which defeats the entire point of
     the review gate (step 5). Batching also gives clustering a chance to
     merge overlapping questions into one section instead of one per
     question.
3. **The drafting recipe — already proven manually 3×** (strength/`07`,
   recovery/`10`, the Oura device-trust amendment to `10`). A research pass
   produces a **verified dossier**: each candidate source confirmed to exist
   by title+author web search and recorded as title + author + year +
   journal — **never a URL or PubMed/PMC/DOI ID**, since a prior Gemini-
   assisted pass fabricated exactly those and poisoned the repo (the reason
   `reference_list.md` is now the only trustworthy citation source). Sources
   carry ✓/~/⚠ verification markers through to the dossier; summaries are
   honest 2–4 sentences with no embellishment; conflicts of interest are
   preserved rather than smoothed over (e.g. the Oura dossier flags sources
   authored by Oura employees). The dossier commits to
   `library/research-dossiers/` as provenance — raw input, explicitly
   **not itself citable** (see the header note in the two existing dossiers).
   From the dossier: sources go into `reference_list.md`; claims go into the
   routed topic file with mandatory tags (`[EVIDENCE: swim-ultra|swim]` /
   `[ADAPTED: cycling|running|tri|general-endurance]` + `Confidence:` +
   `Test:`, or `Coach judgment:`); the changed section is marked
   `UNREVIEWED`; `INDEX.md`'s routing table is updated to point at it.
4. **Precondition: the CI library-evidence gate** (being built now on branch
   `ci/library-evidence-gate` — this section depends on it, doesn't
   implement or duplicate it). It machine-enforces the invariants step 3
   currently only holds by careful prompting: no fabricated-ID-shaped
   citations, every `[ADAPTED]` block carries `Confidence:` + `Test:`, tag
   values are valid, topic files stay ≤2,500 words, citations resolve to
   `reference_list.md`, and engine-constant library references point at real
   files.
   - *Principle:* automated drafting is only safe once the evidence
     discipline is an **invariant the system enforces**, not a convention a
     careful prompter follows. Without the gate, a drafting agent scales up
     the repo's original fabrication failure instead of preventing its
     recurrence — this loop does not go live before that gate is merged.
5. **Human review is a hard gate — and must be a human.** The drafting job
   opens a PR (new/changed topic file + dossier + `reference_list.md` +
   `INDEX.md` diffs); a human with domain judgment (Andrew, or a real coach)
   reviews it and removes `UNREVIEWED`. Never auto-merge.
   - *Trap to avoid stating obliquely:* an AI reviewing an AI's draft is a
     mirror, not a gate — it will pattern-match agreement, not catch a bad
     inference. The PR is the sign-off record; the reviewer is the control,
     not another model.
6. **Release + loop closure.** Merging is not enough by itself: `library/`
   is baked into the backend container image at `/app/library` (see "Known
   limitation" above), so the **live chat coach** only sees the new text
   after a redeploy (`gh workflow run deploy-backend.yml --ref main`) — repo-
   side Claude Code skills see the merged file immediately, the deployed
   coach doesn't. Recommend, as a follow-up, a path-filtered auto-deploy
   trigger (`paths: ['library/**', 'engine/**', 'backend/**']` on
   `deploy-backend.yml`) to remove that manual step — same class of fix as
   the Phase 2.5 DB-freshness limitation, different layer. After the deploy,
   mark the originating `Feedback` rows `status="resolved"`, linking the
   merged file, so the same gap isn't independently re-researched next
   sweep.
7. **Why the library stays in git, not a DB or vector store — recorded
   here as a decision, not left implicit.** Even fully built out (files
   `01`–`12` at the ≤2,500-word cap), the corpus is ~30–35k tokens — the
   *entire* library fits in one context window, so RAG/vector retrieval
   solves a problem this project doesn't have. `INDEX.md`'s hand-curated
   routing table beats embedding similarity over ~12 documents: it encodes
   judgment ("this claim actually belongs under `10`, not `06`") that
   similarity search can't. More importantly, baking library + engine from
   the same git commit into the same container image makes production drift
   **impossible by construction** — the deployed engine constant and the
   library file that justifies it are always the same version
   (`00-conventions.md`'s code/library-drift rule, enforced at the artifact
   level rather than by convention). The draft → review → release state
   machine described above **is** branch → PR → merge; provenance, diff, and
   rollback come for free from git instead of being rebuilt. Triggers that
   would reopen this decision: library writes becoming routine (more than
   weekly), or a reviewer who can't use GitHub — and even then the fix is a
   PWA review screen calling the GitHub API to merge the PR, keeping git as
   source of truth, **not** moving the library into Postgres. Separately:
   the *unbounded* corpora (raw coach texts, workout logs) are a plausible
   future home for embedding search — the curated, human-reviewed library
   is not, and shouldn't be conflated with them.

---

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



---

### Engine CLI (every skill shells out to these)
`python -m swim_coach.cli`: `validate --athlete <slug>` (pydantic-validate whole tree, nonzero exit on error — runs in CI) · `zones` (CSS + zone table → profile) · `scaffold-macro` · `plan-week` (pool sessions emitted as placeholders `source: pool_coach`) · `ingest --file x.fit|tcx|csv` · `parse-coach-text` · `summarize --weeks 4` (compact JSON: volume, load, wellness trend, compliance — reused by Phase 2 context assembler) · `adapt --week <iso>` (draft next week + machine rationale).

### Adaptation rules (adapt.py — constants cited to library files, all unit-tested)
- Wellness composite red (≤2.0) OR 7d:28d load ratio >1.4 → cut volume 20–30%, hold long swim, add recovery day.
- Compliance <70% → repeat progression step.
- All green + compliance ≥90% → advance (volume +≤8%/wk, long swim +≤10–15%).
- Pool-coach sessions are fixed constraints: engine budgets remaining load around their *actual* delivered load and balances intensity distribution (80/20 across total swim time).
- `/adapt` skill reviews the draft with judgment (may not exceed engine caps), finalizes, appends rationale to notes/decisions.md.

### Event format parameter + long-swim progression (added 2026-07-05)
`Event` gains an `event_format: single_day | multi_day_stage` field (default `single_day`), threaded through `scaffold_macro` and weekly generation. It does **not** change the macro block volumes (those are runway- and ramp-cap-limited regardless) — it changes **weekly composition**, chiefly the long-swim treatment:
- **`single_day`** (e.g. Renee's 33.3 km continuous Greece choice): long-swim progression is first-class. `plan.py`/`adapt.py` build an escalating ladder of single continuous swims toward a peak of ~60–70% of event distance (cite `library/06`), each milestone swim followed by 3–5 mandated easy/recovery days (Garmin single-session finding + channel-swim guidance). Long-swim share of weekly volume rises to ~55–65% in peak weeks. One full-duration fueling rehearsal required.
- **`multi_day_stage`** (e.g. UltraSwim 33.3's 4-day option): back-to-back weekend long swims (Sat+Sun), longest single swim tops out ~30–40% of total distance, plus inter-day recovery/refuel emphasis. No single monster swim.
- The A event may **switch formats** if the single-day long-swim ladder isn't on track (Renee's is flagged switchable by mid-Aug), and the Dec event's format is TBD — so format must be a cheap re-scaffold, not a rebuild.
- New model field is backward-compatible (default preserves current behavior); `library/06-long-swim-progression.md` is authored alongside so the ladder constants have a citation home.

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
