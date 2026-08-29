"""Read-only, exploratory taper-shape simulation against the Banister
CTL/ATL/TSB model (`load.py`'s `ctl_atl_tsb_series`) -- the first empirical
input toward the long-standing "taper-individualization algorithm" roadmap
item, NOT a replacement for `plan.py`'s real `scaffold_macro` taper math.

**THIS MODULE NEVER MUTATES ANYTHING.** Every function here is a pure
read+compute function over already-loaded `Athlete`/`Event`/`Workout`/
`Wellness` data -- no `store.save_*` call anywhere in this file, no I/O, no
LLM calls, same "pure functions, no side effects" convention as `load.py`/
`quality.py`. `cli.py`'s `simulate-taper` command (the only caller) loads
data, calls into this module, and prints a JSON report; it never persists
the result. Real athlete plan changes always go through `scaffold_macro`/
`/adapt`, with the athlete's explicit confirmation, per CLAUDE.md's safety
rails -- this module exists to inform that conversation, not skip it.

**The core modeling simplification, stated plainly (per this project's
evidence-discipline convention of flagging assumptions, not burying them):**
rather than resolving full session-by-session `WorkoutStructure` targets
into estimated future loads -- a much bigger, more assumption-laden
undertaking -- each candidate taper is modeled as a **volume-reduction
fraction applied to the athlete's own recent average daily training load**.
This reuses `scaffold_macro`'s own `(taper_weeks, decay)` parameterization
verbatim (`volume_fraction = 1 - decay * taper_weeks`, see `plan.py`'s
`TAPER_WEEKLY_DECAY`/`taper_end` line) and simply assumes daily *load*
scales proportionally with weekly *volume* during the taper. That
volume-reduction assumption is not an arbitrary proxy invented for this
tool -- it is literally the primary taper lever the taper-physiology
literature this project already cites describes: `Mujika I., Padilla S.
(2003)`, "Scientific bases for precompetition tapering strategies" (Medicine
& Science in Sports & Exercise, 35(7):1182-1187) recommends maintaining
training INTENSITY while cutting volume 60-90% and frequency by <=~20%, and
`Wang Z., Wang Y.T., Gao W., Zhong Y. (2023)`'s 14-study meta-analysis
(PLOS ONE, 18(5):e0282838) found <=21-day tapers with 41-60% volume
reduction (intensity/frequency roughly held) generally effective -- see
`library/reference_list.md` and `library/10-recovery-hrv.md`'s "Mini-taper
for a B-event" section for both citations in full. Still, "load scales
with volume" is an explicit assumption this module makes, not a derived
fact -- a real session-by-session load projection (accounting for intensity
held constant while volume drops, per Mujika & Padilla above) would likely
show LESS load reduction than a pure volume-fraction proxy implies, since
held intensity offsets some of the volume cut. Flagged here, not silently
assumed.

**Baseline daily load window (`BASELINE_WINDOW_DAYS`):** the athlete's
recent average daily load, NOT her whole history's average -- her early
base-phase weeks ran at meaningfully lower volume than her current
peak-phase training, and a whole-history average would understate the load
her peak phase is actually continuing at. See that constant's own comment
for the exact window and reasoning.

**Race-day boundary (`project_tsb_series` docstring for detail):** projects
day-by-day through the day BEFORE race day, not race day itself, and
reports TSB as of that day -- race day's own effort is the event, not
training load being tapered toward, so it is deliberately excluded from
the projection. This mirrors the everyday coaching-convention framing of
"race-day TSB" (the freshness an athlete carries INTO race day, not
race day's own training stress).

**Taper-block dates in this simulation vs. `scaffold_macro`'s real output:**
`scaffold_macro`'s real macro plan leaves a gap between the taper block's
end date and `event.event_date` (see `plan.py`'s module docstring: "race
week itself is not modeled as a macro block -- it's handled separately").
This simulation does NOT separately model race week -- there is no
session-level detail to separately load-model here in the first place (see
the volume-fraction simplification above) -- so each candidate's taper
block is defined to run for exactly `taper_weeks * 7` days immediately
before race day (`taper_start_date = event.event_date -
timedelta(weeks=taper_weeks)`), folding what would be race week into the
tail of the taper block. This is a simulation-only convenience; it never
touches or reinterprets the real macro's own block dates.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from swim_coach.load import (
    ATL_TIME_CONSTANT_DAYS,
    CTL_TIME_CONSTANT_DAYS,
    RACE_DAY_TSB_BAND,
    daily_loads,
    ctl_atl_tsb_series,
)
from swim_coach.models import Athlete, Event, Wellness, Workout
from swim_coach.plan import TAPER_WEEKLY_DECAY

BASELINE_WINDOW_DAYS = 21
# Coach judgment / PROVISIONAL, library/03-periodization.md. Three weeks
# (long enough to smooth normal day-to-day/rest-day noise, short enough to
# reflect current build/peak-phase training rather than diluting it with
# early base-phase history at much lower volume) ending on the athlete's
# most recently logged day. Missing (rest) days inside the window count as
# zero load, same "a day with no logged load is a real zero-load day, not
# an unknown" convention `daily_loads`/`ctl_atl_tsb_series` already use --
# a rest day is part of the athlete's real current training rhythm, not
# missing data to be skipped.

TAPER_WEEKS_GRID_MIN = 1
# Coach judgment: the shortest taper this search bothers to simulate. A
# 0-week "taper" isn't a taper at all (see `Wang et al. (2023)`'s finding
# that even <=7-day tapers show a real effect, cited in the module
# docstring above) -- 1 week is the shortest block worth calling a taper.

DECAY_GRID_MIN = 0.10
DECAY_GRID_MAX = 0.45
DECAY_GRID_STEP = 0.05
# Coach judgment: brackets `plan.py`'s real TAPER_WEEKLY_DECAY = 0.25 on
# both sides -- from a gentler decline (0.10/week) to noticeably steeper
# than today's real scaffold (0.45/week) -- so the grid can show what
# happens both short of and beyond the current real taper's aggressiveness,
# not just around it. Andrew's own stated range (~0.10-0.45); no library
# citation attaches to this specific numeric grid, only to the general
# "volume reduction is the taper lever" finding cited in the module
# docstring.


@dataclass(frozen=True)
class TaperCandidate:
    """One (taper_weeks, decay) grid point's simulated result.

    `is_current_real_taper` flags the one combination that matches the
    athlete's REAL, already-scaffolded macro taper block (same
    taper_weeks/decay `scaffold_macro` actually used) -- always present in
    `search_taper_grid`'s returned candidate list regardless of the grid's
    own bounds, so a caller can always see how the real plan compares to
    the rest of the grid. `fits_available_runway` is False when
    `taper_weeks` exceeds the whole weeks actually remaining before race
    day (`weeks_available`) -- included for visibility (e.g. the real
    current taper, if a race suddenly moved closer), never silently
    dropped, but flagged rather than presented as a genuinely proposable
    plan.
    """

    taper_weeks: int
    decay: float
    volume_fraction: float
    taper_start_date: date
    projected_ctl: float
    projected_atl: float
    projected_tsb: float
    in_band: bool
    is_current_real_taper: bool
    fits_available_runway: bool


def recent_baseline_daily_load(
    daily_load_values: dict[date, float],
    anchor_date: date,
    window_days: int = BASELINE_WINDOW_DAYS,
) -> float:
    """Mean daily training load over the `window_days` ending at
    `anchor_date` (inclusive) -- see `BASELINE_WINDOW_DAYS` above for why
    this window, not the whole history. A day absent from
    `daily_load_values` counts as zero load (same convention as
    `daily_loads`/`ctl_atl_tsb_series`), so a genuine rest day pulls the
    average down rather than being skipped -- the average is meant to
    reflect the athlete's real current weekly training rhythm, rest days
    included, not just "load on days she trained."
    """
    total = sum(
        daily_load_values.get(anchor_date - timedelta(days=i), 0.0) for i in range(window_days)
    )
    return total / window_days


def taper_volume_fraction(taper_weeks: int, decay: float) -> float:
    """`scaffold_macro`'s own taper-volume formula
    (`peak_volume * (1 - TAPER_WEEKLY_DECAY * taper_weeks)`), reduced to
    just the fraction (dropping the `peak_volume` multiplier since this
    module applies the same fraction to LOAD, not volume -- see module
    docstring's volume-reduction-as-load-proxy assumption). Floored at 0.0,
    same as `scaffold_macro`'s own `max(0, ...)` -- a decay/taper_weeks
    combination steep enough to go negative means "no training," not a
    negative load.
    """
    return max(0.0, 1.0 - decay * taper_weeks)


def project_tsb_series(
    ctl0: float,
    atl0: float,
    anchor_date: date,
    race_date: date,
    baseline_daily_load: float,
    taper_weeks: int,
    decay: float,
    *,
    ctl_tau_days: float = CTL_TIME_CONSTANT_DAYS,
    atl_tau_days: float = ATL_TIME_CONSTANT_DAYS,
) -> tuple[float, float, float, float, date]:
    """Project CTL/ATL/TSB forward day-by-day from `anchor_date` (the
    athlete's real, already-logged starting point) through the day BEFORE
    `race_date` (inclusive) -- see module docstring's "race-day boundary"
    section for why race day itself is excluded from the projection.

    For each projected day: `baseline_daily_load` unchanged while the day
    is still in the "peak phase continues" window (before this candidate's
    taper starts), then `baseline_daily_load * volume_fraction` for every
    day from `taper_start_date` (== `race_date - taper_weeks` weeks; see
    module docstring's "taper-block dates" section) through the day before
    race day. Same Banister recursion as `load.ctl_atl_tsb_series`:
    `CTL_t = CTL_{t-1} + (load_t - CTL_{t-1}) / ctl_tau_days`, same shape
    for ATL.

    Returns `(projected_ctl, projected_atl, projected_tsb,
    volume_fraction, taper_start_date)` as of the last projected day (the
    day before `race_date`). If `anchor_date` is already on or after
    `race_date - 1 day` (essentially no runway left to project), no
    recursion steps run and `(ctl0, atl0, ctl0 - atl0, ...)` is returned
    unchanged -- an honest "nothing to project" rather than a crash or a
    fabricated extra step.
    """
    volume_fraction = taper_volume_fraction(taper_weeks, decay)
    taper_start_date = race_date - timedelta(weeks=taper_weeks)

    ctl, atl = ctl0, atl0
    day = anchor_date + timedelta(days=1)
    last_projected_day = race_date - timedelta(days=1)
    while day <= last_projected_day:
        load = baseline_daily_load if day < taper_start_date else baseline_daily_load * volume_fraction
        ctl = ctl + (load - ctl) / ctl_tau_days
        atl = atl + (load - atl) / atl_tau_days
        day += timedelta(days=1)

    return ctl, atl, ctl - atl, volume_fraction, taper_start_date


def _decay_grid(decay_min: float, decay_max: float, decay_step: float) -> list[float]:
    steps = round((decay_max - decay_min) / decay_step)
    return [round(decay_min + i * decay_step, 10) for i in range(steps + 1)]


def build_taper_grid(
    weeks_available: int,
    current_real_taper_weeks: int,
    current_real_decay: float = TAPER_WEEKLY_DECAY,
    *,
    taper_weeks_min: int = TAPER_WEEKS_GRID_MIN,
    decay_min: float = DECAY_GRID_MIN,
    decay_max: float = DECAY_GRID_MAX,
    decay_step: float = DECAY_GRID_STEP,
) -> list[tuple[int, float]]:
    """Every `(taper_weeks, decay)` combination `search_taper_grid` should
    simulate, sorted ascending.

    `taper_weeks` candidates are bounded above by `weeks_available` (never
    propose a taper longer than the actual remaining runway -- same
    discipline `scaffold_macro` itself applies via `MIN_MACRO_WEEKS`) --
    the generated grid is empty if `weeks_available < taper_weeks_min`.
    Regardless of that bound, `(current_real_taper_weeks,
    current_real_decay)` -- the athlete's REAL already-scaffolded taper --
    is always added to the returned set, even if it doesn't fit
    `weeks_available` (`search_taper_grid` flags that case via
    `fits_available_runway`, it is never silently excluded here).
    """
    weeks_grid = list(range(taper_weeks_min, weeks_available + 1))
    decay_values = _decay_grid(decay_min, decay_max, decay_step)
    combos = {(w, d) for w in weeks_grid for d in decay_values}
    combos.add((current_real_taper_weeks, current_real_decay))
    return sorted(combos)


def _distance_to_band(tsb: float, band: dict[str, float]) -> float:
    if band["low"] <= tsb <= band["high"]:
        return 0.0
    return min(abs(tsb - band["low"]), abs(tsb - band["high"]))


def search_taper_grid(
    *,
    athlete: Athlete,
    event: Event,
    workouts: list[Workout],
    wellness: list[Wellness] | None = None,
    as_of: date,
    current_real_taper_weeks: int,
    current_real_decay: float = TAPER_WEEKLY_DECAY,
    baseline_window_days: int = BASELINE_WINDOW_DAYS,
    taper_weeks_min: int = TAPER_WEEKS_GRID_MIN,
    decay_min: float = DECAY_GRID_MIN,
    decay_max: float = DECAY_GRID_MAX,
    decay_step: float = DECAY_GRID_STEP,
    tsb_band: dict[str, float] = RACE_DAY_TSB_BAND,
) -> dict[str, object]:
    """Read-only grid search: for every `(taper_weeks, decay)` combination
    `build_taper_grid` produces, project the athlete's real current
    CTL/ATL forward to race-day-adjacent TSB (`project_tsb_series`) and
    report whether it lands inside `tsb_band`. NEVER writes anything -- see
    module docstring.

    The real starting point (`ctl0`/`atl0`/`anchor_date`) comes from
    running `load.ctl_atl_tsb_series` over the athlete's REAL logged
    `workouts`/`wellness` history and taking its last entry -- not a
    synthetic seed. `anchor_date` is therefore the athlete's most recently
    LOGGED day, which may lag `as_of` if logging itself lags reality; the
    baseline daily load window and the projection's "peak phase continues"
    segment are both anchored there for consistency with the recursion's
    real starting point.

    `weeks_available` (whole weeks from `as_of` to `event.event_date`) uses
    the same simple whole-week floor `scaffold_macro` uses for its own
    runway check, just measured from `as_of` (today) rather than a macro
    scaffold's own start date. Raises `ValueError` if `workouts` produces
    no loggable day at all (nothing to seed a starting CTL/ATL from).

    Returns a dict with `anchor_date`/`ctl0`/`atl0`/`tsb0`,
    `baseline_daily_load`, `race_date`, `weeks_available`, `tsb_band`,
    `candidates` (list of `TaperCandidate`), `any_in_band` (bool),
    `closest_to_band` (the `TaperCandidate` with the smallest distance into
    `tsb_band`, ties broken by grid order -- always populated, even when
    `any_in_band` is False, so a miss is reported as "here's the closest
    miss" rather than nothing useful), and `current_real_taper` (the one
    `TaperCandidate` with `is_current_real_taper=True`).
    """
    wellness = wellness or []
    loads = daily_loads(workouts, athlete=athlete, wellness=wellness)
    if not loads:
        raise ValueError(
            "no logged workouts for this athlete -- cannot compute a starting "
            "CTL/ATL or a recent baseline daily load"
        )

    series = ctl_atl_tsb_series(loads)
    anchor_date, ctl0, atl0, tsb0 = series[-1]
    baseline_daily_load = recent_baseline_daily_load(loads, anchor_date, baseline_window_days)

    race_date = event.event_date
    weeks_available = max(0, (race_date - as_of).days // 7)

    combos = build_taper_grid(
        weeks_available,
        current_real_taper_weeks,
        current_real_decay,
        taper_weeks_min=taper_weeks_min,
        decay_min=decay_min,
        decay_max=decay_max,
        decay_step=decay_step,
    )

    candidates: list[TaperCandidate] = []
    for taper_weeks, decay in combos:
        ctl, atl, tsb, volume_fraction, taper_start_date = project_tsb_series(
            ctl0,
            atl0,
            anchor_date,
            race_date,
            baseline_daily_load,
            taper_weeks,
            decay,
        )
        candidates.append(
            TaperCandidate(
                taper_weeks=taper_weeks,
                decay=decay,
                volume_fraction=volume_fraction,
                taper_start_date=taper_start_date,
                projected_ctl=ctl,
                projected_atl=atl,
                projected_tsb=tsb,
                in_band=tsb_band["low"] <= tsb <= tsb_band["high"],
                is_current_real_taper=(
                    taper_weeks == current_real_taper_weeks and decay == current_real_decay
                ),
                fits_available_runway=taper_weeks <= weeks_available,
            )
        )

    any_in_band = any(c.in_band for c in candidates)
    closest_to_band = min(candidates, key=lambda c: _distance_to_band(c.projected_tsb, tsb_band))
    current_real_taper = next(c for c in candidates if c.is_current_real_taper)

    return {
        "anchor_date": anchor_date,
        "ctl0": ctl0,
        "atl0": atl0,
        "tsb0": tsb0,
        "baseline_daily_load": baseline_daily_load,
        "baseline_window_days": baseline_window_days,
        "race_date": race_date,
        "weeks_available": weeks_available,
        "tsb_band": tsb_band,
        "candidates": candidates,
        "any_in_band": any_in_band,
        "closest_to_band": closest_to_band,
        "current_real_taper": current_real_taper,
    }
