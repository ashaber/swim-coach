"""Context assembly for the coach chat endpoint, built for prompt caching.

Layout (stable -> volatile, per ROADMAP.md "Chat context assembly" and this
build's task spec):

  System block A (cacheable, byte-stable): coach persona + hard rules
    (grounding/citation/safety, adapted from `.claude/skills/coach/SKILL.md`)
    + full text of `library/00-conventions.md` + `library/INDEX.md`. No
    per-request data ever enters this block -- `build_system_blocks` takes
    no per-request argument at all, which is what guarantees byte-stability
    by construction rather than by convention.

  System block B (cacheable): `library/reference_list.md` (INDEX.md's own
    rule: "always load reference_list.md alongside for citations", so it's
    treated as a routing constant, not a routed file) plus 1-3 topic files
    selected by deterministic keyword-bucket routing against INDEX.md's
    routing table. Same message (or any message landing in the same
    keyword bucket) always produces byte-identical block B text, so common
    topics share a cache entry.

  Per-request (uncached): athlete profile + zones, current + next week
  plan, the exact logged sessions from the trailing ~28 days (each session
  keeps its own `sport`, `distance_m`, `duration_min`, `rpe`,
  `avg_pace_s_per_100m` -- ground truth, not narrated), events/races with
  `days_until`, and the engine's `summarize` rollup -- explicitly labelled
  as an AGGREGATE derived from those same sessions, so exact-vs-aggregate is
  unambiguous to the model (via `summarize_rollup`, which calls straight
  into `swim_coach.load`'s functions -- the same ones `cli.py`'s
  `summarize` command uses -- never recomputed in prose). This is merged
  into the *first* message of the conversation (the first `history` entry
  if there is one, else the new `message`) rather than inserted as a
  separate message, because the Anthropic Messages API requires strictly
  alternating user/assistant roles -- a lone synthetic "user" message in
  front of history's own first (user) message would be two user turns in a
  row and get rejected.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, TypedDict

from swim_coach.load import (
    acute_chronic_ratio,
    compliance as compute_compliance,
    daily_loads,
    monotony,
    weekly_volume_m,
    wellness_trend,
)
from swim_coach.models import Athlete, Event, Workout
from swim_coach.store import StoreInterface

# --- system block A: persona + hard rules -----------------------------------

# Adapted from `.claude/skills/coach/SKILL.md` (Phase 1's /coach skill) --
# same persona, same safety-first override, same grounding rules -- so
# Phase 1 and Phase 2 coaching voice/behavior stay identical. Byte-stable:
# no template variables, no timestamps.
PERSONA_AND_RULES = """\
You are the swim-coach AI coaching agent: conversational coaching grounded in
`library/` (a curated research library) and the athlete's own plan/history.
You explain and advise; you do not silently change the athlete's training
plan. Structural plan changes go through the deterministic adaptation engine
(the `propose_adaptation` tool) and require the athlete's or Andrew's
explicit confirmation before anything is persisted -- you can propose and
discuss a draft, you cannot finalize one.

## Safety first -- acute medical symptoms override everything

If the athlete describes acute physical distress -- chest tightness/pain,
heart palpitations, fainting, or symptoms of heat stroke or hypothermia
(confusion, stopping shivering, slurred speech, severe cramping) -- stop
coaching immediately and respond with ONLY this, nothing else:

> **CRITICAL SAFETY WARNING:** The symptoms you're describing need immediate
> medical evaluation. Pause training, alert your support crew or emergency
> services, and consult a qualified healthcare professional. Do not rely on
> an automated training tool for acute physical distress.

Do not synthesize training advice, pacing, or fueling around an acute-symptom
report. This is not medical advice software; it is a coaching aid for
healthy training. Ordinary training soreness, fatigue, or a niggle is normal
coaching territory -- this override is for acute/alarming symptoms only.

## Voice

You are her coach, not a literature review. She knows you know the research
-- that's not what she needs to hear in every reply. Talk like a coach who
knows her: warm, direct, encouraging. Short sentences. Plain language over
jargon. Lead with the answer, not the preamble.

No hedging stacks -- one caveat, clearly placed, beats three softened
qualifiers around a mushy middle. Say the thing plainly, then the one
reason it matters.

Encouraging does not mean soft. Be not afraid to give necessary guidance --
be firm and specific whenever pain, overreaching, ramp caps, or fueling
adequacy are in play, and anywhere else the situation is safety-adjacent.
If the training call and the athlete's mood pull in different directions,
give the training call straight and let the warmth carry the delivery, not
the content. Encouragement must NEVER soften a real warning -- "let's ease
up on the long swim this week" is a fine warm sentence right up until it
replaces "your load ratio says stop," which it must never do.

This voice section shapes *how* you say things. It never overrides the
safety override above or the grounding rules below -- a warmly-delivered
answer must still be a grounded, accurate one.

## Grounding rules

1. Cite by title + author + year (e.g. "per Wakayoshi et al. (1992)"), never
   by URL or PubMed/PMC ID -- `library/reference_list.md` is the only
   trustworthy citation source in this repository; older sources elsewhere
   in this project contained fabricated identifiers.
2. Every claim still has to be grounded in the library, but how much of the
   evidence machinery you show the asker depends on the "Asker mode" line in
   the per-request context below:
   - **Athlete mode** (the default -- "Asker mode: athlete"): lead with the
     coaching answer in plain language. The claim must still be true to its
     underlying tag, but don't recite it -- no raw tag strings like
     `[ADAPTED: cycling] Confidence: medium` in chat prose, ever. Name the
     evidence level only when it changes what she should actually do (e.g.
     "this one's adapted from cycling research, so treat it as a starting
     point and we'll tune it on your own data") or when she asks where
     something comes from. A `Coach judgment:` call can just be given as
     your judgment, plainly labeled as such in ordinary words ("my call
     here is..."), not as a tag. Citations and evidence tiers are earned by
     relevance, not sprinkled onto every answer.
   - **Expert mode** (a professional coach or physiologist -- "Asker mode:
     expert"): unchanged full rigor, exactly as before. Cite by title +
     author + year, name the tag explicitly (`[EVIDENCE: swim-ultra]`,
     `[ADAPTED: cycling]`, etc.), state the `Confidence:` level and the
     `Test:` line for every adapted claim, and label `Coach judgment:`
     claims as such. Don't soften this rigor just because the voice above
     is warmer -- expert mode is a different asker with a different need.
3. If the library doesn't cover a question, say "I don't know" plainly
   rather than improvising an unsourced answer, give your best coach
   judgment labeled as such if you have one, and call the
   `log_open_question` tool so the gap gets followed up on. This applies
   whether the asker is the athlete or, in expert mode, a professional
   coach/physiologist proposing something the library doesn't yet cover --
   log those too (the tool call's context carries the expert-mode flag
   automatically; you don't need to set it yourself).
4. Never hand-compute zones, loads, or volumes in chat, and never exceed the
   deterministic engine's caps (ramp-cap, long-swim-ladder step cap,
   adaptation rule table). Read the athlete's computed values from the
   context below, or call `get_plan_summary` / `propose_adaptation` for
   anything not already provided.
5. Read-only by default: if the conversation concludes the plan should
   change, say what you'd change and why, call `propose_adaptation` to show
   a concrete draft grounded in the engine's own rule table, and hand off
   for confirmation ("tell me to go ahead and I'll note it for /adapt" or
   "run /adapt to finalize this") -- you never persist a plan change
   yourself.

## Answering

Recommendation first, then the reasoning -- and the citation/evidence level
where rule 2 above says it earns its place for this asker. Keep it to what
was asked. The per-request context below (profile, zones,
current/next week plan, exact logged sessions with their sport, events/races
with dates, and the 28-day AGGREGATE load/wellness/compliance rollup) is the
athlete's current ground truth -- prefer it over asking the athlete to
restate numbers you already have. The exact-session and events sections are
individual facts (e.g. a specific session's sport, or a race's date); the
AGGREGATE rollup is a derived summary of those same sessions -- don't
confuse the two, and don't call a session by the wrong sport when its exact
row is right there. That per-request context only reaches back ~28 days --
if the athlete asks about a specific past workout or date range older than
that, call the `get_workouts` tool rather than saying you have no record of
it; don't call it for recent sessions, they're already above.
"""


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def build_system_blocks(library_dir: Path) -> list[dict[str, Any]]:
    """System block A: persona + rules + 00-conventions.md + INDEX.md, as a
    single cacheable text block. Takes no per-request argument -- this is
    what makes it byte-stable across every request regardless of what the
    athlete asks."""
    conventions = _read_text(library_dir / "00-conventions.md")
    index = _read_text(library_dir / "INDEX.md")
    text = (
        f"{PERSONA_AND_RULES}\n\n"
        f"---\n\n# library/00-conventions.md\n\n{conventions}\n\n"
        f"---\n\n# library/INDEX.md\n\n{index}"
    )
    return [
        {
            "type": "text",
            "text": text,
            "cache_control": {"type": "ephemeral"},
        }
    ]


# --- system block B: routed library topic files -----------------------------

# Mirrors library/INDEX.md's "Topic -> file routing table" as fixed keyword
# buckets rather than parsing the table at request time -- deterministic,
# fast, and the buckets are exactly what INDEX.md documents. If INDEX.md's
# routing table changes, update this dict in the same change (same
# discipline library/00-conventions.md asks of engine-constant citations).
_LIBRARY_FILES_IN_PRIORITY_ORDER = [
    "03-periodization.md",
    "04-css-intensity-anchors.md",
    "05-open-water-pace-inference.md",
    "06-long-swim-progression.md",
]

_KEYWORD_ROUTES: dict[str, set[str]] = {
    "volume": {"03-periodization.md", "06-long-swim-progression.md"},
    "cut": {"03-periodization.md"},
    "repeat": {"03-periodization.md"},
    "advance": {"03-periodization.md"},
    "periodization": {"03-periodization.md"},
    "monoton": {"03-periodization.md"},
    "acwr": {"03-periodization.md"},
    "load": {"03-periodization.md"},
    "compliance": {"03-periodization.md"},
    "consisten": {"03-periodization.md"},
    "taper": {"03-periodization.md"},
    "pace": {"04-css-intensity-anchors.md"},
    "zone": {"04-css-intensity-anchors.md"},
    "css": {"04-css-intensity-anchors.md"},
    "critical swim speed": {"04-css-intensity-anchors.md"},
    "negative split": {"04-css-intensity-anchors.md"},
    "dryland": {"04-css-intensity-anchors.md"},
    "strength": {"04-css-intensity-anchors.md"},
    "wetsuit": {"05-open-water-pace-inference.md"},
    "open water": {"05-open-water-pace-inference.md"},
    "open-water": {"05-open-water-pace-inference.md"},
    "chop": {"05-open-water-pace-inference.md"},
    "cold": {"05-open-water-pace-inference.md"},
    "current": {"05-open-water-pace-inference.md"},
    "tide": {"05-open-water-pace-inference.md"},
    "milestone": {"06-long-swim-progression.md"},
    "long swim": {"06-long-swim-progression.md"},
    "long-swim": {"06-long-swim-progression.md"},
    "stage": {"06-long-swim-progression.md"},
    "single-day": {"06-long-swim-progression.md"},
    "single day": {"06-long-swim-progression.md"},
    "recovery": {"06-long-swim-progression.md", "03-periodization.md"},
}

# Deterministic fallback bucket when no keyword matches -- "why is the plan
# what it is" is the single most common ungrounded question shape, so this
# maximizes cache-hit odds for whatever doesn't match a specific keyword.
DEFAULT_ROUTE_FILES = ["03-periodization.md", "06-long-swim-progression.md"]

MAX_ROUTED_FILES = 3


def route_library_files(message: str, *, max_files: int = MAX_ROUTED_FILES) -> list[str]:
    """Deterministically route `message` to up to `max_files` topic files
    (not counting reference_list.md, which is always included separately).

    Order is fixed by `_LIBRARY_FILES_IN_PRIORITY_ORDER`, not by keyword
    match order, so any two messages that hit the same bucket produce the
    same file list in the same order -- required for the resulting text
    block to be byte-identical (and thus cache-shareable).
    """
    lower = message.lower()
    matched: set[str] = set()
    for keyword, files in _KEYWORD_ROUTES.items():
        if keyword in lower:
            matched |= files
    if not matched:
        matched = set(DEFAULT_ROUTE_FILES)
    ordered = [f for f in _LIBRARY_FILES_IN_PRIORITY_ORDER if f in matched]
    return ordered[:max_files]


def build_routed_block(library_dir: Path, message: str) -> list[dict[str, Any]]:
    """System block B: reference_list.md (always included -- INDEX.md's own
    "always load alongside for citations" rule) plus the routed topic
    files for `message`, as a single cacheable text block."""
    filenames = ["reference_list.md", *route_library_files(message)]
    parts = []
    for filename in filenames:
        content = _read_text(library_dir / filename)
        parts.append(f"# library/{filename}\n\n{content}")
    text = "\n\n---\n\n".join(parts)
    return [
        {
            "type": "text",
            "text": text,
            "cache_control": {"type": "ephemeral"},
        }
    ]


def build_system(library_dir: Path, message: str) -> list[dict[str, Any]]:
    """The full `system` param: block A then block B, each its own cache
    breakpoint (stable prefix first, per Anthropic's prompt-caching rules --
    a cache_control block also implicitly caches everything before it)."""
    return build_system_blocks(library_dir) + build_routed_block(library_dir, message)


# --- engine reuse: summarize rollup -----------------------------------------


def iso_week_str(d: date) -> str:
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def _rollup_window(as_of: date, weeks: int) -> tuple[date, date, list[date]]:
    """The Monday-to-Sunday span covering the trailing `weeks` ISO weeks
    (inclusive of the current, in-progress week). Shared by `summarize_rollup`
    and `build_per_request_context` so the "exact logged sessions" list and
    the aggregate rollup derived from it always cover the identical window --
    a session that appears in one always counts in the other."""
    as_of_monday = as_of - timedelta(days=as_of.weekday())
    week_starts = [as_of_monday - timedelta(weeks=i) for i in range(weeks - 1, -1, -1)]
    span_start = week_starts[0]
    span_end = as_of_monday + timedelta(days=6)
    return span_start, span_end, week_starts


def summarize_rollup(
    store: StoreInterface,
    slug: str,
    *,
    weeks: int = 4,
    as_of: date | None = None,
    workouts: list[Workout] | None = None,
) -> dict[str, Any]:
    """The compact training-load/wellness/compliance rollup, computed with
    the exact same `swim_coach.load` functions `cli.py`'s `summarize`
    command uses (see `_cmd_summarize` in `swim_coach/cli.py`) -- this is
    "reuse the engine" in the literal sense: the math lives in `load.py`,
    this function only assembles the same window/rollup shape around it, it
    never recomputes a formula. Used both for the per-request chat context
    and for the `get_plan_summary` tool.

    `workouts` lets a caller that already fetched the athlete's workouts
    (e.g. `build_per_request_context`, which also renders them as exact
    sessions) pass them in rather than triggering a second `list_workouts`
    round trip; defaults to fetching them here when omitted.
    """
    as_of = date.today() if as_of is None else as_of
    span_start, span_end, week_starts = _rollup_window(as_of, weeks)

    workouts = store.list_workouts(slug) if workouts is None else workouts
    wellness = store.list_wellness(slug)

    volume_by_week = {iso_week_str(ws): weekly_volume_m(workouts, ws) for ws in week_starts}

    loads = daily_loads(workouts)
    window_loads = {d: v for d, v in loads.items() if span_start <= d <= span_end}
    monotony_value = monotony(window_loads)
    load_ratio = acute_chronic_ratio(workouts, as_of)

    window_wellness = [w for w in wellness if span_start <= w.date <= span_end]
    trend = wellness_trend(window_wellness)

    planned_sessions = []
    for ws in week_starts:
        week_plan = store.load_week(slug, iso_week_str(ws))
        if week_plan is not None:
            planned_sessions.extend(week_plan.sessions)
    window_workouts = [w for w in workouts if span_start <= w.date <= span_end]
    compliance_pct = (
        compute_compliance(planned_sessions, window_workouts) if planned_sessions else None
    )

    return {
        "athlete": slug,
        "as_of": as_of.isoformat(),
        "weeks": weeks,
        "volume_m": volume_by_week,
        "srpe_load_by_day": {d.isoformat(): v for d, v in sorted(window_loads.items())},
        "load_ratio_7d_28d": load_ratio,
        "monotony": monotony_value,
        "wellness_trend": [[d.isoformat(), v] for d, v in trend],
        "compliance_pct": compliance_pct,
    }


# --- per-request context -----------------------------------------------------


def _week_or_none(store: StoreInterface, slug: str, iso_week: str) -> dict[str, Any] | None:
    week = store.load_week(slug, iso_week)
    return week.model_dump(mode="json") if week is not None else None


def _render_recent_sessions(workouts: list[Workout], span_start: date, span_end: date) -> str:
    """Compact, chronological, one-row-per-workout rendering of every
    exactly-logged session in `[span_start, span_end]` -- each row keeps its
    own `sport`, which is exactly what the aggregate rollup below throws
    away. This is what lets the model tell a `swim_ow` session from a
    `swim_pool` one instead of guessing from volume alone."""
    window = sorted(
        (w for w in workouts if span_start <= w.date <= span_end), key=lambda w: w.date
    )
    if not window:
        return "(none logged in this window)"
    rows = [
        json.dumps(
            {
                "date": w.date.isoformat(),
                "sport": w.sport,
                "distance_m": w.distance_m,
                "duration_min": w.duration_min,
                "rpe": w.rpe,
                "avg_pace_s_per_100m": w.avg_pace_s_per_100m,
            }
        )
        for w in window
    ]
    return "\n".join(rows)


def _compute_age(dob: date, today: date) -> int:
    """Whole years elapsed from `dob` to `today` -- the ordinary "birthday
    hasn't happened yet this year" adjustment."""
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def _render_demographics(athlete: Athlete, today: date) -> str | None:
    """A compact derived-facts line so the model reads age/sex/height/weight
    as ground truth instead of guessing (the production bug this build
    fixes). Age is computed from `dob` relative to `today` rather than
    stored, so it never goes stale. Returns None when nothing is on file so
    the caller can omit the line entirely rather than render an empty one."""
    facts: dict[str, Any] = {}
    if athlete.dob is not None:
        facts["age"] = _compute_age(athlete.dob, today)
    if athlete.sex is not None:
        facts["sex"] = athlete.sex
    if athlete.height_cm is not None:
        facts["height_cm"] = athlete.height_cm
    if athlete.weight_kg is not None:
        facts["weight_kg"] = athlete.weight_kg
    if not facts:
        return None
    return json.dumps(facts)


def _render_events(events: list[Event], today: date) -> str:
    """Compact, chronological rendering of every event on file, each with
    `days_until` computed relative to `today` -- fixes the coach not
    knowing race dates."""
    if not events:
        return "(no events on file)"
    ordered = sorted(events, key=lambda e: e.event_date)
    rows = [
        json.dumps(
            {
                "name": e.name,
                "event_date": e.event_date.isoformat(),
                "distance_m": e.distance_m,
                "event_format": e.event_format,
                "days_until": (e.event_date - today).days,
            }
        )
        for e in ordered
    ]
    return "\n".join(rows)


# --- focused workout (Log tab's embedded workout chat) ----------------------
# A scoped chat tied to one already-logged workout (the detail view's "Ask
# your coach about this workout" section) needs the model to see that ONE
# workout's full detail -- not just whatever compact facts happen to fall
# out of the ordinary 28-day exact-sessions list above (which omits laps/
# pauses/full analytics, and won't even include it at all if it's older than
# 28 days). This section stays per-request (uncached), same as the rest of
# `build_per_request_context` -- never in the byte-stable system prefix
# (`build_system_blocks`/`build_routed_block` above), since it's specific to
# one request's workout_id and would otherwise poison the cache key for
# every other request.

# A long open-water swim can log dozens to hundreds of GPS-derived laps;
# this bounds the table the same way the coach's get_workouts tool bounds
# workout counts (app.tools.GET_WORKOUTS_CAP) -- the model doesn't need
# per-lap-beyond-this granularity to discuss the session, and an unbounded
# table would dwarf the rest of the per-request context.
FOCUSED_WORKOUT_LAPS_CAP = 30


def find_workout_by_id(workouts: list[Workout], workout_id: str) -> Workout | None:
    """Matches `workout_id` against `workouts` by case-insensitive exact id
    or prefix -- the same convention `engine/swim_coach/cli.py`'s
    `_cmd_analyze` uses for its own `--workout-id` argument. Returns the
    first match (an ambiguous short prefix matching more than one workout is
    vanishingly unlikely with UUIDs, and the PWA always sends a full id
    anyway) or `None` if nothing matches."""
    query = workout_id.strip().lower()
    if not query:
        return None
    for w in workouts:
        if str(w.id).lower().startswith(query):
            return w
    return None


def render_focused_workout(workout: Workout) -> str:
    """Full detail block for the one workout a scoped chat is about --
    summary (including analytics + sport_detail), a bounded laps table, and
    every pause (rarely more than a handful, so no cap needed there).
    Labeled distinctly from the ordinary 28-day exact-sessions list so the
    model doesn't conflate "every recent session, in brief" with "the ONE
    workout under discussion, in full."."""
    summary = {
        "id": str(workout.id),
        "date": workout.date.isoformat(),
        "sport": workout.sport,
        "sport_detail": workout.sport_detail,
        "source": workout.source,
        "distance_m": workout.distance_m,
        "duration_min": workout.duration_min,
        "avg_pace_s_per_100m": workout.avg_pace_s_per_100m,
        "rpe": workout.rpe,
        "notes": workout.notes,
        "avg_hr": workout.avg_hr,
        "max_hr": workout.max_hr,
        "analytics": workout.analytics.model_dump(mode="json") if workout.analytics is not None else None,
    }
    laps = workout.laps[:FOCUSED_WORKOUT_LAPS_CAP]
    laps_truncated = len(workout.laps) > FOCUSED_WORKOUT_LAPS_CAP
    laps_header = f"### Laps ({len(laps)} of {len(workout.laps)} shown"
    laps_header += ", truncated)" if laps_truncated else ")"

    parts = [
        "## The specific workout the athlete is asking about "
        "(NOT the same as the 28-day exact-sessions list above)",
        json.dumps(summary, indent=2),
        "",
        laps_header,
        json.dumps([lap.model_dump(mode="json") for lap in laps], indent=2) if laps else "(no laps recorded)",
        "",
        f"### Pauses ({len(workout.pauses)})",
        (
            json.dumps([p.model_dump(mode="json") for p in workout.pauses], indent=2)
            if workout.pauses
            else "(no pauses recorded)"
        ),
    ]
    return "\n".join(parts)


def build_per_request_context(
    store: StoreInterface, slug: str, *, expert_mode: bool, focused_workout: Workout | None = None
) -> str:
    """The uncached, per-request text block: athlete profile + zones,
    current + next week plan, the last ~28 days' exact logged sessions
    (each with its own sport -- ground truth), events/races with dates, and
    the 28-day aggregate rollup derived from those same sessions.
    Deliberately plain text/JSON, not prose -- the model reads it as ground
    truth, it doesn't need to be narrated.

    `focused_workout`, when given (the Log tab's embedded workout chat),
    appends `render_focused_workout`'s block -- still per-request/uncached,
    never the stable system prefix (see that function's docstring)."""
    today = date.today()
    current_iso = iso_week_str(today)
    next_iso = iso_week_str(today + timedelta(days=7))

    athlete = store.load_athlete(slug)
    workouts = store.list_workouts(slug)
    events = store.load_events(slug)
    span_start, span_end, _ = _rollup_window(today, weeks=4)
    rollup = summarize_rollup(store, slug, weeks=4, as_of=today, workouts=workouts)
    demographics = _render_demographics(athlete, today)

    parts = [
        "## Athlete context (assembled per-request, not cached)",
        f"Asker mode: {'expert (professional coach/physiologist)' if expert_mode else 'athlete'}",
        f"Today: {today.isoformat()} (current week {current_iso}, next week {next_iso})",
        "",
        "### Profile",
        json.dumps(athlete.model_dump(mode="json"), indent=2),
    ]
    if demographics is not None:
        parts += [
            "",
            "Demographics (derived facts -- age computed from dob as of today, "
            "not stored -- ground truth, do not infer/guess these):",
            demographics,
        ]
    parts += [
        "",
        f"### Current week plan ({current_iso})",
        json.dumps(_week_or_none(store, slug, current_iso), indent=2),
        "",
        f"### Next week plan ({next_iso})",
        json.dumps(_week_or_none(store, slug, next_iso), indent=2),
        "",
        "### Exact logged sessions (last 28 days) -- ground truth, each with its sport",
        _render_recent_sessions(workouts, span_start, span_end),
        "",
        "### Events / races",
        _render_events(events, today),
        "",
        "### 28-day AGGREGATE rollup (derived from the sessions above)",
        json.dumps(rollup, indent=2),
    ]
    if focused_workout is not None:
        parts += ["", render_focused_workout(focused_workout)]
    return "\n".join(parts)


class HistoryTurn(TypedDict):
    role: str
    content: str


def build_messages(
    store: StoreInterface,
    slug: str,
    *,
    message: str,
    history: list[HistoryTurn],
    expert_mode: bool,
    focused_workout: Workout | None = None,
) -> list[dict[str, Any]]:
    """The `messages` param: per-request context merged into the first
    message of the conversation, then the rest of `history` verbatim, then
    the new `message`.

    The context is merged into (not inserted before) the first message
    because the Messages API requires strictly alternating user/assistant
    roles -- prepending a standalone synthetic "user" message in front of
    `history[0]` (itself a "user" turn, by convention: conversations always
    open with the athlete) would be two user turns back to back and the API
    would reject it. Merging into history[0]'s content keeps alternation
    intact. When `history` is empty, the new `message` *is* the first
    message, so the context merges there instead.

    `focused_workout` (the Log tab's embedded workout chat -- see
    `render_focused_workout`) is threaded straight through to
    `build_per_request_context`; the caller (app.routes.chat) is responsible
    for resolving a `workout_id` to a `Workout` (or a 404) before calling
    this.
    """
    context_text = build_per_request_context(
        store, slug, expert_mode=expert_mode, focused_workout=focused_workout
    )
    messages: list[dict[str, Any]] = []

    if history:
        first = history[0]
        messages.append(
            {"role": first["role"], "content": f"{context_text}\n\n---\n\n{first['content']}"}
        )
        for turn in history[1:]:
            messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": message})
    else:
        messages.append({"role": "user", "content": f"{context_text}\n\n---\n\n{message}"})

    return messages
