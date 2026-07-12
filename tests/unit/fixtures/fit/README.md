# .fit fixtures

Four real fixtures exist, all exported from Garmin Connect, activating the
`pytest.mark.skipif`-guarded real-fixture tests in
`tests/unit/test_parse_files.py`.

## real_swim.fit

A pool swim recorded on a Garmin Instinct (2026-03-14, 1623m, 54.0min): 1
`session` frame (`pool_length`, `num_active_lengths`, `total_strokes`,
`total_timer_time`, `total_elapsed_time`), 1 `lap` frame
(`first_length_index`, `num_lengths`, `swim_stroke`), 71 `length` frames
(all `length_type == "active"` -- no idle lengths in this file; carries
`total_strokes`, `total_elapsed_time`, `total_timer_time`, `swim_stroke`,
`avg_swimming_cadence`, `start_time`), 3241 `record` frames, and 2 `event`
frames (a single timer start/stop_all pair spanning the whole activity, no
mid-activity pause).

Verified before committing (via `fitdecode`, scanning every frame including
all `record` messages) that the file carries no `position_lat`/
`position_long` or other GPS/location data -- pool swims on this device
don't record GPS. The `record` frames only contain `heart_rate` (field
defined but always `None` in every one of the 3241 records -- this device
doesn't capture wrist HR during pool swims), `temperature`, and
`timestamp`. This repo is public, so do not replace this fixture with a
`.fit` file that has GPS or real HR data.

Note for anyone extending the analytics: the real device data has one
oddity worth knowing about -- the final length (index 70, `backstroke`)
spans ~19 minutes with only 5 recorded strokes (`total_elapsed_time` =
1135.933s vs. ~25-40s for every other length), apparently a device
auto-length-detection miss rather than a parser bug (its `total_elapsed_time`
is part of the sum that exactly matches the lap's `total_timer_time`). This
produces a large outlier SWOLF value in the last quartile of
`swolf_trend`'s output for this specific file -- real data, not a
computation error.

## real_kayak.fit

A ~5h03m kayak activity (2026-07-09, 11,494m), exported to validate
cross_train `.fit` ingest with GPS/HR/distance record-level telemetry: 1
`session` + 1 `lap` frame (`avg_heart_rate`/`max_heart_rate`,
`total_timer_time`, `total_elapsed_time`, start/end `position_lat`/
`position_long`), 4678 `record` frames (`heart_rate`, `distance`,
`timestamp`, `enhanced_altitude`, `enhanced_speed`, `temperature`; the
first ~117 records have no GPS lock yet, so `position_lat`/`position_long`
are absent on those specific frames -- FIT lat/long are semicircles,
converted to degrees as `semicircles * 180 / 2**31`), and 3 `event` frames
(a timer start/stop_all pair plus one `recovery_hr` marker event, no
mid-activity timer pause). No `length` frames (not a pool swim).

Device "smart recording" means record-to-record intervals vary (observed
gaps up to ~19s); `analytics.GAP_THRESHOLD_S = 30.0` is set above that
observed variance specifically so this file's normal sampling gaps aren't
misdetected as pauses -- this file has zero real pauses (elapsed time ==
timer time in the session frame), and the parser's pause count for it is 0,
not a placeholder.

## real_mtb_race.fit

The athlete's 2026-06-13 MTB race (10 laps, ~4h26min, sport="cycling",
sub_sport="mountain" -- resolves to `sport_detail="cycling/mountain"`).
26,678 `record` frames (`heart_rate` present on 26,644 of them, plus
`distance`, `speed`/`enhanced_speed`, `position_lat`/`position_long`,
`temperature`), 10 `lap` frames, 1277 `event` frames (almost all
`rear_gear_change` marker events from the bike's electronic shifting --
irrelevant to this parser, which only reads `event == "timer"` frames --
plus exactly one `timer` start/stop_all pair spanning the whole activity,
verified via fitdecode). No `length` frames (not a pool swim). Many other
frame types (`time_in_zone`, `split`, `device_info`, `jump`, several
`unknown_*` types the FIT SDK profile installed here doesn't decode) are
present and ignored by this parser -- normal for a modern head-unit export,
not a parsing gap.

**Calibration fixture for the stationary-speed pause detector**
(`analytics.stationary_pauses`, `STATIONARY_SPEED_MPS`/`STATIONARY_MIN_S` --
see `library/11-workout-analytics.md`). This device records with
**auto-pause off**: the single timer start/stop_all pair above means the
existing timer-event and `GAP_THRESHOLD_S` record-gap detectors find *zero*
pauses in this file even though the athlete demonstrably stopped multiple
times (a pre-race start-corral wait, five per-lap bottle stops). Only the
speed series exposes those stops. At the 0.5 m/s / 30s thresholds this repo
uses, the detector finds the start-corral wait plus all five bottle stops
(no other spurious spans on this particular file) -- see
`tests/unit/test_parse_files.py`'s `test_parse_fit_mtb_race_detects_
stationary_bottle_stops` for the pinned assertions (re-derived from actually
running the parser, not hardcoded from memory).

## real_mtb_0709.fit

The athlete's 2026-07-09 MTB ride (~4h50min, sport="cycling",
sub_sport="mountain" -- same `sport_detail="cycling/mountain"` resolution
as the race fixture above). 17,380 `record` frames (`distance`,
`speed`/`enhanced_speed`, `position_lat`/`position_long`, `temperature` --
**no `heart_rate`** on any record, unlike the race fixture: this ride
wasn't recorded with a paired HR strap/watch-optical reading, verified via
fitdecode scanning every record). Same auto-pause-off behavior as
real_mtb_race.fit: one timer start/stop_all pair, zero timer/gap pauses.

More technical/stop-and-go terrain than the race fixture: at a 15s
minimum-duration floor, the stationary detector produces ~93 spurious
sub-15s spans on this file (almost certainly slow technical singletrack
misread as stops, not real ones) -- this is the real evidence behind this
project's `STATIONARY_MIN_S = 30.0` floor choice (see
`library/11-workout-analytics.md`). At the 30s floor this repo actually
uses, one specific stop -- a ~69s feed/mechanical stop around the 22-minute
mark -- is pinned in `tests/unit/test_parse_files.py`'s
`test_parse_fit_mtb_0709_detects_stationary_feed_stop`.

Both MTB files, together with real_kayak.fit above, are also the evidence
behind `parse_files._is_cycling_sport` gating the stationary detector to
FIT sessions whose raw sport is `"cycling"` only: running the same 0.5 m/s
/ 30s thresholds against real_kayak.fit (also auto-pause-off, also carrying
a full speed series) produces ~50 false-positive "stops", because that
trip's average speed (0.63 m/s) sits right at the threshold -- there's no
"fast baseline, rare real stop" structure for a naturally slow-cruising
sport to exploit. See `library/11-workout-analytics.md`'s
"Stationary-speed pause detection" section for the full writeup.

All four files: do not fabricate a synthetic `.fit` binary as a substitute
-- the FIT binary format is intricate enough (CRC, message definitions,
field encodings) that a hand-rolled fake would validate the parser against
assumptions rather than reality, defeating the point of the fixture.
