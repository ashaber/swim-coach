"""Compact bike-workout notation -> `WorkoutStructure`.

The coach authors bike workouts as one short string instead of verbose JSON
(the JSON form cost thousands of output tokens per week -- prod incident
2026-10-18). Example::

    12m ramp 50-70%; 2x[3m 91-96% / 2m 52%]; 3x[20s free / 1m40s 50%]; 5m 50%

Grammar (bike only; swim/strength stay JSON):
  workout  := item (";" item)*
  item     := repeat | step
  repeat   := N "x" "[" step ("/" step)* "]"      (one nested repeat allowed)
  step     := [role ":"] duration target ["\\"label\\""]
  duration := 1h30m | 20m | 90s | 1m40s
  target   := 91-96% | 55% | 250W | 230-250W | z2 | ramp 50-70% | free | open
  role     := wu | cd | work | rec | steady        (inferred when omitted)

`%` targets are % of FTP and resolve to absolute watts (`basis="power_w"`) via
`ftp_watts`, exactly like `plan._bike_step`; without FTP a `%` target is an
error (use `W`, a zone, or set FTP). `zN` resolves through
`zones.bike_zone_table` (Coggan zones) when FTP is known, else stays a zone
target (Z1-Z5 only). `free`/`open` is an untargeted step (`basis="open"`).

Role inference: with 2+ top-level items, an un-prefixed leading step is the
warm-up and an un-prefixed trailing step the cool-down (unless untargeted);
inside a repeat the first step is `interval` and the others `recovery`; other
steps are `steady`; a mid-workout `ramp` is role `ramp`.

Pure function -- no I/O. Errors raise `NotationError` naming the step number
and character offset.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from swim_coach.models import WorkoutRepeat, WorkoutStep, WorkoutStepOrRepeat, WorkoutStructure, WorkoutTarget
from swim_coach.zones import bike_zone_table

_ROLE_PREFIXES = {
    "wu": "warmup",
    "cd": "cooldown",
    "work": "interval",
    "int": "interval",
    "rec": "recovery",
    "steady": "steady",
}
_MAX_REPEAT_DEPTH = 2

_NUM = r"(\d+(?:\.\d+)?)"
_RE_REPEAT = re.compile(r"^(\d+)\s*x\s*\[(.*)\]$", re.DOTALL | re.IGNORECASE)
_RE_ROLE = re.compile(r"^([a-z]+)\s*:\s*")
_RE_LABEL = re.compile(r'"([^"]*)"')
_RE_DURATION = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$", re.IGNORECASE)
_RE_RAMP = re.compile(rf"^ramp\s+{_NUM}\s*-\s*{_NUM}\s*(%|w)$", re.IGNORECASE)
_RE_RANGE = re.compile(rf"^{_NUM}(?:\s*-\s*{_NUM})?\s*(%|w)$", re.IGNORECASE)
_RE_ZONE = re.compile(r"^z([1-7])$", re.IGNORECASE)


class NotationError(ValueError):
    """Parse failure; message is already `step N (char C): ...`."""


@dataclass
class _Ctx:
    ftp_watts: float | None
    step_no: int = 0


def _err(ctx: _Ctx, offset: int, msg: str) -> NotationError:
    return NotationError(f"step {ctx.step_no} (char {offset}): {msg}")


def _split_top(text: str, sep: str, base: int) -> list[tuple[str, int]]:
    """Split on `sep` outside [] and quotes; returns (segment, absolute offset)."""
    parts: list[tuple[str, int]] = []
    depth, in_q, start = 0, False, 0
    for i, ch in enumerate(text):
        if ch == '"':
            in_q = not in_q
        elif in_q:
            continue
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        elif ch == sep and depth == 0:
            parts.append((text[start:i], base + start))
            start = i + 1
    parts.append((text[start:], base + start))
    return parts


def _lead(segment: str) -> int:
    return len(segment) - len(segment.lstrip())


def _parse_duration(token: str, ctx: _Ctx, offset: int) -> float:
    m = _RE_DURATION.match(token)
    if not token or m is None or not any(m.groups()):
        raise _err(ctx, offset, f"bad duration {token!r} (use e.g. 20s, 3m, 1m40s, 1h30m)")
    h, mi, s = (int(g) if g else 0 for g in m.groups())
    total = h * 3600 + mi * 60 + s
    if total <= 0:
        raise _err(ctx, offset, f"duration {token!r} must be positive")
    return float(total)


def _pct_to_watts(pct: float, ctx: _Ctx, offset: int) -> float:
    if ctx.ftp_watts is None:
        raise _err(ctx, offset, "a % FTP target needs the athlete's FTP, which is not set -- use watts (W) or a zone (z2)")
    return float(round(ctx.ftp_watts * pct / 100.0))


def _parse_target(text: str, ctx: _Ctx, offset: int) -> tuple[WorkoutTarget, bool]:
    """(target, is_ramp)."""
    t = text.strip()
    if not t:
        raise _err(ctx, offset, "missing target (use e.g. 90%, 250W, z2, or `free` for none)")
    if t.lower() in ("free", "open"):
        return WorkoutTarget(basis="open"), False
    m = _RE_RAMP.match(t)
    if m:
        lo, hi = float(m[1]), float(m[2])
        if lo >= hi:
            raise _err(ctx, offset, f"ramp must climb: {t!r}")
        if m[3] == "%":
            lo, hi = _pct_to_watts(lo, ctx, offset), _pct_to_watts(hi, ctx, offset)
        return WorkoutTarget(basis="power_w", low=lo, high=hi), True
    m = _RE_RANGE.match(t)
    if m:
        lo = float(m[1])
        hi = float(m[2]) if m[2] else lo
        if lo > hi:
            raise _err(ctx, offset, f"range low exceeds high: {t!r}")
        if m[3] == "%":
            lo, hi = _pct_to_watts(lo, ctx, offset), _pct_to_watts(hi, ctx, offset)
        return WorkoutTarget(basis="power_w", low=lo, high=hi), False
    m = _RE_ZONE.match(t)
    if m:
        name = f"Z{m[1]}"
        if ctx.ftp_watts is None:
            if int(m[1]) > 5:
                raise _err(ctx, offset, f"zone {name} needs FTP to resolve (only z1-z5 allowed without it)")
            return WorkoutTarget(basis="zone", zone=name), False
        row = bike_zone_table(ctx.ftp_watts)[name]
        hi = row["watts_hi"]
        return WorkoutTarget(basis="power_w", low=float(round(row["watts_lo"])), high=float(round(hi)) if hi is not None else None), False
    raise _err(ctx, offset, f"unknown target {t!r}")


def _parse_step(segment: str, offset: int, ctx: _Ctx, *, role: str | None) -> tuple[WorkoutStep, bool]:
    """(step, had_explicit_role). `role` is the default when un-prefixed."""
    ctx.step_no += 1
    offset += _lead(segment)
    text = segment.strip()
    if not text:
        raise _err(ctx, offset, "empty step")
    explicit: str | None = None
    rm = _RE_ROLE.match(text.lower())
    if rm:
        key = rm[1]
        if key not in _ROLE_PREFIXES:
            raise _err(ctx, offset, f"unknown role {key!r} (use {', '.join(_ROLE_PREFIXES)})")
        explicit = _ROLE_PREFIXES[key]
        text = text[rm.end():]
    label = None
    lm = _RE_LABEL.search(text)
    if lm:
        label = lm[1].strip() or None
        text = (text[: lm.start()] + text[lm.end():]).strip()
    head, _, rest = text.partition(" ")
    seconds = _parse_duration(head.lower(), ctx, offset)
    target, is_ramp = _parse_target(rest, ctx, offset)
    chosen = explicit or role or "steady"
    if is_ramp and explicit is None and chosen in ("steady", "interval", "recovery"):
        chosen = "ramp"
    step = WorkoutStep(
        label=label or f"{head} {rest.strip()}",
        role=chosen,
        duration_kind="time_s",
        duration_value=seconds,
        target=target,
        modality="bike",
    )
    return step, explicit is not None


def _parse_repeat(s: str, off: int, ctx: _Ctx, depth: int) -> WorkoutRepeat:
    rm = _RE_REPEAT.match(s)
    if rm is None:
        raise _err(ctx, off, f"malformed repeat {s!r} (expected Nx[step / step])")
    if depth >= _MAX_REPEAT_DEPTH:
        raise _err(ctx, off, "repeats nest only one level deep")
    count = int(rm[1])
    if count < 1:
        raise _err(ctx, off, "repeat count must be >= 1")
    steps: list[WorkoutStepOrRepeat] = []
    inner_base = off + s.index("[") + 1
    for i, (iseg, ioff) in enumerate(_split_top(rm[2], "/", inner_base)):
        if re.match(r"^\s*\d+\s*x\s*\[", iseg, re.IGNORECASE):
            steps.append(_parse_repeat(iseg.strip(), ioff + _lead(iseg), ctx, depth + 1))
        else:
            step, _ = _parse_step(iseg, ioff, ctx, role="interval" if i == 0 else "recovery")
            steps.append(step)
    return WorkoutRepeat(count=count, steps=steps)


def parse_workout_notation(text: str, *, ftp_watts: float | None = None) -> WorkoutStructure:
    """Parse compact bike notation into a `WorkoutStructure`. Raises `NotationError`."""
    if not isinstance(text, str) or not text.strip():
        raise NotationError("step 0 (char 0): empty notation")
    ctx = _Ctx(ftp_watts=ftp_watts)
    items: list[WorkoutStepOrRepeat] = []
    explicit_flags: list[bool] = []
    for seg, off in _split_top(text, ";", 0):
        if not seg.strip():
            continue
        s, o = seg.strip(), off + _lead(seg)
        if re.match(r"^\d+\s*x\b", s, re.IGNORECASE):
            items.append(_parse_repeat(s, o, ctx, 0))
            explicit_flags.append(False)
        else:
            step, explicit = _parse_step(seg, off, ctx, role=None)
            items.append(step)
            explicit_flags.append(explicit)
    if not items:
        raise NotationError("step 0 (char 0): no steps found")
    if len(items) >= 2:
        for idx, role in ((0, "warmup"), (len(items) - 1, "cooldown")):
            item = items[idx]
            if (
                isinstance(item, WorkoutStep)
                and not explicit_flags[idx]
                and item.role in ("steady", "ramp")
                and item.target is not None
                and item.target.basis != "open"
            ):
                item.role = role
    return WorkoutStructure(items=items)
