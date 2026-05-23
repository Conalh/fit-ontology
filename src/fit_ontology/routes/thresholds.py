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
from ..reasoning import DEFAULT_THRESHOLDS, recommend_baseline_window
from .deps import read_only_conn
from .schemas import BaselineWindowSuggestionResponse, ThresholdsPatch, ThresholdsResponse

router = APIRouter()


@router.get("/api/clients/{client_id}/thresholds", response_model=ThresholdsResponse)
def get_thresholds(client_id: str, con=Depends(read_only_conn)) -> ThresholdsResponse:
    """Returns the global defaults + this client's sparse overrides + the
    auto-fit suggestion for ``baseline_window_days``. Front-end renders
    each threshold with the override styled distinctly when present, and
    surfaces the suggestion alongside the baseline window row when it
    differs from the active value."""
    metrics = metrics_for_client(con, client_id, days=70)  # need at least 56d for the longest candidate
    suggestion = recommend_baseline_window(metrics)
    return ThresholdsResponse(
        defaults=DEFAULT_THRESHOLDS,
        overrides=thresholds_for_client(con, client_id),
        baseline_window_suggestion=BaselineWindowSuggestionResponse(
            days=suggestion.days, stable=suggestion.stable, reason=suggestion.reason,
        ),
    )


@router.patch("/api/clients/{client_id}/thresholds", response_model=ThresholdsResponse)
def patch_thresholds(client_id: str, payload: ThresholdsPatch) -> ThresholdsResponse:
    """Sparse upsert/delete. Keys with a float value are upserted;
    keys with null are deleted (reverting to the global default).
    Unknown threshold names are rejected so we don't accumulate
    junk rows the reasoning layer never reads."""
    unknown = set(payload.overrides) - set(DEFAULT_THRESHOLDS)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown threshold name(s): {sorted(unknown)}",
        )
    try:
        with connect(DEFAULT_DB_PATH, read_only=False) as con:
            for name, value in payload.overrides.items():
                if value is None:
                    delete_threshold(con, client_id, name)
                else:
                    upsert_threshold(con, client_id, name, value)
            new_overrides = thresholds_for_client(con, client_id)
    except duckdb.IOException as e:
        raise HTTPException(status_code=503, detail=f"DB busy: {e}") from e
    return ThresholdsResponse(defaults=DEFAULT_THRESHOLDS, overrides=new_overrides)
