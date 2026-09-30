"""web/src/shape.js copies the engine's bike zone bounds so the workout shape
chart works offline. This fails if the two drift."""

from __future__ import annotations

import re
from pathlib import Path

from swim_coach.zones import _BIKE_ZONE_BOUNDS

SHAPE_JS = Path(__file__).resolve().parents[2] / "web" / "src" / "shape.js"


def test_js_zone_table_matches_engine_bounds() -> None:
    text = SHAPE_JS.read_text()
    rows = re.findall(r"\{ zone: '(Z\d)', loPct: ([\d.]+), hiPct: (null|[\d.]+) \}", text)
    js = [(z, None if hi == "null" else float(hi)) for z, _lo, hi in rows]
    assert js == [(name, hi) for name, hi in _BIKE_ZONE_BOUNDS]
    los = [float(lo) for _z, lo, _hi in rows]
    his = [hi for _z, hi in js[:-1]]
    assert los == [0.0] + his
