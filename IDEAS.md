# Ideas for Swim Coach App
## IDEA 001 - Dragon Fly as theme image
When designing and creating logos, use dragon flies as a theme inspiration

---

## IDEA 002 - Add Daily checkin to PWA.  Ask HRV or body battery, resting heart rate etc.
Expect future integration to source this data from Garmin or Oura
- RHR
- BB/HRV
- Sleep
- How you feel


## IDEA 003 - PWA layout
Tabbed view with these tabs:
- Daily Checkin: Morning stats (IDEA 002)
- Load workout: upload .fit or daily workout image
- Coach Chat: chat bot with coach 
- Plan: show training plan, daily, weekly, periodization, event specific (could merge swim crew features)
- Library: videos, research
- Athlete (may be settings from gear instead of tab): zones, pace, etc.

## IDEA 004 - expansion of research and validation
When new research data is added, agent takes the new data into account on answers

## IDEA 005 - chat agent "I don't know"
when questions asked don't have supporting data - answer clearly - I don't know.  But, record 
the question to trigger developer to do further research.  Ideally follow-up to athlete when further
research answers the question.  Related to this, have expert mode - allow physiologist or professional 
coach ask questions to train the research.

---

## IDEA 006 - research and redesign "compliance" (per-workout vs weekly vs mesocycle)

Coach-mode Phase 1 (2026-08) added `engine/swim_coach/compliance.py`'s
`WorkoutCompliance` -- a PER-WORKOUT distance/duration-delta + quality-signal
bundle -- without checking that `engine/swim_coach/load.py` already has an
authoritative, library-cited `compliance()`: a WEEKLY aggregate
(`completed swim distance / planned swim distance * 100`,
`library/03-periodization.md`'s "Compliance" section), with real 70%/90%
thresholds that drive `/adapt`'s actual repeat/hold/advance decision.

Two problems to research and fix, not just rename:
1. **Naming collision** -- two different things in this codebase are both
   called "compliance" today (the new per-workout one has no library
   citation of its own).
2. **Conflated concepts** -- the per-workout module bundles genuinely
   plan-matching fields (distance/duration delta, intensity_match) together
   with genuinely QUALITY fields (cardiac_drift_pct-derived, SWOLF
   degradation) under one name. Standard training-science usage treats these
   as different axes: quality = how well a single session was executed
   (legitimately per-workout); compliance/adherence = did the athlete do
   what was prescribed, normally measured as a PERIOD aggregate (weekly is
   the standard cadence in both research and applied coaching; sometimes
   rolled up to a mesocycle/block for periodization review) -- volume/load
   compliance, session-count adherence, and (less commonly implemented)
   intensity-distribution/time-in-zone compliance.

Before redesigning: research actual standard definitions/citations (Foster
sRPE, the periodization/monitoring literature `load.py`'s existing
monotony/ACWR machinery already draws on) rather than inventing thresholds
again. Likely shape: keep per-workout signals as "quality"/"execution", not
"compliance"; either surface the existing weekly `load.compliance()` in the
coach view as-is, or extend THAT one with intensity-distribution matching if
a richer weekly number is wanted -- don't add a third parallel definition.