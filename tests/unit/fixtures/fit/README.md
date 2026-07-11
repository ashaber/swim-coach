# .fit fixtures

Two real fixtures exist, both exported from Garmin Connect, activating the
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

Both files: do not fabricate a synthetic `.fit` binary as a substitute --
the FIT binary format is intricate enough (CRC, message definitions, field
encodings) that a hand-rolled fake would validate the parser against
assumptions rather than reality, defeating the point of the fixture.
