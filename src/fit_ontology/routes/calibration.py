"""Override audit + rule-based tuning suggestions."""
from __future__ import annotations

import duckdb
import pandas as pd
from fastapi import APIRouter, Depends

from ..db import all_overrides
from .deps import read_only_conn
from .helpers import classify_rec, override_response
from .schemas import (
    CalibrationResponse,
    CalibrationSuggestion,
    ConfidenceBucket,
    PerClientAgreement,
    WeeklyAgreement,
)

router = APIRouter()


@router.get("/api/calibration", response_model=CalibrationResponse)
def get_calibration(con=Depends(read_only_conn)) -> CalibrationResponse:
    df = all_overrides(con, limit=1000)
    if df.empty:
        return CalibrationResponse(
            total=0, accept_rate=0.0, edits=0, rejects=0, matrix={}, recent=[],
            by_week=[], by_client=[], suggestions=[],
        )

    df = df.copy()
    df["system_type"] = df["system_recommendation"].apply(classify_rec)

    total = len(df)
    accept_n = int((df["trainer_action"] == "accept").sum())
    edit_n = int((df["trainer_action"] == "edit").sum())
    reject_n = int((df["trainer_action"] == "reject").sum())

    matrix: dict[str, dict[str, int]] = {}
    for system_type, group in df.groupby("system_type"):
        action_counts = group["trainer_action"].value_counts().to_dict()
        matrix[str(system_type)] = {str(k): int(v) for k, v in action_counts.items()}

    recent = [override_response(row) for row in df.head(25).to_dict(orient="records")]

    by_week = _build_weekly_agreement(df)
    by_client = _build_per_client_agreement(con, df)
    suggestions = _build_suggestions(df)
    confidence_audit = _build_confidence_audit(con)

    return CalibrationResponse(
        total=total,
        accept_rate=accept_n / total if total else 0.0,
        edits=edit_n,
        rejects=reject_n,
        matrix=matrix,
        recent=recent,
        by_week=by_week,
        by_client=by_client,
        suggestions=suggestions,
        confidence_audit=confidence_audit,
    )


def _build_confidence_audit(con) -> list[ConfidenceBucket]:
    """Bucket persisted recommendations by their stated confidence and
    compute the rate at which the trainer accepted them.

    Inner-join semantics: we only count weeks where both a persisted
    recommendation and a trainer decision exist. Weeks the trainer
    hasn't ruled on yet are excluded — we don't know what they'll do.

    Window-function pick on the override side: if a trainer edited the
    same week twice we count their most recent action, not the first.
    """
    try:
        df = con.execute(
            """
            SELECT r.confidence, o.trainer_action
            FROM recommendations r
            INNER JOIN (
                SELECT client_id, week_of, trainer_action,
                       ROW_NUMBER() OVER (
                           PARTITION BY client_id, week_of
                           ORDER BY created_at DESC
                       ) AS rn
                FROM recommendation_overrides
            ) o
            ON r.client_id = o.client_id AND r.week_of = o.week_of
            WHERE o.rn = 1
            """,
        ).df()
    except duckdb.CatalogException:
        # Pre-migration DB — recommendations / overrides table may not
        # exist on a fresh install. Return empty buckets; the audit fills
        # in as decisions are logged.
        df = pd.DataFrame(columns=["confidence", "trainer_action"])

    # Fixed bands so the chart shape is comparable week-over-week even as
    # the data fills in. Top bucket includes 1.0 (otherwise a confidence
    # of exactly 1.0 falls out of the audit).
    bands = [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.001)]
    buckets: list[ConfidenceBucket] = []
    for lo, hi in bands:
        mask = (df["confidence"] >= lo) & (df["confidence"] < hi) if not df.empty else None
        rows = df[mask] if mask is not None else df
        n = len(rows)
        accepts = int((rows["trainer_action"] == "accept").sum()) if n else 0
        buckets.append(ConfidenceBucket(
            low=lo,
            high=min(hi, 1.0),
            total=n,
            accepts=accepts,
            accept_rate=accepts / n if n else 0.0,
        ))
    return buckets


def _build_weekly_agreement(df: pd.DataFrame) -> list[WeeklyAgreement]:
    """Group overrides by ``week_of`` and compute the accept rate per
    week. Sorted oldest-first so the front-end can render a left-to-
    right time series."""
    grouped = df.groupby("week_of")
    out: list[WeeklyAgreement] = []
    for week_of, group in grouped:
        total = len(group)
        accepts = int((group["trainer_action"] == "accept").sum())
        out.append(WeeklyAgreement(
            week_of=week_of,
            total=total,
            accepts=accepts,
            accept_rate=accepts / total if total else 0.0,
        ))
    out.sort(key=lambda r: r.week_of)
    return out


def _build_per_client_agreement(con, df: pd.DataFrame) -> list[PerClientAgreement]:
    """Per-client tally. The trainer cares less about aggregate accept
    rate than about which specific client they keep disagreeing with."""
    grouped = df.groupby("client_id")
    rows: list[PerClientAgreement] = []
    # One small SELECT to get names; saves a per-client roundtrip.
    name_map: dict[str, str] = {}
    for client_id in grouped.groups:
        row = con.execute(
            "SELECT name FROM clients WHERE id = ?", [client_id]
        ).fetchone()
        name_map[client_id] = row[0] if row else client_id

    for client_id, group in grouped:
        total = len(group)
        accepts = int((group["trainer_action"] == "accept").sum())
        edits = int((group["trainer_action"] == "edit").sum())
        rejects = int((group["trainer_action"] == "reject").sum())
        rows.append(PerClientAgreement(
            client_id=str(client_id),
            name=name_map.get(str(client_id), str(client_id)),
            total=total,
            accepts=accepts,
            edits=edits,
            rejects=rejects,
            accept_rate=accepts / total if total else 0.0,
        ))
    # Worst-agreement-first so the trainer scans top → calibration gaps.
    rows.sort(key=lambda r: (r.accept_rate, -r.total))
    return rows


def _build_suggestions(df: pd.DataFrame) -> list[CalibrationSuggestion]:
    """Rule-based tuning prompts. These aren't ML; they're explicit
    if/then heuristics the trainer can audit. The "explainable beats
    clever" thesis applies — a trainer who can't reason about why a
    suggestion appeared won't trust it."""
    suggestions: list[CalibrationSuggestion] = []

    # Rule 1: ≥60% of recent (last 5) deload calls were not accepted →
    # HRV thresholds may be too sensitive for this trainer's clients.
    deloads = df[df["system_type"] == "Deload"].sort_values("created_at", ascending=False).head(5)
    if len(deloads) >= 3:
        rejected_or_edited = int(((deloads["trainer_action"] == "reject") | (deloads["trainer_action"] == "edit")).sum())
        if rejected_or_edited / len(deloads) >= 0.6:
            suggestions.append(CalibrationSuggestion(
                kind="threshold_tune",
                severity="warn",
                message=(
                    f"You've pushed back on {rejected_or_edited} of the last {len(deloads)} deload calls. "
                    f"Consider raising hrv_severe_sd or rhr_severe_bpm in the affected clients' threshold panel — "
                    f"your athletes may be more reactive than the population default."
                ),
                target="hrv_severe_sd",
            ))

    # Rule 2: ≥50% of recent (last 5) standard calls were edited or
    # rejected → standard progression may be too aggressive for this practice.
    standards = df[df["system_type"] == "Standard"].sort_values("created_at", ascending=False).head(5)
    if len(standards) >= 3:
        not_accepted = int((standards["trainer_action"] != "accept").sum())
        if not_accepted / len(standards) >= 0.5:
            suggestions.append(CalibrationSuggestion(
                kind="threshold_tune",
                severity="info",
                message=(
                    f"You've adjusted {not_accepted} of the last {len(standards)} standard-progression calls. "
                    f"The ACSM 5-10% range may be too aggressive for your clients — consider tuning per client."
                ),
                target=None,
            ))

    # Rule 3: any single client with ≥3 overrides and accept rate ≤0.25
    # → flag for review.
    for client_id, group in df.groupby("client_id"):
        if len(group) >= 3:
            rate = (group["trainer_action"] == "accept").sum() / len(group)
            if rate <= 0.25:
                suggestions.append(CalibrationSuggestion(
                    kind="per_client_drift",
                    severity="warn",
                    message=(
                        f"You've accepted only {int((group['trainer_action'] == 'accept').sum())} of "
                        f"{len(group)} system calls for this client. Their thresholds may need per-client tuning."
                    ),
                    target=str(client_id),
                ))

    return suggestions
