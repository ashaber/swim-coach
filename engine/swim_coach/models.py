"""Pydantic v2 data models for the swim-coach engine.

Every entity that references an athlete carries ``athlete_id: UUID`` (the
``Athlete`` model is the exception — its own ``id`` fills that role). Every
model that maps to a persisted YAML file carries ``schema_version: int = 1``
so future migrations have a field to branch on.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator

# cross_train: logged non-swim endurance activity (kayak, run, ride, ...).
# Counts toward sRPE load (load.py is sport-agnostic there) but never toward
# swim volume (load.py's volume filters allowlist {swim_pool, swim_ow}).
# The planner never schedules it; it exists so real .fit imports of non-swim
# activities aren't mislabeled as swims.
#
# bike: a first-class, PLANNABLE cycling sport (engine/cycling-coach branch,
# IDEA 008 use case 5) -- deliberately NOT reusing `cross_train`, which is
# explicitly documented above as a logging-only catch-all the planner never
# schedules. `bike` is the opposite: `plan.generate_week` can author real
# bike sessions for it (see that module's `primary_sport` parameter). Road/
# MTB/cyclocross/gravel sub-classification reuses the EXISTING
# `Workout.sport_detail` free-text field below (confirmed real production
# values: "cycling/mountain", "cycling/road", "cycling/gravel_cycling",
# "cycling/cyclocross") rather than a new field -- see that field's own
# comment.
Sport = Literal["swim_pool", "swim_ow", "strength", "recovery", "cross_train", "bike"]

_ISO_WEEK_RE = re.compile(r"^\d{4}-W\d{2}$")
_VALID_ZONES = {"Z1", "Z2", "Z3", "Z4", "Z5"}
_VALID_ANCHORS = {"css_pace", "rpe", "hr"}


# Words for the engine's deterministic bike interval types (plan.BIKE_INTERVAL_TEMPLATES), so the
# coach or athlete can CHOOSE one by whatever name they use. Unrecognised -> None (the caller keeps
# the weekly rotation and notes it; never an error).
_INTERVAL_TYPE_WORDS: dict[str, str] = {
    **dict.fromkeys(("sustained_threshold", "threshold", "sustained threshold", "ftp", "sustained", "lt", "lactate threshold"), "sustained_threshold"),
    **dict.fromkeys(("over_unders", "over/unders", "over unders", "over-unders", "over under", "over/under", "overunders"), "over_unders"),
    **dict.fromkeys(("short_short_vo2", "vo2", "vo2max", "vo2 max", "short short", "short-short", "30/15", "vo2 intervals"), "short_short_vo2"),
    **dict.fromkeys(("race_pace", "race pace", "race-pace", "punchy", "race"), "race_pace"),
    **dict.fromkeys(("openers", "opener", "primer", "primers", "pre-race", "pre race"), "openers"),
}


def normalize_interval_type(raw: object) -> str | None:
    """The engine's interval-type key for whatever word was used, or `None` when it is not one."""
    if not isinstance(raw, str):
        return None
    return _INTERVAL_TYPE_WORDS.get(raw.strip().lower())


class AthleteNote(BaseModel):
    """A durable, free-text fact or preference the athlete has told the coach ("I prefer
    kettlebells to free weights", "call me Bob", "3 bikes; flat pedals when teaching skills").

    Deliberately open: `category` is a free label (never a fixed vocabulary), and a note is
    never deleted -- changing one retires it (`active=False`) so history is kept."""

    id: UUID
    text: str
    category: str | None = None
    created: date
    active: bool = True


class RaceDebrief(BaseModel):
    """A structured record of a post-race (or post-key-session) interview -- what the coach and
    athlete learned, kept as durable history the way `AthleteNote` keeps preferences (never
    deleted; `Athlete.race_debriefs` only ever grows).

    Andrew, 2026-09-22, reading a real transcript from a second coaching tool that produced a
    visibly better-targeted block off exactly this kind of interview: the value isn't the
    interview text itself, it's that the CONCLUSION gets written down once and then every later
    planning turn can read it back, instead of re-deriving "what does this athlete need to work
    on" from raw logs every single time. Two fields are the athlete's own two requested opening
    questions (`went_well`/`work_on`); `data_findings` and `tactical_note` capture what the
    analyzer/official-result cross-check and the race-tactics half of the conversation turned up,
    kept separate from `training_implication` (what should actually change in the PLAN) because a
    race-day tactic (where to line up) and a training change (what to build into a session) are
    different kinds of follow-up with different owners -- see `save_race_debrief`'s docstring for
    the full split and why each is optional, not required."""

    id: UUID
    event_id: UUID | None = None
    event_name: str
    event_date: date
    logged: date
    result: str | None = None
    went_well: str | None = None
    work_on: str | None = None
    data_findings: list[str] = Field(default_factory=list)
    training_implication: str | None = None
    tactical_note: str | None = None


class Athlete(BaseModel):
    """The athlete profile: identity, CSS pace, zones, constraints, pool schedule."""

    schema_version: int = 1
    id: UUID
    slug: str
    name: str
    css_pace_s_per_100m: float | None = None
    zones: dict | None = None
    constraints: dict = Field(default_factory=dict)
    pool_schedule: list[str | dict] = Field(default_factory=list)
    training_days: dict[str, list[str | dict]] | None = None
    # IDEA 023 phase 1 -- scheduling preferences the week GENERATOR honors, so
    # they survive every regeneration of a week (they live on the athlete, not
    # in a chat). A `training_days` entry may be a dict carrying, besides its
    # `day`, a `label` (e.g. a standing club ride's name) and a `role`:
    # "hard" (the week's interval day) or "endurance" (a Z2 day). A standing
    # commitment is just an endurance-role entry with a label. Roles/labels are
    # applied in build/base weeks only; taper and race weeks ignore them (the
    # taper/race generators' own placement wins).
    #
    # `strength_placement`: "same_day_as_hard" puts the week's first strength
    # session on the interval day, after the intervals (recovery-wise: one
    # hard day instead of two); "after_hard" / None keep the engine's default
    # (after the hard day, same day or later, never the day before a hard/race
    # day). Additive/optional, no schema_version bump.
    strength_placement: Literal["after_hard", "same_day_as_hard"] | None = None
    # IDEA 023 v3 -- the WEEKLY TEMPLATE: the athlete states the SHAPE of their
    # week and the engine fills in content and volume. Maps a weekday
    # ("mon".."sun", any case, full names accepted) to an ORDERED list of
    # session slots for that day; a day that is absent or `[]` is a day off.
    # A slot is `{"kind": ..., "role"?: ..., "label"?: ..., "duration_min"?: ...}`:
    #   kind "bike"      + role "hard" (an interval session; several per week
    #                      are fine; `intervals` picks the type, else the weekly rotation)
    #                    | role "endurance" (a Z2 ride, e.g. a club group ride)
    #                    | role "flex" (Z2 by default with an optional push -- a ride that can
    #                      be easy OR pushed, e.g. a group ride; never counts as a hard day)
    #   kind "skills"    cyclocross bike-handling session
    #   kind "strength"  dryland strength (noted "after the intervals" when it
    #                    follows a hard ride the same day)
    #   kind "yoga"      yoga/mobility (a `recovery` session)
    #   kind "recovery"  an easy recovery/mobility session
    # Any slot may also carry `purpose`: the athlete's OWN description of the
    # session (e.g. a kettlebell EMOM), used verbatim in place of the engine's
    # generic text -- a bike slot keeps its engine-built intervals/structure.
    # Applied in build/base weeks only; taper and race weeks use the engine's
    # own placement and the week carries a planning_warning saying so. Volume
    # still comes from the macro's ramp-capped target -- a template sets the
    # structure, never the load. Additive/optional, no schema_version bump.
    weekly_template: dict[str, list[dict]] | None = None
    # Durable free-text preferences and facts the coach remembers and applies (see AthleteNote).
    # Stored on the athlete record, so it needs no migration. Additive/optional.
    notes: list[AthleteNote] = Field(default_factory=list)
    # Post-race/key-session interview history (see RaceDebrief). Same "stored on the athlete,
    # never deleted, no migration" shape as `notes` -- additive/optional.
    race_debriefs: list[RaceDebrief] = Field(default_factory=list)
    # Per-sport weekly training-day PATTERN -- the bike/strength/skills
    # counterpart to `pool_schedule` above (which only ever covered pool
    # days). Maps a session-kind key ("bike", "strength", "skills" -- free
    # strings; only those three are consumed by the engine today) to an
    # ordered list of weekday entries in the SAME `str | dict` shape
    # `pool_schedule` accepts ("tue" / "tuesday" / {"day": "tue"}), so
    # `plan._pool_day_offset` resolves both. Order is meaningful: the FIRST
    # bike entry is treated as the week's hard/interval day (see
    # `plan._bike_week_sessions`). A `"skills"` entry places a cyclocross
    # bike-handling session (`plan._skills_sessions`) on those weekdays for
    # a `primary_sport="bike"` week. `None` (the default) means "no pattern
    # declared" -- `plan.generate_week`'s bike path then falls back to
    # `_spread_days_evenly`'s even spacing exactly as before, byte-for-byte,
    # for every existing profile.yaml (no `training_days` key). Additive/
    # optional, no schema_version bump, same convention as every other
    # additive field in this file.
    # Demographic fields: all optional, defaulting to None, so every
    # existing profile.yaml (with none of these keys) keeps validating
    # unchanged -- additive, no schema_version bump needed. Store dob, not
    # age, so age stays correct as time passes rather than going stale the
    # day after it's recorded; callers derive age from dob relative to
    # "today" (see backend/app/context.py's `build_per_request_context`,
    # which resolves that via `athlete_time.athlete_today` -- this
    # athlete's own local date when `timezone` below is set, plain
    # `date.today()` otherwise).
    dob: date | None = None
    sex: Literal["male", "female", "other"] | None = None
    height_cm: float | None = Field(default=None, gt=0)
    weight_kg: float | None = Field(default=None, gt=0)
    has_pool_coach: bool = True
    # Defaults True -- zero behavior change for every existing profile.yaml
    # (no key present) unless explicitly set False. True means a real
    # masters/pool coach hands out this athlete's pool-day workout content
    # post-hoc (the system's original, still-default assumption); False
    # means no such coach is on deck, so `generate_week` (plan.py) must
    # author real warm-up/main-set/cool-down structure for those pool-day
    # sessions itself instead of emitting a content-less placeholder.
    email_notifications_enabled: bool = True
    # Settings-tab toggle (coach-mode Q&A notification build): gates BOTH
    # directions of the Resend email wiring in `backend/app/notify.py` --
    # this athlete's own email as a Feedback recipient (coach-reply
    # notifications) AND, when this athlete is acting as a COACH (coaches
    # are themselves athlete accounts, see CoachGrant's docstring), this
    # athlete's own email as a coach notified of a new question. Defaults
    # True per this session's explicit decision -- zero behavior change for
    # every existing profile.yaml (no key present) unless explicitly toggled
    # off, same additive/no-schema_version-bump convention as
    # `has_pool_coach` above.
    sports: list[Sport] | None = None
    # Which sport(s) this athlete's OWN training actually spans -- IDEA 008's
    # "never surface cycling guidance to a swim-only athlete" hard
    # requirement (`engine/cycling-coach` branch), the structural half of
    # the constraint `library/23-cycling-training.md`'s own guidance-scoping
    # note names. `None` (the default) means "not yet declared" -- every
    # existing athlete's profile.yaml has no `sports` key today. Additive/
    # optional, no schema_version bump, same convention as every other
    # additive field in this file.
    #
    # **Do not read this raw field for sport-scope routing -- use
    # `effective_sports` below.** A real review bug (PR #167 review,
    # Finding 1): `backend/app/context.py`'s sport-scope filtering used to
    # treat `sports is None` as "apply no filtering at all" (i.e. every
    # sport), which meant cycling library content reached 100% of real
    # athletes -- every one of whom has `sports=None` today, since setting
    # it on real athlete data was explicitly deferred. `None` must mean
    # "not yet declared, so assume swim-only" (this project's actual
    # population today), never "declared as every sport."

    @property
    def effective_sports(self) -> list[Sport]:
        """`sports` resolved to a concrete list for any consumer that needs
        to know which sport(s) actually ground this athlete's routing/
        guidance scope -- an unset `sports` field behaves as swim-only
        (`["swim_pool", "swim_ow"]`), matching every real athlete's actual
        training today, NEVER as "every sport." See the bug this fixes in
        `sports`'s own comment above. Prefer this over reading `.sports`
        directly wherever a concrete sport list is actually needed (sport-
        scope library routing today); `.sports` itself stays `None`-capable
        for callers that specifically care whether the athlete has ever
        declared it at all.
        """
        return self.sports if self.sports is not None else ["swim_pool", "swim_ow"]

    lthr_bpm: int | None = None
    # Lactate-threshold heart rate (bpm) -- a physiological anchor the
    # athlete supplies directly (e.g. from a field test, or read off a
    # platform like intervals.icu/Garmin that already estimates it), the
    # same role `css_pace_s_per_100m` plays for swim pace: a real,
    # athlete-specific reference point rather than a population default or
    # an incidentally-observed extreme. Used by `load.py`'s HR-based TRIMP
    # tier to rescale onto the same "100 = one hour at threshold" unit TSS
    # uses for power -- see that module's `_normalize_trimp_to_lthr_hour`
    # and `library/15-tiered-session-load.md`. `None` (the default) leaves
    # tier 2 exactly as before -- raw, un-normalized TRIMP -- for every
    # existing profile.yaml (no key present) and any athlete who hasn't
    # set one. Additive, no schema_version bump.
    ftp_watts: float | None = None
    # Functional Threshold Power (watts) -- cycling's own physiological
    # anchor, the same role `css_pace_s_per_100m` plays for swim pace and
    # `lthr_bpm` plays for HR (engine/cycling-coach Part C). Used by
    # `zones.bike_zone_table` (via `plan._bike_step`/`_bike_week_sessions`)
    # to resolve a bike session's %FTP zone into absolute watts, and by
    # `backend/app/zwo_export.build_zwo_export` to express a `.zwo` file's
    # power targets as fractions of a real, athlete-specific FTP rather than
    # an arbitrary one supplied per-request. `None` (the default) leaves
    # every existing profile.yaml (no key present) validating unchanged --
    # `generate_week`'s bike path already tolerates `ftp_watts=None`
    # gracefully (zone-name-only targets, no absolute watts), and the `.zwo`
    # export route/tool return a clear 422 rather than guessing at a number
    # when it's missing. Additive, no schema_version bump.
    carb_tolerance_g_per_hr: float | None = None
    # In-session carbohydrate-tolerance anchor (grams/hour) -- mirrors
    # `ftp_watts` exactly (engine/fueling-calculator build), the same
    # human-set-by-design posture: never auto-inferred, set via
    # `update_athlete_profile` once a `ThresholdRecord` reading (or the
    # athlete's own report) is judged trustworthy. Consumed by
    # `swim_coach.fueling.compute_fueling_plan`, which falls back to its own
    # `DEFAULT_CARB_TOLERANCE_G_PER_HR` (60 g/h, library/08-ultra-feeding.md's
    # single-transportable-carbohydrate gut-absorption ceiling) when this is
    # `None` -- per this build's brief, verbatim from Andrew: "when did you
    # train at this rate?" is the real mechanism for surfacing an unset
    # value, not a silently-assumed number (see that tool's own docstring).
    # `None` (the default) leaves every existing profile.yaml (no key
    # present) validating unchanged. Additive, no schema_version bump, same
    # convention as every other additive field in this file.
    home_elevation_m: float | None = None
    # This athlete's real, usual training elevation -- the anchor
    # `interval_analysis.analyze`'s altitude-context signal compares a
    # ride's own altitude against (`library/30-altitude-power-adjustment.
    # md`). **Human-set by design, same posture as `ftp_watts`/`lthr_bpm`/
    # `css_pace_s_per_100m` above and `ThresholdRecord` below -- never
    # auto-inferred.** A rolling average of recent ride-start elevations was
    # considered and explicitly rejected: partial altitude acclimatization
    # is real physiology but slow and partial, and an automatic rolling
    # baseline cannot distinguish "genuinely living/training at elevation
    # for weeks" from "traveling this week" -- it would silently launder a
    # travel week into a new baseline exactly when the athlete most needs
    # the flag to fire. `None` (the default) leaves every existing
    # profile.yaml unchanged: `analyze` falls back to its original
    # session-relative heuristic (`_ride_baseline_altitude_m`) for any
    # athlete who hasn't set this. Additive, no schema_version bump.
    timezone: str | None = None
    # This athlete's own IANA timezone name (e.g. "America/Denver"),
    # **human-set by design, same posture as `ftp_watts`/`lthr_bpm`/
    # `home_elevation_m` above -- never auto-inferred or guessed.** Root-fix
    # for a real, confirmed bug (feedback entry ed20cbfb-d5a5-4716-9afd-
    # 87fbbc7cc810): before this field existed, the backend had NO
    # per-athlete timezone concept at all, and `date.today()` (server/
    # process local time -- UTC on Cloud Run in production) stood in as
    # "the athlete's today" across every plan-math call site that needed
    # one, which is silently wrong for any athlete not physically in UTC --
    # an evening workout logged in the athlete's own local time can land on
    # the wrong calendar day server-side, and a taper/event runway computed
    # from server-UTC "today" can read a day short right at a UTC day
    # boundary. See `athlete_time.athlete_today`, the resolver this field
    # feeds: it uses `Athlete.timezone` (via `zoneinfo.ZoneInfo`) when set,
    # and falls back to plain `date.today()` (server time, unchanged
    # behavior) when unset. `None` (the default) leaves every existing
    # profile.yaml (no `timezone` key -- 100% of real athletes as of this
    # field's introduction) validating and behaving byte-for-byte
    # unchanged. Additive, no schema_version bump, same convention as every
    # other additive field in this file.
    #
    # Validated (not a bare, format-free `str | None`) via the
    # `_validate_timezone` field_validator below: Python's own `zoneinfo`
    # module already ships the IANA database this needs, so checking
    # `ZoneInfo(name)` doesn't raise is a near-zero-cost way to catch a
    # typo'd/invalid zone name at profile-save time (a clear validation
    # error) rather than at first use, deep inside plan-math code, as an
    # unhandled `ZoneInfoNotFoundError`. This is a deliberate, narrow
    # departure from this file's usual "no format validation on a human-set
    # string field" convention (`ftp_watts`/`lthr_bpm`/etc. take any
    # float): those fields fail safely (a wrong number is still a number
    # that flows through the same math), but a malformed timezone name
    # fails LOUD, deep in a code path this field's whole purpose is to make
    # MORE correct, not less -- validating at the boundary is worth the
    # small departure here.

    @field_validator("weekly_template")
    @classmethod
    def _validate_weekly_template(
        cls, value: dict[str, list[dict]] | None
    ) -> dict[str, list[dict]] | None:
        """Normalizes weekday keys to "mon".."sun" and every slot to a writable shape.

        POLICY (Andrew, 2026-09-21: hard codes must never block a coach from WRITING a week):
        anything unusual is normalized WITH A NOTE (`_note` on the slot, surfaced by
        `plan.template_normalization_notes`), never rejected. Only input that cannot be
        placed at all is an error: a key that is not a weekday, or a slot with no `kind`."""
        if value is None:
            return None
        days = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
        sports = ("swim_pool", "swim_ow", "strength", "recovery", "cross_train", "bike")
        kind_aliases = {
            "mobility": "yoga", "stretch": "yoga", "stretching": "yoga",
            "weights": "strength", "lifting": "strength", "gym": "strength", "kettlebell": "strength",
            "kettlebells": "strength", "kb": "strength", "core": "strength", "strength training": "strength",
            "cx skills": "skills", "cyclocross skills": "skills", "bike skills": "skills",
        }
        hard_words = {"hard", "interval", "intervals", "vo2", "vo2max", "threshold", "tempo", "sweet spot",
                      "sweetspot", "race pace", "race-pace", "sprint", "sprints"}
        easy_words = {"endurance", "easy", "z2", "zone 2", "long", "group", "social", "base", "aerobic", "steady"}
        flex_words = {"flex", "flexible", "either", "optional", "choose", "z2 or threshold", "easy or hard", "z2 or hard"}
        text_caps = {"label": 200, "purpose": 1500, "structure": 6000}
        out: dict[str, list[dict]] = {}
        for raw_day, slots in value.items():
            day = str(raw_day).strip().lower()[:3]
            if day not in days:
                raise ValueError(f"weekly_template day {raw_day!r} is not a weekday (mon..sun)")
            if day in out:
                raise ValueError(f"weekly_template lists {day!r} twice")
            normalized: list[dict] = []
            for original in slots:
                raw_kind = original.get("kind")
                if not isinstance(raw_kind, str) or not raw_kind.strip():
                    raise ValueError("every weekly_template slot needs a `kind` (e.g. bike, strength, yoga, swim)")
                slot = dict(original)
                notes: list[str] = [slot["_note"]] if slot.get("_note") else []
                kind = raw_kind.strip().lower()
                kind = kind_aliases.get(kind, kind)
                slot["kind"] = kind
                if kind == "bike":
                    role = slot.get("role")
                    word = role.strip().lower() if isinstance(role, str) else None
                    if word in flex_words:
                        slot["role"] = "flex"
                    elif word in hard_words:
                        slot["role"] = "hard"
                    elif word in easy_words:
                        slot["role"] = "endurance"
                    else:
                        slot["role"] = "endurance"
                        notes.append(
                            "bike slot had no role, treated as an endurance ride"
                            if role is None
                            else f"bike role {role!r} not recognised, treated as an endurance ride"
                        )
                elif "role" in slot:
                    slot.pop("role")
                    notes.append(f"role ignored: it only applies to bike slots, not {kind!r}")
                if "intervals" in slot:
                    chosen = normalize_interval_type(slot["intervals"])
                    if kind != "bike" or slot.get("role") == "endurance":
                        notes.append(f"intervals {slot.pop('intervals')!r} ignored: it only applies to hard or flex bike rides")
                    elif chosen is None:
                        notes.append(f"intervals {slot.pop('intervals')!r} is not a known interval type, so the weekly rotation is used")
                    else:
                        slot["intervals"] = chosen
                for name, cap in text_caps.items():
                    if name in slot:
                        if not isinstance(slot[name], str):
                            slot.pop(name)
                            notes.append(f"{name} dropped: it must be text")
                        elif len(slot[name]) > cap:
                            slot[name] = slot[name][:cap]
                            notes.append(f"{name} truncated to {cap} characters")
                if "duration_min" in slot:
                    d = slot["duration_min"]
                    if isinstance(d, bool) or not isinstance(d, (int, float)):
                        slot.pop("duration_min")
                        notes.append("duration_min dropped: it must be a number")
                    elif not 5 <= d <= 900:
                        slot["duration_min"] = min(max(d, 5), 900)
                        notes.append(f"duration_min {d} clamped to {slot['duration_min']}")
                if "distance_m" in slot:
                    m = slot["distance_m"]
                    if isinstance(m, bool) or not isinstance(m, (int, float)) or m < 0:
                        slot.pop("distance_m")
                        notes.append("distance_m dropped: it must be a non-negative number")
                if "sport" in slot and slot["sport"] not in sports:
                    notes.append(f"sport {slot.pop('sport')!r} not recognised, ignored")
                if notes:
                    slot["_note"] = "; ".join(dict.fromkeys(notes))
                normalized.append(slot)
            out[day] = normalized
        return out

    @field_validator("training_days")
    @classmethod
    def _validate_training_days(
        cls, value: dict[str, list[str | dict]] | None
    ) -> dict[str, list[str | dict]] | None:
        """Dict entries (the IDEA 023 label/role form) must carry a `day` and,
        when present, a `role` of "hard" or "endurance" and a string `label`.
        Plain string entries keep their historical lazy validation."""
        for entries in (value or {}).values():
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                if not entry.get("day"):
                    raise ValueError(f"training_days entry {entry!r} needs a 'day'")
                if entry.get("role") not in (None, "hard", "endurance"):
                    raise ValueError(
                        f"training_days role must be 'hard' or 'endurance', got {entry['role']!r}"
                    )
                if entry.get("label") is not None and not isinstance(entry["label"], str):
                    raise ValueError(f"training_days label must be a string, got {entry['label']!r}")
        return value

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str | None) -> str | None:
        """`None` passes straight through (not set -- the overwhelmingly
        common, always-valid case). A non-`None` value must be a real IANA
        zone name `zoneinfo.ZoneInfo` recognizes; see the field's own
        comment above for why this field departs from this file's usual
        no-format-validation convention."""
        if value is None:
            return value
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(
                f"{value!r} is not a recognized IANA timezone name (e.g. 'America/Denver')"
            ) from exc
        return value


class Event(BaseModel):
    """A target event (e.g. a channel swim) the athlete is training toward."""

    schema_version: int = 1
    id: UUID
    athlete_id: UUID
    name: str
    event_date: date
    target_metric: Literal["distance_m", "duration_min", "load_au"] = "distance_m"
    # Discriminator for what this event's target is measured in -- follows
    # this codebase's own `basis`-discriminator idiom (see WorkoutTarget/
    # WorkoutLoad above: a discriminator field + generic value field(s)
    # reused across variants, documented per-variant in comments) rather
    # than a true `Field(discriminator=...)` tagged union of separate
    # classes (that mechanism exists here too -- WorkoutStepOrRepeat -- but
    # is reserved for structurally different tree nodes, not this case).
    # No single universal target metric exists across sports (multi-sport-
    # unlock design discussion, ROADMAP.md IDEA 007-010): duration+intensity
    # is what actually tells you something for cycling ("a 2-hour endurance
    # ride tells me what I need to know"); distance is genuinely the right
    # universal unit for swimming, especially open water where pace is
    # unknown; strength is measured in cumulative work (e.g. total lbs
    # lifted). Defaults to "distance_m" so every existing Event YAML (no
    # target_metric key) validates unchanged and means exactly what it
    # always meant -- additive, no schema_version bump.
    primary_sport: Literal["swim", "bike"] = "swim"
    # Which sport this event is FOR -- deliberately the same `Literal["swim",
    # "bike"]` shape `plan.generate_week`'s own `primary_sport` parameter
    # already uses (not the finer-grained `Sport` enum `Workout`/`Session`
    # rows use, which distinguishes `swim_pool`/`swim_ow` -- an event's
    # primary discipline doesn't need that granularity). Deliberately
    # ORTHOGONAL to `target_metric` above: `target_metric` says what UNIT
    # this event's target is measured in (distance/duration/load),
    # `primary_sport` says WHICH SPORT it's for -- do not infer one from the
    # other anywhere, going forward. That conflation was a real, audited bug
    # (threshold-history build): `backend/app/tools.py`'s
    # `_handle_propose_adaptation` and `cli.py`'s `_cmd_adapt` used to derive
    # `primary_sport = "bike" if event.target_metric != "distance_m" else
    # "swim"` -- invisible only while bike was the sole non-swim sport and
    # happened to always use `duration_min`; a future running event (running
    # is typically ALSO distance-based, e.g. a 5K) would be misidentified as
    # "swim" under that inference. A plain, flat `Literal` string list (not
    # a richer type) is the right shape for "cheap to extend later, don't
    # over-engineer now" -- same precedent as `ThresholdRecord.metric` and
    # `00-conventions.md`'s `[EVIDENCE: <discipline>]` tag -- extend the
    # Literal with each new sport as it's actually built (running next, per
    # ROADMAP.md). Defaults "swim" so every existing Event YAML (no
    # primary_sport key) validates unchanged and means exactly what it
    # always meant -- additive, no schema_version bump, matching every other
    # additive field in this file.
    distance_m: int | None = Field(default=None, gt=0)
    # Relaxed from required (`Field(gt=0)`) to optional -- required in
    # practice (enforced by `_validate_target_metric_fields` below) only
    # when target_metric == "distance_m". Deliberately KEPT AS ITS OWN
    # NAMED FIELD rather than folded into `target_value` below -- a
    # deliberate departure from WorkoutTarget/WorkoutLoad's pure single-
    # generic-value idiom. `distance_m` is consumed BY NAME across ~10 real
    # call sites (the create_event tool schema, the onboarding route, the
    # PWA plan-view form/validation and long-swim-ladder rendering, the
    # JSON export, and 20+ existing tests) -- renaming it would be a much
    # wider, riskier blast radius than this build needs.
    target_value: float | None = None
    # Meaning depends on target_metric: minutes when target_metric ==
    # "duration_min", AU (arbitrary training-load units, see load.py's
    # module docstring) when target_metric == "load_au". Unused/None when
    # target_metric == "distance_m" (distance_m carries that meaning
    # instead, see above). Required in practice (enforced below) whenever
    # target_metric != "distance_m".
    water_temp_c: float | None = None
    wetsuit: bool = False
    priority: str
    event_format: Literal["single_day", "multi_day_stage"] = "single_day"
    # Default preserves current (pre-Day-4) behavior: every existing Event
    # YAML file with no event_format key validates as "single_day", and
    # plan.py's/adapt.py's single-continuous-long-swim ladder is exactly what
    # generate_week already produced before this field existed. See
    # ROADMAP.md "Event format parameter + long-swim progression" and
    # library/06-long-swim-progression.md.
    active: bool = True
    # Soft delete/reactivate flag (backend/app/tools.py's
    # set_event_active_status), NOT a hard delete -- a macro's event_id can
    # still reference an event after the athlete has moved on, and
    # hard-deleting risks orphaning that reference. Defaults True so every
    # existing Event YAML (no active key) and every newly-created event via
    # create_event validates/behaves unchanged -- purely additive, no
    # schema_version bump. Existing event-by-id/-name lookups elsewhere
    # (draft_macro_plan/replace_macro_plan/propose_adaptation) deliberately
    # do NOT filter on this field -- it only changes how the coach *talks
    # about* events in conversation, never which events those lookups find.

    @model_validator(mode="after")
    def _validate_target_metric_fields(self) -> "Event":
        """Cross-field rule: `distance_m` is required when target_metric ==
        "distance_m"; `target_value` is required otherwise. New precedent --
        this codebase has zero existing `model_validator`s (only
        `field_validator`s on individual fields) before this one; kept
        deliberately small and narrowly scoped to this single cross-field
        rule, not a general validation-framework expansion.
        """
        if self.target_metric == "distance_m":
            if self.distance_m is None:
                raise ValueError(
                    "distance_m is required when target_metric == 'distance_m'"
                )
        elif self.target_value is None:
            raise ValueError(
                f"target_value is required when target_metric is {self.target_metric!r} "
                "(not 'distance_m')"
            )
        return self


class WorkoutTarget(BaseModel):
    """Intensity target for a cardio-style (swim) `WorkoutStep`.

    `basis` distinguishes a TEMPLATE's relative target from a resolved
    WORKOUT's absolute one -- the same shape serves both stages of the
    template/workout split (see `workout_templates.resolve_template`, the
    one place this resolution happens). A template step carries
    `basis="zone"` (e.g. Z3) or `basis="percent_css"` (e.g. 135% of CSS)
    with no athlete-specific numbers; resolving a template against an
    athlete's `css_pace_s_per_100m` (via `zones.zone_table`) fills in
    `basis="absolute"` `low`/`high` pace values (seconds per 100m).
    `rpe`/`open` never need resolving -- already athlete-relative or
    deliberately untargeted. `rpe` reuses `low`/`high` too (a 1-10 value,
    the same scale `Workout.rpe` already uses athlete-facing elsewhere in
    this app) rather than a dedicated field -- `low`/`high` are already
    generic per-`basis` numbers, so a distinct `rpe_value` field would just
    duplicate that shape for no benefit. No engine-generated template sets
    `basis="rpe"` today (every real swim/strength template resolves off CSS
    or is `basis="bodyweight"` -- see `plan.py`'s `_additional_swim_
    structure_template`/`_strength_session_structure_template`); it exists
    for the coach's ad hoc structured-authoring tool (`backend/app/tools.py`'s
    `create_week_plan`/`replace_week_plan` `structured` param) to use on a
    genuinely effort-based day (recovery, technique) where no pace target
    is the right anchor.

    `basis="power_w"` (engine/cycling-coach Part C -- delivery/logging):
    the bike-modality RESOLVED counterpart to `basis="absolute"` above --
    `low`/`high` are absolute watts (not pace), populated by
    `plan._bike_step` from `zones.bike_zone_table` once an athlete's
    `ftp_watts` is known. `basis="zone"` still covers the bike case where
    FTP is unknown (the zone name alone, e.g. "Z2", for a device to apply
    its own configured power zone -- same graceful partial-data fallback
    `_bike_step`'s docstring documents); `"power_w"` is only ever reached
    once real watts numbers exist. Not reusing `"absolute"` itself: that
    basis's `low`/`high` are documented everywhere else in this codebase
    (`workout_templates.resolve_template`, `garmin_export._apply_target`)
    as seconds-per-100m pace specifically, and silently overloading its
    unit by modality would be a real footgun for any future reader who
    forgets to check `WorkoutStep.modality` first.
    """

    schema_version: int = 1
    basis: Literal["zone", "percent_css", "absolute", "rpe", "open", "power_w"]
    zone: Literal["Z1", "Z2", "Z3", "Z4", "Z5"] | None = None  # basis="zone"
    low: float | None = None  # percent_css: % of CSS; absolute: pace_s_per_100m; rpe: 1-10; power_w: watts
    high: float | None = None  # same units as low


class WorkoutLoad(BaseModel):
    """Resistance target for a strength-style `WorkoutStep` -- same
    relative/resolved split as `WorkoutTarget`, against 1RM instead of CSS.
    """

    schema_version: int = 1
    basis: Literal["bodyweight", "percent_1rm", "absolute", "rpe_only"]
    value: float | None = None  # percent_1rm: 0-100; absolute: resolved weight


class WorkoutStep(BaseModel):
    """One leaf node in a `WorkoutStructure` tree -- a single swim rep/segment
    or a single strength exercise. `kind` is the tagged-union discriminator
    that lets `WorkoutRepeat.steps` hold a mix of steps and nested repeats
    (see `WorkoutStepOrRepeat` below)."""

    schema_version: int = 1
    kind: Literal["step"] = "step"
    label: str  # athlete-facing short name
    role: Literal["warmup", "steady", "interval", "rest", "recovery", "cooldown", "open", "ramp"]
    # "ramp" added for the bike ramp-test generator (`plan._bike_ramp_test_
    # structure` -- threshold-history build): a genuine mid-workout power
    # PROGRESSION (start low, climb steadily to a real ceiling), unlike
    # every other role's flat/fixed target. Before this, no real producer
    # in this codebase ever emitted a role whose `WorkoutTarget` low/high
    # bounds were meant to be read as "climbs from low to high over the
    # step's duration" rather than "a flat target band" -- `zwo_export.
    # _convert_leaf`'s own `<Ramp>`-element branch existed only as
    # defensive/forward-compatible dead code, documented there as
    # UNREACHABLE via any value of this Literal that existed at the time.
    # "ramp" is the first role that actually reaches it.
    duration_kind: Literal["time_s", "distance_m", "reps", "open"]
    duration_value: float | None = None
    target: WorkoutTarget | None = None  # swim/cardio steps
    load: WorkoutLoad | None = None  # strength steps
    modality: Literal["swim", "strength", "bike"] = "swim"
    # "bike" added alongside `Sport`'s own "bike" value (engine/cycling-coach
    # branch) -- a harder, per-step constraint than `Session.sport` since a
    # single WorkoutStructure tree's steps are all one modality in practice
    # today (see `workout_templates.render_main_set`'s modality-uniformity
    # assumption). Real cycling `WorkoutStep`s ARE now constructed by
    # `plan._bike_session_structure` (engine/cycling-coach Part C) -- a
    # minimal warm-up/main-block/cool-down shape, the same
    # deferred-until-delivery-stage groundwork this comment originally
    # flagged. Additive/no schema_version bump.
    stroke: Literal["free", "back", "breast", "fly", "im", "mixed", "drill"] | None = None
    equipment: list[str] = Field(default_factory=list)  # e.g. ["paddles"]
    exercise_name: str | None = None  # strength steps, e.g. "kettlebell swing"
    reference_url: str | None = None  # technique/demo link
    # Optional coach- or engine-set link (e.g. plan.py's
    # STRENGTH_EXERCISE_REFERENCE_URLS, or a coach-authored step's own URL
    # via session_overrides' `structured`) shown to the athlete as a
    # clickable technique/demo reference and written into the exported FIT
    # step's notes -- see garmin_export.py's `_build_leaf_step`. Additive/
    # optional, same pattern as `Session.structured` above: every existing
    # persisted WorkoutStep has no `reference_url` key and validates
    # unchanged as `reference_url=None`; no schema_version bump.


class WorkoutRepeat(BaseModel):
    """A loop wrapper around an ordered list of steps (nested repeats
    allowed, rarely used). `repeat_mode` matters more than it looks -- a
    plain `count` (execute N times) can't express EMOM ("every minute on
    the minute" -- a new round starts on a fixed interval regardless of how
    long the round took, `for_duration` + `interval_s`) or AMRAP (as many
    rounds/reps as possible in a time window, `amrap` + `duration_s`).
    Without this distinction, `isEMOM`/`isAMRAP` become underivable and
    collapse back into exactly the kind of hand-typed, drift-prone tag this
    model is designed to avoid -- so this needs to be right at the model
    level, not patched on later.
    """

    schema_version: int = 1
    kind: Literal["repeat"] = "repeat"
    repeat_mode: Literal["count", "for_duration", "amrap"] = "count"
    count: int | None = None  # repeat_mode == "count"
    duration_s: float | None = None  # for_duration/amrap: total window length
    interval_s: float | None = None  # for_duration: e.g. 60 for classic EMOM
    steps: list["WorkoutStepOrRepeat"]  # nested loops allowed, rarely used


# Tagged union on `kind` so pydantic v2 can discriminate step vs. repeat
# nodes in `WorkoutRepeat.steps` / `WorkoutStructure.items` without a class
# hierarchy (WorkoutStep/WorkoutRepeat stay flat siblings, matching this
# file's no-inheritance house style).
WorkoutStepOrRepeat = Annotated[WorkoutStep | WorkoutRepeat, Field(discriminator="kind")]
WorkoutRepeat.model_rebuild()


class WorkoutStructure(BaseModel):
    """The canonical structured workout intermediate representation (IR).
    Both a workout TEMPLATE (relative targets) and a resolved WORKOUT
    (absolute targets) use this same shape -- see `WorkoutTarget`/
    `WorkoutLoad`'s `basis` field and `workout_templates.resolve_template`.
    Prose (`Session.structure`) and any future device export (Garmin, etc.)
    are both just renderings of this IR, never the source of truth.
    """

    schema_version: int = 1
    items: list[WorkoutStepOrRepeat]  # top-level ordered sequence


class Session(BaseModel):
    """A single planned session within a WeekPlan."""

    schema_version: int = 1
    id: UUID
    athlete_id: UUID
    date: date
    sport: Sport
    source: Literal["ai_coach", "pool_coach", "athlete"]
    duration_min: float = Field(gt=0)
    distance_m: int | None = Field(default=None, ge=0)
    intensity: dict
    purpose: str
    structure: str | None = None
    structured: WorkoutStructure | None = None
    # Canonical structured IR alongside the legacy prose `structure` field
    # (kept, not replaced -- see workout_templates.py / plan.py module
    # docstrings for the migration rationale). Additive/optional: every
    # existing persisted Session (YAML file or DB jsonb row) has no
    # `structured` key and validates unchanged as `structured=None`; no
    # schema_version bump, no backfill, same pattern as every other
    # additive field in this file.
    status: Literal["planned", "completed", "skipped", "replaced"] = "planned"
    is_indoor: bool | None = None
    # Engine/cycling-coach Part C (delivery/logging): the lightweight signal
    # this build's own brief asked for -- "does this bike session need the
    # outdoor Garmin/intervals.icu push, or the indoor/trainer .zwo export"
    # (see `backend/app/garmin_push.py` and `swim_coach.zwo_export`). `None`
    # (the default) means "not indoor" for gating purposes -- every real bike
    # session this engine currently generates (`plan._bike_week_sessions`)
    # is a generic outdoor Z2/Z3 ride (matching this athlete's real,
    # already-flowing production `.fit` data: "cycling/mountain",
    # "cycling/road", all outdoor sub_sports), so defaulting to the outdoor
    # push path is the honest default, not a guess. Only ever meaningful for
    # `sport == "bike"` today; every other sport ignores this field. Purely
    # additive/optional, no schema_version bump, same convention as every
    # other additive field in this file.

    @field_validator("intensity")
    @classmethod
    def _validate_intensity(cls, v: dict) -> dict:
        zone = v.get("zone")
        anchor = v.get("anchor")
        if zone is not None and zone not in _VALID_ZONES:
            raise ValueError(f"invalid zone: {zone!r}, must be one of {sorted(_VALID_ZONES)}")
        if anchor is not None and anchor not in _VALID_ANCHORS:
            raise ValueError(
                f"invalid anchor: {anchor!r}, must be one of {sorted(_VALID_ANCHORS)}"
            )
        return v


class RaceWeekChecklistItem(BaseModel):
    """One dated, categorized action item surfaced on the final taper week
    immediately preceding an athlete's active A-priority event -- see
    `engine/swim_coach/plan.py`'s `_race_week_checklist` for how these are
    computed and `library/16-race-week.md` for the citations/rationale
    behind each category.

    `date` is the specific calendar date the item applies to, computed
    directly from `Event.event_date` -- it is deliberately NOT guaranteed
    to fall within the parent `WeekPlan`'s own Monday-Sunday span. A race
    that isn't itself on a Monday (the common case) pushes windows like the
    36-72h pre-race carbohydrate-load onto calendar days that land in the
    following week -- the one containing the event itself, which
    `plan.scaffold_macro`/`generate_week` deliberately don't model as a
    macro block (see that module's docstring: "race week itself is ...
    handled separately"). A per-session field couldn't represent a date
    outside the week it's attached to; this dedicated, independently-dated
    list can.

    `category` distinguishes the three genuinely different kinds of content
    this list can carry, each with its own timing/evidence basis -- see
    `plan.py`'s citation comments for each:
      - "carb_load": the 36-72h pre-race carbohydrate-loading window.
      - "bodywork": the 3-5-day-out light bodywork/massage window.
      - "logistics": athlete-specific event-logistics checklist items
        (travel/acclimatization, fueling-plan rehearsal, support-crew
        confirmation) derived from the event's own fields, not universal
        taper science.
    """

    schema_version: int = 1
    date: date
    category: Literal["carb_load", "bodywork", "logistics"]
    label: str


class WeekPlan(BaseModel):
    """One week of planned sessions."""

    schema_version: int = 1
    id: UUID
    athlete_id: UUID
    iso_week: str
    meso_block: str
    focus: str
    target_volume_m: int = Field(ge=0)
    sessions: list[Session] = Field(default_factory=list)
    adaptation_rationale: str | None = None
    draft: bool = False
    # When a HELD draft was proposed (UTC). Drafts older than the tools' expiry are
    # treated as absent so a stale, forgotten draft can never be written by a later,
    # unrelated confirm. Additive/optional, no schema_version bump.
    drafted_at: datetime | None = None
    # Which tool proposed a HELD draft, so a confirm that names no draft_id only ever
    # picks up ITS OWN tool's draft (a replace_week_plan draft is never written by a
    # later merge_week_plan confirm on the same week). Additive/optional.
    drafted_by: str | None = None
    planning_warnings: list[str] = Field(default_factory=list)
    # Realism-guardrail verdict for this week's plan (Build A defect 1,
    # engine/week-generator-realism). Human-readable strings surfaced to the
    # coach when a bike-primary week's session mix looks unrealistic (too
    # many hard bike days, too many rideable days, back-to-back hard days,
    # or a weekly-volume jump past the +8%/week safety rail -- see
    # `plan.evaluate_week_realism`). The engine NEVER silently clamps on
    # these; it emits the plan as requested plus the warnings, and the coach
    # decides. Empty list for a realistic week and for every swim-primary
    # week. Additive/optional: every existing persisted WeekPlan (YAML file
    # or DB jsonb row) has no `planning_warnings` key and validates
    # unchanged as an empty list; no schema_version bump, same pattern as
    # `race_week_checklist` below.
    race_week_checklist: list[RaceWeekChecklistItem] = Field(default_factory=list)
    # Populated only for the final week of a taper block immediately
    # preceding the athlete's active, A-priority target event -- see
    # `plan.generate_week`'s `event` parameter and `_race_week_checklist`.
    # Additive/optional: every existing persisted WeekPlan (YAML file or DB
    # jsonb row) has no `race_week_checklist` key and validates unchanged as
    # an empty list; no schema_version bump, same pattern as every other
    # additive field in this file.

    @field_validator("iso_week")
    @classmethod
    def _validate_iso_week(cls, v: str) -> str:
        if not _ISO_WEEK_RE.match(v):
            raise ValueError(f"iso_week must look like '2026-W28', got {v!r}")
        return v


class MacroBlock(BaseModel):
    """One block within a MacroPlan.

    `"base"`/`"build"`/`"peak"`/`"taper"` are `plan.scaffold_macro`'s
    original base->build->peak->taper shape. `"hold"`/`"sharpen"` are the
    established-base, short-runway "sharpening" shape's own two new phases
    (`plan.scaffold_sharpening_macro`) -- Issurin's block-periodization
    "transmutation" block, plus an optional flat maintenance phase ahead of
    it when the runway allows more than the minimum -- see that function's
    own docstring for the full design and citation. That second shape
    reuses `"taper"` UNCHANGED (same block, same volume-decay math,
    `plan.generate_week`'s existing taper handling) rather than inventing a
    third taper variant.

    **Scope note, sharpening-macro build:** `scaffold_sharpening_macro` is a
    separate function, never called from any swim-path code -- as of this
    build, only `backend/app/tools.py`'s `draft_macro_plan` handler ever
    invokes it, and only when the target event's `primary_sport == "bike"`.
    `plan.generate_week`'s swim-primary path (`_no_coach_pool_purpose`,
    `_additional_swim_structure`, the taper-decay long-swim cap) is
    therefore never handed a `"hold"`/`"sharpen"`-named block in practice,
    and was NOT audited or extended to specifically understand those two
    names in this build -- deliberately out of scope, see
    `scaffold_sharpening_macro`'s own docstring.
    """

    name: Literal["base", "build", "peak", "taper", "hold", "sharpen"]
    start_date: date
    end_date: date
    weekly_volume_target_m: int = Field(ge=0)
    focus: str
    race_event_id: UUID | None = None
    # Which race (an Event.id) this specific block is building toward or
    # tapering into -- multi-race-season-macro build
    # (`plan.scaffold_season_macro`). `None` for every block produced by
    # `scaffold_macro`/`scaffold_sharpening_macro` (unchanged meaning: the
    # caller already knows the single target event via the parent
    # `MacroPlan.event_id`, so tagging every block there would be pure
    # redundancy, not new information) -- additive, no schema_version bump,
    # every existing persisted MacroBlock (YAML or DB JSONB, no
    # race_event_id key) validates unchanged. Only `scaffold_season_macro`
    # sets this, on every block it produces, since a season-spanning
    # `MacroPlan.blocks` list chains multiple races' worth of blocks
    # end-to-end and a reader can no longer assume "the whole plan is for
    # one event" the way a single-race macro's reader can -- see
    # `MacroPlan.event_ids`'s own docstring below.


class MacroPlan(BaseModel):
    """The macrocycle scaffold (base -> build -> peak -> taper) toward an event.

    `event_id` is always required and always resolves: for a single-race
    macro (`plan.scaffold_macro`/`plan.scaffold_sharpening_macro`, unchanged)
    it is that macro's one and only target event, exactly as before this
    field existed. For a season-spanning macro
    (`plan.scaffold_season_macro`, multi-race-season-macro build) it is set
    to the LAST (chronologically final) race in the season -- so every
    EXISTING single-event consumer that only ever reads `.event_id` (the
    duplicate-macro guard in `backend/app/tools.py`'s `draft_macro_plan`
    handler, the DB `macro_plans` table's own `event_id` column/index, the
    PWA) keeps working unchanged, seeing "the plan's event" as its final
    target -- a reasonable single answer, not an arbitrary one, since the
    final race is what every earlier block in a season-spanning plan is
    ultimately building toward.
    """

    schema_version: int = 1
    id: UUID
    athlete_id: UUID
    event_id: UUID
    blocks: list[MacroBlock] = Field(default_factory=list)
    event_ids: list[UUID] = Field(default_factory=list)
    # ALL races this macro plan was scaffolded across, chronological order --
    # multi-race-season-macro build. Empty (the default) for every macro
    # produced by `scaffold_macro`/`scaffold_sharpening_macro`, unchanged --
    # additive, no schema_version bump, every existing persisted MacroPlan
    # (YAML or DB JSONB, no `event_ids` key) validates unchanged as an empty
    # list, which is exactly what it always implicitly meant ("this macro is
    # about the one `event_id` above, full stop"). Only `scaffold_season_macro`
    # populates this, with `event_ids[-1] == event_id` always true for its
    # output. NOT every id in this list is guaranteed to have a dedicated
    # `MacroBlock` tagged with its id via `MacroBlock.race_event_id` --
    # `scaffold_season_macro` deliberately does not carve out a dedicated
    # block for every race (a B-priority race too close to periodize, or a
    # C-priority race at all, is folded into whichever surrounding block
    # already covers its date instead -- see that function's own docstring)
    # -- so `event_ids` is the complete "races this plan is aware of" list,
    # while `{b.race_event_id for b in blocks if b.race_event_id}` is the
    # (possibly smaller) "races that got their own dedicated block" subset.


class WorkoutSet(BaseModel):
    """One set within a completed Workout. Only distance_m is required."""

    reps: int | None = None
    distance_m: int = Field(ge=0)
    interval: str | None = None
    target_pace: str | None = None
    stroke: str | None = None
    description: str | None = None


class WorkoutLap(BaseModel):
    """One device lap/interval, from a FIT `lap` frame.

    Distinct from `WorkoutSet` (which comes from coach-text parsing or a
    generic lap-as-set fallback): a `WorkoutLap` is numeric device telemetry
    (duration/distance/HR/pace), not a free-text description.
    """

    index: int
    start_offset_s: float | None = None
    duration_s: float
    distance_m: float | None = None
    avg_hr: int | None = None
    max_hr: int | None = None
    avg_pace_s_per_100m: float | None = None
    stroke: str | None = None
    num_lengths: int | None = None
    # Bike lap-level average power (Build I: Normalized Power + power-based
    # load tier), read straight off the FIT lap frame's own `avg_power`
    # field -- see `parse_files._build_laps`. Gated to cycling sports the
    # same way `_build_series`'s `extended=`/`_is_cycling_sport` pattern
    # already gates the record-level power/cadence/altitude channels, so
    # every swim/kayak/strength lap keeps `avg_power_w=None`, byte-identical
    # to before this field existed. Additive/optional, no schema_version
    # bump, same convention as every other additive field in this file.
    avg_power_w: float | None = None


class WorkoutLength(BaseModel):
    """One active pool length, from a FIT `length` frame
    (`length_type == "active"` only -- idle lengths become a `WorkoutPause`
    instead, see `parse_files.parse_fit`)."""

    index: int
    lap_index: int | None = None
    duration_s: float
    strokes: int | None = None
    stroke: str | None = None
    swolf: float | None = None


class WorkoutPause(BaseModel):
    """A stopped/idle span within a workout, from one of four sources:
    a FIT `event` timer stop->start pair (`"timer"`), a `record`-frame
    timestamp gap exceeding `analytics.GAP_THRESHOLD_S` (`"gap"`), an idle
    pool length (`"idle_length"`), or a sustained sub-`analytics.
    STATIONARY_SPEED_MPS` span in the speed series (`"stationary"` --
    catches real stops a device with auto-pause off never records as a
    timer event or gap; see `parse_files.parse_fit` and
    `library/11-workout-analytics.md`)."""

    start_offset_s: float
    duration_s: float
    source: Literal["timer", "gap", "idle_length", "stationary"]


class IntervalSubStructure(BaseModel):
    """The internal shape of one detected effort that isn't a single flat
    block -- either a VO2 "rep set" (a run of short on/off reps collapsed
    into one effort by `interval_analysis`'s set-clustering pass) or an
    "over/under" (a continuous block whose power oscillates in a roughly
    regular high/low pattern). `pattern` discriminates; the `high_*`/`low_*`
    fields carry the ON/OVER vs float/UNDER halves either way. See
    `library/26-activity-stream-interval-analysis.md` ("Micro-interval
    detection and set clustering", "Over/under sub-resolution") and
    `library/24-cycling-periodization-intervals.md` ("Short-short (VO2)",
    "Over/unders")."""

    schema_version: int = 1
    pattern: Literal["rep_set", "over_under"]
    n_reps: int  # rep_set: ON-rep count; over_under: number of over/under cycles
    high_avg_w: float | None = None  # mean power of the ON / OVER segments
    low_avg_w: float | None = None  # mean power of the float-recovery / UNDER segments
    high_s: float | None = None  # median ON / OVER segment duration
    low_s: float | None = None  # median float / UNDER segment duration
    time_in_high_pct: float | None = None  # % of the effort's span in ON/OVER segments
    time_in_low_pct: float | None = None  # % of the effort's span in float/UNDER segments
    note: str


class IntervalEffort(BaseModel):
    """One detected sustained effort within a ride, assessed against a
    target when one is known -- produced by
    `swim_coach.interval_analysis.assess_effort`. All quality fields are
    optional: a ride with a power meter fills them in, an HR-only ride
    leaves the power/target ones `None`. See `library/11-workout-
    analytics.md` ("Deterministic interval detection", "Interval quality
    vs. target", "Terrain-confound detection")."""

    n: int  # 1-based effort index within the ride, in time order
    start_s: float
    duration_s: float
    avg_w: float | None = None
    avg_hr: int | None = None
    target_w: float | None = None
    pct_of_target: float | None = None  # avg_w / target_w * 100
    avg_vs_target_w: float | None = None  # avg_w - target_w (signed)
    time_in_band_pct: float | None = None  # % of samples within +/-5% of target
    fade_pct: float | None = None  # (first-third mean - last-third mean) / first-third mean * 100
    hr_drift_bpm: float | None = None  # last-third mean HR - first-third mean HR
    grade_delta_pct_pts: float | None = None  # first-third mean grade - last-third, in percentage points
    terrain_flag: str | None = None
    verdict: str
    sub_structure: IntervalSubStructure | None = None
    # Set only when this effort isn't a single flat block: a clustered VO2
    # rep set (30/30-style micro-intervals) or an over/under. `None` for an
    # ordinary sustained effort. Additive/optional -- every existing
    # persisted IntervalEffort validates unchanged as `sub_structure=None`;
    # no schema_version bump.
    altitude_m: float | None = None  # this effort's own mean altitude sample
    altitude_gain_m: float | None = None
    # altitude_m - WorkoutIntervals.baseline_altitude_m. That baseline is
    # `Athlete.home_elevation_m` when the athlete has set one, else the
    # ride's own session-relative baseline -- see `baseline_altitude_source`
    # on `WorkoutIntervals` for which applied to this ride.
    altitude_context: str | None = None
    # A computed, sourced altitude-power-capability note -- set only when
    # `altitude_gain_m >= interval_analysis.ALTITUDE_FLAG_THRESHOLD_M`
    # (library/30-altitude-power-adjustment.md); `None` for every ride
    # without a resolvable baseline, and for every effort whose elevation
    # above it doesn't clear that threshold. Same "flag, never silently
    # override" posture as `terrain_flag` -- it never adjusts
    # `pct_of_target`/`avg_vs_target_w`/`verdict`, it's an additional signal
    # for the coach to weigh alongside them. Additive/optional -- every
    # existing persisted IntervalEffort (predating this field, or from a
    # ride with no altitude channel) validates unchanged with every
    # altitude_* field `None`; no schema_version bump.
    altitude_decrement_pct: float | None = None
    # The estimated %-power-capability reduction at this effort's elevation
    # (`ALTITUDE_POWER_DECREMENT_PCT_PER_1000M * altitude_gain_m / 1000`),
    # set alongside `altitude_context` whenever that note fires -- the same
    # number embedded in the note's text, exposed separately so a caller
    # doesn't have to parse it back out of a human-readable string.
    altitude_adjusted_target_w: float | None = None
    cleared_altitude_adjusted_target: bool | None = None
    # Answers Andrew's actual question: "would this rep have hit target
    # once corrected for elevation, even though it read below the raw
    # target?" Set only when BOTH `target_w` and `altitude_decrement_pct`
    # are available for this effort: `altitude_adjusted_target_w = target_w
    # * (1 - altitude_decrement_pct / 100)`, and
    # `cleared_altitude_adjusted_target = avg_w >= altitude_adjusted_
    # target_w`. Never changes `pct_of_target`/`avg_vs_target_w`/`verdict`
    # themselves -- those stay computed against the raw, un-adjusted
    # `target_w`, exactly as before this field existed; this is an
    # additional, clearly-labeled signal alongside them, same "flag, never
    # silently override" posture as `terrain_flag`/`altitude_context`.
    # `None` whenever no target was supplied or no altitude flag fired for
    # this effort. Additive/optional, no schema_version bump.


class WorkoutIntervals(BaseModel):
    """The compact interval block on `WorkoutAnalytics` -- deterministic
    output of `swim_coach.interval_analysis.analyze`, computed inside
    `compute_analytics` for `sport == "bike"` rides that carry a power (or,
    failing that, HR) series. `None` on `WorkoutAnalytics` for every other
    sport. `decoupling_tightened_pct` SUPPLEMENTS `WorkoutAnalytics.
    cardiac_drift_pct` (it does not replace it) -- it's the same first-half-
    vs-second-half efficiency-factor calc restricted to genuinely working
    samples, so it's meaningful on a stop-start dirt-road ride where the
    unfiltered number is not; `decoupling_note` says which."""

    schema_version: int = 1
    efforts_detected: int
    detection_basis: Literal["power", "hr"]
    matched_to_prescription: bool = False
    prescribed_count: int | None = None
    efforts: list[IntervalEffort] = Field(default_factory=list)
    decoupling_tightened_pct: float | None = None
    decoupling_note: str | None = None
    baseline_altitude_m: float | None = None
    # The altitude every effort's `altitude_gain_m` is measured against.
    # `Athlete.home_elevation_m` when the athlete has set one (re-anchored
    # 2026-09-14: this is what actually answers "was this ride performed
    # above my home elevation" -- a ride that starts already high relative
    # to home is now flaggable from its very first sample, not just for
    # climbing further above wherever it happened to start); otherwise this
    # ride's own session-relative heuristic -- its lowest `altitude_m`
    # sample (`interval_analysis._ride_baseline_altitude_m`). `None` for a
    # ride with no altitude channel. See `baseline_altitude_source` for
    # which applied, and `library/30-altitude-power-adjustment.md` for the
    # full reasoning (including why an auto-inferred rolling baseline was
    # considered and explicitly rejected). Additive/optional -- every
    # existing persisted WorkoutIntervals validates unchanged as `None`; no
    # schema_version bump.
    baseline_altitude_source: Literal["home_elevation", "ride_relative"] | None = None
    # Which of the two baselines above `baseline_altitude_m` actually is --
    # `None` only alongside `baseline_altitude_m=None` (no altitude channel,
    # no `home_elevation_m`, and too few samples for the ride-relative
    # heuristic). Exists so a coach reading a flagged (or notably NOT
    # flagged) effort can see at a glance whether the number reflects the
    # athlete's real home elevation or just wherever this particular ride
    # happened to start. Additive/optional, no schema_version bump.


class WorkoutAnalytics(BaseModel):
    """Derived workout analytics computed at ingest time by
    `swim_coach.analytics.compute_analytics` -- see that module for the
    pure functions and their library/ citations."""

    cardiac_drift_pct: float | None = None
    split_label: Literal["negative", "even", "positive"] | None = None
    first_half_pace_s_per_100m: float | None = None
    second_half_pace_s_per_100m: float | None = None
    elapsed_min: float | None = None
    moving_min: float | None = None
    pause_total_min: float | None = None
    pause_count: int | None = None
    swolf_first_quarter: float | None = None
    swolf_last_quarter: float | None = None
    swolf_degradation_pct: float | None = None
    # Interval-analyzer block (deterministic, no LLM) -- populated only for
    # `sport == "bike"` rides with a usable power/HR series; `None` for
    # every swim/kayak/strength workout. See `WorkoutIntervals` and
    # `swim_coach.interval_analysis`.
    intervals: WorkoutIntervals | None = None
    # Ride-level average power and Normalized Power (Build I), populated by
    # `swim_coach.analytics.compute_analytics` from the workout's own
    # `power_w` series channel when present -- which `parse_files.
    # _build_series` only ever emits for a cycling `.fit` (see its
    # `extended=` gate), so these two fields are `None` for every swim/
    # kayak/strength workout, exactly like `intervals` above. NP is the
    # standard Coggan/Allen 4-step algorithm (30s rolling average of power,
    # each value to the 4th power, mean, 4th root) -- see `analytics.
    # normalized_power_w`'s own citation and `library/23-cycling-
    # training.md`'s "Training Stress Score, Normalized Power, Intensity
    # Factor" section. Additive/optional, no schema_version bump, same
    # convention as every other additive field in this file.
    avg_power_w: float | None = None
    normalized_power_w: float | None = None


WorkoutChatSenderRole = Literal["athlete", "ai_coach", "coach"]


class WorkoutChatMessage(BaseModel):
    """One message in a workout's persisted three-party chat thread (IDEA 016) --
    replaces the old ephemeral, AI-only workout-chat box (`renderWorkoutChatSection`
    used to say plainly "this thread isn't saved -- it clears when you leave this
    workout"). Andrew, 2026-09-23: the athlete chats, the AI responds naturally
    the same as before, and a human coach can now also read the whole thing and
    comment on just one part without that silencing the AI for the rest of it.

    Embedded on `Workout` (`chat_messages` below), not its own table: per-workout
    volume is bounded (a handful to a few dozen messages about ONE workout) --
    the same "small, bounded, embed it" shape `AthleteNote`/`RaceDebrief` already
    use on `Athlete`, not the unbounded-ongoing-log shape a general coach<->athlete
    thread would need (that's a separate model). Never deleted or edited.
    """

    id: UUID
    sender_role: WorkoutChatSenderRole
    # Set only when sender_role == "coach" -- which coach, since CoachGrant is
    # genuinely many-to-many (an athlete can have more than one active coach).
    coach_athlete_id: UUID | None = None
    body: str
    created_at: datetime


class Workout(BaseModel):
    """A completed workout, logged manually or ingested from a file/coach text."""

    schema_version: int = 1
    id: UUID
    athlete_id: UUID
    date: date
    sport: Sport
    source: Literal["manual", "fit", "tcx", "csv", "coach_text"]
    distance_m: int = Field(ge=0)
    duration_min: float = Field(gt=0)
    avg_pace_s_per_100m: float | None = None
    # 0-10 Foster CR-10 modified-Borg scale (0 = "Rest / Nothing at all"),
    # see library/19-srpe-protocol.md -- not 1-10, so 0 is a real, valid
    # response, not an unreachable floor.
    rpe: int | None = Field(default=None, ge=0, le=10)
    sets: list[WorkoutSet] = Field(default_factory=list)
    planned_session_id: UUID | None = None
    raw_ref: str | None = None
    notes: str | None = None
    # Additive fields for the .fit workout-analytics feature (Slice 1).
    # All optional/defaulted so every existing Workout YAML (with none of
    # these keys) keeps validating unchanged -- no schema_version bump.
    avg_hr: int | None = None
    max_hr: int | None = None
    laps: list[WorkoutLap] = Field(default_factory=list)
    lengths: list[WorkoutLength] = Field(default_factory=list)
    pauses: list[WorkoutPause] = Field(default_factory=list)
    analytics: WorkoutAnalytics | None = None
    # Repo-relative path to the columnar time-series sidecar JSON (see
    # store.FileStore.save_series), NOT the Workout YAML itself -- keeps
    # committed YAML human-readable per CLAUDE.md.
    series_ref: str | None = None
    # Dedupe key for auto-ingested workouts, e.g. "intervals:i132013445"
    # (backend/app/sync.py, the intervals.icu -> Garmin auto-sync job).
    # Additive/optional so every existing Workout YAML (with no external_id
    # key) keeps validating unchanged -- no schema_version bump. None for
    # manually logged or CLI-ingested workouts; the sync job is the only
    # writer of a non-None value today.
    external_id: str | None = None
    # Free-text FIT sport/sub_sport detail (e.g. "cycling/mountain",
    # "paddling/kayaking", "walking") for a non-swim `.fit` ingest -- see
    # `parse_files._fit_sport`/`parse_fit`. Additive/optional so every
    # existing Workout YAML (with no sport_detail key) keeps validating
    # unchanged -- no schema_version bump. Always None for swim_pool/
    # swim_ow (the Sport enum already distinguishes pool/open-water, so a
    # detail string there would be redundant).
    sport_detail: str | None = None
    # When this workout record was actually saved (DbStore: the real
    # `workouts.created_at` DB column, surfaced read-only -- see
    # store_db.row_to_workout; FileStore: always None, no equivalent
    # durable "first saved" timestamp exists on disk). Never written back
    # into the persisted JSONB blob -- read-derived only. Additive/
    # optional so every existing Workout YAML/row keeps validating
    # unchanged -- no schema_version bump.
    logged_at: datetime | None = None
    # Real workout end-time estimate: populated from parse_fit's FIT
    # session.start_time (+ duration_min) when a real .fit start_time was
    # captured -- see parse_files.parse_fit. None for tcx/csv ingests (no
    # equivalent extracted field) and for any .fit without a session
    # start_time. Additive/optional so every existing Workout YAML/row
    # keeps validating unchanged -- no schema_version bump.
    started_at: datetime | None = None
    # Workout chat thread (IDEA 016, see WorkoutChatMessage's own docstring).
    # Additive/optional so every existing Workout YAML/row (with neither key)
    # keeps validating unchanged -- no schema_version bump.
    chat_messages: list[WorkoutChatMessage] = Field(default_factory=list)
    # Deterministic mute switch: a plain boolean, not something inferred from
    # scanning message history, so it's a reliable control either party (or
    # the AI itself, told to recognize an explicit "stop responding here")
    # can flip -- see `set_workout_chat_muted` (backend/app/tools.py) and
    # PATCH /api/workouts/{id}'s `chat_ai_muted` field.
    chat_ai_muted: bool = False


class WorkoutQuality(BaseModel):
    """Per-workout planned-vs-actual interpretation, computed by
    `swim_coach.quality.workout_quality` -- NOT persisted (a
    response/computed shape only, hence no `schema_version`).

    Distinct from `load.compliance`'s aggregate weekly-volume-percentage
    number, which remains this codebase's sole authoritative "compliance":
    this is one workout matched against (at most) one planned `Session`, not
    a sum across a week. Named `WorkoutQuality` (not `WorkoutCompliance`,
    its original Phase-1 name) specifically to avoid colliding with that
    aggregate -- see `IDEAS.md`'s resolved IDEA 006 and `quality.py`'s
    module docstring for the full distinction and the Phase-1
    `intensity_match` gap.
    """

    matched: bool
    distance_delta_pct: float | None = None
    duration_delta_pct: float | None = None
    load_delta_pct: float | None = None
    # Percent difference between this workout's actual training load
    # (`swim_coach.load.session_load`) and its matched session's projected
    # load (`swim_coach.load.session_target_load_au`) -- `None` when
    # unmatched, same convention as `distance_delta_pct`/
    # `duration_delta_pct` above. Part of the training-load validation
    # mechanism (see `quality.workout_quality`'s docstring and
    # `cli.py`'s `validate-load-model` diagnostic) -- informational only,
    # never wired into `adapt.py`.
    intensity_match: Literal["match", "mismatch", "unknown"] = "unknown"
    quality_summary: str | None = None


FeedbackType = Literal[
    "research_question", "feature_request", "comment", "bug", "question", "coach_review"
]
# "question" -- athlete-initiated, expects an answer (workout-linked via
# `workout_id`, or direct-to-coach). "coach_review" -- AI-flagged
# `needs_human_review=True` with no research gap behind it (pain/safety
# escalations, an explicit "talk to my coach" request, or any other
# high-stakes judgment call the AI declines to make alone).
FeedbackSource = Literal["coach", "athlete"]


class Feedback(BaseModel):
    """A durable feedback-log entry.

    Replaces the ephemeral `research/open-questions.jsonl` file (IDEA 005,
    the coach's `log_open_question` tool) -- Cloud Run's disk is wiped on
    scale-to-zero, so a plain file was silently losing every logged research
    gap. Generalized here to also carry athlete-submitted feature requests,
    comments, and bug reports from the app's Feedback tab, and (coach-mode
    Chunk A) athlete questions and human-coach review/reply state.

    `athlete_id` is nullable: a research question logged by the coach about
    the athlete's own session is still tied to that athlete, but feedback
    isn't required to be athlete-scoped in general. `context` is a free-form
    bag for type-specific extras (e.g. `{"topic": "taper", "expert_mode":
    true}` for a research_question) -- see backend/app/tools.py and
    backend/app/routes/feedback.py for what each type puts there.

    `type` and `needs_human_review` are orthogonal: a `"research_question"`
    row can ALSO carry `needs_human_review=True` when it's both
    under-evidenced AND urgent -- one row, not a fork into a second entry.
    """

    schema_version: int = 1
    id: UUID
    athlete_id: UUID | None = None
    type: FeedbackType
    source: FeedbackSource
    body: str
    context: dict = Field(default_factory=dict)
    status: str = "open"
    created_at: datetime
    # Human-coach-review fields (coach-mode Chunk A). All optional/defaulted
    # so every existing Feedback YAML/row (with none of these keys) keeps
    # validating unchanged -- additive, no schema_version bump needed, same
    # pattern as `Workout.external_id` above.
    workout_id: UUID | None = None  # links a comment/question to a Workout
    # `session_date`/`session_sport` link a question to a PLANNED Session
    # instead of a completed Workout -- mutually exclusive with `workout_id`
    # (enforced by the route, not here; see backend/app/routes/feedback.py).
    # Linking by (date, sport) rather than a raw Session.id is deliberate:
    # `Session.id` does NOT survive `replace_week_plan` (every session gets
    # a fresh uuid4() on a full week regenerate -- see plan.py/tools.py), so
    # a question linked by raw id would silently orphan the moment its week
    # is regenerated. (date, sport) is the same stability fallback
    # `quality.match_workout_to_session` already trusts for matching a
    # completed workout to its planned session. Both optional/defaulted so
    # every existing persisted Feedback row (with neither key) keeps
    # validating unchanged -- additive, no schema_version bump, same
    # pattern as `workout_id` above.
    session_date: date | None = None
    session_sport: Sport | None = None
    needs_human_review: bool = False  # independently settable by AI or athlete
    ai_provisional_answer: str | None = None
    coach_athlete_id: UUID | None = None  # which coach (an athlete_id) replied
    coach_reply: str | None = None
    coach_reply_at: datetime | None = None


class HealthStatus(BaseModel):
    """A durable, append-only LOG of an athlete's injury/illness/medical
    status over time -- built after a real incident exposed that this
    system had NO durable record of health status anywhere: `Wellness.
    soreness` is just a daily 1-5 self-rating with no memory beyond "today,"
    `backend/app/routes/chat.py` persists nothing server-side (chat history
    is client-supplied per request, so a raw injury description that never
    triggers a tool call vanishes the moment the browser tab closes), and
    there was no model of this shape at all. CLAUDE.md's own standing safety
    rail -- "any pain report -> stop-and-assess" -- was enforced ONLY as
    prompt-level guidance with zero durable backing before this model
    existed.

    This is a LOG, not a single mutable field, deliberately mirroring
    `Feedback` above: health status evolves over days/weeks, and the
    HISTORY matters as much as the current state -- a physio's guidance
    last week and this week's may differ, and a later entry must never
    silently overwrite what was said before. Every entry this athlete has
    ever had recorded stays on file permanently (this codebase's own safety
    rail: never delete logs; see CLAUDE.md).

    `restriction` is a coarse, closed 3-value enum -- NOT a replacement for
    `description`'s free text, which still carries the full human detail
    (what hurts, what a practitioner said, context) -- because an AI reading
    this field later (the future ramp-back-up-then-taper planning engine
    this build is the foundation for, but does NOT itself implement) needs
    something it can safely branch on without re-interpreting prose every
    time. "none" / "light_only" / "no_training" is deliberately coarse: a
    machine can trust an enum value where it can't safely trust its own
    parse of a paragraph of free text describing a shoulder.

    `reported_by` (who told the system: "athlete" in her own chat, or
    "coach" relaying something) and `source` (the underlying claim's
    provenance: "self_reported" -- the athlete's own account of how she
    feels -- vs "practitioner" -- a physio/doctor's actual clinical
    guidance, typically relayed by the coach) are independent axes, both
    worth keeping: a coach can relay a self-reported feeling ("she told me
    her shoulder's been off") just as an athlete could in principle relay
    practitioner guidance herself ("my physio said light-only this week").
    Neither is a lesser kind of claim than the other, but they're not the
    SAME kind of claim either, and a future reader (human or AI) should be
    able to tell which is which.

    `resolved`/`resolved_at` let one status be explicitly closed out (e.g.
    "cleared to resume full training as of DATE") WITHOUT deleting the
    history that came before it -- a new entry, not an edit to the old one,
    is how a status changes; nothing here is ever mutated in place except
    flipping `resolved` on the entry being closed. The MOST RECENT entry
    (by `reported_at`) with `resolved=False` for a given athlete is that
    athlete's current active status. If NO such entry exists -- either
    nothing has ever been logged, or every entry on file has since been
    resolved -- there is NO active restriction on file. That is explicitly
    NOT the same thing as "she's definitely fine": it means nothing has
    been recorded, one way or the other. An absence of data must never be
    read as an all-clear, by a human OR by any future automated logic that
    reads this log -- say so plainly wherever this fact is surfaced.

    --- Second-iteration fields (`body_region`/`onset`/`severity`/
    `related_status_id`) -- industry-modeling evolution, before this ever
    shipped or migrated ---

    The first version above ("Is there industry modeling we can validate the
    health status class?") leaned entirely on free-text `description` for
    anything beyond a coarse restriction level -- workable as a start, but
    exactly the kind of thing that "will quickly run short" once real
    automated logic (a future ramp-then-taper planning engine, not part of
    this build) needs to reason about WHICH activities a restriction
    affects, not just how severe it sounds. These four fields close that
    gap by adapting three real, established sports-medicine consensus
    frameworks -- `[ADAPTED: general-endurance]`, Confidence: medium (the
    underlying frameworks are real, verified, high-quality consensus
    documents; the specific choice of which fields to adopt at what
    granularity for a single-athlete coaching app, rather than a research
    surveillance tool, is Coach judgment, not itself directly validated).
    Test: if this athlete population's injury patterns diverge meaningfully
    from what this coarse taxonomy anticipates, or a genuine need for
    finer-grained OSICS-style coding emerges, revisit.

      - Fuller CW, Ekstrand J, Junge A, Andersen TE, Bahr R, Dvorak J,
        Hagglund M, McCrory P, Meeuwisse WH (2006), "Consensus statement on
        injury definitions and data collection procedures in studies of
        football (soccer) injuries," Scandinavian Journal of Medicine &
        Science in Sports / British Journal of Sports Medicine -- the
        field-defining consensus paper (FIFA/F-MARC). Classifies every
        injury by location, type, diagnosis, and cause; defines recurrence
        with precise timing (early: within 2 months of return to full
        participation; late: 2-12 months after; delayed: >12 months after).
      - Bahr R, Clarsen B, Derman W, et al. -- International Olympic
        Committee Injury and Illness Epidemiology Consensus Group (2020),
        "International Olympic Committee consensus statement: methods for
        recording and reporting of epidemiological data on injury and
        illness in sport 2020 (including STROBE-SIIS)," British Journal of
        Sports Medicine / Orthopaedic Journal of Sports Medicine (PMID
        32118084 / 32071062) -- the current cross-sport standard (covers
        illness, not just injury); grades severity by TIME-LOSS (days of
        full/modified training availability lost), not by a point-in-time
        restriction level.
      - Time-loss severity bands, used across multiple sports' consensus
        statements (Fuller 2006 and successors): slight (<=1 day), minimal
        (2-3 days), mild (4-7 days), moderate (8-28 days), serious (>28
        days-6 months), long-term (>6 months) -- keyed to actual/expected
        days of full or modified training lost.
      - OSICS/OSIICS (Orchard Sports Injury and Illness Classification
        System), the ~800-code body-region+tissue+pathology standard most
        sports injury surveillance databases use, is explicitly NOT being
        adopted in full here -- that system is built for population-level
        research comparing injury rates across many athletes/teams, which
        is overkill for a single-athlete coaching app. Only its
        STRUCTURING PRINCIPLE (classify by body region) is adapted here, at
        a deliberately coarse level.

    `body_region` is a coarse 9-value enum, NOT full OSICS coding -- the
    goal is "can automated logic reason about which activities this
    restriction affects" (a shoulder issue rules out pulling/catch-up drills
    specifically, not swimming generally), never population-level injury-
    rate epidemiology. Optional/`None` because a first-contact report right
    after an incident often genuinely doesn't yet know a precise region --
    forcing a guess here would fabricate false precision on safety-relevant
    data, exactly the failure mode this codebase's own "a real value beats a
    missing one, but never invent false precision" philosophy (see e.g.
    `engine/swim_coach/load.py`'s `HR_REST_GENERIC_FALLBACK_BPM` comment)
    already commits to elsewhere.

    `severity` is a SEPARATE axis from `restriction`, not a replacement for
    it: `restriction` answers "how much can she do RIGHT NOW" (a point-in-
    time operational fact); `severity` answers "how big a deal is this
    expected to be OVERALL" (a time-loss-based clinical/prognostic
    judgment, per Bahr et al. 2020 / Fuller 2006's severity grading). A
    broken toe might be `restriction="no_training"` today but only
    `severity="mild"` (short expected recovery); a stress fracture could be
    BOTH `no_training` AND `severity="serious"` or `"long_term"`.
    Conflating these into one field is exactly the gap this evolution
    closes. `severity` is optional and MUST stay that way even for a
    `resolved=True` entry being closed out -- the athlete/coach might
    genuinely never learn (or bother recording) an exact time-loss
    classification, and absence of a severity value is NOT itself
    meaningful information, same "absence isn't evidence" doctrine this
    whole model already commits to for the record's existence overall.

    `onset` (acute vs. gradual/overuse) follows Fuller/IOC's own standard
    split -- informs whether this is a discrete event or a cumulative
    pattern. Optional for the same "don't force a guess" reason as
    `body_region`/`severity`.

    `related_status_id` links a new entry to an EARLIER `HealthStatus.id`
    this is a recurrence/continuation of -- not enforced via a DB foreign
    key at the JSONB layer, just a same-athlete id reference the reader is
    expected to resolve. This is what makes Fuller (2006)'s early/late/
    delayed recurrence classification (2mo / 2-12mo / >12mo since return to
    full participation) actually COMPUTABLE later, from the gap between the
    linked entries' dates, instead of only inferable by a human re-reading
    free text across the whole history. This build does NOT implement
    automatic early/late/delayed recurrence computation/labeling -- that's
    a real, worthwhile follow-up once enough linked entries exist to make it
    meaningful; this build only adds the linking field itself. No
    validation that `related_status_id` actually references a real prior
    entry for THIS athlete belongs here (a cross-record consistency check
    doesn't belong at the single-model-validation layer) -- if implemented
    anywhere, it belongs in the tool handler / route layer where the full
    history is actually available, and even there a dangling reference
    should be at most a soft warning, never a hard validation failure that
    could block saving a real health report over a linking mistake.

    Across all four: `description` remains the necessary free-text escape
    valve for everything that doesn't fit these coarse structured fields --
    these additions give AUTOMATED logic (the coach roster's display today;
    a future ramp-then-taper planning engine, not part of this build)
    something real to branch on, not a replacement for human judgment
    reading the actual description.
    """

    schema_version: int = 1
    id: UUID
    athlete_id: UUID
    reported_at: datetime
    reported_by: Literal["athlete", "coach"]
    source: Literal["self_reported", "practitioner"]
    description: str
    restriction: Literal["none", "light_only", "no_training"]
    expected_review_date: date | None = None
    resolved: bool = False
    resolved_at: datetime | None = None
    body_region: Literal[
        "shoulder", "knee", "back", "hip", "ankle_foot", "elbow_wrist",
        "illness_systemic", "head_neck", "other",
    ] | None = None
    onset: Literal["acute", "gradual"] | None = None
    severity: Literal["slight", "minimal", "mild", "moderate", "serious", "long_term"] | None = None
    related_status_id: UUID | None = None


class ThresholdRecord(BaseModel):
    """A durable, append-only LOG of one dated per-sport threshold reading
    -- same shape as `HealthStatus` above, and for the same reason: a
    threshold (FTP, LTHR, CSS) is not a single mutable fact, it decays in
    accuracy over time, and a later reading must never silently erase an
    earlier one's record. Built to close a real gap: PR #167 added three
    ad-hoc, undated, unsourced threshold fields directly on `Athlete`
    (`css_pace_s_per_100m`, `lthr_bpm`, `ftp_watts`) with no way for the
    coach to ever write them at all -- `record_health_status`/`create_event`
    existed as real coach tools, but nothing let the coach persist an
    athlete's own reported FTP. Rather than bolt on a narrow "set FTP" tool,
    this generalizes the requirement, verbatim from Andrew (the athlete/
    project owner) this session: "We know for HR based training, will use
    LTHR, for run, pace. But, there are per-sport values. This value needs
    to be stored, dated (it will decompose over time). Coach can use
    judgement for trustworthiness of the value (I was 350w 10 years ago is
    invalid vs, ramp test last week is accurate)."

    The ENGINE's job is only to store/surface this history -- see
    `backend/app/context.py`'s `_recent_thresholds`/render function -- it
    NEVER picks a "current" value automatically; the COACH exercises
    judgment about which reading is currently trustworthy (a ramp test last
    week outweighs a number from ten years ago), the same "never let the
    engine guess at subjective trust" boundary `HealthStatus` already draws
    for injury-restriction judgment (see that model's own docstring). The
    engine-resolved value an athlete's zones/load math actually reads stays
    exactly where it already lives -- `Athlete.ftp_watts`/`lthr_bpm`/
    `css_pace_s_per_100m` -- set via `update_athlete_profile`
    (`backend/app/tools.py`) only after a human or the coach model judges a
    `ThresholdRecord` reading trustworthy enough to adopt; this model itself
    resolves nothing.

    Every entry ever recorded stays on file permanently (this codebase's
    own safety rail: never delete logs; see CLAUDE.md) -- there is no
    resolved/superseded flag on this model at all (unlike `HealthStatus`'s
    `resolved`), because a threshold reading is never "wrong" the way an
    open injury status can be closed out -- it just ages. Recency
    (`measured_at`) and provenance (`source`) are read together, not
    collapsed into one score.

    `metric` is a flat string list, trivially extensible (e.g. a future
    `run_pace_s_per_km` once running support exists -- IDEA 008's later
    build, not this one). Deliberately NOT derived from `sport` alone -- an
    athlete could plausibly have both an HR- and pace-based reading for the
    same sport (e.g. LTHR from a chest strap alongside a CSS-equivalent
    pace test for the same swim sport), so `sport` and `metric` are
    independent axes, both required.

    `source` is the trustworthiness signal Andrew's own example names
    directly: "I was 350w 10 years ago" -> `self_reported_historical`;
    "ramp test last week" -> `ramp_test`. Coach-facing, not engine-consumed
    -- the coach reads this alongside `measured_at` to judge recency and
    provenance together, same two-axis judgment `HealthStatus`'s
    `reported_by`/`source` pair already models for a different question.
    `field_test` covers a real standalone test that ISN'T the ramp-test
    protocol (e.g. a swim CSS time-trial pair, a 20-minute FTP test);
    `app_estimate` covers a platform's own algorithmic estimate (e.g.
    TrainerRoad's AI FTP detection) -- real signal, but modelled rather than
    directly tested, which is exactly the kind of distinction Andrew's own
    "modelled not tested" framing (his real profile.md) already draws and
    this field makes structurally queryable instead of only prose.

    `notes` is free text, e.g. "TrainerRoad AI FTP detection, modelled not
    tested" (matching Andrew's own real profile.md phrasing) -- same role
    `HealthStatus.description` plays: the engine can't safely parse this,
    the coach can.
    """

    schema_version: int = 1
    id: UUID
    athlete_id: UUID
    sport: Sport
    metric: Literal["ftp_watts", "lthr_bpm", "css_pace_s_per_100m", "carb_tolerance_g_per_hr"]
    # "carb_tolerance_g_per_hr" (engine/fueling-calculator build): a dated
    # reading of this athlete's demonstrated in-session carbohydrate
    # tolerance (grams/hour) -- exactly the "trivially extensible" future
    # metric this docstring's own comment anticipated. See
    # `Athlete.carb_tolerance_g_per_hr`'s comment for how a trusted reading
    # here gets adopted, and `swim_coach.fueling`'s module docstring for how
    # it's consumed.
    value: float
    measured_at: date
    source: Literal[
        "field_test", "ramp_test", "race_file", "app_estimate", "self_reported_historical"
    ]
    notes: str | None = None


CoachGrantStatus = Literal["active", "revoked"]
ChatVisibility = Literal["full", "shared_only"]


class CoachGrant(BaseModel):
    """One athlete's grant of coach access to another athlete (coaches in
    this system are themselves athlete accounts -- e.g. Tim, a consulting
    physiologist with no training data of his own, still has an
    `athletes/tim/` profile purely to hold a session identity; a
    `CoachGrant` just references the athletes table twice rather than
    needing a separate Coach identity model).

    `chat_visibility` controls whether the granted coach can see the
    athlete's full AI-chat history or only messages the athlete explicitly
    shares -- defined here now but NOT YET ENFORCED anywhere (chat isn't
    durably persisted at all yet); defaults to the more private
    `"shared_only"` so an athlete who never touches the setting doesn't
    over-share by default once enforcement lands.
    """

    schema_version: int = 1
    id: UUID
    coach_athlete_id: UUID  # the coach's own athlete row
    athlete_id: UUID        # the athlete being coached
    status: CoachGrantStatus = "active"
    chat_visibility: ChatVisibility = "shared_only"
    granted_at: datetime
    revoked_at: datetime | None = None


class AllowedEmail(BaseModel):
    """One entry in the server-side beta allowlist (Slice 1 "verified
    identity" -- see backend/app/routes/auth.py).

    A signed-in Google email that isn't in this list gets `403 {"error":
    "request access"}` from `POST /api/auth/google` and never gets a session
    or an athlete created -- adding a beta user is purely a data change (this
    row), never a code deploy (see `swim_coach.cli`'s `invite`/`list-invites`/
    `revoke-invite` commands).

    `email` is always the normalized (stripped, lowercased) form -- callers
    never see or store the original casing. `athlete_slug` (not `athlete_id`)
    is the identifier here, matching every other StoreInterface method's
    convention (`slug: str` in/out); DbStore's `allowed_emails` table stores
    the FK column (`athlete_id`) underneath and resolves slug<->id at the SQL
    layer via a join, same as `list_feedback`'s `athlete` filter does.

    `athlete_slug is None` (Slice 1 self-service onboarding) means this email
    was invited BEFORE an athlete exists for it -- a PENDING invite. The
    `allowed_emails.athlete_id` column is nullable (`supabase/migrations/
    <onboarding_nullable_athlete>.sql`) precisely so this state is
    representable; `store.add_allowed_email(email)` with no `athlete` creates
    one, and re-inviting the same (normalized) email with an `athlete` later
    upserts it to athlete-bound, same upsert-by-email behavior as always.
    """

    schema_version: int = 1
    email: str
    athlete_slug: str | None = None
    note: str | None = None
    created_at: datetime


class AuthSession(BaseModel):
    """One opaque server-side session (Slice 1 "verified identity").

    Minted by `POST /api/auth/google` after a verified Google ID token
    resolves to an `AllowedEmail`; `token_hash` is the sha256 hex digest of
    the raw session token (the raw token itself is never persisted -- same
    discipline as `Settings.api_token_hash` for the legacy shared token, see
    backend/app/config.py). `require_auth` (backend/app/auth.py) treats a
    session as valid only when `revoked_at is None` and `expires_at` is in
    the future -- both checks happen at the auth layer, not here, so the
    store stays a dumb read/write and the notion of "now" never needs to be
    injected into it.

    Named `AuthSession`, and the DbStore table is `auth_sessions` -- NOT
    `Session`/`sessions` -- because those names are already taken by the
    unrelated WeekPlan-session concept (`Session` above, and the RESERVED
    `sessions` table stub in `supabase/migrations/20260706000000_init.sql`).

    `athlete_slug is None` (Slice 1 self-service onboarding) is an
    ONBOARDING session: minted by `POST /api/auth/google` for an allowlisted
    email with no athlete behind it yet. `require_auth` (backend/app/auth.py)
    resolves such a session to a `Principal(kind="onboarding", athlete=None,
    ...)` -- it can reach `GET /api/me` (so a future frontend can detect
    onboarding mode) but `resolve_athlete` 403s it on every athlete-scoped
    route, since it has no athlete to act as.

    `pending_email` (Slice 2 of self-service onboarding, `supabase/
    migrations/<onboarding_session_email>.sql`) is the verified Google email
    this session belongs to -- set ONLY for an onboarding session
    (`athlete_slug is None`); always `None` for an athlete-bound session,
    which already knows who it is via `athlete_slug`. It's what lets
    `POST /api/onboard` (backend/app/routes/onboard.py) know which PENDING
    `allowed_emails` row it's completing without trusting anything the
    client claims about its own identity -- the email is read off the
    server-side session, never the request body.
    """

    schema_version: int = 1
    token_hash: str
    athlete_slug: str | None = None
    pending_email: str | None = None
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None


class Wellness(BaseModel):
    """A daily wellness check-in.

    The four subjective fields (sleep_quality/stress/soreness/motivation) and
    sleep_hours are optional -- required historically, but an automated
    intervals.icu sync (backend/app/sync.py) can only ever populate the
    objective resting_hr/hrv fields, never a fabricated 1-5 subjective rating
    (same "real load exists regardless of whether it was surveyed"
    principle used elsewhere in this engine). Additive/optional change, no
    schema_version bump -- every existing row already has all five populated.
    """

    schema_version: int = 1
    id: UUID
    athlete_id: UUID
    date: date
    sleep_quality: int | None = Field(default=None, ge=1, le=5)
    sleep_hours: float | None = Field(default=None, ge=0)
    stress: int | None = Field(default=None, ge=1, le=5)
    soreness: int | None = Field(default=None, ge=1, le=5)
    motivation: int | None = Field(default=None, ge=1, le=5)
    resting_hr: int | None = None
    hrv: float | None = None
    notes: str | None = None
    # Provenance, mirroring Workout.source's existing convention. `None` for
    # every pre-existing row (unknown/manual provenance, written before this
    # field existed) -- additive/optional, no schema_version bump.
    source: Literal["manual", "intervals_sync"] | None = None
