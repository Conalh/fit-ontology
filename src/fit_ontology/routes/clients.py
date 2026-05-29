"""CRUD on the clients table."""
from __future__ import annotations

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Request

from ..db import (
    DEFAULT_DB_PATH,
    connect,
    delete_client_cascade,
    insert_client_from_payload,
    list_clients,
    record_audit,
)
from ..ontology import Sex
from .deps import current_trainer_id, forbid_demo_trainer, read_only_conn, real_client_ip
from .schemas import ClientCreate, ClientSummary, ClientUpdate

router = APIRouter()


@router.get("/api/clients", response_model=list[ClientSummary])
def get_clients(
    con=Depends(read_only_conn),
    trainer_id: str = Depends(current_trainer_id),
) -> list[ClientSummary]:
    df = list_clients(con, trainer_id)
    return [ClientSummary(**row) for row in df.to_dict(orient="records")]


@router.get("/api/clients/{client_id}")
def get_client(
    client_id: str,
    con=Depends(read_only_conn),
    trainer_id: str = Depends(current_trainer_id),
) -> dict:
    # trainer_id in the WHERE clause is what makes "another trainer's
    # client" a 404 rather than a successful lookup.
    row = con.execute(
        """
        SELECT id, name, sex, age, height_cm, weight_kg, goal, injury_history
        FROM clients
        WHERE id = ? AND trainer_id = ?
        """,
        [client_id, trainer_id],
    ).df()
    if row.empty:
        raise HTTPException(status_code=404, detail=f"No client with id {client_id}")
    return row.iloc[0].to_dict()


@router.post("/api/clients")
def post_client(
    payload: ClientCreate,
    request: Request,
    trainer_id: str = Depends(forbid_demo_trainer),
) -> dict:
    """Create a new client. Returns the generated id so the front-end
    can navigate straight to the detail page."""
    client_ip = real_client_ip(request)
    try:
        with connect(DEFAULT_DB_PATH, read_only=False) as con:
            client_id = insert_client_from_payload(con, trainer_id, payload)
            # Audit name only — the rest is PII we don't want in the
            # log row even though the row itself is trainer-scoped.
            record_audit(
                con, trainer_id, "client.created",
                target_type="client", target_id=client_id,
                details={"name": payload.name},
                ip=client_ip,
            )
    except duckdb.IOException as e:
        raise HTTPException(status_code=503, detail=f"DB busy: {e}") from e
    return {"id": client_id}


@router.patch("/api/clients/{client_id}")
def patch_client(
    client_id: str,
    payload: ClientUpdate,
    trainer_id: str = Depends(forbid_demo_trainer),
) -> dict:
    """Partial update. Builds the SET clause from only the fields the
    trainer touched so we don't overwrite values they left alone."""
    updates = payload.model_dump(exclude_none=True)
    if "sex" in updates and isinstance(updates["sex"], Sex):
        updates["sex"] = updates["sex"].value
    if not updates:
        return {"ok": True, "updated": []}

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = [*updates.values(), client_id, trainer_id]
    try:
        with connect(DEFAULT_DB_PATH, read_only=False) as con:
            existing = con.execute(
                "SELECT 1 FROM clients WHERE id = ? AND trainer_id = ?",
                [client_id, trainer_id],
            ).fetchone()
            if not existing:
                raise HTTPException(status_code=404, detail=f"No client with id {client_id}")
            con.execute(
                f"UPDATE clients SET {set_clause} WHERE id = ? AND trainer_id = ?",
                values,
            )
    except duckdb.IOException as e:
        raise HTTPException(status_code=503, detail=f"DB busy: {e}") from e
    return {"ok": True, "updated": list(updates.keys())}


@router.delete("/api/clients/{client_id}")
def delete_client(
    client_id: str,
    request: Request,
    trainer_id: str = Depends(forbid_demo_trainer),
) -> dict:
    """Hard-delete a client and every row that FK-references them
    (sessions, metrics, recommendations, overrides, planned sessions,
    thresholds, share tokens; intake tokens get their consumed_client_id
    NULL'd to preserve the mint-event trail).

    Returns ``{"ok": True, "name": "..."}`` so the front-end can show
    a "Deleted Captain Ahab" toast without having to remember which
    client just disappeared. 404 if the client doesn't belong to the
    calling trainer — same shape as a missing client, so we don't
    leak the difference between "doesn't exist" and "isn't yours."

    The audit row captures the client's name in ``details`` so the
    trail survives even after the row is gone. This is the one piece
    of PII we deliberately put in the log (name only; goal / injury
    history stay on the row, which is now deleted) — without it the
    audit table would carry "client.deleted" events that point at
    nonexistent ids, and a year from now the trainer can't answer
    "what was client_id c_abc?".
    """
    client_ip = real_client_ip(request)
    try:
        # NOT wrapped in transaction(): DuckDB's foreign-key checker is
        # over-eager inside an explicit transaction — the parent DELETE
        # FROM clients still "sees" the child rows we deleted earlier in
        # the same uncommitted transaction and raises ConstraintException.
        # See delete_client_cascade's docstring. The deletes therefore run
        # leaf-first under per-statement autocommit on one serialized
        # connection, which is the partial-write protection DuckDB allows
        # here.
        with connect(DEFAULT_DB_PATH, read_only=False) as con:
            snapshot = delete_client_cascade(con, trainer_id, client_id)
            if snapshot is None:
                raise HTTPException(
                    status_code=404, detail=f"No client with id {client_id}"
                )
            record_audit(
                con, trainer_id, "client.deleted",
                target_type="client", target_id=client_id,
                details={"name": snapshot["name"]},
                ip=client_ip,
            )
    except duckdb.IOException as e:
        raise HTTPException(status_code=503, detail=f"DB busy: {e}") from e
    return {"ok": True, "name": snapshot["name"]}
