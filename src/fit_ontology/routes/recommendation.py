"""Weekly recommendation — current week (lazy-persisted) + history."""
from __future__ import annotations

import json
from datetime import date, timedelta

import duckdb
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException

from ..contraindications import match_contraindications
from ..db import (
    DEFAULT_DB_PATH,
    connect,
    insert_recommendation,
    metrics_for_client,
    recommendation_for_week,
    recommendations_for_client,
    sessions_for_client,
    thresholds_for_client,
)
from ..demo import is_demo_trainer
from ..ontology import MetricKind
from ..reasoning import (
    FLAG_CITATIONS,
    compute_recovery_score,
    compute_trend_slope,
    generate_recommendation,
)
from .deps import current_trainer_id, read_only_conn
from .schemas import (
    ContraindicationItem,
    RecommendationResponse,
    RecoveryScoreResponse,
    TrendExplain,
    TrendExplainEntry,
    TrendSignalDetail,
)

router = APIRouter()


@router.get("/api/clients/{client_id}/recommendation", response_model=RecommendationResponse)
def get_recommendation(
    client_id: str,
    explain_trend: bool = False,
    trainer_id: str = Depends(current_trainer_id),
) -> RecommendationResponse:
    """Return the recommendation for the current week, persisting it on
    first compute so subsequent lookups are stable.

    Why lazy-persist rather than overwrite-on-every-render: the trainer
    needs the rec they saw on Monday to still read the same way on
    Wednesday when they override it. New wearable data arriving
    mid-week shouldn't silently change what the system "said" this
    week — the override log already captures the moment-of-decision
    snapshot, and the persisted recommendation is the canonical
    "what the system said this week" record.

    Connection lifecycle: we manage our own here rather than taking
    the read-only dependency, because if the rec for this week hasn't
    been persisted yet we need to open a write connection. DuckDB
    refuses to open write while any read handle is alive in the same
    process, so we read first (closing the connection), then write.
    """
    today = date.today()
    week_of = today - timedelta(days=today.weekday())  # Monday

    needs_persist = False
    rec = None
    injury: str | None = None
    # We always need the current metrics + sessions for the live recovery
    # gauge, whether or not the verdict itself was already persisted.
    metrics: pd.DataFrame | None = None
    sessions: pd.DataFrame | None = None
    overrides: dict | None = None

    with connect(DEFAULT_DB_PATH, read_only=True) as rcon:
        stored = recommendation_for_week(rcon, trainer_id, client_id, week_of)
        injury_row = rcon.execute(
            "SELECT injury_history FROM clients WHERE id = ? AND trainer_id = ?",
            [client_id, trainer_id],
        ).fetchone()
        if injury_row is None:
            raise HTTPException(status_code=404, detail=f"No client with id {client_id}")
        injury = injury_row[0]

        metrics = metrics_for_client(rcon, trainer_id, client_id, days=35)
        sessions = sessions_for_client(rcon, trainer_id, client_id, days=35)
        overrides = thresholds_for_client(rcon, trainer_id, client_id)

        if stored is not None:
            rec = stored
        else:
            rec = generate_recommendation(client_id, metrics, sessions, thresholds=overrides)
            needs_persist = True

    # Demo trainer: skip the persist branch. Visitor gets a freshly
    # computed verdict rendered in memory, no row lands in the DB,
    # no writer-lock contention from demo traffic.
    if needs_persist and not is_demo_trainer(trainer_id):
        try:
            with connect(DEFAULT_DB_PATH, read_only=False) as wcon:
                insert_recommendation(wcon, trainer_id, rec)
        except duckdb.IOException as e:
            raise HTTPException(status_code=503, detail=f"DB busy: {e}") from e

    contras = [
        ContraindicationItem(kind=c.kind, title=c.title, advice=c.advice, source_phrase=c.source_phrase)
        for c in match_contraindications(injury)
    ]

    # Recovery gauge — fresh on every call, not persisted. The verdict
    # carries the Monday-morning decision; this carries today's snapshot.
    score = compute_recovery_score(metrics, sessions, today=today, thresholds=overrides)
    recovery = RecoveryScoreResponse(
        composite=score.composite,
        hrv=score.hrv,
        sleep=score.sleep,
        rhr=score.rhr,
        acwr=score.acwr,
    )

    # E2 debug payload — only computed when explicitly asked for via
    # ?explain_trend=1. Surfaces both detectors (7-day OLS acute + 28-
    # day EWMA chronic) side-by-side for each of HRV/RHR/sleep so
    # threshold tuning in E3 can be data-driven. Verdict logic is
    # unchanged by E2; this is purely diagnostic and gets removed in
    # E4 once the chronic path is wired into the verdict combiner.
    trend_explain = _build_trend_explain(metrics, today) if explain_trend else None

    assert rec is not None  # for type-checkers; the branches above both set it
    return RecommendationResponse(
        id=rec.id, client_id=rec.client_id, week_of=rec.week_of,
        recommendation=rec.recommendation, rationale=rec.rationale,
        source_metric_ids=rec.source_metric_ids, confidence=rec.confidence,
        generated_at=rec.generated_at,
        contraindications=contras,
        recovery_score=recovery,
        flag_citations=FLAG_CITATIONS,
        trend_explain=trend_explain,
    )


def _build_trend_explain(metrics: pd.DataFrame, today: date) -> TrendExplain:
    """Build the E2 debug payload — both detectors' output for HRV,
    resting HR, and sleep hours. Helper kept route-local because the
    payload format is route-specific (verdict-builder doesn't need
    these structured shapes) and the lifecycle is short (gone in E4)."""
    return TrendExplain(
        hrv=_explain_one(metrics, MetricKind.HRV_RMSSD.value, today),
        rhr=_explain_one(metrics, MetricKind.RESTING_HR.value, today),
        sleep=_explain_one(metrics, MetricKind.SLEEP_HOURS.value, today),
    )


def _explain_one(metrics: pd.DataFrame, kind: str, today: date) -> TrendExplainEntry:
    """Compute acute (OLS@7d) + chronic (EWMA@28d) for a single signal
    kind, plus the baseline_sd both share for normalization."""
    # Lazy imports — both helpers live in reasoning.py and the route
    # already imports compute_trend_slope; pulling _baseline + _hrv_kind
    # here keeps the route's import block focused on what generate_-
    # recommendation actually needs at runtime.
    from ..reasoning import _baseline

    # For HRV the engine picks RMSSD-or-SDNN; for the debug payload we
    # use whatever's stored under the requested kind verbatim so the
    # numbers match what a developer would inspect manually.
    acute = compute_trend_slope(metrics, kind, today, method="ols", window_days=7)
    chronic = compute_trend_slope(metrics, kind, today, method="ewma", window_days=28)
    _, baseline_sd, _ = _baseline(metrics, kind, today, 28)

    def _detail(r) -> TrendSignalDetail | None:
        if r is None:
            return None
        sd = abs(r.slope_per_day) / baseline_sd if baseline_sd else None
        return TrendSignalDetail(
            method=r.method,
            window_days=r.window_days,
            slope_per_day=r.slope_per_day,
            n_samples=r.n_samples,
            confidence_weight=r.confidence_weight,
            sd_per_day=sd,
        )

    return TrendExplainEntry(
        kind=kind,
        baseline_sd=baseline_sd,
        acute=_detail(acute),
        chronic=_detail(chronic),
    )


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
    """Past weekly recommendations, newest first. Contraindications
    are not historical — they're derived from the current intake — so
    each row's ``contraindications`` field is the empty list. Callers
    that need contraindications should hit /recommendation for the
    current week."""
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
            )
        )
    return out
