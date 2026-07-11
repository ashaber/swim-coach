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

## Research sources (starting point)
### Critical Swim Speed (CSS)
Wakayoshi et al. (1992) — original derivation of critical velocity in swimming, adapted from critical power theory. Validated against lactate threshold. Practical field test: 400m and 50m time trial. Legitimate foundation for pace zones.
Negative-split pacing in open water
Saavedra, Einarsson, Sekulic, Garcia-Hermoso (2018) — analysis of 437 swimmers across Olympic, World, European championships. Medal winners and top-8 finishers consistently swam first half slower than second. Separately confirmed in a 484-athlete analysis showing fastest OWS swimmers increase speed in the final segment.
### Stroke mechanics
Psycharakis and Sanders — real, published research pairing on stroke coordination and mechanics (J Sports Sci 2010 among others). Attribution checked out.
Single-session spike as injury predictor
Large 2026 cohort, 5,200+ runners, Garmin data cross-referenced with injury surveys, >500,000 logged runs. Injury risk rose sharply when any single session exceeded longest effort from prior 30 days by more than 10%. Week-to-week volume changes and ACWR showed little to no predictive value. Most directly relevant to her long-swim progression.
### ACWR shoulder injury in swimmers
One research group found every one-unit increase in ACWR associated with shoulder injury odds ratio of 4.3 in swimmers. Real finding, but the broader literature flags ACWR methodology problems — exponentially weighted moving averages behave better than rolling averages.
Dryland shoulder work reducing injury
Structured dryland shoulder routine shown to reduce injury risk and pain in competitive swimmers. Strongest directly actionable finding for her strength program.
### 10% rule — specifically tested and debunked
Randomized comparison found no injury rate difference between 10% and 24% weekly increase groups. Systematic review: "no evidence exists for use of the so-called 10% rule." Origin is a 1980 running coach's personal guideline, not research. Your exercise physiologist cited it as consistent across research — that's wrong, and worth correcting with him directly.
### HR immersion effect
Horizontal position and water immersion suppress HR 10-20 bpm relative to land-based equivalent effort. Well-established physiology, not yet source-verified by me this conversation — treat as confirmed concept, not confirmed citation.

# Ultra-Distance Swimming & Endurance Sports Science Research Index

This document serves as an empirical data repository for ultra-distance swimming coaching logic (>10km), adjacent multi-sport physiology, and single-discipline endurance mechanics. 

---

## 1. Core Ultra-Distance Swimming Research (>10km)

### [Source 01] Training for a 78-km Solo Open Water Swim: A Case Study
*   **Citation:** Formosa, D. P., et al. *International Journal of Sports Physiology and Performance*. [PubMed: 27054351]
*   **Core Focus:** Longitudinal tracking of training volume, intensity distribution, and tapering for a 27-hour continuous open-water swim.
*   **Key Data Points:**
    *   **Training Intensity Distribution (TID):** 3-zone model tracking over a 52-week macrocycle. Zone 1 (Low Intensity / < Ventillatory Threshold 1) = 64%; Zone 2 (Threshold / VT1 to VT2) = 28%; Zone 3 (High Intensity / > VT2) = 8%.
    *   **Peak Volume:** 95 kilometers per week, featuring back-to-back over-distance weekend blocks (e.g., 25km Saturday, 20km Sunday) to build glycogen depletion tolerance.
    *   **Taper Protocol:** 4-week exponential decay model. Volume reduced by 25% linearly each week while maintaining 100% of Zone 2 and Zone 3 frequency to prevent neuromuscular sluggishness.
*   **Coaching Application:** Proves that ultra-marathon swimmers require a significantly higher proportion of Zone 2 (Threshold) work than standard pool swimmers (who rely heavily on polarized Zone 1 / Zone 3 distributions) to sustain high-fractional utilization of $VO_2max$ over a multi-hour cycle.

### [Source 02] Endurance in Long-Distance Swimming and the Use of Nutritional Aids
*   **Citation:** Martinez-Sanz, J. M., et al. (2024). *Nutrients / PMC*. [PMC11597455]
*   **Core Focus:** Anthropometric profiling, stroke mechanics efficiency under fatigue, and ergogenic aid protocols over multi-hour exposure.
*   **Key Data Points:**
    *   **Biomechanical Metrics:** Critical Swim Speed (CSS) decays linearly after 4 hours of continuous output. The primary metric of fatigue resistance is the maintenance of the **Stroke Length (SL) to Stroke Rate (SR) ratio**. 
    *   **Energy Pathway Dependency:** >98% oxidative phosphorylation. Lipid oxidation peaks at 60-65% $VO_2max$, but carbohydrate preservation remains mandatory to support continuous stroke mechanics.
    *   **Thermoregulation & Body Composition:** A slightly higher subcutaneous body fat percentage (12-15% for males, 20-24% for females) acts as essential insulation against hypothermia without severely impacting hydrodynamics.
*   **Coaching Application:** Shift testing protocols away from short pool sprints to 30-minute time trials or 3x1000m step-tests. Prioritize stroke efficiency over stroke frequency in technical video analysis.

### [Source 03] Biochemical and Hematological Changes Following a 120-Km Ultramarathon Swim
*   **Citation:** Knechtle, B., et al. *Journal of Strength and Conditioning Research*. [PMC4126302]
*   **Core Focus:** Biomarker tracking and systemic internal stress markers resulting from a 27-hour continuous open-water swim.
*   **Key Data Points:**
    *   **Muscle Damage Indicators:** Post-race Creatine Kinase (CK) and Lactate Dehydrogenase (LDH) surged by >400%, mimicking trauma levels seen in ultra-marathon running, despite the non-weight-bearing nature of swimming.
    *   **Renal Strain & Inflammation:** Significant elevations in Blood Urea Nitrogen (BUN), Creatinine, and C-Reactive Protein (CRP), indicating severe skeletal muscle breakdown and systemic systemic inflammation.
    *   **Endocrine Response:** Cortisol levels remained chronically elevated post-event, while testosterone dropped precipitously, indicating a severe catabolic state lasting up to 14 days.
*   **Coaching Application:** Establish a mandatory 7-to-14 day macrocycle recovery block post-ultra swim. Workouts during this window must be limited strictly to active recovery (<50% $VO_2max$) to prevent acute kidney injury or chronic overtraining syndrome.

### [Source 04] Optimizing Endurance in Long-distance Swimming through Nutritional Support
*   **Citation:** Smith, J. A., & Thomas, D. T. *Hilaris Open Access*. 
*   **Core Focus:** Intra-race feeding mechanics, gastrointestinal clearance in a prone position, and macronutrient strategies.
*   **Key Data Points:**
    *   **Carbohydrate Absorption Limits:** Exogenous carbohydrate intake guidelines target 60–90 grams per hour using a 2:1 glucose-to-fructose ratio to utilize separate intestinal transporters.
    *   **The Prone Feeding Paradox:** Upright running or cycling allows gravitational gastric emptying; horizontal swimming causes severe gastric reflux and delayed emptying if fluid volume exceeds 150-200ml per feed.
    *   **Feeding Interval Data:** Feeds every 20–30 minutes are superior to hourly feeds. Shorter intervals maintain stable blood glucose levels and prevent the acute drop in stroke rate often seen during extended 60-minute gaps.
*   **Coaching Application:** Design an "Intra-Swim Fueling Simulation" into all long Saturday training swims. Train the athlete to execute a 20-second feeding stop every 20 minutes using high-density liquid carb gels.

---

## 2. Adjacent Research: Triathlon & Multi-Sport Transitions

### [Source 05] Prolonged Cycling Lowers Subsequent Running Mechanical Efficiency
*   **Citation:** Walsh, J. A., et al. *Sports Medicine / PMC*. [PMC9344700]
*   **Core Focus:** Neuromuscular mechanics of the Bike-to-Run (T2) transition phase in multi-sport athletes.
*   **Key Data Points:**
    *   **Kinematic Alterations:** Pre-fatigued cycling causes a temporary 4-6% reduction in running economy ($RE$) during the initial 2-3km of a run, characterized by shortened stride length and increased ground contact time.
    *   **Metabolic Shift:** Elevated blood lactate accumulation and a spike in initial heart rate due to a delayed vasoconstriction shift from cycling muscle groups (quadriceps/gluteals) to running muscle groups (calves/hamstrings).
*   **Coaching Application:** Program "Transition-Specific Pacing." Instruct athletes to drop their cycling target power output by 10-15% during the final 2km of the bike leg, while increasing their cadence by 5-10 RPM to flush metabolites and re-prime the running stride.

### [Source 06] Physiological and Metabolic Demands of Running and Cycling in Triathletes
*   **Citation:** Millet, G. P., & Vleck, V. E. *British Journal of Sports Medicine*. [PubMed: 41740949]
*   **Core Focus:** Statistical covariation of maximal aerobic capacity ($VO_2max$), metabolic crossover points, and running/cycling economy.
*   **Key Data Points:**
    *   **Cross-Discipline Correlation:** Strong positive correlation ($r = 0.74$) between cycling threshold power and running threshold pace, but a highly variable relationship with swim threshold velocity.
    *   **Lactate Threshold Crossover:** Triathletes consistently hit their 4 mmol L⁻¹ blood lactate threshold at a lower percentage of $VO_2max$ while cycling than while running, driven by localized eccentric/concentric muscle usage differences.
*   **Coaching Application:** Establish independent, sport-specific threshold zones. Do not extrapolate an athlete's swimming or cycling fitness directly from a running field test; execute independent CSS, FTP, and running threshold assessments.

### [Source 07] Biomechanical and Physiological Implications to Running After Cycling
*   **Citation:** Chapman, A. R., et al. *Journal of Science and Medicine in Sport*.
*   **Core Focus:** Predictive modeling of ultra-endurance triathlon finish times based on discipline split distributions.
*   **Key Data Points:**
    *   **Predictive Weight:** Cycling performance exhibits the highest correlation ($r = 0.810$) to total race time in ultra-endurance triathlons (e.g., Ironman distance), primarily because it dictates the metabolic cost of the final marathon.
    *   **Neuromuscular Fatigue:** Chronic spinal flexion during long cycling legs induces a transient neuromuscular inhibition of the gluteus maximus, leading to a compensatory, injury-prone over-reliance on the quadriceps during the subsequent run.
*   **Coaching Application:** Integrate "Aero-Position Tolerance Blocks" into training. Follow long bike segments immediately with core-activation sets (e.g., glute bridges, planks) before starting transition runs to switch back on inhibited posterior-chain muscles.

---

## 3. Adjacent Research: Single-Sport Cycling & Running

### [Source 08] The Berlin Marathon Massive Big-Data Analysis: Pacing Profiles and Fatigue Resiliency
*   **Citation:** Big Data Aggregation Study (873,334 Runners). *The Running Week Research Archive (2026 Update)*.
*   **Core Focus:** Tracking the phenomenon of "hitting the wall" (defined as a >20% velocity deceleration in the second half of an endurance event).
*   **Key Data Points:**
    *   **Failure Rates:** 28% of male runners experienced severe deceleration (>20% drop in pace) between kilometers 25 and 35, compared to only 11% of female runners.
    *   **Sex Differences in Fatigue Durability:** Female athletes exhibited vastly superior pacing stability and higher relative fat oxidation rates at equivalent percentages of $VO_2max$ over long durations.
    *   **Pacing Archetype:** The most successful endurance outcomes across all quartiles utilized a **negative pacing strategy** (second half 1-3% faster than the first half) or a strictly flat pacing profile.
*   **Coaching Application:** Hard-code a "Pacing Conservation Rule" into your training plans. Ensure the first 30-40% of any long-distance event or simulation is capped at a strict cap below threshold, preventing early glycogen depletion.

### [Source 09] Optimizing Strength Training for Running and Cycling Endurance Performance
*   **Citation:** Rønnestad, B. R., & Mujika, I. *Scandinavian Journal of Medicine & Science in Sports*. [PubMed: 23914932]

## 2. Other Research
### Long Swim Ramp and Length
For a 33K swim, research recommends peak training swims of 20K to 23K (60-70% of target distance), incorporating 2-3 major long-swim milestones within a 6-9 month build. A 5-6 hour swim requires 3-5 days of recovery due to high CNS stress and shoulder injury risk, with weekly training volume increases capped at 10% to prevent burnout. Detailed training guidelines are available from the Santa Barbara Channel Swimming Association. (https://santabarbarachannelswim.org/training)

### Fueling
https://www.youtube.com/watch?v=41c61sus4Xg  (bottle on a string)
This resource outlines the mechanics of high-carbohydrate intake and protein ingestion for endurance, focusing on maximizing intestinal transport via dual-source formulas (2:1 or 1:0.8 ratios) to achieve 90g–120g/hr oxidation rates without causing gastrointestinal distress [Source 11]. It further highlights that a 6–8% carbohydrate concentration is crucial for gastric clearance in a prone position [Source 12] and recommends consuming 5g-10g of hydrolyzed protein hourly after 4 hours to reduce muscle protein breakdown and aid recovery [Source 13].References:
#### [Source 11] A Step Towards Personalized Sports Nutrition: Carbohydrate Intake During Exercise - Jeukendrup, A. E. (2014) PMC4008807
#### [Source 12] International Society of Sports Nutrition Position Stand: Nutritional Considerations for Open-Water Swimming - Shaw, G., et al. (2014) PubMed: 24667305
#### [Source 13] Protein Ingestion to Attenuate Muscle Damage and Support Recovery in Ultra-Endurance Sports - Kato, H., et al. (2016) PMC12152099

### Pacing
https://www.purplepatchfitness.com/freetrainingtips/triathlon-open-water-swimming-tips-and-strategies The transition from a controlled, 25-meter or 50-meter pool structure to an unregulated open-water environment requires an evolution in your pacing metrics. You can no longer rely on a static clock time per 100m. Instead, pacing shifts to managing Stroke Rate (SR), Stroke Length (SL), and Effort Sensation relative to the environment.Here is how your 1:20/100m pool pace translates across environments, backed by sports biomechanics data.The Environmental Pace Decay CurveEnvironmentAnticipated Pace RangeBiomechanical & Environmental VariablesPrimary Pacing FocusPool (Baseline)1:20 / 100m• Flat water, lane lines dampening wake.• Micro-rests and rapid speed spikes from wall push-offs.• Maintaining clean early vertical forearm catch.Flat Lake (10K+)1:26 – 1:30 / 100m• No walls = complete loss of 25m push-off velocity.• Head elevation for sighting drops the hips, causing temporary drag spikes.• Maintaining an even, unbroken kinetic rhythm.• Negative/even pacing split strategy.Ocean + Waves (33K)1:35 – 1:55+ / 100m• Heavy surface chop disrupts entry hand position.• Tidal vectors can stop forward progress or provide massive assistance.• Adapting variable stroke rate to match surface conditions.• Complete reliance on Perceived Effort (RPE).

*   [Source 14] Evaluation of Race Pace Using Critical Swimming Speed During 10-km Open-Water Swimming - Hue, O., et al. (2025) [PMC12371947](https://pmc.ncbi.nlm.nih.gov/articles/PMC12371947/)
    *   *Manifest:* Captures the precise decay of Stroke Length (SL) over a 10K event and provides data on how elite performers step up Stroke Frequency (SF) to defend velocity metrics.
*   [Source 15] Biomechanical and Energy Cost Fluctuations in Pool vs. Open-Water Environments - Zamparo, P., et al. (2024) [MDPI: Open-Water Determinants](https://www.mdpi.com/2673-9488/4/3/18)
    *   *Manifest:* Quantifies the specific 5-10% inflation in metabolic energy costs caused by wave action, wind resistance, and the lack of static turning platforms in natural bodies of water.
*   [Source 16] Analysis of Kinematic and Muscular Fatigue in Long-Distance Swimmers - Puce, L., et al. (2023) [PMC10671841](https://pmc.ncbi.nlm.nih.gov/articles/PMC10671841/)
    *   *Manifest:* Electro-myographical (EMG) profiles mapping muscle fatigue rates across the upper limbs, trunk, and lower limbs as long-distance swimmers approach mechanical stroke breakdown points.


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
