"""Client-facing weekly PDF export."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from ..db import metrics_for_client, sessions_for_client
from ..reasoning import generate_recommendation
from ..report import build_weekly_pdf
from .deps import read_only_conn
from .schemas import PdfRequest

router = APIRouter()


@router.post("/api/clients/{client_id}/pdf")
def post_pdf(client_id: str, payload: PdfRequest, con=Depends(read_only_conn)) -> Response:
    row = con.execute(
        "SELECT name, goal FROM clients WHERE id = ?", [client_id]
    ).df()
    if row.empty:
        raise HTTPException(status_code=404, detail=f"No client with id {client_id}")

    metrics = metrics_for_client(con, client_id, days=35)
    sessions = sessions_for_client(con, client_id, days=35)
    rec = generate_recommendation(client_id, metrics, sessions)

    pdf_bytes = build_weekly_pdf(
        client_name=row.iloc[0]["name"],
        client_goal=row.iloc[0]["goal"],
        rec=rec,
        metrics=metrics,
        coach_message=payload.coach_message,
    )
    filename = f"{row.iloc[0]['name'].replace(' ', '_')}_week_{rec.week_of:%Y%m%d}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
