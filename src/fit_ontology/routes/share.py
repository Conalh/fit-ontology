"""Share tokens — trainer mints, client reads (no auth).

Two endpoints, deliberately split by auth surface:

  POST /api/clients/{client_id}/share   trainer-scoped; mints a token
  GET  /api/share/{token}               PUBLIC; renders the client view

The public route is the only endpoint in the app that does NOT go
through ``current_trainer_id``. Its scoping is "the bearer of this
token can see exactly the rows linked to it" — which is enforced
in the share_lookup helper itself.

What the public payload includes (intentionally minimal):
  - client's first name (for personalization)
  - this week's verdict + recommendation + rationale
  - this week's recovery score
  - this week's plan (slot titles + targets, no executed-session ids)
  - the trainer's note attached to the token
  - expires_at, so the front-end can warn "this link expires soon"

What it EXCLUDES (PII the client doesn't need from a share URL):
  - sex, age, height, weight
  - injury history
  - other clients' anything
  - raw wearable metric rows
  - decision history / overrides
  - per-client thresholds
"""
from __future__ import annotations

from datetime import date, timedelta

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Request

from ..db import (
    DEFAULT_DB_PATH,
    SHARE_TTL_DAYS_DEFAULT,
    connect,
    create_share_token,
    metrics_for_client,
    plan_for_week,
    recommendation_for_week,
    record_audit,
    sessions_for_client,
    share_lookup,
    thresholds_for_client,
)
from ..rate_limit import SHARE_MINT_LIMIT, enforce
from ..reasoning import compute_recovery_score, generate_recommendation
from .deps import forbid_demo_trainer, read_only_conn
from .schemas import (
    ShareCreateRequest,
    ShareCreateResponse,
    SharePlannedSession,
    ShareViewResponse,
)

router = APIRouter()


@router.post("/api/clients/{client_id}/share", response_model=ShareCreateResponse)
def post_share(
    client_id: str,
    payload: ShareCreateRequest,
    request: Request,
    trainer_id: str = Depends(forbid_demo_trainer),
) -> ShareCreateResponse:
    """Trainer mints a fresh token for one of their clients. Multiple
    live tokens per client are fine — re-issuing doesn't revoke the
    old one. To kill a leaked link before its natural expiry, use the
    revoke endpoint (not in this slice; tokens just expire on their
    own at 14 days).

    Rate-limited per trainer (see rate_limit.SHARE_MINT_LIMIT) — the
    real case is an accidental double-bound button minting 50 tokens
    when the trainer clicked once.
    """
    enforce(SHARE_MINT_LIMIT, trainer_id)
    client_ip = request.client.host if request.client else None
    try:
        with connect(DEFAULT_DB_PATH, read_only=False) as con:
            token, expires_at = create_share_token(
                con,
                trainer_id=trainer_id,
                client_id=client_id,
                trainer_message=payload.trainer_message,
                ttl_days=SHARE_TTL_DAYS_DEFAULT,
            )
            record_audit(
                con,
                trainer_id,
                "share.minted",
                target_type="client",
                target_id=client_id,
                details={"expires_at": expires_at.isoformat()},
                ip=client_ip,
            )
    except ValueError as e:
        # create_share_token raises ValueError when the client doesn't
        # belong to this trainer — same shape as a missing client.
        raise HTTPException(status_code=404, detail=str(e)) from e
    except duckdb.IOException as e:
        raise HTTPException(status_code=503, detail=f"DB busy: {e}") from e

    return ShareCreateResponse(token=token, expires_at=expires_at)


@router.get("/api/share/{token}", response_model=ShareViewResponse)
def get_share(
    token: str,
    con=Depends(read_only_conn),
) -> ShareViewResponse:
    """Public read. No session cookie, no trainer header. The token's
    presence is the entire authorization."""
    record = share_lookup(con, token)
    if not record:
        raise HTTPException(status_code=404, detail="Share link not found")
    if record["expired"]:
        # 410 Gone — the resource existed but is intentionally no
        # longer available. Lets the front-end show a "this link
        # expired" message rather than the generic "not found."
        raise HTTPException(status_code=410, detail="Share link has expired")

    trainer_id = record["trainer_id"]
    client_id = record["client_id"]

    # Pull the client row (just the name — PII fields stay server-side).
    row = con.execute(
        "SELECT name FROM clients WHERE id = ? AND trainer_id = ?",
        [client_id, trainer_id],
    ).fetchone()
    if not row:
        # Client was deleted after the token was minted. Treat as
        # expired from the public POV.
        raise HTTPException(status_code=410, detail="Share link has expired")
    full_name = row[0]
    first_name = full_name.split(" ", 1)[0] if full_name else "you"

    # Current week's verdict — same logic as the dashboard's
    # /recommendation endpoint, but read-only and without
    # lazy-persisting (the dashboard's POST writes are the canonical
    # path; the share view should never create rows).
    today = date.today()
    week_of = today - timedelta(days=today.weekday())

    stored = recommendation_for_week(con, trainer_id, client_id, week_of)
    metrics = metrics_for_client(con, trainer_id, client_id, days=35)
    sessions = sessions_for_client(con, trainer_id, client_id, days=35)
    overrides = thresholds_for_client(con, trainer_id, client_id)

    if stored is not None:
        rec_text = stored.recommendation
        rec_rationale = stored.rationale
        confidence = stored.confidence
    else:
        rec = generate_recommendation(client_id, metrics, sessions, thresholds=overrides)
        rec_text = rec.recommendation
        rec_rationale = rec.rationale
        confidence = rec.confidence

    score = compute_recovery_score(metrics, sessions, today=today, thresholds=overrides)
    recovery = {
        "composite": score.composite,
        "hrv": score.hrv,
        "sleep": score.sleep,
        "rhr": score.rhr,
        "acwr": score.acwr,
    }

    plan_rows = plan_for_week(con, trainer_id, client_id, week_of)
    plan = [
        SharePlannedSession(
            slot=ps.slot,
            type=ps.type.value if hasattr(ps.type, "value") else str(ps.type),
            title=ps.title,
            description=ps.description,
            target_duration_min=ps.target_duration_min,
            target_rpe=ps.target_rpe,
            done=ps.executed_session_id is not None,
        )
        for ps in plan_rows
    ]

    return ShareViewResponse(
        client_first_name=first_name,
        week_of=week_of,
        recommendation=rec_text,
        rationale=rec_rationale,
        confidence=confidence,
        recovery_score=recovery,
        plan=plan,
        trainer_message=record["trainer_message"],
        expires_at=record["expires_at"],
    )
