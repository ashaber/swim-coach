# Free-ride analysis (reading a ride with no prescribed structure)

See `00-conventions.md` for the tagging scheme and `reference_list.md` for full citations. Sources
are cited from `23-cycling-training.md` (power zones), `24-cycling-periodization-intervals.md`
(Seiler 2010) and `26-activity-stream-interval-analysis.md` (power curve); this file adds no new
citations.

**Sport scope: `bike`.** **UNREVIEWED**, pending human review. A free ride is a ride with no
structure to score, even when it was on the calendar (a scheduled group ride). No study defines
what to read from one, so the choices below are `Coach judgment:` anchored to those sources; each
carries a **Test:** against the athlete's own rides. `engine/swim_coach/free_ride.py` implements
them; every verdict needs a stated intent, otherwise the read is distribution only.

## 1. Where the time went

**[EVIDENCE: cycling]** Time is binned into the Coggan/Allen %FTP zones (`23`) over pedalling time
(power above `COASTING_FLOOR_W`, 20 W); coasting is reported separately because outdoor rides here
coast about 30% of moving time and would otherwise swamp Z1. Heart-rate zones use
`HR_ZONE_UPPER_PCT_LTHR` (81/89/93/99% of LTHR): `Coach judgment:` the library has no HR-zone
table. **Test:** zone seconds plus coasting seconds must equal moving time on every ride.

## 2. Intent and tempo creep

**[ADAPTED: general-endurance] Confidence: medium.** Seiler (2010, in `24`): elite endurance
training is roughly 80% low and 20% high intensity, with little moderate "grey zone" time. A ride
whose matched session states an easy zone (Z1 or Z2, from the session's structured intensity, never
its purpose text) is flagged `tempo_creep` when more than 20% of pedalling time and at least 15
minutes is Z3 or harder; the 15-minute floor (`TEMPO_CREEP_MIN_S`) is `Coach judgment:` so a short
ride cannot trip it. With no stated intent the engine reports the Z3+ share and no verdict.
**Test:** on easy-planned rides, creep should recur on the days the athlete reports unusual
fatigue or flat hard days; if not, raise the threshold.

## 3. Notable efforts

`Coach judgment:` the ride's best 20, 5 and 1 minute windows (the power curve's own windows, `26`)
are reported with start offset, average power and %FTP, average HR, net altitude gain and average
grade. A window is labelled by its %FTP zone (tempo, threshold, VO2max, anaerobic, sprint) and is a
"climb" at grade of at least 3% (`CLIMB_MIN_GRADE_PCT`) and net gain of at least 50 m
(`CLIMB_MIN_GAIN_M`). New 42/90-day bests come from the curve. **Test:** a 20-minute window labelled
"threshold climb" should be within ~5% of the athlete's recent 20-minute best.

## 4. Matches burned

`Coach judgment:` a match is a stretch of at least 10 s (`MATCH_MIN_S`) where 30 s centred power
(`MATCH_SMOOTH_S`) exceeds FTP, with gaps under 10 s (`MATCH_MERGE_GAP_S`) merged; each reports
duration, peak 5 s power and kJ above FTP, with totals for count, time and kJ. This is a stand-in:
`29-ftp-threshold-change-modeling.md` lists fitting CP/W' as future work, and a W' balance replaces
this once the athlete has fitted values. **Test:** on a ride with a known repeated sprint, the
count should equal the sprints ridden.

## 5. Cost against the week

TSS and IF come from the existing power-TSS tier (`load.session_load`, Normalized Power over FTP;
`23`), never recomputed. `Coach judgment:` a key session is a race, or a planned workout that is
structured or sits in Z4/Z5; a free ride the day before or after one is noted with its IF, because
what a ride costs depends on what it sits next to. **Test:** a high-IF free ride the day before a
key session should coincide with a weaker key session more often than a low-IF one.

## 6. Steady-stretch drift

`Coach judgment:` aerobic decoupling (`11`) is only meaningful on steady output, so drift is read
only over the longest stretches (up to two) of at least 20 minutes (`STEADY_MIN_S`) built from 60 s
blocks that are at least 90% pedalling with block-mean power CV of at most 12%
(`STEADY_MAX_CV`). A stop-start ride gets no drift number. **Test:** on a steady trainer ride the
segment should span nearly the whole ride and match the whole-ride drift.

## 7. Data quality

`Coach judgment:` when zero or missing power is 50% or more of moving time (`POWER_MISSING_PCT`;
outdoor coasting is about 30%), the read says so and gives no tempo verdict, effort labels or drift;
an altitude range under 30 m (`FLAT_ALTITUDE_RANGE_M`) skips climb calls. **Test:** a ride whose
power meter dropped out should always carry the note; a normal outdoor ride never should.
