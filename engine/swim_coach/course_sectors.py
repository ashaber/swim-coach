"""Lap-over-lap course sectors: where on a repeated course the time (and smoothness) went.

For a ride with 2+ comparable canonical laps (`canonical_laps`: CX/MTB race laps, a lap-per-circuit
pre-ride -- full laps from the lap mark of similar distance), each compared lap is cut into sections that line up across laps. With GPS the sections are course
features (`course_features`: straights vs corner sequences found on the best lap, every lap read
through them by track position, so odometer differences do not matter); without GPS, or when the
track has no usable features, into `SECTOR_COUNT` equal-DISTANCE sectors. Output: per-lap time / power / flow / grit, the fade first -> last lap
(including the flow trend: flow worsening while power holds reads as technique slipping under
fatigue), and a per-sector loss table with the top-3 loss sectors. Loss is measured against the fastest time
through THAT sector on any lap (the motorsport "ideal lap"), so it is never negative.

Constants are Coach judgment, not sourced: SECTOR_COUNT, TRACK_POINTS, MAX_LAPS.
Flow and grit are Garmin's proprietary device metrics (see `mtb_dynamics`); they are shown beside
the time loss, never thresholded. The data cannot name what a section IS (run-up, sand, off-camber) -- the coach asks the rider.
"""

from __future__ import annotations

from bisect import bisect_left
from typing import Mapping, Sequence

from swim_coach.course_features import MIN_SECTIONS, Section, align_edges, cumulative_m, project_xy, segment_course, split_sections
from swim_coach.models import CanonicalLap, CourseSectors, CourseTrack, LapFade, SectorLap, SectorLoss, SectorPass, TrackSector
from swim_coach.mtb_dynamics import GRIT_RECORD_SCALE, has_channel, mean_moving, mean_present, window_indices
from swim_coach.section_noise import SectionNoise, loss_noise_floor, section_sigmas
from swim_coach.section_passes import efficiency_applies, free_speed, pass_extras, terrain_of

SECTOR_COUNT = 8  # Coach judgment: enough resolution to localise a loss, still ~10+ s per sector
MAX_LAPS = 12  # Coach judgment: more than this is auto-lap noise (e.g. every km), not a course
TOP_LOSS_SECTORS = 3
TRACK_POINTS = 200  # Coach judgment: enough to draw a recognisable lap outline, small enough to store


def _t_at(dist: Sequence[float], t: Sequence[float], d: float) -> float:
    i = bisect_left(dist, d)
    if i <= 0:
        return t[0]
    if i >= len(dist):
        return t[-1]
    span = dist[i] - dist[i - 1]
    return t[i] if span <= 0 else t[i - 1] + (t[i] - t[i - 1]) * (d - dist[i - 1]) / span


def _even_edges(series: dict, idx: range, span: tuple[float, float]) -> list[float] | None:
    """SECTOR_COUNT equal-distance sector edges (times) through one lap, None if the lap has no usable
    distance. The first and last edge are the lap's own span (`CanonicalLap.start_s` / `end_s`): a lap
    runs to the next lap's start, so its time is the canonical duration, not first-to-last sample."""
    t_s, dist = series["t_s"], series["dist_m"]
    pts = [(t_s[i], dist[i]) for i in idx if dist[i] is not None]
    if len(pts) < SECTOR_COUNT + 1:
        return None
    t = [p[0] for p in pts]
    d = [p[1] for p in pts]
    for i in range(1, len(d)):  # distance never runs backwards inside a lap
        d[i] = max(d[i], d[i - 1])
    total = d[-1] - d[0]
    if total <= 0:
        return None
    inner = [_t_at(d, t, d[0] + total * k / SECTOR_COUNT) for k in range(SECTOR_COUNT + 1)]
    return [span[0], *inner[1:-1], span[1]]


def _speeds_through(speed: Sequence[float | None], sec: range) -> tuple[float | None, float | None, float | None]:
    """`(entry, slowest, exit)` speed over the section's records, None where there are none."""
    vals = [speed[i] for i in sec if speed[i] is not None]
    return (speed[sec[0]], min(vals), speed[sec[-1]]) if vals and speed[sec[0]] is not None and speed[sec[-1]] is not None else (None, None, None)


def _value_at(t_s: Sequence[float], vals: Sequence[float | None], t: float) -> float | None:
    """`vals` linearly interpolated at time `t` (None if either neighbour is missing)."""
    i = bisect_left(t_s, t)
    if i <= 0:
        return vals[0] if t_s and t <= t_s[0] else None
    if i >= len(t_s):
        return vals[-1]
    a, b = vals[i - 1], vals[i]
    if a is None or b is None:
        return None
    span = t_s[i] - t_s[i - 1]
    return b if span <= 0 else a + (b - a) * (t - t_s[i - 1]) / span


def _alt_change(t_s: Sequence[float], alt: Sequence[float | None], start: float, end: float) -> float | None:
    a, b = _value_at(t_s, alt, start), _value_at(t_s, alt, end)
    return None if a is None or b is None else b - a


def _cut(series: dict, idx: range, edges: list[float]) -> dict:
    """One lap cut at `edges` (times): per-section time / flow / grit / speed / power, plus lap totals."""
    t_s = series["t_s"]
    flow, grit, power = series.get("flow") or [], series.get("grit") or [], series.get("power_w") or []
    speed = series.get("speed_mps") or []
    n = len(edges) - 1
    times, flows, grits, speeds, powers, passes = [], [], [], [], [], []
    alt = series.get("altitude_m") or []
    alts = [_alt_change(t_s, alt, edges[k], edges[k + 1]) if alt else None for k in range(n)]
    for k in range(n):
        sec = window_indices(t_s, edges[k], edges[k + 1])
        sec = range(max(sec.start, idx.start), min(sec.stop, idx.stop))
        times.append(round(edges[k + 1] - edges[k], 2))
        flows.append(mean_moving(flow, speed, sec) if flow else None)
        vals = [grit[i] for i in sec if grit[i] is not None] if grit else []
        grits.append(round(sum(vals) / GRIT_RECORD_SCALE, 3) if vals else None)
        speeds.append(mean_present(speed, sec) if speed and len(sec) else None)
        powers.append(mean_present(power, sec) if power and len(sec) else None)
        passes.append(_speeds_through(speed, sec) if speed and len(sec) else (None, None, None))
    return {"edges": edges, "idx": idx, "time_s": round(edges[-1] - edges[0], 1), "times": times, "flows": flows, "grits": grits,
            "speeds": speeds, "powers": powers, "passes": passes, "alts": alts,
            "power": mean_present(power, idx) if power else None,
            "flow": mean_moving(flow, speed, idx) if flow else None,
            "grit": round(sum(v for v in (grit[i] for i in idx) if v is not None) / GRIT_RECORD_SCALE, 2)
            if has_channel(series, "grit") else None}


def _evenly(indices: list[int], limit: int) -> list[int]:
    """At most `limit` of `indices`, evenly spread, always keeping the first and the last."""
    if len(indices) <= limit:
        return indices
    step = (len(indices) - 1) / (limit - 1)
    return [indices[round(i * step)] for i in range(limit)]


def build_track(series: dict, lap: dict, sections: Sequence[Section] | None = None) -> CourseTrack | None:
    """The lap's outline as per-section polylines in local metres (equirectangular projection around
    the lap centroid, north up), ~TRACK_POINTS points in all; None without usable GPS. `sections`
    (course features) name and type each polyline."""
    lat, lng = series.get("lat") or [], series.get("lng") or []
    idx, edges, t_s = lap["idx"], lap["edges"], series["t_s"]
    n = len(edges) - 1
    fixes = [i for i in idx if i < len(lat) and i < len(lng) and lat[i] is not None and lng[i] is not None]
    if len(fixes) < n + 1:
        return None
    lat0 = sum(lat[i] for i in fixes) / len(fixes)
    lng0 = sum(lng[i] for i in fixes) / len(fixes)
    xys = dict(zip(fixes, project_xy(lat, lng, fixes, lat0, lng0)))

    def xy(i: int) -> tuple[float, float]:
        return round(xys[i][0], 1), round(xys[i][1], 1)

    per_sector = max(2, TRACK_POINTS // n)
    track, joined = [], None
    for k in range(n):
        last = k == n - 1
        mine = [i for i in fixes if edges[k] <= t_s[i] and (t_s[i] <= edges[k + 1] if last else t_s[i] < edges[k + 1])]
        if not mine:
            return None
        points = [xy(i) for i in _evenly(mine, per_sector)]
        if joined is not None:  # start where the previous sector ended so the outline is continuous
            points = [joined, *points[1:]] if len(points) > 1 else [joined, points[0]]
        joined = points[-1]
        feature = sections[k] if sections else None
        track.append(TrackSector(sector=k + 1, points=points, label=points[len(points) // 2],
                                 kind=feature.kind if feature else None, name=feature.label if feature else None))
    return CourseTrack(sectors=track)


def _slope(values: list[float]) -> float | None:
    n = len(values)
    if n < 2:
        return None
    mx, my = (n - 1) / 2, sum(values) / n
    den = sum((i - mx) ** 2 for i in range(n))
    return round(sum((i - mx) * (v - my) for i, v in enumerate(values)) / den, 2)


def _pct(new: float | None, old: float | None) -> float | None:
    return round((new - old) / old * 100, 1) if new is not None and old else None


def _mean(vals: list[float]) -> float | None:
    return round(sum(vals) / len(vals), 2) if vals else None


def _fix_indices(series: dict, idx: range) -> list[int]:
    lat, lng = series.get("lat") or [], series.get("lng") or []
    return [i for i in idx if i < len(lat) and i < len(lng) and lat[i] is not None and lng[i] is not None]


def _time_at_index(times: Sequence[float], b: float) -> float:
    """The time at fractional sample index `b`."""
    lo = min(int(b), len(times) - 1)
    if lo >= len(times) - 1:
        return times[-1]
    return times[lo] + (times[lo + 1] - times[lo]) * (b - lo)


def _with_parts(series: dict, edges: list[float], parts: Sequence[int]) -> list[float]:
    """`edges` with every section that is split into n parts cut at n-1 more times, equal-DISTANCE on
    this lap's own odometer between the section's (position-aligned) edges. Cutting by the odometer,
    not by track position, keeps a long section that runs close to itself from mis-aligning."""
    t_s, dist = series["t_s"], series["dist_m"]
    out = [edges[0]]
    for k, n in enumerate(parts):
        a, b = edges[k], edges[k + 1]
        if n > 1:
            idx = window_indices(t_s, a - 1.0, b + 1.0)
            pts = [(t_s[i], dist[i]) for i in idx if dist[i] is not None]
            da, db = _value_at([t for t, _ in pts], [d for _, d in pts], a), _value_at([t for t, _ in pts], [d for _, d in pts], b)
            if pts and da is not None and db is not None:
                d_run = [max(d, pts[0][1]) for _, d in pts]
                for i in range(1, len(d_run)):
                    d_run[i] = max(d_run[i], d_run[i - 1])
                out.extend(min(max(_t_at(d_run, [t for t, _ in pts], da + (db - da) * j / n), a), b) for j in range(1, n))
            else:
                out.extend(a + (b - a) * j / n for j in range(1, n))
        out.append(b)
    return out


def _feature_edges(
    series: dict, cut: list[tuple[int, dict]], best_i: int, splits: Mapping[str, int] | None = None
) -> tuple[list[Section], list[list[float]]] | None:
    """Course-feature sections found on the best lap and every lap's boundary times through them
    (same first/last edge as the equal-distance cut, so lap times do not change), or None when the
    track has no usable GPS, no features, or some lap does not follow the best lap's line. `splits`
    cuts the named sections into equal-distance parts (`course_features.split_sections`).

    The reference (best) lap's boundaries are read straight off its own sample times, so its section
    times are exact whole seconds on a 1 Hz recording; every other lap's are interpolated crossings.
    That lap has no alignment jitter, which `section_sigmas` allows for by leaving it out."""
    best = cut[best_i][1]
    fixes = _fix_indices(series, best["idx"])
    if len(fixes) < 2 * MIN_SECTIONS:
        return None
    lat, lng, t_s = series["lat"], series["lng"], series["t_s"]
    lat0 = sum(lat[i] for i in fixes) / len(fixes)
    lng0 = sum(lng[i] for i in fixes) / len(fixes)
    ref_xy = project_xy(lat, lng, fixes, lat0, lng0)
    flow = series.get("flow")
    fix_t = [t_s[i] for i in fixes]
    sections = segment_course(ref_xy, fix_t, [flow[i] for i in fixes] if flow else None)
    if sections is None:
        return None
    bounds = [s.start_i for s in sections] + [sections[-1].end_i]
    parts = [1] * len(sections)
    if splits:
        split = split_sections(sections, cumulative_m(ref_xy), dict(splits))
        parts = [sum(1 for p in split if (p.split_of or p.label) == s.label) for s in sections]
        sections = split
    all_edges = []
    for k, (_, lap) in enumerate(cut):
        if k == best_i:
            mine = [_time_at_index(fix_t, b) for b in bounds]
        else:
            lap_fixes = _fix_indices(series, lap["idx"])
            mine = align_edges(ref_xy, bounds, project_xy(lat, lng, lap_fixes, lat0, lng0), [t_s[i] for i in lap_fixes])
            if mine is None:
                return None
        mine[0], mine[-1] = lap["edges"][0], lap["edges"][-1]  # the lap's own span, as for the even cut
        mine = [max(e, mine[j - 1]) if j else e for j, e in enumerate(mine)]
        all_edges.append(_with_parts(series, mine, parts))
    return sections, all_edges


def _section_row(k: int, cut: list[tuple[int, dict]], section: Section | None, sigma_s: float) -> SectorLoss:
    times = [s["times"][k] for _, s in cut]
    fastest = min(range(len(cut)), key=lambda i: times[i])
    ref = cut[fastest][1]
    losses = [t - times[fastest] for t in times]
    dflow = [s["flows"][k] - ref["flows"][k] for i, (_, s) in enumerate(cut)
             if i != fastest and s["flows"][k] is not None and ref["flows"][k] is not None]
    flow_by_lap = [s["flows"][k] for _, s in cut]
    flows = [f for f in flow_by_lap if f is not None]
    grits = [s["grits"][k] for _, s in cut if s["grits"][k] is not None]
    mean_loss = sum(losses) / len(losses)
    floor = loss_noise_floor(sigma_s, len(cut))
    row = SectorLoss(
        sector=k + 1, best_time_s=times[fastest], mean_loss_s=round(mean_loss, 2),
        total_loss_s=round(sum(losses), 2), spread_s=round(max(times) - times[fastest], 2),
        avg_flow=_mean(flows), flow_vs_best=_mean(dflow), avg_grit=_mean(grits),
        sigma_s=round(sigma_s, 2), noise_floor_s=round(floor, 2),
        loss_significant=mean_loss > floor and 2 * sum(1 for x in losses if x > sigma_s) >= len(cut),
    )
    alts = [s["alts"][k] for _, s in cut if s["alts"][k] is not None]
    row.terrain = terrain_of(sum(alts) / len(alts)) if alts else None
    row.passes = [
        SectorPass(lap=n, time_s=s["times"][k], avg_power_w=s["powers"][k], avg_flow=round(s["flows"][k], 2) if s["flows"][k] is not None else None)
        for n, s in cut
    ]
    if section is None:
        return row
    passes = [s["passes"][k] for _, s in cut]
    row.kind, row.label, row.length_m, row.split_of = section.kind, section.label, section.length_m, section.split_of
    row.avg_speed_mps = _mean([s["speeds"][k] for _, s in cut if s["speeds"][k] is not None])
    row.avg_power_w = _mean([s["powers"][k] for _, s in cut if s["powers"][k] is not None])
    row.entry_speed_mps, row.min_speed_mps, row.exit_speed_mps = (
        _mean([p[j] for p in passes if p[j] is not None]) for j in range(3))
    row.flow_by_lap = flow_by_lap
    row.flow_slope_per_lap = _slope(flows) if len(flows) == len(cut) else None
    row.efficiency_applies = efficiency_applies(section.kind, row.terrain or "flat", sum(times) / len(times))
    if row.efficiency_applies:
        extras = pass_extras([(p.time_s, p.avg_power_w) for p in row.passes], sigma_s)
        for p, extra in zip(row.passes, extras):
            p.extra_w = extra
        present = [e for e in extras if e is not None]
        row.mean_extra_w = round(sum(present) / len(present), 1) if present else None
    return row


def _applied_splits(sections: Sequence[Section] | None) -> dict[str, int]:
    out: dict[str, int] = {}
    for s in sections or []:
        if s.split_of:
            out[s.split_of] = out.get(s.split_of, 0) + 1
    return out


def build_course_sectors(
    laps: Sequence[CanonicalLap], series: dict | None, section_splits: Mapping[str, int] | None = None
) -> CourseSectors | None:
    """The section comparison over the canonical laps that are `comparable` (`canonical_laps`), or
    None unless 2..MAX_LAPS of them can be cut by distance.
    With GPS the best lap is split into straights and corner sequences (`course_features`) and every
    lap is read through those sections by position; otherwise (or if that fails) into SECTOR_COUNT
    equal-distance sectors. `section_splits` (label -> 2..4 parts) cuts course sections further, only
    on the course-feature path. Each lap's time is the canonical lap's duration."""
    if not series or not series.get("t_s") or not has_channel(series, "dist_m"):
        return None
    group = [lap for lap in laps if lap.comparable]
    if not 2 <= len(group) <= MAX_LAPS:
        return None
    cut = []
    for lap in group:
        idx = window_indices(series["t_s"], lap.start_s, lap.end_s)
        edges = _even_edges(series, idx, (lap.start_s, lap.end_s))
        if edges is None:
            return None
        cut.append((lap.n, _cut(series, idx, edges)))
    best_i = min(range(len(cut)), key=lambda i: cut[i][1]["time_s"])
    featured = _feature_edges(series, cut, best_i, section_splits)
    sections = None
    if featured:
        sections, all_edges = featured
        cut = [(n, _cut(series, lap["idx"], edges)) for (n, lap), edges in zip(cut, all_edges)]
    best = cut[best_i][1]
    sector_laps = [
        SectorLap(lap=n, time_s=s["time_s"], avg_power_w=s["power"], avg_flow=s["flow"], grit=s["grit"],
                  time_vs_best_s=round(s["time_s"] - best["time_s"], 1), sector_times_s=s["times"])
        for n, s in cut
    ]
    count = len(best["times"])
    noise: SectionNoise = section_sigmas([s["times"] for _, s in cut], skip=best_i if featured else None,
                                         chain=[cut[i + 1][0] == cut[i][0] + 1 for i in range(len(cut) - 1)])
    rows = [_section_row(k, cut, sections[k] if sections else None, noise.section_s[k]) for k in range(count)]
    ideal = round(sum(r.best_time_s for r in rows), 1)
    ranked = sorted((r for r in rows if r.loss_significant and r.total_loss_s > 0), key=lambda r: -r.total_loss_s)
    first, last = cut[0][1], cut[-1][1]
    flow_by_lap = [s["flow"] for _, s in cut if s["flow"] is not None]
    fade = LapFade(
        time_change_pct=_pct(last["time_s"], first["time_s"]) or 0.0,
        power_change_pct=_pct(last["power"], first["power"]),
        flow_change=round(last["flow"] - first["flow"], 2) if last["flow"] is not None and first["flow"] is not None else None,
        flow_slope_per_lap=_slope(flow_by_lap) if len(flow_by_lap) == len(cut) else None,
    )
    gap = round(max(best["time_s"] - ideal, 0.0), 1)
    gap_noise = round(sum(r.noise_floor_s or 0.0 for r in rows), 1)
    efficient = {r.label: r.passes for r in rows if r.efficiency_applies and r.label}
    return CourseSectors(
        sector_count=count, best_lap=cut[best_i][0], laps=sector_laps, fade=fade, sectors=rows,
        top_loss_sectors=[r.sector for r in ranked[:TOP_LOSS_SECTORS]],
        ideal_lap_s=ideal, ideal_gap_s=gap,
        track=build_track(series, best, sections),
        free_speed=free_speed(efficient, {r.label: r.sigma_s for r in rows if r.label and r.sigma_s is not None}),
        splits=_applied_splits(sections),
        edge_noise_s=round(noise.pooled_edge_s, 2), ideal_gap_noise_s=gap_noise,
        ideal_gap_beyond_noise_s=round(max(gap - gap_noise, 0.0), 1),
    )
