"""Synthetic MTB/CX ride with Garmin dynamics (grit/flow/jumps), shared by the unit tests.

Deterministic and GPS-free. Three ~1 km laps at 1 Hz: lap 2 and 3 are slower through sector 5
(the "loss" sector) and flow worsens lap over lap while power holds. Per-record `grit` is the
device's raw increment (kGrit x 1000: ~9 per record, summing to the session's total_grit x 1000), per-record `flow` is 0 while stopped.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

LAP_S = (300, 312, 336)  # lap durations
LAP_M = 1000.0
START = datetime(2026, 10, 4, 15, 0, 0, tzinfo=timezone.utc)
JUMP_OFFSETS_S = (40, 95, 150, 340, 420, 700)


def _speed_profile(lap: int, n: int) -> list[float]:
    """Metres per second for each second of a lap, scaled so the lap covers LAP_M exactly."""
    base = [1.0] * n
    slow = {0: 0.0, 1: 0.35, 2: 0.7}[lap]  # extra time lost through sector 5 on later laps
    lo, hi = int(n * 4 / 8), int(n * 5 / 8)
    for i in range(lo, hi):
        base[i] = 1.0 - slow * 0.5
    total = sum(base)
    return [b * LAP_M / total for b in base]


def build_series() -> dict:
    rng = random.Random(7)
    t_s, dist_m, speed, power, grit, flow = [], [], [], [], [], []
    t = 0
    d = 0.0
    for lap, n in enumerate(LAP_S):
        prof = _speed_profile(lap, n)
        for i in range(n):
            d += prof[i]
            t_s.append(float(t))
            dist_m.append(round(d, 2))
            speed.append(round(prof[i], 3))
            power.append(round(210 + rng.uniform(-15, 15)))
            grit.append(float(rng.randint(3, 15)) if i % 10 else 0.0)
            f = 0.0 if i < 3 else float(rng.randint(2, 4) + lap)  # whole numbers: fit_tool truncates fractions
            flow.append(f)
            t += 1
    return {"t_s": t_s, "dist_m": dist_m, "speed_mps": speed, "power_w": power, "grit": grit, "flow": flow}


def lap_starts() -> list[int]:
    out, acc = [], 0
    for n in LAP_S:
        out.append(acc)
        acc += n
    return out


def jumps() -> list[dict]:
    return [
        {"offset_s": float(o), "distance_m": 4.0 + i, "height_m": 1.0 + i, "hang_time_s": 1.0 + i,
         "score": 40.0 + i, "speed_mps": 6.0}
        for i, o in enumerate(JUMP_OFFSETS_S)
    ]


def write_fit(path: Path) -> Path:
    """The same ride as a real FIT file (session + 3 laps + records + jump messages)."""
    from fit_tool.fit_file_builder import FitFileBuilder
    from fit_tool.profile.messages.jump_message import JumpMessage
    from fit_tool.profile.messages.lap_message import LapMessage
    from fit_tool.profile.messages.record_message import RecordMessage
    from fit_tool.profile.messages.session_message import SessionMessage
    from fit_tool.profile.profile_type import Sport, SubSport

    def ms(offset: float) -> int:
        return int((START + timedelta(seconds=offset)).timestamp() * 1000)

    series = build_series()
    total_s = float(sum(LAP_S))
    builder = FitFileBuilder(auto_define=True)
    for i, t in enumerate(series["t_s"]):
        r = RecordMessage()
        r.timestamp = ms(t)
        r.distance = series["dist_m"][i]
        r.speed = series["speed_mps"][i]
        r.power = int(series["power_w"][i])
        r.grit = series["grit"][i]
        r.flow = series["flow"][i]
        builder.add(r)
    for o, n in zip(lap_starts(), LAP_S):
        lap = LapMessage()
        lap.start_time = ms(o)
        lap.timestamp = ms(o + n)
        lap.total_timer_time = float(n)
        lap.total_elapsed_time = float(n)
        lap.total_distance = LAP_M
        builder.add(lap)
    for j in jumps():
        m = JumpMessage()
        m.timestamp = ms(j["offset_s"])
        m.distance = j["distance_m"]
        m.height = j["height_m"]
        m.hang_time = j["hang_time_s"]
        m.score = j["score"]
        m.speed = j["speed_mps"]
        builder.add(m)
    s = SessionMessage()
    s.start_time = ms(0)
    s.timestamp = ms(total_s)
    s.total_timer_time = total_s
    s.total_elapsed_time = total_s
    s.total_distance = LAP_M * len(LAP_S)
    s.sport = Sport.CYCLING
    s.sub_sport = SubSport.MOUNTAIN
    s.total_grit = round(sum(series["grit"]) / 1000)
    s.avg_flow = 4.0
    s.jump_count = len(JUMP_OFFSETS_S)
    builder.add(s)
    builder.build().to_file(str(path))
    return path
