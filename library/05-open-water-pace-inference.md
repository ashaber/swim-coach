# Open-water pace inference

Grounds `engine/swim_coach/zones.py`'s `infer_ow_pace()` — the wetsuit,
condition, and cold-water corrections applied on top of a pool-derived CSS
pace to estimate an achievable open-water pace. See `00-conventions.md` for
the tagging scheme and `reference_list.md` for full citations.

## Why open-water pace needs correction at all

A pool CSS test happens in a controlled 25m/50m lane: flat water, wall
push-offs every length, lane lines damping wake. Open water removes all of
that. **[EVIDENCE: swim] ~ (author legitimate, this specific paper not
individually verified)** Zamparo et al.'s pool-vs-open-water energetics work
(Zamparo is a leading swimming-energetics researcher per `reference_list.md`)
quantifies a real metabolic-cost inflation from wave action, wind, and the
lack of static turning platforms. Confidence: medium (author credible,
specific paper unverified) — treat the *existence* of an open-water penalty
as solid, the *exact percentage* as unconfirmed.

**Every correction constant in this file is explicitly PROVISIONAL** per
`zones.py`'s own module docstring: starting-guess values to be calibrated
against 3-5+ of this specific athlete's logged open-water swims, not
independently published per-second figures. This file exists to document
*why* each constant has the sign and rough magnitude it does, not to claim
it's individually evidence-backed.

## Wetsuit correction: `WETSUIT_ADJ_S = -4.5` (s/100m, faster)

**Coach judgment**, informed by commonly cited wetsuit buoyancy-assist
ranges in the open-water/triathlon coaching community (a wetsuit reduces
drag and raises body position, both of which measurably speed up swim pace
at a given effort). `zones.py` uses -4.5s/100m as the midpoint of a commonly
cited -3 to -6s/100m range. Confidence: low until calibrated against this
athlete's own wetsuit vs. non-wetsuit open-water swims — this is exactly the
kind of number `/adapt`'s judgment review and logged OW swims should be
checking over time.

**Test:** once the athlete has 3+ logged wetsuit OW swims and 3+ skins/no-
wetsuit OW swims at comparable effort (similar RPE, similar conditions),
compare the actual pace delta against -4.5s/100m; re-anchor the constant if
it's consistently off by more than ~1-2s/100m.

**Coaching note specific to this athlete's undecided suit choice:** a
wetsuit (even sleeveless) typically moves an event out of "marathon
swimming / skins" rules — this is a race-category and pace-calibration
decision, not something `infer_ow_pace()` can resolve; it needs deciding
before serious open-water-specific pace targets are trusted.

## Conditions correction: `CONDITIONS_ADJ_S`

```
calm: +2.0s/100m
moderate: +5.0s/100m
rough: +8.0s/100m
```

**Coach judgment**, PROVISIONAL. These represent an escalating
sighting/chop penalty relative to pool pace — even "calm" open water still
requires sighting (head-up strokes cost time no wall-based pool set does)
and has zero wall push-off assistance, hence a nonzero penalty even at the
best end of the scale. Confidence: low across all three tiers until
calibrated per-athlete.

**[ADAPTED: general open-water coaching guidance]** `reference_list.md`'s
"Practical / non-journal resources" includes PurplePatch Fitness's
open-water pacing guide, which documents an "Environmental Pace Decay
Curve" moving from pool baseline through flat-lake to ocean-with-waves,
with each environment carrying a wider anticipated pace range and shifting
the athlete's primary pacing reference from clock time toward stroke
rate/length and perceived effort. This supports the *direction and ordering*
of the three tiers (calm < moderate < rough penalty) even though the exact
second-values in `zones.py` aren't drawn line-for-line from that source.
Confidence: low-medium; Test: log conditions (calm/moderate/rough) alongside
every OW swim's RPE and actual pace, and check whether actual pace deltas
preserve the same ordering as fitness improves — if rough-water swims stop
being meaningfully slower than moderate, the "rough" tier may be
over-penalizing.

## Cold-water correction: `COLD_WATER_THRESHOLD_C = 16.0`, `COLD_WATER_ADJ_S = 2.0`

**Coach judgment**, PROVISIONAL: below 16°C, `infer_ow_pace()` adds a flat
2.0s/100m penalty for the additional neuromuscular/thermal cost of cold
water. Confidence: low, not yet calibrated. This threshold and penalty are
not independently cited — the cold-water physiological cost is real and
well-documented in cold-water-swimming literature generally, but no specific
paper in `reference_list.md` supplies this exact threshold/penalty pair, so
it's flagged as engineering judgment rather than dressed up as evidence.

**Note for this project's first athlete:** the current A-priority event's
water temperature (typically ~23-25°C) sits well above this threshold, so
the cold-water correction is inactive for that event's open-water sessions —
it exists in the engine for a colder future event, and its calibration
priority is lower than the wetsuit/conditions corrections until a colder
event is actually being trained for.

## What calibration will look like in practice

Once the athlete has logged enough open-water swims (workouts with
`sport: "swim_ow"`, `avg_pace_s_per_100m` populated, and enough context in
`notes`/associated wellness to reconstruct conditions and wetsuit status),
the calibration loop is:

1. Compare `infer_ow_pace()`'s prediction (given the swim's actual wetsuit/
   conditions/temp inputs) against the athlete's logged
   `avg_pace_s_per_100m` for that swim.
2. If a systematic bias emerges (predictions consistently faster or slower
   than reality by more than a couple of seconds/100m), adjust the relevant
   constant and re-cite this file's confidence note accordingly.

This calibration loop isn't automated in Day 4's engine — it's a manual
`/adapt` or `/coach` judgment check against logged data, flagged here as
follow-up work rather than implemented.
