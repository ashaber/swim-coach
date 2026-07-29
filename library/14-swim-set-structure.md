# Swim set structure (warm-up / main-set / cool-down)

**UNREVIEWED**: this file is agent-authored per `00-conventions.md`'s
workflow and needs Andrew's human review before being treated as settled
grounding truth.

Grounds `engine/swim_coach/plan.py`'s `_additional_swim_structure()` — the
internal warm-up/main-set/cool-down composition of the "additional"
pool-independent aerobic `swim_ow` session (the `remainder >=
MIN_ADDITIONAL_SWIM_M` path in `generate_week()`). See `00-conventions.md`
for the tagging scheme and `reference_list.md` for full citations.

## Scope boundary: this is not a pace-zone-math file

`04-css-intensity-anchors.md` already owns the CSS derivation and the
Z1-Z5 zone-offset table — this file does not duplicate or change any of
that math. This file is only about how a session *built from* those zones
should be organized internally: how much warm-up, what shape the main set
takes, how much cool-down.

**This file also does not touch the Saturday long-swim session.**
`06-long-swim-progression.md` deliberately keeps that session continuous
and negative-split as race-specific durability practice — that is
intentional, existing design, not a gap this file fills. `14` governs only
the separate "additional" aerobic session.

## Session skeleton: warm-up, main set, cool-down

**Coach judgment / practitioner convention.** A warm-up/main-set/cool-down
skeleton, with the warm-up as roughly a fifth of session distance and the
cool-down a tenth, is standard pool-coaching convention (visible in
`sample_pool_workout_openwater_focus.md` and
`sample_pool_workout_traditional.md` — reference material for *format*
only, never citable sources, per those files' own status). No experimental
source was found fixing a specific warm-up or cool-down percentage.

**[ADAPTED: general-endurance]** McGowan et al. (2015), "Warm-Up
Strategies for Sport and Exercise: Mechanisms and Applications," grounds
*that* an active warm-up is worthwhile — it raises muscle/core
temperature, elevates baseline VO2 and speeds VO2 kinetics, and can
potentiate subsequent performance, with swimming applications discussed.
Confidence: medium-high for "warm-up helps," but this citation does **not**
license any specific warm-up *volume* — the ~20% figure `plan.py` uses is
Coach judgment/convention, not derived from this paper. **Test:** if the
athlete logs noticeably slower early-main-set pace or higher early-set RPE
on days she skips or shortens the warm-up (vs. a matched day with the full
warm-up), that's a supporting signal for including it; if pace/RPE looks
the same regardless, the warm-up's practical value for this athlete's
aerobic sessions specifically is weaker than the general literature
suggests.

## Main-set format menu

**Coach judgment.** Straight aerobic repeats, descending sets,
broken-distance/pyramid sets, and negative-split segments are the shared
vocabulary of pool coaching. No verified source in this pass ranks one
format as superior for aerobic CSS-anchored training — these are offered
as legitimate, standard coaching options, not evidence-graded choices.

**Negative-split pacing** within a segment is the one format element with
real swim evidence, and it is already graded and grounded in
`04-css-intensity-anchors.md` (evidence-tagged swim-specific per Saavedra,
Einarsson et al. 2018, plus an adapted-from-running Berlin Marathon
analysis, each with its own Confidence/Test in that file) — this file
cross-references that existing grounding rather than re-tagging or
re-deriving it here. `plan.py`'s broken-distance main set (build/peak/
taper blocks) applies this by structuring each repeat to finish faster
than it starts.

## Base -> build/peak shift in session emphasis

**[EVIDENCE: swim] Confidence: medium.** González-Ravé et al. (2021), a
systematic review of elite swimmers' training-intensity distribution,
found coaches commonly shift intensity distribution across a macrocycle —
broadly pyramidal/aerobic-heavy in the general/preparatory phase, moving
toward threshold/polarized work in the specific/competitive phase — though
the authors caution the evidence base is thin. Pla et al. (2019), a
6-week intervention in elite swimmers, found a polarized block produced a
small-to-moderately greater 100m improvement and less perceived fatigue
than a threshold block.

This supports the *principle* that session emphasis should shift base ->
build/peak: more continuous aerobic volume early, more broken-distance/
race-pace-adjacent work later. It does **not** validate any specific
broken-distance set design, and both sources are elite-swimmer,
short-event evidence being adapted here to an ultra-distance masters
athlete's aerobic-session emphasis, not a validated set-geometry
prescription. `plan.py`'s `_additional_swim_structure()` implements the
*direction* of this shift (continuous Z2 repeats in the base block;
broken-distance Z3->Z4 descending repeats otherwise) as its own
engineering choice on top of this evidence, not a literal reproduction of
either study's protocol.

## What `plan.py` actually generates

`_additional_swim_structure(macro_block_name, distance_m, css_pace_s)`
returns:

- **Warm-up**: `ADDITIONAL_SWIM_WARM_UP_SHARE` (20%) of session distance,
  floored at `ADDITIONAL_SWIM_MIN_WARM_UP_M` (200m), easy building to Z2
  pace. Coach judgment/convention — see above.
- **Main set**: in the `base` block, straight Z2 repeats
  (`ADDITIONAL_SWIM_BASE_BLOCK_REP_M` = 300m reps, short rest) — continuous
  aerobic volume. In `build`/`peak`/`taper` blocks,
  `ADDITIONAL_SWIM_BUILD_BLOCK_REP_M` (200m) broken-distance repeats
  descending from Z3 toward Z4 on the final rep, each repeat itself
  negative-split. The base-vs-build *direction* is `[EVIDENCE: swim]`
  above; the specific rep lengths and exact zone choice are Coach
  judgment.
- **Cool-down**: `ADDITIONAL_SWIM_COOL_DOWN_SHARE` (10%) of session
  distance, floored at `ADDITIONAL_SWIM_MIN_COOL_DOWN_M` (100m), easy
  choice of stroke. Coach judgment/convention.

All pace numbers are read from `zones.py`'s `zone_table()` — this file
supplies no independent pace math, only session-composition structure
around that existing table.

## Open questions / not yet covered here

- A ranked comparison of main-set formats (straight/descending/broken-
  distance/pyramid) for aerobic CSS-anchored training was not found in
  this pass and may not exist — treat the menu above as coach judgment,
  not a settled ranking.
- Warm-up/cool-down proportions are convention, not calibrated to this
  athlete's own data; a future pass could test whether a shorter or
  longer warm-up correlates with better main-set pace-holding once enough
  logged sessions exist.
- Whether the base->build shift should also vary main-set *rep length*
  (not just zone/format) by macro block is not evidenced here — the two
  cited sources are distribution-level, not session-geometry-level, per
  the caveats above.
