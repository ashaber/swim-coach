# FTP test protocols (2x20 field test)

See `00-conventions.md` for the tagging scheme and `reference_list.md` for
full citations. Split into its own file rather than added to
`23-cycling-training.md` or `24-cycling-periodization-intervals.md` --
both already sit within ~250 words of `00-conventions.md`'s 2,500-word
topic-file cap, same precedent `25-macro-sharpening-established-base.md`'s
own header note sets for splitting out of a full file rather than trimming
unrelated existing content to make room.

**Sport scope: `bike`.** Same guidance-scoping constraint as
`23-cycling-training.md`/`24-cycling-periodization-intervals.md` -- never
surfaced to a swim-only athlete. Not yet wired into `context.py`'s routing
(`_LIBRARY_FILE_SPORT_SCOPE`/keyword routes) -- same deferred state `24`
and `25` are honestly left in.

## The real defect this grounds

A real pool-coach-assigned "2x20 FTP test" was hand-authored in this app
with a fixed `WorkoutTarget(basis="power_w", low=X, high=Y)` target band --
prescribing a power to hold, which is what an ordinary training session
does. A genuine TEST exists to measure the athlete's real, currently-
unknown ceiling; pre-setting the power band the athlete paces to quietly
turns the test into a training session and defeats the entire reason it
was called for. This file grounds `plan.py`'s `_bike_2x20_test_structure`/
`ftp_from_2x20_test` -- a real, correctly-shaped 2x20 protocol for the
coach to prescribe instead of hand-inventing one, the same standing given
to `_bike_ramp_test_structure`/`ftp_from_ramp_test` in
`24-cycling-periodization-intervals.md`'s "Ramp test protocol and FTP
formula" section.

## The canonical single-effort convention (grounding)

`Allen H., Coggan A. (2010)`, *Training and Racing with a Power Meter*
(2nd ed., VeloPress; also the 2019 3rd ed. adding McGregor) is the
originating practitioner text for the single-effort 20-minute FTP test:
ride 20 minutes as hard as sustainable, FTP = 0.95 x average power for
that one effort. This is the SAME citation already grounding
`23-cycling-training.md`'s Coggan-zone/TSS content and
`24`'s ramp-test section's own %FTP framing -- **Confidence: high**, the
practitioner-convention tier (cross-confirmed this session against
TrainingPeaks, TrainerRoad, trainright.com/CTS, and Roadman Cycling, all
independently converging on the identical 0.95 figure for the single-
effort test).

## The 2x20 (two-effort) structure -- what's actually distinct

A genuinely NAMED, purpose-built "2x20 FTP test" protocol (as opposed to
2x20 as a *training* workout, which is common and well-documented but a
different thing entirely) is less standardized across sources than the
single 20-minute test. **✓ Verified by direct fetch this session** against
TrainerDay's own purpose-built "TEST 2x20 FTP Intervals" workout template
(app.trainerday.com/workouts/test-2x20-ftp-intervals): 10 min warm-up
(40-85% FTP) / 20 min @ 100% FTP / 10 min recovery @ 50% FTP / 20 min @
100% FTP / 15 min cool-down. **Confidence: medium** -- a real, concrete,
purpose-built practical template, not from Allen & Coggan's own book
directly.

The 10-minute recovery duration is corroborated by a second, independent
source: the real, well-documented CTS/TrainerRoad two-effort **8-minute**
FTP test's own protocol -- "two 8-minute time trials separated by 10
minutes of easy spinning recovery" (trainright.com, Chris Carmichael/CTS,
✓ direct-fetch confirmed this session) -- convergent on the same 10-minute
figure at a different effort-duration scale, not just one source repeating
itself. A third source (an Endurance Nation-attributed Slowtwitch forum
description) instead described only a 2-minute recovery between the two
20-minute efforts, with FTP taken as the normalized power of the entire
42-minute block rather than a percentage discount -- a real, divergent
convention, noted here honestly but NOT adopted: the 10-minute figure has
two independent convergent sources against this one, and the NP-of-whole-
block formula is a fundamentally different (and more complex) calculation
than this engine's existing `ftp_from_ramp_test`-style pure-arithmetic
shape.

## FTP formula: 0.95 x the average of both efforts

`Coach judgment:` no single authoritative source states a 2x20-specific
formula. `ftp_from_2x20_test` extends the well-established single-effort
0.95 convention above to two efforts by averaging them first -- the same
way trainright.com's own documented convention combines the CTS 8-minute
test's two efforts ("apps... average the two average power outputs,
multiply by .90"), as opposed to that same source's alternative CTS-coach
convention of taking only the HIGHER of the two efforts. Averaging (not
"take the higher") was chosen here for its plain pure-arithmetic shape
(order-independent, no judgment call about which effort to discard) and
because it doesn't silently reward a strong first effort at a fatigued
second effort's expense -- a real test result should reflect both efforts,
not just the better one. **Confidence: medium** (the 0.95 figure itself is
high-confidence per Allen & Coggan; averaging two efforts before applying
it is this file's own reasoned extension, not independently sourced).
**Test:** if this reading consistently sits well below a subsequent single
20-minute test or a real sustained race effort, treat that as this
athlete's own individual-variation signal and prefer the more recent real
result -- same posture `24`'s ramp-test section already documents for its
own formula.

## Pacing cue (prescription text, not a target)

The athlete-facing "Why:" line on `_bike_2x20_test_structure`'s trailing
step carries real, sourced pacing guidance, never a power number: "start
controlled, don't blow up in the first 5 minutes." **✓ Verified by direct
fetch this session** against TrainerRoad's own FTP-assessment blog post
(trainerroad.com/blog/ftp-assessment-tips): "From the start, build your
power quickly but controlled, then hold it high and steady... the simplest
advice is don't go out too hard." A legitimate coaching CUE -- distinct
from a power/zone target, which the work steps themselves never carry
(`WorkoutTarget(basis="rpe")` only -- see `plan.py`'s own module comment on
this build's real defect).

## Implementation history

Landed with `engine/ftp-2x20-test` (Build F): `_bike_2x20_test_structure`/
`ftp_from_2x20_test`, wired into `record_threshold_test`'s tool-schema text
and `context.py`'s "don't hand-author what the engine already knows how to
build" guidance (`backend/app/tools.py`, `backend/app/context.py`). No open
deferral beyond the sport-scope routing gap already noted above (shared
with `24`/`25`).
