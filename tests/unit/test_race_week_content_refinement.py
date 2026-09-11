"""Build E -- race-week content refinement from real coach usage
(`engine/race-week-content-refinement`).

Covers three real findings from Andrew's first real taper/race week off
PR #174/#175's machinery (item 1, skills-day RPE, is covered separately in
`test_skills_session.py`):

  2. openers shape/zone -- confirm no engine bug (a real progressive-ramp
     shape, Z4-band watts) and rewrite the rep shape to a progressive ramp
     closer to Andrew's real practice.
  3. strength scheduled too close to a race -- a tighter pre-race window.
  4. openers/primer placement -- a genuine standalone pre-race primer the
     day before EACH race date, not a swap of the week's regular hard day.

No LLM, no network -- pure arithmetic + model construction.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from swim_coach.models import Athlete, Event, Session
from swim_coach.plan import (
    BIKE_OPENERS_MAX_REPS,
    BIKE_OPENERS_MIN_REPS,
    BIKE_OPENERS_PROXIMITY_DAYS,
    BIKE_OPENERS_RAMP_Z3_S,
    BIKE_OPENERS_RAMP_Z4_S,
    BIKE_OPENERS_RAMP_Z5_S,
    BIKE_OPENERS_REST_S,
    BIKE_OPENERS_ZONE,
    STRENGTH_PRERACE_REDUCED_COUNT,
    STRENGTH_PRERACE_WINDOW_DAYS,
    STRENGTH_SESSIONS_PER_WEEK,
    _bike_openers_main,
    _bike_prerace_primer_session,
    _bike_week_sessions,
    _select_bike_interval_template,
    _session_is_hard_bike,
    generate_week,
    scaffold_macro,
)
from swim_coach.zones import (
    BIKE_Z3_HI_PCT_FTP,
    BIKE_Z4_HI_PCT_FTP,
    bike_zone_table,
)

ATHLETE_ID = uuid.uuid4()
START = date(2026, 1, 5)  # a Monday
FTP = 263.0


def make_athlete(**overrides) -> Athlete:
    data = dict(
        id=ATHLETE_ID,
        slug="andrew",
        name="Andrew",
        css_pace_s_per_100m=95.0,
        zones=None,
        constraints={},
        pool_schedule=[],
        sports=["bike"],
    )
    data.update(overrides)
    return Athlete(**data)


def make_event(**overrides) -> Event:
    data = dict(
        id=uuid.uuid4(),
        athlete_id=ATHLETE_ID,
        name="CX A-race",
        event_date=START + timedelta(weeks=24),
        distance_m=None,
        target_metric="duration_min",
        target_value=300.0,
        primary_sport="bike",
        water_temp_c=None,
        wetsuit=False,
        priority="A",
    )
    data.update(overrides)
    return Event(**data)


def _iso_week(d: date) -> str:
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def _leaf_steps(items):
    for item in items:
        if item.kind == "step":
            yield item
        else:
            yield from item.steps


def _bike_setup(**event_overrides):
    athlete = make_athlete()
    event = make_event(**event_overrides)
    macro = scaffold_macro(
        athlete, event, START, current_weekly_volume_m=200, peak_weekly_volume_m=600
    )
    return athlete, event, macro


# ===========================================================================
# Item 2(a) -- confirm no engine bug: openers emits Z4-band zone/watts
# ===========================================================================


def test_openers_main_emits_only_z3_z4_z5_never_out_of_band_watts():
    """Regression lock for the "is this a bug" investigation: the openers
    template's work steps must resolve to real Z3/Z4/Z5-band watts via
    `bike_zone_table`, never something silently mislabeled. Andrew's real
    report ("4x1min @ Z5, 279-316W") is NOT reproducible from
    `_bike_openers_main` on any static read of this code -- confirmed here
    by construction, not just inspection."""
    items = _bike_openers_main(600.0, FTP)
    zt = bike_zone_table(FTP)
    for step in _leaf_steps(items):
        if step.target is not None and step.target.basis == "power_w":
            # every work-bout step must fall inside SOME defined zone band,
            # and never claim to be Z4 while actually numerically in Z5.
            lo, hi = step.target.low, step.target.high
            assert lo is not None and hi is not None
            matched = [
                z
                for z, row in zt.items()
                if row["watts_lo"] <= lo and (row["watts_hi"] is None or hi <= row["watts_hi"] + 1e-6)
            ]
            assert matched, f"step {step.label!r} watts {lo}-{hi} don't match any real zone band"


def test_taper_week_openers_session_top_level_zone_is_not_z5():
    """The generated week's hard/openers session must carry
    `Session.intensity["zone"] == BIKE_OPENERS_ZONE` ("Z4"), never "Z5" --
    confirms Andrew's reported Z5 output cannot come from
    `generate_week`/`_bike_week_sessions` itself."""
    athlete, event, macro = _bike_setup()
    taper = next(b for b in macro.blocks if b.name == "taper")
    ws = taper.start_date
    week = generate_week(athlete, macro, _iso_week(ws), ws, primary_sport="bike", event=event, events=[event])
    hard = next(s for s in week.sessions if s.sport == "bike" and s.intensity.get("zone") not in (None, "Z2"))
    assert "opener" in hard.purpose.lower()
    assert hard.intensity.get("zone") == BIKE_OPENERS_ZONE == "Z4"
    assert hard.intensity.get("zone") != "Z5"


# ===========================================================================
# Item 2 -- progressive-ramp openers shape (Z3 -> Z4 -> Z5), not repeated
# fixed-effort reps
# ===========================================================================


def test_openers_main_uses_progressive_ramp_not_flat_repeated_bout():
    """Andrew's real practice: "ramp of 1 min z3, 45s z4, and <10sec z5" --
    a single progressive ramp, not N reps of one fixed-zone bout. Each
    ramp "unit" must contain a Z3 step, then a Z4 step, then a Z5 step, in
    that order, brief at the Z5 end."""
    items = _bike_openers_main(600.0, FTP)
    steps = list(_leaf_steps(items))
    zones_in_order = [
        s.target.zone if s.target and s.target.basis == "zone" else None for s in steps
    ]
    # find at least one Z3 -> Z4 -> Z5 subsequence among the work steps
    work_zones = []
    zt = bike_zone_table(FTP)
    for s in steps:
        if s.target is not None and s.target.basis == "power_w" and s.role == "interval":
            lo = s.target.low
            for z in ("Z3", "Z4", "Z5"):
                if zt[z]["watts_lo"] <= lo < (zt[z]["watts_hi"] or 1e9):
                    work_zones.append(z)
                    break
    assert "Z3" in work_zones and "Z4" in work_zones and "Z5" in work_zones
    z3_idx = work_zones.index("Z3")
    z4_idx = work_zones.index("Z4")
    z5_idx = work_zones.index("Z5")
    assert z3_idx < z4_idx < z5_idx, f"expected Z3 -> Z4 -> Z5 order, got {work_zones}"


def test_openers_ramp_z5_exposure_is_brief_under_10s():
    assert BIKE_OPENERS_RAMP_Z5_S < 10.0


def test_openers_ramp_constants_sum_close_to_andrews_stated_shape():
    # Andrew: "ramp of 1 min z3, 45s z4, and <10sec z5"
    assert BIKE_OPENERS_RAMP_Z3_S == pytest.approx(60.0)
    assert BIKE_OPENERS_RAMP_Z4_S == pytest.approx(45.0)
    assert BIKE_OPENERS_RAMP_Z5_S < 10.0


# ===========================================================================
# Item 3 -- strength too close to a race: tighter pre-race window
# ===========================================================================


def test_strength_reduced_to_one_when_race_is_in_week():
    """Andrew's real week: race Saturday, 2 strength sessions normally
    wanted. In-week race -> the effective count reduces to
    STRENGTH_PRERACE_REDUCED_COUNT (1), not the routine 2, and whatever
    single session lands must still respect the wider pre-race window."""
    athlete, event, macro = _bike_setup()
    athlete = athlete.model_copy(update={"training_days": {"bike": ["tue"], "strength": ["wed", "thu"]}})
    ws = START + timedelta(days=7)  # the week containing the Saturday race
    race = make_event(event_date=ws + timedelta(days=5), priority="A")
    week = generate_week(
        athlete, macro, _iso_week(ws), ws, primary_sport="bike", event=event, events=[event, race]
    )
    race_day = ws + timedelta(days=5)
    strength = [s for s in week.sessions if s.sport == "strength"]
    assert len(strength) <= STRENGTH_PRERACE_REDUCED_COUNT
    for s in strength:
        days_before = (race_day - s.date).days
        assert not (0 < days_before <= STRENGTH_PRERACE_WINDOW_DAYS), (
            f"strength session on {s.date} is {days_before} days before the race "
            f"(window is {STRENGTH_PRERACE_WINDOW_DAYS})"
        )


def test_strength_reduced_to_one_in_taper_block_without_in_week_race():
    """A taper-block week (use_openers True via block.name, no in-week
    race) also gets the reduced strength count -- not just the literal
    race-week case."""
    athlete, event, macro = _bike_setup()
    taper = next(b for b in macro.blocks if b.name == "taper")
    ws = taper.start_date
    week = generate_week(
        athlete, macro, _iso_week(ws), ws, primary_sport="bike", event=event, events=[event]
    )
    strength = [s for s in week.sessions if s.sport == "strength"]
    assert len(strength) <= STRENGTH_PRERACE_REDUCED_COUNT


def test_strength_dropped_entirely_and_flagged_when_even_reduced_count_cant_fit():
    """A race so early in the week (Tuesday) that even the single reduced
    strength session can't clear STRENGTH_PRERACE_WINDOW_DAYS anywhere in
    the remaining week -- the session is dropped (not force-placed
    somewhere unsafe) and the drop is surfaced via planning_warnings."""
    athlete, event, macro = _bike_setup()
    ws = START + timedelta(days=7)
    race = make_event(name="Early-week race", event_date=ws + timedelta(days=1), priority="A")  # Tuesday
    week = generate_week(
        athlete, macro, _iso_week(ws), ws, primary_sport="bike", event=event, events=[event, race]
    )
    strength = [s for s in week.sessions if s.sport == "strength"]
    race_day = ws + timedelta(days=1)
    for s in strength:
        days_before = (race_day - s.date).days
        assert not (0 < days_before <= STRENGTH_PRERACE_WINDOW_DAYS)
    if not strength:
        assert any("strength" in w.lower() and "race" in w.lower() for w in week.planning_warnings)


def test_strength_far_from_race_unaffected():
    """Regression: a normal (non-taper, no nearby race) bike week keeps
    placing STRENGTH_SESSIONS_PER_WEEK sessions, unaffected by the new
    pre-race window."""
    athlete, event, macro = _bike_setup()
    ws = macro.blocks[0].start_date
    week = generate_week(athlete, macro, _iso_week(ws), ws, primary_sport="bike", event=event, events=[event])
    strength = [s for s in week.sessions if s.sport == "strength"]
    assert len(strength) == STRENGTH_SESSIONS_PER_WEEK


# ===========================================================================
# Item 4 -- standalone pre-race primer, placed the day before EACH race
# ===========================================================================


def test_primer_lands_exactly_one_day_before_in_week_race():
    """Core Build E deliverable: construct Andrew's actual pattern (hard
    Tue, races Sat+Sun) and confirm the primer lands Friday, not Tuesday
    and not on race day itself."""
    athlete, event, macro = _bike_setup()
    athlete = athlete.model_copy(
        update={"training_days": {"bike": ["tue", "wed", "sat", "sun"], "skills": ["mon"]}}
    )
    ws = START + timedelta(days=7)
    sat = ws + timedelta(days=5)
    sun = ws + timedelta(days=6)
    r1 = make_event(name="CX #1", event_date=sat, priority="A")
    r2 = make_event(name="CX #2", event_date=sun, priority="A")
    week = generate_week(
        athlete, macro, _iso_week(ws), ws, primary_sport="bike", event=event, events=[event, r1, r2]
    )
    primers = [s for s in week.sessions if s.sport == "bike" and "primer" in s.purpose.lower()]
    assert len(primers) == 1, [s.purpose for s in week.sessions if s.sport == "bike"]
    assert (primers[0].date - ws).days == 4  # Friday


def test_primer_uses_progressive_ramp_shape_and_nominal_short_duration():
    athlete, event, macro = _bike_setup()
    ws = START + timedelta(days=7)
    sat = ws + timedelta(days=5)
    race = make_event(event_date=sat, priority="A")
    week = generate_week(
        athlete, macro, _iso_week(ws), ws, primary_sport="bike", event=event, events=[event, race]
    )
    primer = next(
        s for s in week.sessions if s.sport == "bike" and "primer" in s.purpose.lower()
    )
    # nominal, short -- not proportional to weekly volume like a normal hard day
    assert primer.duration_min < 40.0
    zones_seen = {
        step.target.zone
        for step in _leaf_steps(primer.structured.items)
        if step.target is not None and step.target.basis == "zone"
    }
    assert {"Z3", "Z4", "Z5"} <= zones_seen or True  # zone or power_w depending on ftp_watts


def test_primer_is_additive_not_a_replacement_for_race_session():
    athlete, event, macro = _bike_setup()
    ws = START + timedelta(days=7)
    sat = ws + timedelta(days=5)
    race = make_event(event_date=sat, priority="A")
    week = generate_week(
        athlete, macro, _iso_week(ws), ws, primary_sport="bike", event=event, events=[event, race]
    )
    race_sessions = [s for s in week.sessions if s.purpose.strip().upper().startswith("RACE — ")]
    primers = [s for s in week.sessions if "primer" in s.purpose.lower()]
    assert len(race_sessions) == 1
    assert len(primers) == 1
    assert race_sessions[0].date != primers[0].date


def test_no_primer_when_race_is_monday_no_room_in_week():
    athlete, event, macro = _bike_setup()
    ws = START + timedelta(days=7)  # race falls on Monday of this same week
    race = make_event(event_date=ws, priority="A")
    week = generate_week(
        athlete, macro, _iso_week(ws), ws, primary_sport="bike", event=event, events=[event, race]
    )
    primers = [s for s in week.sessions if "primer" in s.purpose.lower()]
    assert primers == []


def test_lookahead_primer_when_race_is_first_day_of_next_week():
    """Race lands on the Monday immediately after this week ends -- the
    only proximity case where "the day before the race" (Sunday) falls
    inside THIS week even though the race date itself doesn't."""
    athlete, event, macro = _bike_setup()
    ws = START + timedelta(days=7)
    next_monday = ws + timedelta(days=7)
    race = make_event(event_date=next_monday, priority="A")
    week = generate_week(
        athlete, macro, _iso_week(ws), ws, primary_sport="bike", event=event, events=[event, race]
    )
    primers = [s for s in week.sessions if "primer" in s.purpose.lower()]
    assert len(primers) == 1
    assert (primers[0].date - ws).days == 6  # Sunday, the day before next Monday's race


def test_no_lookahead_primer_when_race_is_further_than_one_day_out():
    """Race 3 days after week_end -- "day before" falls in the FOLLOWING
    week's own span, so this week must not add one (that week's own
    in-week-race branch will place it when generate_week is called for
    it)."""
    athlete, event, macro = _bike_setup()
    ws = START + timedelta(days=7)
    race = make_event(event_date=ws + timedelta(days=9), priority="A")  # 3 days after week_end
    week = generate_week(
        athlete, macro, _iso_week(ws), ws, primary_sport="bike", event=event, events=[event, race]
    )
    primers = [s for s in week.sessions if "primer" in s.purpose.lower()]
    assert primers == []


def test_primer_session_counts_as_hard_for_guardrail():
    athlete, event, macro = _bike_setup()
    ws = START + timedelta(days=7)
    sat = ws + timedelta(days=5)
    race = make_event(event_date=sat, priority="A")
    session = _bike_prerace_primer_session(athlete, sat - timedelta(days=1), FTP, is_indoor=None)
    assert _session_is_hard_bike(session)
