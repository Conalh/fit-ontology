"""Metrics, sessions, and wearable-export uploads."""
from __future__ import annotations

import contextlib
import tempfile
from pathlib import Path

import duckdb
import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from ..db import (
    DEFAULT_DB_PATH,
    connect,
    insert_metrics,
    metrics_for_client,
    sessions_for_client,
)
from ..ingest import (
    from_apple_health_export,
    from_strava_export,
    from_whoop_json,
)
from .deps import current_trainer_id, read_only_conn
from .schemas import MetricRow, SessionRow

router = APIRouter()


@router.get("/api/clients/{client_id}/metrics", response_model=list[MetricRow])
def get_metrics(
    client_id: str,
    days: int = 35,
    con=Depends(read_only_conn),
    trainer_id: str = Depends(current_trainer_id),
) -> list[MetricRow]:
    df = metrics_for_client(con, trainer_id, client_id, days=days)
    if df.empty:
        return []
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return [MetricRow(**row) for row in df.to_dict(orient="records")]


@router.get("/api/clients/{client_id}/sessions", response_model=list[SessionRow])
def get_sessions(
    client_id: str,
    days: int = 35,
    con=Depends(read_only_conn),
    trainer_id: str = Depends(current_trainer_id),
) -> list[SessionRow]:
    df = sessions_for_client(con, trainer_id, client_id, days=days)
    if df.empty:
        return []
    df["date"] = pd.to_datetime(df["date"]).dt.date
    # SessionRow doesn't carry client_id (already in the route); drop it
    # if the SQL ever adds it.
    return [
        SessionRow(
            id=row["id"], date=row["date"], type=row["type"],
            duration_min=int(row["duration_min"]), rpe=int(row["rpe"]),
            notes=row["notes"] if pd.notna(row["notes"]) else None,
        )
        for row in df.to_dict(orient="records")
    ]


@router.post("/api/clients/{client_id}/upload", response_model=dict)
async def post_upload(
    client_id: str,
    file: UploadFile = File(...),
    trainer_id: str = Depends(current_trainer_id),
) -> dict:
    """Accept a wearable export and ingest it for the given client.

    Sniffs the format from the upload's filename + the first few KB of
    content (matching the Streamlit dashboard's behavior). Returns the
    number of rows inserted and the distinct metric kinds.
    """
    raw = await file.read()
    suffix = Path(file.filename or "").suffix.lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
        tmp_file.write(raw)
        tmp_path = Path(tmp_file.name)
    try:
        if suffix == ".zip" or (suffix == ".xml" and b"HealthData" in raw[:4096]):
            df = from_apple_health_export(tmp_path, client_id)
        elif suffix == ".csv":
            df = from_strava_export(tmp_path, client_id)
        elif suffix == ".json":
            df = from_whoop_json(tmp_path, client_id)
        else:
            raise HTTPException(status_code=415, detail=f"Unsupported file type: {file.filename}")
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp_path.unlink()

    if df.empty:
        return {"inserted": 0, "kinds": []}

    try:
        with connect(DEFAULT_DB_PATH, read_only=False) as con:
            insert_metrics(con, trainer_id, df)
    except duckdb.IOException as e:
        raise HTTPException(status_code=503, detail=f"DB busy: {e}") from e

    return {"inserted": int(len(df)), "kinds": sorted(df["kind"].unique().tolist())}
