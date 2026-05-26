"""Client-facing weekly PDF export."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from ..report import build_weekly_pdf
from ..weekly_state import ClientNotFoundError, build_weekly_client_state
from .deps import current_trainer_id, read_only_conn
from .schemas import PdfRequest

router = APIRouter()


@router.post("/api/clients/{client_id}/pdf")
def post_pdf(
    client_id: str,
    payload: PdfRequest,
    con=Depends(read_only_conn),
    trainer_id: str = Depends(current_trainer_id),
) -> Response:
    try:
        state = build_weekly_client_state(con, trainer_id, client_id, include_plan=False)
    except ClientNotFoundError:
        raise HTTPException(status_code=404, detail=f"No client with id {client_id}") from None

    pdf_bytes = build_weekly_pdf(
        client_name=state.client_name,
        client_goal=state.client_goal,
        rec=state.recommendation,
        metrics=state.metrics,
        coach_message=payload.coach_message,
    )
    filename = f"{state.client_name.replace(' ', '_')}_week_{state.recommendation.week_of:%Y%m%d}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
