"""The coach's view of a ride's analytics: ordering and slimming of the power fields.

Used by `analysis.BikeAnalyzer.coach_view` (the per-workout detail surfaces, never the
always-loaded context). The power curve leads (as its compact summary), then within `intervals`
the starts table, its flag and note, then the rest, and `efforts` last; starts, warm-up builds
and single-rep rounds are not repeated as efforts/rounds (see `_slim_efforts_and_rounds`).
"""

from __future__ import annotations

from swim_coach.models import WorkoutAnalytics
from swim_coach.power_curve import WARMUP_BUILD_VERDICT, coach_summary

STARTS_COACH_NOTE = (
    "Starts are skill practice. A single weak start (missed clip, slow launch) is a skill rep, "
    "not fatigue and not a reason to stop; only consecutive or steadily declining starts read as "
    "fatigue. The drop vs the best start is a post-ride review number -- the athlete cannot see "
    "10% mid-ride. Judge a start by held seconds vs intended, not only by peak power. "
    "For starts, lead with the top start_finding and its library/39 cue (the cue_key row): one cause, "
    "one thing to practice."
)

COACH_START_DROP = (
    "trace_cadence", "prescribed_s", "s_to_peak", "launch_rate_w_per_s", "sustain_floor_w", "burst_s", "avg_w",
    "launch_cadence_rpm", "held_s",
)


def _slim_efforts_and_rounds(iv: dict) -> None:
    """Coach view only. Every start lives in the `starts` table, so its effort and its
    prescription round are dropped (as are warm-up builds, whose 5 s averages the coach
    once quoted as starts); the remaining efforts are renumbered 1..N (stored `n` is untouched)
    and shed the per-effort altitude fields (`ride_altitude_*` say it once). Rounds keep their
    stored `n` (efforts point at it with `round_n`) and are left out entirely when every round
    is a single rep, since each such round repeats its effort."""
    start_s = {s.get("burst_start_s") for s in iv.get("starts") or []}
    gone = [
        e for e in iv.get("efforts") or []
        if e.get("verdict") == WARMUP_BUILD_VERDICT or e.get("start_s") in start_s
    ]
    drop_rounds = {e.get("round_n") for e in gone} - {None}
    efforts = [e for e in iv.get("efforts") or [] if e not in gone]
    for i, e in enumerate(efforts, 1):
        e["n"] = i
        for k in ("altitude_context", "altitude_m", "altitude_gain_m", "altitude_decrement_pct"):
            e.pop(k, None)
    iv["efforts"] = efforts
    rounds = [r for r in iv.get("rounds") or [] if r.get("n") not in drop_rounds]
    if any((r.get("reps_prescribed") or 0) > 1 for r in rounds):
        iv["rounds"] = rounds
    else:
        iv.pop("rounds", None)


def _shape_intervals(iv: dict) -> dict:
    if iv.get("starts"):
        iv["starts_note"] = STARTS_COACH_NOTE
    iv.pop("schema_version", None)
    for st in iv.get("starts") or []:
        for k in COACH_START_DROP:  # stored for the PWA; the verdict/launch fields carry these
            st.pop(k, None)
        if not st.get("weak_start"):
            st.pop("weak_start", None)
    _slim_efforts_and_rounds(iv)
    lead = [k for k in ("starts", "start_findings", "starts_flag", "starts_note") if k in iv]
    rest = [k for k in iv if k not in lead and k != "efforts"]
    return {k: iv[k] for k in [*lead, *rest, *(["efforts"] if "efforts" in iv else [])]}


FREE_RIDE_COACH_NOTE = (
    "For a free ride, lead with what mattered: the biggest notable effort, matches burned vs plan, "
    "and whether intensity fit the week."
)
COACH_TOP_EFFORTS = 3


def _clock(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def _zone_line(zones: list[dict]) -> str:
    return ", ".join(f"{z['zone']} {z['seconds'] // 60}m ({z['pct']:.0f}%)" for z in zones if z["seconds"] >= 30)


def _effort_line(e: dict) -> str:
    bits = [f"{e['duration_s'] // 60}min {e['avg_w']}W ({e['pct_ftp']:.0f}% FTP)"]
    if e.get("avg_hr") is not None:
        bits.append(f"HR {e['avg_hr']}")
    if e.get("altitude_gain_m") is not None:
        grade = f" at {e['avg_grade_pct']}%" if e.get("avg_grade_pct") is not None else ""
        bits.append(f"{e['altitude_gain_m']:+.0f} m{grade}")
    bits.append(f"{_clock(e['start_offset_s'])} into the ride")
    line = ", ".join(bits)
    if e.get("label"):
        line += f" -- {e['label']}"
    best = [lbl for lbl, k in (("42d", "new_best_42d"), ("90d", "new_best_90d")) if e.get(k)]
    return line + (f" [new {'/'.join(best)} best]" if best else "")


def _match_line(m: dict) -> str:
    return (
        f"{m['duration_s']}s avg {m['avg_w']}W peak {m['peak_w']}W, "
        f"{m['kj_above_ftp']} kJ above FTP, {_clock(m['start_offset_s'])} in"
    )


def _drift_line(d: dict) -> str:
    return (
        f"{d['duration_min']:.0f} min from {_clock(d['start_offset_s'])}: avg {d['avg_w']}W, "
        f"power CV {d['power_cv_pct']}%, drift {d['drift_pct']:+.1f}%"
    )


def free_ride_coach_view(fr: dict) -> dict:
    """Compact, ordered free-ride block for the coach: data quality, zones, top efforts, matches,
    cost, steady-stretch drift. `fr` is the dumped `FreeRideRead`."""
    matches = fr.get("matches") or {}
    drift = [_drift_line(d) for d in fr.get("steady_drift") or []]
    out = {
        "coach_note": FREE_RIDE_COACH_NOTE,
        "data_quality": fr.get("data_quality_notes"),
        "power_zones_pedalling": _zone_line(fr.get("power_zones") or []),
        "hr_zones": _zone_line(fr.get("hr_zones") or []),
        "coasting": f"{fr['coasting_pct']:.0f}% of moving time",
        "intent_zone": fr.get("intent_zone"),
        "z3_plus_pct_of_pedalling": fr.get("z3_plus_pct"),
        "tempo_creep": fr.get("tempo_creep_note"),
        "notable_efforts": [_effort_line(e) for e in (fr.get("notable_efforts") or [])[:COACH_TOP_EFFORTS]],
        "matches_burned": (
            {
                "count": matches["count"],
                "time_above_ftp_s": matches["time_above_ftp_s"],
                "kj_above_ftp": matches["kj_above_ftp"],
                "top": [_match_line(m) for m in (matches.get("efforts") or [])[:COACH_TOP_EFFORTS]],
            }
            if matches.get("count")
            else None
        ),
        "cost_vs_week": (fr.get("cost") or {}).get("note"),
        "steady_drift": drift or fr.get("steady_note"),
    }
    return {k: v for k, v in out.items() if v not in (None, "", [], {})}


MTB_COACH_NOTE = (
    "Garmin device metrics (proprietary, read-only): Grit = how difficult the ride was (elevation, gradient, "
    "rapid direction changes); Flow = how consistently speed/smoothness is held through turns, so lower Flow "
    "is smoother. Grit is a course-difficulty number: compare laps on the same course, never across courses. "
    "Lap Flow is the mean over the lap's moving records, approximately on Garmin's scale (the exact formula is "
    "unpublished): compare laps with each other. No thresholds exist; read the trend."
)
COURSE_SECTORS_COACH_NOTE = (
    "Each similar-distance lap is cut into course sections: with GPS the best lap is split into straights (S) "
    "and corner sequences (C: corners within ~25 m of each other count as one), numbered in lap order, and "
    "every lap is read through the same sections by track position (so odometer differences do not matter); "
    "without GPS it is cut into 8 equal-distance sectors. The data cannot name what a section is: ask the "
    "rider which feature each top loss section is (run-up, off-camber, sand, climb) before explaining it. "
    "For a corner sequence, entry/min/exit speed show where the time went: slow exit speed costs time all the "
    "way down the next straight. Flow worsening while power holds "
    "reads as technique slipping under fatigue, not fitness. Sector loss is measured against the rider's "
    "own best time through that sector on any lap (so it is never negative): a big spread means an "
    "inconsistent section, so ask what was different on the fast lap. Sector flow is Garmin's per-record "
    "flow averaged over the sector: approximate (Garmin's formula is unpublished), so read it relative "
    "between laps of the same sector, never as an absolute. Verified on a real race file: per-second flow is "
    "~0 on straights (58% of samples), rises with turning rate (mean ~2 below 10 deg/s, ~13 at 30-60 deg/s, "
    "~20 above 60 deg/s), is higher at lower speed, and has ~1-2 s memory -- so sector flow reflects that "
    "sector's cornering and how cleanly it was ridden. Compare the SAME sector across laps, never different "
    "sectors. Grit per second showed no relation to turning, speed or power (|r| < 0.11): treat it as course "
    "roughness/difficulty. Every section edge carries timing noise (1 Hz GPS): a section's loss is only a "
    "finding when it clears the noise floor, so losses inside it are never findings and top_loss_sectors "
    "may be empty. Extra watts (efficiency sections: corners, descents of 10+ s) is a pass's power over "
    "the cheapest pass that was at least as fast; free speed is a pass as fast as another on 30+ W less."
)
COACH_TOP_LOSS_SECTORS = 3
COACH_TOP_JUMPS = 3


def _lap_line(lap: dict) -> str:
    bits = [f"Lap {lap['lap']}: {_clock(lap['duration_s'])}"]
    if lap.get("avg_power_w") is not None:
        bits.append(f"{lap['avg_power_w']:.0f}W")
    if lap.get("grit") is not None:
        bits.append(f"grit {lap['grit']}")
    if lap.get("avg_flow") is not None:
        bits.append(f"flow {lap['avg_flow']}")
    if lap.get("jumps"):
        bits.append(f"{lap['jumps']} jumps")
    return ", ".join(bits)


def mtb_coach_view(m: dict) -> dict:
    """Compact MTB-dynamics block: totals, one line per lap, a jumps summary. `m` is the dumped
    `MtbDynamics`."""
    j = m.get("jumps") or {}
    jumps = None
    if j:
        parts = [f"{j['count']} jumps"]
        for key, label, unit in (("max_height_m", "max height", "m"), ("max_hang_time_s", "max hang time", "s"),
                                 ("max_distance_m", "longest", "m"), ("best_score", "best score", "")):
            if j.get(key) is not None:
                parts.append(f"{label} {j[key]}{unit}")
        jumps = ", ".join(parts)
    out = {
        "coach_note": MTB_COACH_NOTE,
        "total_grit": m.get("total_grit"),
        "avg_flow": m.get("avg_flow"),
        "jump_count": m.get("jump_count"),
        "jumps": jumps,
        "laps": [_lap_line(lap) for lap in m.get("laps") or []],
    }
    return {k: v for k, v in out.items() if v not in (None, "", [], {})}


def _section_line(s: dict, prev: dict | None, count: int) -> str:
    """One top-loss line. Course-feature sections say what they are and what precedes them; the
    equal-distance fallback keeps the plain "Sector N of M" wording."""
    if s.get("kind"):
        what = "corner sequence" if s["kind"] == "corners" else "straight"
        after = f", after {prev['label']} ({prev['length_m']:.0f} m {'corner sequence' if prev['kind'] == 'corners' else 'straight'})" if prev else ""
        head = f"Section {s['label']} ({what}, {s['length_m']:.0f} m{after})"
    else:
        head = f"Sector {s['sector']} of {count}"
    line = f"{head}: loses {s['total_loss_s']:.1f}s total ({s['mean_loss_s']:.1f}s per lap) vs its own best {s['best_time_s']:.1f}s, spread {s.get('spread_s', 0):.1f}s"
    if s.get("kind") == "corners" and s.get("entry_speed_mps") is not None:
        line += f", speed in {s['entry_speed_mps']:.1f} / slowest {s['min_speed_mps']:.1f} / out {s['exit_speed_mps']:.1f} m/s"
    elif s.get("kind") and s.get("avg_speed_mps") is not None:
        line += f", avg {s['avg_speed_mps']:.1f} m/s"
    by_lap = [f for f in s.get("flow_by_lap") or [] if f is not None]
    if s.get("kind") == "corners" and len(by_lap) >= 2:
        line += f", flow {by_lap[0]:.1f} -> {by_lap[-1]:.1f} across laps"
    elif s.get("flow_vs_best") is not None:
        line += f", flow {s['flow_vs_best']:+.2f} vs best"
    if s.get("avg_grit") is not None:
        line += f", grit {s['avg_grit']}"
    return line


def _free_speed_line(f: dict) -> str:
    return (f"{f['label']} lap {f['lap']} matched lap {f['vs_lap']} ({f['time_s']:.1f} vs {f['vs_time_s']:.1f} s) "
            f"on {f['watts_saved']:.0f} W less ({f['power_w']:.0f} vs {f['vs_power_w']:.0f} W)")


def _noise_line(cs: dict) -> str | None:
    if cs.get("edge_noise_s") is None:
        return None
    line = f"section edge timing noise ~{cs['edge_noise_s']:.1f}s; losses inside each section's noise floor are not findings"
    if cs.get("ideal_gap_noise_s") is not None:
        line += (f"; of the {cs['ideal_gap_s']:.1f}s best-lap-to-ideal gap ~{cs['ideal_gap_noise_s']:.1f}s is what noise alone "
                 f"produces ({cs['ideal_gap_beyond_noise_s']:.1f}s beyond it)")
    return line


def course_sectors_coach_view(cs: dict, section_notes: dict | None = None) -> dict:
    """Lap trend + the top loss sectors (the full sector table stays in the stored analytics), free-speed
    passes, the timing-noise statement and the athlete's notes on sections."""
    fade = cs.get("fade") or {}
    trend = [f"time {fade['time_change_pct']:+.1f}% first to last lap"]
    if fade.get("power_change_pct") is not None:
        trend.append(f"power {fade['power_change_pct']:+.1f}%")
    if fade.get("flow_change") is not None:
        trend.append(f"flow {fade['flow_change']:+.2f} ({fade.get('flow_slope_per_lap', 0):+.2f}/lap)")
    laps = [
        f"Lap {lap['lap']}: {_clock(lap['time_s'])}"
        + (f" (+{lap['time_vs_best_s']:.1f}s vs best)" if lap["time_vs_best_s"] else " (best)")
        + (f", flow {lap['avg_flow']}" if lap.get("avg_flow") is not None else "")
        for lap in cs.get("laps") or []
    ]
    rows = cs.get("sectors") or []
    by_n = {s["sector"]: (i, s) for i, s in enumerate(rows)}
    top = []
    for n in (cs.get("top_loss_sectors") or [])[:COACH_TOP_LOSS_SECTORS]:
        i, s = by_n[n]
        top.append(_section_line(s, rows[i - 1] if i and s.get("kind") else None, cs["sector_count"]))
    ideal = None
    if cs.get("ideal_lap_s") is not None:
        ideal = (f"Ideal lap {_clock(cs['ideal_lap_s'])} (best sectors combined); the best lap is "
                 f"{cs['ideal_gap_s']:.1f}s slower than that")
    extra = [f"{s['label']} {s['mean_extra_w']:.0f} W" for s in sorted(
        (r for r in rows if r.get("mean_extra_w") is not None), key=lambda r: -r["mean_extra_w"])[:COACH_TOP_LOSS_SECTORS]]
    notes = [f"{label}: {text}" for label, text in (section_notes or {}).items() if any(r.get("label") == label for r in rows)]
    return {
        "coach_note": COURSE_SECTORS_COACH_NOTE,
        "lap_trend": ", ".join(trend),
        "ideal_lap": ideal,
        "timing_noise": _noise_line(cs),
        "laps": laps,
        "top_loss_sectors": top or ("none clears the timing noise" if rows else None),
        "free_speed": [_free_speed_line(f) for f in cs.get("free_speed") or []],
        "most_extra_watts_per_pass": ", ".join(extra) or None,
        "athlete_notes_on_sections": notes,
    }


RACE_EFFICIENCY_COACH_NOTE = (
    "Efficiency across the race is the first thing to cover: lead the debrief with this lap-to-lap read "
    "(the verdict, then the laps), and only then use the course sections to explain WHERE it changed. "
    "EF is Normalized Power / average HR (watts per bpm) per lap; decoupling is the EF change from the "
    "first half of the laps to the second half, flagged at 5% (an engineering default, not a validated "
    "cutoff). A lap's HR lags power and rises with heat, caffeine and sleep debt, so name those before "
    "calling it fitness. Flow is Garmin's proprietary score: read it only relative between laps."
)


def race_efficiency_coach_view(re: dict) -> dict:
    """Verdict first, then one compact line per lap."""
    laps = []
    for lap in re.get("laps") or []:
        line = f"Lap {lap['lap']}{' (start lap, not in the trend)' if lap.get('start_lap') else ''}: {_clock(lap['time_s'])}"
        for key, label, fmt in (("np_w", "NP", "{:.0f} W"), ("avg_hr", "HR", "{:.0f}"), ("ef", "EF", "{:.2f}"),
                                ("speed_per_100w", "speed/100 W", "{:.2f} m/s"), ("avg_flow", "flow", "{:.1f}")):
            if lap.get(key) is not None:
                line += f", {label} " + fmt.format(lap[key])
        laps.append(line)
    t = re.get("trend") or {}
    slopes = [f"{label} {t[key]:+.{3 if key == 'ef_slope_per_lap' else 1}f}/lap" for key, label in (
        ("time_slope_s_per_lap", "time s"), ("power_slope_w_per_lap", "NP W"),
        ("hr_slope_bpm_per_lap", "HR bpm"), ("ef_slope_per_lap", "EF")) if t.get(key) is not None]
    return {
        "coach_note": RACE_EFFICIENCY_COACH_NOTE,
        "verdict": re["verdict"],
        "laps": laps,
        "slopes": ", ".join(slopes) or None,
        "decoupling_pct": t.get("decoupling_pct"),
    }


LAPS_COACH_NOTE = (
    "These are the ride's canonical laps, the one lap set every lap number in this analysis refers to "
    "(device laps merged where one lap fired twice, a race trimmed to the gun so lap 1 excludes the "
    "warm-up and the wait on the line, missed laps found from the GPS lap mark). A start lap begins at "
    "the race start, not at the mark, so it is shown but never compared with the full laps."
)


def laps_coach_view(laps: list[dict]) -> dict:
    """One compact line per canonical lap, with a note on what the laps are."""
    lines = []
    for lap in laps:
        label = " (start lap, from the gun)" if lap.get("start_lap") else "" if lap.get("comparable") else " (not compared)"
        bits = [_clock(lap["duration_s"])]
        if lap.get("distance_m") is not None:
            bits.append(f"{lap['distance_m']:.0f} m")
        if lap.get("avg_power_w") is not None:
            bits.append(f"{lap['avg_power_w']:.0f} W")
        if lap.get("avg_hr") is not None:
            bits.append(f"HR {lap['avg_hr']}")
        if lap.get("source") == "gps_filled":
            bits.append("found by GPS")
        lines.append(f"Lap {lap['n']}{label}: " + ", ".join(bits))
    return {"coach_note": LAPS_COACH_NOTE, "laps": lines}


def shape_ride_view(out: dict, analytics: WorkoutAnalytics, section_notes: dict | None = None) -> dict:
    """`out` is the field-restricted dump; returns it with the compact curve first and the
    intervals reordered and slimmed; a free ride's compact `free_ride` block leads everything.
    Null pruning is left to the caller."""
    if out.get("power_curve"):
        out["power_curve"] = coach_summary(analytics.power_curve)
    if out.get("intervals"):
        out["intervals"] = _shape_intervals(out["intervals"])
    if "power_curve" in out:
        out = {"power_curve": out.pop("power_curve"), **out}
    dynamics = {}
    if out.get("mtb_dynamics"):
        dynamics["mtb_dynamics"] = mtb_coach_view(out.pop("mtb_dynamics"))
    if out.get("course_sectors"):
        dynamics["course_sectors"] = course_sectors_coach_view(out.pop("course_sectors"), section_notes)
    out.pop("mtb_dynamics", None)
    out.pop("course_sectors", None)
    race_lines = race_view_lines(out.pop("race_overview", None), out.pop("race_start", None), out.pop("finish_sprint", None))
    efficiency = race_efficiency_coach_view(out.pop("race_efficiency")) if out.get("race_efficiency") else None
    if out.get("laps"):
        dynamics = {"laps": laps_coach_view(out.pop("laps")), **dynamics}
    if (out.get("intervals") or {}).get("race_start"):
        # A race leads with its summary and lap-to-lap block; the device/sector detail is the
        # drill-down after it, so the lap-to-lap read keeps the focus.
        out = {**out, **dynamics}
    else:
        out = {**dynamics, **out}
    if efficiency:
        out = {"race_efficiency": efficiency, **out}
    if race_lines:
        out = {"race_view": race_lines, **out}
    if out.get("free_ride"):
        out.pop("cardiac_drift_pct", None)  # no whole-ride drift verdict; the block carries steady-stretch drift
        out = {"free_ride": free_ride_coach_view(out.pop("free_ride")), **out}
    return out


def race_view_lines(overview: dict | None, start: dict | None, sprint: dict | None) -> dict:
    """Terse lines for the race window, the first 40 s (dip, previous race) and a finish sprint."""
    out: dict = {}
    if overview:
        bits = [f"{_clock(overview['duration_s'])} from the start to the line"]
        if overview.get("distance_m") is not None:
            bits.append(f"{overview['distance_m'] / 1000:.1f} km")
        if overview.get("avg_power_w") is not None:
            bits.append(f"avg {overview['avg_power_w']} W / NP {overview.get('np_w')} W / max {overview.get('max_power_w')} W, {overview.get('work_kj')} kJ")
        if overview.get("avg_hr") is not None:
            bits.append(f"HR {overview['avg_hr']} avg / {overview.get('max_hr')} max")
        if overview.get("avg_speed_kmh") is not None:
            bits.append(f"{overview['avg_speed_kmh']} km/h avg / {overview.get('max_speed_kmh')} max")
        if overview.get("avg_cadence_rpm") is not None:
            bits.append(f"cadence {overview['avg_cadence_rpm']}")
        out["race_overview"] = ", ".join(bits)
    if start:
        line = (f"peak {start['peak_w']} W at {start['peak_at_s']}s, 5s avg {start['mean_5s_w']} W, 15s avg {start['mean_15s_w']} W, "
                f"top {start['top_speed_kmh']} km/h at {start['top_speed_at_s']}s")
        if start.get("dip"):
            line += f"; power fell to {start['dip']['power_w']} W at {start['dip']['at_s']}s (a shift or bobble?)"
        prev = start.get("previous")
        if prev:
            line += f"; previous race ({prev['date']}): 15s avg {prev.get('mean_15s_w')} W, top {prev.get('top_speed_kmh')} km/h"
        out["race_start_trace"] = line
    if sprint:
        out["finish_sprint"] = (f"{sprint['duration_s']}s avg {sprint['avg_w']} W (peak {sprint['peak_w']} W), "
                                f"{sprint.get('entry_speed_kmh')} -> {sprint.get('exit_speed_kmh')} km/h to the line")
    return out
