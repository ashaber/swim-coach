# CSS & intensity anchors

Grounds `engine/swim_coach/zones.py`: the Critical Swim Speed (CSS)
derivation and the CSS-anchored Z1-Z5 zone table. See `00-conventions.md`
for the tagging scheme and `reference_list.md` for full citations.

## Why anchor to CSS, not power or heart rate

Cycling and running have mature power-meter/HR-based intensity models.
Swimming doesn't have an equivalent low-cost, reliable power meter in
general use, and horizontal water immersion suppresses heart rate relative
to land-based effort at the same physiological intensity (a well-established
physiological effect, though `reference_list.md` notes it hasn't been
individually source-verified in this project — treat the *concept* as
sound, the *specific numeric HR-suppression range* as unconfirmed).
**Coach judgment:** pace, anchored to a swimming-specific critical-velocity
test, is the most practical primary intensity anchor available for this
population; HR/RPE are secondary anchors layered on top (see `Session`
sessions with `anchor: "rpe"` for pool-coach-assigned content whose actual
target pace is unknown until delivered).

## Critical Swim Speed (CSS)

**[EVIDENCE: swim]** Wakayoshi et al. (1992) derived critical velocity in
swimming, adapting critical-power theory from cycling to a swimming context,
and validated it against lactate threshold. CSS is computed from a paired
time trial:

```
CSS (s/100m) = (t400 - t200) / 2
```

using 400m and 200m time-trial times. This is a legitimate, swim-specific
foundation for pace-based training zones — not an adaptation from another
sport (the *test protocol* is swimming-specific, even though the underlying
critical-power *concept* originates in cycling literature).

`zones.py`'s `css_from_test(t400_s, t200_s)` implements this formula exactly
and rejects a test where `t400_s <= t200_s` (a swimmer physically cannot
average a faster per-100m pace over 400m than over 200m in a valid maximal
test — that result indicates a pacing/timing error, not a valid CSS).

**Re-test cadence.** CSS drifts with fitness changes. **Coach judgment:**
re-test every 4-6 weeks (ROADMAP.md risk #4) rather than treating one test as
permanent — this isn't itself a cited figure, just a practical maintenance
interval; treat a stale zone table (>6-8 weeks since test) as a flag to
re-test before trusting pace targets closely.

## The Z1-Z5 zone table

`zones.py`'s `zone_table(css)` builds five zones as offsets (seconds per
100m) from CSS pace:

| Zone | Offset range (s/100m relative to CSS) | Character |
|---|---|---|
| Z1 | CSS+10s and slower (open-ended) | easy/recovery |
| Z2 | CSS+5s to CSS+9s | aerobic endurance |
| Z3 | CSS+2s to CSS+4s | tempo/threshold-adjacent |
| Z4 | CSS-1s to CSS+1s | at/near CSS (critical velocity itself) |
| Z5 | CSS-2s and faster (open-ended) | above-critical-velocity, anaerobic |

**Coach judgment:** the specific offset values (10, 5-9, 2-4, -1 to +1, -2)
are this engine's own zone-table construction around CSS as the Z4 anchor —
a standard training-zone-table *shape* (five bands straddling a critical-
velocity anchor), but the specific second-offsets are not independently
published figures; they are a practical starting scheme. **Test:** if a
season of logged Z2 swims shows RPE trending down at a stable pace (i.e. the
same offset feels progressively easier as fitness improves, independent of a
CSS re-test), that's the expected signal the zone offsets are doing their
job; if Z2 swims consistently feel harder than the "aerobic endurance"
label implies, re-examine the offset before assuming poor fitness.

Confidence: medium — the *anchor point* (CSS via critical velocity, per
Wakayoshi 1992) is well-evidenced; the specific *offset widths* around it are
coach judgment pending enough logged data to validate per-zone RPE/duration
patterns for this specific athlete.

## Negative-split pacing (Z2 long-swim target discipline)

**[EVIDENCE: swim]** Saavedra, Einarsson, et al. (2018) analyzed pacing
strategies across 437 swimmers in international 10km open-water events:
medal winners and top-8 finishers consistently swam the first half slower
than the second (negative-split), not the reverse. This is swim-specific
evidence (not adapted from another sport) and directly informs how a long
open-water swim's Z2 target pace should be *held or built into*, not
front-loaded — a coaching note that belongs alongside the long swim's
purpose text (`plan.py`'s "long open-water swim" sessions), not a numeric
engine constant.

**[ADAPTED: running]** Confidence: medium. A ~873,000-runner Berlin Marathon
analysis (`reference_list.md`, "Sex differences in marathon pacing") found
negative or flat pacing outperforms positive (fast-start) pacing at scale,
and that men were roughly twice as likely to "hit the wall." **Test:**
if a long open-water swim shows the second half's average pace materially
slower than the first half's (a positive split), treat that as an early
warning the athlete under-fueled or over-paced the first half, not simply
"fatigue" — cross-check against fueling-interval compliance
(`06-long-swim-progression.md`) before concluding it's a fitness gap.

## Dryland strength as an intensity-adjacent input

`plan.py`'s `STRENGTH_SESSIONS_PER_WEEK = 2` doesn't set a swim intensity
zone, but is grounded here because it's a training-load input that competes
for the same weekly stress budget CSS-anchored zones are trying to manage.

**[EVIDENCE: swim]** Reference_list.md's "Injury & training load" section
cites multiple dry-land shoulder-strengthening RCTs in competitive swimmers
showing reduced shoulder pain/injury incidence and improved rotator-cuff
strength balance — the direct evidence behind planning 2x/week strength
sessions regardless of macro block. Confidence: high (multiple RCTs, direct
swim population). A dedicated strength-programming topic file (`07-*`, not
yet authored) would be the fuller home for exercise selection/dosing; this
file only grounds the *frequency* constant.

## Open questions / not yet covered here

- Zone-specific fueling guidance is `05`/`06`'s territory (pace-adjacent but
  not zone-table math).
- HR-based secondary anchoring (for athletes whose HRV device also reports
  swim HR) isn't implemented in `zones.py` yet — `Session.intensity` allows
  an `"hr"` anchor value in the model, but no engine function currently
  computes an HR-based zone table. **Coach judgment / UNREVIEWED**: flagged
  as a gap, not a decision.
