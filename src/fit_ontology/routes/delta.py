"""Weekly delta: plan-vs-reality summary for one client."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..weekly_delta import build_weekly_delta
from ..weekly_state import ClientNotFoundError
from .deps import current_trainer_id, read_only_conn
from .schemas import WeeklyDeltaResponse

router = APIRouter()


@router.get("/api/clients/{client_id}/weekly-delta", response_model=WeeklyDeltaResponse)
def get_weekly_delta(
    client_id: str,
    con=Depends(read_only_conn),
    trainer_id: str = Depends(current_trainer_id),
) -> WeeklyDeltaResponse:
    try:
        delta = build_weekly_delta(con, trainer_id, client_id)
    except ClientNotFoundError:
        raise HTTPException(status_code=404, detail=f"No client with id {client_id}") from None
    return WeeklyDeltaResponse(**delta.__dict__)
