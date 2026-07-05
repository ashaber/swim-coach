# real_swim.fit

`parse_fit` (engine/swim_coach/parse_files.py) has no real `.fit` fixture
to test against yet. Export a real pool swim `.fit` file from Garmin
Connect (Activity -> ... -> Export Original) and drop it here as
`real_swim.fit` to activate the tests guarded by
`pytest.mark.skipif(not FIXTURE.exists(), ...)` in
`tests/unit/test_parse_files.py`.

Do not fabricate a synthetic `.fit` binary as a substitute -- the FIT
binary format is intricate enough (CRC, message definitions, field
encodings) that a hand-rolled fake would validate the parser against
assumptions rather than reality, defeating the point of the fixture.
