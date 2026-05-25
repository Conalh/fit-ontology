"""Coach Assistant draft endpoint — Phase 7a.

POST /api/clients/{client_id}/coach-message/draft

Trainer-scoped, rate-limited, audited. Assembles this week's data
from the existing helpers, hands it to coach_draft.draft_coach_message,
returns plain text. The trainer reviews + edits + sends through the
existing PDF / share-link surface; this endpoint does not deliver
the message anywhere on its own.
"""
from __future__ import annotations

from datetime import date, timedelta

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Request

from ..coach_draft import (
    DEFAULT_MODEL as COACH_DEFAULT_MODEL,
)
from ..coach_draft import (
    build_coach_draft_payload,
    draft_coach_message,
)
from ..db import (
    DEFAULT_DB_PATH,
    connect,
    metrics_for_client,
    overrides_for_client,
    plan_for_week,
    recommendation_for_week,
    record_audit,
    sessions_for_client,
    thresholds_for_client,
)
from ..rate_limit import COACH_DRAFT_LIMIT, enforce
from ..reasoning import compute_recovery_score, generate_recommendation
from .deps import current_trainer_id
from .schemas import CoachDraftResponse

router = APIRouter()


@router.post("/api/clients/{client_id}/coach-message/draft",
             response_model=CoachDraftResponse)
def post_coach_draft(
    client_id: str,
    request: Request,
    trainer_id: str = Depends(current_trainer_id),
) -> CoachDraftResponse:
    """Draft a 2-3 sentence check-in for this client based on this
    week's data. Returns the draft text — the trainer reviews,
    edits, and decides where to send it from.

    Manages its own connection lifecycle (rather than depending on
    read_only_conn) because we need to follow the read with a write
    for the audit row, and DuckDB rejects mixed read+write opens on
    the same DB file in the same process. Close the reader before
    we open the writer.
    """
    enforce(COACH_DRAFT_LIMIT, trainer_id)

    today = date.today()
    week_of = today - timedelta(days=today.weekday())

    # ── Gather phase (read-only) ──
    with connect(DEFAULT_DB_PATH, read_only=True) as rcon:
        row = rcon.execute(
            "SELECT name, goal FROM clients WHERE id = ? AND trainer_id = ?",
            [client_id, trainer_id],
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"No client with id {client_id}")
        client_name, client_goal = row

        # Verdict + rationale — prefer the persisted recommendation
        # for this week so the draft reflects the same call the
        # trainer is looking at on screen.
        stored = recommendation_for_week(rcon, trainer_id, client_id, week_of)
        metrics = metrics_for_client(rcon, trainer_id, client_id, days=35)
        sessions = sessions_for_client(rcon, trainer_id, client_id, days=35)
        thresh = thresholds_for_client(rcon, trainer_id, client_id)
        if stored is not None:
            rec_text = stored.recommendation
            rec_rationale = stored.rationale
            confidence = stored.confidence
        else:
            rec = generate_recommendation(client_id, metrics, sessions, thresholds=thresh)
            rec_text = rec.recommendation
            rec_rationale = rec.rationale
            confidence = rec.confidence

        score = compute_recovery_score(metrics, sessions, today=today, thresholds=thresh)

        # Plan adherence for THIS week only. Different from
        # calibration's all-clients-all-time view — Claude needs
        # "what's going on this week with this client," not
        # historical aggregates.
        plan_rows = plan_for_week(rcon, trainer_id, client_id, week_of)
        if plan_rows:
            total_slots = len(plan_rows)
            matched_slots = sum(1 for p in plan_rows if p.executed_session_id is not None)
            plan_adherence = {
                "total_slots": total_slots,
                "matched_slots": matched_slots,
                "match_rate": round(matched_slots / total_slots, 2) if total_slots else None,
            }
        else:
            plan_adherence = None

        # Recent overrides — strip down to (action, week, note) so the
        # prompt isn't bloated with system_recommendation snapshots
        # the model can already infer from rec_text.
        raw_overrides = overrides_for_client(rcon, trainer_id, client_id, limit=3)

    recovery = {
        "composite": score.composite,
        "hrv": score.hrv,
        "sleep": score.sleep,
        "rhr": score.rhr,
        "acwr": score.acwr,
    }
    recent_overrides: list[dict] = []
    if not raw_overrides.empty:
        for _, ov in raw_overrides.iterrows():
            note = ov.get("trainer_note")
            recent_overrides.append({
                "week_of": str(ov["week_of"]),
                "action": ov["trainer_action"],
                "note": note if (note is not None and str(note).strip()) else None,
            })

    payload = build_coach_draft_payload(
        client_name=client_name,
        client_goal=client_goal,
        recommendation=rec_text,
        rationale=rec_rationale,
        confidence=confidence,
        recovery_score=recovery,
        plan_adherence=plan_adherence,
        recent_overrides=recent_overrides,
    )

    # ── Network phase (no DB connection held) ──
    try:
        result = draft_coach_message(payload, model=COACH_DEFAULT_MODEL)
    except RuntimeError as e:
        # ANTHROPIC_API_KEY missing — same 412 contract as /ask.
        raise HTTPException(status_code=412, detail=str(e)) from e

    # ── Audit phase (write) ──
    # Best-effort — don't fail the draft because the audit write
    # contended (the trainer's already got the text, the rate limit
    # already capped the action).
    client_ip = request.client.host if request.client else None
    try:
        with connect(DEFAULT_DB_PATH, read_only=False) as wcon:
            record_audit(
                wcon, trainer_id, "coach.drafted",
                target_type="client", target_id=client_id,
                details={"model": result.model, "week_of": week_of.isoformat()},
                ip=client_ip,
            )
    except duckdb.IOException:
        pass

    return CoachDraftResponse(draft=result.draft, model=result.model)
