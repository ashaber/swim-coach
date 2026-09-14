# Activity-stream fixtures

Real, already-parsed columnar series data (the `dict[str, list]` shape
`parse_files._build_series` produces / `interval_analysis` consumes), saved
as JSON rather than a raw `.fit` -- for cases where the analyzer under test
consumes a specific set of channels and the provenance is a workout already
synced from a third-party source (not a locally-recorded `.fit` file), so a
`.fit`-fixture pipeline doesn't apply.

## real_bike_5x2min_vo2.json

Andrew's real 2026-09-12 bike ride, synced via intervals.icu (workout id
`656e6e84-4cdf-49cf-a888-01a38144a73a`, `external_id`
`intervals:i186049001`), pulled via `store_db.DbStore.load_series`. Prescribed
main set: 5x2min VO2, target 309.1W (110-114% of a 276W FTP).

Trimmed to the four channels `interval_analysis.py` actually reads
(`t_s`, `power_w`, `hr`, `grade`) -- `lat`/`lng`/`dist_m`/`speed_mps`/
`altitude_m`/`cadence_rpm` dropped from the original pulled series. This
repo is public; the dropped channels carry GPS track data (this ride's
route, and by extension home/start-location information) that has no
bearing on interval detection and has no place in a committed fixture.
`power_w`, `hr`, and `grade` are the athlete's real, unaltered training
numbers -- not sensitive to publish, and exactly what
`interval_analysis.detect_efforts`/`assess_effort`/`analyze` need.

**Calibration fixture for `EFFORT_MIN_S_TOLERANCE_S`**
(`interval_analysis.EFFORT_MIN_S_TOLERANCE_S` -- see
`library/26-activity-stream-interval-analysis.md`). All 5 reps of the
prescribed set were genuinely well-executed and in-band (101-103% of
target), but before the tolerance fix only 3 were detected: two real reps
(the 2nd and 5th) measured 119.00s and 118.00s -- a couple of seconds short
of the old rigid `EFFORT_MIN_S = 120.0` floor from real ramp-up/settle-out
lag at the effort boundary -- and were silently dropped. See
`tests/unit/test_interval_analysis.py`'s
`test_real_5x2min_vo2_set_detects_all_five_reps` for the pinned assertions
(re-derived from actually running the analyzer, not hardcoded from memory).

Do not fabricate a synthetic replacement for this fixture -- the whole point
is exercising the analyzer against a real device power stream's real
sample-to-sample noise at the effort boundary, which a hand-rolled series
would not reproduce faithfully.
