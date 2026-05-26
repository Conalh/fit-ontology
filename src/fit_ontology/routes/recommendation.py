"""Weekly recommendation: current week (lazy-persisted) + history."""
from __future__ import annotations

import json

import duckdb
from fastapi import APIRouter, Depends, HTTPException

from ..db import (
    DEFAULT_DB_PATH,
    connect,
    insert_recommendation,
    recommendations_for_client,
    replace_recommendation_for_week,
)
from ..demo import is_demo_trainer
from ..ontology import Recommendation
from ..reasoning import (
    FLAG_CITATIONS,
    compute_trend_diagnostics,
    generate_recommendation,
)
from ..weekly_state import ClientNotFoundError, WeeklyClientState, build_weekly_client_state
from .deps import current_trainer_id, read_only_conn
from .schemas import (
    ContraindicationItem,
    RecommendationPreviewResponse,
    RecommendationResponse,
    RecoveryScoreResponse,
    TrendDetailResponse,
)

router = APIRouter()


def _recommendations_differ(a: Recommendation, b: Recommendation) -> bool:
    return (
        a.recommendation != b.recommendation
        or a.rationale != b.rationale
        or a.source_metric_ids != b.source_metric_ids
        or abs(float(a.confidence) - float(b.confidence)) > 1e-9
    )


def _preview_response(rec: Recommendation) -> RecommendationPreviewResponse:
    return RecommendationPreviewResponse(
        recommendation=rec.recommendation,
        rationale=rec.rationale,
        source_metric_ids=rec.source_metric_ids,
        confidence=rec.confidence,
        generated_at=rec.generated_at,
    )


def _response_from_state(
    state: WeeklyClientState,
    rec: Recommendation,
    *,
    is_locked: bool,
    live_preview: RecommendationPreviewResponse | None = None,
) -> RecommendationResponse:
    contras = [
        ContraindicationItem(kind=c.kind, title=c.title, advice=c.advice, source_phrase=c.source_phrase)
        for c in state.contraindications
    ]

    # Recovery gauge: fresh on every call, not persisted. The verdict
    # carries the weekly decision; this carries today's snapshot.
    score = state.recovery_score
    recovery = RecoveryScoreResponse(
        composite=score.composite,
        hrv=score.hrv,
        sleep=score.sleep,
        rhr=score.rhr,
        acwr=score.acwr,
    )

    # Trend chips are current-state diagnostics. They can drift while
    # the locked recommendation text remains stable.
    trend_diag = compute_trend_diagnostics(state.metrics, state.today, state.thresholds)
    trend_details = {
        kind: TrendDetailResponse(
            kind=d.kind,
            acute_window_days=d.acute_window_days,
            acute_slope_per_day=d.acute_slope_per_day,
            acute_sd_per_day=d.acute_sd_per_day,
            acute_fired=d.acute_fired,
            chronic_window_days=d.chronic_window_days,
            chronic_slope_per_day=d.chronic_slope_per_day,
            chronic_sd_per_day=d.chronic_sd_per_day,
            chronic_fired=d.chronic_fired,
            chronic_confidence_weight=d.chronic_confidence_weight,
        )
        for kind, d in trend_diag.items()
    }

    return RecommendationResponse(
        id=rec.id,
        client_id=rec.client_id,
        week_of=rec.week_of,
        recommendation=rec.recommendation,
        rationale=rec.rationale,
        source_metric_ids=rec.source_metric_ids,
        confidence=rec.confidence,
        generated_at=rec.generated_at,
        contraindications=contras,
        recovery_score=recovery,
        flag_citations=FLAG_CITATIONS,
        trend_details=trend_details,
        is_locked=is_locked,
        live_preview=live_preview,
        preview_differs=live_preview is not None,
    )


@router.get("/api/clients/{client_id}/recommendation", response_model=RecommendationResponse)
def get_recommendation(
    client_id: str,
    trainer_id: str = Depends(current_trainer_id),
) -> RecommendationResponse:
    """Return the current week's recommendation.

    The first non-demo compute is persisted so subsequent lookups stay
    stable. If the persisted row differs from today's live engine output,
    the live output is surfaced as a preview instead of silently replacing
    the trainer-facing weekly snapshot.
    """
    with connect(DEFAULT_DB_PATH, read_only=True) as rcon:
        try:
            state = build_weekly_client_state(rcon, trainer_id, client_id)
        except ClientNotFoundError:
            raise HTTPException(status_code=404, detail=f"No client with id {client_id}") from None

    is_demo = is_demo_trainer(trainer_id)
    is_locked = state.stored_recommendation is not None
    live_preview: RecommendationPreviewResponse | None = None

    if state.recommendation_needs_persist and not is_demo:
        try:
            with connect(DEFAULT_DB_PATH, read_only=False) as wcon:
                insert_recommendation(wcon, trainer_id, state.recommendation)
                is_locked = True
        except (duckdb.IOException, duckdb.ConnectionException):
            # Do not fail the page if the initial lazy persist races another
            # read request. The trainer still gets the live computed verdict;
            # the next GET can lock it once the writer is available.
            is_locked = False
    elif state.stored_recommendation is not None:
        current = generate_recommendation(
            client_id,
            state.metrics,
            state.sessions,
            today=state.today,
            thresholds=state.thresholds,
        )
        if _recommendations_differ(state.stored_recommendation, current):
            live_preview = _preview_response(current)

    return _response_from_state(
        state,
        state.recommendation,
        is_locked=is_locked,
        live_preview=live_preview,
    )


@router.post("/api/clients/{client_id}/recommendation/refresh", response_model=RecommendationResponse)
def refresh_recommendation(
    client_id: str,
    trainer_id: str = Depends(current_trainer_id),
) -> RecommendationResponse:
    """Explicitly replace this week's locked recommendation with a fresh compute."""
    if is_demo_trainer(trainer_id):
        raise HTTPException(status_code=403, detail="Demo trainer cannot refresh recommendations")

    with connect(DEFAULT_DB_PATH, read_only=True) as rcon:
        try:
            state = build_weekly_client_state(rcon, trainer_id, client_id)
        except ClientNotFoundError:
            raise HTTPException(status_code=404, detail=f"No client with id {client_id}") from None

    rec = generate_recommendation(
        client_id,
        state.metrics,
        state.sessions,
        today=state.today,
        thresholds=state.thresholds,
    )
    try:
        with connect(DEFAULT_DB_PATH, read_only=False) as wcon:
            replace_recommendation_for_week(wcon, trainer_id, rec)
    except (duckdb.IOException, duckdb.ConnectionException) as e:
        raise HTTPException(status_code=503, detail=f"DB busy: {e}") from e

    return _response_from_state(state, rec, is_locked=True)


@router.get(
    "/api/clients/{client_id}/recommendations",
    response_model=list[RecommendationResponse],
)
def get_recommendation_history(
    client_id: str,
    limit: int = 12,
    con=Depends(read_only_conn),
    trainer_id: str = Depends(current_trainer_id),
) -> list[RecommendationResponse]:
    """Past weekly recommendations, newest first.

    Contraindications are current intake-derived state, so history rows
    leave them empty. Callers that need current constraints should hit
    /recommendation.
    """
    df = recommendations_for_client(con, trainer_id, client_id, limit=limit)
    if df.empty:
        return []
    out: list[RecommendationResponse] = []
    for _, row in df.iterrows():
        out.append(
            RecommendationResponse(
                id=row["id"],
                client_id=row["client_id"],
                week_of=row["week_of"],
                recommendation=row["recommendation"],
                rationale=row["rationale"],
                source_metric_ids=json.loads(row["source_metric_ids"]) if row.get("source_metric_ids") else [],
                confidence=float(row["confidence"]),
                generated_at=row["generated_at"],
                contraindications=[],
                is_locked=True,
            )
        )
    return out
