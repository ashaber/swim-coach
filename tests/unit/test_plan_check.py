"""Golden-fixture tests for `swim_coach.plan_check` (engine/plan-check-red-
team PR 1). Two real macros: Tim's real cyclocross macrocycle table
(`ai-coach/athlete/plans/current/macrocycle.md`, transcribed verbatim below)
should come back sound-ish with no high-severity findings; the swim-coach
repo's own real, buggy Sep-Nov macro (misplaced taper, an uncovered race
week, bike volume recorded in meters) should get flagged for exactly those
defects. A third case (a 58-year-old targeting 5 W/kg from 3.5) exercises
the goal-reality check. A fourth confirms `check_macro`/`check_week` are
advisory only -- they never raise, no matter how broken the plan is.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from swim_coach.models import (
    Athlete,
    Event,
    MacroBlock,
    MacroPlan,
    MacroWeek,
    Session,
    WeekPlan,
)
from swim_coach.plan_check import (
    check_macro,
    check_week,
    _project_ctl_atl_tsb,
    _spread_weekly_tss_to_daily,
)

TODAY = date(2026, 9, 27)


def _athlete(**overrides) -> Athlete:
    defaults = dict(
        id=uuid.uuid4(),
        slug="test-athlete",
        name="Test Athlete",
        css_pace_s_per_100m=None,
        constraints={},
        pool_schedule=[],
    )
    defaults.update(overrides)
    return Athlete(**defaults)


def _event(**overrides) -> Event:
    defaults = dict(
        id=uuid.uuid4(),
        athlete_id=uuid.uuid4(),
        name="Race",
        event_date=date(2026, 10, 17),
        target_metric="duration_min",
        target_value=50.0,
        distance_m=None,
        priority="A",
        primary_sport="bike",
        active=True,
    )
    defaults.update(overrides)
    return Event(**defaults)


def _macro(weeks: list[MacroWeek], **overrides) -> MacroPlan:
    defaults = dict(
        id=uuid.uuid4(),
        athlete_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        blocks=[],
        weeks=weeks,
    )
    defaults.update(overrides)
    return MacroPlan(**defaults)


# ============================================================================
# Golden fixture 1: Tim's real cyclocross macrocycle
# (ai-coach/athlete/plans/current/macrocycle.md, transcribed verbatim)
# ============================================================================


def _tims_weeks() -> list[MacroWeek]:
    rows = [
        # (week_start, phase, focus, hours, tss, ctl, key_sessions, recovery)
        (date(2026, 9, 7), "Reset", "Clear fatigue, install the pattern", 5.5, 240, 43,
         ["Tue: outdoor threshold 2x12 min @ 250 W (FTP check)", "Sat: short VO2 5x2 min @ 290-300 W"], True),
        (date(2026, 9, 14), "Race 1", "Open the legs, race the weekend", 5.0, 285, 43,
         ["Tue: openers 4x1 min VO2", "Sat 9/19 + Sun 9/20 races"], False),
        (date(2026, 9, 21), "Sharpen 1", "Fade resistance (outdoor only)", 6.5, 320, 43,
         ["Tue: over/unders 3x[8 min]", "Sat: CX sim 4x5 min hard w/ barriers"], False),
        (date(2026, 9, 28), "Sharpen 2", "Repeatability + flat power (outdoor)", 7.0, 345, 44,
         ["Tue: short-short VO2 2x[10x(40s/20s)]", "Sat: flat aero threshold 3x10 min"], False),
        (date(2026, 10, 5), "Sharpen 3", "Consolidate, start freshening", 6.0, 270, 43,
         ["Tue: over/unders 3x[6 min]", "Sat: race-pace 5x3 min"], True),
        (date(2026, 10, 12), "Peak", "Freshen, race fresh", 4.5, 250, 42,
         ["Tue: sharpeners 4x2 min @ 280 W", "Sat 10/17 + Sun 10/18 -- target races"], True),
        (date(2026, 10, 19), "Unload", "Absorb, stay primed", 5.0, 230, 41,
         ["Thu: over/unders 2x[6 min]", "Sat: opener 4x1 min"], True),
        (date(2026, 10, 26), "Race 3", "Open and race", 5.0, 285, 41,
         ["Tue: openers 5x1 min VO2", "Sat 10/31 + Sun 11/1 races"], False),
        (date(2026, 11, 2), "Maintain", "Hold the sharpness", 6.5, 320, 42,
         ["Tue: short-short VO2 2x[8x(40s/20s)]", "Sat: threshold 3x10 min + surges"], False),
        (date(2026, 11, 9), "Recovery", "Deliberate unload", 3.5, 185, 40,
         ["Easy Z2 only Mon-Thu", "Fri: short openers 3x1 min"], True),
        (date(2026, 11, 16), "Race 4", "Open and race -- season end", 5.0, 280, 40,
         ["Thu: race-pace 3x3 min @ 280 W", "Sat 11/21 + Sun 11/22 races"], False),
    ]
    return [
        MacroWeek(
            week_start=r[0], phase=r[1], focus=r[2], hours=r[3], load_tss=r[4],
            ctl_target=r[5], key_sessions=r[6], recovery=r[7],
        )
        for r in rows
    ]


def _tims_athlete() -> Athlete:
    # dob 1975-04-07 -- as of TODAY (2026-09-27) this is age 51, masters.
    return _athlete(name="Andrew", dob=date(1975, 4, 7), sex="male", ftp_watts=263.0, weight_kg=72.6)


def _tims_events() -> list[Event]:
    return [
        _event(name="Race 1", event_date=date(2026, 9, 19), priority="B", primary_sport="bike"),
        _event(name="Peak weekend", event_date=date(2026, 10, 17), priority="A", primary_sport="bike"),
        _event(name="Race 3", event_date=date(2026, 10, 31), priority="B", primary_sport="bike"),
        _event(name="Race 4", event_date=date(2026, 11, 21), priority="B", primary_sport="bike"),
    ]


def test_tims_macro_is_sound_or_sound_with_caveats_and_has_no_high_findings():
    plan = _macro(_tims_weeks())
    report = check_macro(
        plan,
        _tims_athlete(),
        current_ctl=43.0,
        recent_weekly_hours=[6.5, 7.0, 7.5, 7.0, 6.8, 7.2, 7.0, 6.5, 7.0, 7.3],
        events=_tims_events(),
        today=date(2026, 9, 7),
    )
    assert report.verdict in ("sound", "sound-with-caveats")
    assert not any(f.severity == "high" for f in report.findings)
    # Taper checks are load-based, not phase-name-based: Tim's table never
    # writes the literal word "taper" (the peak race's lead-in is labelled
    # "Peak"/"Sharpen 3"), and its real hours cut into the peak week
    # (7.0h -> 4.5h, ~36%) falls inside the short-event evidence band --
    # so no taper finding of any kind should fire.
    assert not any("taper" in f.id for f in report.findings)


def test_tims_macro_with_a_realistic_current_atl_reports_race_day_tsb():
    """Same fixture, but seeded with a real (non-CTL-fallback) ATL --
    exercises check_macro's optional current_atl parameter."""
    plan = _macro(_tims_weeks())
    report = check_macro(
        plan,
        _tims_athlete(),
        current_ctl=43.0,
        current_atl=48.0,  # somewhat fatigued entering the Sep-7 reset week
        recent_weekly_hours=[6.5, 7.0, 7.5, 7.0, 6.8, 7.2, 7.0, 6.5, 7.0, 7.3],
        events=_tims_events(),
        today=date(2026, 9, 7),
    )
    tsb_finding = next((f for f in report.findings if f.id.startswith("race-day-tsb-")), None)
    assert tsb_finding is not None
    # No taper-too-long finding for Tim's plan (see the dedicated test
    # below), so this stays medium -- the escalation to high only fires
    # when a taper-too-long finding for the SAME race coincides with a
    # too-FRESH (above-band) reading.
    assert tsb_finding.severity == "medium"
    print(tsb_finding.evidence)


# ============================================================================
# Golden fixture 2: the swim-coach repo's own real, buggy Sep-Nov macro
# ============================================================================


def _buggy_weeks() -> list[MacroWeek]:
    weeks = []
    # sharpen Sep 14 - 27 (2 weeks)
    for d in (date(2026, 9, 14), date(2026, 9, 21)):
        weeks.append(MacroWeek(week_start=d, phase="sharpen", focus="build", hours=6.0, load_tss=300.0, ctl_target=40.0))
    # taper Sep 28 - Oct 11 (2 weeks)
    for d in (date(2026, 9, 28), date(2026, 10, 5)):
        weeks.append(MacroWeek(week_start=d, phase="taper", focus="freshen", hours=4.0, load_tss=180.0, ctl_target=39.0))
    # Oct 12-18: UNCOVERED -- contains the Oct 17 A race.
    # sharpen Oct 19 - Nov 8 (3 weeks), bike volumes recorded in bare meters
    # (the real "meters-for-bike" defect): no hours, no load_tss.
    for d, m in zip((date(2026, 10, 19), date(2026, 10, 26), date(2026, 11, 2)), (540, 270, 202)):
        weeks.append(
            MacroWeek(
                week_start=d, phase="sharpen", focus="build",
                hours=None, load_tss=None, ctl_target=40.0,
                notes=f"{m}m",
            )
        )
    # taper Nov 9-15 (1 week)
    weeks.append(MacroWeek(week_start=date(2026, 11, 9), phase="taper", focus="freshen", hours=4.0, load_tss=150.0, ctl_target=39.0))
    return weeks


def _buggy_events() -> list[Event]:
    return [
        _event(name="Goal CX race", event_date=date(2026, 10, 17), priority="A", primary_sport="bike"),
        _event(name="B race", event_date=date(2026, 10, 31), priority="B", primary_sport="bike"),
        _event(name="Season finale", event_date=date(2026, 11, 21), priority="B", primary_sport="bike"),
    ]


def test_buggy_macro_flags_uncovered_race_week_and_meters_defect():
    # Taper checks are load-based (see below) -- the buggy macro's actual
    # race week (Oct 12-18, containing the Oct 17 A race) has no MacroWeek
    # row at all, so there's no load number to judge a taper cut against;
    # the taper-quality check silently skips (never fabricates a reading),
    # and the missing week is caught instead by the uncovered-weeks check,
    # which is the real, high-severity defect here.
    plan = _macro(_buggy_weeks())
    athlete = _athlete(dob=date(1975, 4, 7), ftp_watts=263.0, weight_kg=72.6)
    report = check_macro(
        plan,
        athlete,
        current_ctl=40.0,
        recent_weekly_hours=[6.0, 6.5, 7.0],
        events=_buggy_events(),
        today=date(2026, 9, 14),
    )
    finding_ids = [f.id for f in report.findings]

    assert any("uncovered" in fid for fid in finding_ids), finding_ids
    assert any(fid == "bike-weeks-missing-load" for fid in finding_ids), finding_ids
    assert not any("taper" in fid for fid in finding_ids), finding_ids
    assert report.verdict in ("fragile", "not-feasible")


# ============================================================================
# Golden fixture 3: unrealistic goal reality check
# ============================================================================


def test_goal_reality_check_flags_unrealistic_58_year_old_5_w_per_kg_goal():
    weeks = [MacroWeek(week_start=date(2026, 9, 7), phase="base", focus="build", hours=6.0, load_tss=300.0)]
    plan = _macro(
        weeks,
        architecture=(
            "This season builds toward a long-range goal of 5 W/kg; this block "
            "focuses on FTP and threshold work."
        ),
    )
    athlete = _athlete(
        dob=date(TODAY.year - 58, TODAY.month, TODAY.day),
        ftp_watts=245.0,
        weight_kg=70.0,  # 3.5 W/kg current
    )
    report = check_macro(
        plan,
        athlete,
        current_ctl=40.0,
        recent_weekly_hours=[6.0, 6.5],
        events=[],
        today=TODAY,
    )
    assert any(f.id == "goal-reality-check" for f in report.findings)


# ============================================================================
# Golden fixture 4: advisory only -- never raises
# ============================================================================


def test_check_macro_never_raises_on_a_bad_plan():
    # Empty weeks, no events, an athlete with no demographic data at all.
    plan = _macro([])
    athlete = _athlete()
    report = check_macro(
        plan, athlete, current_ctl=0.0, recent_weekly_hours=[], events=[], today=TODAY,
    )
    assert report.verdict in ("sound", "sound-with-caveats", "fragile", "not-feasible")

    # Wildly inconsistent data: negative-looking, contradictory weeks.
    weird_weeks = [
        MacroWeek(week_start=date(2026, 1, 5), phase="", focus="", hours=-5.0, load_tss=-100.0, ctl_target=-1.0),
        MacroWeek(week_start=date(2020, 1, 1), phase="taper", focus="", recovery=True),
    ]
    weird_plan = _macro(weird_weeks)
    report2 = check_macro(
        weird_plan,
        athlete,
        current_ctl=-10.0,
        recent_weekly_hours=[0.0],
        events=[_event(event_date=date(2019, 1, 1), priority="A", active=True)],
        today=TODAY,
    )
    assert report2.verdict in ("sound", "sound-with-caveats", "fragile", "not-feasible")


# ============================================================================
# Golden fixture 5: the real 2026-09-27 production failure -- a 2-week
# taper (Sep 28, Oct 5) plus race week (Oct 12, containing the Oct 17-18 A
# race) on the only race-free CX build window. The red team that day
# returned only medium findings ("race-day TSB just outside band," "recovery
# cadence") and the coach argued the TSB finding away instead of flagging
# the actual defect: the build window was spent tapering, not building.
# ============================================================================


def _production_failure_weeks() -> list[MacroWeek]:
    # Loads tuned (not hand-picked to be flattering) so the projected race-day
    # TSB genuinely lands ABOVE `RACE_DAY_TSB_BAND` (>25) as well -- the real
    # 2026-09-27 draft's own red-team run reported race-day TSB 25.5, "just
    # outside 5-25" -- so this fixture exercises BOTH new behaviors at once:
    # the taper-too-long finding, and its escalation of the race-day-tsb
    # finding from medium to high.
    return [
        MacroWeek(week_start=date(2026, 8, 31), phase="build", focus="build", hours=7.0, load_tss=400.0, ctl_target=48.0),
        MacroWeek(week_start=date(2026, 9, 7), phase="build", focus="build", hours=7.0, load_tss=410.0, ctl_target=49.0),
        MacroWeek(week_start=date(2026, 9, 14), phase="build", focus="build", hours=6.5, load_tss=390.0, ctl_target=50.0),
        MacroWeek(week_start=date(2026, 9, 21), phase="build", focus="build", hours=7.0, load_tss=405.0, ctl_target=51.0),
        MacroWeek(week_start=date(2026, 9, 28), phase="Taper", focus="freshen", hours=1.5, load_tss=40.0, ctl_target=48.0),
        MacroWeek(week_start=date(2026, 10, 5), phase="Taper", focus="freshen", hours=1.0, load_tss=20.0, ctl_target=44.0),
        MacroWeek(week_start=date(2026, 10, 12), phase="Race", focus="race the CX weekend", hours=1.0, load_tss=20.0, ctl_target=41.0),
    ]


def _production_failure_events() -> list[Event]:
    return [
        _event(
            name="CX A race",
            event_date=date(2026, 10, 17),
            priority="A",
            primary_sport="bike",
            target_metric="duration_min",
            target_value=60.0,  # ~1h cyclocross
        ),
    ]


def test_production_failure_draft_flags_high_taper_too_long():
    plan = _macro(_production_failure_weeks())
    athlete = _athlete(dob=date(1975, 4, 7), ftp_watts=263.0, weight_kg=72.6)
    report = check_macro(
        plan,
        athlete,
        current_ctl=48.0,
        current_atl=48.0,
        recent_weekly_hours=[6.5, 7.0, 7.0, 6.8, 7.0],
        events=_production_failure_events(),
        today=date(2026, 8, 31),
    )
    finding_ids = {f.id for f in report.findings}
    taper_too_long = next((f for f in report.findings if f.id.startswith("taper-too-long-")), None)
    assert taper_too_long is not None, finding_ids
    assert taper_too_long.severity == "high"
    # Real production behavior this fixes: the coach reasoned away a lone
    # medium "race-day TSB just outside band" finding ("too fresh is a
    # smaller risk than flat"). With a coinciding taper-too-long finding for
    # the same race, that TSB finding is escalated to high too -- two highs,
    # "not-feasible", nothing left to talk itself out of.
    tsb_finding = next((f for f in report.findings if f.id.startswith("race-day-tsb-")), None)
    assert tsb_finding is not None, finding_ids
    assert tsb_finding.severity == "high"
    assert report.verdict == "not-feasible"


def test_tims_macro_has_no_taper_too_long_finding():
    plan = _macro(_tims_weeks())
    report = check_macro(
        plan,
        _tims_athlete(),
        current_ctl=43.0,
        recent_weekly_hours=[6.5, 7.0, 7.5, 7.0, 6.8, 7.2, 7.0, 6.5, 7.0, 7.3],
        events=_tims_events(),
        today=date(2026, 9, 7),
    )
    assert not any(f.id.startswith("taper-too-long-") for f in report.findings)


# ============================================================================
# Golden fixture 6: the real hours-only production defect -- a MacroWeek
# with `hours` set but no `load_tss` used to be silently projected as ZERO
# load, so a 1-week and a 2-week hours-only taper decayed to the IDENTICAL
# fake race-day TSB regardless of taper length. `recent_tss_per_hour`
# (estimated from the athlete's own real logged history via
# `load.recent_tss_per_hour`) fixes this.
# ============================================================================


def _hours_only_weeks(*, two_week_taper: bool) -> list[MacroWeek]:
    """All hours-only (`load_tss=None` throughout) -- the real production
    macro's own shape (the coach authored `hours`, never `load_tss`).
    `two_week_taper=False` is the evidence-backed shape this fix's own
    taper-too-long check recommends: build volume held through Sep 28/
    Oct 5, with the whole cut living inside race week itself (Oct 12,
    ~3.25h, roughly half of the ~6.5-7h build weeks) -- exactly the
    coordinator's own worked example. `two_week_taper=True` reproduces the
    real bad draft: Sep 28/Oct 5 already reduced, race week barely cut
    further."""
    build = [
        MacroWeek(week_start=date(2026, 8, 31), phase="build", focus="build", hours=7.0),
        MacroWeek(week_start=date(2026, 9, 7), phase="build", focus="build", hours=7.0),
        MacroWeek(week_start=date(2026, 9, 14), phase="build", focus="build", hours=6.5),
        MacroWeek(week_start=date(2026, 9, 21), phase="build", focus="build", hours=7.0),
    ]
    if two_week_taper:
        pre_race = [
            MacroWeek(week_start=date(2026, 9, 28), phase="Taper", focus="freshen", hours=4.0),
            MacroWeek(week_start=date(2026, 10, 5), phase="Taper", focus="freshen", hours=3.0),
        ]
        race = MacroWeek(week_start=date(2026, 10, 12), phase="Race", focus="race the CX weekend", hours=3.0)
    else:
        pre_race = [
            MacroWeek(week_start=date(2026, 9, 28), phase="build", focus="build", hours=7.0),
            MacroWeek(week_start=date(2026, 10, 5), phase="build", focus="build", hours=6.5),
        ]
        race = MacroWeek(week_start=date(2026, 10, 12), phase="Race", focus="race the CX weekend", hours=3.25)
    return build + pre_race + [race]


def test_hours_only_weeks_project_different_race_day_tsb_for_1_vs_2_week_taper():
    # Real production bug: an hours-only week used to contribute ZERO load
    # to the projection (no load_tss to spread), so these two genuinely
    # different plans decayed to the SAME fake TSB. With a realistic
    # recent-history rate (~55-65 AU/hour) to estimate from, they must
    # actually differ.
    rate = 60.0
    today = date(2026, 8, 31)
    event_date = date(2026, 10, 17)

    def _projected_tsb_on_event_day(weeks: list[MacroWeek]) -> float:
        daily, _estimated, unresolved = _spread_weekly_tss_to_daily(weeks, rate)
        assert not unresolved, "every week here has `hours` set; nothing should be unresolved"
        plan_end_exclusive = weeks[-1].week_start + timedelta(days=7)
        projection_end = max(plan_end_exclusive - timedelta(days=1), today)
        series = _project_ctl_atl_tsb(48.0, daily, today, projection_end, current_atl=48.0)
        by_date = {d: tsb for d, _ctl, _atl, tsb in series}
        return by_date[event_date]

    tsb_1_week_taper = _projected_tsb_on_event_day(_hours_only_weeks(two_week_taper=False))
    tsb_2_week_taper = _projected_tsb_on_event_day(_hours_only_weeks(two_week_taper=True))
    assert tsb_1_week_taper != pytest.approx(tsb_2_week_taper, abs=0.5)


def test_hours_only_weeks_without_a_rate_give_projection_unavailable_not_a_tsb_number():
    # The "missing-everything" case (e.g. a brand-new athlete with no
    # logged history yet to estimate a rate from): must NOT silently
    # project zero load and report a precise-looking but fake TSB.
    athlete = _athlete(dob=date(1975, 4, 7), ftp_watts=263.0, weight_kg=72.6)
    plan = _macro(_hours_only_weeks(two_week_taper=True))
    report = check_macro(
        plan,
        athlete,
        current_ctl=48.0,
        current_atl=48.0,
        recent_weekly_hours=[6.5, 7.0, 7.0, 6.8, 7.0],
        # recent_tss_per_hour omitted -- no usable rate.
        events=_production_failure_events(),
        today=date(2026, 8, 31),
    )
    finding_ids = [f.id for f in report.findings]
    assert "projection-unavailable" in finding_ids, finding_ids
    assert not any(fid.startswith("race-day-tsb-") for fid in finding_ids), finding_ids
    assert "sustained-low-tsb" not in finding_ids, finding_ids


def test_hours_only_weeks_with_a_rate_labels_the_race_day_tsb_finding_as_estimated():
    # Same numbers as the production-failure golden fixture (test above),
    # but authored hours-only and reconstructed via a real recent-history
    # rate instead of directly-set load_tss -- proves the estimate path
    # produces the same real finding (including the high-severity
    # escalation via taper-too-long), clearly labelled as an estimate.
    rate = 60.0

    def h(tss: float) -> float:
        return tss / rate

    weeks = [
        MacroWeek(week_start=date(2026, 8, 31), phase="build", focus="build", hours=h(400.0)),
        MacroWeek(week_start=date(2026, 9, 7), phase="build", focus="build", hours=h(410.0)),
        MacroWeek(week_start=date(2026, 9, 14), phase="build", focus="build", hours=h(390.0)),
        MacroWeek(week_start=date(2026, 9, 21), phase="build", focus="build", hours=h(405.0)),
        MacroWeek(week_start=date(2026, 9, 28), phase="Taper", focus="freshen", hours=h(40.0)),
        MacroWeek(week_start=date(2026, 10, 5), phase="Taper", focus="freshen", hours=h(20.0)),
        MacroWeek(week_start=date(2026, 10, 12), phase="Race", focus="race the CX weekend", hours=h(20.0)),
    ]
    athlete = _athlete(dob=date(1975, 4, 7), ftp_watts=263.0, weight_kg=72.6)
    plan = _macro(weeks)
    report = check_macro(
        plan,
        athlete,
        current_ctl=48.0,
        current_atl=48.0,
        recent_weekly_hours=[6.5, 7.0, 7.0, 6.8, 7.0],
        recent_tss_per_hour=rate,
        events=_production_failure_events(),
        today=date(2026, 8, 31),
    )
    finding_ids = [f.id for f in report.findings]
    assert "projection-unavailable" not in finding_ids, finding_ids
    tsb_finding = next((f for f in report.findings if f.id.startswith("race-day-tsb-")), None)
    assert tsb_finding is not None, finding_ids
    assert "estimated" in tsb_finding.evidence.lower()
    assert tsb_finding.severity == "high"  # taper-too-long still coincides


def test_check_week_never_raises_and_is_advisory_only():
    athlete = _athlete()
    week = WeekPlan(
        id=uuid.uuid4(),
        athlete_id=athlete.id,
        iso_week="2026-W38",
        meso_block="build",
        focus="build",
        target_volume_m=0,
        sessions=[],
    )
    report = check_week(week, None, athlete, recent_weeks=[])
    assert report.verdict in ("sound", "sound-with-caveats", "fragile", "not-feasible")
    # never raises even with a huge, unrealistic jump vs. recent history
    prev = WeekPlan(
        id=uuid.uuid4(), athlete_id=athlete.id, iso_week="2026-W37",
        meso_block="build", focus="build", target_volume_m=1000,
        sessions=[
            Session(
                id=uuid.uuid4(), athlete_id=athlete.id, date=date(2026, 9, 13),
                sport="swim_ow", source="ai_coach", duration_min=30.0,
                distance_m=1000, intensity={"zone": "Z2"}, purpose="long swim",
            )
        ],
    )
    big_week = WeekPlan(
        id=uuid.uuid4(), athlete_id=athlete.id, iso_week="2026-W38",
        meso_block="build", focus="build", target_volume_m=5000,
        sessions=[
            Session(
                id=uuid.uuid4(), athlete_id=athlete.id, date=date(2026, 9, 20),
                sport="swim_ow", source="ai_coach", duration_min=120.0,
                distance_m=5000, intensity={"zone": "Z2"}, purpose="long swim",
            )
        ],
    )
    report2 = check_week(big_week, None, athlete, recent_weeks=[prev])
    assert report2.verdict in ("sound", "sound-with-caveats", "fragile", "not-feasible")
    assert any(f.id == "confirm-weekly-volume-ramp" for f in report2.findings)
    assert any(f.id == "confirm-long-swim-step" for f in report2.findings)
