"""Reusable athlete-onboarding orchestration.

`provision_athlete` is the one function that turns a parsed profile (+
optional events) into a complete, usable athlete inside a `StoreInterface`
(`FileStore` or `DbStore`): zones, an optional macro scaffold + first week,
and a beta allowlist entry. It reuses the engine's own math -- `zone_table`
(zones.py), `scaffold_macro`/`generate_week` (plan.py) -- rather than
recomputing anything.

This lives in `engine/`, not `swim_coach.cli`, specifically so a future
in-app onboarding HTTP route (backend/app/routes/) can call the exact same
function `python -m swim_coach.cli onboard` does today -- see GitHub issue
#61 ("Tier C"). `cli.py`'s `onboard` subcommand is a thin wrapper: it only
parses local YAML into `Athlete`/`Event` models and resolves CLI-only
concerns (fuzzy `--event` matching, `--test-400`/`--test-200`), then hands
off to this function. All persistence orchestration -- and the FK-safe
write order -- lives here, once.

Idempotency: every `StoreInterface.save_*` this calls is an upsert (see
`store.py`/`store_db.py`), so re-running `provision_athlete` for the same
`profile.id` (FileStore: same `slug`) UPDATES the existing athlete/events/
macro/first-week/allowlist entry rather than refusing or duplicating.
Re-running with a *different* id but the same `slug` is a slug collision --
FileStore silently reprovisions that slug (last write wins, no id
uniqueness enforced at that layer); DbStore's `athletes.slug` unique
constraint raises (propagates as an unexpected error from `save_athlete`).
`cli.py`'s `onboard` command avoids this by resolving an omitted profile id
to any existing athlete's id at that slug before calling here -- see its
module docstring.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from swim_coach.models import AllowedEmail, Athlete, Event, MacroPlan, WeekPlan
from swim_coach.plan import generate_week, scaffold_macro
from swim_coach.store import StoreInterface
from swim_coach.zones import zone_table

# Library-style logger: named, structured-field calls (`extra=`), no handler
# attached here. Per CLAUDE.md's Python JSON-logging standard, the JSON
# formatting/handler wiring is an application-boundary concern (see
# backend/app/logging_config.py's JsonLogger for this repo's app-level
# implementation) -- attaching one here would make every embedder (the CLI,
# and any future in-app onboarding route) inherit this module's opinion on
# log format. With no handler configured, calls below are inert (stdlib
# `logging` drops them by level before they'd print anything), which also
# keeps them from breaking `cli.py`'s "exactly one JSON object on stdout per
# command" contract.
log = logging.getLogger("swim_coach.provision")


@dataclass(frozen=True)
class ProvisionResult:
    """Everything `provision_athlete` created or attached to `store`."""

    athlete: Athlete
    events: list[Event] = field(default_factory=list)
    macro: MacroPlan | None = None
    week: WeekPlan | None = None
    allowed_email: AllowedEmail | None = None
    # Human-readable reasons any optional step (currently: macro + first
    # week) was skipped -- e.g. "no target event given". Empty when every
    # step ran. `cli.py`'s `onboard` surfaces this verbatim in its JSON
    # summary so a degraded run is never silently incomplete.
    skipped: list[str] = field(default_factory=list)


def _iso_week(d: date) -> str:
    """Mirrors `swim_coach.cli`'s own private `_iso_week` -- both are a
    3-line wrapper around `date.isocalendar()`, not worth a cross-module
    import for."""
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def provision_athlete(
    store: StoreInterface,
    *,
    profile: Athlete,
    events: list[Event] | None = None,
    email: str,
    note: str | None = None,
    target_event: Event | None = None,
    current_volume_m: int | None = None,
    peak_volume_m: int | None = None,
    macro_start: date | None = None,
) -> ProvisionResult:
    """Provision one complete, usable athlete into `store`.

    Reuses (never reimplements) the engine's own math:
      - `zones.zone_table(profile.css_pace_s_per_100m)` for the zone table
      - `plan.scaffold_macro` for the macro periodization scaffold
      - `plan.generate_week` for the macro's first week

    Write order (FK-safe -- parents before children, matching
    `scripts/migrate_files_to_db.py`'s `_migrate_athlete`):
      athlete -> events -> macro -> first week -> allowlist entry.

    `profile.css_pace_s_per_100m` must already be set (directly, or derived
    from a CSS test by the caller -- `cli.py`'s `onboard` reuses
    `zones.css_from_test`/`cli.parse_time_to_s`, exactly like its `zones`
    subcommand) -- zones are mandatory scope for v1 onboarding, so a missing
    CSS pace is a hard `ValueError`, not a degraded/skipped step.

    The macro scaffold + first week are the one part of v1 scope that
    degrades instead of erroring: if `target_event` or `current_volume_m`
    is absent, both are skipped (recorded in the returned
    `ProvisionResult.skipped`) and the athlete is still fully provisioned
    (profile, zones, events if given, and the allowlist entry). This is
    deliberately narrower than "any failure downgrades to skip" -- if
    `target_event`/`current_volume_m` ARE given but `scaffold_macro`/
    `generate_week` itself raises `ValueError` (e.g. too few weeks of
    runway before the event), that propagates as a hard error rather than
    being swallowed: it's real, actionable information (per
    `scaffold_macro`'s own docstring), not an absent-input case. Because
    every write up to that point already landed (upserts), the caller can
    just fix the input (a later event, a corrected `--current-volume`) and
    re-run -- no partial-provisioning cleanup needed.

    The allowlist entry (`store.add_allowed_email`) always runs, regardless
    of whether the macro/first week were skipped -- unlike bare `invite`,
    this command creates the athlete row itself first (see `cli.py`'s
    `onboard`), so it never hits the FK-missing-athlete case `invite`
    against a bare `--database-url` can.
    """
    if profile.css_pace_s_per_100m is None:
        raise ValueError(
            "profile has no css_pace_s_per_100m -- a CSS pace (direct, or "
            "derived from a 400m/200m test) is required to compute zones"
        )
    athlete = profile.model_copy(
        update={"zones": zone_table(profile.css_pace_s_per_100m)}
    )
    events = list(events) if events else []

    log.info(
        "provisioning athlete",
        extra={"slug": athlete.slug, "athlete_id": str(athlete.id), "n_events": len(events)},
    )

    store.save_athlete(athlete)
    if events:
        store.save_events(athlete.slug, events)

    macro: MacroPlan | None = None
    week: WeekPlan | None = None
    skipped: list[str] = []

    missing_inputs = []
    if target_event is None:
        missing_inputs.append("no target event given")
    if current_volume_m is None:
        missing_inputs.append("no current_volume_m given")

    if missing_inputs:
        skipped.append(
            "skipped macro scaffold and first week (" + "; ".join(missing_inputs) + ")"
        )
        log.info("skipping macro/first-week", extra={"slug": athlete.slug, "reasons": missing_inputs})
    else:
        start = macro_start or date.today()
        macro = scaffold_macro(athlete, target_event, start, current_volume_m, peak_volume_m)
        store.save_macro(athlete.slug, macro)

        week_start = macro.blocks[0].start_date
        iso_week = _iso_week(week_start)
        week = generate_week(
            athlete, macro, iso_week, week_start, event_format=target_event.event_format
        )
        store.save_week(athlete.slug, week)
        log.info(
            "scaffolded macro and first week",
            extra={"slug": athlete.slug, "n_blocks": len(macro.blocks), "first_week": iso_week},
        )

    allowed_email = store.add_allowed_email(email, athlete=athlete.slug, note=note)

    log.info(
        "provisioned athlete",
        extra={
            "slug": athlete.slug,
            "macro": macro is not None,
            "week": week is not None,
            "skipped": skipped,
        },
    )

    return ProvisionResult(
        athlete=athlete,
        events=events,
        macro=macro,
        week=week,
        allowed_email=allowed_email,
        skipped=skipped,
    )
