"""Intake tokens — trainer mints, prospective client submits (no auth).

Phase 3b. The inbound counterpart to ``share.py``: that one is outbound
(trainer publishes a read-only weekly view); this one is inbound
(prospective client opens a URL, fills the form, and the submission
inserts their row into the trainer's roster scoped to the token's
trainer_id).

Three endpoints, split by auth surface:

  POST /api/clients/intake/mint   trainer-scoped; mints a one-shot token
  GET  /api/intake/{token}        PUBLIC; preflight for the form page —
                                  trainer name + optional welcome
                                  message + token state
  POST /api/intake/{token}        PUBLIC; submits the form, atomically
                                  consumes the token + inserts the
                                  client in one transaction

Mint is rate-limited per trainer (INTAKE_MINT_LIMIT) and demo-trainer-
forbidden. Submit is rate-limited per IP (INTAKE_SUBMIT_LIMIT) because
the caller isn't authed — the trainer isn't known until the token
resolves. Every mint writes ``intake.minted``, every successful
submission writes ``intake.submitted`` (scoped to the resolved
trainer, with the new client_id as the audit target), so the trainer
can reconcile "I sent N links" against "N clients arrived" without
inferring across log lines.
"""
from __future__ import annotations

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Request

from ..db import (
    DEFAULT_DB_PATH,
    connect,
    consume_intake_token,
    create_intake_token,
    insert_client_from_payload,
    intake_lookup,
    record_audit,
)
from ..rate_limit import INTAKE_MINT_LIMIT, INTAKE_SUBMIT_LIMIT, enforce
from .deps import forbid_demo_trainer, read_only_conn
from .schemas import (
    ClientCreate,
    IntakeMintRequest,
    IntakeMintResponse,
    IntakeViewResponse,
)

router = APIRouter()


@router.post("/api/clients/intake/mint", response_model=IntakeMintResponse)
def post_intake_mint(
    payload: IntakeMintRequest,
    request: Request,
    trainer_id: str = Depends(forbid_demo_trainer),
) -> IntakeMintResponse:
    """Trainer mints a fresh intake token for a prospective client.

    The token isn't tied to a client_id yet — that gets stamped on
    submission via consume_intake_token. Multiple live intake tokens
    per trainer are fine; each is one-shot, so re-issuing one because
    a client never filled the first form doesn't leak anything (the
    first token still expires on its own at 14 days).

    Rate-limited per trainer (see INTAKE_MINT_LIMIT) — same posture as
    SHARE_MINT_LIMIT, the real failure case is an accidental
    click-loop minting dozens of tokens, not adversarial use.
    """
    enforce(INTAKE_MINT_LIMIT, trainer_id)
    client_ip = request.client.host if request.client else None
    try:
        with connect(DEFAULT_DB_PATH, read_only=False) as con:
            token, expires_at = create_intake_token(
                con,
                trainer_id=trainer_id,
                trainer_message=payload.trainer_message,
            )
            # Audit on mint so an "I sent this link" event is on record
            # even if the client never submits — useful for triaging
            # "I sent it last week, did they fill it in?" without
            # waiting on a downstream signal.
            record_audit(
                con,
                trainer_id,
                "intake.minted",
                target_type="intake_token",
                target_id=token[:12],  # prefix only — the full token is the secret
                details={"expires_at": expires_at.isoformat()},
                ip=client_ip,
            )
    except ValueError as e:
        # create_intake_token raises ValueError if the trainer_id has
        # no trainers row. With forbid_demo_trainer in front of us
        # that's essentially unreachable in production, but better a
        # 400 here than a silent dangling token.
        raise HTTPException(status_code=400, detail=str(e)) from e
    except duckdb.IOException as e:
        raise HTTPException(status_code=503, detail=f"DB busy: {e}") from e

    return IntakeMintResponse(token=token, expires_at=expires_at)


@router.get("/api/intake/{token}", response_model=IntakeViewResponse)
def get_intake(
    token: str,
    con=Depends(read_only_conn),
) -> IntakeViewResponse:
    """Public preflight for the intake form page.

    No session cookie, no trainer header — the token's presence is
    the entire authorization. Returns the data the public form page
    needs to render its header ("Intake for {trainer_name}" + the
    optional welcome message) plus the token state so the page can
    decide whether to render the form, an "already submitted"
    confirmation, or a "this link expired" message.

    Status posture matches share.py:
      - 404  token unknown
      - 410  expired (was usable, now gone)
      - 200  with ``consumed=True``  already submitted (keeps the
             trainer name in the payload so the page can render a
             personalized confirmation rather than a generic 410)
      - 200  with ``consumed=False`` → render the form
    """
    record = intake_lookup(con, token)
    if not record:
        raise HTTPException(status_code=404, detail="Intake link not found")
    if record["expired"]:
        raise HTTPException(status_code=410, detail="Intake link has expired")

    trainer_row = con.execute(
        "SELECT name FROM trainers WHERE id = ?",
        [record["trainer_id"]],
    ).fetchone()
    if not trainer_row:
        # Trainer was deleted after the token was minted. Treat as
        # expired from the public POV — there's no roster to land in.
        raise HTTPException(status_code=410, detail="Intake link has expired")

    return IntakeViewResponse(
        trainer_name=trainer_row[0],
        trainer_message=record["trainer_message"],
        expires_at=record["expires_at"],
        consumed=record["consumed"],
    )


@router.post("/api/intake/{token}")
def post_intake(
    token: str,
    payload: ClientCreate,
    request: Request,
) -> dict:
    """Public form submission. Atomically inserts the new client row
    and consumes the token in one transaction so a race-lost
    submission doesn't leave a stranded client behind.

    Order of operations:
      1. Per-IP rate limit (defends against form-spam against a
         leaked link before consume kicks in).
      2. Pre-flight intake_lookup on a write connection — same
         conditions as GET but we map "consumed" to 410 here because
         the submit verb is meaningless on a used-up token.
      3. BEGIN TRANSACTION; insert client; consume_intake_token.
         If consume returns False (lost the race to a concurrent
         submission), ROLLBACK and 410. Otherwise audit + COMMIT.

      consume_intake_token's WHERE clause also rejects expired
      tokens, so even if a future change to the precheck regressed
      the expiry path, the helper still won't claim an expired row.
      Defense in depth.

    Rate-limit identity is the client IP (request.client.host) — the
    trainer isn't known until intake_lookup runs, and even then
    rate-limiting per trainer wouldn't help (the threat is form-spam
    from one source, not one trainer's tokens being abused).
    """
    client_ip = request.client.host if request.client else "unknown"
    enforce(INTAKE_SUBMIT_LIMIT, client_ip)

    try:
        with connect(DEFAULT_DB_PATH, read_only=False) as con:
            record = intake_lookup(con, token)
            if not record:
                raise HTTPException(status_code=404, detail="Intake link not found")
            if record["expired"]:
                raise HTTPException(status_code=410, detail="Intake link has expired")
            if record["consumed"]:
                raise HTTPException(
                    status_code=410,
                    detail="This intake form has already been submitted",
                )

            trainer_id = record["trainer_id"]

            con.execute("BEGIN TRANSACTION")
            client_id = insert_client_from_payload(con, trainer_id, payload)
            claimed = consume_intake_token(con, token, client_id)
            if not claimed:
                # Lost the race to a concurrent submission between
                # intake_lookup above and consume here. Roll back the
                # insert so we don't leave a stranded client row.
                con.execute("ROLLBACK")
                raise HTTPException(
                    status_code=410,
                    detail="This intake form has already been submitted",
                )
            record_audit(
                con,
                trainer_id,
                "intake.submitted",
                target_type="client",
                target_id=client_id,
                details={
                    "intake_token_prefix": token[:12],
                    "name": payload.name,
                },
                ip=client_ip,
            )
            con.execute("COMMIT")
    except HTTPException:
        raise
    except duckdb.IOException as e:
        raise HTTPException(status_code=503, detail=f"DB busy: {e}") from e

    return {"ok": True, "id": client_id}
