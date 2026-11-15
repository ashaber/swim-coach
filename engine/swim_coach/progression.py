"""Progression ledger: what stimulus the athlete completed, how well, how they recovered, and the
deterministic next-dose read per (sport, kind). Advisory only; nothing here rewrites a plan.

Sport differences live in `stimulus.SportProfile`; nothing here branches on the sport name.
Every rule and number is Coach judgment, documented with a validation test in
library/48-stimulus-progression.md.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from swim_coach.adapt import WELLNESS_RED_THRESHOLD
from swim_coach.execution_score import FADE_FREE_PCT, INTENSITY_MATCH_MIN_IN_BAND_PCT
from swim_coach.formatting import format_amount
from swim_coach.load import (
    session_target_load_au,
    wellness_baseline_deviation,
    wellness_composite,
)
from swim_coach.models import Athlete, Session, WeekPlan, Wellness, Workout
from swim_coach.plan import WEEKLY_VOLUME_RAMP_CAP
from swim_coach.quality import match_workout_to_session
from swim_coach.stimulus import (
    ExecutedStimulus,
    SportProfile,
    StimulusDose,
    StimulusKind,
    Unit,
    executed_dose,
    planned_dose,
    profile_for,
)

# Coach judgment (library/48-stimulus-progression.md)
PROGRESSION_STEP_FRACTION = 0.10  # one progression step, as a fraction of the reference dose
REPEAT_TOLERANCE_FRACTION = 0.05  # how far below the reference a "repeat" may sit
PROGRESSION_STALE_DAYS = 28  # a kind untrained this long is rebuilt, not progressed
COMPLETION_PROGRESS_MIN_PCT = 90.0  # executed / planned work needed to progress
COMPLETION_REDUCE_BELOW_PCT = 75.0  # below this the dose was too big
IN_BAND_REDUCE_BELOW_PCT = 50.0  # reps in band below this: the dose was too big
RPE_MARGINAL_MIN = 9  # session RPE at or above this blocks progress
CONSECUTIVE_REPEATS_TO_REDUCE = 2
RECOVERY_WINDOW_DAYS = 2  # wellness rows on the 1-2 days after the session
RECOVERY_DEVIATION_CONCERNING_PCT = 5.0  # mirrors web/src/plan.js WELLNESS_DEVIATION_CONCERNING_PCT
DUPLICATE_STIMULUS_FRACTION = 0.75  # unplanned work this share of a planned dose already delivered it
HARD_RECOVERY_WINDOW_H = 48.0  # hours a hard session needs after tempo/threshold/vo2/long work
HARD_KINDS = frozenset({"tempo", "threshold", "vo2", "mixed"})
HARD_OR_LONG_KINDS = HARD_KINDS | {"long"}
COMPLETION_SANITY_MAX_PCT = 150.0  # structured completion above this draws a "check the match" reason

Grade = Literal["clean", "marginal", "poor", "unknown"]


class RecoveryResponse(BaseModel):
    """How the athlete came out of a session. Informational: library/17 records no validated
    deviation threshold, so this reuses the project's +/-5% and composite-red conventions.
    Missing wellness is "unknown", never "recovered"."""

    status: Literal["recovered", "strained", "unknown"]
    hrv_pct_deviation: float | None = None
    resting_hr_pct_deviation: float | None = None
    soreness_max: int | None = None
    composite_post: float | None = None
    composite_change: float | None = None
    evidence: list[str] = Field(default_factory=list)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _recovery_breaches(
    hrv: float | None, rhr: float | None, composite: float | None
) -> list[str]:
    breaches: list[str] = []
    if hrv is not None and hrv <= -RECOVERY_DEVIATION_CONCERNING_PCT:
        breaches.append(f"HRV {hrv:+.1f}% vs baseline (at or beyond -{RECOVERY_DEVIATION_CONCERNING_PCT:g}%)")
    if rhr is not None and rhr >= RECOVERY_DEVIATION_CONCERNING_PCT:
        breaches.append(f"resting HR {rhr:+.1f}% vs baseline (at or beyond +{RECOVERY_DEVIATION_CONCERNING_PCT:g}%)")
    if composite is not None and composite <= WELLNESS_RED_THRESHOLD:
        breaches.append(f"wellness composite {composite:.2f} (at or under {WELLNESS_RED_THRESHOLD:g})")
    return breaches


def recovery_response(day: date, wellness: list[Wellness], *, as_of: date) -> RecoveryResponse:
    """Read the wellness rows on the 1-2 days after `day` (never after `as_of`) against the athlete's
    own baseline. "strained" when HRV is at or under -5%, resting HR at or over +5%, or the
    post-session composite is at or under the red threshold; "recovered" when at least one signal
    exists and none breach; "unknown" when no signal exists."""
    end = min(day + timedelta(days=RECOVERY_WINDOW_DAYS), as_of)
    days = (end - day).days
    if days < 1:
        return RecoveryResponse(status="unknown", evidence=["No full day of wellness after the session yet."])
    rows = [w for w in wellness if w.date <= end]
    post = [w for w in rows if day < w.date <= end]
    deviation = wellness_baseline_deviation(rows, end, acute_window_days=days)
    hrv, rhr = deviation["hrv_pct_deviation"], deviation["resting_hr_pct_deviation"]
    post_composites = [c for w in post if (c := wellness_composite(w)) is not None]
    pre_composites = [c for w in rows if day - timedelta(days=6) <= w.date <= day and (c := wellness_composite(w)) is not None]
    composite = _mean(post_composites)
    baseline = _mean(pre_composites)
    soreness = [w.soreness for w in post if w.soreness is not None]
    change = composite - baseline if composite is not None and baseline is not None else None
    breaches = _recovery_breaches(hrv, rhr, composite)
    if hrv is None and rhr is None and composite is None:
        return RecoveryResponse(status="unknown", soreness_max=max(soreness, default=None),
                                evidence=["No HRV, resting HR or wellness composite after the session."])
    return RecoveryResponse(
        status="strained" if breaches else "recovered",
        hrv_pct_deviation=hrv,
        resting_hr_pct_deviation=rhr,
        soreness_max=max(soreness, default=None),
        composite_post=composite,
        composite_change=change,
        evidence=breaches or ["No recovery signal after the session crossed its concern threshold."],
    )


class StimulusRecord(BaseModel):
    """One completed training workout: what was planned, what was done, how recovery went."""

    date: date
    sport: str
    kind: StimulusKind
    planned: bool
    planned_dose: StimulusDose | None = None
    executed: ExecutedStimulus
    recovery: RecoveryResponse
    workout_id: UUID | None = None
    session_id: UUID | None = None

    def has_execution_data(self, unit: Unit) -> bool:
        """True when the dose comes from measured analytics (not session totals) and has work."""
        return self.executed.dose.confidence == "structured" and self.executed.dose.work_in(unit) is not None

    @property
    def planned_kind(self) -> StimulusKind | None:
        return self.executed.planned_kind

    @property
    def substituted(self) -> bool:
        """True when the session planned one kind and the workout delivered another."""
        return self.executed.substituted

    def grade(self) -> Grade:
        """"unknown" for an estimated execution (its numbers are guesses); "poor" when completion <
        75% or in-band < 50%; "clean" when completed (>= 90% of plan, or unplanned or substituted, which
        have no completion), in band at the project's match threshold, fade within the free band, RPE
        under 9 and recovery not strained; otherwise "marginal"."""
        e = self.executed
        if e.dose.confidence == "estimated":
            return "unknown"
        if (e.completion_pct is not None and e.completion_pct < COMPLETION_REDUCE_BELOW_PCT) or (
            e.in_band_pct is not None and e.in_band_pct < IN_BAND_REDUCE_BELOW_PCT
        ):
            return "poor"
        clean = (
            (e.completion_pct is None or e.completion_pct >= COMPLETION_PROGRESS_MIN_PCT)
            and (e.in_band_pct is None or e.in_band_pct >= INTENSITY_MATCH_MIN_IN_BAND_PCT)
            and (e.fade_pct is None or e.fade_pct <= FADE_FREE_PCT)
            and (e.rpe is None or e.rpe < RPE_MARGINAL_MIN)
            and self.recovery.status != "strained"
        )
        return "clean" if clean else "marginal"


def _recent_longest(done: list[Workout], before: Workout, profile: SportProfile) -> float | None:
    prior = [
        profile.extent(w.duration_min, w.distance_m)
        for w in done
        if w.date < before.date and profile_for(w.sport) is profile
    ]
    return max((x for x in prior if x), default=None)


def build_ledger(
    workouts: list[Workout],
    weeks: list[WeekPlan],
    wellness: list[Wellness],
    athlete: Athlete,
    *,
    as_of: date,
    lookback_days: int = 42,
) -> list[StimulusRecord]:
    """One record per completed training workout in the lookback window, oldest first. Workouts are
    matched to planned sessions by `quality.match_workout_to_session` (which honours
    `planned_session_id` first). Races, openers, warm-ups and unsupported sports are skipped."""
    sessions = [s for week in weeks for s in week.sessions]
    start = as_of - timedelta(days=lookback_days)
    window = sorted(
        (w for w in workouts if start <= w.date <= as_of), key=lambda w: (w.date, str(w.started_at or ""), str(w.id))
    )
    records: list[StimulusRecord] = []
    for w in window:
        profile = profile_for(w.sport)
        if profile is None:
            continue
        session = match_workout_to_session(w, sessions, other_workouts=[o for o in window if o is not w])
        longest = _recent_longest(window, w, profile)
        executed = executed_dose(w, athlete, session, recent_longest=longest)
        if executed is None:
            continue
        planned = planned_dose(session, athlete, recent_longest=longest) if session else None
        records.append(
            StimulusRecord(
                date=w.date, sport=w.sport, kind=executed.dose.kind, planned=session is not None,
                planned_dose=planned, executed=executed, recovery=recovery_response(w.date, wellness, as_of=as_of),
                workout_id=w.id, session_id=session.id if session else None,
            )
        )
    return records


Verdict = Literal["progress", "repeat", "reduce", "rebuild", "insufficient_data"]


class ProgressionRead(BaseModel):
    """The next-dose read for one (sport, kind). Ranges are in `unit` (s for bike, m for swim)."""

    sport: str
    kind: StimulusKind
    verdict: Verdict
    unit: Unit
    reasons: list[str]
    last: StimulusRecord | None = None
    reference_dose: StimulusDose | None = None
    suggested_work_range: tuple[float, float] | None = None
    suggested_longest_rep_max: float | None = None
    verdict_reason: str | None = None  # the reason that decided the verdict
    days_since_last: int | None = None
    confidence: Literal["high", "medium", "low"]


def _round_to(value: float, step: float) -> float:
    return round(value / step) * step


def _practical_range(low: float, high: float, profile: SportProfile) -> tuple[float, float]:
    """A work range rounded to the profile's practical unit, never with low above high."""
    low_r, high_r = _round_to(low, profile.work_round), _round_to(high, profile.work_round)
    return (min(low_r, high_r), high_r)


def _practical_rep_cap(raw: float, longest: float, target: float, profile: SportProfile) -> float:
    """A longest-rep cap rounded to the profile's rep unit, at least one unit above the current
    longest rep (a cap that rounds back to the current rep is no progression) and never above `target`."""
    step = profile.rep_round
    cap = _round_to(raw, step)
    if cap <= longest:
        cap = _round_to(longest, step) + step
    return min(cap, target)


def _describe(record: StimulusRecord, unit: Unit) -> str:
    e = record.executed
    parts = [f"did {format_amount(e.dose.work_in(unit), unit)} of {record.kind} on {record.date.isoformat()}"]
    if record.substituted:
        parts.insert(0, f"planned {record.planned_kind}, delivered {record.kind}")
    if e.completion_pct is not None:
        parts.append(f"{e.completion_pct:.0f}% of planned work")
    if e.in_band_pct is not None:
        parts.append(f"{e.in_band_pct:.0f}% of reps in band")
    if e.fade_pct is not None:
        parts.append(f"fade {e.fade_pct:.1f}%")
    if e.rpe is not None:
        parts.append(f"RPE {e.rpe}")
    parts.append(f"recovery {record.recovery.status}")
    return ", ".join(parts)


def _range(base: float, low_factor: float, high_factor: float, profile: SportProfile) -> tuple[float, float]:
    return _practical_range(base * low_factor, base * high_factor, profile)


def _cause(base: ProgressionRead, text: str) -> None:
    """Record the reason that decided the verdict (also the most informative one for a finding)."""
    base.reasons.append(text)
    base.verdict_reason = text


def _confidence(usable: int, recovery: str, stale: bool) -> Literal["high", "medium", "low"]:
    """Starts high; one level off each for a single usable record, unknown recovery, a stale read."""
    score = 2 - (usable < 2) - (recovery == "unknown") - stale
    return "high" if score >= 2 else "medium" if score == 1 else "low"


def _rep_length_is_short(last: StimulusRecord, profile: SportProfile) -> float | None:
    """The kind's longest-rep target when the last longest rep is below it (IDEA 014), else None."""
    target = profile.rep_targets.get(last.kind)
    longest = last.executed.dose.longest_rep_in(profile.unit)
    return target if target is not None and longest is not None and longest < target else None


def _progress_read(
    base: ProgressionRead, last: StimulusRecord, profile: SportProfile, work: float
) -> ProgressionRead:
    target = _rep_length_is_short(last, profile)
    step = PROGRESSION_STEP_FRACTION
    if target is not None:
        longest = last.executed.dose.longest_rep_in(profile.unit)
        base.suggested_work_range = _range(work, 1.0, 1.0, profile)
        base.suggested_longest_rep_max = _practical_rep_cap(longest * (1 + step), longest, target, profile)
        _cause(base,
            f"Longest rep was {format_amount(longest, profile.unit)}, short for {last.kind} (target {format_amount(target, profile.unit)}); "
            f"lengthen reps up to {format_amount(base.suggested_longest_rep_max, profile.unit)} before adding total work."
        )
    else:
        base.suggested_work_range = _range(work, 1.0, 1 + step, profile)
        _cause(base, f"Next dose {format_amount(base.suggested_work_range[0], profile.unit)} to {format_amount(base.suggested_work_range[1], profile.unit)} (+{step:.0%} step).")
    return base


def _decide(
    base: ProgressionRead, usable: list[StimulusRecord], profile: SportProfile, as_of: date
) -> ProgressionRead:
    last, unit = usable[-1], profile.unit
    work = last.executed.dose.work_in(unit)
    clean = next((r for r in reversed(usable) if r.grade() == "clean"), None)
    base.last, base.days_since_last = last, (as_of - last.date).days
    base.reference_dose = clean.executed.dose if clean else None
    step, tol = PROGRESSION_STEP_FRACTION, REPEAT_TOLERANCE_FRACTION
    grades = [r.grade() for r in usable[-CONSECUTIVE_REPEATS_TO_REDUCE:]]
    base.reasons.append(f"Last session {_describe(last, unit)}.")
    completion = last.executed.completion_pct
    if completion is not None and completion > COMPLETION_SANITY_MAX_PCT:
        base.reasons.append(
            f"Completion {completion:.0f}% is over {COMPLETION_SANITY_MAX_PCT:.0f}% of the planned work; check the session match before trusting this dose."
        )
    if base.days_since_last > PROGRESSION_STALE_DAYS:
        ref = (clean.executed.dose.work_in(unit) if clean else None) or work
        base.verdict, base.suggested_work_range = "rebuild", _range(ref * (1 - step), 1 - tol, 1.0, profile)
        _cause(base, f"{base.days_since_last} days since this kind was trained (over {PROGRESSION_STALE_DAYS}); step back {step:.0%} from the last reference dose.")
    elif grades[-1] == "poor" or grades == ["marginal"] * CONSECUTIVE_REPEATS_TO_REDUCE:
        base.verdict, base.suggested_work_range = "reduce", _range(work * (1 - step), 1 - tol, 1.0, profile)
        _cause(base, "Completion or in-band was too low." if grades[-1] == "poor" else f"{CONSECUTIVE_REPEATS_TO_REDUCE} marginal sessions in a row.")
    elif grades[-1] == "marginal":
        base.verdict, base.suggested_work_range = "repeat", _range(work, 1 - tol, 1.0, profile)
        _cause(base, "Completed but marginal on completion, in-band, fade, RPE or recovery; repeat the dose.")
    else:
        base.verdict = "progress"
        _progress_read(base, last, profile, work)
    if last.recovery.status == "unknown":
        base.reasons.append("Recovery is unknown (no wellness after the session), so confidence is lowered.")
    return base


def _read_group(
    sport: str, kind: StimulusKind, records: list[StimulusRecord], profile: SportProfile, as_of: date
) -> ProgressionRead:
    unit = profile.unit
    usable = [r for r in records if r.has_execution_data(unit)]
    base = ProgressionRead(sport=sport, kind=kind, verdict="insufficient_data", unit=unit, reasons=[], confidence="low")
    if not usable:
        base.last = records[-1] if records else None
        base.reasons.append(f"No usable executed {kind} data ({len(records)} estimated-only record(s)): insufficient execution data to read progression.")
        return base
    _decide(base, usable, profile, as_of)
    stale = base.verdict == "rebuild"
    base.confidence = _confidence(len(usable), usable[-1].recovery.status, stale)
    return base


def read_progression(ledger: list[StimulusRecord], *, as_of: date) -> list[ProgressionRead]:
    """One read per (sport profile, kind) present in the ledger, sorted by sport then kind. Records
    for sports without a profile are ignored."""
    groups: dict[tuple[str, StimulusKind], list[StimulusRecord]] = {}
    profiles: dict[str, SportProfile] = {}
    for record in sorted(ledger, key=lambda r: r.date):
        profile = profile_for(record.sport)
        if profile is None:
            continue
        profiles[profile.name] = profile
        groups.setdefault((profile.name, record.kind), []).append(record)
    return [_read_group(s, k, recs, profiles[s], as_of) for (s, k), recs in sorted(groups.items())]


# --- unplanned work: week stimulus review ------------------------------------------------------

ImpactType = Literal["duplicate_stimulus", "hard_too_soon", "load_over_target"]


class SessionStimulus(BaseModel):
    """A planned session's stimulus and, when done, what was delivered."""

    session_id: UUID
    date: date
    sport: str
    kind: StimulusKind | None = None
    planned_dose: StimulusDose | None = None
    executed: ExecutedStimulus | None = None
    load_au: float | None = None


class UnplannedWork(BaseModel):
    """A workout this week that matched no planned session."""

    workout_id: UUID
    date: date
    sport: str
    kind: StimulusKind | None = None
    executed: ExecutedStimulus | None = None
    load_au: float | None = None  # planned-scale load (minutes x RPE); None when it cannot be priced
    planned_kind: StimulusKind | None = None  # set for a substituted session: what was planned


class RemainingImpact(BaseModel):
    """How done work affects one remaining planned session. Advisory; nothing is rescheduled."""

    session_id: UUID
    date: date
    sport: str
    kind: StimulusKind | None = None
    impact: ImpactType
    evidence: list[str]


class WeekStimulusReview(BaseModel):
    """The week containing `as_of`: stimuli planned and done, missed, unplanned, and impacts."""

    week_start: date
    as_of: date
    planned_done: list[SessionStimulus] = Field(default_factory=list)
    planned_missed: list[SessionStimulus] = Field(default_factory=list)
    remaining: list[SessionStimulus] = Field(default_factory=list)
    unplanned_done: list[UnplannedWork] = Field(default_factory=list)
    substituted_done: list[UnplannedWork] = Field(default_factory=list)  # planned one kind, delivered another
    impacts: list[RemainingImpact] = Field(default_factory=list)
    load_comparable: bool = True  # every done workout could be priced on the planned scale
    planned_load_au: float = 0.0
    done_load_au: float = 0.0
    remaining_load_au: float = 0.0


def _planned_scale_load(workout: Workout, session: Session | None, athlete: Athlete) -> float | None:
    """A done workout's load on the planned-session scale (`session_target_load_au`: minutes x RPE).
    `load.session_load` is a different scale for measured tiers (power TSS, HR TRIMP are about one
    hour at threshold = 100), so it is never compared with a planned target. Priced as the athlete's
    own sRPE when rated, else as the matched session's target (the session done as planned); None when
    neither exists."""
    if workout.rpe:
        return workout.duration_min * workout.rpe
    return session_target_load_au(session, athlete) if session is not None else None


def _source_subject(u: UnplannedWork) -> str:
    """Who delivered the work: an unplanned workout, or a planned session that delivered another kind."""
    unit = _unit_of(u.sport)
    delivered = f"delivered {format_amount(u.executed.dose.work_in(unit), unit)} of {u.executed.dose.kind}"
    if u.planned_kind is None:
        return f"unplanned {u.sport} on {u.date.isoformat()} {delivered}"
    return f"{u.date.strftime('%A')}'s planned {u.planned_kind} {u.sport} session {delivered}"


def _unit_of(sport: str) -> Unit | None:
    profile = profile_for(sport)
    return profile.unit if profile else None


def _duplicate_impact(remaining: SessionStimulus, unplanned: list[UnplannedWork]) -> RemainingImpact | None:
    dose, unit = remaining.planned_dose, _unit_of(remaining.sport)
    if dose is None or unit is None:
        return None
    evidence: list[str] = []
    for u in unplanned:
        if u.executed is None or u.executed.dose.kind != dose.kind or profile_for(u.sport) is not profile_for(remaining.sport):
            continue
        fraction = u.executed.dose.fraction_of(dose, unit)
        if fraction is not None and fraction >= DUPLICATE_STIMULUS_FRACTION:
            evidence.append(
                f"{_source_subject(u).capitalize()}, already {fraction:.0%} of this session's planned {dose.kind} dose "
                f"({format_amount(u.executed.dose.work_in(unit), unit)} vs {format_amount(dose.work_in(unit), unit)}); "
                f"the duplicate threshold is {DUPLICATE_STIMULUS_FRACTION:.0%}."
            )
    return _impact(remaining, "duplicate_stimulus", evidence)


def _hard_too_soon_impact(remaining: SessionStimulus, unplanned: list[UnplannedWork]) -> RemainingImpact | None:
    if remaining.kind not in HARD_KINDS:
        return None
    evidence = [
        f"{remaining.kind} session on {remaining.date.isoformat()} is {(remaining.date - u.date).days * 24:.0f} h after "
        f"{_source_subject(u)} (under {HARD_RECOVERY_WINDOW_H:.0f} h)."
        for u in unplanned
        if u.executed is not None
        and u.executed.dose.kind in HARD_OR_LONG_KINDS
        and 0 <= (remaining.date - u.date).days * 24 < HARD_RECOVERY_WINDOW_H
    ]
    return _impact(remaining, "hard_too_soon", evidence)


def _impact(remaining: SessionStimulus, impact: ImpactType, evidence: list[str]) -> RemainingImpact | None:
    if not evidence:
        return None
    return RemainingImpact(session_id=remaining.session_id, date=remaining.date, sport=remaining.sport,
                           kind=remaining.kind, impact=impact, evidence=evidence)


def _load_over_target_impact(review: WeekStimulusReview) -> RemainingImpact | None:
    projected = review.done_load_au + review.remaining_load_au
    limit = review.planned_load_au * (1 + WEEKLY_VOLUME_RAMP_CAP)
    if not review.load_comparable or review.planned_load_au <= 0 or not review.remaining or projected <= limit:
        return None
    heaviest = max(review.remaining, key=lambda r: r.load_au or 0.0)
    return _impact(heaviest, "load_over_target", [
        f"Done {review.done_load_au:.0f} AU plus {review.remaining_load_au:.0f} AU still planned is {projected:.0f} AU, "
        f"over the week's planned {review.planned_load_au:.0f} AU by more than the {WEEKLY_VOLUME_RAMP_CAP:.0%} weekly ramp rail "
        f"(limit {limit:.0f} AU). Attached to the heaviest remaining session ({heaviest.load_au or 0:.0f} AU)."
    ])


def _session_entry(session: Session, athlete: Athlete, executed: ExecutedStimulus | None, load: float | None) -> SessionStimulus:
    dose = planned_dose(session, athlete)
    return SessionStimulus(session_id=session.id, date=session.date, sport=session.sport,
                           kind=dose.kind if dose else None, planned_dose=dose, executed=executed, load_au=load)


def _match_week(workouts: list[Workout], sessions: list[Session]) -> dict[UUID, Session | None]:
    return {w.id: match_workout_to_session(w, sessions, other_workouts=[o for o in workouts if o is not w]) for w in workouts}


def week_stimulus_review(
    week_plan: WeekPlan,
    workouts: list[Workout],
    athlete: Athlete,
    wellness: list[Wellness],
    *,
    as_of: date,
) -> WeekStimulusReview:
    """For the Monday-Sunday week containing `as_of`: planned-and-done, planned-and-missed (date
    passed), remaining, and unplanned stimuli, plus an impact on each remaining planned session when
    unplanned work duplicated its stimulus (>= 75% of its dose), puts it under 48 h after hard or
    long work, or pushes the week's load past planned by more than the weekly ramp rail (attached to
    the heaviest remaining session). Skipped and replaced sessions count as missed / ignored."""
    start = as_of - timedelta(days=as_of.weekday())
    done = [w for w in workouts if start <= w.date <= min(as_of, start + timedelta(days=6))]
    sessions = [s for s in week_plan.sessions if s.status != "replaced"]
    matches = _match_week(done, sessions)
    review = WeekStimulusReview(week_start=start, as_of=as_of)
    done_ids: set[UUID] = set()
    substituted_ids: set[UUID] = set()
    for w in done:
        session = matches[w.id]
        executed = executed_dose(w, athlete, session)
        swapped = executed is not None and executed.substituted
        load = _planned_scale_load(w, None if swapped else session, athlete)
        review.load_comparable &= load is not None
        review.done_load_au += load or 0.0
        if session is None or swapped:
            work = UnplannedWork(workout_id=w.id, date=w.date, sport=w.sport, kind=executed.dose.kind if executed else None,
                                 executed=executed, load_au=load, planned_kind=executed.planned_kind if swapped else None)
            (review.substituted_done if swapped else review.unplanned_done).append(work)
            if swapped:
                substituted_ids.add(session.id)
        else:
            review.planned_done.append(_session_entry(session, athlete, executed, load))
        if session is not None and not swapped:
            done_ids.add(session.id)
    for session in sessions:
        if session.id in done_ids:
            continue
        entry = _session_entry(session, athlete, None, session_target_load_au(session, athlete))
        if session.id in substituted_ids or session.date < as_of or session.status == "skipped":
            review.planned_missed.append(entry)
        else:
            review.remaining.append(entry)
    review.planned_load_au = sum(session_target_load_au(s, athlete) for s in sessions)
    review.remaining_load_au = sum(e.load_au or 0.0 for e in review.remaining)
    review.impacts = _impacts(review)
    return review


def _impacts(review: WeekStimulusReview) -> list[RemainingImpact]:
    found: list[RemainingImpact | None] = []
    sources = review.unplanned_done + review.substituted_done
    for remaining in review.remaining:
        found.append(_duplicate_impact(remaining, sources))
        found.append(_hard_too_soon_impact(remaining, sources))
    found.append(_load_over_target_impact(review))
    return [i for i in found if i is not None]
