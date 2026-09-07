"""Build a `.zwo` file export for one INDOOR/trainer bike `Session` -- the
counterpart to `app.garmin_push` (outdoor cycling, and swim/strength). See
that module's own docstring for the outdoor push mechanism, and
`swim_coach.zwo_export`'s module docstring for the sibling `workout-to-zwo`
skill this whole feature ports and the full structure->XML design rationale.

Unlike a Garmin push, a `.zwo` file is NOT a live external calendar write --
it's an inert file the athlete loads into MyWhoosh/Zwift's own Workout
Builder herself. That's the reason this is a plain, straightforward
build-and-return function (used by both `GET /api/sessions/{id}/zwo` and the
`export_zwo_workout` chat tool -- see `app.tools`), not a draft-then-confirm
flow the way `propose_adaptation`/`replace_macro_plan` are: there is nothing
already-active for a bad call to disrupt, and the actual "commit" step (the
athlete or coach opening the code block and saving it, or downloading the
file) always happens outside this system.
"""

from __future__ import annotations

from typing import Any

from swim_coach.models import Session
from swim_coach.zwo_export import to_zwo_workout


def build_zwo_export(session: Session, ftp_watts: float) -> dict[str, Any]:
    """Builds the `.zwo` XML for `session` against `ftp_watts` (the
    athlete's own `Athlete.ftp_watts`, resolved by the caller -- see
    `app.routes.garmin`'s `GET .../zwo` route and `app.tools`'
    `_handle_export_zwo_workout`, both of which do their own
    sport/`structured`/ftp-availability checks BEFORE calling this,
    mirroring `app.garmin_push.build_workout_event`'s own "caller
    pre-checks, this function is deliberately still a thin, honest
    'do the build' primitive" split).

    Raises whatever `swim_coach.zwo_export.to_zwo_workout` raises (a real
    structural limitation -- e.g. a non-time-based duration_kind, or a
    `WorkoutRepeat` outside the supported on/off-pair shape) -- callers turn
    that into their own error response (422, since it's an engine bug/
    unsupported-shape situation, never an athlete input error).
    """
    xml_str = to_zwo_workout(session.structured, ftp_watts=ftp_watts, name=session.purpose)
    filename = f"{session.date.isoformat()}-bike.zwo"
    return {
        "zwo_xml": xml_str,
        "filename": filename,
        "session_id": str(session.id),
        "ftp_watts": ftp_watts,
    }
