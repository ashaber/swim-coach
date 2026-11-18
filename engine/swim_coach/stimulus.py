"""Sport-agnostic training stimulus model: what dose of which stimulus a session plans or delivers.

All sport differences live in one `SportProfile` per sport (`profile_for`); nothing here branches
on the sport name. Adding a sport is adding a profile. Sports without a profile (strength,
recovery, cross_train) yield `None` from every public function.

Kind rule (`classify_kind`), over the WORK steps only (roles interval/steady; warm-up, rest and
cool-down never count): each work step has a zone rank 1..5 (Z6+ counts as Z5). A zone is
"meaningful" when it carries at least `KIND_MIN_SHARE` of the ranked work. Two or more of
tempo/threshold/vo2 each at or above `MIXED_MIN_SHARE` give `mixed`; otherwise the highest
meaningful zone sets the kind (Z5 vo2, Z4 threshold, Z3 tempo); all-Z1/Z2 is `endurance`, upgraded
to `long` when total work is at least `max(profile.long_min_work, LONG_FRACTION_OF_RECENT_LONGEST
x recent_longest)`. Races, openers and warm-ups are not stimuli and return `None`.

The dose of a quality kind (tempo/threshold/vo2/mixed) is the work at Z3 and above; the dose of
endurance/long is all work. Library: library/48-stimulus-progression.md (Coach judgment).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Literal

from pydantic import BaseModel

from swim_coach.models import (
    Athlete,
    Session,
    ThresholdRecord,
    Workout,
    WorkoutIntervals,
    WorkoutRepeat,
    WorkoutStep,
    WorkoutStructure,
)
from swim_coach.zones import bike_zone_for_pct, zone_table

StimulusKind = Literal["endurance", "tempo", "threshold", "vo2", "long", "mixed"]
Unit = Literal["s", "m"]

# Coach judgment (library/48-stimulus-progression.md): shares of ranked work that define the kind.
KIND_MIN_SHARE = 0.10
MIXED_MIN_SHARE = 0.30
# Coach judgment (library/48): an endurance session this fraction of the recent longest is "long".
LONG_FRACTION_OF_RECENT_LONGEST = 0.85
BIKE_LONG_MIN_WORK_S = 5400.0  # Coach judgment (library/48): 90 min of work
SWIM_LONG_MIN_WORK_M = 4000.0  # Coach judgment (library/48)
# Coach judgment (library/48): with only a session-level zone, a Z3+ session's work is this share.
ESTIMATED_QUALITY_WORK_FRACTION = 0.5
# Coach judgment (library/48): "short rep for the kind" targets, in the profile's dose unit.
BIKE_REP_TARGET_S: dict[str, float] = {"tempo": 1200.0, "threshold": 600.0, "vo2": 240.0}
SWIM_REP_TARGET_M: dict[str, float] = {"tempo": 400.0, "threshold": 200.0, "vo2": 100.0}

# Coach judgment (library/48): the smallest quality dose that counts as a stimulus, per kind. Below it a
# workout is read as endurance on its whole aerobic time instead of as a (tiny) quality record.
BIKE_MIN_DOSE_S: dict[str, float] = {"tempo": 600.0, "threshold": 480.0, "vo2": 180.0}
SWIM_MIN_DOSE_M: dict[str, float] = {"tempo": 400.0, "threshold": 300.0, "vo2": 200.0}
# Coach judgment (library/48): practical units suggested doses are rounded to, per profile.
BIKE_WORK_ROUND_S, BIKE_REP_ROUND_S = 30.0, 15.0
SWIM_WORK_ROUND_M, SWIM_REP_ROUND_M = 50.0, 25.0
ENDURANCE_KINDS = frozenset({"endurance", "long"})

QUALITY_KINDS = frozenset({"tempo", "threshold", "vo2", "mixed"})
NON_STIMULUS_KINDS = frozenset({"race", "opener", "warmup"})
KIND_RANK: dict[str, int] = {"tempo": 3, "threshold": 4, "vo2": 5}
WORK_ROLES = frozenset({"interval", "steady"})
REST_ROLES = frozenset({"rest", "recovery"})
YARD_M = 0.9144
MAX_REP_DETAIL = 200  # more work reps than this keep no per-rep detail


class StimulusDose(BaseModel):
    """How much of one stimulus kind. `confidence` is "structured" when the numbers come from a
    structured plan or measured analytics, "estimated" when inferred from session totals."""

    sport: str
    kind: StimulusKind
    work_s: float | None = None
    work_m: float | None = None
    rep_count: int | None = None
    longest_rep_s: float | None = None
    longest_rep_m: float | None = None
    work_rest_ratio: float | None = None
    confidence: Literal["structured", "estimated"]
    # Executed quality work only: every work rep's size (the profile's unit) and the rest in seconds
    # between consecutive reps (one fewer). Present only when every rep of the workout is in the dose.
    rep_sizes: list[float] | None = None
    rest_gaps_s: list[float] | None = None

    def work_in(self, unit: Unit) -> float | None:
        return self.work_s if unit == "s" else self.work_m

    def longest_rep_in(self, unit: Unit) -> float | None:
        return self.longest_rep_s if unit == "s" else self.longest_rep_m

    def fraction_of(self, other: "StimulusDose", unit: Unit) -> float | None:
        """This dose's work as a fraction of `other`'s, None when either is unknown or zero."""
        mine, theirs = self.work_in(unit), other.work_in(unit)
        if mine is None or not theirs:
            return None
        return mine / theirs


class ExecutedStimulus(BaseModel):
    """The dose actually done plus how well. `completion_pct` is None when unplanned."""

    dose: StimulusDose
    completion_pct: float | None = None
    in_band_pct: float | None = None
    fade_pct: float | None = None
    rpe: int | None = None
    planned: bool
    planned_kind: StimulusKind | None = None
    substituted: bool = False  # delivered a different kind than the session planned


@dataclass(frozen=True)
class Leaf:
    """One step of a structure with its zone rank and the product of enclosing repeat counts."""

    rank: int | None
    duration_s: float | None
    distance_m: float | None
    reps: int
    role: str


@dataclass
class ExecutedRead:
    """What a profile read from an executed workout, before the kind is resolved."""

    rank_weights: list[tuple[int | None, float]]
    work_s: float | None = None
    work_m: float | None = None
    rep_count: int | None = None
    longest_rep_s: float | None = None
    longest_rep_m: float | None = None
    work_rest_ratio: float | None = None
    in_band_pct: float | None = None
    fade_pct: float | None = None
    confidence: Literal["structured", "estimated"] = "structured"
    reps: list[tuple[int | None, float | None, float | None]] = field(default_factory=list)  # (rank, s, m)
    matches_plan: bool = False  # the analyzer located the planned reps, so the kind is the planned kind
    total_s: float | None = None  # whole aerobic extent (moving time / total swum), for endurance kinds
    total_m: float | None = None
    rep_sizes: list[float] | None = None  # per work rep, in the profile's unit
    rest_gaps_s: list[float] | None = None  # rest seconds between consecutive work reps


# --- zone ranks and the shared leaf walker -------------------------------------------------


def zone_rank_of(zone: object) -> int | None:
    """Rank 1..7 of a "Z<n>" literal, None for anything else."""
    text = str(zone or "").upper()
    return int(text[1:]) if len(text) == 2 and text[0] == "Z" and text[1].isdigit() else None


def pace_zone_rank(pace_s_per_100m: float, css: float) -> int:
    """Zone rank 1..5 for a swim pace; the gaps between the CSS table's zones split at midpoints."""
    t = zone_table(css)
    edges = [
        (t["Z5"]["pace_hi_s"] + t["Z4"]["pace_lo_s"]) / 2,
        (t["Z4"]["pace_hi_s"] + t["Z3"]["pace_lo_s"]) / 2,
        (t["Z3"]["pace_hi_s"] + t["Z2"]["pace_lo_s"]) / 2,
        (t["Z2"]["pace_hi_s"] + t["Z1"]["pace_lo_s"]) / 2,
    ]
    for rank, edge in zip((5, 4, 3, 2), edges):
        if pace_s_per_100m < edge:
            return rank
    return 1


def zone_pace_s_per_100m(rank: int, css: float) -> float | None:
    """Representative pace of a swim zone: mean of its resolved bounds (one bound for Z1/Z5)."""
    zone = zone_table(css).get(f"Z{rank}")
    if zone is None:
        return None
    bounds = [b for b in (zone["pace_lo_s"], zone["pace_hi_s"]) if b is not None]
    return sum(bounds) / len(bounds)


def zone_rank(
    step: WorkoutStep, *, ftp_watts: float | None = None, css_pace_s_per_100m: float | None = None
) -> int | None:
    """Zone rank of a step's target: a zone literal, `power_w` against FTP, or `percent_css` /
    swim `absolute` pace against CSS. None when the target cannot be placed."""
    target = step.target
    if target is None:
        return None
    if target.zone:
        return int(target.zone[1:])
    bounds = [b for b in (target.low, target.high) if b is not None]
    if not bounds:
        return None
    mid = sum(bounds) / len(bounds)
    if target.basis == "power_w" and ftp_watts:
        return int(bike_zone_for_pct(mid / ftp_watts * 100)[1:])
    if css_pace_s_per_100m and target.basis == "percent_css":
        return pace_zone_rank(css_pace_s_per_100m * mid / 100, css_pace_s_per_100m)
    if css_pace_s_per_100m and target.basis == "absolute" and step.modality == "swim":
        return pace_zone_rank(mid, css_pace_s_per_100m)
    return None


def walk_leaves(
    structure: WorkoutStructure,
    *,
    ftp_watts: float | None = None,
    css_pace_s_per_100m: float | None = None,
    time_only: bool = False,
) -> list[Leaf]:
    """Every timed (and, unless `time_only`, distance-based) step in order, with repeat products."""
    out: list[Leaf] = []

    def visit(items: list, reps: int) -> None:
        for item in items:
            if isinstance(item, WorkoutRepeat) or getattr(item, "kind", None) == "repeat":
                visit(item.steps, reps * (item.count or 1))
            elif item.duration_value and item.duration_kind in ("time_s", "distance_m"):
                is_time = item.duration_kind == "time_s"
                if not is_time and time_only:
                    continue
                rank = zone_rank(item, ftp_watts=ftp_watts, css_pace_s_per_100m=css_pace_s_per_100m)
                value = float(item.duration_value)
                out.append(Leaf(rank, value if is_time else None, None if is_time else value, reps, item.role))

    visit(structure.items, 1)
    return out


def zone_at_least(zone: object, min_rank: int) -> bool:
    """True when a "Z<n>" literal is at or above `min_rank` (the shared "hard session" test)."""
    rank = zone_rank_of(zone)
    return rank is not None and rank >= min_rank


def intensity_is_hard(session: Session, min_rank: int) -> bool:
    """True when the session's top-level intensity zone is at or above `min_rank`."""
    return zone_at_least(session.intensity.get("zone"), min_rank)


# --- sport profiles -------------------------------------------------------------------------


@dataclass(frozen=True)
class SportProfile:
    """Everything that differs by sport; all stimulus logic reads this, never the sport name."""

    name: str
    sports: frozenset[str]
    unit: Unit
    long_min_work: float
    rep_targets: dict[str, float]
    leaf_work: Callable[[Leaf, Athlete], tuple[float | None, float | None]]
    read_executed: Callable[[Workout, Athlete, StimulusKind | None], ExecutedRead | None]
    min_dose: dict[str, float] = field(default_factory=dict)
    work_round: float = 1.0
    rep_round: float = 1.0
    # The threshold this sport's zones hang on: an `Athlete` field and `ThresholdRecord.metric`.
    anchor_metric: str = ""
    anchor_label: str = ""
    anchor_unit_label: str = ""
    anchor_higher_is_faster: bool = True  # False for a pace, where a smaller number is a higher threshold
    anchor_gain_word: str = "rose"

    def extent(self, duration_min: float, distance_m: float | None) -> float | None:
        """A session's total size in this sport's dose unit."""
        return duration_min * 60.0 if self.unit == "s" else (float(distance_m) if distance_m else None)

    def athlete_anchor(self, athlete: Athlete) -> float | None:
        """The athlete's current threshold for this sport, None when unset."""
        return getattr(athlete, self.anchor_metric, None) if self.anchor_metric else None

    def anchor_gain_pct(self, then: float, now: float) -> float:
        """How much higher the threshold is now, in percent of `then` (negative when it fell). A pace
        threshold is higher when the pace is smaller."""
        change = (now - then) if self.anchor_higher_is_faster else (then - now)
        return change / then * 100.0

    def anchor_on(self, day: date, athlete: Athlete, records: list[ThresholdRecord]) -> tuple[float | None, bool]:
        """(threshold in effect on `day`, known). Known when a record of this sport's metric is dated on
        or before `day`; otherwise the athlete's current value and False."""
        mine = [
            r for r in records
            if r.metric == self.anchor_metric and r.sport in self.sports and r.measured_at <= day
        ]
        if not mine:
            return self.athlete_anchor(athlete), False
        latest = max(mine, key=lambda r: (r.measured_at, str(r.id)))
        return latest.value, True

    def weight(self, leaf: Leaf, athlete: Athlete) -> float:
        seconds, metres = self.leaf_work(leaf, athlete)
        value = seconds if self.unit == "s" else metres
        return (value or 0.0) * leaf.reps


def _bike_leaf_work(leaf: Leaf, athlete: Athlete) -> tuple[float | None, float | None]:
    return leaf.duration_s, None


def _swim_leaf_work(leaf: Leaf, athlete: Athlete) -> tuple[float | None, float | None]:
    css = athlete.css_pace_s_per_100m
    pace = zone_pace_s_per_100m(leaf.rank, css) if css and leaf.rank else None
    if leaf.distance_m is not None:
        return (leaf.distance_m / 100.0 * pace if pace else None), leaf.distance_m
    return leaf.duration_s, (leaf.duration_s * 100.0 / pace if pace and leaf.duration_s else None)


def profile_named(name: str) -> SportProfile | None:
    """The profile called `name` (`SportProfile.name`), None when there is none."""
    return next((p for p in PROFILES if p.name == name), None)


def profile_for(sport: str) -> SportProfile | None:
    """The profile owning `sport` (a `Session.sport` / `Workout.sport`), None when unsupported."""
    return next((p for p in PROFILES if sport in p.sports), None)


# --- classification ---------------------------------------------------------------------------


def _share_by_rank(rank_weights: list[tuple[int | None, float]]) -> dict[int, float]:
    ranked = [(min(r, 5), w) for r, w in rank_weights if r is not None and w > 0]
    total = sum(w for _, w in ranked)
    shares: dict[int, float] = {}
    for rank, weight in ranked:
        shares[rank] = shares.get(rank, 0.0) + weight / total
    return shares


def classify_kind(
    rank_weights: list[tuple[int | None, float]],
    total_work: float,
    profile: SportProfile,
    recent_longest: float | None = None,
) -> StimulusKind | None:
    """The stimulus kind per the module-docstring rule; None when no work step has a known zone."""
    shares = _share_by_rank(rank_weights)
    if not shares:
        return None
    quality = [r for r in (3, 4, 5) if shares.get(r, 0.0) >= MIXED_MIN_SHARE]
    if len(quality) >= 2:
        return "mixed"
    for rank, kind in ((5, "vo2"), (4, "threshold"), (3, "tempo")):
        if shares.get(rank, 0.0) >= KIND_MIN_SHARE:
            return kind
    long_floor = max(profile.long_min_work, LONG_FRACTION_OF_RECENT_LONGEST * (recent_longest or 0.0))
    return "long" if total_work >= long_floor else "endurance"


def min_work_rank(kind: StimulusKind) -> int:
    """Lowest zone rank whose work counts toward a kind's dose."""
    return 3 if kind in QUALITY_KINDS else 1


# --- planned dose -----------------------------------------------------------------------------


def _is_stimulus_session(session: Session) -> bool:
    return session.effective_kind not in NON_STIMULUS_KINDS


def _structured_dose(
    session: Session, athlete: Athlete, profile: SportProfile, recent_longest: float | None
) -> StimulusDose | None:
    leaves = walk_leaves(session.structured, ftp_watts=athlete.ftp_watts, css_pace_s_per_100m=athlete.css_pace_s_per_100m)
    work = [leaf for leaf in leaves if leaf.role in WORK_ROLES]
    weights = [(leaf.rank, profile.weight(leaf, athlete)) for leaf in work]
    total = sum(w for r, w in weights if r is not None)
    kind = classify_kind(weights, total, profile, recent_longest)
    if kind is None:
        return None
    counted = [leaf for leaf in work if (leaf.rank or 0) >= min_work_rank(kind) or (leaf.rank is None and kind not in QUALITY_KINDS)]
    return _dose_from_leaves(session.sport, kind, counted, leaves, athlete, profile)


def _dose_from_leaves(
    sport: str, kind: StimulusKind, counted: list[Leaf], all_leaves: list[Leaf], athlete: Athlete, profile: SportProfile
) -> StimulusDose | None:
    if not counted:
        return None
    pairs = [(profile.leaf_work(leaf, athlete), leaf.reps) for leaf in counted]
    work_s = sum((s or 0.0) * reps for (s, _), reps in pairs if s is not None) or None
    work_m = sum((m or 0.0) * reps for (_, m), reps in pairs if m is not None) or None
    rest_s = sum((leaf.duration_s or 0.0) * leaf.reps for leaf in all_leaves if leaf.role in REST_ROLES)
    return StimulusDose(
        sport=sport,
        kind=kind,
        work_s=work_s,
        work_m=work_m,
        rep_count=sum(leaf.reps for leaf in counted),
        longest_rep_s=max((s for (s, _), _ in pairs if s is not None), default=None),
        longest_rep_m=max((m for (_, m), _ in pairs if m is not None), default=None),
        work_rest_ratio=(work_s / rest_s) if work_s and rest_s else None,
        confidence="structured",
    )


def _estimated_dose(
    session: Session, profile: SportProfile, recent_longest: float | None
) -> StimulusDose | None:
    rank = zone_rank_of(session.intensity.get("zone"))
    extent = profile.extent(session.duration_min, session.distance_m)
    if rank is None or extent is None:
        return None
    kind = classify_kind([(rank, extent)], extent, profile, recent_longest)
    fraction = ESTIMATED_QUALITY_WORK_FRACTION if rank >= 3 else 1.0
    return StimulusDose(
        sport=session.sport,
        kind=kind,
        work_s=session.duration_min * 60.0 * fraction,
        work_m=float(session.distance_m) * fraction if session.distance_m else None,
        confidence="estimated",
    )


def planned_dose(
    session: Session, athlete: Athlete, *, recent_longest: float | None = None
) -> StimulusDose | None:
    """The dose a session plans: from `session.structured` when it yields ranked work ("structured"),
    else estimated from `intensity["zone"]` and the session totals ("estimated"). None for races,
    openers, warm-ups, unsupported sports, or a session with no zone information."""
    profile = profile_for(session.sport)
    if profile is None or not _is_stimulus_session(session):
        return None
    if session.structured is not None:
        dose = _structured_dose(session, athlete, profile, recent_longest)
        if dose is not None:
            return dose
    return _estimated_dose(session, profile, recent_longest)


# --- executed dose ----------------------------------------------------------------------------


def _bike_effort_rank(effort, intervals: WorkoutIntervals, ftp: float | None) -> int | None:
    if ftp and effort.avg_w:
        return int(bike_zone_for_pct(effort.avg_w / ftp * 100)[1:])
    if ftp and effort.target_w:
        return int(bike_zone_for_pct(effort.target_w / ftp * 100)[1:])
    return zone_rank_of(intervals.target_zone)


def _in_band_pct(intervals: WorkoutIntervals) -> float | None:
    """The analyzer's reps-in-band share; unknown (None) when it reports 0 but resolved neither a
    target zone nor a power band, since 0 then means "no band to measure against", not "all out"."""
    pct = intervals.reps_in_band_pct
    if pct == 0.0 and intervals.target_zone is None and intervals.target_band_w is None:
        return None
    return pct


def _bike_intervals_read(intervals: WorkoutIntervals, athlete: Athlete) -> ExecutedRead:
    efforts = intervals.efforts
    ranks = [(_bike_effort_rank(e, intervals, athlete.ftp_watts), e.duration_s) for e in efforts]
    gaps = [
        nxt.start_s - (cur.start_s + cur.duration_s)
        for cur, nxt in zip(efforts, efforts[1:])
        if nxt.start_s > cur.start_s + cur.duration_s
    ]
    work = sum(e.duration_s for e in efforts)
    return ExecutedRead(
        rank_weights=ranks,
        work_s=work,
        rep_count=intervals.reps_completed or len(efforts),
        longest_rep_s=max(e.duration_s for e in efforts),
        work_rest_ratio=(work / sum(gaps)) if gaps and sum(gaps) > 0 else None,
        in_band_pct=_in_band_pct(intervals),
        fade_pct=intervals.fade_across_reps_pct,
        reps=[(rank, seconds, None) for rank, seconds in ranks],
        matches_plan=intervals.matched_to_prescription,
        rep_sizes=[e.duration_s for e in efforts] if len(efforts) <= MAX_REP_DETAIL else None,
        rest_gaps_s=[max(0.0, nxt.start_s - (cur.start_s + cur.duration_s)) for cur, nxt in zip(efforts, efforts[1:])]
        if len(efforts) <= MAX_REP_DETAIL else None,
    )


def _bike_free_ride_read(zones) -> ExecutedRead | None:
    ranked = [(zone_rank_of(z.zone), float(z.seconds)) for z in zones if (zone_rank_of(z.zone) or 0) >= 2]
    total = sum(w for _, w in ranked)
    return ExecutedRead(rank_weights=ranked, work_s=total) if total > 0 else None


def _bike_whole_read(workout: Workout, athlete: Athlete) -> ExecutedRead | None:
    a = workout.analytics
    power = (a.normalized_power_w or a.avg_power_w) if a else None
    if not (power and athlete.ftp_watts):
        return None
    rank = int(bike_zone_for_pct(power / athlete.ftp_watts * 100)[1:])
    seconds = workout.duration_min * 60.0
    return ExecutedRead(rank_weights=[(rank, seconds)], work_s=seconds, confidence="estimated")


def _bike_moving_s(workout: Workout) -> float:
    """Moving time of the ride: the free-ride read's `moving_s` when present, else the workout duration."""
    a = workout.analytics
    moving = a.free_ride.moving_s if a is not None and a.free_ride is not None else None
    return float(moving) if moving else workout.duration_min * 60.0


def _bike_read(workout: Workout, athlete: Athlete, planned_kind: StimulusKind | None) -> ExecutedRead | None:
    a = workout.analytics
    read: ExecutedRead | None = None
    if a is not None and a.intervals is not None and a.intervals.efforts:
        read = _bike_intervals_read(a.intervals, athlete)
    elif a is not None and a.free_ride is not None and a.free_ride.power_zones:
        read = _bike_free_ride_read(a.free_ride.power_zones)
    read = read or _bike_whole_read(workout, athlete)
    if read is not None:
        read.total_s = _bike_moving_s(workout)
    return read


def _swim_reps_m(workout: Workout, athlete: Athlete) -> list[tuple[float, float, float | None, float | None]]:
    """(distance_m, swim_time_s, pace_s_per_100m, rest_after_s) for every recorded rep."""
    a = workout.analytics
    unit = (a.pool_unit if a else None) or workout.pool_unit
    factor = YARD_M if unit == "yd" else 1.0
    reps = [rep for s in (a.swim_sets if a else []) for rep in s.reps]
    return [(r.distance * factor, r.swim_time_s, r.pace_s_per_100 / factor, r.rest_after_s) for r in reps]


def _swim_fade_pct(paces: list[float]) -> float | None:
    if len(paces) < 3:
        return None
    third = len(paces) // 3
    first, last = sum(paces[:third]) / third, sum(paces[-third:]) / third
    return (last - first) / first * 100.0 if first else None


def _swim_rest_gaps(reps: list[tuple[float, float, float | None, float | None]]) -> list[float] | None:
    """Rest seconds after every rep but the last; None when any is unrecorded."""
    gaps = [r for _, _, _, r in reps[:-1]]
    return None if any(g is None for g in gaps) else [float(g) for g in gaps]


def _swim_sets_read(workout: Workout, athlete: Athlete, planned_kind: StimulusKind | None) -> ExecutedRead | None:
    reps = _swim_reps_m(workout, athlete)
    css = athlete.css_pace_s_per_100m
    if not reps:
        return None
    ranks = [pace_zone_rank(p, css) if css else None for _, _, p, _ in reps]
    quality = [i for i, r in enumerate(ranks) if r is not None and r >= 3]
    keep = quality or list(range(len(reps)))
    work = [reps[i] for i in keep]
    work_s, work_m = sum(t for _, t, _, _ in work), sum(d for d, _, _, _ in work)
    rests = [r for _, _, _, r in work[:-1] if r is not None]
    target = KIND_RANK.get(planned_kind or "")
    in_band = (
        100.0 * sum(1 for i in keep if (ranks[i] or 0) >= target) / len(keep) if target and css else None
    )
    total_m = float(workout.distance_m) if workout.distance_m else sum(d for d, _, _, _ in reps)
    return ExecutedRead(
        rank_weights=[(ranks[i], reps[i][0]) for i in keep],
        work_s=work_s,
        work_m=work_m,
        rep_count=len(work),
        longest_rep_s=max(t for _, t, _, _ in work),
        longest_rep_m=max(d for d, _, _, _ in work),
        work_rest_ratio=(work_s / sum(rests)) if rests and sum(rests) > 0 else None,
        in_band_pct=in_band,
        fade_pct=_swim_fade_pct([p for _, _, p, _ in work]),
        reps=[(ranks[i], reps[i][1], reps[i][0]) for i in keep],
        rep_sizes=[reps[i][0] for i in keep] if len(keep) == len(reps) else None,
        rest_gaps_s=_swim_rest_gaps(reps) if len(keep) == len(reps) else None,
        total_s=workout.duration_min * 60.0,
        total_m=total_m,
    )


def _swim_whole_read(workout: Workout, athlete: Athlete) -> ExecutedRead | None:
    css = athlete.css_pace_s_per_100m
    if not css or not workout.distance_m:
        return None
    a = workout.analytics
    pace = (a.moving_pace_s_per_100m if a else None) or workout.duration_min * 60.0 / workout.distance_m * 100.0
    return ExecutedRead(
        rank_weights=[(pace_zone_rank(pace, css), float(workout.distance_m))],
        work_s=workout.duration_min * 60.0,
        work_m=float(workout.distance_m),
        confidence="estimated",
        total_s=workout.duration_min * 60.0,
        total_m=float(workout.distance_m),
    )


def _swim_read(workout: Workout, athlete: Athlete, planned_kind: StimulusKind | None) -> ExecutedRead | None:
    return _swim_sets_read(workout, athlete, planned_kind) or _swim_whole_read(workout, athlete)


PROFILES: tuple[SportProfile, ...] = (
    SportProfile(
        "bike", frozenset({"bike"}), "s", BIKE_LONG_MIN_WORK_S, BIKE_REP_TARGET_S, _bike_leaf_work, _bike_read,
        min_dose=BIKE_MIN_DOSE_S, work_round=BIKE_WORK_ROUND_S, rep_round=BIKE_REP_ROUND_S,
        anchor_metric="ftp_watts", anchor_label="FTP", anchor_unit_label="W",
    ),
    SportProfile(
        "swim", frozenset({"swim_pool", "swim_ow"}), "m", SWIM_LONG_MIN_WORK_M, SWIM_REP_TARGET_M, _swim_leaf_work,
        _swim_read, min_dose=SWIM_MIN_DOSE_M, work_round=SWIM_WORK_ROUND_M, rep_round=SWIM_REP_ROUND_M,
        anchor_metric="css_pace_s_per_100m", anchor_label="CSS", anchor_unit_label="s/100 m",
        anchor_higher_is_faster=False, anchor_gain_word="improved",
    ),
)


def _set_unit_work(read: ExecutedRead, profile: SportProfile, value: float) -> None:
    if profile.unit == "s":
        read.work_s = value
    else:
        read.work_m = value


def _narrow_to_quality(read: ExecutedRead, kind: StimulusKind, profile: SportProfile) -> None:
    """For a quality kind the dose is the work at Z3+: total work, rep count and longest rep all
    follow the same Z3+ filter, so the longest rep can never exceed the work."""
    min_rank = min_work_rank(kind)
    if read.reps:
        hard = [r for r in read.reps if (r[0] or 0) >= min_rank]
        if not hard:
            return
        if len(hard) < len(read.reps):
            read.rep_sizes = read.rest_gaps_s = None
        read.work_s = sum(s for _, s, _ in hard if s is not None) or None
        read.work_m = sum(m for _, _, m in hard if m is not None) or None
        read.rep_count = len(hard)
        read.longest_rep_s = max((s for _, s, _ in hard if s is not None), default=None)
        read.longest_rep_m = max((m for _, _, m in hard if m is not None), default=None)
        return
    hard_work = sum(w for r, w in read.rank_weights if r is not None and r >= min_rank)
    if hard_work > 0:
        _set_unit_work(read, profile, hard_work)


def _aerobic_kind(read: ExecutedRead, profile: SportProfile, recent_longest: float | None) -> StimulusKind | None:
    """Re-read the workout as endurance or long on its whole aerobic extent (moving time, total swum
    distance); detected efforts and rep subsets are irrelevant to that dose. None without an extent."""
    extent = read.total_s if profile.unit == "s" else read.total_m
    if not extent:
        return None
    read.work_s, read.work_m = read.total_s, read.total_m
    read.rep_count = read.longest_rep_s = read.longest_rep_m = read.work_rest_ratio = None
    return classify_kind([(1, extent)], extent, profile, recent_longest)


def _quality_floor(kind: StimulusKind, profile: SportProfile) -> float | None:
    if kind == "mixed":
        return max(profile.min_dose.values(), default=None)
    return profile.min_dose.get(kind)


def _resolve_kind(
    read: ExecutedRead, kind: StimulusKind, planned: StimulusDose | None, profile: SportProfile,
    recent_longest: float | None,
) -> StimulusKind | None:
    """The kind this workout delivered. A workout whose reps the analyzer matched to the prescription
    is the planned kind. A quality dose under the profile's floor is not a stimulus: the workout is
    read as endurance instead, so one workout yields one primary record."""
    if read.matches_plan and planned is not None:
        kind = planned.kind
    elif kind in QUALITY_KINDS:
        _narrow_to_quality(read, kind, profile)
        floor = _quality_floor(kind, profile)
        work = read.work_s if profile.unit == "s" else read.work_m
        if floor is not None and (work or 0.0) < floor:
            return _aerobic_kind(read, profile, recent_longest)
        return kind
    if kind in ENDURANCE_KINDS:
        return _aerobic_kind(read, profile, recent_longest) or kind
    return kind


def _same_family(a: StimulusKind | None, b: StimulusKind) -> bool:
    return a == b or (a in ENDURANCE_KINDS and b in ENDURANCE_KINDS)


def _completion_pct(dose: StimulusDose, planned: StimulusDose | None, unit: Unit, *, substituted: bool) -> float | None:
    """Work done as a percent of the planned work; None for a substituted kind (nothing to compare)
    or an estimated execution (its number is a guess, so a ratio against the plan is meaningless)."""
    if substituted or dose.confidence == "estimated":
        return None
    fraction = dose.fraction_of(planned, unit) if planned else None
    return None if fraction is None else fraction * 100.0


def _is_non_stimulus(workout: Workout, session: Session | None) -> bool:
    return workout.effective_kind in NON_STIMULUS_KINDS or (
        session is not None and session.effective_kind in NON_STIMULUS_KINDS
    )


def executed_dose(
    workout: Workout,
    athlete: Athlete,
    session: Session | None = None,
    *,
    recent_longest: float | None = None,
) -> ExecutedStimulus | None:
    """The dose a workout delivered plus quality (completion vs the matched session, in-band and
    fade from the analyzer, RPE). The kind comes from the executed zones (the planned kind when the
    analyzer matched the prescription), falling back to the planned kind. When it differs from the
    planned kind the result is `substituted`: no completion or in-band, `planned_kind` recorded.
    None when the workout or its session is a race / opener / warm-up, for unsupported sports, or
    with no readable zone or session information. Bike reads intervals, then free-ride zone time,
    then average power; swim reads swim sets, then whole-workout pace."""
    profile = profile_for(workout.sport)
    if profile is None or _is_non_stimulus(workout, session):
        return None
    planned = planned_dose(session, athlete, recent_longest=recent_longest) if session else None
    read = profile.read_executed(workout, athlete, planned.kind if planned else None)
    if read is None:
        return None
    total = sum(w for r, w in read.rank_weights if r is not None)
    kind = classify_kind(read.rank_weights, total, profile, recent_longest) or (planned.kind if planned else None)
    kind = _resolve_kind(read, kind, planned, profile, recent_longest) if kind else None
    if kind is None:
        return None
    dose = StimulusDose(
        sport=workout.sport,
        kind=kind,
        work_s=read.work_s,
        work_m=read.work_m,
        rep_count=read.rep_count,
        longest_rep_s=read.longest_rep_s,
        longest_rep_m=read.longest_rep_m,
        work_rest_ratio=read.work_rest_ratio,
        confidence=read.confidence,
        rep_sizes=read.rep_sizes if kind in QUALITY_KINDS else None,
        rest_gaps_s=read.rest_gaps_s if kind in QUALITY_KINDS else None,
    )
    planned_kind = planned.kind if planned else None
    substituted = planned_kind is not None and not _same_family(planned_kind, kind)
    return ExecutedStimulus(
        dose=dose,
        completion_pct=_completion_pct(dose, planned, profile.unit, substituted=substituted),
        in_band_pct=None if substituted else read.in_band_pct,
        fade_pct=read.fade_pct,
        rpe=workout.rpe,
        planned=session is not None,
        planned_kind=planned_kind,
        substituted=substituted,
    )
