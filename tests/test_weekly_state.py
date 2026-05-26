"""Shared weekly-state assembly tests."""
from __future__ import annotations

from datetime import date, datetime

from fit_ontology.db import (
    DEFAULT_TRAINER_ID,
    connect,
    ensure_client,
    insert_override,
    insert_recommendation,
    upsert_planned_session,
    upsert_threshold,
)
from fit_ontology.ontology import (
    OverrideAction,
    PlannedSession,
    PlanSource,
    Recommendation,
    RecommendationOverride,
    SessionType,
)
from fit_ontology.weekly_state import build_weekly_client_state, week_start


def test_weekly_state_collects_stored_recommendation_thresholds_plan_and_override(tmp_path):
    db_path = tmp_path / "weekly_state.duckdb"
    today = date.today()
    week_of = week_start(today)

    with connect(db_path, read_only=False) as con:
        ensure_client(con, DEFAULT_TRAINER_ID, "c_state", name="Snapshot Client")
        upsert_threshold(con, DEFAULT_TRAINER_ID, "c_state", "sleep_floor_hours", 6.25)
        insert_recommendation(
            con,
            DEFAULT_TRAINER_ID,
            Recommendation(
                id="rec_state",
                client_id="c_state",
                generated_at=datetime(2026, 5, 26, 9, 0),
                week_of=week_of,
                recommendation="Stored weekly verdict.",
                rationale="Stored rationale.",
                source_metric_ids=[],
                confidence=0.66,
            ),
        )
        insert_override(
            con,
            DEFAULT_TRAINER_ID,
            RecommendationOverride(
                id="ov_old",
                client_id="c_state",
                week_of=week_of,
                system_recommendation="Old system verdict",
                system_confidence=0.5,
                trainer_action=OverrideAction.EDIT,
                trainer_recommendation="Old trainer call.",
                created_at=datetime(2026, 5, 26, 8, 0),
            ),
        )
        insert_override(
            con,
            DEFAULT_TRAINER_ID,
            RecommendationOverride(
                id="ov_new",
                client_id="c_state",
                week_of=week_of,
                system_recommendation="Stored weekly verdict.",
                system_confidence=0.66,
                trainer_action=OverrideAction.EDIT,
                trainer_recommendation="Latest trainer call.",
                created_at=datetime(2026, 5, 26, 10, 0),
            ),
        )
        upsert_planned_session(
            con,
            DEFAULT_TRAINER_ID,
            PlannedSession(
                id="ps_state_1",
                client_id="c_state",
                week_of=week_of,
                slot=1,
                type=SessionType.STRENGTH,
                title="Strength primer",
                description="Keep the session crisp.",
                target_duration_min=45,
                target_load_au=270,
                target_rpe=6.0,
                source=PlanSource.TRAINER,
                generated_at=datetime(2026, 5, 26, 9, 30),
            ),
        )

    with connect(db_path, read_only=True) as con:
        state = build_weekly_client_state(con, DEFAULT_TRAINER_ID, "c_state", today=today)

    assert state.week_of == week_of
    assert state.recommendation.id == "rec_state"
    assert state.recommendation_needs_persist is False
    assert state.thresholds == {"sleep_floor_hours": 6.25}
    assert [p.id for p in state.plan] == ["ps_state_1"]
    assert state.latest_override.iloc[0]["id"] == "ov_new"
