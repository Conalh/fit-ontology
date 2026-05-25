"""Cross-trainer isolation regression.

The most important test in the multi-tenant foundation (roadmap
Phase 2a). It seeds two trainers, gives each one their own client +
their own metrics + their own sessions + their own recommendations +
their own overrides + their own planned sessions + their own
per-client thresholds, then asserts that every scoped helper trainer
A calls returns only trainer A's rows and never trainer B's.

Catches an entire class of bugs at once: if anyone in the future
forgets to add a ``WHERE trainer_id = ?`` to a new helper, the
roundtrip test for that surface will pass (the helper still works
for the single-trainer happy path) but THIS test will fail because
trainer A will see trainer B's data.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from fit_ontology.db import (
    all_overrides,
    connect,
    ensure_client,
    insert_metrics,
    insert_override,
    insert_plan,
    insert_recommendation,
    insert_sessions,
    insert_trainer,
    latest_override_for_week,
    latest_recommendation,
    list_clients,
    metrics_for_client,
    overrides_for_client,
    plan_for_week,
    recommendation_for_week,
    recommendations_for_client,
    sessions_for_client,
    thresholds_for_client,
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


def _seed_world(db_path: Path) -> tuple[str, str, str, str, date]:
    """Build a two-trainer world and return identifiers needed for assertions.

    Layout (the symmetric structure is intentional — anything trainer
    A's helpers can read of trainer A's data, they must NOT be able to
    read of trainer B's):

      trainer_a (t_a) owns client c_a:
        - 3 days of metrics (HRV)
        - 2 sessions
        - 1 weekly recommendation
        - 1 override on that week
        - 1 planned session for the week
        - 1 per-client threshold override

      trainer_b (t_b) owns client c_b with the same shape.

    Returns (trainer_a_id, trainer_b_id, client_a_id, client_b_id, week_of).
    """
    today = date(2026, 5, 25)
    week_of = today - timedelta(days=today.weekday())  # Monday of that week
    trainer_a = "t_a"
    trainer_b = "t_b"
    client_a = "c_a"
    client_b = "c_b"

    with connect(db_path, read_only=False) as con:
        # connect() already seeds the default trainer via _run_migrations;
        # add A and B alongside it. Their emails differ from the default
        # so the trainers.email UNIQUE constraint is satisfied.
        insert_trainer(con, trainer_a, "trainer-a@example.com", "Trainer A")
        insert_trainer(con, trainer_b, "trainer-b@example.com", "Trainer B")

        # Clients
        ensure_client(con, trainer_a, client_a, name="Client A")
        ensure_client(con, trainer_b, client_b, name="Client B")

        # Metrics — 3 daily HRV rows each, identifiable values per trainer
        # so an accidental leakage shows up as the wrong number.
        for offset, value in enumerate([55.0, 58.0, 60.0]):
            row_a = pd.DataFrame([{
                "id": f"m_a_{offset}",
                "client_id": client_a,
                "date": today - timedelta(days=offset),
                "source": "garmin",
                "kind": "hrv_rmssd",
                "value": value,
                "unit": "ms",
            }])
            row_b = pd.DataFrame([{
                "id": f"m_b_{offset}",
                "client_id": client_b,
                "date": today - timedelta(days=offset),
                "source": "garmin",
                "kind": "hrv_rmssd",
                "value": value + 100,  # distinctly different magnitude
                "unit": "ms",
            }])
            insert_metrics(con, trainer_a, row_a)
            insert_metrics(con, trainer_b, row_b)

        # Sessions — 2 each.
        for offset in range(2):
            sess_a = pd.DataFrame([{
                "id": f"s_a_{offset}",
                "client_id": client_a,
                "date": today - timedelta(days=offset),
                "type": "cardio",
                "duration_min": 45,
                "rpe": 6,
                "notes": None,
            }])
            sess_b = pd.DataFrame([{
                "id": f"s_b_{offset}",
                "client_id": client_b,
                "date": today - timedelta(days=offset),
                "type": "strength",
                "duration_min": 60,
                "rpe": 7,
                "notes": None,
            }])
            insert_sessions(con, trainer_a, sess_a)
            insert_sessions(con, trainer_b, sess_b)

        # Recommendations — one each for the current week.
        rec_a = Recommendation(
            id="r_a", client_id=client_a, generated_at=datetime.now(),
            week_of=week_of, recommendation="Standard progression: 5–10%.",
            rationale="A-rationale", source_metric_ids=[], confidence=0.8,
        )
        rec_b = Recommendation(
            id="r_b", client_id=client_b, generated_at=datetime.now(),
            week_of=week_of, recommendation="Deload week: reduce 20%.",
            rationale="B-rationale", source_metric_ids=[], confidence=0.9,
        )
        insert_recommendation(con, trainer_a, rec_a)
        insert_recommendation(con, trainer_b, rec_b)

        # Overrides — one each for the same week.
        ov_a = RecommendationOverride(
            id="o_a", client_id=client_a, week_of=week_of,
            system_recommendation=rec_a.recommendation,
            system_confidence=rec_a.confidence,
            trainer_action=OverrideAction.ACCEPT,
            applied_load_change_pct=None, trainer_note=None,
            created_at=datetime.now(),
        )
        ov_b = RecommendationOverride(
            id="o_b", client_id=client_b, week_of=week_of,
            system_recommendation=rec_b.recommendation,
            system_confidence=rec_b.confidence,
            trainer_action=OverrideAction.EDIT,
            applied_load_change_pct=-15.0, trainer_note="travel",
            created_at=datetime.now(),
        )
        insert_override(con, trainer_a, ov_a)
        insert_override(con, trainer_b, ov_b)

        # Planned sessions — one slot each for the week.
        plan_a = PlannedSession(
            id=f"ps_a_{uuid.uuid4().hex[:6]}",
            client_id=client_a, week_of=week_of, slot=1,
            type=SessionType.CARDIO, title="Z2 ride", description="60min easy",
            target_duration_min=60, target_load_au=300, target_rpe=5.0,
            contraindications=[], source=PlanSource.ENGINE,
            generated_at=datetime.now(), executed_session_id=None,
        )
        plan_b = PlannedSession(
            id=f"ps_b_{uuid.uuid4().hex[:6]}",
            client_id=client_b, week_of=week_of, slot=1,
            type=SessionType.STRENGTH, title="Lower body",
            description="squat + deadlift",
            target_duration_min=75, target_load_au=525, target_rpe=7.0,
            contraindications=[], source=PlanSource.ENGINE,
            generated_at=datetime.now(), executed_session_id=None,
        )
        insert_plan(con, trainer_a, [plan_a])
        insert_plan(con, trainer_b, [plan_b])

        # Per-client thresholds.
        upsert_threshold(con, trainer_a, client_a, "hrv_severe_sd", -1.5)
        upsert_threshold(con, trainer_b, client_b, "hrv_severe_sd", -2.0)

    return trainer_a, trainer_b, client_a, client_b, week_of


def test_list_clients_is_trainer_scoped(tmp_path: Path) -> None:
    db_path = tmp_path / "iso.duckdb"
    trainer_a, trainer_b, client_a, client_b, _ = _seed_world(db_path)

    with connect(db_path, read_only=True) as con:
        roster_a = list_clients(con, trainer_a)
        roster_b = list_clients(con, trainer_b)

    assert list(roster_a["id"]) == [client_a]
    assert list(roster_b["id"]) == [client_b]


def test_metrics_and_sessions_scoped(tmp_path: Path) -> None:
    db_path = tmp_path / "iso.duckdb"
    trainer_a, trainer_b, client_a, client_b, _ = _seed_world(db_path)

    with connect(db_path, read_only=True) as con:
        # Trainer A asking about their own client gets data; asking about
        # trainer B's client gets nothing (404-equivalent at the data
        # layer — the row exists but is not theirs to see).
        a_own_metrics = metrics_for_client(con, trainer_a, client_a, days=14)
        a_peek_metrics = metrics_for_client(con, trainer_a, client_b, days=14)
        b_own_metrics = metrics_for_client(con, trainer_b, client_b, days=14)
        b_peek_metrics = metrics_for_client(con, trainer_b, client_a, days=14)

        a_own_sessions = sessions_for_client(con, trainer_a, client_a, days=14)
        a_peek_sessions = sessions_for_client(con, trainer_a, client_b, days=14)

    assert len(a_own_metrics) == 3 and len(b_own_metrics) == 3
    assert a_peek_metrics.empty and b_peek_metrics.empty
    assert len(a_own_sessions) == 2
    assert a_peek_sessions.empty

    # Magnitude check — trainer A's HRV values are 55-60; if a leak
    # ever flips the WHERE clause, the values would jump to 155-160
    # (trainer B's distinctive range).
    assert a_own_metrics["value"].max() <= 100


def test_recommendations_scoped(tmp_path: Path) -> None:
    db_path = tmp_path / "iso.duckdb"
    trainer_a, trainer_b, client_a, client_b, week_of = _seed_world(db_path)

    with connect(db_path, read_only=True) as con:
        # Single-week lookup
        rec_a = recommendation_for_week(con, trainer_a, client_a, week_of)
        rec_a_peek = recommendation_for_week(con, trainer_a, client_b, week_of)
        rec_b = recommendation_for_week(con, trainer_b, client_b, week_of)

        # Latest + history
        latest_a = latest_recommendation(con, trainer_a, client_a)
        latest_a_peek = latest_recommendation(con, trainer_a, client_b)
        history_a = recommendations_for_client(con, trainer_a, client_a)
        history_a_peek = recommendations_for_client(con, trainer_a, client_b)

    assert rec_a is not None and rec_a.id == "r_a"
    assert rec_b is not None and rec_b.id == "r_b"
    assert rec_a_peek is None
    assert latest_a.iloc[0]["recommendation"].startswith("Standard")
    assert latest_a_peek.empty
    assert list(history_a["id"]) == ["r_a"]
    assert history_a_peek.empty


def test_overrides_scoped(tmp_path: Path) -> None:
    db_path = tmp_path / "iso.duckdb"
    trainer_a, trainer_b, client_a, client_b, week_of = _seed_world(db_path)

    with connect(db_path, read_only=True) as con:
        a_history = overrides_for_client(con, trainer_a, client_a)
        a_peek = overrides_for_client(con, trainer_a, client_b)
        a_latest = latest_override_for_week(con, trainer_a, client_a, week_of)
        a_latest_peek = latest_override_for_week(con, trainer_a, client_b, week_of)

        # all_overrides feeds the calibration page; trainer A must not
        # see trainer B's override history there either.
        a_all = all_overrides(con, trainer_a)
        b_all = all_overrides(con, trainer_b)

    assert list(a_history["id"]) == ["o_a"]
    assert a_peek.empty
    assert a_latest.iloc[0]["trainer_action"] == "accept"
    assert a_latest_peek.empty
    assert list(a_all["id"]) == ["o_a"]
    assert list(b_all["id"]) == ["o_b"]


def test_planned_sessions_scoped(tmp_path: Path) -> None:
    db_path = tmp_path / "iso.duckdb"
    trainer_a, trainer_b, client_a, client_b, week_of = _seed_world(db_path)

    with connect(db_path, read_only=True) as con:
        plan_a = plan_for_week(con, trainer_a, client_a, week_of)
        plan_a_peek = plan_for_week(con, trainer_a, client_b, week_of)
        plan_b = plan_for_week(con, trainer_b, client_b, week_of)

    assert len(plan_a) == 1 and plan_a[0].type == SessionType.CARDIO
    assert len(plan_b) == 1 and plan_b[0].type == SessionType.STRENGTH
    assert plan_a_peek == []


def test_thresholds_scoped(tmp_path: Path) -> None:
    db_path = tmp_path / "iso.duckdb"
    trainer_a, trainer_b, client_a, client_b, _ = _seed_world(db_path)

    with connect(db_path, read_only=True) as con:
        a_thresh = thresholds_for_client(con, trainer_a, client_a)
        a_peek = thresholds_for_client(con, trainer_a, client_b)
        b_thresh = thresholds_for_client(con, trainer_b, client_b)

    assert a_thresh == {"hrv_severe_sd": -1.5}
    assert a_peek == {}
    assert b_thresh == {"hrv_severe_sd": -2.0}


def test_upsert_threshold_rejects_cross_trainer_client_id(tmp_path: Path) -> None:
    """A trainer who knows another trainer's client_id must not be able
    to move or overwrite that client's sparse threshold rows."""
    db_path = tmp_path / "iso.duckdb"
    trainer_a, trainer_b, client_a, _client_b, _ = _seed_world(db_path)

    with connect(db_path, read_only=False) as con:
        before = thresholds_for_client(con, trainer_a, client_a)
        with pytest.raises(ValueError):
            upsert_threshold(con, trainer_b, client_a, "hrv_severe_sd", -2.5)
        after_a = thresholds_for_client(con, trainer_a, client_a)
        after_b = thresholds_for_client(con, trainer_b, client_a)

    assert before == {"hrv_severe_sd": -1.5}
    assert after_a == before
    assert after_b == {}


def test_insert_metrics_rejects_cross_trainer_client_id(tmp_path: Path) -> None:
    db_path = tmp_path / "iso.duckdb"
    trainer_a, trainer_b, client_a, _client_b, _ = _seed_world(db_path)

    bad = pd.DataFrame([{
        "id": "m_cross",
        "client_id": client_a,
        "date": date.today(),
        "source": "garmin",
        "kind": "hrv_rmssd",
        "value": 50.0,
        "unit": "ms",
    }])
    with connect(db_path, read_only=False) as con:
        with pytest.raises(ValueError):
            insert_metrics(con, trainer_b, bad)
        assert metrics_for_client(con, trainer_b, client_a, days=14).empty
        assert not metrics_for_client(con, trainer_a, client_a, days=14).empty


def test_insert_override_rejects_cross_trainer_client_id(tmp_path: Path) -> None:
    db_path = tmp_path / "iso.duckdb"
    trainer_a, trainer_b, client_a, _client_b, week_of = _seed_world(db_path)

    ov = RecommendationOverride(
        id="o_cross", client_id=client_a, week_of=week_of,
        system_recommendation="Standard progression: 5-10%.",
        system_confidence=0.78,
        trainer_action=OverrideAction.REJECT,
        applied_load_change_pct=None, trainer_note="not yours",
        created_at=datetime.now(),
    )
    with connect(db_path, read_only=False) as con:
        with pytest.raises(ValueError):
            insert_override(con, trainer_b, ov)
        assert overrides_for_client(con, trainer_b, client_a).empty
        assert not overrides_for_client(con, trainer_a, client_a).empty


def test_upsert_planned_session_preserves_isolation(tmp_path: Path) -> None:
    """upsert_planned_session is the trainer-edit path. Even if a buggy
    UI sent trainer A's edit with trainer B's client_id, the trainer_id
    column on the row must remain A's so future reads still scope it
    correctly."""
    db_path = tmp_path / "iso.duckdb"
    trainer_a, trainer_b, client_a, client_b, week_of = _seed_world(db_path)

    # Trainer A edits their own slot — should still belong to A after write.
    with connect(db_path, read_only=False) as con:
        plan_a = plan_for_week(con, trainer_a, client_a, week_of)
        existing = plan_a[0]
        existing.title = "Z2 ride (edited)"
        upsert_planned_session(con, trainer_a, existing)

    with connect(db_path, read_only=True) as con:
        # Trainer A still sees the edited slot.
        plan_a_after = plan_for_week(con, trainer_a, client_a, week_of)
        assert plan_a_after[0].title == "Z2 ride (edited)"
        # Trainer B does not, because the row's trainer_id is still A.
        plan_b_peek = plan_for_week(con, trainer_b, client_a, week_of)
        assert plan_b_peek == []
