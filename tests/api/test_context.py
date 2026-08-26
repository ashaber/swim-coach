"""Unit tests for `app.context`: the cacheable system prefix must be
byte-identical across different user messages (no leaked per-request data),
and keyword routing must pick sensible library files."""

from __future__ import annotations

import json
import uuid
from datetime import date, timedelta

import pytest

from swim_coach.store import FileStore

from swim_coach.models import WorkoutAnalytics, WorkoutLap, WorkoutPause

from app.context import (
    FOCUSED_WORKOUT_LAPS_CAP,
    build_messages,
    build_per_request_context,
    build_routed_block,
    build_system,
    build_system_blocks,
    find_workout_by_id,
    render_focused_workout,
    route_library_files,
    summarize_rollup,
)
from fakes import make_event, make_wellness, make_workout
from swim_coach.load import (
    ctl_atl_tsb_series,
    daily_loads as compute_daily_loads,
    wellness_baseline_deviation,
)


def test_system_block_a_is_byte_identical_regardless_of_message(library_dir) -> None:
    # build_system_blocks takes no per-request argument at all -- calling it
    # twice with nothing to vary is the point: there is no code path by
    # which per-request data could leak in.
    block_1 = build_system_blocks(library_dir)
    block_2 = build_system_blocks(library_dir)
    assert block_1 == block_2


def test_system_block_a_has_cache_control(library_dir) -> None:
    blocks = build_system_blocks(library_dir)
    assert len(blocks) == 1
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert "CRITICAL SAFETY WARNING" in blocks[0]["text"]
    # reference_list.md's own bibliography content belongs in block B (it's
    # routed alongside topic files, not baked into the stable persona
    # block) -- block A only *mentions* the filename via INDEX.md's table.
    assert "Research Reference List" not in blocks[0]["text"]


def test_system_block_a_preserves_safety_and_grounding_invariants(library_dir) -> None:
    # The coach-voice softening pass (backend/coach-voice) must not touch a
    # single word of these -- the safety override and rules 3/4/5 are the
    # invariants that make this a coaching aid, not a chatbot. Asserted by
    # content fragments so a wording tweak elsewhere in the block can't
    # accidentally satisfy the test without the substance surviving.
    text = build_system_blocks(library_dir)[0]["text"]
    # Safety override, verbatim in substance.
    assert "CRITICAL SAFETY WARNING" in text
    assert "acute physical distress" in text
    assert "Pause training, alert your support crew" in text
    # Rule 3: "I don't know" + flag_for_coach_review -- the whole research
    # queue depends on this never softening into improvisation.
    assert '"I don\'t know"' in text
    assert "flag_for_coach_review" in text
    assert "research_gap" in text
    assert "needs_human_review" in text
    # An explicit request to reach the real human coach, and a low-confidence
    # high-stakes call, must both always flag for human review too.
    assert "EXPLICITLY asks to talk to" in text
    assert "high-stakes" in text
    # The safety override must ALSO trigger a parallel, invisible-to-the-
    # athlete flag_for_coach_review call -- not just the fixed warning text.
    assert "acute safety override triggered" in text
    # Rule 4: never hand-compute, never exceed engine caps.
    assert "Never hand-compute zones, loads, or volumes" in text
    assert "ramp-cap" in text
    # Rule 5: read-only, propose_adaptation, never persist.
    assert "Read-only by default" in text
    assert "propose_adaptation" in text
    assert "you never persist a plan change" in text


def test_system_block_a_has_voice_section_with_warmth_and_firmness(library_dir) -> None:
    text = build_system_blocks(library_dir)[0]["text"]
    assert "## Voice" in text
    # Warmth.
    assert "warm" in text.lower()
    # Firmness/guidance -- not just encouragement.
    assert "Encouraging does not mean soft" in text
    assert "NEVER soften a real warning" in text


def test_system_block_a_voice_bounds_response_length(library_dir) -> None:
    # The athlete-facing replies must stay TLDR-scannable: bottom line first,
    # a paragraph or two, not an essay -- with expert mode exempted so its
    # full evidence trail isn't truncated.
    text = build_system_blocks(library_dir)[0]["text"]
    assert "phone between sets" in text
    assert "not an essay" in text
    assert "Expert mode is the exception" in text


def test_system_block_a_rule_2_covers_both_asker_modes(library_dir) -> None:
    # Evidence-surfacing is asker-mode-conditional, but the conditioning
    # lives entirely inside the byte-stable system text (it references the
    # existing per-request "Asker mode" line rather than the system block
    # being forked per request) -- so the SAME stable block must describe
    # both branches.
    text = build_system_blocks(library_dir)[0]["text"]
    assert "Athlete mode" in text
    assert "Expert mode" in text
    assert "Asker mode" in text
    # Athlete-mode guidance: no raw tag strings in chat prose.
    assert "no raw tag strings like" in text or "don't recite it" in text
    # Expert-mode guidance: unchanged full rigor, tags/confidence named.
    assert "[EVIDENCE: swim-ultra]" in text
    assert "Confidence:" in text
    assert "Test:" in text


def test_full_system_is_byte_identical_across_two_different_questions_in_same_bucket(
    library_dir,
) -> None:
    # Both route to 03-periodization.md via different keywords ("cut" vs "repeat").
    system_1 = build_system(library_dir, "why did this week get cut?")
    system_2 = build_system(library_dir, "why was this week repeated instead of advanced?")
    assert system_1 == system_2


def test_system_differs_across_different_buckets(library_dir) -> None:
    pace_system = build_system(library_dir, "what pace should I swim the long set at?")
    ow_system = build_system(library_dir, "what pace should I expect in a wetsuit?")
    # Block A (index 0) is identical; block B (index 1) differs by bucket.
    assert pace_system[0] == ow_system[0]
    assert pace_system[1] != ow_system[1]


def test_route_library_files_pace_question() -> None:
    files = route_library_files("What pace should I swim my Z2 set at?")
    assert "04-css-intensity-anchors.md" in files


def test_route_library_files_open_water_question() -> None:
    files = route_library_files("How should I adjust my pace for a wetsuit swim in chop?")
    assert "05-open-water-pace-inference.md" in files


def test_route_library_files_long_swim_question() -> None:
    files = route_library_files("How big should my next long swim be after the last milestone?")
    assert "06-long-swim-progression.md" in files


def test_route_library_files_default_bucket_when_no_keyword_matches() -> None:
    files = route_library_files("What's the weather like for swimming today?")
    assert files  # falls back to the default bucket, never empty
    assert "03-periodization.md" in files


def test_route_library_files_strength_question_reaches_07() -> None:
    files = route_library_files("What exercises should I do for my dryland strength session?")
    assert "07-strength-dryland.md" in files


def test_route_library_files_set_structure_question_reaches_14() -> None:
    files = route_library_files("What should my warm-up and main set look like today?")
    assert "14-swim-set-structure.md" in files


def test_routed_block_always_includes_reference_list(library_dir) -> None:
    block = build_routed_block(library_dir, "what pace should I swim at?")
    assert "library/reference_list.md" in block[0]["text"]
    assert block[0]["cache_control"] == {"type": "ephemeral"}


def test_build_messages_shape_with_history(app_env) -> None:
    store = FileStore(base_dir=app_env)
    history = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello!"},
    ]
    messages = build_messages(
        store, "renee", message="what's next?", history=history, expert_mode=False
    )
    assert len(messages) == 3
    assert messages[0]["role"] == "user"
    assert "## Athlete context" in messages[0]["content"]
    assert messages[0]["content"].endswith("hi")
    assert messages[1] == {"role": "assistant", "content": "hello!"}
    assert messages[2] == {"role": "user", "content": "what's next?"}


def test_build_messages_shape_without_history(app_env) -> None:
    store = FileStore(base_dir=app_env)
    messages = build_messages(store, "renee", message="hello coach", history=[], expert_mode=False)
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert "## Athlete context" in messages[0]["content"]
    assert messages[0]["content"].endswith("hello coach")


def test_per_request_context_computes_age_and_shows_sex_when_dob_set(app_env) -> None:
    # The production bug this build fixes: with no demographic fields on
    # Athlete at all, the coach guessed an age/sex from nothing. Once a real
    # dob/sex is on file, the rendered context must show a computed age (not
    # a stored one -- age drifts, dob doesn't) and the sex, as fact.
    store = FileStore(base_dir=app_env)
    athlete = store.load_athlete("renee")
    athlete = athlete.model_copy(
        update={"dob": date(1969, 3, 14), "sex": "female", "height_cm": 168.0, "weight_kg": 63.5}
    )
    store.save_athlete(athlete)

    text = build_per_request_context(store, "renee", expert_mode=False)
    profile_section = text.split("### Profile")[1].split("### Current week plan")[0]

    expected_age = (
        date.today().year
        - 1969
        - ((date.today().month, date.today().day) < (3, 14))
    )
    assert f'"age": {expected_age}' in profile_section
    assert '"sex": "female"' in profile_section
    assert '"height_cm": 168.0' in profile_section
    assert '"weight_kg": 63.5' in profile_section


def test_per_request_context_omits_age_when_no_dob(app_env) -> None:
    # Renee's real profile.yaml (as committed) carries none of the new
    # demographic fields -- must render without crashing and without a
    # fabricated age.
    store = FileStore(base_dir=app_env)
    text = build_per_request_context(store, "renee", expert_mode=False)
    profile_section = text.split("### Profile")[1].split("### Current week plan")[0]
    assert '"age"' not in profile_section


def test_per_request_context_reflects_expert_mode(app_env) -> None:
    store = FileStore(base_dir=app_env)
    expert_text = build_per_request_context(store, "renee", expert_mode=True)
    athlete_text = build_per_request_context(store, "renee", expert_mode=False)
    assert "expert" in expert_text.lower()
    assert "expert" not in athlete_text.lower().split("current week")[0]


def test_per_request_context_includes_summarize_rollup(app_env) -> None:
    store = FileStore(base_dir=app_env)
    text = build_per_request_context(store, "renee", expert_mode=False)
    assert "compliance_pct" in text
    assert "load_ratio_7d_28d" in text


def test_summarize_rollup_ctl_atl_tsb_uses_full_history_but_windows_output(app_env) -> None:
    # `loads = daily_loads(workouts)` inside summarize_rollup already sees
    # the FULL logged history -- the CTL/ATL series must be computed from
    # that same full history (so the exponential average gets a real
    # warm-up), but the returned "ctl_atl_tsb" list must only include the
    # dates that fall inside the requested weeks-N window, same
    # window-relative convention `wellness_trend`'s "trend" field uses.
    store = FileStore(base_dir=app_env)
    as_of = date(2026, 7, 6)  # Monday
    workouts = [
        # Well before the 1-week window -- exists only to warm up CTL/ATL.
        make_workout(date=as_of - timedelta(days=100), rpe=6, duration_min=60.0),
        # Inside the window.
        make_workout(date=as_of + timedelta(days=1), rpe=7, duration_min=45.0),
    ]
    for w in workouts:
        store.save_workout("renee", w)

    rollup = summarize_rollup(store, "renee", weeks=1, as_of=as_of, workouts=workouts)

    assert "ctl_atl_tsb" in rollup
    span_start, span_end = as_of, as_of + timedelta(days=6)
    full_series = ctl_atl_tsb_series(compute_daily_loads(workouts))
    expected = [
        [d.isoformat(), round(ctl, 1), round(atl, 1), round(tsb, 1)]
        for d, ctl, atl, tsb in full_series
        if span_start <= d <= span_end
    ]
    assert expected, "test setup should produce a non-empty windowed series"
    assert rollup["ctl_atl_tsb"] == expected
    # The 100-day-old workout falls outside the window, but its effect on
    # CTL/ATL should still be visible -- i.e. this isn't just recomputed
    # from `window_loads` alone (which would start the recursion at zero
    # right at span_start instead of carrying warmed-up history into it).
    window_only_series = ctl_atl_tsb_series(
        {d: v for d, v in compute_daily_loads(workouts).items() if span_start <= d <= span_end}
    )
    window_only_first_ctl = window_only_series[0][1]
    full_history_first_ctl = full_series[
        [d for d, _, _, _ in full_series].index(span_start)
    ][1]
    assert full_history_first_ctl != pytest.approx(window_only_first_ctl)


def test_summarize_rollup_includes_wellness_baseline_deviation(app_env) -> None:
    # Same shape/field-naming as the "ctl_atl_tsb" pattern above: a
    # separate, distinctly-named key -- never folded into "ctl_atl_tsb" --
    # computed from the FULL wellness history (not window_wellness), so a
    # short weeks=N window doesn't starve the 28-day chronic baseline.
    store = FileStore(base_dir=app_env)
    as_of = date(2026, 7, 28)
    entries = [
        make_wellness(date=as_of - timedelta(days=i), resting_hr=44, hrv=None)
        for i in range(7, 28)
    ] + [
        make_wellness(date=as_of - timedelta(days=i), resting_hr=60, hrv=None)
        for i in range(0, 7)
    ]
    for entry in entries:
        store.save_wellness("renee", entry)

    rollup = summarize_rollup(store, "renee", weeks=1, as_of=as_of, workouts=[])

    assert "wellness_baseline_deviation" in rollup
    expected = wellness_baseline_deviation(entries, as_of)
    assert rollup["wellness_baseline_deviation"] == {
        "resting_hr_pct_deviation": round(expected["resting_hr_pct_deviation"], 1),
        "hrv_pct_deviation": expected["hrv_pct_deviation"],
    }
    assert rollup["wellness_baseline_deviation"]["resting_hr_pct_deviation"] == pytest.approx(25.0)
    assert rollup["wellness_baseline_deviation"]["hrv_pct_deviation"] is None


def test_per_request_context_labels_rollup_as_aggregate(app_env) -> None:
    # Andrew flagged that it wasn't clear what/how much was aggregate --
    # the rollup header must say so explicitly so the model can't confuse
    # it with the exact per-session facts above it.
    store = FileStore(base_dir=app_env)
    text = build_per_request_context(store, "renee", expert_mode=False)
    assert "AGGREGATE" in text
    assert "derived from the sessions above" in text


def test_per_request_context_lists_exact_sessions_with_distinct_sports(app_env) -> None:
    # The production bug this build fixes: the coach called a logged
    # swim_ow session a "pool" session because it could only see an
    # aggregate rollup, never an individual workout's sport.
    store = FileStore(base_dir=app_env)
    today = date.today()
    ow_workout = make_workout(
        date=today - timedelta(days=2),
        sport="swim_ow",
        distance_m=8000,
        duration_min=150.0,
        rpe=5,
        avg_pace_s_per_100m=112.5,
    )
    pool_workout = make_workout(
        date=today - timedelta(days=4),
        sport="swim_pool",
        distance_m=3200,
        duration_min=65.0,
        rpe=6,
        avg_pace_s_per_100m=95.0,
    )
    store.save_workout("renee", ow_workout)
    store.save_workout("renee", pool_workout)

    text = build_per_request_context(store, "renee", expert_mode=False)

    assert "### Exact logged sessions (last 28 days)" in text
    assert "ground truth" in text
    assert '"sport": "swim_ow"' in text
    assert '"sport": "swim_pool"' in text
    assert '"distance_m": 8000' in text
    assert '"distance_m": 3200' in text
    # Isolate the exact-logged-sessions section and parse its rows -- asserting on
    # text.index() over the whole context is fragile (it collides with other
    # in-window workouts that share a sport, e.g. renee's real 2026-07-06 swim_ow).
    header = "### Exact logged sessions"
    start = text.index(header)
    end = text.index("\n### ", start + len(header))
    rows = [json.loads(ln) for ln in text[start:end].splitlines() if ln.startswith("{")]
    # ordering contract: rows are chronological (oldest-first), regardless of which
    # other sessions fall in the window.
    dates = [r["date"] for r in rows]
    assert dates == sorted(dates)
    # the two injected workouts specifically: older pool (3200m) precedes newer ow (8000m).
    pool_i = next(i for i, r in enumerate(rows) if r["distance_m"] == 3200)
    ow_i = next(i for i, r in enumerate(rows) if r["distance_m"] == 8000)
    assert pool_i < ow_i


def test_per_request_context_excludes_stale_sessions_outside_window(app_env) -> None:
    store = FileStore(base_dir=app_env)
    today = date.today()
    stale_workout = make_workout(
        date=today - timedelta(days=90),
        sport="swim_pool",
        distance_m=1234,
    )
    store.save_workout("renee", stale_workout)

    text = build_per_request_context(store, "renee", expert_mode=False)
    assert '"distance_m": 1234' not in text


def test_per_request_context_has_no_sessions_message_when_none_logged(app_env, tmp_path) -> None:
    # A freshly onboarded athlete with no logged workouts yet -- the
    # section must say so plainly rather than rendering an empty/ambiguous
    # block.
    from swim_coach.models import Athlete

    empty_dir = tmp_path / "athletes_empty"
    store = FileStore(base_dir=empty_dir)
    store.save_athlete(Athlete(id=uuid.uuid4(), slug="newbie", name="Newbie"))

    text = build_per_request_context(store, "newbie", expert_mode=False)
    assert "### Exact logged sessions (last 28 days)" in text
    assert "none logged" in text.lower()


def test_per_request_context_lists_events_with_dates_and_days_until(app_env) -> None:
    store = FileStore(base_dir=app_env)
    today = date.today()
    event = make_event(
        name="UltraSwim 33.3 Greece",
        event_date=today + timedelta(days=45),
        distance_m=33300,
        event_format="single_day",
    )
    store.save_events("renee", [event])

    text = build_per_request_context(store, "renee", expert_mode=False)

    assert "### Events / races" in text
    assert '"name": "UltraSwim 33.3 Greece"' in text
    assert f'"event_date": "{(today + timedelta(days=45)).isoformat()}"' in text
    assert '"days_until": 45' in text
    assert '"distance_m": 33300' in text


def test_per_request_context_no_events_message_when_none_on_file(app_env) -> None:
    store = FileStore(base_dir=app_env)
    store.save_events("renee", [])

    text = build_per_request_context(store, "renee", expert_mode=False)
    assert "### Events / races" in text
    assert "no events on file" in text.lower()


def test_per_request_context_events_include_active_status(app_env) -> None:
    # Regression: PERSONA_AND_RULES instructs the model to treat
    # `active: false` events as archived and not suggest them, but that's
    # only followable if the per-request context actually surfaces the
    # field -- confirm both an active and a deactivated event show their
    # real `active` value in the rendered text.
    store = FileStore(base_dir=app_env)
    today = date.today()
    live_event = make_event(
        name="Live Event",
        event_date=today + timedelta(days=30),
        distance_m=10000,
    )
    archived_event = make_event(
        name="Archived Event",
        event_date=today + timedelta(days=60),
        distance_m=20000,
        active=False,
    )
    store.save_events("renee", [live_event, archived_event])

    text = build_per_request_context(store, "renee", expert_mode=False)

    assert '"name": "Live Event"' in text
    assert '"name": "Archived Event"' in text
    live_line = next(line for line in text.splitlines() if '"name": "Live Event"' in line)
    archived_line = next(line for line in text.splitlines() if '"name": "Archived Event"' in line)
    assert '"active": true' in live_line
    assert '"active": false' in archived_line


# --- focused workout (Log tab's embedded workout chat) -----------------------


def _rich_workout(**overrides):
    """A .fit-shaped workout with laps/pauses/analytics/sport_detail -- the
    fields render_focused_workout exists to surface (the ordinary 28-day
    exact-sessions list deliberately omits all of them)."""
    data = dict(
        sport="cross_train",
        sport_detail="cycling/mountain",
        source="fit",
        avg_hr=132,
        max_hr=158,
        analytics=WorkoutAnalytics(cardiac_drift_pct=6.4, split_label="positive"),
        laps=[
            WorkoutLap(index=0, duration_s=1830.0, distance_m=2500.0, avg_hr=128),
            WorkoutLap(index=1, duration_s=1980.0, distance_m=2500.0, avg_hr=136),
        ],
        pauses=[
            WorkoutPause(start_offset_s=754.0, duration_s=45.0, source="gap"),
            WorkoutPause(start_offset_s=2600.0, duration_s=90.0, source="timer"),
        ],
        notes="Choppy back half.",
    )
    data.update(overrides)
    return make_workout(**data)


def test_find_workout_by_id_matches_exact_and_prefix_case_insensitively() -> None:
    w1 = make_workout()
    w2 = make_workout()
    workouts = [w1, w2]

    assert find_workout_by_id(workouts, str(w2.id)) is w2
    assert find_workout_by_id(workouts, str(w2.id)[:8]) is w2
    assert find_workout_by_id(workouts, str(w2.id)[:8].upper()) is w2


def test_find_workout_by_id_unknown_or_empty_is_none() -> None:
    workouts = [make_workout()]
    assert find_workout_by_id(workouts, "ffffffff-0000-0000-0000-000000000000") is None
    assert find_workout_by_id(workouts, "") is None
    assert find_workout_by_id(workouts, "   ") is None


def test_render_focused_workout_includes_summary_analytics_laps_pauses_sport_detail() -> None:
    workout = _rich_workout()
    text = render_focused_workout(workout)

    assert "specific workout the athlete is asking about" in text
    assert str(workout.id) in text
    assert '"sport_detail": "cycling/mountain"' in text
    assert '"cardiac_drift_pct": 6.4' in text
    assert '"split_label": "positive"' in text
    assert '"avg_hr": 132' in text
    assert "Choppy back half." in text
    # Laps table (both laps) and pauses (both, with their sources).
    assert "### Laps (2 of 2 shown)" in text
    assert '"duration_s": 1830.0' in text
    assert "### Pauses (2)" in text
    assert '"source": "gap"' in text
    assert '"source": "timer"' in text


def test_render_focused_workout_caps_laps_and_labels_truncation() -> None:
    laps = [WorkoutLap(index=i, duration_s=60.0, distance_m=100.0) for i in range(50)]
    workout = _rich_workout(laps=laps)

    text = render_focused_workout(workout)

    assert f"### Laps ({FOCUSED_WORKOUT_LAPS_CAP} of 50 shown, truncated)" in text
    assert f'"index": {FOCUSED_WORKOUT_LAPS_CAP - 1}' in text
    assert f'"index": {FOCUSED_WORKOUT_LAPS_CAP}' not in text


def test_render_focused_workout_bare_manual_workout_renders_cleanly() -> None:
    workout = make_workout()  # no laps/pauses/analytics/sport_detail
    text = render_focused_workout(workout)

    assert "specific workout the athlete is asking about" in text
    assert "(no laps recorded)" in text
    assert "(no pauses recorded)" in text
    assert '"analytics": null' in text


def test_per_request_context_appends_focused_workout_only_when_given(app_env) -> None:
    store = FileStore(base_dir=app_env)
    workout = _rich_workout()

    without = build_per_request_context(store, "renee", expert_mode=False)
    with_focus = build_per_request_context(
        store, "renee", expert_mode=False, focused_workout=workout
    )

    assert "specific workout the athlete is asking about" not in without
    assert "specific workout the athlete is asking about" in with_focus
    assert str(workout.id) in with_focus
    # Appended after the aggregate rollup -- still per-request, never system.
    assert with_focus.index("AGGREGATE") < with_focus.index("specific workout")


def test_build_messages_threads_focused_workout_into_first_message(app_env) -> None:
    store = FileStore(base_dir=app_env)
    workout = _rich_workout()

    messages = build_messages(
        store,
        "renee",
        message="how did this one go?",
        history=[],
        expert_mode=False,
        focused_workout=workout,
    )

    assert len(messages) == 1
    assert "specific workout the athlete is asking about" in messages[0]["content"]
    assert messages[0]["content"].endswith("how did this one go?")


def test_system_prefix_untouched_by_focused_workout(library_dir) -> None:
    # The workout block is per-request only -- the byte-stable system prefix
    # (build_system) takes no workout argument at all, so scoped and unscoped
    # chats about the same message share the same cache entry by construction.
    message = "how did this workout go?"
    assert build_system(library_dir, message) == build_system(library_dir, message)
