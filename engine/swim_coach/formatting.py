"""Shared pace, rounding and ISO-week helpers used across the engine and backend."""

from __future__ import annotations

from datetime import date


def format_pace_s(pace_s: float) -> str:
    """Format a seconds-per-100m pace as M:SS (e.g. 92.3 -> '1:32')."""
    total = int(round(pace_s))
    minutes, seconds = divmod(total, 60)
    return f"{minutes}:{seconds:02d}"


def round_100(value: float) -> int:
    """Round a distance to the nearest 100 m."""
    return int(round(value / 100)) * 100


def duration_min_for_distance(distance_m: float, pace_s_per_100m: float) -> float:
    """Minutes to cover `distance_m` at `pace_s_per_100m`, rounded to 0.1 (negative distance clamps to 0)."""
    return round(max(distance_m, 0) / 100 * pace_s_per_100m / 60, 1)


def iso_week_str(d: date) -> str:
    """ISO week label for a date, e.g. 2026-W07."""
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"
