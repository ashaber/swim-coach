"""Lever-based guardrail findings for one planned session (used by `progression_check`).

When the athlete's reference session and the planned session each have a regular shape in the same
zone, the plan is judged by which levers it moves (`progression_levers.classify_move`) instead of by a
percentage of the dose. Findings are advisory `judgment` class; nothing here branches on the sport.

Rules (Coach judgment, library/48-stimulus-progression.md "Guardrail findings"):
- `progression-threshold-rebase-<sport>-<kind>` (medium): the threshold rose since the reference
  session and the plan continues from the old reference instead of the restart level.
- `progression-multi-lever-<sport>-<kind>` (medium): more than one lever progresses at once.
- `progression-oversized-step-<sport>-<kind>` (medium; high after a reduce or rebuild verdict): one lever
  moves more than one step.
- `progression-over-ceiling-<sport>-<kind>` (medium): work beyond the zone's per-session ceiling.
- `progression-retest-<sport>` (low): the reference is at the ceiling with clean sessions and no
  threshold test is planned this week.
"""

from __future__ import annotations

from swim_coach.models import Athlete, PlanCheckFinding, Session, WeekPlan
from swim_coach.progression import ProgressionRead
from swim_coach.progression_levers import LeverPolicy, MoveRead, SessionShape, classify_move, fmt_size
from swim_coach.stimulus import StimulusDose, profile_for

_TEST_ROLES = frozenset({"ramp"})


def _is_test_session(session: Session) -> bool:
    """A planned threshold test: a ramp step in its structure, or "test" in its title or purpose."""
    words = f"{session.title or ''} {session.purpose}".lower().split()
    steps = getattr(session.structured, "items", []) if session.structured else []
    return "test" in words or any(getattr(s, "role", None) in _TEST_ROLES for s in steps)


def week_has_test(week: WeekPlan, group: str) -> bool:
    return any(
        _is_test_session(s) and (p := profile_for(s.sport)) is not None and p.name == group for s in week.sessions
    )


def candidate_fix(read: ProgressionRead) -> str:
    """The top three candidates in rung notation, e.g. "Try 2x12 min/4 min Z4 (rep 10 min -> 12 min); ..."."""
    top = [f"{c.rung} ({c.change})" for c in read.candidates[:3]]
    return "Try " + "; ".join(top) + "; or keep the plan and say why." if top else "Keep the plan and say why."


def _evidence(session: Session, planned: SessionShape, reference: SessionShape, read: ProgressionRead, move: MoveRead) -> str:
    clean = "last clean" if read.reference is not None else "last"
    changed = move.summary or "no lever change"
    return (f"{clean} {reference.describe()}; planned {planned.describe()} on {session.date.isoformat()}: {changed}. "
            f"Verdict {read.verdict} ({read.confidence} confidence).")


def _finding(fid: str, severity: str, evidence: str, consequence: str, read: ProgressionRead) -> PlanCheckFinding:
    return PlanCheckFinding(id=fid, severity=severity, evidence=evidence,  # type: ignore[arg-type]
                            consequence=consequence, fix=candidate_fix(read), category="judgment")


def _rebase_ignored(planned: SessionShape, read: ProgressionRead) -> bool:
    return bool(read.rebase and read.rebase.rebased and read.shape and planned.work() >= read.shape.work())


def lever_findings(
    session: Session, planned: SessionShape, read: ProgressionRead, policy: LeverPolicy, *, week: WeekPlan, taper: bool
) -> list[PlanCheckFinding]:
    """Findings for one session whose shape and the read's reference shape share a zone, most
    informative first (the caller keeps one per sport and kind by severity, then this order)."""
    reference = read.rebase.shape if read.rebase and read.rebase.rebased else read.shape
    move = classify_move(reference, planned, policy)
    tag, text = f"{read.sport}-{read.kind}", _evidence(session, planned, reference, read, move)
    severe = read.verdict in ("reduce", "rebuild")
    out: list[PlanCheckFinding] = []
    if _rebase_ignored(planned, read):
        out.append(_finding(
            f"progression-threshold-rebase-{tag}", "medium",
            f"{read.rebase.reason} Planned {planned.describe()} on {session.date.isoformat()} continues from the old "
            f"reference {read.shape.describe()}; the restart level is {read.rebase.shape.describe()}.",
            "The first sessions at a higher threshold should be ones the athlete will not fail; "
            "continuing from the old level risks a failed or marginal session.", read))
    if move.multi_lever:
        out.append(_finding(f"progression-multi-lever-{tag}", "medium", text,
                            "Moving several levers at once makes a failed session impossible to read and raises its odds.", read))
    if move.oversized_step:
        out.append(_finding(f"progression-oversized-step-{tag}", "high" if severe else "medium", text,
                            "One lever moves more than a tolerable step from the last clean session.", read))
    if move.over_ceiling:
        zone = policy.zone(planned.sport_group, planned.zone)
        ceiling = fmt_size(zone.band_for(planned.rep_size).work, planned.unit)
        out.append(_finding(f"progression-over-ceiling-{tag}", "medium",
                            f"{text} It is past the {planned.zone} per-session ceiling of {ceiling}: {move.ceiling_source}",
                            "Work beyond the tested or judged ceiling has no support for its benefit and costs recovery.", read))
    if read.retest_suggested and read.verdict == "progress" and not taper and not week_has_test(week, read.sport):
        out.append(_finding(f"progression-retest-{read.sport}", "low",
                            f"{text} The last clean session is at the {planned.zone} ceiling and no threshold test is planned this week.",
                            "More volume at the top of the zone adds little; a retest sets the next zone targets.", read))
    return out


def zone_jump_finding(
    session: Session, dose: StimulusDose, reads: list[ProgressionRead], athlete: Athlete, policy: LeverPolicy
) -> PlanCheckFinding | None:
    """`progression-zone-jump-<sport>-<kind>` (low): the planned session's zone has no history and an
    easier zone's reading is below its promotion point. Silent without easier-zone history."""
    profile = profile_for(session.sport)
    planned = SessionShape.from_structure(session.structured, athlete, session.sport) if session.structured else None
    easier = [r for r in reads if profile and r.sport == profile.name and r.shape is not None
              and planned is not None and r.shape.zone < planned.zone]
    if planned is None or not easier:
        return None
    base = max(easier, key=lambda r: r.shape.zone)
    move = classify_move(base.shape, planned, policy, easier_best=base.shape)
    if not move.harder_zone_without_base:
        return None
    text = (f"Planned {planned.describe()} on {session.date.isoformat()} is the athlete's first {dose.kind} work; the "
            f"easier zone's last session was {base.shape.describe()}, below its {base.shape.zone} promotion point.")
    return _finding(f"progression-zone-jump-{base.sport}-{dose.kind}", "low", text,
                    "Starting a harder zone before the easier one is built raises the chance of a failed session.", base)
