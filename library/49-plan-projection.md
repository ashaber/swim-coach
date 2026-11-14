# Plan projection: defaults behind `projection.py`

See `00-conventions.md` for the tagging scheme. Grounds the defaults in `engine/swim_coach/projection.py`, which projects load and freshness (CTL/ATL/TSB) for hypothetical training scenarios and compares them. Every claim here is unsourced engineering judgment. **UNREVIEWED**, pending human review.

## Scope of the projection (`Coach judgment:`)

**Coach judgment:** a projection reports load, freshness and plan-check findings only. It makes no claim about watts, pace or race result, because no library file calibrates load to performance gain for this athlete. Test: no projection output field or trade-off sentence names a performance figure.

## Defaults for a scenario week (`Coach judgment:`)

**Coach judgment:** a recovery week with no stated reduction cuts weekly hours by 30% (`RECOVERY_WEEK_REDUCTION_DEFAULT = 0.30`), a middle value between a light and a full deload, consistent with the 3:1 / 2:1 cadence discussed in `36-plan-authoring-limits.md`. Test: for an athlete with logged recovery weeks, compare the median logged recovery-week hours to the preceding week; a value far from 30% means the default should be replaced by the athlete's own.

**Coach judgment:** the longest session of a scenario week sits on Sunday, the usual weekend long-session day. Test: the athlete's own longest logged session of each week falls on Saturday or Sunday in most weeks.

**Coach judgment:** hard sessions are placed to maximise the smallest gap in days between them (wrapping across the week boundary), then to keep them away from the long-session day. A hard session is never placed on the long-session day. Test: the projected minimum hours between hard sessions for a 2-hard, 4-day week is 72 h or more.

## Easy and hard load per hour (`Coach judgment:`)

**Coach judgment:** to split the athlete's recent load per hour into easy and hard figures, a logged workout with RPE 7 or higher counts as hard (`HARD_WORKOUT_RPE_MIN = 7`), the rest as easy. The split is used only when at least 3 workouts fall in each bucket (`MIN_WORKOUTS_PER_INTENSITY_BUCKET = 3`); otherwise both figures fall back to the blended load per hour and the projection records that in its assumptions. Test: for an athlete with enough RPE-logged workouts, the hard figure exceeds the easy figure; if not, the RPE logging is too sparse to use.
