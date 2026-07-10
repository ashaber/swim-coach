# real_swim.fit

A real fixture now exists: a pool swim recorded on a Garmin Instinct
(2026-03-14, 1623m, 54.0min), exported from Garmin Connect. It activates
the tests guarded by `pytest.mark.skipif(not FIXTURE.exists(), ...)` in
`tests/unit/test_parse_files.py`.

Verified before committing (via `fitdecode`, scanning every frame
including all `record` messages) that the file carries no
`position_lat`/`position_long` or other GPS/location data -- pool
swims on this device don't record GPS. The `record` frames only
contain heart_rate, temperature, and timestamp. This repo is public,
so do not replace this fixture with a `.fit` file that has GPS data.

Do not fabricate a synthetic `.fit` binary as a substitute -- the FIT
binary format is intricate enough (CRC, message definitions, field
encodings) that a hand-rolled fake would validate the parser against
assumptions rather than reality, defeating the point of the fixture.
