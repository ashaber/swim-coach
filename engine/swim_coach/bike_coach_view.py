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


def shape_ride_view(out: dict, analytics: WorkoutAnalytics) -> dict:
    """`out` is the field-restricted dump; returns it with the compact curve first and the
    intervals reordered and slimmed; a free ride's compact `free_ride` block leads everything.
    Null pruning is left to the caller."""
    if out.get("power_curve"):
        out["power_curve"] = coach_summary(analytics.power_curve)
    if out.get("intervals"):
        out["intervals"] = _shape_intervals(out["intervals"])
    if "power_curve" in out:
        out = {"power_curve": out.pop("power_curve"), **out}
    if out.get("free_ride"):
        out = {"free_ride": free_ride_coach_view(out.pop("free_ride")), **out}
    return out
