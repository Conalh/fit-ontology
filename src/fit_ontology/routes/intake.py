"""Intake tokens — trainer mints, prospective client submits (no auth).

Phase 3b. The inbound counterpart to ``share.py``: that one is outbound
(trainer publishes a read-only weekly view); this one is inbound
(prospective client opens a URL, fills the form, and the submission
inserts their row into the trainer's roster scoped to the token's
trainer_id).

M2 milestone — trainer-side only. The public lookup + submit endpoints
land in M3 alongside their tests:

  POST /api/clients/intake/mint   trainer-scoped; mints a one-shot token
  GET  /api/intake/{token}        (M3) PUBLIC; renders form preconditions
  POST /api/intake/{token}        (M3) PUBLIC; submits + atomically
                                  consumes the token + inserts the client

The mint endpoint is rate-limited (INTAKE_MINT_LIMIT) and demo-trainer-
forbidden (a hosted-demo visitor can't mint links that would create
real clients under the t_demo trainer). Every mint writes an
``intake.minted`` audit row so the trainer can reconcile "I sent N
links" against "N clients arrived" in the audit log.
"""
from __future__ import annotations

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Request

from ..db import (
    DEFAULT_DB_PATH,
    connect,
    create_intake_token,
    record_audit,
)
from ..rate_limit import INTAKE_MINT_LIMIT, enforce
from .deps import forbid_demo_trainer
from .schemas import IntakeMintRequest, IntakeMintResponse

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
