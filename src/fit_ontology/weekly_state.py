"""Shared weekly client snapshot.

Dashboard, share links, PDF export, and coach draft all need the same
"what does this client's week look like?" bundle. Keeping that assembly
in one place prevents route-local recomputes from drifting apart.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from .contraindications import Contraindication, match_contraindications
from .db import (
    latest_override_for_week,
    metrics_for_client,
    plan_for_week_with_matches,
    recommendation_for_week,
    sessions_for_client,
    thresholds_for_client,
)
from .ontology import PlannedSession, Recommendation
from .reasoning import RecoveryScore, compute_recovery_score, generate_recommendation


class ClientNotFoundError(LookupError):
    """Raised when a trainer-scoped client lookup misses."""


@dataclass(frozen=True)
class WeeklyClientState:
    trainer_id: str
    client_id: str
    client_name: str
    client_goal: str
    injury_history: str | None
    today: date
    week_of: date
    metrics: pd.DataFrame
    sessions: pd.DataFrame
    thresholds: dict[str, float]
    stored_recommendation: Recommendation | None
    recommendation: Recommendation
    recommendation_needs_persist: bool
    recovery_score: RecoveryScore
    contraindications: list[Contraindication]
    plan: list[PlannedSession]
    latest_override: pd.DataFrame


def week_start(today: date | None = None) -> date:
    """Return the Monday anchoring the weekly recommendation cadence."""
    today = today or date.today()
    return today - timedelta(days=today.weekday())


def build_weekly_client_state(
    con,
    trainer_id: str,
    client_id: str,
    *,
    today: date | None = None,
    include_plan: bool = True,
) -> WeeklyClientState:
    """Assemble one trainer-scoped weekly snapshot for a client.

    The recommendation field is the stored recommendation for the week
    when present; otherwise it is generated in memory with the same
    per-client thresholds the recovery score uses. The caller decides
    whether to persist a generated recommendation.
    """
    today = today or date.today()
    week_of = week_start(today)
    row = con.execute(
        "SELECT name, goal, injury_history FROM clients WHERE id = ? AND trainer_id = ?",
        [client_id, trainer_id],
    ).fetchone()
    if not row:
        raise ClientNotFoundError(client_id)
    client_name, client_goal, injury_history = row

    metrics = metrics_for_client(con, trainer_id, client_id, days=35)
    sessions = sessions_for_client(con, trainer_id, client_id, days=35)
    thresholds = thresholds_for_client(con, trainer_id, client_id)
    stored = recommendation_for_week(con, trainer_id, client_id, week_of)
    if stored is not None:
        rec = stored
        needs_persist = False
    else:
        rec = generate_recommendation(
            client_id,
            metrics,
            sessions,
            today=today,
            thresholds=thresholds,
        )
        needs_persist = True

    score = compute_recovery_score(metrics, sessions, today=today, thresholds=thresholds)
    return WeeklyClientState(
        trainer_id=trainer_id,
        client_id=client_id,
        client_name=client_name,
        client_goal=client_goal,
        injury_history=injury_history,
        today=today,
        week_of=week_of,
        metrics=metrics,
        sessions=sessions,
        thresholds=thresholds,
        stored_recommendation=stored,
        recommendation=rec,
        recommendation_needs_persist=needs_persist,
        recovery_score=score,
        contraindications=match_contraindications(injury_history),
        plan=plan_for_week_with_matches(con, trainer_id, client_id, week_of) if include_plan else [],
        latest_override=latest_override_for_week(con, trainer_id, client_id, week_of),
    )
