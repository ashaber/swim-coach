"""Deterministic plan projection and side-by-side scenario comparison.

Projects LOAD and FRESHNESS (CTL / ATL / TSB) and runs the existing
`plan_check` findings over a hypothetical training scenario, an authored macro
plan, or alternative orderings of one week. It never predicts performance
(watts, pace) and never names a winner: a comparison is per-metric rows plus
plain trade-off sentences quoting the numbers. Pure functions and pydantic
models; no I/O, no LLM, no network.

Every default constant below is `Coach judgment:`, documented and marked for
human review in `library/49-plan-projection.md`.
"""

from __future__ import annotations

import itertools
import statistics
import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from pydantic import BaseModel, ConfigDict, Field, model_validator

from swim_coach.load import (
    estimate_hr_max,
    estimate_hr_rest,
    monotony,
    session_load,
    session_target_load_au,
)
from swim_coach.models import Athlete, Event, MacroPlan, MacroWeek, PlanCheckFinding, WeekPlan, Workout, Wellness
from swim_coach.plan_check import (
    MASTERS_AGE_THRESHOLD,
    RECOVERY_CADENCE_WEEKS,
    RECOVERY_CADENCE_WEEKS_MASTERS_OR_INJURY,
    SUSTAINED_LOW_TSB_THRESHOLD,
    PlanCheckReport,
    _age_years,
    _is_hard_session,
    _project_ctl_atl_tsb,
    _spread_weekly_tss_to_daily,
    check_macro,
    check_week,
)

# Coach judgment: library/49-plan-projection.md ("Defaults for a scenario week").
RECOVERY_WEEK_REDUCTION_DEFAULT = 0.30
LONG_SESSION_DAY_OFFSET = 6  # Monday = 0; the longest session sits on Sunday
# Coach judgment: library/49-plan-projection.md ("Easy and hard load per hour").
HARD_WORKOUT_RPE_MIN = 7
MIN_WORKOUTS_PER_INTENSITY_BUCKET = 3
HOURS_PER_DAY = 24.0
STRENGTH_SPORT = "strength"

COMPARISON_LIMITS: list[str] = [
    "Load and freshness only: CTL, ATL, TSB and plan-check findings are projected from planned hours and the athlete's own recent load per hour.",
    "No performance prediction: nothing here estimates watts, pace or race result.",
    "The recovery cost of extra training days beyond load (sleep, life stress) is not modelled.",
]
SEQUENCE_LIMITS: list[str] = [
    *COMPARISON_LIMITS,
    "Sessions carry a date but no clock time, so hours between sessions are whole days times 24.",
]
_NAMESPACE = uuid.UUID("5d2f3c1e-7a1b-4c53-9a39-3c6f0d1b0a49")


# --- scenario input -----------------------------------------------------------------


class TrainingScenario(BaseModel):
    """A hypothetical, sport-neutral training pattern repeated week after week."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    days_per_week: int = Field(ge=1, le=7)
    hours_per_week: float = Field(gt=0)
    hard_sessions_per_week: int = Field(default=2, ge=0)
    long_session_share: float | None = Field(default=None, gt=0, le=1)
    recovery_week_every: int | None = Field(default=None, ge=1)
    recovery_week_reduction: float = Field(default=RECOVERY_WEEK_REDUCTION_DEFAULT, ge=0, lt=1)
    weekly_hours_ramp: float = Field(default=0.0, ge=-0.5, le=0.5)
    taper_weeks: int = Field(default=0, ge=0)
    taper_reduction: float | None = Field(default=None, gt=0, lt=1)

    @model_validator(mode="after")
    def _check_consistency(self) -> TrainingScenario:
        if self.hard_sessions_per_week > self.days_per_week:
            raise ValueError("hard_sessions_per_week cannot exceed days_per_week")
        if self.long_session_share is not None and self.long_session_share < 1 / self.days_per_week:
            raise ValueError(
                "long_session_share must be at least 1/days_per_week, or it is not the longest session"
            )
        if self.taper_weeks > 0 and self.taper_reduction is None:
            raise ValueError("taper_reduction is required when taper_weeks > 0")
        if self.taper_weeks == 0 and self.taper_reduction is not None:
            raise ValueError("taper_reduction needs taper_weeks > 0")
        return self

    @property
    def effective_hard_sessions(self) -> int:
        """Hard sessions that fit: never on the long-session day."""
        return min(self.hard_sessions_per_week, self.days_per_week - 1)


# --- placement ----------------------------------------------------------------------


def training_day_offsets(days: int) -> list[int]:
    """Weekday offsets (Mon=0) of `days` training days, spread as evenly as 7 slots allow,
    always including the long-session day (Sunday). Remaining days are rest days."""
    return sorted({LONG_SESSION_DAY_OFFSET - int(i * 7 / days + 0.5) for i in range(days)})


def _circular_gaps(offsets: tuple[int, ...]) -> list[int]:
    gaps = [b - a for a, b in zip(offsets, offsets[1:])]
    gaps.append(offsets[0] + 7 - offsets[-1])
    return gaps


def _distance_to_long_day(offset: int) -> int:
    straight = abs(offset - LONG_SESSION_DAY_OFFSET)
    return min(straight, 7 - straight)


def hard_day_offsets(training_offsets: list[int], hard: int) -> list[int]:
    """Choose `hard` offsets (never the long-session day) maximising the smallest
    circular gap between hard days, then their smallest distance from the long day;
    remaining ties go to the earliest offsets."""
    if hard <= 0:
        return []
    pool = [o for o in training_offsets if o != LONG_SESSION_DAY_OFFSET]
    best: tuple[int, ...] | None = None
    best_score: tuple[int, int] = (-1, -1)
    for combo in itertools.combinations(pool, hard):
        gap = 7 if hard == 1 else min(_circular_gaps(combo))
        score = (gap, min(_distance_to_long_day(o) for o in combo))
        if score > best_score:
            best, best_score = combo, score
    return list(best or ())


@dataclass(frozen=True)
class DayPlan:
    offset: int
    hours: float
    hard: bool


def week_day_plan(scenario: TrainingScenario, week_hours: float) -> list[DayPlan]:
    """Placement rule: training days are spread evenly over the week with the longest
    session on Sunday; hard sessions are spaced as far apart as the days allow and never
    sit on the long day; other days are rest. The long day gets `long_session_share` of
    the hours (even split when None) and the rest share the remainder equally."""
    offsets = training_day_offsets(scenario.days_per_week)
    hard = set(hard_day_offsets(offsets, scenario.effective_hard_sessions))
    share = scenario.long_session_share
    long_hours = week_hours * (share if share is not None else 1 / scenario.days_per_week)
    if scenario.days_per_week == 1:
        long_hours = week_hours
    other_hours = (week_hours - long_hours) / max(scenario.days_per_week - 1, 1)
    return [
        DayPlan(o, long_hours if o == LONG_SESSION_DAY_OFFSET else other_hours, o in hard)
        for o in offsets
    ]


def _day_load(day: DayPlan, easy: float, hard: float) -> float:
    return day.hours * (hard if day.hard else easy)


# --- scenario -> weeks and days ------------------------------------------------------


def default_recovery_cadence(athlete: Athlete, as_of: date) -> int:
    """The cadence `check_macro` applies: 3:1, or 2:1 for athletes at the masters age."""
    age = _age_years(athlete.dob, as_of)
    if age is not None and age >= MASTERS_AGE_THRESHOLD:
        return RECOVERY_CADENCE_WEEKS_MASTERS_OR_INJURY
    return RECOVERY_CADENCE_WEEKS


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _week_shape(
    scenario: TrainingScenario, index: int, total: int, cadence: int
) -> tuple[float, str]:
    """(planned hours, phase) for week `index` of `total`."""
    hours = scenario.hours_per_week * (1 + scenario.weekly_hours_ramp) ** index
    if scenario.taper_weeks and index >= total - scenario.taper_weeks:
        return hours * (1 - (scenario.taper_reduction or 0.0)), "taper"
    if (index + 1) % (cadence + 1) == 0:
        return hours * (1 - scenario.recovery_week_reduction), "recovery"
    return hours, "build"


def scenario_weeks(
    scenario: TrainingScenario,
    *,
    start: date,
    end: date,
    tss_per_hour_easy: float,
    tss_per_hour_hard: float,
    default_cadence: int = RECOVERY_CADENCE_WEEKS,
) -> list[MacroWeek]:
    """Week-by-week table from the Monday on or before `start` through the week holding
    `end`: ramp, then taper (last `taper_weeks`), else recovery weeks every
    `recovery_week_every` (default `default_cadence`) builds. `load_tss` is the sum of the
    placed daily loads, so weekly and daily views always agree."""
    cadence = scenario.recovery_week_every or default_cadence
    first = _monday(start)
    total = (_monday(end) - first).days // 7 + 1
    weeks: list[MacroWeek] = []
    for index in range(total):
        hours, phase = _week_shape(scenario, index, total, cadence)
        load = sum(_day_load(d, tss_per_hour_easy, tss_per_hour_hard) for d in week_day_plan(scenario, hours))
        weeks.append(
            MacroWeek(
                week_start=first + timedelta(weeks=index),
                phase=phase,
                focus=scenario.name,
                hours=hours,
                load_tss=load,
                recovery=phase == "recovery",
            )
        )
    return weeks


def scenario_daily_loads(
    scenario: TrainingScenario,
    weeks: list[MacroWeek],
    *,
    tss_per_hour_easy: float,
    tss_per_hour_hard: float,
) -> dict[date, float]:
    """Load per training day under the placement rule in `week_day_plan`; rest days absent."""
    loads: dict[date, float] = {}
    for week in weeks:
        for day in week_day_plan(scenario, week.hours or 0.0):
            loads[week.week_start + timedelta(days=day.offset)] = _day_load(
                day, tss_per_hour_easy, tss_per_hour_hard
            )
    return loads


def scenario_hard_days(scenario: TrainingScenario, weeks: list[MacroWeek]) -> list[date]:
    """Dates carrying a hard session, in order."""
    return sorted(
        week.week_start + timedelta(days=d.offset)
        for week in weeks
        for d in week_day_plan(scenario, week.hours or 0.0)
        if d.hard
    )


def split_load_per_hour(
    workouts: list[Workout],
    as_of: date,
    *,
    athlete: Athlete | None = None,
    wellness: list[Wellness] | None = None,
    weeks: int = 12,
) -> tuple[float, float] | None:
    """(easy, hard) median load per hour over the trailing `weeks`: a workout with RPE >=
    `HARD_WORKOUT_RPE_MIN` is hard, any other RPE-logged workout easy. None unless each
    bucket holds `MIN_WORKOUTS_PER_INTENSITY_BUCKET` workouts."""
    window_start = _monday(as_of) - timedelta(weeks=weeks)
    window_end = _monday(as_of) + timedelta(days=7)
    wellness = wellness or []
    hr_max = estimate_hr_max(workouts)
    buckets: dict[bool, list[float]] = {True: [], False: []}
    for w in workouts:
        if w.rpe is None or not window_start <= w.date < window_end:
            continue
        value = session_load(
            w,
            hr_max=hr_max,
            hr_rest=estimate_hr_rest(wellness, w.date),
            sex=athlete.sex if athlete else None,
            css_pace_s_per_100m=athlete.css_pace_s_per_100m if athlete else None,
            lthr_bpm=athlete.lthr_bpm if athlete else None,
            ftp_watts=athlete.ftp_watts if athlete else None,
        ).value
        buckets[w.rpe >= HARD_WORKOUT_RPE_MIN].append(value / (w.duration_min / 60.0))
    if min(len(buckets[True]), len(buckets[False])) < MIN_WORKOUTS_PER_INTENSITY_BUCKET:
        return None
    return statistics.median(buckets[False]), statistics.median(buckets[True])


# --- projection result models --------------------------------------------------------


class EventMetric(BaseModel):
    name: str
    date: date
    ctl: float
    tsb: float


class Metric(BaseModel):
    key: str
    label: str
    unit: str
    value: float | None


class ScenarioProjection(BaseModel):
    """Projected load and freshness for one scenario or authored plan."""

    name: str
    weeks: list[MacroWeek]
    series: list[tuple[date, float, float, float]]
    ctl_end: float
    tsb_end: float
    event_metrics: list[EventMetric]
    peak_ctl_ramp_per_week: float | None
    days_below_tsb_threshold: int
    mean_weekly_monotony: float | None
    total_hours: float
    hard_session_count: int | None
    min_hours_between_hard: float | None
    verdict: str
    findings: list[PlanCheckFinding]
    goal_findings: list[PlanCheckFinding]
    assumptions: list[str]

    def metrics(self) -> list[Metric]:
        """The comparable metrics, each as a labelled number (no judgement attached)."""
        rows = [
            Metric(key="ctl_end", label="CTL at end of projection", unit="", value=self.ctl_end),
            Metric(key="tsb_end", label="TSB at end of projection", unit="", value=self.tsb_end),
            Metric(key="peak_ctl_ramp_per_week", label="Peak weekly CTL ramp", unit="/wk", value=self.peak_ctl_ramp_per_week),
            Metric(key="days_below_tsb_threshold", label=f"Days with TSB below {SUSTAINED_LOW_TSB_THRESHOLD:.0f}", unit="days", value=float(self.days_below_tsb_threshold)),
            Metric(key="mean_weekly_monotony", label="Mean weekly monotony", unit="", value=self.mean_weekly_monotony),
            Metric(key="total_hours", label="Total planned hours", unit="h", value=self.total_hours),
            Metric(key="hard_session_count", label="Hard sessions", unit="", value=None if self.hard_session_count is None else float(self.hard_session_count)),
            Metric(key="min_hours_between_hard", label="Minimum hours between hard sessions", unit="h", value=self.min_hours_between_hard),
            Metric(key="finding_count", label="Plan-check findings", unit="", value=float(len(self.findings))),
        ]
        for event in self.event_metrics:
            rows.append(Metric(key=f"ctl_on:{event.name}", label=f"CTL on {event.name}", unit="", value=event.ctl))
            rows.append(Metric(key=f"tsb_on:{event.name}", label=f"TSB on {event.name}", unit="", value=event.tsb))
        return rows

    def to_summary(self) -> dict:
        """JSON-friendly view without the daily series."""
        return self.model_dump(mode="json", exclude={"series"})


# --- projection ---------------------------------------------------------------------


@dataclass(frozen=True)
class _Inputs:
    athlete: Athlete
    current_ctl: float
    current_atl: float | None
    start: date
    end: date
    events: list[Event]
    recent_weekly_hours: list[float]
    recent_tss_per_hour: float | None
    today: date


def _resolve_rates(
    easy: float | None, hard: float | None, blended: float | None
) -> tuple[float, float, list[str]]:
    """Easy/hard load per hour, falling back to the blended figure for both."""
    if easy is not None and hard is not None:
        return easy, hard, []
    if blended is None:
        raise ValueError("no load per hour available: the athlete has no recent logged workouts to derive it from")
    note = (
        f"Easy and hard sessions both use the blended recent load per hour ({blended:.1f} AU/h): "
        "no easy/hard split was available, so a hard session carries no extra load per hour "
        "and day placement changes only day-to-day variation."
    )
    return blended, blended, [note]


def _event_metrics(series: list[tuple[date, float, float, float]], events: list[Event]) -> tuple[list[EventMetric], list[str]]:
    by_date = {d: (ctl, tsb) for d, ctl, _atl, tsb in series}
    metrics: list[EventMetric] = []
    notes: list[str] = []
    for event in sorted((e for e in events if e.active), key=lambda e: e.event_date):
        if event.event_date in by_date:
            ctl, tsb = by_date[event.event_date]
            metrics.append(EventMetric(name=event.name, date=event.event_date, ctl=ctl, tsb=tsb))
        else:
            notes.append(f"Event {event.name} ({event.event_date.isoformat()}) falls outside the projection window and has no CTL/TSB figure.")
    return metrics, notes


def _peak_weekly_ramp(series: list[tuple[date, float, float, float]], current_ctl: float) -> float | None:
    """Largest CTL gain across consecutive full 7-day blocks, the first measured from `current_ctl`."""
    ends = [series[i][1] for i in range(6, len(series), 7)]
    if not ends:
        return None
    return max(b - a for a, b in zip([current_ctl, *ends], ends))


def _mean_weekly_monotony(weeks: list[MacroWeek], loads: dict[date, float], ctx: _Inputs) -> float | None:
    values: list[float] = []
    for week in weeks:
        days = [week.week_start + timedelta(days=i) for i in range(7)]
        if days[0] < ctx.start or days[-1] > ctx.end:
            continue
        m = monotony({d: loads.get(d, 0.0) for d in days})
        if m is not None:
            values.append(m)
    return statistics.mean(values) if values else None


def _min_hours_between(hard_days: list[date]) -> float | None:
    if len(hard_days) < 2:
        return None
    return min((b - a).days for a, b in zip(hard_days, hard_days[1:])) * HOURS_PER_DAY


def _with_ctl_targets(weeks: list[MacroWeek], series: list[tuple[date, float, float, float]]) -> list[MacroWeek]:
    """Fill `ctl_target` with the projected CTL at each week's last projected day so the
    ramp check reads the projection rather than nothing."""
    by_date = {d: ctl for d, ctl, _atl, _tsb in series}
    out = []
    for week in weeks:
        last = week.week_start + timedelta(days=6)
        target = by_date.get(last)
        out.append(week.model_copy(update={"ctl_target": target}) if target is not None else week)
    return out


def _run_check(plan: MacroPlan, ctx: _Inputs) -> PlanCheckReport:
    return check_macro(
        plan,
        ctx.athlete,
        current_ctl=ctx.current_ctl,
        current_atl=ctx.current_atl,
        recent_weekly_hours=ctx.recent_weekly_hours,
        recent_tss_per_hour=ctx.recent_tss_per_hour,
        events=ctx.events,
        today=ctx.today,
    )


def _common_assumptions(ctx: _Inputs) -> list[str]:
    notes = [
        "Weeks start on Monday; days before the start date are not projected.",
        "Race and event loads are not added; load comes only from the planned hours.",
        "Plan-check findings come from check_macro, which projects each week's load spread evenly over 7 days, so its TSB-based findings can differ slightly from the daily-placed series here.",
    ]
    if ctx.current_atl is None:
        notes.append("Current ATL was not supplied, so TSB is assumed to be 0 at the start.")
    return notes


def _assemble(
    name: str,
    weeks: list[MacroWeek],
    loads: dict[date, float],
    hard_days: list[date] | None,
    plan: MacroPlan,
    ctx: _Inputs,
    assumptions: list[str],
) -> ScenarioProjection:
    series = _project_ctl_atl_tsb(ctx.current_ctl, loads, ctx.start, ctx.end, current_atl=ctx.current_atl)
    events, event_notes = _event_metrics(series, ctx.events)
    report = _run_check(plan, ctx)
    in_range = [d for d in (hard_days or []) if ctx.start <= d <= ctx.end]
    return ScenarioProjection(
        name=name,
        weeks=weeks,
        series=series,
        ctl_end=series[-1][1],
        tsb_end=series[-1][3],
        event_metrics=events,
        peak_ctl_ramp_per_week=_peak_weekly_ramp(series, ctx.current_ctl),
        days_below_tsb_threshold=sum(1 for *_x, tsb in series if tsb < SUSTAINED_LOW_TSB_THRESHOLD),
        mean_weekly_monotony=_mean_weekly_monotony(weeks, loads, ctx),
        total_hours=sum(w.hours or 0.0 for w in weeks),
        hard_session_count=None if hard_days is None else len(in_range),
        min_hours_between_hard=None if hard_days is None else _min_hours_between(in_range),
        verdict=report.verdict,
        findings=report.findings,
        goal_findings=[f for f in report.findings if f.id == "goal-reality-check"],
        assumptions=[*assumptions, *_common_assumptions(ctx), *event_notes],
    )


def project_scenario(
    scenario: TrainingScenario,
    athlete: Athlete,
    *,
    current_ctl: float,
    current_atl: float | None,
    start: date,
    end: date,
    events: list[Event],
    recent_weekly_hours: list[float],
    recent_tss_per_hour: float | None,
    today: date,
    tss_per_hour_easy: float | None = None,
    tss_per_hour_hard: float | None = None,
    architecture: str | None = None,
) -> ScenarioProjection:
    """Project `scenario` from `start` to `end`. Easy/hard load per hour default to the
    blended `recent_tss_per_hour` (recorded in `assumptions`). `architecture` is free text a
    stated goal is read from, so `goal_findings` can fire."""
    ctx = _Inputs(athlete, current_ctl, current_atl, start, end, events, recent_weekly_hours, recent_tss_per_hour, today)
    easy, hard, assumptions = _resolve_rates(tss_per_hour_easy, tss_per_hour_hard, recent_tss_per_hour)
    weeks = scenario_weeks(
        scenario, start=start, end=end, tss_per_hour_easy=easy, tss_per_hour_hard=hard,
        default_cadence=default_recovery_cadence(athlete, start),
    )
    loads = scenario_daily_loads(scenario, weeks, tss_per_hour_easy=easy, tss_per_hour_hard=hard)
    series = _project_ctl_atl_tsb(current_ctl, loads, start, end, current_atl=current_atl)
    weeks = _with_ctl_targets(weeks, series)
    if scenario.effective_hard_sessions < scenario.hard_sessions_per_week:
        assumptions.append("Hard sessions were capped at days_per_week - 1: none sits on the long-session day.")
    assumptions.append("Hard-session count per week is unchanged in recovery and taper weeks; only hours shrink.")
    assumptions.append("ctl_target on each scenario week is filled from this projection, so the ramp check reads the projected CTL.")
    event_id = next((e.id for e in events if e.active), athlete.id)
    plan = MacroPlan(
        id=uuid.uuid5(_NAMESPACE, scenario.name), athlete_id=athlete.id, event_id=event_id,
        weeks=weeks, architecture=architecture,
    )
    return _assemble(scenario.name, weeks, loads, scenario_hard_days(scenario, weeks), plan, ctx, assumptions)


def project_macro(
    macro: MacroPlan,
    athlete: Athlete,
    *,
    current_ctl: float,
    current_atl: float | None,
    start: date,
    end: date | None = None,
    events: list[Event],
    recent_weekly_hours: list[float],
    recent_tss_per_hour: float | None,
    today: date,
    name: str = "Current plan",
) -> ScenarioProjection:
    """Project an authored macro the way `check_macro` does (each week's load spread evenly
    over its 7 days), so it can be compared beside hypothetical scenarios."""
    weeks = sorted(macro.weeks, key=lambda w: w.week_start)
    if not weeks:
        raise ValueError("macro plan has no weeks to project")
    end = end or weeks[-1].week_start + timedelta(days=6)
    ctx = _Inputs(athlete, current_ctl, current_atl, start, end, events, recent_weekly_hours, recent_tss_per_hour, today)
    loads, estimated, unresolved = _spread_weekly_tss_to_daily(weeks, recent_tss_per_hour)
    assumptions = [
        "Each authored week's load is spread evenly over its 7 days, so hard-session count, spacing and monotony are not available for an authored macro.",
    ]
    if estimated:
        assumptions.append(f"{len(estimated)} week(s) had hours but no load_tss and use hours x recent load per hour.")
    if unresolved:
        assumptions.append(f"{len(unresolved)} week(s) have neither load_tss nor a usable hours estimate and project as no load.")
    return _assemble(name, weeks, loads, None, macro, ctx, assumptions)


# --- comparison ---------------------------------------------------------------------


class ComparisonRow(BaseModel):
    key: str
    label: str
    unit: str
    values: dict[str, float | None]
    difference_vs_first: dict[str, float | None]


class ScenarioComparison(BaseModel):
    """Per-metric rows and trade-off sentences. Never ranks or names a winner."""

    names: list[str]
    rows: list[ComparisonRow]
    tradeoffs: list[str]
    limits: list[str]
    findings: dict[str, list[str]]
    assumptions: dict[str, list[str]]


def _rows(per_name: dict[str, list[Metric]]) -> list[ComparisonRow]:
    names = list(per_name)
    keys: dict[str, Metric] = {}
    for metrics in per_name.values():
        for m in metrics:
            keys.setdefault(m.key, m)
    rows = []
    for key, proto in keys.items():
        values = {n: next((m.value for m in per_name[n] if m.key == key), None) for n in names}
        base = values[names[0]]
        diff = {n: None if v is None or base is None else v - base for n, v in values.items()}
        rows.append(ComparisonRow(key=key, label=proto.label, unit=proto.unit, values=values, difference_vs_first=diff))
    return rows


def _fmt(value: float | None, digits: int = 0) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _day_count_clause(a: int, b: int) -> str:
    if a == b:
        return f"the same {a} days below TSB {SUSTAINED_LOW_TSB_THRESHOLD:.0f}"
    word = "more" if a > b else "fewer"
    return f"{abs(a - b)} {word} days below TSB {SUSTAINED_LOW_TSB_THRESHOLD:.0f}"


def _end_sentence(a: ScenarioProjection, b: ScenarioProjection) -> str:
    return (
        f"{a.name} reaches CTL {a.ctl_end:.0f} vs {b.ctl_end:.0f} for {b.name} at the end of the projection, "
        f"with a peak ramp of {_fmt(a.peak_ctl_ramp_per_week, 1)}/wk vs {_fmt(b.peak_ctl_ramp_per_week, 1)}/wk "
        f"and {_day_count_clause(a.days_below_tsb_threshold, b.days_below_tsb_threshold)}."
    )


def _event_sentences(a: ScenarioProjection, b: ScenarioProjection) -> list[str]:
    b_by_name = {e.name: e for e in b.event_metrics}
    return [
        f"On {e.name} ({e.date.isoformat()}), {a.name} projects CTL {e.ctl:.0f} / TSB {e.tsb:+.0f} "
        f"vs CTL {b_by_name[e.name].ctl:.0f} / TSB {b_by_name[e.name].tsb:+.0f} for {b.name}."
        for e in a.event_metrics
        if e.name in b_by_name
    ]


def _structure_sentence(a: ScenarioProjection, b: ScenarioProjection) -> str | None:
    if a.hard_session_count is None or b.hard_session_count is None:
        return None
    return (
        f"{a.name} has {a.hard_session_count} hard sessions with at least {_fmt(a.min_hours_between_hard)} h between them "
        f"vs {b.hard_session_count} with at least {_fmt(b.min_hours_between_hard)} h for {b.name}; "
        f"mean weekly monotony {_fmt(a.mean_weekly_monotony, 2)} vs {_fmt(b.mean_weekly_monotony, 2)}."
    )


def _finding_ids(p: ScenarioProjection) -> str:
    return ", ".join(f.id for f in p.findings) or "none"


def _pair_tradeoffs(a: ScenarioProjection, b: ScenarioProjection) -> list[str]:
    sentences = [_end_sentence(a, b), *_event_sentences(a, b)]
    structure = _structure_sentence(a, b)
    if structure:
        sentences.append(structure)
    sentences.append(f"{a.name} totals {a.total_hours:.0f} h over {len(a.weeks)} weeks vs {b.total_hours:.0f} h over {len(b.weeks)} weeks for {b.name}.")
    sentences.append(f"Plan-check findings: {a.name}: {_finding_ids(a)}; {b.name}: {_finding_ids(b)}.")
    return sentences


def compare_scenarios(projections: list[ScenarioProjection]) -> ScenarioComparison:
    """Side-by-side rows (differences are against the first projection) and trade-off
    sentences pairing the first projection with each other one."""
    if len(projections) < 2:
        raise ValueError("compare_scenarios needs at least two projections")
    names = [p.name for p in projections]
    if len(set(names)) != len(names):
        raise ValueError("projection names must be unique")
    tradeoffs = [s for other in projections[1:] for s in _pair_tradeoffs(projections[0], other)]
    return ScenarioComparison(
        names=names,
        rows=_rows({p.name: p.metrics() for p in projections}),
        tradeoffs=tradeoffs,
        limits=list(COMPARISON_LIMITS),
        findings={p.name: [f.id for f in p.findings] for p in projections},
        assumptions={p.name: p.assumptions for p in projections},
    )


# --- one-week sequence comparison -----------------------------------------------------


class SequenceResult(BaseModel):
    """Load and freshness facts for one ordering of a week."""

    hard_morning_tsb: dict[date, float]
    longest_session_date: date | None
    longest_morning_tsb: float | None
    min_hours_between_hard: float | None
    back_to_back_hard_pairs: int
    strength_before_key_dates: list[date]
    monotony: float | None
    end_tsb: float
    findings: list[PlanCheckFinding]

    def metrics(self) -> list[Metric]:
        lowest = min(self.hard_morning_tsb.values(), default=None)
        return [
            Metric(key="min_hours_between_hard", label="Minimum hours between hard sessions", unit="h", value=self.min_hours_between_hard),
            Metric(key="back_to_back_hard_pairs", label="Hard sessions on consecutive days", unit="", value=float(self.back_to_back_hard_pairs)),
            Metric(key="lowest_hard_morning_tsb", label="Lowest TSB on a hard-session morning", unit="", value=lowest),
            Metric(key="longest_morning_tsb", label="TSB on the morning of the longest session", unit="", value=self.longest_morning_tsb),
            Metric(key="strength_before_key_count", label="Strength the day before a hard or longest session", unit="", value=float(len(self.strength_before_key_dates))),
            Metric(key="monotony", label="Weekly monotony", unit="", value=self.monotony),
            Metric(key="end_tsb", label="TSB at end of week", unit="", value=self.end_tsb),
            Metric(key="finding_count", label="Plan-check findings", unit="", value=float(len(self.findings))),
        ]


class SequenceComparison(BaseModel):
    candidates: dict[str, SequenceResult]
    rows: list[ComparisonRow]
    tradeoffs: list[str]
    limits: list[str]


def _morning_tsb(series: list[tuple[date, float, float, float]], seed_tsb: float, first_day: date) -> dict[date, float]:
    """TSB on the morning of each day = TSB after the previous day's load."""
    out = {first_day: seed_tsb}
    for (_d, _c, _a, tsb), (nxt, *_rest) in zip(series, series[1:]):
        out[nxt] = tsb
    return out


def _analyse_week(
    week: WeekPlan, athlete: Athlete, events: list[Event], current_ctl: float, current_atl: float | None
) -> SequenceResult:
    if not week.sessions:
        raise ValueError("a candidate week has no sessions")
    first_day = _monday(min(s.date for s in week.sessions))
    loads: dict[date, float] = {}
    for s in week.sessions:
        loads[s.date] = loads.get(s.date, 0.0) + session_target_load_au(s, athlete)
    series = _project_ctl_atl_tsb(current_ctl, loads, first_day, first_day + timedelta(days=6), current_atl=current_atl)
    seed = current_ctl - (current_ctl if current_atl is None else current_atl)
    morning = _morning_tsb(series, seed, first_day)
    race_dates = frozenset(e.event_date for e in events)
    hard_days = sorted({s.date for s in week.sessions if _is_hard_session(s, race_dates)})
    longest = max(week.sessions, key=lambda s: (s.duration_min, -s.date.toordinal()))
    key_days = set(hard_days) | {longest.date}
    strength = sorted(
        s.date for s in week.sessions if s.sport == STRENGTH_SPORT and s.date + timedelta(days=1) in key_days
    )
    report = check_week(week, None, athlete, recent_weeks=[], events=events)
    return SequenceResult(
        hard_morning_tsb={d: morning[d] for d in hard_days},
        longest_session_date=longest.date,
        longest_morning_tsb=morning[longest.date],
        min_hours_between_hard=_min_hours_between(hard_days),
        back_to_back_hard_pairs=sum(1 for a, b in zip(hard_days, hard_days[1:]) if (b - a).days == 1),
        strength_before_key_dates=strength,
        monotony=monotony({first_day + timedelta(days=i): loads.get(first_day + timedelta(days=i), 0.0) for i in range(7)}),
        end_tsb=series[-1][3],
        findings=report.findings,
    )


def _sequence_pair(an: str, a: SequenceResult, bn: str, b: SequenceResult) -> list[str]:
    lowest_a = min(a.hard_morning_tsb.values(), default=None)
    lowest_b = min(b.hard_morning_tsb.values(), default=None)
    return [
        f"{an} keeps at least {_fmt(a.min_hours_between_hard)} h between hard sessions vs {_fmt(b.min_hours_between_hard)} h for {bn}, "
        f"with {a.back_to_back_hard_pairs} vs {b.back_to_back_hard_pairs} pairs of hard sessions on consecutive days.",
        f"The lowest TSB on a hard-session morning is {_fmt(lowest_a)} for {an} vs {_fmt(lowest_b)} for {bn}; "
        f"on the morning of the longest session it is {_fmt(a.longest_morning_tsb)} vs {_fmt(b.longest_morning_tsb)}.",
        f"Strength falls the day before a hard or longest session on {len(a.strength_before_key_dates)} vs {len(b.strength_before_key_dates)} days; "
        f"weekly monotony is {_fmt(a.monotony, 2)} vs {_fmt(b.monotony, 2)} and end-of-week TSB is {a.end_tsb:+.0f} vs {b.end_tsb:+.0f}.",
        f"Plan-check findings: {an}: {', '.join(f.id for f in a.findings) or 'none'}; {bn}: {', '.join(f.id for f in b.findings) or 'none'}.",
    ]


def compare_week_sequences(
    candidates: dict[str, WeekPlan],
    athlete: Athlete,
    *,
    current_ctl: float,
    current_atl: float | None,
    events: list[Event] | None = None,
) -> SequenceComparison:
    """Compare orderings of one week using each session's planned load. "Hard" is
    `plan_check._is_hard_session`; the morning TSB of a day is the TSB after the previous day."""
    if len(candidates) < 2:
        raise ValueError("compare_week_sequences needs at least two candidate weeks")
    events = events or []
    results = {n: _analyse_week(w, athlete, events, current_ctl, current_atl) for n, w in candidates.items()}
    names = list(results)
    tradeoffs = [s for other in names[1:] for s in _sequence_pair(names[0], results[names[0]], other, results[other])]
    return SequenceComparison(
        candidates=results,
        rows=_rows({n: r.metrics() for n, r in results.items()}),
        tradeoffs=tradeoffs,
        limits=list(SEQUENCE_LIMITS),
    )
