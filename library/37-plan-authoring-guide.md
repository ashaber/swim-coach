# Plan-authoring guide: how the coach uses `author_macro_plan` / `author_week_plan` / `check_plan`

**`Coach judgment:`** practitioner method, not a research citation — a
compact port of Tim's `ai-coach` `plan-macrocycle` / `build-block` /
`weekly-review` skills and `red-team` subagent, adapted to this app's own
tools (`author_macro_plan`, `author_week_plan`, `check_plan`,
`save_race_debrief`) and its deterministic red team
(`swim_coach.plan_check.check_macro`/`check_week` — see
`36-plan-authoring-limits.md` for the evidence behind its constants).
Routed (`backend/app/context.py`) so it loads only on planning turns, not
in the always-on prefix.

**UNREVIEWED**, pending human review.

## The three tools, in one line each

- **`author_macro_plan`** — the coach writes the full week-by-week season
  table directly (phase, focus, hours, load, CTL target, key sessions,
  recovery flag) plus a 3-5 sentence `architecture` rationale. Draft, see
  the `check_macro` report, accept/decline each finding, confirm.
- **`author_week_plan`** — the coach writes one week's real sessions.
  Draft, see the `check_week` report, accept/decline, confirm. A
  `confirm-*` finding (weekly volume +8%, long-swim step +15%) requires an
  explicit accepted decision before it will persist — CLAUDE.md's one hard
  safety rail.
- **`check_plan`** — read-only re-check of whatever's currently persisted.
  Run it after any manual edit (`patch_week_plan`/`merge_week_plan`), or
  just to see how a plan reads against the athlete's latest real
  CTL/history.

Never hand-compute zones/loads/volumes in chat (CLAUDE.md standing rule) —
these tools' own draft calls already run the check; read its findings, add
judgment on top.

## Planning layers: macro → meso → workouts

**Macro (season):** the full week-by-week table, authored once via
`author_macro_plan` and re-checked (`check_plan`) after every race or
material change. Work backwards from the A race: taper, peak, build, base,
transition, same order Tim's `plan-macrocycle` skill uses. Changes only
when the goal or capacity genuinely changes — not every week.

**Meso (block):** each block gets, in the `architecture` text and the
block's own `key_sessions`/`notes`: its **purpose**, the **limiter** it
targets, the **key session types with a stated progression** (e.g.
over/unders 3×8 → 3×10 → 4×10), **hard days per week**, the **intensity
distribution** the block claims (count sessions, not minutes, if it claims
polarized), and the **test/benchmark that closes it**. Write this level of
detail for the **current and next block only** — later blocks stay at
table-row precision. A 40-week table written to block-level detail
everywhere is false precision: the athlete's life rewrites it before week
20 (Tim's own framing, and this app's own real history — see `31`).

**Workouts (micro):** `author_week_plan` writes real sessions through the
**next race weekend or ~2 weeks, whichever is longer** — never open-ended.
State the horizon out loud ("planned through Oct 18; will refresh after
that weekend or in ~2 weeks, whichever comes first"). A refresh is
triggered by a race, the weekly review, or the horizon running out — don't
let it silently lapse.

## Author the macro, then check it, then present it

1. Read the athlete's **actual** current CTL/ATL and actual sustained
   weekly hours (never a self-report best week) before drafting anything.
2. Call `author_macro_plan` with `confirm` omitted — this validates and
   runs `check_macro` automatically. **Always run the check before
   presenting** — never show a hand-reasoned plan the engine hasn't seen.
3. Show the athlete the table, the architecture rationale, and **every
   finding** the report returned (verdict, severity, evidence,
   consequence, fix) — never summarize the review as a formality.
4. Get an explicit accept-or-decline **with a reason** for each finding.
   Declining is legitimate and must be visible — don't manufacture a
   change just because a finding exists, and don't quietly drop a finding
   the athlete didn't actually address.
5. Call `author_macro_plan` again with `confirm: true`, the `draft_id`,
   and `decisions` covering every finding id. A missing decision refuses
   the confirm and writes nothing — this is deliberate, not a bug to work
   around.
6. Re-draft at most twice per request without stopping to show the
   athlete what you have. A third re-draft in one request is refused —
   present the plan instead of iterating silently.

`author_week_plan` follows the identical draft → check → decide → confirm
shape, one ISO week at a time, against that week's own `MacroWeek` row.

## Say it now, not in week 9

If the CTL trajectory to the goal requires a ramp above what
`check_macro`'s ramp-cap finding allows, or the goal-reality check says the
clock runs out before the athlete gets there, **say so in the first
conversation**, not after nine weeks of a plan built on a number that was
never reachable. The finding exists specifically so this never has to be
discovered late.

## Race-weekend Sunday flow

What a race weekend should look like end to end, tools already built for
each step (`plan-macrocycle`'s approved-plan section, "Race-weekend Sunday
flow"):

1. **Debrief.** Pull the objective data first (`get_ride_pacing` /
   `reanalyze_workout` / `pull_activity_stream`, official result if given),
   then run the `save_race_debrief` interview: what went well, what to
   work on (always both, the athlete's own words), plus targeted
   follow-ups the data raises. Ask what the data can't show — Tim's
   weekly-review read order still applies: compliance → CTL vs. target →
   fatigue/wellness → session texture → the athlete's own account, which
   outranks any metric when they disagree.
2. **Update the numbers.** FTP/threshold anchor from real race power/pace
   files; real CTL/TSB from logged history. Run `check_plan` against the
   updated state — don't reason about the next block from stale numbers.
3. **Adapt the meso.** Map what the debrief surfaced to the next block's
   limiter and key sessions (e.g. "faded late → over/unders; weak on flats
   → sustained threshold; strong start → keep one start-rep set"). Propose
   the change with reasons and the fresh `check_macro`/`check_week`
   findings; the athlete approves.
4. **Write and push.** Author sessions through the next race weekend (or
   ~2 weeks, whichever is longer) via `author_week_plan`, check each week,
   and push to the calendar **only after** the athlete has seen the
   summary — never push silently ahead of a look.
5. **Log the decision.** What changed and why, on the plan's own
   `red_team`/decision record (the `decisions` passed at confirm already
   capture this) so the next review can see the reasoning, not just the
   resulting numbers.

## Weekly review order (non-race weeks)

Same four-question order as a race-weekend debrief, scaled down: did the
work happen (compliance — which sessions were missed, and were they the
right ones to miss); is fitness moving as planned (CTL vs. the macro
target — a flat CTL in a build phase is as much a flag as an over-steep
ramp); is fatigue tolerable (TSB trend plus wellness — one bad night is
noise, several consecutive bad signals aren't); what do the sessions say
(power/pace holding, hard sessions completed as written or quietly
shortened). Adjust the **upcoming week**, not the whole macro, unless the
goal or capacity has genuinely changed. "The plan is working, keep going"
is a legitimate output — constant tinkering is its own failure mode.

## Handling `check_macro`/`check_week` findings (red-team discipline)

These findings are **advisory, capped at six, ranked by severity** — never
a clamp, never a rejection (the engine's own rule: `plan_check.py` "never
rejects or clamps a plan"). Treat them the way Tim's `red-team` agent asks
a coach to treat adversarial review:

- **Accept or decline, visibly, every time** — a decline with a real
  reason ("the athlete has already run this exact taper twice and reads
  fine at this depth") is a legitimate outcome, not a failure to engage.
- **Don't manufacture agreement with every finding** just because the
  report produced one — a report with three real findings and three
  reflexive accepts is worse than one with two findings and one honest
  decline.
- **Don't pad your own reasoning to sound more thorough** than the finding
  warrants — match the engine's own "cap it at six, the ones that matter
  get buried otherwise" discipline in how you respond, too.
- The one place a finding is **not** advisory: a `confirm-*` id (the
  +8%/+15% safety rails). These still require an explicit accepted
  decision to persist — that's a hard stop, not a preference.
