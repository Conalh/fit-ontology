"""Shared helpers for converting DB rows into Pydantic response models.

These exist because pandas returns NaN/NaT for null DOUBLE/TIMESTAMP
columns and we need to normalize to ``None`` before Pydantic gets
hold of them. Centralizing the coercion here means individual routes
don't repeat the same NaN-checking pattern.
"""
from __future__ import annotations

import pandas as pd

from ..ontology import RecommendationOverride
from .schemas import OverrideResponse


def classify_rec(rec_text: str) -> str:
    low = rec_text.lower()
    if low.startswith("deload"):
        return "Deload"
    if low.startswith("conservative"):
        return "Conservative"
    if low.startswith("standard"):
        return "Standard"
    return "Other"


def override_response(row: dict) -> OverrideResponse:
    """Coerce a DataFrame row dict into an OverrideResponse. Pandas
    returns NaN for null DOUBLEs and NaT for nulls in datetime columns;
    we normalize to None for JSON serialization."""
    pct = row.get("applied_load_change_pct")
    if pct is not None and pd.isna(pct):
        pct = None
    note = row.get("trainer_note")
    if note is not None and pd.isna(note):
        note = None
    return OverrideResponse(
        id=row["id"], client_id=row["client_id"], week_of=row["week_of"],
        system_recommendation=row["system_recommendation"],
        system_confidence=float(row["system_confidence"]),
        trainer_action=str(row["trainer_action"]),
        applied_load_change_pct=pct,
        trainer_note=note,
        created_at=row["created_at"],
    )


def override_response_from_model(ov: RecommendationOverride) -> OverrideResponse:
    return OverrideResponse(
        id=ov.id, client_id=ov.client_id, week_of=ov.week_of,
        system_recommendation=ov.system_recommendation,
        system_confidence=ov.system_confidence,
        trainer_action=ov.trainer_action.value,
        applied_load_change_pct=ov.applied_load_change_pct,
        trainer_note=ov.trainer_note,
        created_at=ov.created_at,
    )
