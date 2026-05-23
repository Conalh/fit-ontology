"""CRUD on the clients table."""
from __future__ import annotations

import uuid

import duckdb
from fastapi import APIRouter, Depends, HTTPException

from ..db import DEFAULT_DB_PATH, connect, list_clients
from ..ontology import Sex
from .deps import read_only_conn
from .schemas import ClientCreate, ClientSummary, ClientUpdate

router = APIRouter()


@router.get("/api/clients", response_model=list[ClientSummary])
def get_clients(con=Depends(read_only_conn)) -> list[ClientSummary]:
    df = list_clients(con)
    return [ClientSummary(**row) for row in df.to_dict(orient="records")]


@router.get("/api/clients/{client_id}")
def get_client(client_id: str, con=Depends(read_only_conn)) -> dict:
    row = con.execute(
        "SELECT id, name, sex, age, height_cm, weight_kg, goal, injury_history FROM clients WHERE id = ?",
        [client_id],
    ).df()
    if row.empty:
        raise HTTPException(status_code=404, detail=f"No client with id {client_id}")
    return row.iloc[0].to_dict()


@router.post("/api/clients")
def post_client(payload: ClientCreate) -> dict:
    """Create a new client. Returns the generated id so the front-end
    can navigate straight to the detail page."""
    client_id = f"c_{uuid.uuid4().hex[:12]}"
    try:
        with connect(DEFAULT_DB_PATH, read_only=False) as con:
            con.execute(
                """
                INSERT INTO clients
                  (id, name, sex, age, height_cm, weight_kg, goal, injury_history, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                [
                    client_id,
                    payload.name,
                    payload.sex.value,
                    payload.age,
                    payload.height_cm,
                    payload.weight_kg,
                    payload.goal,
                    payload.injury_history,
                ],
            )
    except duckdb.IOException as e:
        raise HTTPException(status_code=503, detail=f"DB busy: {e}") from e
    return {"id": client_id}


@router.patch("/api/clients/{client_id}")
def patch_client(client_id: str, payload: ClientUpdate) -> dict:
    """Partial update. Builds the SET clause from only the fields the
    trainer touched so we don't overwrite values they left alone."""
    updates = payload.model_dump(exclude_none=True)
    if "sex" in updates and isinstance(updates["sex"], Sex):
        updates["sex"] = updates["sex"].value
    if not updates:
        return {"ok": True, "updated": []}

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = [*updates.values(), client_id]
    try:
        with connect(DEFAULT_DB_PATH, read_only=False) as con:
            existing = con.execute(
                "SELECT 1 FROM clients WHERE id = ?", [client_id]
            ).fetchone()
            if not existing:
                raise HTTPException(status_code=404, detail=f"No client with id {client_id}")
            con.execute(f"UPDATE clients SET {set_clause} WHERE id = ?", values)
    except duckdb.IOException as e:
        raise HTTPException(status_code=503, detail=f"DB busy: {e}") from e
    return {"ok": True, "updated": list(updates.keys())}
