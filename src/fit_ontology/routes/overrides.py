"""Trainer overrides — list + record a new decision."""
from __future__ import annotations

import uuid
from datetime import datetime

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Request

from ..db import DEFAULT_DB_PATH, connect, insert_override, overrides_for_client, record_audit
from ..ontology import RecommendationOverride
from .deps import current_trainer_id, forbid_demo_trainer, read_only_conn
from .helpers import override_response, override_response_from_model
from .schemas import OverrideCreate, OverrideResponse

router = APIRouter()


@router.get("/api/clients/{client_id}/overrides", response_model=list[OverrideResponse])
def get_overrides(
    client_id: str,
    limit: int = 20,
    con=Depends(read_only_conn),
    trainer_id: str = Depends(current_trainer_id),
) -> list[OverrideResponse]:
    df = overrides_for_client(con, trainer_id, client_id, limit=limit)
    if df.empty:
        return []
    return [override_response(row) for row in df.to_dict(orient="records")]


@router.post("/api/clients/{client_id}/overrides", response_model=OverrideResponse)
def post_override(
    client_id: str,
    payload: OverrideCreate,
    request: Request,
    trainer_id: str = Depends(forbid_demo_trainer),
) -> OverrideResponse:
    ov = RecommendationOverride(
        id=f"o_{uuid.uuid4().hex[:12]}",
        client_id=client_id,
        week_of=payload.week_of,
        system_recommendation=payload.system_recommendation,
        system_confidence=payload.system_confidence,
        trainer_action=payload.trainer_action,
        trainer_recommendation=payload.trainer_recommendation,
        applied_load_change_pct=payload.applied_load_change_pct,
        trainer_note=payload.trainer_note,
        created_at=datetime.now(),
    )
    client_ip = request.client.host if request.client else None
    try:
        with connect(DEFAULT_DB_PATH, read_only=False) as con:
            insert_override(con, trainer_id, ov)
            record_audit(
                con, trainer_id, "override.saved",
                target_type="client", target_id=client_id,
                details={
                    "override_id": ov.id,
                    "week_of": ov.week_of.isoformat(),
                    "trainer_action": ov.trainer_action.value,
                },
                ip=client_ip,
            )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except duckdb.IOException as e:
        # Cross-process write conflict (Garmin sync holds the writer lock).
        raise HTTPException(status_code=503, detail=f"DB busy: {e}") from e

    return override_response_from_model(ov)
