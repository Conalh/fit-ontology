"""Per-client reasoning thresholds — global defaults + sparse overrides."""
from __future__ import annotations

import duckdb
from fastapi import APIRouter, Depends, HTTPException

from ..db import (
    DEFAULT_DB_PATH,
    connect,
    delete_threshold,
    metrics_for_client,
    thresholds_for_client,
    upsert_threshold,
)
from ..reasoning import DEFAULT_THRESHOLDS, recommend_baseline_window, validate_thresholds
from .deps import current_trainer_id, forbid_demo_trainer, read_only_conn
from .schemas import BaselineWindowSuggestionResponse, ThresholdsPatch, ThresholdsResponse

router = APIRouter()


def _ensure_client(con, trainer_id: str, client_id: str) -> None:
    row = con.execute(
        "SELECT 1 FROM clients WHERE id = ? AND trainer_id = ?",
        [client_id, trainer_id],
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"No client with id {client_id}")


@router.get("/api/clients/{client_id}/thresholds", response_model=ThresholdsResponse)
def get_thresholds(
    client_id: str,
    con=Depends(read_only_conn),
    trainer_id: str = Depends(current_trainer_id),
) -> ThresholdsResponse:
    """Returns the global defaults + this client's sparse overrides + the
    auto-fit suggestion for ``baseline_window_days``. Front-end renders
    each threshold with the override styled distinctly when present, and
    surfaces the suggestion alongside the baseline window row when it
    differs from the active value."""
    _ensure_client(con, trainer_id, client_id)
    metrics = metrics_for_client(con, trainer_id, client_id, days=70)  # need at least 56d for the longest candidate
    suggestion = recommend_baseline_window(metrics)
    return ThresholdsResponse(
        defaults=DEFAULT_THRESHOLDS,
        overrides=thresholds_for_client(con, trainer_id, client_id),
        baseline_window_suggestion=BaselineWindowSuggestionResponse(
            days=suggestion.days, stable=suggestion.stable, reason=suggestion.reason,
        ),
    )


@router.patch("/api/clients/{client_id}/thresholds", response_model=ThresholdsResponse)
def patch_thresholds(
    client_id: str,
    payload: ThresholdsPatch,
    trainer_id: str = Depends(forbid_demo_trainer),
) -> ThresholdsResponse:
    """Sparse upsert/delete. Keys with a float value are upserted;
    keys with null are deleted (reverting to the global default).
    Unknown threshold names are rejected so we don't accumulate junk
    rows the reasoning layer never reads; out-of-range or mis-ordered
    values are rejected so a fat-fingered override can't quietly break
    the severity ladder the engine reasons over."""
    unknown = set(payload.overrides) - set(DEFAULT_THRESHOLDS)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown threshold name(s): {sorted(unknown)}",
        )
    try:
        with connect(DEFAULT_DB_PATH, read_only=False) as con:
            _ensure_client(con, trainer_id, client_id)

            # Validate the *resulting* effective set, not just the patch:
            # apply this patch on top of the client's current overrides,
            # merge over the defaults, and check ranges + ladder ordering.
            # A sparse patch (e.g. only hrv_moderate_sd) is then judged
            # against the mild/severe values it leaves untouched.
            resulting = dict(thresholds_for_client(con, trainer_id, client_id))
            for name, value in payload.overrides.items():
                if value is None:
                    resulting.pop(name, None)
                else:
                    resulting[name] = value
            effective = {**DEFAULT_THRESHOLDS, **resulting}
            try:
                validate_thresholds(effective)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e

            for name, value in payload.overrides.items():
                if value is None:
                    delete_threshold(con, trainer_id, client_id, name)
                else:
                    upsert_threshold(con, trainer_id, client_id, name, value)
            new_overrides = thresholds_for_client(con, trainer_id, client_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except duckdb.IOException as e:
        raise HTTPException(status_code=503, detail=f"DB busy: {e}") from e
    return ThresholdsResponse(defaults=DEFAULT_THRESHOLDS, overrides=new_overrides)
