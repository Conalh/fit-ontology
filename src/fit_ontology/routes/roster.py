"""Multi-client triage: one row per client with rec label + freshness."""
from __future__ import annotations

from datetime import date

import pandas as pd
from fastapi import APIRouter, Depends

from ..db import list_clients, metrics_for_client, sessions_for_client
from ..reasoning import generate_recommendation
from .deps import current_trainer_id, read_only_conn
from .helpers import classify_rec
from .schemas import RosterRow

router = APIRouter()


@router.get("/api/roster", response_model=list[RosterRow])
def get_roster(
    con=Depends(read_only_conn),
    trainer_id: str = Depends(current_trainer_id),
) -> list[RosterRow]:
    """Computed roster: one row per client with the recommendation
    label, flag kinds, and freshness. The frontend handles sorting and
    presentation — we just hand over structured data."""
    clients = list_clients(con, trainer_id)
    if clients.empty:
        return []

    today = pd.Timestamp(date.today())
    out: list[RosterRow] = []

    for _, client in clients.iterrows():
        cid = client["id"]
        metrics = metrics_for_client(con, trainer_id, cid, days=28)
        sessions = sessions_for_client(con, trainer_id, cid, days=28)

        last_days: int | None = None
        if not metrics.empty:
            last_days = int((today - pd.to_datetime(metrics["date"]).max()).days)

        if last_days is None or last_days > 7:
            out.append(RosterRow(
                client_id=cid, name=client["name"], goal=client["goal"],
                label="No recent data", flags=[],
                confidence=None, sources=0,
                last_data_days=last_days, stale=True,
            ))
            continue

        rec = generate_recommendation(cid, metrics, sessions)
        label = classify_rec(rec.recommendation)
        flags: list[str] = []
        if "Flags:" in rec.rationale:
            flags = [f.strip() for f in rec.rationale.split("Flags:", 1)[1].strip().rstrip(".").split(",") if f.strip()]

        out.append(RosterRow(
            client_id=cid, name=client["name"], goal=client["goal"],
            label=label, flags=flags,
            confidence=rec.confidence, sources=len(rec.source_metric_ids),
            last_data_days=last_days, stale=False,
        ))

    return out
