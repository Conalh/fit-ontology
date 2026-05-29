"""Weekly plan: structured sessions derived from the recommendation."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Request

from ..contraindications import match_contraindications
from ..db import (
    DEFAULT_DB_PATH,
    connect,
    insert_plan,
    latest_override_for_week,
    match_planned_sessions,
    metrics_for_client,
    plan_for_week,
    recommendation_for_week,
    record_audit,
    sessions_for_client,
    thresholds_for_client,
    upsert_planned_session,
)
from ..demo import is_demo_trainer
from ..ontology import PlanSource, SessionType
from ..planning import Verdict, generate_plan
from ..reasoning import generate_recommendation
from .deps import current_trainer_id, forbid_demo_trainer, real_client_ip
from .schemas import PlannedSessionPatch, PlannedSessionResponse, PlanResponse

router = APIRouter()


def _client_injury_history_or_404(con, trainer_id: str, client_id: str) -> str | None:
    row = con.execute(
        "SELECT injury_history FROM clients WHERE id = ? AND trainer_id = ?",
        [client_id, trainer_id],
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"No client with id {client_id}")
    return row[0]


def _classify_verdict(rec_text: str) -> Verdict:
    """Map the recommendation's text-prefixed first word to a verdict
    enum. Same shape as routes.helpers.classify_rec but returns the
    planning module's verdict literals (uppercase) rather than the UI
    display strings."""
    low = rec_text.lower()
    if low.startswith("deload"):
        return "DELOAD"
    if low.startswith("conservative"):
        return "CONSERVATIVE"
    return "STANDARD"


def _trainer_override_verdict(row) -> Verdict | None:
    """Return the trainer's explicit current-week verdict when present.

    Legacy override rows predate ``trainer_recommendation`` and only carry
    accept/edit/reject, so they deliberately fall back to the system verdict
    rather than reintroducing the old lossy opposite-verdict inference.
    """
    if row.empty:
        return None
    raw = row.iloc[0].get("trainer_recommendation")
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text.lower() == "nan":
        return None
    return _classify_verdict(text)


@router.get("/api/clients/{client_id}/plan", response_model=PlanResponse)
def get_plan(
    client_id: str,
    trainer_id: str = Depends(current_trainer_id),
) -> PlanResponse:
    """Return the current week's plan, lazy-persisting on first fetch.

    Mirrors the recommendation route's pattern: read first (closing the
    read connection), then write only if the plan hasn't been persisted
    yet. Once written, subsequent reads return the same row even if the
    trainer's editing decision (or the underlying verdict) drifts —
    that's the whole point of plan persistence.
    """
    today = date.today()
    week_of = today - timedelta(days=today.weekday())  # Monday

    plan: list = []
    verdict: Verdict = "STANDARD"
    needs_persist = False
    new_plan = None

    with connect(DEFAULT_DB_PATH, read_only=True) as rcon:
        injury = _client_injury_history_or_404(rcon, trainer_id, client_id)
        plan = plan_for_week(rcon, trainer_id, client_id, week_of)
        # We also need the verdict for the response, regardless of
        # whether the plan is fresh or cached. Look up the persisted
        # recommendation if there is one; otherwise compute inline so
        # we have a verdict to drive generation.
        rec = recommendation_for_week(rcon, trainer_id, client_id, week_of)
        if rec is None:
            metrics = metrics_for_client(rcon, trainer_id, client_id, days=70)
            sessions = sessions_for_client(rcon, trainer_id, client_id, days=35)
            overrides = thresholds_for_client(rcon, trainer_id, client_id)
            rec = generate_recommendation(client_id, metrics, sessions, thresholds=overrides)
        verdict = _classify_verdict(rec.recommendation)
        override_verdict = _trainer_override_verdict(
            latest_override_for_week(rcon, trainer_id, client_id, week_of)
        )
        if override_verdict is not None:
            verdict = override_verdict

        if not plan:
            # Generate the initial plan from the verdict + recent
            # sessions + injury-derived contraindications.
            sessions = sessions_for_client(rcon, trainer_id, client_id, days=35)
            ci_phrases = [c.advice for c in match_contraindications(injury)]
            new_plan = generate_plan(
                client_id=client_id,
                week_of=week_of,
                verdict=verdict,
                sessions=sessions,
                contraindications=ci_phrases,
                today=today,
            )
            needs_persist = True

    # Demo trainer: skip ALL writes. The visitor gets a freshly
    # generated plan rendered in memory but nothing lands in the DB.
    # Avoids: writer-lock contention on every demo visitor, audit-log
    # noise, demo-data drift across visits.
    if is_demo_trainer(trainer_id):
        return PlanResponse(
            week_of=week_of,
            verdict=verdict,
            sessions=[_to_response(ps) for ps in (new_plan or plan)],
        )

    if needs_persist and new_plan:
        try:
            with connect(DEFAULT_DB_PATH, read_only=False) as wcon:
                insert_plan(wcon, trainer_id, new_plan)
                # Plan just got created — any sessions already logged
                # this week should retroactively link to their slots.
                match_planned_sessions(wcon, trainer_id, client_id)
                # Re-read to pick up executed_session_id values the
                # matcher just wrote.
                plan = plan_for_week(wcon, trainer_id, client_id, week_of)
        except (duckdb.IOException, duckdb.ConnectionException):
            # Client-detail renders fan out several read queries in parallel.
            # If one is still open, DuckDB can refuse a write-mode handle.
            # Return the generated plan in memory; a later GET will persist it.
            plan = new_plan
    else:
        # Plan already existed — opportunistically run the matcher in
        # case sessions landed since last fetch. Cheap (LEFT JOIN with an
        # index) and ensures the UI always shows current execution status.
        try:
            with connect(DEFAULT_DB_PATH, read_only=False) as wcon:
                linked = match_planned_sessions(wcon, trainer_id, client_id)
                if linked > 0:
                    plan = plan_for_week(wcon, trainer_id, client_id, week_of)
        except (duckdb.IOException, duckdb.ConnectionException):
            # Background match failed — not fatal, just skip the refresh.
            pass

    return PlanResponse(
        week_of=week_of,
        verdict=verdict,
        sessions=[_to_response(ps) for ps in plan],
    )


@router.patch(
    "/api/clients/{client_id}/plan/{slot}",
    response_model=PlannedSessionResponse,
)
def patch_planned_session(
    client_id: str,
    slot: int,
    payload: PlannedSessionPatch,
    request: Request,
    trainer_id: str = Depends(forbid_demo_trainer),
) -> PlannedSessionResponse:
    """Edit one slot of the current week's plan. Any patch flips the
    row's source to "trainer" — once the trainer has touched a slot,
    re-generating the plan must never overwrite their decision."""
    today = date.today()
    week_of = today - timedelta(days=today.weekday())

    # Load the existing slot so we can apply partial updates.
    with connect(DEFAULT_DB_PATH, read_only=True) as rcon:
        _client_injury_history_or_404(rcon, trainer_id, client_id)
        plan = plan_for_week(rcon, trainer_id, client_id, week_of)
    existing = next((p for p in plan if p.slot == slot), None)
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail=f"No planned session at slot {slot} for week {week_of.isoformat()}",
        )

    # Build the updated session in memory before writing — partial-update
    # logic stays here rather than in SQL so we get type validation through
    # the dataclass on the way in.
    updated_type = existing.type
    if payload.type is not None:
        try:
            updated_type = SessionType(payload.type)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown session type: {payload.type!r}",
            ) from e

    existing.type = updated_type
    if payload.title is not None:
        existing.title = payload.title
    if payload.description is not None:
        existing.description = payload.description
    if payload.target_duration_min is not None:
        existing.target_duration_min = payload.target_duration_min
    if payload.target_load_au is not None:
        existing.target_load_au = payload.target_load_au
    if payload.target_rpe is not None:
        existing.target_rpe = payload.target_rpe
    existing.source = PlanSource.TRAINER
    existing.generated_at = datetime.now()

    client_ip = real_client_ip(request)
    # Capture which fields the trainer actually touched so the audit
    # row reflects the edit rather than the whole post-edit blob.
    touched = sorted(payload.model_dump(exclude_none=True).keys())
    try:
        with connect(DEFAULT_DB_PATH, read_only=False) as wcon:
            upsert_planned_session(wcon, trainer_id, existing)
            record_audit(
                wcon, trainer_id, "plan.edited",
                target_type="client", target_id=client_id,
                details={"slot": slot, "week_of": existing.week_of.isoformat(),
                         "fields": touched},
                ip=client_ip,
            )
    except duckdb.IOException as e:
        raise HTTPException(status_code=503, detail=f"DB busy: {e}") from e

    return _to_response(existing)


def _to_response(ps) -> PlannedSessionResponse:
    return PlannedSessionResponse(
        id=ps.id,
        client_id=ps.client_id,
        week_of=ps.week_of,
        slot=ps.slot,
        type=ps.type.value if hasattr(ps.type, "value") else str(ps.type),
        title=ps.title,
        description=ps.description,
        target_duration_min=ps.target_duration_min,
        target_load_au=ps.target_load_au,
        target_rpe=ps.target_rpe,
        contraindications=ps.contraindications,
        source=ps.source.value if hasattr(ps.source, "value") else str(ps.source),
        generated_at=ps.generated_at,
        executed_session_id=ps.executed_session_id,
    )
