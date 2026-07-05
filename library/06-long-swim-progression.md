# Long-swim progression & event format

Grounds the long-swim-specific constants in `engine/swim_coach/plan.py`
(`LONG_SWIM_SHARE`, `STAGE_SATURDAY_SHARE`, pool-placeholder sizing) and
`engine/swim_coach/adapt.py` (the event-format-aware long-swim ladder). See
`00-conventions.md` for the tagging scheme and `reference_list.md` for full
citations.

## Why the long swim gets first-class treatment

For an ultra-distance open-water event, the single continuous long swim (or
back-to-back stage swims) is the training stimulus most directly specific to
race demands — nothing else in the week rehearses multi-hour fueling,
pacing, and durability at once. `Event.event_format` (`single_day` |
`multi_day_stage`, default `single_day`) determines how that stimulus is
arranged week to week; it does **not** change macro block volumes (those
stay runway- and ramp-cap-limited regardless of format) — only weekly
*composition*.

## The core injury-risk evidence: single-session spikes

**[ADAPTED: running] Confidence: medium.** The single most load-bearing
citation in this file: `reference_list.md`'s **Garmin-RunSafe running-health
cohort** ("How much running is too much? Identifying high-risk running
sessions in a 5,200-person cohort study," *British Journal of Sports
Medicine* 2025/26, >500,000 logged runs) found injury risk rose sharply when
a single session exceeded the longest effort from the prior 30 days by more
than ~10% — and that week-to-week volume changes and ACWR showed comparatively
little predictive value by contrast (see `03-periodization.md`'s ACWR
section for that side of the finding).

This is adapted from running to swimming, not directly evidenced in
swimmers, hence medium (not high) confidence. **Test:** flag any single long
swim that exceeds the athlete's longest swim of the prior 30 days by more
than the engine's configured step cap — this is exactly what
`adapt.py`'s `_longest_recent_swim_m()` + `SINGLE_SESSION_STEP_CAP` compute
and enforce on every ladder advance.

`adapt.py`'s `SINGLE_SESSION_STEP_CAP = 0.15` is this engine's ceiling, set
at the *upper* end of ROADMAP.md's stated "+10-15%" range rather than at the
directly-evidenced 10% figure itself — a deliberate, documented, slightly
more permissive choice, not a claim that 15% is itself evidence-backed.
`LONGEST_SWIM_LOOKBACK_DAYS = 30` matches the Garmin-RunSafe cohort's own
30-day lookback window exactly.

## Milestone recovery: 3-5 days

**Coach judgment**, informed by the same Garmin single-session finding (a
large spike carries elevated injury risk, so the days immediately after a
milestone swim are exactly when that elevated risk needs to be actively
managed down, not left to the normal week's schedule) plus general
channel-swim community practice (see the Santa Barbara Channel Swimming
Association guidance below, which frames long swims as a small number of
"major milestones" within a build rather than smooth weekly increments).
`adapt.py`'s `RECOVERY_DAYS_AFTER_MILESTONE_MIN/MAX = 3/5` isn't an
independently published figure; it's this engine's operationalization of
"give a big spike real recovery before stacking anything else on top of it."

**Engine mechanics, honestly scoped:** a single `adapt_week()` call only
controls one week's sessions, so it can only directly mark the one
post-milestone day that falls within *that* week's own date range as easy
(Sunday, immediately after a Saturday milestone swim). The remaining days of
the 3-5 day window spill into the *following* week's `adapt_week` call,
which enforces the rest via a forced-hold gate keyed on
`days_since_last_milestone` (supplied by the caller/skill, since the engine
has no persistent cross-call memory of "when was the last milestone" —
`/adapt`'s skill records that date in `notes/decisions.md` for exactly this
reason).

## `single_day` format: the escalating ladder

For events like Renee's 33.3km continuous Skopelos swim: the plan's spine is
a single continuous swim that escalates over the build, peak-ing at
`SINGLE_DAY_PEAK_SHARE_MAX = 0.70` of `event.distance_m`
(`SINGLE_DAY_PEAK_SHARE_MIN = 0.60` marks the advisory low end of the
target range, not separately enforced as a floor).

**[EVIDENCE: swim-ultra, practical] Confidence: medium.** The Santa Barbara
Channel Swimming Association's published training guidance
(`reference_list.md`'s "Practical / non-journal resources") recommends, for
a 33km swim specifically, peak training swims of 20-23km — 60-70% of target
distance — built via **2-3 major long-swim milestones** across a 6-9 month
build, each requiring 3-5 days of recovery due to CNS stress and shoulder
injury risk, with weekly volume increases capped at 10%. This is a web
practical resource (not a peer-reviewed paper), but it's swim-specific and
directly on-point for this exact distance class, which is why it's cited at
medium rather than low confidence despite not being a journal source.
`SINGLE_DAY_PEAK_SHARE_MAX = 0.70` and the 3-5 day recovery window both come
directly from this source; the "2-3 major milestones... capped at 10%"
framing is the direct precedent for treating milestone *jumps* (bounded by
`SINGLE_SESSION_STEP_CAP`), not smooth weekly increments, as the primary
progression lever.

Each ladder step (`adapt._advance_single_day_long_swim_m()`) is bounded by
three caps simultaneously: never below the current planned distance
(monotonic), never more than `SINGLE_SESSION_STEP_CAP` over the actual
prior-30-day-longest logged open-water swim, and never above
`SINGLE_DAY_PEAK_SHARE_MAX * event.distance_m`.

### Long-swim share of weekly volume in peak weeks

**Coach judgment**, PROVISIONAL: `LONG_SWIM_SHARE_PEAK_MIN/MAX = 0.55/0.65`
documents the target range for how much of a peak week's total volume the
long swim itself should represent (vs. the baseline `LONG_SWIM_SHARE = 0.33`
used earlier in the macro). This isn't separately hard-enforced as a
planning cap in the Day 4 engine (the ladder's own step/peak-distance caps
already bound the long swim, and `plan.py`'s baseline `LONG_SWIM_SHARE`
governs ordinary weeks) — it's tracked here as the documented target for
`/adapt`'s judgment review to check peak weeks against.

## `multi_day_stage` format: back-to-back weekend swims

For an event's stage-race option (e.g. UltraSwim 33.3's 4-day option):
`plan.generate_week()` splits the same total long-swim volume
(`LONG_SWIM_SHARE` of weekly target) across Saturday+Sunday instead of one
continuous swim, using `STAGE_SATURDAY_SHARE = 0.55` (Saturday, the fresher
day, gets the larger share) — **Coach judgment**: a stage event's second day
is always swum on the first day's fatigue, so training should mirror that
order rather than making the days symmetric or front-loading Sunday.

`adapt.py`'s ladder caps the longer (Saturday) day at
`STAGE_LONGEST_DAY_SHARE_MAX = 0.40` of `event.distance_m`
(`STAGE_LONGEST_DAY_SHARE_MIN = 0.30` is the advisory low end) — directly
from ROADMAP.md's "longest single swim tops out ~30-40% of total distance...
no single monster swim" framing for this format, which is this project's own
design decision for how a stage event's training should differ from a
single-day event's (explicitly *not* trying to build one huge swim, since
race day itself never asks for one). The same `SINGLE_SESSION_STEP_CAP`
(Garmin-RunSafe-derived) applies per day, since each stage day is still,
individually, a single session relative to the athlete's own recent
longest swim.

**Inter-day recovery emphasis**, rather than a single milestone-then-rest
pattern: `plan.py`'s Sunday stage session purpose text notes it's "swum on
Saturday's fatigue" and calls for aggressive overnight refueling/recovery
between the two days — this is the `multi_day_stage` format's analog of the
`single_day` format's post-milestone recovery window, compressed into the
overnight gap between back-to-back stage days rather than spread across
several subsequent days.

## Format switching

Per ROADMAP.md, this project's A event may switch formats if the
`single_day` ladder isn't tracking well by a stated decision point — the
model's `event_format` field and the engine functions above are built so
that switching is a cheap re-scaffold (update `events.yaml`, re-run
`cli scaffold-macro`/`cli plan-week`/`cli adapt`), not a rebuild: macro
block volumes are unaffected by format, and both ladders share the same
underlying `LONG_SWIM_SHARE`, `STAGE_SATURDAY_SHARE`, and
`SINGLE_SESSION_STEP_CAP` constants.

## Pool-session placeholder sizing

`plan.py`'s `DEFAULT_POOL_SESSION_MIN = 75` and `POOL_SESSION_EST_M = 3500`
are **Coach judgment, PROVISIONAL**: estimated duration/distance for a
pool-coach-assigned session whose actual content is unknown until delivered
post-hoc (this project's key domain constraint — the pool coach doesn't
know the periodization plan). `POOL_SESSION_EST_M` roughly matches the
~3,500-4,000m sample workouts collected as reference material
(`library/sample_pool_workout_*.md`) and is treated as constant regardless
of macro phase, since the pool coach's own volume doesn't scale with this
project's periodization.
