"""Deterministic red-team review of a coach-AUTHORED plan.

Architecture (engine/plan-check-red-team, approved plan
`~/.claude/plans/just-exploring-a-design-cheeky-pretzel.md`): the LLM coach
authors macro/week plans directly (`MacroPlan.weeks`, real `Session`s); this
module computes and RED-TEAMS them with advisory findings. **It never
rejects or clamps a plan** -- `check_macro`/`check_week` always return a
`PlanCheckReport`, never raise, no matter how bad the input plan is. Findings
are bounded by research-based limits where evidence exists, and honestly
labelled `Coach judgment` / `PROVISIONAL` where it doesn't (several
constants below are explicitly placeholder values pending PR 3's dedicated
limits research -- see each constant's own comment).

Mirrors the shape of `ai-coach/.claude/agents/red-team.md`'s adversarial
review (VERDICT + ranked, capped objections: severity / evidence /
consequence / fix) -- deterministic engine code here instead of an LLM
subagent, per the approved plan's token-economics section.

Every named constant cites its `library/` file, per this project's own
"every engine constant must cite its library/ file" standing rule
(CLAUDE.md). Two already-cited files (`library/03-periodization.md`,
`library/24-cycling-periodization-intervals.md`) are already at or near the
2,500-word test cap (`tests/unit/test_library_discipline.py`'s Rule 5) --
this module cites them by REFERENCE for constants whose underlying
convention already lives there (CTL/ATL/TSB Banister model, ramp-rate
convention), without adding new prose to either file. `library/31-multi-
race-season-periodization.md` gets a genuinely NEW section (verified
short-event taper evidence -- Neary 2003, Houmard 1991, Rønnestad 2010 --
see that file's own new section for the citations).

**PR 3 update (engine/plan-check-red-team, 2026-09-27):** `library/36-
plan-authoring-limits.md` now grounds the constants PR 1 left labelled
PROVISIONAL, replacing that placeholder status with an honest verdict --
several stay `Coach judgment` because no evidence exists (masters ramp/
recovery cadence, time-feasibility margin), one changes on real evidence
(`MASTERS_ANNUAL_DECLINE_FRACTION`, Rogers 1990), and one is confirmed
already correct as-is (`GENERAL_TAPER_CUT_FRACTION_MIN/MAX`, Bosquet 2007).
Per the dossier's own orchestrator correction: `Hellard et al. (2013)`
studied a PREDEFINED overload/taper window and does not establish a
3-week taper as optimal, so `TAPER_WEEKS_LONG` (`plan.py`, the retired
scaffold's own constant) is NOT changed on that basis -- taper length is
now the coach's own per-event choice (`author_macro_plan`), this module's
taper constants only check the resulting plan's load reduction against
the evidence band, never pick a length for the coach.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal

from swim_coach.adapt import SINGLE_SESSION_STEP_CAP
from swim_coach.load import CTL_TIME_CONSTANT_DAYS, ATL_TIME_CONSTANT_DAYS, session_target_load_au
from swim_coach.models import (
    Athlete,
    Event,
    MacroPlan,
    MacroWeek,
    PlanCheckFinding,
    Session,
    WeekPlan,
)
from swim_coach.plan import WEEKLY_VOLUME_RAMP_CAP, evaluate_week_realism
from swim_coach.taper_search import RACE_DAY_TSB_BAND

Verdict = Literal["sound", "sound-with-caveats", "fragile", "not-feasible"]
Severity = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class PlanCheckReport:
    """Computed/response shape only -- NOT persisted (same "no
    schema_version" convention `WorkoutQuality`/`PlanCheckFinding` in
    models.py already use for this codebase's other computed shapes; a
    dataclass rather than a pydantic BaseModel since nothing here is ever
    round-tripped through YAML/DB). `findings` is already ranked
    (highest-consequence first) and capped at `MAX_FINDINGS` -- callers
    never need to re-sort or re-truncate.

    `MacroPlan.red_team` (models.py) is the PERSISTED counterpart: once a
    coach reviews a report, PR 2's confirm flow copies each finding here
    into a `MacroRedTeamRecord`, adding the coach's own `fix`/`keep_as_is`
    decision (engine/red-team-taper-gate: not `accept`/`decline`, which
    caused a real bad outcome -- see that model's own docstring) -- this
    report itself is never written to disk.
    """

    verdict: Verdict
    findings: list[PlanCheckFinding] = field(default_factory=list)

    def to_dict(self) -> dict:
        """JSON-friendly shape for `cli.py`'s `check-macro`/`check-week`
        commands (every CLI command prints exactly one JSON object -- see
        that module's own docstring)."""
        return {
            "verdict": self.verdict,
            "findings": [
                {
                    "id": f.id,
                    "severity": f.severity,
                    "evidence": f.evidence,
                    "consequence": f.consequence,
                    "fix": f.fix,
                }
                for f in self.findings
            ],
        }


MAX_FINDINGS = 6
# Cap, per the approved plan and mirroring `ai-coach/.claude/agents/red-
# team.md`'s own "cap it at six objections... the three that matter are
# getting burying" discipline. Coach judgment -- a review-quality rule, not
# a physiology citation.

_SEVERITY_ORDER: dict[Severity, int] = {"high": 0, "medium": 1, "low": 2}


# ============================================================================
# Constants -- one cited source per number. "PROVISIONAL"/"Coach judgment"
# marks a placeholder this project has no direct evidence for yet (PR 3's
# dedicated limits-research dossier is expected to replace several of these).
# ============================================================================

# --- CTL ramp rate (dossier-season-taper-2026-09-26.md Q4, reconfirmed by
# library/36-plan-authoring-limits.md's "Masters ramp and recovery-week
# cadence" section: convention only, no peer-reviewed evidence found for a
# ramp-RATE number at all, masters or otherwise; Friel/TrainingPeaks
# practitioner convention, "5-8 CTL points/week," individualized). Mirrors
# `ai-coach/.claude/agents/red-team.md`'s own framing verbatim ("+5 to +7
# per week sustained is a flag for most athletes, lower for masters
# athletes and anyone with an injury history"). Coach judgment -- NOT an
# [EVIDENCE] claim; library/36 explicitly declines to invent a masters-
# specific ramp-rate number where none exists, and keeps this as a
# ceiling, not a target. library/03-periodization.md (CTL/ATL/TSB section)
# + library/36-plan-authoring-limits.md.
CTL_RAMP_CAP_PER_WEEK = 7.0
CTL_RAMP_CAP_PER_WEEK_MASTERS_OR_INJURY = 5.0
MASTERS_AGE_THRESHOLD = 40
# The approved plan's own spec: "lower for masters age >=40 or injury
# history." Coach judgment -- no citation pins 40 specifically as the
# masters cutoff for CTL-ramp tolerance; 40 is this project's chosen
# threshold, consistent with common masters-category conventions
# (USMS/British Masters swimming and masters cycling both use 25-40+
# tiers). library/03-periodization.md.

# --- Recovery cadence (approved plan: "recovery cadence (3:1, or 2:1
# masters)"). Coach judgment -- library/36-plan-authoring-limits.md
# ("Masters ramp and recovery-week cadence") confirms no study tests 3:1
# vs. 2:1 cadence in a real masters cohort; the 2:1 shift is a defensible
# default given real, cited context (Hottenrott 2022's well-trained-
# masters recovery-kinetics finding; Burtscher 2022's volume-matters-more-
# than-age finding), not itself a cadence trial. library/03-
# periodization.md (macro-block-shape conventions) + library/36.
RECOVERY_CADENCE_WEEKS = 3
RECOVERY_CADENCE_WEEKS_MASTERS_OR_INJURY = 2

# --- Taper: judged by ACTUAL LOAD REDUCTION, never by phase-name text.
# `MacroWeek.phase` is free text the coach chooses ("Peak," "Sharpen 3,"
# "Unload," ...) -- a plan that never once writes the literal word "taper"
# can still taper correctly (see library/31-multi-race-season-
# periodization.md's new "Short-event taper and in-season maintenance"
# section, Neary et al. (2003), verified this dossier pass: a 7-day,
# ~50%-volume-cut taper, intensity held, significantly improved a ~25-30
# min time-trial effort).
SHORT_EVENT_MAX_HOURS = 1.5
# Coach judgment: threshold below which an event counts as "short" for
# taper purposes. Neary 2003 studied a ~25-30 min TT; 1.5h is a generous
# ceiling that still comfortably covers a cyclocross race (typically
# 40-60 min) with margin, not itself an evidence-pinned cutoff.

SHORT_EVENT_TAPER_CUT_FRACTION_MIN = 0.30
SHORT_EVENT_TAPER_CUT_FRACTION_MAX = 0.65
# [EVIDENCE: cycling] Neary, Bhambhani & McKenzie (2003) -- 30%/50%/80%
# volume-cut tapers were tested; only the 50% cut reached significance.
# MIN/MAX bracket a band around that single validated point, short of the
# two non-significant tested extremes -- Coach judgment banding, not
# itself a validated range (only 50% is directly evidence-backed).
# library/31-multi-race-season-periodization.md.

GENERAL_TAPER_CUT_FRACTION_MIN = 0.41
GENERAL_TAPER_CUT_FRACTION_MAX = 0.60
# [ADAPTED: general-endurance] Bosquet, Montpetit, Arvisais & Mujika
# (2007) meta-analysis (already cited in library/31 and
# library/03-periodization.md): the optimal full taper is a ~2-week
# exponential volume reduction of 41-60%. Reused here unchanged for any
# event NOT classified "short" (SHORT_EVENT_MAX_HOURS).
#
# PR 3 confirmation (library/36-plan-authoring-limits.md, "Swim taper
# length"): this band is CONFIRMED, not changed -- it was already the
# best-supported number in the dossier pass, and stays the load-based
# check band regardless of event/sport. Explicitly NOT tightened toward a
# "3-week taper" reading of `Hellard et al. (2013)` -- that paper studied
# a PREDEFINED overload/taper window, not a length comparison, so it
# cannot ground a 3-week optimum (dossier's own orchestrator correction).
# `TAPER_WEEKS_LONG`/`TAPER_WEEKLY_DECAY` (plan.py's retired scaffold
# constants) are correspondingly left unchanged here too -- taper LENGTH
# is the coach's own per-event choice (`author_macro_plan`); this module
# only checks the resulting volume cut against the band above, it never
# picks a length. library/36-plan-authoring-limits.md.

TAPER_BASELINE_LOOKBACK_WEEKS = 4
# Coach judgment / PROVISIONAL: how many weeks back from the final
# pre-race week to look for the recent BUILD peak the cut is measured
# against. No citation pins this window specifically -- chosen to
# comfortably reach the recent build block without reaching back into an
# unrelated earlier phase of a long macro. library/31-multi-race-season-
# periodization.md.

# --- Taper-too-long (real production failure, 2026-09-27): a plan can pass
# `_check_one_event_taper`'s "is race week's own cut deep enough" question
# while still spending WEEKS of the build window already tapering before
# race week ever arrives -- exactly what shipped on the first real run
# ("Build my macro for the rest of the CX season"): Sep 28 Taper, Oct 5
# Taper, Oct 12 Race (the only race-free build window spent tapering, not
# building). The red team that day returned only medium findings (race-day
# TSB just outside band; recovery cadence) and the coach talked itself out
# of even those ("too fresh is a smaller risk than flat") -- contrary to
# the evidence below. This is the dedicated, load-based check for that
# failure mode.
TAPER_TOO_LONG_CUT_FRACTION = 0.20
# Coach judgment: a week counts as "already tapering" (not still build) once
# its volume sits at least 20% below the recent build peak -- comfortably
# below `SHORT_EVENT_TAPER_CUT_FRACTION_MIN` (0.30, the shallow end of the
# evidence-backed RACE-WEEK cut band) so an ordinary lighter week deep in
# the build isn't miscounted as the start of a taper run, while still
# catching a real multi-week glide-down. library/31-multi-race-season-
# periodization.md (Neary 2003, Houmard 1991), library/36-plan-authoring-
# limits.md (Bosquet 2007).
LONG_EVENT_MAX_TAPER_WEEKS_BEFORE_RACE = 2
# `[ADAPTED: general-endurance] Bosquet et al. (2007)`: the optimal FULL
# taper is a ~2-week exponential volume reduction (already-cited GROUNDS
# `GENERAL_TAPER_CUT_FRACTION_MIN/MAX` above; library/36-plan-authoring-
# limits.md's "Swim taper length" section, reconfirmed 2026-09-27). Weeks of
# already-tapered load beyond that 2-week window, sitting before race week
# itself, are "too long" for a long event -- not itself a citation for the
# number 2 as a hard ceiling, but the same evidence already anchoring the
# cut-depth band.

# --- Race-day TSB band (library/22-injury-adapted-taper.md's existing
# `RACE_DAY_TSB_BAND`, imported and reused unchanged -- not redefined here;
# see that module's own citation, Joe Friel via TrainingPeaks, Confidence:
# medium).

# --- Sustained low TSB (approved plan: "build TSB not sustained below -30
# without a reason"). Coach judgment / PROVISIONAL -- no citation pins -30
# specifically; chosen as a clearly-deep fatigue reading, well past the
# -10 to -20 range typically described as a normal, recoverable build-phase
# dip in cycling/TrainingPeaks practitioner literature (the same tier
# `library/22-injury-adapted-taper.md`'s own race-day-TSB citation comes
# from). library/03-periodization.md (CTL/ATL/TSB section).
SUSTAINED_LOW_TSB_THRESHOLD = -30.0
SUSTAINED_LOW_TSB_MIN_CONSECUTIVE_DAYS = 14

# --- Time-reality buffer (approved plan, quoting
# `ai-coach/.claude/agents/red-team.md` verbatim: "Plans routinely require
# 10% more time than they claim"). Coach judgment -- a planning-discipline
# heuristic, not a physiology citation; library/36-plan-authoring-limits.md
# ("Time-feasibility margin") confirms no peer-reviewed source gives a
# planned-vs-completed training-TIME adherence percentage for adult
# endurance athletes (the one quantified figure found is a poor
# population match -- junior netball, session-count not hours). Distinct
# from `Inoue et al. (2022)`'s real but ADJACENT finding (easy days run
# hotter than coaches plan, an intensity-perception gap, not a duration
# one) -- not folded into this fraction. library/03-periodization.md +
# library/36-plan-authoring-limits.md.
TIME_REALITY_BUFFER_FRACTION = 0.10

# --- Goal reality check (approved plan: "the implied rate of progress to
# the stated goal ... against research-based progression rates and the
# athlete's age"). PR 3 update (library/36-plan-authoring-limits.md):
#
# MAX_REALISTIC_ANNUAL_GAIN_FRACTION stays Coach judgment, NOT PROVISIONAL
# -- library/36's "Realistic progression rates" section confirms no
# numeric W/kg (or annual-%) ceiling is evidence-backed for a trained
# masters athlete; the QUALITATIVE shape is evidence-backed instead
# (Bacon 2013: diminishing returns with training age; Cove 2024: modest,
# single-digit-to-low-teens-% gains per block in trained cyclists, block
# DURATION predicting improvement, not added weekly volume). 0.08 (8%/yr)
# is a Coach-judgment pick inside that qualitative band, not a citation-
# derived number -- false precision would misrepresent the evidence.
#
# MASTERS_ANNUAL_DECLINE_FRACTION CHANGES on real evidence: `Rogers et al.
# (1990)`'s 8-year LONGITUDINAL cohort (not cross-sectional) found trained
# masters athletes' VO2max declined ~5.5%/decade, roughly half the
# sedentary rate (~12%/decade) -- library/36 flags `Pimentel et al.
# (2003)`'s contradicting cross-sectional finding honestly rather than
# picking a false-precision single "settled" number, but Rogers' same-
# cohort longitudinal design is the stronger design for isolating a
# training-maintenance effect, so it anchors this constant.
#
# GOAL_REALITY_CHECK_HORIZON_YEARS stays Coach judgment (review-cadence
# heuristic, not a citation) -- library/36 makes no horizon-length claim.
# library/36-plan-authoring-limits.md (all three).
MAX_REALISTIC_ANNUAL_GAIN_FRACTION = 0.08
MASTERS_ANNUAL_DECLINE_FRACTION = 0.006
GOAL_REALITY_CHECK_HORIZON_YEARS = 5.0

# --- Polarization (library/24-cycling-periodization-intervals.md's own
# existing Seiler-polarized citation, already grounding
# `plan.evaluate_week_realism`'s `BIKE_MAX_HARD_DAYS_PER_WEEK`; reused here
# as a session-count fraction rather than a raw day count, for a
# session-count-based read on non-bike-primary weeks too).
POLARIZED_MAX_HARD_SESSION_FRACTION = 1.0 / 3.0
_HARD_ZONES = frozenset({"Z4", "Z5"})


def _is_hard_session(session: Session) -> bool:
    """A session counts as "hard" for the polarization check if it's
    planned at Z4/Z5 -- the same zone-based hard/easy split
    `plan.evaluate_week_realism`'s own hard-bike check already uses
    (library/24, Seiler polarized distribution), generalized here to any
    sport rather than bike-only."""
    return session.intensity.get("zone") in _HARD_ZONES


def _age_years(dob: date | None, as_of: date) -> float | None:
    if dob is None:
        return None
    years = as_of.year - dob.year - ((as_of.month, as_of.day) < (dob.month, dob.day))
    return float(years)


def _project_ctl_atl_tsb(
    current_ctl: float,
    daily_loads_by_date: dict[date, float],
    start: date,
    end: date,
    *,
    current_atl: float | None = None,
) -> list[tuple[date, float, float, float]]:
    """Project CTL/ATL/TSB day-by-day from `start` through `end` (inclusive),
    SEEDED at the athlete's real, ACTUAL current CTL -- not from zero.

    Same exact Banister recursion `load.ctl_atl_tsb_series` implements
    (`CTL_t = CTL_{t-1} + (load_t - CTL_{t-1}) / CTL_TIME_CONSTANT_DAYS`,
    same shape for ATL, both constants imported from `load.py` unchanged) --
    but that function always seeds `CTL = ATL = 0` immediately before the
    earliest day it walks (see its own "Known limitation -- cold start"
    section), which is the WRONG behavior for a plan-check projection: a
    macro review must start from where the athlete REALLY is today, not
    climb from zero over the projected weeks. This is a small, deliberate
    seeding fix, not a different model.

    `current_atl`: the athlete's REAL current ATL, when the caller has one
    (e.g. `load.ctl_atl_tsb_series` over her real logged history -- see
    `cli.py`'s `check-macro` command). Falls back to `current_ctl` (an
    assumed TSB=0 as of `start`) when omitted, same behavior as before this
    parameter existed -- every existing caller that only ever had a CTL
    number on hand keeps working unchanged.
    """
    ctl = current_ctl
    atl = current_ctl if current_atl is None else current_atl
    series: list[tuple[date, float, float, float]] = []
    day = start
    while day <= end:
        load = daily_loads_by_date.get(day, 0.0)
        ctl = ctl + (load - ctl) / CTL_TIME_CONSTANT_DAYS
        atl = atl + (load - atl) / ATL_TIME_CONSTANT_DAYS
        series.append((day, ctl, atl, ctl - atl))
        day += timedelta(days=1)
    return series


def _spread_weekly_tss_to_daily(weeks: list[MacroWeek]) -> dict[date, float]:
    """Planned weekly TSS, spread evenly across that week's 7 days --
    the approved plan's own explicit instruction ("spread evenly per day
    unless better info exists"; this module has no per-day breakdown to do
    better with, since a `MacroWeek` is a macro-level row, not day-by-day
    `Session`s). A week with `load_tss=None` contributes zero load days
    (not a fabricated number) -- `_check_bike_weeks_missing_load` is the
    dedicated finding for a week missing this data, not this function."""
    out: dict[date, float] = {}
    for week in weeks:
        if week.load_tss is None:
            continue
        daily = week.load_tss / 7.0
        for offset in range(7):
            out[week.week_start + timedelta(days=offset)] = daily
    return out


def _week_for_date(weeks: list[MacroWeek], day: date) -> MacroWeek | None:
    for week in weeks:
        if week.week_start <= day < week.week_start + timedelta(days=7):
            return week
    return None


def _sorted_weeks(weeks: list[MacroWeek]) -> list[MacroWeek]:
    return sorted(weeks, key=lambda w: w.week_start)


# ============================================================================
# check_macro
# ============================================================================


def check_macro(
    plan: MacroPlan,
    athlete: Athlete,
    *,
    current_ctl: float,
    current_atl: float | None = None,
    recent_weekly_hours: list[float],
    events: list[Event],
    today: date,
) -> PlanCheckReport:
    """Red-team a coach-authored macro plan (`plan.weeks`). Never raises,
    never clamps/edits `plan` -- always returns a `PlanCheckReport`, even
    for a badly broken plan (see `test_plan_check.py`'s
    `test_check_macro_never_raises_on_a_bad_plan`).

    `current_ctl`: the athlete's REAL current CTL (e.g. from
    `load.ctl_atl_tsb_series` over her actual logged history) -- the
    projection below starts here, not from zero.
    `current_atl`: the athlete's REAL current ATL from the same series,
    when the caller has one. Optional -- falls back to `current_ctl` (an
    assumed TSB=0 as of `today`) when omitted, same behavior as before
    this parameter existed.
    `recent_weekly_hours`: the athlete's actual weekly training hours over
    (nominally) the trailing ~12 weeks, most-recent-last or in any order --
    only `max()` is read.
    `events`: every `Event` this athlete has on file (active and inactive);
    only `active=True` events are checked.
    `today`: the date this check is run as-of.
    """
    weeks = _sorted_weeks(plan.weeks)
    active_events = [e for e in events if e.active]
    findings: list[PlanCheckFinding] = []

    if not weeks:
        findings.append(
            PlanCheckFinding(
                id="no-weeks",
                severity="high",
                evidence="MacroPlan.weeks is empty.",
                consequence="There is no week-by-week plan to check or for the athlete to follow.",
                fix="Author at least one MacroWeek row before requesting a check.",
            )
        )
        return PlanCheckReport(verdict=_verdict_from_findings(findings), findings=findings)

    plan_start = weeks[0].week_start
    plan_end_exclusive = weeks[-1].week_start + timedelta(days=7)

    daily_loads_by_date = _spread_weekly_tss_to_daily(weeks)
    projection_end = max(plan_end_exclusive - timedelta(days=1), today)
    series = _project_ctl_atl_tsb(
        current_ctl, daily_loads_by_date, today, projection_end, current_atl=current_atl
    )
    series_by_date = {d: (ctl, atl, tsb) for d, ctl, atl, tsb in series}

    findings.extend(_check_uncovered_weeks(weeks, active_events, plan_start, plan_end_exclusive))
    findings.extend(_check_ctl_ramp(weeks, athlete, today))
    findings.extend(_check_recovery_cadence(weeks, athlete))
    taper_too_long_findings = _check_taper_too_long(weeks, active_events)
    taper_too_long_event_ids = frozenset(
        f.id[len("taper-too-long-"):] for f in taper_too_long_findings
    )
    findings.extend(taper_too_long_findings)
    findings.extend(
        _check_taper_and_race_day(
            weeks, active_events, series_by_date,
            taper_too_long_event_ids=taper_too_long_event_ids,
        )
    )
    findings.extend(_check_sustained_low_tsb(series))
    findings.extend(_check_hours_reality(weeks, recent_weekly_hours))
    findings.extend(_check_bc_races_labelled(weeks, active_events))
    findings.extend(_check_bike_weeks_missing_load(weeks, active_events))
    goal_finding = _check_goal_reality(plan, athlete, today)
    if goal_finding is not None:
        findings.append(goal_finding)

    findings = _rank_and_cap(findings)
    return PlanCheckReport(verdict=_verdict_from_findings(findings), findings=findings)


def _rank_and_cap(findings: list[PlanCheckFinding]) -> list[PlanCheckFinding]:
    ranked = sorted(findings, key=lambda f: _SEVERITY_ORDER[f.severity])
    return ranked[:MAX_FINDINGS]


def _verdict_from_findings(findings: list[PlanCheckFinding]) -> Verdict:
    n_high = sum(1 for f in findings if f.severity == "high")
    if n_high >= 2:
        return "not-feasible"
    if n_high == 1:
        return "fragile"
    if findings:
        return "sound-with-caveats"
    return "sound"


def _check_uncovered_weeks(
    weeks: list[MacroWeek],
    active_events: list[Event],
    plan_start: date,
    plan_end_exclusive: date,
) -> list[PlanCheckFinding]:
    """No gap in weekly coverage through the last active event's date
    (approved plan: "no uncovered weeks through the last active event").
    Flags every distinct gap week once; a gap that also contains an active
    event is called out by name and escalated to high severity."""
    if not active_events:
        last_event_date = plan_end_exclusive - timedelta(days=1)
    else:
        last_event_date = max(e.event_date for e in active_events)
    if last_event_date < plan_start:
        return []
    findings: list[PlanCheckFinding] = []
    cursor = plan_start
    while cursor <= last_event_date:
        week = _week_for_date(weeks, cursor)
        if week is None:
            events_in_gap = [
                e for e in active_events if cursor <= e.event_date < cursor + timedelta(days=7)
            ]
            if events_in_gap:
                names = ", ".join(f"{e.name} ({e.priority})" for e in events_in_gap)
                findings.append(
                    PlanCheckFinding(
                        id=f"uncovered-race-week-{cursor.isoformat()}",
                        severity="high",
                        evidence=(
                            f"No MacroWeek row covers {cursor.isoformat()}-"
                            f"{(cursor + timedelta(days=6)).isoformat()}, the week "
                            f"containing: {names}."
                        ),
                        consequence=(
                            "The athlete has no plan at all for race week -- the exact "
                            "week the whole campaign is aimed at."
                        ),
                        fix="Author a MacroWeek row for this week before the race.",
                    )
                )
            else:
                findings.append(
                    PlanCheckFinding(
                        id=f"uncovered-week-{cursor.isoformat()}",
                        severity="medium",
                        evidence=(
                            f"No MacroWeek row covers {cursor.isoformat()}-"
                            f"{(cursor + timedelta(days=6)).isoformat()}."
                        ),
                        consequence="A gap in the plan the athlete/coach has to fill blind.",
                        fix="Author a MacroWeek row for this week.",
                    )
                )
        cursor += timedelta(days=7)
    return findings


def _check_ctl_ramp(
    weeks: list[MacroWeek], athlete: Athlete, today: date
) -> list[PlanCheckFinding]:
    """Week-over-week `ctl_target` delta vs `CTL_RAMP_CAP_PER_WEEK`
    (lower for masters/injury-history athletes)."""
    age = _age_years(athlete.dob, today)
    cap = CTL_RAMP_CAP_PER_WEEK
    if (age is not None and age >= MASTERS_AGE_THRESHOLD):
        cap = CTL_RAMP_CAP_PER_WEEK_MASTERS_OR_INJURY
    worst_delta = 0.0
    worst_week: MacroWeek | None = None
    prev: MacroWeek | None = None
    for week in weeks:
        if prev is not None and prev.ctl_target is not None and week.ctl_target is not None:
            delta = week.ctl_target - prev.ctl_target
            if delta > worst_delta:
                worst_delta = delta
                worst_week = week
        prev = week
    if worst_week is not None and worst_delta > cap:
        return [
            PlanCheckFinding(
                id="ctl-ramp-too-steep",
                severity="medium",
                evidence=(
                    f"ctl_target rises by {worst_delta:.1f}/week into the week starting "
                    f"{worst_week.week_start.isoformat()}, above the {cap:.0f}/week cap."
                ),
                consequence="A ramp this steep risks overreaching before it's ever tested in a race.",
                fix="Spread the CTL gain over more weeks, or confirm explicitly with the athlete.",
            )
        ]
    return []


def _check_recovery_cadence(
    weeks: list[MacroWeek], athlete: Athlete
) -> list[PlanCheckFinding]:
    cadence = RECOVERY_CADENCE_WEEKS
    age = _age_years(athlete.dob, weeks[0].week_start) if weeks else None
    if age is not None and age >= MASTERS_AGE_THRESHOLD:
        cadence = RECOVERY_CADENCE_WEEKS_MASTERS_OR_INJURY
    run = 0
    worst_run = 0
    worst_week: MacroWeek | None = None
    for week in weeks:
        if week.recovery:
            run = 0
            continue
        run += 1
        if run > worst_run:
            worst_run = run
            worst_week = week
    if worst_run > cadence:
        assert worst_week is not None
        return [
            PlanCheckFinding(
                id="recovery-cadence",
                severity="low",
                evidence=(
                    f"{worst_run} consecutive non-recovery weeks through the week starting "
                    f"{worst_week.week_start.isoformat()}, above the {cadence}:1 cadence."
                ),
                consequence="Fatigue accumulates with no deliberate release valve.",
                fix="Insert a recovery week (recovery=True), or confirm the long run is intentional.",
            )
        ]
    return []


def _check_taper_and_race_day(
    weeks: list[MacroWeek],
    active_events: list[Event],
    series_by_date: dict[date, tuple[float, float, float]],
    *,
    taper_too_long_event_ids: frozenset[str] = frozenset(),
) -> list[PlanCheckFinding]:
    findings: list[PlanCheckFinding] = []
    a_events = [e for e in active_events if e.priority.strip().upper() == "A"]
    for event in a_events:
        findings.extend(_check_one_event_taper(weeks, event))
        tsb_reading = series_by_date.get(event.event_date)
        if tsb_reading is not None:
            _ctl, _atl, tsb = tsb_reading
            if not (RACE_DAY_TSB_BAND["low"] <= tsb <= RACE_DAY_TSB_BAND["high"]):
                # Too FRESH (above the band) that coincides with an already-
                # confirmed taper-too-long finding for this same event is
                # escalated to high -- the real 2026-09-27 failure was the
                # coach reading a merely-medium "TSB just outside band"
                # finding in isolation and reasoning it away ("too fresh is
                # a smaller risk than flat"); paired with the load-based
                # taper-too-long finding for the SAME event, this is no
                # longer an ambiguous single medium signal to argue with.
                # Too FATIGUED (below the band) stays medium regardless --
                # that direction isn't the failure mode this escalation
                # targets, and isn't what a too-long taper produces anyway.
                too_fresh = tsb > RACE_DAY_TSB_BAND["high"]
                severity: Severity = (
                    "high" if too_fresh and str(event.id) in taper_too_long_event_ids else "medium"
                )
                findings.append(
                    PlanCheckFinding(
                        id=f"race-day-tsb-{event.id}",
                        severity=severity,
                        evidence=(
                            f"Projected TSB on {event.event_date.isoformat()} ({event.name}) is "
                            f"{tsb:.1f}, outside the {RACE_DAY_TSB_BAND['low']:.0f} to "
                            f"{RACE_DAY_TSB_BAND['high']:.0f} race-day band (library/22)."
                            + (
                                " Coincides with a taper-too-long finding for this same race -- "
                                "not an ambiguous signal on its own."
                                if severity == "high"
                                else ""
                            )
                        ),
                        consequence="Racing too fresh (flat legs) or too fatigued (no snap) for the A race.",
                        fix="Adjust the taper depth/length so projected race-day TSB lands in-band.",
                    )
                )
    return findings


def _recent_build_peak(weeks_by_start: dict[date, MacroWeek], race_week_start: date) -> float | None:
    """Max real volume (`_week_volume`) over the `TAPER_BASELINE_LOOKBACK_WEEKS`
    weeks immediately before `race_week_start` -- the same recent-build-peak
    window `_check_one_event_taper` measures the race week's own cut
    against, reused here as the reference point for "how many of those
    weeks were already tapering." `None` when there's no usable data in the
    window (never a fabricated peak)."""
    candidates = [
        v
        for i in range(1, TAPER_BASELINE_LOOKBACK_WEEKS + 1)
        if (w := weeks_by_start.get(race_week_start - timedelta(weeks=i))) is not None
        and (v := _week_volume(w)) is not None
    ]
    return max(candidates) if candidates else None


def _consecutive_pre_race_tapered_weeks(weeks: list[MacroWeek], race_week: MacroWeek) -> int:
    """How many CONSECUTIVE weeks immediately before `race_week` already sit
    `TAPER_TOO_LONG_CUT_FRACTION` (20%) or more below the recent build peak
    -- i.e. how many weeks of the build window were already spent tapering
    before race week itself, as distinct from `_check_one_event_taper`'s
    "is race week's OWN cut deep enough" question. Walks backward from the
    week immediately before race week and stops at the first week that
    ISN'T already cut this much (a real build week), so an ordinary
    lighter week deep in the build isn't miscounted as part of a taper run.
    Returns 0 when there's no usable peak to measure against (never
    fabricates a reading)."""
    weeks_by_start = {w.week_start: w for w in weeks}
    peak = _recent_build_peak(weeks_by_start, race_week.week_start)
    if peak is None or peak <= 0:
        return 0
    run = 0
    i = 1
    while True:
        week = weeks_by_start.get(race_week.week_start - timedelta(weeks=i))
        if week is None:
            break
        volume = _week_volume(week)
        if volume is None:
            break
        if 1 - (volume / peak) < TAPER_TOO_LONG_CUT_FRACTION:
            break
        run += 1
        i += 1
    return run


def _check_taper_too_long(
    weeks: list[MacroWeek], active_events: list[Event]
) -> list[PlanCheckFinding]:
    """The real 2026-09-27 production failure: a plan can pass
    `_check_one_event_taper`'s "is race week's own cut deep enough" question
    while still spending weeks of the build window already tapering BEFORE
    race week ever arrives -- Sep 28 Taper, Oct 5 Taper, Oct 12 Race, the
    only race-free build window spent tapering instead of building. High
    severity, always, for a short event with ANY such week (Neary 2003,
    Houmard 1991 -- a multi-week taper buys a short event nothing extra and
    spends real build window); high beyond `LONG_EVENT_MAX_TAPER_WEEKS_BEFORE_RACE`
    (~2 weeks) for a long event (Bosquet 2007). Never fabricates a finding
    when there's no usable load data to judge (see
    `_consecutive_pre_race_tapered_weeks`)."""
    findings: list[PlanCheckFinding] = []
    a_events = [e for e in active_events if e.priority.strip().upper() == "A"]
    for event in a_events:
        race_week = _final_pre_race_week(weeks, event)
        if race_week is None:
            continue
        run = _consecutive_pre_race_tapered_weeks(weeks, race_week)
        if run <= 0:
            continue
        is_short = _event_hours(event) is not None and _event_hours(event) <= SHORT_EVENT_MAX_HOURS
        if is_short:
            too_long = True
            evidence_cite = (
                "Neary, Bhambhani & McKenzie (2003): only a 7-day, ~50% volume "
                "cut (intensity held) reached significance for a short event -- "
                "30%/80% cuts did not. Houmard (1991): fitness/performance holds "
                "10-28 days at volume cuts up to 70-80%. A multi-week taper buys "
                "a short event nothing extra and spends real build window "
                "(library/31, library/36)."
            )
            fix = "Keep build load until race week; taper within race week itself (~50% cut, intensity held)."
        else:
            too_long = run > LONG_EVENT_MAX_TAPER_WEEKS_BEFORE_RACE
            evidence_cite = (
                f"Bosquet et al. (2007): the optimal full taper is a ~2-week "
                f"exponential reduction (41-60% volume, intensity held) -- "
                f"{run} already-tapered week(s) sit before race week itself, "
                f"beyond that window (library/36)."
            )
            fix = "Shorten the taper toward Bosquet's ~2-week window; hold build load longer first."
        if not too_long:
            continue
        findings.append(
            PlanCheckFinding(
                id=f"taper-too-long-{event.id}",
                severity="high",
                evidence=(
                    f"{run} consecutive week(s) immediately before race week "
                    f"({race_week.week_start.isoformat()}, {event.name}) already sit "
                    f"{TAPER_TOO_LONG_CUT_FRACTION*100:.0f}%+ below the recent build peak. "
                    + evidence_cite
                ),
                consequence="Loses the build window, detraining risk, flat not fresh.",
                fix=fix,
            )
        )
    return findings


def _final_pre_race_week(weeks: list[MacroWeek], event: Event) -> MacroWeek | None:
    """The MacroWeek covering `event.event_date` -- for a Saturday/Sunday
    race this is the week most of the taper's final days actually fall in
    (Monday-Friday of race week, plus the race day itself), which is why
    this is compared against the recent build peak below, not the week
    strictly before it."""
    race_week_start = event.event_date - timedelta(days=event.event_date.weekday())
    return next((w for w in weeks if w.week_start == race_week_start), None)


def _week_volume(week: MacroWeek) -> float | None:
    """Volume proxy for the load-based taper check: `hours` when set
    (Neary et al.'s own studies measure a literal VOLUME cut, not a TSS
    figure), else `load_tss` as a fallback, else `None` -- never a
    fabricated number. `None` here is a real "no usable data," not a
    zero -- callers must skip rather than treat it as zero volume."""
    if week.hours is not None:
        return week.hours
    if week.load_tss is not None:
        return week.load_tss
    return None


def _check_one_event_taper(weeks: list[MacroWeek], event: Event) -> list[PlanCheckFinding]:
    """Whether the plan actually TAPERS into this event -- judged purely by
    the real load numbers (hours/load_tss), never by what the coach
    happened to name the phase (`MacroWeek.phase` is free text; a week
    literally never called "taper" can still taper correctly, and one
    called "taper" can fail to). Compares the race week's own volume
    against the recent build peak (`TAPER_BASELINE_LOOKBACK_WEEKS` back)
    and checks the resulting cut fraction against the evidence-based band
    for this event's duration (library/31).

    Silently skips (returns no finding) whenever there isn't enough real
    data to judge honestly: a missing race week is already flagged by
    `_check_uncovered_weeks` (high severity); a race week or every
    candidate baseline week with neither `hours` nor `load_tss` set is
    already flagged by `_check_bike_weeks_missing_load`. Padding a second,
    lower-confidence finding on top of either of those would violate this
    module's own "don't manufacture objections" discipline
    (`ai-coach/.claude/agents/red-team.md`).
    """
    race_week = _final_pre_race_week(weeks, event)
    if race_week is None:
        return []
    race_volume = _week_volume(race_week)
    if race_volume is None:
        return []

    weeks_by_start = {w.week_start: w for w in weeks}
    baseline_candidates = [
        v
        for i in range(1, TAPER_BASELINE_LOOKBACK_WEEKS + 1)
        if (w := weeks_by_start.get(race_week.week_start - timedelta(weeks=i))) is not None
        and (v := _week_volume(w)) is not None
    ]
    if not baseline_candidates:
        return []
    baseline = max(baseline_candidates)
    if baseline <= 0:
        return []

    cut_fraction = 1 - (race_volume / baseline)
    is_short = _event_hours(event) is not None and _event_hours(event) <= SHORT_EVENT_MAX_HOURS
    cut_min = SHORT_EVENT_TAPER_CUT_FRACTION_MIN if is_short else GENERAL_TAPER_CUT_FRACTION_MIN
    cut_max = SHORT_EVENT_TAPER_CUT_FRACTION_MAX if is_short else GENERAL_TAPER_CUT_FRACTION_MAX

    if cut_fraction < 0:
        return [
            PlanCheckFinding(
                id=f"taper-load-increased-{event.id}",
                severity="high",
                evidence=(
                    f"Race week ({race_week.week_start.isoformat()}) volume is HIGHER than the "
                    f"recent build peak ({race_volume:g} vs {baseline:g}) going into "
                    f"{event.name} ({event.event_date.isoformat()})."
                ),
                consequence="The athlete races carrying full (or rising) training fatigue, not freshness.",
                fix="Cut race week's volume below the recent build peak.",
            )
        ]
    if cut_fraction < cut_min:
        return [
            PlanCheckFinding(
                id=f"taper-insufficient-{event.id}",
                severity="medium",
                evidence=(
                    f"Race week volume is only {cut_fraction*100:.0f}% below the recent build peak "
                    f"({race_volume:g} vs {baseline:g}) going into {event.name} "
                    f"({event.event_date.isoformat()}); the evidence-based cut for this event is "
                    f"{cut_min*100:.0f}-{cut_max*100:.0f}%."
                ),
                consequence="A shallower-than-evidenced cut risks arriving under-tapered.",
                fix=f"Cut race week's volume {cut_min*100:.0f}-{cut_max*100:.0f}% below the recent build peak.",
            )
        ]
    if cut_fraction > cut_max:
        return [
            PlanCheckFinding(
                id=f"taper-too-deep-{event.id}",
                severity="low",
                evidence=(
                    f"Race week volume is {cut_fraction*100:.0f}% below the recent build peak "
                    f"({race_volume:g} vs {baseline:g}) going into {event.name} "
                    f"({event.event_date.isoformat()}); the evidence-based cut for this event is "
                    f"{cut_min*100:.0f}-{cut_max*100:.0f}%."
                ),
                consequence="An unnecessarily deep cut risks arriving flat/stale rather than sharp.",
                fix=f"Hold race week's volume closer to a {cut_min*100:.0f}-{cut_max*100:.0f}% cut.",
            )
        ]
    return []


def _event_hours(event: Event) -> float | None:
    if event.target_metric == "duration_min" and event.target_value is not None:
        return event.target_value / 60.0
    return None


def _check_sustained_low_tsb(
    series: list[tuple[date, float, float, float]]
) -> list[PlanCheckFinding]:
    run = 0
    worst_run = 0
    worst_start: date | None = None
    run_start: date | None = None
    for day, _ctl, _atl, tsb in series:
        if tsb < SUSTAINED_LOW_TSB_THRESHOLD:
            if run == 0:
                run_start = day
            run += 1
            if run > worst_run:
                worst_run = run
                worst_start = run_start
        else:
            run = 0
    if worst_run >= SUSTAINED_LOW_TSB_MIN_CONSECUTIVE_DAYS:
        return [
            PlanCheckFinding(
                id="sustained-low-tsb",
                severity="medium",
                evidence=(
                    f"Projected TSB stays below {SUSTAINED_LOW_TSB_THRESHOLD:.0f} for "
                    f"{worst_run} consecutive days starting {worst_start.isoformat()}."
                ),
                consequence="Extended deep fatigue without a planned release risks overreaching/illness.",
                fix="Insert a recovery week, or confirm this depth is deliberate and time-boxed.",
            )
        ]
    return []


def _check_hours_reality(
    weeks: list[MacroWeek], recent_weekly_hours: list[float]
) -> list[PlanCheckFinding]:
    if not recent_weekly_hours:
        return []
    ceiling = max(recent_weekly_hours)
    worst_week: MacroWeek | None = None
    worst_required = 0.0
    for week in weeks:
        if week.hours is None:
            continue
        required = week.hours * (1 + TIME_REALITY_BUFFER_FRACTION)
        if required > ceiling and required > worst_required:
            worst_required = required
            worst_week = week
    if worst_week is not None:
        return [
            PlanCheckFinding(
                id="hours-optimistic",
                severity="low",
                evidence=(
                    f"Week starting {worst_week.week_start.isoformat()} plans "
                    f"{worst_week.hours:.1f}h (~{worst_required:.1f}h with the "
                    f"{TIME_REALITY_BUFFER_FRACTION*100:.0f}% time-reality buffer), above the "
                    f"athlete's max sustained recent week ({ceiling:.1f}h)."
                ),
                consequence="Plans routinely take longer than they claim; this week is likely to slip.",
                fix="Trim the week's hours, or confirm the athlete genuinely has this much time free.",
            )
        ]
    return []


def _check_bc_races_labelled(
    weeks: list[MacroWeek], active_events: list[Event]
) -> list[PlanCheckFinding]:
    findings: list[PlanCheckFinding] = []
    for event in active_events:
        if event.priority.strip().upper() == "A":
            continue
        week = _week_for_date(weeks, event.event_date)
        if week is None:
            continue  # caught by _check_uncovered_weeks
        haystack = " ".join([week.notes or "", week.focus, *week.key_sessions]).lower()
        if event.name.lower() not in haystack and "race" not in haystack:
            findings.append(
                PlanCheckFinding(
                    id=f"bc-race-unlabelled-{event.id}",
                    severity="low",
                    evidence=(
                        f"{event.name} ({event.priority}) falls in the week starting "
                        f"{week.week_start.isoformat()}, which doesn't mention it or 'race'."
                    ),
                    consequence="The athlete may be surprised, or may over-taper for a training-stress race.",
                    fix="Note the B/C race explicitly in that week's key_sessions/notes.",
                )
            )
    return findings


def _check_bike_weeks_missing_load(
    weeks: list[MacroWeek], active_events: list[Event]
) -> list[PlanCheckFinding]:
    """The meters-for-bike defect: a bike-primary macro's week is
    meaningless if it carries neither hours nor load_tss -- bike load is
    not measured in meters (see the approved plan's context section:
    "bike volume in 'meters' (actually minutes)")."""
    is_bike_macro = any(e.primary_sport == "bike" for e in active_events)
    if not is_bike_macro:
        return []
    offending = [w for w in weeks if w.hours is None and w.load_tss is None]
    if not offending:
        return []
    dates = ", ".join(w.week_start.isoformat() for w in offending[:3])
    more = f" (+{len(offending) - 3} more)" if len(offending) > 3 else ""
    return [
        PlanCheckFinding(
            id="bike-weeks-missing-load",
            severity="high",
            evidence=f"{len(offending)} week(s) with neither hours nor load_tss set: {dates}{more}.",
            consequence=(
                "These weeks carry no usable training-load number at all -- CTL/TSB "
                "projections and ramp checks silently skip them (treated as zero load)."
            ),
            fix="Set hours and/or load_tss for every bike week; never record bike volume in meters.",
        )
    ]


_GOAL_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*W\s*/\s*kg", re.IGNORECASE)


def _check_goal_reality(
    plan: MacroPlan, athlete: Athlete, today: date
) -> PlanCheckFinding | None:
    """Implied rate of progress to a stated W/kg goal vs. a research-based
    (here: PROVISIONAL placeholder, see constants above) progression rate
    and the athlete's age -- "the clock runs out first" framing from the
    approved plan. The goal is read from `plan.architecture`'s free text
    (Coach judgment: no structured goal field exists yet on any model;
    `architecture` is the coach's own written rationale, a natural place
    to state a numeric target -- PR 3 may add a dedicated field)."""
    if not plan.architecture or athlete.ftp_watts is None or athlete.weight_kg is None:
        return None
    match = _GOAL_PATTERN.search(plan.architecture)
    if match is None:
        return None
    goal_wkg = float(match.group(1))
    current_wkg = athlete.ftp_watts / athlete.weight_kg
    if goal_wkg <= current_wkg:
        return None
    age = _age_years(athlete.dob, today)
    decline = MASTERS_ANNUAL_DECLINE_FRACTION if (age is not None and age >= MASTERS_AGE_THRESHOLD) else 0.0
    net_annual_gain = MAX_REALISTIC_ANNUAL_GAIN_FRACTION - decline
    required_fraction = (goal_wkg - current_wkg) / current_wkg
    age_display = f"{age:.0f}" if age is not None else "unknown"
    if net_annual_gain <= 0:
        return PlanCheckFinding(
            id="goal-reality-check",
            severity="medium",
            evidence=(
                f"Goal {goal_wkg:.1f} W/kg from {current_wkg:.1f} W/kg at age "
                f"{age_display}: age-related decline "
                f"({decline*100:.0f}%/yr) meets or exceeds the realistic gain rate "
                f"({MAX_REALISTIC_ANNUAL_GAIN_FRACTION*100:.0f}%/yr, PROVISIONAL placeholder)."
            ),
            consequence="This goal cannot be reached at any horizon at the current age on these assumptions.",
            fix="Set a less aggressive goal, or revisit once PR 3's progression-rate research lands.",
        )
    years_needed = required_fraction / net_annual_gain
    if years_needed <= GOAL_REALITY_CHECK_HORIZON_YEARS:
        return None
    estimated_date = today + timedelta(days=round(years_needed * 365))
    return PlanCheckFinding(
        id="goal-reality-check",
        severity="medium",
        evidence=(
            f"Goal {goal_wkg:.1f} W/kg from {current_wkg:.1f} W/kg needs "
            f"~{years_needed:.1f} years at a {net_annual_gain*100:.1f}%/yr net realistic "
            f"gain rate (PROVISIONAL placeholder, PR 3 to replace) -- beyond the "
            f"{GOAL_REALITY_CHECK_HORIZON_YEARS:.0f}-year horizon this check treats as reasonable."
        ),
        consequence=(
            f"The clock runs out first: on these assumptions the goal isn't reached until "
            f"roughly {estimated_date.isoformat()}."
        ),
        fix="Set an interim, reachable goal for this season; revisit the long-range target yearly.",
    )


# ============================================================================
# check_week
# ============================================================================


def check_week(
    week: WeekPlan,
    macro_week: MacroWeek | None,
    athlete: Athlete,
    *,
    recent_weeks: list[WeekPlan],
) -> PlanCheckReport:
    """Red-team one coach-authored WEEK of real `Session`s against its
    macro row and recent history. Never raises. `+8%` volume / `+15%`
    long-swim flags are `requires_athlete_confirmation` advisories (id
    prefix `confirm-`), never clamps -- CLAUDE.md's safety rail already
    requires explicit athlete confirmation past these thresholds; this
    function surfaces that requirement, it does not enforce it."""
    findings: list[PlanCheckFinding] = []

    if macro_week is not None:
        projected_total = sum(session_target_load_au(s, athlete) for s in week.sessions)
        if macro_week.load_tss is not None and macro_week.load_tss > 0:
            delta_pct = (projected_total / macro_week.load_tss - 1) * 100
            if abs(delta_pct) > 20.0:
                findings.append(
                    PlanCheckFinding(
                        id="week-tss-mismatch",
                        severity="low",
                        evidence=(
                            f"This week's sessions project to {projected_total:.0f} AU vs. "
                            f"the macro row's {macro_week.load_tss:.0f} TSS ({delta_pct:+.0f}%)."
                        ),
                        consequence="The week's real sessions don't match what the macro promised.",
                        fix="Reconcile the week's sessions with the macro row, or update the macro.",
                    )
                )

    bike_sessions = [s for s in week.sessions if s.sport == "bike"]
    if bike_sessions:
        prev_bike_volume = None
        if recent_weeks:
            last = recent_weeks[-1]
            last_bike = [s for s in last.sessions if s.sport == "bike"]
            if last_bike:
                prev_bike_volume = sum(s.duration_min for s in last_bike)
        for i, warning in enumerate(
            evaluate_week_realism(week.sessions, prev_week_bike_volume_min=prev_bike_volume)
        ):
            findings.append(
                PlanCheckFinding(
                    id=f"week-realism-{i}",
                    severity="medium",
                    evidence=warning,
                    consequence="Unrealistic session mix tends to get abandoned mid-week.",
                    fix="See evidence above (plan.evaluate_week_realism).",
                )
            )

    if week.sessions:
        hard_count = sum(1 for s in week.sessions if _is_hard_session(s))
        fraction = hard_count / len(week.sessions)
        if fraction > POLARIZED_MAX_HARD_SESSION_FRACTION:
            findings.append(
                PlanCheckFinding(
                    id="polarization",
                    severity="low",
                    evidence=(
                        f"{hard_count}/{len(week.sessions)} sessions this week are hard "
                        f"(Z4/Z5), above the polarized {POLARIZED_MAX_HARD_SESSION_FRACTION*100:.0f}% share."
                    ),
                    consequence="A grey-zone week plateaus performance (library/24, Seiler polarized distribution).",
                    fix="Move an extra hard session to easy endurance.",
                )
            )

    findings.extend(_check_week_volume_confirmation(week, recent_weeks))

    findings = _rank_and_cap(findings)
    return PlanCheckReport(verdict=_verdict_from_findings(findings), findings=findings)


def _check_week_volume_confirmation(
    week: WeekPlan, recent_weeks: list[WeekPlan]
) -> list[PlanCheckFinding]:
    if not recent_weeks:
        return []
    findings: list[PlanCheckFinding] = []
    prev = recent_weeks[-1]
    if prev.target_volume_m > 0:
        growth = week.target_volume_m / prev.target_volume_m - 1
        if growth > WEEKLY_VOLUME_RAMP_CAP:
            findings.append(
                PlanCheckFinding(
                    id="confirm-weekly-volume-ramp",
                    severity="low",
                    evidence=(
                        f"target_volume_m {week.target_volume_m} is +{growth*100:.0f}% over last "
                        f"week ({prev.target_volume_m}), past the "
                        f"+{WEEKLY_VOLUME_RAMP_CAP*100:.0f}%/week safety rail (CLAUDE.md)."
                    ),
                    consequence="Requires explicit athlete confirmation per CLAUDE.md's safety rail.",
                    fix="Confirm with the athlete, or spread the increase over more weeks.",
                )
            )

    def _longest_swim_m(w: WeekPlan) -> int:
        swim = [s for s in w.sessions if s.sport in {"swim_pool", "swim_ow"} and s.distance_m]
        return max((s.distance_m for s in swim), default=0)

    this_longest = _longest_swim_m(week)
    prev_longest = _longest_swim_m(prev)
    if prev_longest > 0 and this_longest > 0:
        growth = this_longest / prev_longest - 1
        if growth > SINGLE_SESSION_STEP_CAP:
            findings.append(
                PlanCheckFinding(
                    id="confirm-long-swim-step",
                    severity="low",
                    evidence=(
                        f"Longest swim {this_longest}m is +{growth*100:.0f}% over last week's "
                        f"{prev_longest}m, past the +{SINGLE_SESSION_STEP_CAP*100:.0f}% cap "
                        "(library/06-long-swim-progression.md)."
                    ),
                    consequence="Requires explicit athlete confirmation per CLAUDE.md's safety rail.",
                    fix="Confirm with the athlete, or step the long swim up more gradually.",
                )
            )
    return findings
