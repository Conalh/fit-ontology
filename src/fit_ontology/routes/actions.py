"""Trainer action queue for the roster dashboard."""
from __future__ import annotations

from datetime import date

import pandas as pd
from fastapi import APIRouter, Depends

from ..db import list_clients
from ..weekly_state import build_weekly_client_state
from .deps import current_trainer_id, read_only_conn
from .helpers import classify_rec
from .schemas import ActionQueueItem

router = APIRouter()

_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}
_KIND_RANK = {"review_recommendation": 0, "sync_data": 1, "build_plan": 2}


def _last_metric_days(metrics: pd.DataFrame, today: date) -> int | None:
    if metrics.empty:
        return None
    return int((pd.Timestamp(today) - pd.to_datetime(metrics["date"]).max()).days)


def _flags_from_rationale(rationale: str) -> list[str]:
    if "Flags:" not in rationale:
        return []
    return [
        f.strip()
        for f in rationale.split("Flags:", 1)[1].strip().rstrip(".").split(",")
        if f.strip()
    ]


def _item(
    *,
    kind: str,
    priority: str,
    client_id: str,
    client_name: str,
    client_goal: str,
    title: str,
    detail: str,
    cta_label: str,
    href: str,
) -> ActionQueueItem:
    return ActionQueueItem(
        id=f"{kind}:{client_id}",
        client_id=client_id,
        client_name=client_name,
        client_goal=client_goal,
        priority=priority,
        kind=kind,
        title=title,
        detail=detail,
        cta_label=cta_label,
        href=href,
    )


@router.get("/api/action-queue", response_model=list[ActionQueueItem])
def get_action_queue(
    con=Depends(read_only_conn),
    trainer_id: str = Depends(current_trainer_id),
) -> list[ActionQueueItem]:
    """Return trainer next-actions, ordered by urgency.

    This is not another metrics feed. It translates the shared weekly
    state into concrete work: review high-risk verdicts, reconnect
    stale data, or build a missing plan.
    """
    clients = list_clients(con, trainer_id)
    if clients.empty:
        return []

    items: list[ActionQueueItem] = []
    today = date.today()
    for _, client in clients.iterrows():
        cid = client["id"]
        state = build_weekly_client_state(con, trainer_id, cid)
        last_days = _last_metric_days(state.metrics, today)
        client_href = f"/clients?id={cid}"

        if last_days is None or last_days > 7:
            detail = (
                "No wearable data in the last 35 days."
                if last_days is None
                else f"Last wearable metric landed {last_days} days ago."
            )
            items.append(_item(
                kind="sync_data",
                priority="high" if last_days is None or last_days > 14 else "medium",
                client_id=cid,
                client_name=state.client_name,
                client_goal=state.client_goal,
                title=f"Reconnect data for {state.client_name}",
                detail=detail,
                cta_label="Upload data",
                href=f"/clients/upload?id={cid}",
            ))
            continue

        label = classify_rec(state.recommendation.recommendation)
        already_reviewed = not state.latest_override.empty
        if label in {"Deload", "Conservative"} and not already_reviewed:
            flags = _flags_from_rationale(state.recommendation.rationale)
            detail = (
                f"{label} call at {round(state.recommendation.confidence * 100)}% confidence"
                + (f" with {', '.join(flags[:2])}." if flags else ".")
            )
            items.append(_item(
                kind="review_recommendation",
                priority="high" if label == "Deload" else "medium",
                client_id=cid,
                client_name=state.client_name,
                client_goal=state.client_goal,
                title=f"Review {label} call for {state.client_name}",
                detail=detail,
                cta_label="Review client",
                href=client_href,
            ))

        if not state.plan:
            items.append(_item(
                kind="build_plan",
                priority="medium",
                client_id=cid,
                client_name=state.client_name,
                client_goal=state.client_goal,
                title=f"Build this week's plan for {state.client_name}",
                detail="No planned sessions exist for the current week.",
                cta_label="Open plan",
                href=client_href,
            ))

    return sorted(
        items,
        key=lambda item: (
            _PRIORITY_RANK.get(item.priority, 99),
            _KIND_RANK.get(item.kind, 99),
            item.client_name.lower(),
        ),
    )
