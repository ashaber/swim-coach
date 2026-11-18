"""`read_levers`: the ledger's per-kind progression read plus the lever view (shape, candidates, rebase).

Wraps `progression.read_progression`; the dose-based fields stay as the fallback for a kind whose
reference session has no regular shape. Nothing here branches on the sport: the threshold anchor and
the unit come from `stimulus.SportProfile`, the rules from the `LeverPolicy`.
"""

from __future__ import annotations

from datetime import date

from swim_coach.models import Athlete
from swim_coach.formatting import format_amount
from swim_coach.progression import ProgressionRead, StimulusRecord, read_progression
from swim_coach.progression_levers import (
    Candidate,
    LeverPolicy,
    RebaseRead,
    SessionShape,
    default_policy,
    is_at_ceiling,
    next_shapes,
    rebase_for_threshold_change,
)
from swim_coach.stimulus import KIND_RANK, profile_for

LENGTHEN_REASON_PREFIX = "Longest rep was"


def _restart(rebase: RebaseRead, reference: SessionShape, policy: LeverPolicy) -> Candidate:
    rule = policy.rebase_rule(reference.sport_group, reference.zone)
    return Candidate(
        shape=rebase.shape, rung=rebase.shape.describe(), lever="rebase", direction="rebase",
        change=f"restart {rebase.steps_down} lower: {reference.describe()} -> {rebase.shape.describe()}",
        work_delta_pct=(rebase.shape.work() / reference.work() - 1) * 100.0, basis=rule.basis,
    )


def _drop_lengthen_reasons(read: ProgressionRead) -> None:
    read.reasons = [r for r in read.reasons if not r.startswith(LENGTHEN_REASON_PREFIX)]


def _attach_candidates(read: ProgressionRead, shape: SessionShape, rebase: RebaseRead, policy: LeverPolicy) -> None:
    if rebase.rebased and read.verdict in ("progress", "repeat"):
        read.candidates = [_restart(rebase, shape, policy)]
        _set_cause(read, rebase.reason)
        return
    start = rebase.shape if rebase.rebased else shape
    read.candidates = next_shapes(start, policy, verdict=read.verdict)
    read.at_ceiling = read.verdict == "progress" and is_at_ceiling(start, policy)
    read.retest_suggested = any(c.direction == "retest" for c in read.candidates)
    if read.verdict == "progress" and read.candidates:
        top = read.candidates[0]
        _set_cause(read, f"Next: {top.change} ({top.rung}).")


def _set_cause(read: ProgressionRead, text: str) -> None:
    _drop_lengthen_reasons(read)
    read.reasons.append(text)
    read.verdict_reason = text


def _entry_read(read: ProgressionRead, policy: LeverPolicy) -> ProgressionRead:
    """No session to progress from but quality work of this kind was delivered unstructured: offer the
    zone's entry shape and say how much was delivered, so the coach can start higher."""
    rank = KIND_RANK.get(read.kind)
    if not read.also_delivered or rank is None or not policy.has_zone(read.sport, f"Z{rank}"):
        return read
    total = sum(a.work or 0.0 for a in read.also_delivered)
    count = len(read.also_delivered)
    read.candidates = next_shapes(None, policy, verdict="progress", group=read.sport, zone=f"Z{rank}")
    read.reasons.append(
        f"{count} unstructured {read.kind} session{'s' if count != 1 else ''} delivered in the lookback "
        f"({format_amount(total, read.unit)} in total) but none with a plan or regular shape to progress from; "
        f"the zone's entry shape is offered (start higher if the athlete is ready)."
    )
    return read


def _lever_read(read: ProgressionRead, athlete: Athlete, policy: LeverPolicy) -> ProgressionRead:
    if read.verdict == "insufficient_data":
        return _entry_read(read, policy)
    record = read.last
    profile = profile_for(record.sport) if record else None
    shape, note = record.lever_shape() if record and read.kind in _ZONE_KINDS else (None, None)
    if shape is None or profile is None or not policy.has_zone(shape.sport_group, shape.zone):
        return read
    then = record.anchor_value if record.anchor_known else None
    rebase = rebase_for_threshold_change(shape, anchor_then=then, anchor_now=profile.athlete_anchor(athlete), policy=policy)
    read.shape, read.shape_note, read.rebase = shape, note, rebase
    _attach_candidates(read, shape, rebase, policy)
    return read


_ZONE_KINDS = frozenset(KIND_RANK)


def read_levers(
    ledger: list[StimulusRecord], athlete: Athlete, *, as_of: date, policy: LeverPolicy | None = None
) -> list[ProgressionRead]:
    """`read_progression` with the lever view added to each read whose reference session has a regular
    shape: the `shape`, one-lever `candidates`, the threshold `rebase` (applied before the candidates),
    `at_ceiling` and `retest_suggested`. Reads without a derivable shape are returned unchanged."""
    policy = policy or default_policy()
    reads = read_progression(ledger, as_of=as_of)
    return [_lever_read(read, athlete, policy) for read in reads]
