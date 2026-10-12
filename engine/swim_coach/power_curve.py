"""Mean-maximal power (power-duration) curve for one ride -- pure, no I/O.

For each standard duration, the highest average power the athlete held over
any contiguous window of that length in the ride, plus where that window
started. Duration set, the nulls-as-zero convention and the pause handling
are grounded in `library/26-activity-stream-interval-analysis.md`
("Mean-maximal power curve").

Conventions (all deliberate, all matched to intervals.icu so numbers agree
with the tool the athlete already looks at):

* The stream is resampled to 1 Hz on `t_s`. A null power sample is **0 W**
  (coasting / dropout), not "skip it" -- skipping would inflate every short
  window.
* A gap in `t_s` of up to `PAUSE_GAP_S` seconds is a dropout: it is filled
  with 0 W and counts as riding time. A gap LARGER than that is a timer
  pause (auto-pause at a stop, a manual stop): the paused span is removed
  from the timeline instead of being filled with zeros, so no window is
  diluted by -- or rewarded for -- time the athlete was not riding. A window
  may therefore straddle a pause (the riding on either side is joined);
  `start_s` is always reported on the original `t_s` timeline.
* Durations longer than the ride's riding time are omitted.
"""

from __future__ import annotations

from swim_coach.models import PowerCurvePoint

# Largest t_s gap still treated as a signal dropout (filled with 0 W). Beyond it the gap
# is a timer pause and is dropped from the timeline. Coach judgment (library/26).
PAUSE_GAP_S = 5

# Standard durations in seconds (practitioner convention, library/26): 1/2/5/10/15/20/30 s,
# 1/2/3/5/10/15/20/30/60/90/120 min, then every 30 min for as long as the ride lasts.
_BASE_DURATIONS_S = (
    1, 2, 5, 10, 15, 20, 30,
    60, 120, 180, 300, 600, 900, 1200, 1800, 3600, 5400, 7200,
)
_LONG_STEP_S = 1800


def standard_durations(riding_s: int) -> list[int]:
    """The standard durations that fit in `riding_s` seconds of riding."""
    out = [d for d in _BASE_DURATIONS_S if d <= riding_s]
    d = 7200 + _LONG_STEP_S
    while d <= riding_s:
        out.append(d)
        d += _LONG_STEP_S
    return out


def _riding_timeline(t_s: list, power_w: list) -> tuple[list[float], list[float]]:
    """1 Hz riding-time power values (nulls and short gaps as 0 W, long gaps
    removed) and the original `t_s` second each value sits at."""
    watts: list[float] = []
    clock: list[float] = []
    prev_t: float | None = None
    for t, p in zip(t_s, power_w):
        if t is None:
            continue
        if prev_t is not None:
            gap = t - prev_t
            if gap <= 0:
                continue  # duplicate / out-of-order timestamp
            if gap <= PAUSE_GAP_S:
                for k in range(1, int(round(gap))):
                    watts.append(0.0)
                    clock.append(prev_t + k)
            # else: a timer pause -- nothing is inserted
        watts.append(float(p) if p is not None else 0.0)
        clock.append(float(t))
        prev_t = t
    return watts, clock


def power_curve(series: dict | None) -> list[PowerCurvePoint] | None:
    """Mean-maximal power curve, or `None` when the series has no power channel
    (or no power samples at all)."""
    if not series:
        return None
    t_s = series.get("t_s") or []
    power = series.get("power_w") or []
    if not t_s or not power or all(p is None for p in power):
        return None
    watts, clock = _riding_timeline(t_s, power)
    n = len(watts)
    if n == 0:
        return None
    cum = [0.0]
    for w in watts:
        cum.append(cum[-1] + w)
    points: list[PowerCurvePoint] = []
    for d in standard_durations(n):
        best_sum, best_i = -1.0, 0
        for i in range(n - d + 1):
            s = cum[i + d] - cum[i]
            if s > best_sum:
                best_sum, best_i = s, i
        points.append(
            PowerCurvePoint(
                duration_s=d,
                watts=int(round(best_sum / d)),
                start_s=round(clock[best_i], 1),
            )
        )
    return points or None


# Verdict of a prescribed warm-up build (a <10 s rep) in which no burst was ridden: not a
# start, not scored. Set by interval_analysis; the coach view leaves these out of `efforts`.
WARMUP_BUILD_VERDICT = "warm-up build (not scored)"

BEST_WINDOWS_DAYS = (42, 90)

COACH_DURATIONS_S = (1, 5, 15, 30, 60, 300, 600, 1200, 3600)


def _label(d: int) -> str:
    return f"{d}s" if d < 60 else f"{d // 60}min"


def coach_summary(curve: list[PowerCurvePoint] | None) -> list[dict]:
    """Compact curve for the coach: only `COACH_DURATIONS_S`, each with the prior
    42/90-day bests and new-best flags (the full array stays in storage)."""
    if not curve:
        return []
    return [
        {
            "duration": _label(p.duration_s),
            "watts": p.watts,
            "best_42d_w": p.best_42d_w,
            "best_90d_w": p.best_90d_w,
            "new_best_42d": p.is_best_42d,
            "new_best_90d": p.is_best_90d,
        }
        for p in curve
        if p.duration_s in COACH_DURATIONS_S
    ]


STARTS_COACH_NOTE = (
    "Starts are skill practice. A single weak start (missed clip, slow launch) is a skill rep, "
    "not fatigue and not a reason to stop; only consecutive or steadily declining starts read as "
    "fatigue. The drop vs the best start is a post-ride review number -- the athlete cannot see "
    "10% mid-ride. Judge a start by held seconds vs intended, not only by peak power."
)


SWIM_ONLY_FIELDS = (
    "split_label", "first_half_pace_s_per_100m", "second_half_pace_s_per_100m",
    "swolf_first_quarter", "swolf_last_quarter", "swolf_degradation_pct",
)
COACH_START_DROP = ("trace_cadence", "prescribed_s", "s_to_peak")
POWER_ONLY_FIELDS = ("power_curve", "avg_power_w", "normalized_power_w", "intervals")


def _prune(x):
    """Drop None values and empty lists/dicts recursively (the coach does not need to read
    what is absent)."""
    if isinstance(x, dict):
        return {k: v for k, v in ((k, _prune(v)) for k, v in x.items()) if v is not None and v != [] and v != {}}
    if isinstance(x, list):
        return [_prune(v) for v in x]
    return x


def _is_bike(analytics, sport: str | None) -> bool:
    if sport is not None:
        return sport == "bike"
    return analytics.intervals is not None or analytics.power_curve is not None or analytics.avg_power_w is not None


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


def analytics_for_coach(analytics, sport: str | None = None) -> dict | None:
    """`WorkoutAnalytics` as a JSON dict in the order the coach should read it, with the power
    curve swapped for its compact coach view (used by the per-workout detail surfaces, never
    the always-loaded context). The power curve leads, then within `intervals` the starts
    table, its flag and note, then the rest, and `efforts` last. Null keys are dropped; swim-only
    fields are dropped for a ride (and power fields for anything else) -- `sport` says which,
    inferred from what the analytics hold when omitted; starts, warm-up builds and
    single-rep rounds are not repeated as efforts/rounds (see `_slim_efforts_and_rounds`)."""
    if analytics is None:
        return None
    out = analytics.model_dump(mode="json")
    bike = _is_bike(analytics, sport)
    for k in SWIM_ONLY_FIELDS if bike else POWER_ONLY_FIELDS:
        out.pop(k, None)
    if out.get("power_curve"):
        out["power_curve"] = coach_summary(analytics.power_curve)
    iv = out.get("intervals")
    if iv:
        if iv.get("starts"):
            iv["starts_note"] = STARTS_COACH_NOTE
        iv.pop("schema_version", None)
        for st in iv.get("starts") or []:
            for k in COACH_START_DROP:  # stored for the PWA; the verdict/launch fields carry these
                st.pop(k, None)
            if not st.get("weak_start"):
                st.pop("weak_start", None)
        _slim_efforts_and_rounds(iv)
        lead = [k for k in ("starts", "starts_flag", "starts_note") if k in iv]
        rest = [k for k in iv if k not in lead and k != "efforts"]
        out["intervals"] = {k: iv[k] for k in [*lead, *rest, *(["efforts"] if "efforts" in iv else [])]}
        out = {
            **{k: out[k] for k in ("power_curve",) if k in out},
            **{k: v for k, v in out.items() if k not in ("power_curve", "intervals")},
            "intervals": out["intervals"],
        }
    elif "power_curve" in out:
        out = {"power_curve": out.pop("power_curve"), **out}
    return _prune(out)


def annotate_bests(
    curve: list[PowerCurvePoint], prior: list[tuple[int, list[PowerCurvePoint]]]
) -> list[PowerCurvePoint]:
    """Fill `best_42d_w`/`best_90d_w` and `is_best_*` from earlier rides' curves.

    `prior` is `(days_before_this_ride, curve)` per earlier ride that has a stored
    curve (rides without one are simply absent). A duration with no prior value in a
    window gets `None` for that window -- unknown, not "a new best". Ties are not a
    new best."""
    out: list[PowerCurvePoint] = []
    for pt in curve:
        upd: dict = {}
        for days in BEST_WINDOWS_DAYS:
            vals = [
                q.watts
                for age, c in prior
                if 0 < age <= days
                for q in c
                if q.duration_s == pt.duration_s
            ]
            best = max(vals) if vals else None
            upd[f"best_{days}d_w"] = best
            upd[f"is_best_{days}d"] = None if best is None else pt.watts > best
        out.append(pt.model_copy(update=upd))
    return out
