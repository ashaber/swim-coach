# Canonical structured workout data model

**Status:** designed and built across five PRs (#91, #92, #93, #94, #95), all
open, CI-green, mergeable, not yet merged as of this writing. See each PR for
the actual diffs; this doc captures the design and the reasoning behind it so
it survives independent of any single PR's description.

## Why this exists

The engine's main-set template library (`engine/swim_coach/workout_templates.py`,
built earlier the same session) generated `Session.structure` as free-text
prose directly. While reviewing that, a bigger question came up: was
generating prose first — with the Plan tab's UI then regex-parsing that prose
back into visual blocks (`web/src/plan.js`'s `parseStructureBlocks`/
`parseMainSetIntervals`) — backwards? And could the same underlying data
export to a real device format (a Garmin watch), which prose fundamentally
cannot?

The answer to both: yes. This model inverts the generation order — the
engine now builds a **structured intermediate representation (IR)** first,
and prose, the Plan tab UI, and Garmin export are all just *renderings* of
that same IR, never independent representations that can drift from each
other.

## Template vs. Workout

A **workout template** is a workout *shape* whose targets are
modality-relative — a zone (`Z3`), a percentage of a baseline (`135% of CSS`,
`70% of 1RM`) — never an absolute number. A **workout** is a template with
those relative targets *resolved* against one athlete's actual profile (CSS
pace, 1RM) into absolute numbers. This isn't a new concept forced onto the
codebase — `zones.py` already resolved Z1–Z5 into absolute pace from CSS at
generation time; this makes that same relative-to-absolute resolution
explicit and uniform across swim *and* strength, instead of implicit and
swim-only.

The same `WorkoutStep`/`WorkoutRepeat` tree shape serves both stages — a
`WorkoutTarget`/`WorkoutLoad`'s `basis` field distinguishes relative
(`zone`, `percent_css`, `percent_1rm`) from resolved (`absolute`), rather than
needing two parallel class trees for "template" and "workout."

## The model (`engine/swim_coach/models.py`, PR #91)

Flat pydantic v2 `BaseModel`s with `Literal`-typed discriminator fields and
`schema_version: int = 1`, matching this file's existing house style
throughout — **not** a class-inheritance hierarchy. This codebase already
avoids inheritance everywhere (`Sport = Literal[...]`), and a prior-art
reference (an existing `.zwo`-workout-authoring skill) uses the same
flat/tagged style for its own section-type field. Composition over
inheritance here is continuity, not a new pattern — and it's what makes
JSON/YAML round-tripping simple (pattern-match on a tag field, no
polymorphic deserialization).

```python
class WorkoutTarget(BaseModel):
    schema_version: int = 1
    basis: Literal["zone", "percent_css", "absolute", "rpe", "open"]
    zone: Literal["Z1", "Z2", "Z3", "Z4", "Z5"] | None = None
    low: float | None = None   # percent_css: % of CSS; absolute: pace_s_per_100m
    high: float | None = None

class WorkoutLoad(BaseModel):
    schema_version: int = 1
    basis: Literal["bodyweight", "percent_1rm", "absolute", "rpe_only"]
    value: float | None = None

class WorkoutStep(BaseModel):
    schema_version: int = 1
    kind: Literal["step"] = "step"
    label: str
    role: Literal["warmup", "steady", "interval", "rest", "recovery", "cooldown", "open"]
    duration_kind: Literal["time_s", "distance_m", "reps", "open"]
    duration_value: float | None = None
    target: WorkoutTarget | None = None    # swim/cardio steps
    load: WorkoutLoad | None = None        # strength steps
    modality: Literal["swim", "strength"] = "swim"
    stroke: Literal["free", "back", "breast", "fly", "im", "mixed", "drill"] | None = None
    equipment: list[str] = []
    exercise_name: str | None = None       # strength steps

class WorkoutRepeat(BaseModel):
    schema_version: int = 1
    kind: Literal["repeat"] = "repeat"
    repeat_mode: Literal["count", "for_duration", "amrap"] = "count"
    count: int | None = None          # repeat_mode == "count"
    duration_s: float | None = None   # for_duration/amrap: total window length
    interval_s: float | None = None   # for_duration: e.g. 60 for classic EMOM
    steps: list["WorkoutStepOrRepeat"]

class WorkoutStructure(BaseModel):
    schema_version: int = 1
    items: list[WorkoutStepOrRepeat]
```

`Session.structured: WorkoutStructure | None = None` was added **alongside**
the existing `Session.structure: str | None` — additive, not a replacement.
Both `week_to_row`/`row_to_week` (Postgres) and `store.py`'s FileStore YAML
dump serialize the whole model generically (`model_dump(mode="json")` /
`model_validate`), so this required **no SQL migration and no backfill** —
old rows simply don't have the field (`None`), same as every other additive
field change in this codebase.

### Why `WorkoutRepeat` needs `repeat_mode`, not just a count

A plain `count` (execute N times) can't express EMOM ("every minute on the
minute" — a new round starts on a fixed interval regardless of how long the
round took) or AMRAP (as many rounds/reps as possible in a time window).
Without this distinction, deriving "is this an EMOM" from the structure later
becomes impossible without a hand-typed, drift-prone tag — exactly the
failure mode this whole design exists to avoid. Getting this right at the
model level, before any real template used it, mattered more than it looked.

## Template metadata: derive, don't duplicate (PR #94)

Adding searchable metadata to the template library (`WorkoutTemplate`)
surfaced the same drift risk one level up: most of what you'd want to query
— equipment used, whether it's a medley, whether it's EMOM-style, roughly
how long it takes — is **mechanically derivable from a template's own
`WorkoutStructure`**. Hand-typing those as tags means they can (and will)
drift from the actual content the moment someone edits the template.

The split that survived:
- **Hand-authored** (genuinely subjective, non-derivable): `purpose`
  (`aerobic_base` / `threshold` / `race_pace` / `technique` / `sprint_power`
  / `recovery` / `strength_endurance` / `max_strength` / `posterior_chain`)
  — coaching intent that can't be read off the geometry (an 8×200 straight
  set could be aerobic-base or a threshold test; only the author knows
  which). Plus `tags: list[str]` as a narrow escape hatch for genuinely
  long-tail labels, not the primary query mechanism.
- **Computed at load time, never persisted** (`TemplateFacets`): `modality`,
  `equipment`, `strokes`/`is_medley`, `interval_style` (including
  `emom`/`amrap`, derived from `WorkoutRepeat.repeat_mode` — not the old
  `format_type` field, which the masters-workout research had already found
  couldn't name every real shape found in the wild), approximate
  duration/distance (nominal only — a template's numbers are parametric,
  resolved per-athlete at render time; exact-minute filtering only makes
  sense on a *resolved workout*, not a template).

`find_templates(purpose=, modality=, block=, max_duration_s=, equipment_any=,
interval_style=)` queries the loaded templates + facets. Storage stays
file-based (YAML in `engine/swim_coach/workout_templates/`, no database):
templates are shared, git-versioned, PR-reviewed library assets — like
engine constants — categorically different from the per-athlete *mutable*
data Postgres exists to serve in this app. Revisit only if templates become
user-generated/mutable at runtime, reach the thousands, or need
cross-athlete analytics.

`backend/app/tools.py`'s `create_week_plan`/`replace_week_plan` both gained
an optional `template_preference` parameter threading through to
`find_templates`, so the chat coach can honor "give me more kettlebell work"
instead of only ever getting whatever the deterministic rotation lands on.

## Garmin export: a real correction mid-design (PR #95)

The original plan assumed "manually load a JSON workout into Garmin
Connect" was a viable, simple export target. It isn't — fact-checked with
real fetched sources (Garmin's own manuals, Garmin community forum threads):
**Garmin Connect's own import/upload UI is activities-only; there is no
workout-file import into Connect itself.** What's actually real and
documented: a workout-type **`.FIT` file copied via USB to the watch's
`NewFiles`/`Workouts` folder**, which explicitly supports pool swim
(pace/HR targets) and lands directly on the device as a followable
structured workout — no Connect account sync, no OAuth Developer API needed.

`engine/swim_coach/garmin_export.py`'s `to_garmin_fit_workout()` uses the
`fit_tool` library (the only real currently-maintained Python *writer* for
FIT — `fitparse`/`fitdecode` are read-only decoders). Building this surfaced
a real bug in `fit_tool` 0.9.15 itself: `SubField.is_valid()` checks dict
membership against field-id keys instead of the valid-value list, silently
mis-scaling some fields by 10x on encode (worked around via the low-level
`Field.set_value()` API with an explicitly-resolved `SubField`, verified via
an independent `fitdecode` round-trip, not `fit_tool`'s own reader — which
has the same bug and would have silently "confirmed" the corrupted value).

A backend endpoint (`GET /api/sessions/{id}/garmin.fit`) and a download
button in the Plan tab's session detail view make this reachable from the
app — not a CLI-only capability. A `.zwo` (Zwift) export was considered as
inspiration for the general step/repeat shape but deliberately not built:
Zwift has no swim activity type, so a swim `.zwo` has nowhere to go.

## UI: render from the IR directly, not regex over prose (PR #93)

Keeping `parseStructureBlocks`/`parseMainSetIntervals` as the *only* path
would have perpetuated exactly the "generate prose, then reverse-engineer
structure back out of it" pattern this whole redesign exists to kill. Phase
A (this pass): `web/src/plan.js`'s `renderStructuredWorkout` walks
`WorkoutStructure.items` directly into readable lines when `session.structured`
is present, falling back to the existing prose/regex path only for legacy
sessions generated before this pipeline (`structured` absent). The regex
parser is not being kept indefinitely — a follow-up Phase B (not built here)
is expected to replace the polished per-block Warm-up/Main-set/Cool-down
prose UI with a structured-aware equivalent, retiring
`parseStructureBlocks` entirely once every session type generates
`structured`.

## Merge order

- **PR #91** (base `main`) is the foundation — must merge first.
- **PR #92** (base `main`) is an independent, unrelated live-bug fix
  (`replace_week_plan`'s `session_overrides`) — no dependency either way,
  merges whenever.
- **PR #93 / #94 / #95** (base `engine/workout-structure-model`, PR #91's
  branch) — once #91 merges to `main`, retarget each of these three to
  `main` (GitHub does this automatically once the base branch is deleted,
  but double-check the diff shown is just that PR's own changes, not #91's
  content again, before merging — this exact mechanics trap stranded an
  earlier PR's content on the wrong branch once already this session).
