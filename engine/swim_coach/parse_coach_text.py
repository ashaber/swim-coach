"""Deterministic parser for pool-coach workout text.

No LLM, no network -- pure regex/grammar over the raw text a pool coach
hands the athlete after a session (see CLAUDE.md "Key domain constraint").
`parse_coach_text` is intentionally line-oriented: each line of the input
is classified as a heading, a round-block declaration, a parseable set, a
set-*like* line that failed to parse, or prose -- see the module-level
regexes and `_looks_set_like` for the exact heuristic.

`CoachTextParse` lives here (not in models.py) because it is a parse
*result*, not a persisted domain entity -- it never round-trips through
FileStore.

ROADMAP.md risk #2 applies: if coach-text notation resists regex parsing
past a ~50% hit rate, the plan is to fall back to agent-first parsing with
schema validation. This module's `unparsed_lines` output is exactly the
signal that decision would be based on.
"""

from __future__ import annotations

import re
import string

from pydantic import BaseModel, Field

from swim_coach.models import WorkoutSet

# --- constants ---------------------------------------------------------------------

MIN_STANDALONE_DISTANCE_M = 25
# A bare "<number> <words>" line (no "N x" reps token) is only treated as a
# distance if the number is >= this floor. Below it, bare numbers are far
# more likely to be markdown list markers, stroke-count call-outs inside a
# coaching note ("25 Butterfly, 25 Backstroke, ..."), or other noise than an
# actual standalone set -- and those lines don't start with a digit in the
# first place, other than the false-positive numbered-list case this floor
# is guarding against. 25m is the shortest realistic standalone pool
# distance (one length of a short-course pool).

_KNOWN_STROKE_WORDS = {
    "freestyle",
    "free",
    "backstroke",
    "back",
    "breaststroke",
    "breast",
    "butterfly",
    "fly",
    "im",
    "pull",
    "kick",
    "drill",
    "swim",
    "paddles",
    "buoy",
    "fins",
}
# Deliberately narrow: generic words like "stroke" or "choice" (as in
# "Stroke Progression", "Choice Recovery") are NOT included here, so those
# notations fall through to `description` whole, per the Day 3 spec's
# examples -- rather than mis-splitting "Choice" off as if it were a named
# stroke.

_HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$")
_BULLET_RE = re.compile(r"^[*\-]\s+")
_ROUND_RE = re.compile(
    r"(?:execute\s+(\d+)\s+rounds?\s+of|repeat\s+(\d+)\s*[x×])", re.IGNORECASE
)
_REPS_DISTANCE_RE = re.compile(r"^(?P<reps>\d+)\s*[x×]\s*(?P<distance>\d+)\b\s*(?P<rest>.*)$")
_SINGLE_DISTANCE_RE = re.compile(
    r"^(?P<distance>\d+)\s*(?:m|meters|yards|yd)?\b\s+(?P<rest>.+)$", re.IGNORECASE
)
_AT_CLAUSE_RE = re.compile(r"@\s*(\S+)")
_CLOCK_TOKEN_RE = re.compile(r"^\d+:\d+(?:\.\d+)?$")
_PLAIN_SECONDS_TOKEN_RE = re.compile(r"^\d+(?:\.\d+)?s?$", re.IGNORECASE)
_LEADING_PUNCT_RE = re.compile(r"^[\s\-–—:]+")

_NUM_X_RE = re.compile(r"\d+\s*[x×]")
_LEADING_DISTANCE_RE = re.compile(r"^(\d+)\b")


class CoachTextParse(BaseModel):
    """Result of deterministically parsing one block of raw coach text."""

    sets: list[WorkoutSet] = Field(default_factory=list)
    unparsed_lines: list[str] = Field(default_factory=list)
    total_distance_m: int = 0
    rounds_expanded: bool = False


# --- heuristics ----------------------------------------------------------------------


def _looks_set_like(line: str) -> bool:
    """True if `line` looks like it's trying to express set notation.

    Heuristic per Day 3 spec: a number immediately followed by x/x, or a
    standalone distance number >= MIN_STANDALONE_DISTANCE_M at the start of
    the line.
    """
    if _NUM_X_RE.search(line):
        return True
    m = _LEADING_DISTANCE_RE.match(line)
    if m and int(m.group(1)) >= MIN_STANDALONE_DISTANCE_M:
        return True
    return False


def _clean_markup(line: str) -> str:
    """Strip a leading list-bullet marker and any bold (`**`) delimiters.

    Single-asterisk italic markers (e.g. `*Focus:*`) are deliberately left
    alone -- they never collide with the `x`/`X` multiplication notation
    this parser looks for, and stripping them isn't needed for
    classification (see `_looks_set_like`, which only looks at digits).
    """
    line = _BULLET_RE.sub("", line)
    line = line.replace("**", "")
    return line.strip()


def _extract_round_multiplier(text: str) -> int | None:
    """Find an "Execute N Rounds of" / "Repeat Nx" phrase anywhere in `text`."""
    m = _ROUND_RE.search(text)
    if not m:
        return None
    return int(m.group(1) or m.group(2))


def _is_pure_round_decl(cleaned: str) -> bool:
    """True if `cleaned` IS a round declaration (not a heading that merely
    mentions one among other words, which is handled separately)."""
    m = _ROUND_RE.search(cleaned)
    if not m:
        return False
    remainder = (cleaned[: m.start()] + cleaned[m.end() :]).strip(" :()")
    return remainder == ""


def _extract_at_clause(rest: str) -> tuple[str, str | None, str | None]:
    """Pull an optional `@ <token>` clause out of `rest`.

    Returns (rest_without_clause, interval, target_pace). A clock-shaped or
    plain-numeric token ("1:40", "90", "90s") is an interval (a send-off /
    rest interval); anything else ("CSS+5", "MP") is a pace hint.
    """
    m = _AT_CLAUSE_RE.search(rest)
    if not m:
        return rest, None, None
    token = re.sub(r"[.,;]+$", "", m.group(1))
    new_rest = (rest[: m.start()] + rest[m.end() :]).strip()
    if _CLOCK_TOKEN_RE.match(token) or _PLAIN_SECONDS_TOKEN_RE.match(token):
        return new_rest, token, None
    return new_rest, None, token


def _extract_stroke(rest: str) -> tuple[str | None, str | None]:
    """Split a leading known stroke/equipment word off `rest`.

    Returns (stroke, description). If the first word isn't recognized, the
    whole (non-empty) rest becomes the description instead.
    """
    rest = rest.strip()
    if not rest:
        return None, None
    parts = rest.split(None, 1)
    first_clean = parts[0].strip(string.punctuation).lower()
    if first_clean in _KNOWN_STROKE_WORDS:
        remainder = parts[1].strip() if len(parts) > 1 else None
        return first_clean, (remainder or None)
    return None, rest


def _parse_line(cleaned: str, multiplier: int) -> WorkoutSet | None:
    """Parse a single already-markdown-cleaned line into a WorkoutSet, or
    return None if it doesn't match any known set notation."""
    m = _REPS_DISTANCE_RE.match(cleaned)
    if m:
        reps: int | None = int(m.group("reps"))
        distance = int(m.group("distance"))
        rest = m.group("rest")
    else:
        m2 = _SINGLE_DISTANCE_RE.match(cleaned)
        if not m2:
            return None
        distance = int(m2.group("distance"))
        if distance < MIN_STANDALONE_DISTANCE_M:
            return None
        reps = None
        rest = m2.group("rest")

    rest = _LEADING_PUNCT_RE.sub("", rest)
    rest, interval, target_pace = _extract_at_clause(rest)
    stroke, description = _extract_stroke(rest)

    final_reps = (reps or 1) * multiplier if multiplier > 1 else reps

    return WorkoutSet(
        reps=final_reps,
        distance_m=distance,
        interval=interval,
        target_pace=target_pace,
        stroke=stroke,
        description=description,
    )


def parse_coach_text(text: str) -> CoachTextParse:
    """Deterministically parse raw pool-coach workout text.

    Line-oriented: headings and round-block declarations manage an active
    reps multiplier (reset to 1 at every heading, unless that heading
    itself declares a repeat count); every other line either parses into a
    `WorkoutSet` (with reps scaled by the active multiplier), gets flagged
    in `unparsed_lines` (if it *looks* like set notation but didn't parse),
    or is silently treated as prose (markdown noise, coaching notes, focus
    call-outs).
    """
    sets: list[WorkoutSet] = []
    unparsed_lines: list[str] = []
    rounds_expanded = False
    multiplier = 1

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue

        heading_match = _HEADING_RE.match(stripped)
        if heading_match:
            heading_multiplier = _extract_round_multiplier(heading_match.group(1))
            multiplier = heading_multiplier or 1
            if heading_multiplier:
                rounds_expanded = True
            continue

        cleaned = _clean_markup(stripped)
        if not cleaned:
            continue

        if _is_pure_round_decl(cleaned):
            decl_multiplier = _extract_round_multiplier(cleaned)
            multiplier = decl_multiplier or 1
            rounds_expanded = True
            continue

        parsed = _parse_line(cleaned, multiplier)
        if parsed is not None:
            sets.append(parsed)
        elif _looks_set_like(cleaned):
            unparsed_lines.append(stripped)
        # else: prose (markdown noise, focus/coaching notes) -- ignored.

    total_distance_m = sum((s.reps or 1) * s.distance_m for s in sets)

    return CoachTextParse(
        sets=sets,
        unparsed_lines=unparsed_lines,
        total_distance_m=total_distance_m,
        rounds_expanded=rounds_expanded,
    )
