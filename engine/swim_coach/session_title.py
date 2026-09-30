"""One short, consumer-facing title per planned session.

Used everywhere a session is named to a human: the PWA plan/session views
(via the plan export's `title`), the Garmin FIT workout name, the
intervals.icu event name, and ZWO. Resolution order:

1. `Session.title` -- the coach-authored title (`author_week_plan`'s `title`),
   e.g. "3x6 VO2 40/20", "Over/unders 3x9", "Endurance 100'".
2. A deterministic title derived from `Session.structured` when it holds
   interval reps -- nested repeats collapse to "3x6 40/20 VO2", a single
   repeat to "8x30/30 VO2" or "3x12' Threshold". Never from prose.
3. The short label of `Session.purpose` ("<label> -- <rationale>" by
   convention), skipping a leading macro-phase word: the purpose
   "Build -- 40/20s VO2 intervals" once produced the device title "Build".

Never contains brackets. Pure functions, no I/O.
"""

from __future__ import annotations

import re

from swim_coach.models import Session, WorkoutRepeat, WorkoutStructure
from swim_coach.workout_templates import short_device_title

TITLE_MAX_LEN = 40  # matches Session.title's max_length

# Coggan/Allen bike zone names (library/23-cycling-training.md); only used for
# bike sessions, since other sports' zone scales differ.
_BIKE_ZONE_NAMES = {
    "Z1": "Recovery", "Z2": "Endurance", "Z3": "Tempo", "Z4": "Threshold",
    "Z5": "VO2", "Z6": "Anaerobic", "Z7": "Sprint",
}
# Macro-phase / block names that are never a session's name.
_PHASE_WORDS = frozenset({
    "base", "build", "peak", "taper", "race", "prep", "preparation", "transition", "deload",
    "recovery week", "maintenance", "specific prep", "general prep", "off-season", "offseason",
})
_BRACKETS_RE = re.compile(r"[\[\]]")
_SHORT_REP_MAX_S = 120  # at or under this a rep is written in seconds ("40/20")


def clean_title(text: str) -> str:
    """Strips brackets, collapses whitespace."""
    return re.sub(r"\s{2,}", " ", _BRACKETS_RE.sub("", text)).strip()


def _leaves(items: list) -> list:
    out: list = []
    for item in items:
        if isinstance(item, WorkoutRepeat) or getattr(item, "kind", None) == "repeat":
            out.extend(_leaves(item.steps))
        else:
            out.append(item)
    return out


def _holds_intervals(items: list) -> bool:
    return any(getattr(leaf, "role", None) == "interval" for leaf in _leaves(items))


def _dur(step) -> str | None:
    if step.duration_kind == "time_s" and step.duration_value:
        return str(int(round(step.duration_value)))
    return None


def _rep_text(work, rest) -> str | None:
    """'40/20' for short on/off reps, "12'" for long ones, '300m' for distance."""
    if work.duration_kind == "distance_m" and work.duration_value:
        return f"{int(round(work.duration_value))}m"
    if work.duration_kind != "time_s" or not work.duration_value:
        return None
    if work.duration_value <= _SHORT_REP_MAX_S:
        on, off = _dur(work), _dur(rest) if rest is not None else None
        return f"{on}/{off}" if off else f"{on}s"
    return f"{int(round(work.duration_value / 60))}'"


def _zone_name(zone: str | None, sport: str) -> str | None:
    if not zone:
        return None
    return _BIKE_ZONE_NAMES.get(zone) if sport == "bike" else zone


def _split_work_rest(steps: list) -> tuple | None:
    """The (work, rest) pair of a repeat body: first interval step, and the
    next recovery/rest step after it, if any."""
    work = next((s for s in steps if getattr(s, "role", None) == "interval"), None)
    if work is None:
        return None
    after = steps[steps.index(work) + 1:]
    rest = next((s for s in after if getattr(s, "role", None) in ("recovery", "rest")), None)
    return work, rest


def _main_repeat(structure: WorkoutStructure):
    for item in structure.items:
        if (isinstance(item, WorkoutRepeat) or getattr(item, "kind", None) == "repeat") and _holds_intervals(
            item.steps
        ):
            return item
    return None


def derive_title(session: Session) -> str | None:
    """A title derived from `session.structured`'s interval reps, or `None`
    when it has no interval repeat (a steady/strength/prose-only session)."""
    if session.structured is None:
        return None
    outer = _main_repeat(session.structured)
    if outer is None:
        return None
    rounds: int | None = outer.count or 1
    inner = next(
        (
            s for s in outer.steps
            if (isinstance(s, WorkoutRepeat) or getattr(s, "kind", None) == "repeat") and _holds_intervals(s.steps)
        ),
        None,
    )
    if inner is not None:
        reps, body = inner.count or 1, inner.steps
        head = f"{rounds}x{reps}"
    else:
        reps, body = None, outer.steps
        head = f"{rounds}x"
    pair = _split_work_rest(body)
    if pair is None:
        return None
    work, rest = pair
    rep = _rep_text(work, rest)
    if rep is None:
        return None
    zone = _zone_name(work.target.zone if work.target is not None else None, session.sport)
    title = f"{head} {rep}" if reps is not None else f"{head}{rep}"
    if zone:
        title = f"{title} {zone}"
    return title


def resolve_title(session: Session) -> str | None:
    """`Session.title` when set, else the structure-derived title, else `None`
    (the caller then falls back to the purpose label)."""
    explicit = clean_title(session.title) if session.title else ""
    return explicit or derive_title(session)


def _purpose_label(purpose: str) -> str:
    parts = [p.strip() for p in re.split(r"\s+(?:—|--)\s+", purpose, maxsplit=1)]
    label = parts[0]
    if len(parts) > 1 and parts[1] and label.lower().rstrip(":") in _PHASE_WORDS:
        label = parts[1]
    return clean_title(short_device_title(clean_title(label), max_len=TITLE_MAX_LEN))


def session_title(session: Session) -> str:
    """The one short title for `session`; see the module docstring."""
    return resolve_title(session) or _purpose_label(session.purpose) or session.sport
