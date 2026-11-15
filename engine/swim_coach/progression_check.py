"""Advisory progression guardrails for one coach-authored week.

Compares each planned session's dose with the athlete's own progression read
(`progression.read_progression`) and carries the week's unplanned-work impacts through as findings.
Findings are `judgment` class: the coach may legitimately keep the plan. Nothing here rejects or
rewrites a plan, and nothing branches on the sport; sport differences come from `stimulus.profile_for`.

Weak data never fires a guardrail. A read with verdict `insufficient_data` or confidence "low"
produces no jump / ignores / stalled / rep-length finding, and a session whose planned dose is only
"estimated" (no structured steps) can only draw the `unplanned-*` findings. A guardrail that fires
on weak data erodes trust. `progression-stalled-*` is also suppressed in a taper or race week.
Rules and thresholds reuse `progression.PROGRESSION_STEP_FRACTION`; see
library/48-stimulus-progression.md "Guardrail findings" (Coach judgment).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from swim_coach.formatting import format_amount
from swim_coach.models import Athlete, MacroWeek, PlanCheckFinding, Session, ThresholdRecord, WeekPlan, Wellness, Workout
from swim_coach.progression import (
    PROGRESSION_STEP_FRACTION,
    ProgressionRead,
    RemainingImpact,
    StimulusRecord,
    WeekStimulusReview,
    build_ledger,
    week_stimulus_review,
)
from swim_coach.lever_read import read_levers
from swim_coach.progression_check_levers import candidate_fix, lever_findings, zone_jump_finding
from swim_coach.progression_levers import LeverPolicy, SessionShape, default_policy
from swim_coach.stimulus import SportProfile, StimulusDose, planned_dose, profile_for

_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}
_TAPER_PHASE_WORDS = ("taper", "race")
_IMPACT_SEVERITY = {"hard_too_soon": "medium", "duplicate_stimulus": "low", "load_over_target": "low"}
_IMPACT_TEXT = {
    "hard_too_soon": (
        "A hard session soon after unplanned hard or long work raises the chance it is under-recovered or abandoned.",
        "Move it, ease it, or keep it knowing the athlete is carrying that work.",
    ),
    "duplicate_stimulus": (
        "The stimulus is already delivered this week, so the planned session adds load without a new adaptation.",
        "Swap it for a different stimulus or an easier session, or keep it deliberately.",
    ),
    "load_over_target": (
        "The week lands above its planned load by more than the weekly ramp rail.",
        "Ease the remaining sessions, or keep the week and confirm the extra load.",
    ),
}


@dataclass(frozen=True)
class ProgressionInputs:
    """What `check_week` needs to run the progression guardrails; build with `build_progression_inputs`."""

    reads: list[ProgressionRead]
    review: WeekStimulusReview | None = None
    ledger: list[StimulusRecord] = field(default_factory=list)
    as_of: date | None = None


def build_progression_inputs(
    workouts: list[Workout],
    weeks: list[WeekPlan],
    wellness: list[Wellness],
    athlete: Athlete,
    week: WeekPlan,
    *,
    as_of: date,
    thresholds: list[ThresholdRecord] | None = None,
) -> ProgressionInputs:
    """Ledger, per-kind reads (with the lever view) and the week review in one call (pure; the caller
    loads the data). `thresholds` dates the threshold each session was done at, for the rebase."""
    ledger = build_ledger(workouts, weeks, wellness, athlete, as_of=as_of, thresholds=thresholds)
    return ProgressionInputs(
        reads=read_levers(ledger, athlete, as_of=as_of),
        review=week_stimulus_review(week, workouts, athlete, wellness, as_of=as_of),
        ledger=ledger,
        as_of=as_of,
    )


def _recent_longest(ledger: list[StimulusRecord]) -> dict[str, float]:
    """Largest executed work per sport profile in the ledger, in that profile's unit."""
    longest: dict[str, float] = {}
    for record in ledger:
        profile = profile_for(record.sport)
        work = record.executed.dose.work_in(profile.unit) if profile else None
        if profile and work:
            longest[profile.name] = max(longest.get(profile.name, 0.0), work)
    return longest


def _reference_date(read: ProgressionRead, ledger: list[StimulusRecord]) -> str:
    candidates = [*ledger, *([read.last] if read.last else [])]
    match = next((r for r in candidates if r.executed.dose == read.reference_dose), None)
    return match.date.isoformat() if match else "date unknown"


def _reference_work(read: ProgressionRead) -> float | None:
    """The last clean dose's work; the last executed dose when no session was clean."""
    if read.reference_dose is not None and read.reference_dose.work_in(read.unit):
        return read.reference_dose.work_in(read.unit)
    return read.last.executed.dose.work_in(read.unit) if read.last else None


def _evidence(session: Session, dose: StimulusDose, read: ProgressionRead, ledger: list[StimulusRecord]) -> str:
    unit, ref = read.unit, _reference_work(read)
    return (
        f"Planned {format_amount(dose.work_in(unit), unit)} of {read.kind} {read.sport} on {session.date.isoformat()} "
        f"(longest rep {format_amount(dose.longest_rep_in(unit), unit)}); last reference dose {format_amount(ref, unit)} on "
        f"{_reference_date(read, ledger)}; verdict {read.verdict} ({read.confidence} confidence): "
        f"{read.verdict_reason or (read.reasons[0] if read.reasons else 'no reason recorded')}"
    )


def _fix(read: ProgressionRead) -> str:
    if read.candidates:
        return candidate_fix(read)
    low, high = read.suggested_work_range  # type: ignore[misc]  # callers guarantee a range
    text = f"Suggested work {format_amount(low, read.unit)} to {format_amount(high, read.unit)}"
    if read.suggested_longest_rep_max is not None:
        text += f", longest rep up to {format_amount(read.suggested_longest_rep_max, read.unit)}"
    return text + "; or keep the plan and say why."


def _finding(fid: str, severity: str, session: Session, dose: StimulusDose, read: ProgressionRead,
             ledger: list[StimulusRecord], consequence: str) -> PlanCheckFinding:
    return PlanCheckFinding(id=fid, severity=severity, evidence=_evidence(session, dose, read, ledger),  # type: ignore[arg-type]
                            consequence=consequence, fix=_fix(read), category="judgment")


def _is_taper_week(week: WeekPlan, macro_week: MacroWeek | None) -> bool:
    phase = (macro_week.phase if macro_week else "").lower()
    return any(w in phase for w in _TAPER_PHASE_WORDS) or any(s.effective_kind == "race" for s in week.sessions)


def _previous_not_progressed(read: ProgressionRead, ledger: list[StimulusRecord], profile: SportProfile) -> bool:
    """True when the last planned session of this kind did no more work than the one before it."""
    done = sorted((r for r in ledger if r.planned and r.kind == read.kind and profile_for(r.sport) is profile
                   and r.has_execution_data(profile.unit)), key=lambda r: r.date)
    if len(done) < 2:
        return False
    return done[-1].executed.dose.work_in(profile.unit) <= done[-2].executed.dose.work_in(profile.unit)


def _dose_findings(session: Session, dose: StimulusDose, read: ProgressionRead, profile: SportProfile,
                   ledger: list[StimulusRecord], taper: bool) -> list[PlanCheckFinding]:
    """The first four rules in priority order for one session."""
    unit, step = read.unit, PROGRESSION_STEP_FRACTION
    work, ref = dose.work_in(unit), _reference_work(read)
    tag = f"{read.sport}-{read.kind}"
    out: list[PlanCheckFinding] = []
    if work is None or read.suggested_work_range is None:
        return out
    severe = read.verdict in ("reduce", "rebuild")
    if work > read.suggested_work_range[1] * (1 + step):
        out.append(_finding(f"progression-jump-{tag}", "high" if severe else "medium", session, dose, read, ledger,
                            "Work well past the next sensible dose risks a failed or marginal session."))
    if severe and ref is not None and work >= ref:
        out.append(_finding(f"progression-ignores-{read.verdict}-{tag}", "medium", session, dose, read, ledger,
                            "The last session of this kind went badly or lapsed, and this plan repeats or exceeds that dose."))
    if (read.verdict == "progress" and not taper and ref is not None and work <= ref
            and _previous_not_progressed(read, ledger, profile)):
        out.append(_finding(f"progression-stalled-{tag}", "low", session, dose, read, ledger,
                            "Two sessions of this kind in a row without progress; fitness for it stops improving."))
    cap, longest = read.suggested_longest_rep_max, dose.longest_rep_in(unit)
    if cap is not None and longest is not None and longest > cap * (1 + step):
        out.append(_finding(f"progression-rep-length-{tag}", "low", session, dose, read, ledger,
                            "Reps much longer than the athlete has done recently are likely to fade."))
    return out


_LEVER_PATH_KEEPS = ("progression-ignores-", "progression-stalled-")


def _session_findings(session: Session, dose: StimulusDose, read: ProgressionRead, profile: SportProfile,
                      ledger: list[StimulusRecord], taper: bool, *, week: WeekPlan, athlete: Athlete,
                      policy: LeverPolicy) -> list[PlanCheckFinding]:
    """Lever findings when the reference and planned shapes share a zone (the dose-percentage jump and
    rep-length rules are then replaced by them; ignores and stalled still apply), else the dose rules."""
    planned = SessionShape.from_structure(session.structured, athlete, session.sport) if session.structured else None
    shared = planned is not None and read.shape is not None and (planned.sport_group, planned.zone) == (
        read.shape.sport_group, read.shape.zone)
    dose_found = _dose_findings(session, dose, read, profile, ledger, taper)
    if not shared:
        return dose_found
    kept = [f for f in dose_found if f.id.startswith(_LEVER_PATH_KEEPS)]
    return [*lever_findings(session, planned, read, policy, week=week, taper=taper), *kept]


def _checkable_sessions(week: WeekPlan, review: WeekStimulusReview | None, as_of: date | None) -> list[Session]:
    """Sessions the guardrails judge. A future week (or no `as_of`) checks all of them; once `as_of`
    falls inside or after the week, only sessions dated on or after it that are not done, skipped or
    replaced, so a session is never compared with its own execution."""
    monday = date.fromisocalendar(*(int(x) for x in week.iso_week.split("-W")), 1)
    ordered = sorted(week.sessions, key=lambda s: s.date)
    if as_of is None or as_of < monday:
        return ordered
    done = {s.session_id for s in review.planned_done} if review else set()
    return [s for s in ordered if s.date >= as_of and s.status == "planned" and s.id not in done]


def _unplanned_finding(impact: RemainingImpact) -> PlanCheckFinding:
    consequence, fix = _IMPACT_TEXT[impact.impact]
    return PlanCheckFinding(
        id=f"unplanned-{impact.impact}-{impact.date.isoformat()}", severity=_IMPACT_SEVERITY[impact.impact],  # type: ignore[arg-type]
        evidence=" ".join(impact.evidence), consequence=consequence, fix=fix, category="judgment")


def check_week_progression(
    week: WeekPlan,
    athlete: Athlete,
    *,
    reads: list[ProgressionRead],
    review: WeekStimulusReview | None = None,
    recent_longest: dict[str, float] | None = None,
    ledger: list[StimulusRecord] | None = None,
    macro_week: MacroWeek | None = None,
    as_of: date | None = None,
    policy: LeverPolicy | None = None,
) -> list[PlanCheckFinding]:
    """Guardrail findings for one week: jump, ignores-reduce/rebuild, stalled and rep-length (one per
    sport and kind, the most severe kept; when the read carries a lever shape and the session has one
    in the same zone, the lever findings of `progression_check_levers` replace jump and rep-length) plus an `unplanned-*` finding per remaining-session impact
    in `review`. `recent_longest` maps profile name to the longest recent work in its unit (default:
    derived from `ledger`). Stalled needs `ledger` and is suppressed in a taper or race week.
    `as_of`: when it falls inside or after the week, only sessions still to do are judged."""
    ledger = ledger or []
    recent = recent_longest if recent_longest is not None else _recent_longest(ledger)
    usable = {(r.sport, r.kind): r for r in reads if r.verdict != "insufficient_data" and r.confidence != "low"}
    taper = _is_taper_week(week, macro_week)
    best: dict[tuple[str, str], PlanCheckFinding] = {}
    for session in _checkable_sessions(week, review, as_of):
        profile = profile_for(session.sport)
        dose = planned_dose(session, athlete, recent_longest=recent.get(profile.name) if profile else None)
        read = usable.get((profile.name, dose.kind)) if profile and dose else None
        if dose is None or profile is None or dose.confidence != "structured":
            continue
        if not any(r.sport == profile.name and r.kind == dose.kind for r in reads):
            jump = zone_jump_finding(session, dose, reads, athlete, policy or default_policy())
            found, read = [jump] if jump else [], None
        elif read is None:
            continue
        else:
            found = _session_findings(session, dose, read, profile, ledger, taper, week=week, athlete=athlete,
                                      policy=policy or default_policy())
        for finding in found:
            key = (profile.name, dose.kind)
            if key not in best or _SEVERITY_RANK[finding.severity] < _SEVERITY_RANK[best[key].severity]:
                best[key] = finding
    ids = {s.id for s in week.sessions}
    unplanned = [_unplanned_finding(i) for i in (review.impacts if review else []) if i.session_id in ids]
    return [*best.values(), *unplanned]
