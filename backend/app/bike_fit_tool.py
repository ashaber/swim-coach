"""`get_bike_fit`: read-only view of the athlete's bike-geometry snapshots for the coach.

Everything comes from the engine (`swim_coach.bike_fit`); this module only picks snapshots and
compacts the result so a few bikes cost few tokens. It never recommends a change.
"""

from __future__ import annotations

from typing import Any

from swim_coach.bike_fit import (
    LIMITS_STATEMENT,
    BikeFitError,
    FitResult,
    FitValue,
    compare_fits,
    compute_fit,
    resolve_snapshot,
)
from swim_coach.models import BikeFitSnapshot

from app.logging_config import get_logger
from app.tool_errors import storage_error

log = get_logger(__name__)

MAX_SNAPSHOTS = 6


def _values(outputs: list[FitValue]) -> dict[str, dict[str, Any]]:
    return {o.key: {"v": round(o.value, 1), "pm": round(o.sigma, 1), "unit": o.unit} for o in outputs}


def _snapshot_summary(snapshot: BikeFitSnapshot, result: FitResult) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "id": str(snapshot.id), "bike_name": snapshot.bike_name, "bike_type": snapshot.bike_type,
        "date": snapshot.date.isoformat(), "retired": snapshot.retired,
        "values": _values(result.outputs), "closure": result.closure.status,
        "notes": result.notes,
    }
    if result.closure.status != "ok":
        summary["closure_detail"] = {
            "message": result.closure.message, "residual_mm": round(result.closure.residual_mm, 1),
            "suspect_measures": [s.label for s in result.closure.suspects],
        }
    if result.seated is not None:
        summary["seated"] = {"rotation_deg": round(result.seated.rotation_deg, 2),
                             "values": _values(result.seated.outputs), "assumption": result.seated.assumption}
    return summary


def _rows(rows: list[Any]) -> list[dict[str, Any]]:
    return [{"key": r.key, "label": r.label, "a": round(r.a, 1), "b": round(r.b, 1), "diff": round(r.diff, 1),
             "pm_diff": round(r.sigma_diff, 1), "exceeds_error": r.exceeds_error} for r in rows]


def _selected(snapshots: list[BikeFitSnapshot], bike: str | None) -> list[BikeFitSnapshot]:
    live = sorted((s for s in snapshots if not s.retired), key=lambda s: s.date, reverse=True)
    if bike:
        return [s for s in live if s.bike_name.lower() == bike.strip().lower()][:MAX_SNAPSHOTS]
    seen: set[str] = set()
    newest: list[BikeFitSnapshot] = []
    for s in live:
        if s.bike_name.lower() not in seen:
            seen.add(s.bike_name.lower())
            newest.append(s)
    return newest[:MAX_SNAPSHOTS]


def handle_get_bike_fit(input_data: dict[str, Any], *, store: Any, slug: str) -> dict[str, Any]:
    try:
        athlete = store.load_athlete(slug)
    except Exception as exc:  # noqa: BLE001
        log.error("storage read failed", what="athlete profile", exc_info=True)
        return storage_error("athlete profile", exc)
    snapshots = athlete.bike_fit_snapshots
    ref_a, ref_b = input_data.get("compare_a"), input_data.get("compare_b")
    if ref_a or ref_b:
        if not (ref_a and ref_b):
            return {"error": "give both compare_a and compare_b (snapshot ids or bike names)"}
        first, second = resolve_snapshot(snapshots, str(ref_a)), resolve_snapshot(snapshots, str(ref_b))
        if first is None or second is None:
            return {"error": "no bike fit snapshot matches compare_a / compare_b"}
        try:
            ra, rb = compute_fit(first.inputs, first.bike_type), compute_fit(second.inputs, second.bike_type)
        except BikeFitError as exc:
            return {"error": str(exc)}
        comparison = compare_fits(ra, rb)
        return {
            "snapshots": [_snapshot_summary(first, ra), _snapshot_summary(second, rb)],
            "comparison": {
                "unweighted": _rows(comparison.unweighted),
                "seated": _rows(comparison.seated) if comparison.seated else None,
                "exceeds_error_means": f"difference is more than {comparison.factor:g} x its combined +/-",
                "notes": comparison.notes,
            },
            "limits": LIMITS_STATEMENT,
        }
    out: list[dict[str, Any]] = []
    for snap in _selected(snapshots, input_data.get("bike")):
        try:
            out.append(_snapshot_summary(snap, compute_fit(snap.inputs, snap.bike_type)))
        except BikeFitError as exc:
            out.append({"id": str(snap.id), "bike_name": snap.bike_name, "date": snap.date.isoformat(),
                        "error": str(exc)})
    return {"snapshots": out, "limits": LIMITS_STATEMENT}
