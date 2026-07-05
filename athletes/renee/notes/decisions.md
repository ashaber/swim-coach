# Renee — coaching decisions log

## 2026-07-05 — Onboarding

- **Athlete:** Renee (`renee`), athlete_id `19250c9f-945e-4578-b6c7-550a89553577`.
- **CSS:** 1:30/100m (90.0 s/100m), given directly (no 400/200 test on file yet —
  worth a real CSS test in the next 4–6 weeks to confirm and to establish a
  re-test cadence). Zones computed from it and written to `profile.yaml`.
- **Coached pool:** USMS, coach-planned, 90 min, Mon/Wed/Fri. The AI coach plans
  *around* these fixed sessions (open-water, long swim, strength, recovery).
- **HRV:** Oura ring (subjective + HRV both available for `/check-in` and adapt).

### Target event — DATE NEEDED before a macro plan can be built
- **Event:** ~33.3 km circumnavigation of **Skopelos Island, Greece** — "Ultra
  Swim." (Spelling written as "scopolose" — confirm it's Skopelos, Sporades.)
- **Distance:** 33,300 m.
- **Water temp:** typically 73–77 °F ≈ 22.8–25.0 °C (warm — no cold-water pace
  penalty applies; the engine's cold adjustment only kicks in below 16 °C).
- **Suit:** UNDECIDED between sleeveless wetsuit / skinsuit / naked (skins).
  Note: a wetsuit (even sleeveless) typically moves an event out of "marathon
  swimming / skins" rules and changes the pace inference (buoyancy assist). Decide
  before serious open-water work so the OW pace targets are calibrated correctly.
- **Priority:** A.

**Blocked on:** event date. Once we have it, create `events.yaml`, then
`scaffold-macro` → `plan-week`. With a ~16,800 m/week current base and a 33.3 km
target, the runway length (weeks to race) drives whether the 16→peak ramp is
feasible under the +8%/week cap.

### Current training volume
- ~16,800 m/week at onboarding.

### Training history (context for load management)
- **Feb 2025:** started from minimal fitness / injury recovery.
- **Feb → late Dec 2025:** ramped heavily.
- **late Dec 2025 → Feb 2026:** illness stalled training.
- **Feb → mid-May 2026:** ramped again, ending with an injury/illness —
  **anaphylactic shock**.
- **June 2026 → now:** restarted the ramp (~6 weeks of rebuild at onboarding).

**Coaching implication:** two significant interruptions in ~18 months and a
recent (May 2026) anaphylaxis mean the current 16,800 m/week is a *freshly
rebuilt* base, not a durable one. Bias toward consistency over heroics; respect
the +8%/week cap strictly; treat large single-session spikes (e.g. the 7/9
5-hour swim) as real injury/illness risk per the Garmin single-session finding;
ensure emergency meds/support on open-water swims given the anaphylaxis history.

### 2026-07-05 — Week 28/29 rebuilt around real events
- **W28** rewritten: the **Thu 7/9 Lucky Peak 5-hour swim** is the week's long
  swim (~15k, easy Z2, fueling rehearsal), replacing the engine's default
  Saturday 6.1k. Fri–Sun weighted to recovery; coached Friday pool flagged
  easy/optional. Week total ~25,500 m (a deliberate milestone spike).
- **W29** built as a mini-taper into the **Sat 7/18 Bear Lake Monster 10K**
  (B race) — treated as a Greece dress rehearsal (kayak support, fueling,
  sighting, negative-split), not an all-out effort. Week total ~17,500 m.
- Rationale for each is stored in the week files' `adaptation_rationale`.

### 2026-07-05 — Greece format: SINGLE-DAY (with switch option)
- Renee's current choice for Greece is the **single-day 33.3 km continuous** option
  (not the 4-day stage). Advantage: no multi-day recovery/refuel/sleep protocol.
  Disadvantage: one 10–13 hr effort, very depleted at the finish.
- **Training implication:** the plan's spine becomes a **long-swim ladder** — the
  7/9 5-hour/15 k swim is rung one, building to a peak continuous swim of ~20–23 km
  (60–70% of 33.3 k) ~3–4 weeks before Sept 18, each milestone followed by 3–5 easy
  days. Long-swim share of weekly volume climbs to ~55–65% in peak weeks. One
  full-duration (7–8 hr) fueling rehearsal required. Macro *block volumes* are
  unchanged (runway/ramp-cap limited either way) — only weekly composition differs.
- **Switch option:** if the ladder isn't tracking by ~mid-Aug, fall back to the
  4-day stage (materially safer for this 10-week runway + post-anaphylaxis rebuild).
- **December event:** a second event is on the calendar for Dec 2026; format
  (single vs multi-day) still undecided — the engine's new `event_format` parameter
  will handle both cheaply.
