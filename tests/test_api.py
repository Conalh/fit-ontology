"""API surface tests — FastAPI's TestClient with a seeded temp DB.

Verifies every route the front-end will hit returns the shape we
promised. Doesn't go through the real network stack; runs the ASGI
app in-process.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import pytest
from fastapi.testclient import TestClient

import fit_ontology.api as api_mod
from fit_ontology.db import (
    DEFAULT_TRAINER_ID,
    connect,
    ensure_client,
    insert_metrics,
    insert_plan,
    insert_recommendation,
    insert_sessions,
    insert_trainer,
)
from fit_ontology.ontology import MetricKind, PlannedSession, PlanSource, Recommendation, SessionType
from fit_ontology.routes import (
    clients as clients_routes,
)
from fit_ontology.routes import (
    metrics as metrics_routes,
)
from fit_ontology.routes import (
    overrides as overrides_routes,
)
from fit_ontology.routes import (
    pdf as pdf_routes,
)
from fit_ontology.routes import (
    planning as planning_routes,
)
from fit_ontology.routes import (
    recommendation as recommendation_routes,
)
from fit_ontology.routes import (
    thresholds as thresholds_routes,
)
from fit_ontology.weekly_delta import build_weekly_delta


@pytest.fixture()
def app_with_db(tmp_path: Path, monkeypatch):
    """Point the API at a temp DuckDB and seed it with one client +
    some recent metrics + sessions. Patches DEFAULT_DB_PATH used by the
    write endpoints, and shadows the read-only dependency so reads come
    from the same temp DB."""
    db_path = tmp_path / "fit_ontology.duckdb"

    con = connect(db_path)
    # The migration in connect() has already seeded DEFAULT_TRAINER_ID.
    # The API dependency current_trainer_id() returns the same id, so
    # routes will read this seeded client without further wiring.
    ensure_client(con, DEFAULT_TRAINER_ID, "c_test", name="Test Client")

    today = date.today()
    metric_rows = []
    for offset in range(28, 0, -1):
        d = today - timedelta(days=offset)
        metric_rows.append({
            "id": f"m-hrv-{offset}", "client_id": "c_test", "date": d,
            "source": "garmin", "kind": MetricKind.HRV_RMSSD.value,
            "value": 55.0, "unit": "ms",
        })
        metric_rows.append({
            "id": f"m-sleep-{offset}", "client_id": "c_test", "date": d,
            "source": "garmin", "kind": MetricKind.SLEEP_HOURS.value,
            "value": 7.5, "unit": "h",
        })
    insert_metrics(con, DEFAULT_TRAINER_ID, pd.DataFrame(metric_rows))

    session_rows = []
    for i, offset in enumerate([2, 4, 6, 9, 11, 13]):
        session_rows.append({
            "id": f"s-{i}", "client_id": "c_test",
            "date": today - timedelta(days=offset),
            "type": "strength", "duration_min": 60, "rpe": 6, "notes": "",
        })
    insert_sessions(con, DEFAULT_TRAINER_ID, pd.DataFrame(session_rows))
    con.close()

    # Each route module did ``from ..db import DEFAULT_DB_PATH`` at load
    # time, so the constant is bound separately in each module's namespace.
    # Patch every module that opens its own write connection.
    for mod in (clients_routes, metrics_routes, overrides_routes, planning_routes, recommendation_routes, thresholds_routes):
        monkeypatch.setattr(mod, "DEFAULT_DB_PATH", db_path)

    def _ro():
        c = connect(db_path, read_only=True)
        try:
            yield c
        finally:
            c.close()

    api_mod.app.dependency_overrides[api_mod._read_only_conn] = _ro
    try:
        yield TestClient(api_mod.app)
    finally:
        api_mod.app.dependency_overrides.pop(api_mod._read_only_conn, None)


def test_health(app_with_db):
    r = app_with_db.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_get_clients_returns_seeded_client(app_with_db):
    r = app_with_db.get("/api/clients")
    assert r.status_code == 200
    rows = r.json()
    assert any(c["id"] == "c_test" for c in rows)


def test_get_client_404_for_unknown(app_with_db):
    assert app_with_db.get("/api/clients/c_missing").status_code == 404


def test_get_metrics_returns_seeded_rows(app_with_db):
    r = app_with_db.get("/api/clients/c_test/metrics?days=14")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) > 0
    kinds = {row["kind"] for row in rows}
    assert {"hrv_rmssd", "sleep_hours"} <= kinds


def test_get_recommendation_returns_structured_payload(app_with_db):
    r = app_with_db.get("/api/clients/c_test/recommendation")
    assert r.status_code == 200
    data = r.json()
    assert "recommendation" in data and "rationale" in data
    assert 0 <= data["confidence"] <= 1
    assert isinstance(data["source_metric_ids"], list)
    assert "contraindications" in data


def test_recommendation_is_lazy_persisted_and_stable(app_with_db):
    """First GET this week computes + persists. Second GET returns the
    SAME id — proves we read the stored row instead of recomputing
    (which would generate a fresh uuid)."""
    first = app_with_db.get("/api/clients/c_test/recommendation").json()
    second = app_with_db.get("/api/clients/c_test/recommendation").json()
    assert first["id"] == second["id"], "second GET should return the stored row"
    assert first["week_of"] == second["week_of"]


def test_recommendation_marks_stored_week_as_locked_with_live_preview(app_with_db):
    """A stored weekly call remains canonical, while today's engine
    output is exposed separately when it has drifted."""
    week_of = date.today() - timedelta(days=date.today().weekday())
    with connect(recommendation_routes.DEFAULT_DB_PATH, read_only=False) as con:
        insert_recommendation(
            con,
            DEFAULT_TRAINER_ID,
            Recommendation(
                id="rec_locked_sentinel",
                client_id="c_test",
                generated_at=datetime.now(),
                week_of=week_of,
                recommendation="Locked trainer-facing verdict.",
                rationale="This is the stable weekly recommendation.",
                source_metric_ids=["m-hrv-1"],
                confidence=0.41,
            ),
        )

    r = app_with_db.get("/api/clients/c_test/recommendation")

    assert r.status_code == 200, r.text
    data = r.json()
    assert data["id"] == "rec_locked_sentinel"
    assert data["recommendation"] == "Locked trainer-facing verdict."
    assert data["is_locked"] is True
    assert data["preview_differs"] is True
    assert data["live_preview"] is not None
    assert data["live_preview"]["recommendation"] != data["recommendation"]


def test_refresh_recommendation_replaces_current_week_snapshot(app_with_db):
    week_of = date.today() - timedelta(days=date.today().weekday())
    with connect(recommendation_routes.DEFAULT_DB_PATH, read_only=False) as con:
        insert_recommendation(
            con,
            DEFAULT_TRAINER_ID,
            Recommendation(
                id="rec_refresh_sentinel",
                client_id="c_test",
                generated_at=datetime.now(),
                week_of=week_of,
                recommendation="Locked stale verdict.",
                rationale="This should be replaced by an explicit refresh.",
                source_metric_ids=["m-hrv-1"],
                confidence=0.25,
            ),
        )

    refreshed = app_with_db.post("/api/clients/c_test/recommendation/refresh")

    assert refreshed.status_code == 200, refreshed.text
    refreshed_data = refreshed.json()
    assert refreshed_data["id"] != "rec_refresh_sentinel"
    assert refreshed_data["recommendation"] != "Locked stale verdict."
    assert refreshed_data["is_locked"] is True
    assert refreshed_data["preview_differs"] is False
    assert refreshed_data["live_preview"] is None

    current = app_with_db.get("/api/clients/c_test/recommendation").json()
    assert current["id"] == refreshed_data["id"]
    assert current["recommendation"] == refreshed_data["recommendation"]


def test_recommendation_get_returns_live_compute_when_initial_persist_writer_is_busy(app_with_db, monkeypatch):
    real_connect = recommendation_routes.connect

    def busy_on_write(db_path, *, read_only=False):
        if not read_only:
            raise duckdb.ConnectionException("writer busy")
        return real_connect(db_path, read_only=read_only)

    monkeypatch.setattr(recommendation_routes, "connect", busy_on_write)

    r = app_with_db.get("/api/clients/c_test/recommendation")

    assert r.status_code == 200, r.text
    data = r.json()
    assert "recommendation" in data
    assert data["is_locked"] is False
    assert data["preview_differs"] is False
    assert data["live_preview"] is None


def test_refresh_recommendation_returns_503_when_writer_is_busy(app_with_db, monkeypatch):
    week_of = date.today() - timedelta(days=date.today().weekday())
    with connect(recommendation_routes.DEFAULT_DB_PATH, read_only=False) as con:
        insert_recommendation(
            con,
            DEFAULT_TRAINER_ID,
            Recommendation(
                id="rec_busy_refresh",
                client_id="c_test",
                generated_at=datetime.now(),
                week_of=week_of,
                recommendation="Locked stale verdict.",
                rationale="This should be replaced by an explicit refresh.",
                source_metric_ids=["m-hrv-1"],
                confidence=0.25,
            ),
        )

    real_connect = recommendation_routes.connect

    def busy_on_write(db_path, *, read_only=False):
        if not read_only:
            raise duckdb.ConnectionException("writer busy")
        return real_connect(db_path, read_only=read_only)

    monkeypatch.setattr(recommendation_routes, "connect", busy_on_write)

    r = app_with_db.post("/api/clients/c_test/recommendation/refresh")

    assert r.status_code == 503, r.text
    assert "DB busy" in r.json()["detail"]


def test_recommendation_history_endpoint(app_with_db):
    """Calling the recommendation endpoint persists; the history
    endpoint then surfaces it."""
    # Trigger one persist by hitting /recommendation first.
    seeded = app_with_db.get("/api/clients/c_test/recommendation").json()

    r = app_with_db.get("/api/clients/c_test/recommendations")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) >= 1
    assert any(row["id"] == seeded["id"] for row in rows)
    # History rows always omit contraindications (they're derived from
    # current intake, not historical).
    for row in rows:
        assert row["contraindications"] == []


def test_recommendation_surfaces_contraindications_from_injury(app_with_db):
    """Editing the client's injury_history should make matching
    contraindications appear in the next recommendation response."""
    app_with_db.patch(
        "/api/clients/c_test",
        json={"injury_history": "ACL reconstruction 2022; lumbar stiffness on heavy days"},
    )
    r = app_with_db.get("/api/clients/c_test/recommendation")
    data = r.json()
    kinds = {c["kind"] for c in data["contraindications"]}
    assert "acl" in kinds
    assert "knee" in kinds
    assert "lumbar" in kinds


def test_get_roster_includes_seeded_client(app_with_db):
    r = app_with_db.get("/api/roster")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) >= 1
    me = next(r for r in rows if r["client_id"] == "c_test")
    assert me["label"] in {"Standard", "Conservative", "Deload", "No recent data"}


def test_roster_uses_stored_weekly_recommendation(app_with_db):
    week_of = date.today() - timedelta(days=date.today().weekday())
    with connect(recommendation_routes.DEFAULT_DB_PATH, read_only=False) as con:
        insert_recommendation(
            con,
            DEFAULT_TRAINER_ID,
            Recommendation(
                id="rec_roster_sentinel",
                client_id="c_test",
                generated_at=datetime.now(),
                week_of=week_of,
                recommendation="Deload week: reduce training load by 20%.",
                rationale="Flags: hrv_below_baseline.",
                source_metric_ids=["m-hrv-1"],
                confidence=0.91,
            ),
        )

    r = app_with_db.get("/api/roster")
    assert r.status_code == 200
    me = next(row for row in r.json() if row["client_id"] == "c_test")
    assert me["label"] == "Deload"
    assert me["confidence"] == 0.91


def test_action_queue_surfaces_unreviewed_deload_and_missing_plan(app_with_db):
    week_of = date.today() - timedelta(days=date.today().weekday())
    with connect(recommendation_routes.DEFAULT_DB_PATH, read_only=False) as con:
        insert_recommendation(
            con,
            DEFAULT_TRAINER_ID,
            Recommendation(
                id="rec_queue_deload",
                client_id="c_test",
                generated_at=datetime.now(),
                week_of=week_of,
                recommendation="Deload week: reduce training load by 20%.",
                rationale="Flags: hrv_below_baseline.",
                source_metric_ids=["m-hrv-1"],
                confidence=0.93,
            ),
        )

    r = app_with_db.get("/api/action-queue")
    assert r.status_code == 200, r.text
    items = r.json()
    assert items[0]["kind"] == "review_recommendation"
    assert items[0]["priority"] == "high"
    assert items[0]["client_id"] == "c_test"
    assert "Deload" in items[0]["title"]
    assert any(item["kind"] == "build_plan" and item["client_id"] == "c_test" for item in items)


def test_plan_get_returns_in_memory_plan_when_writer_is_busy(app_with_db, monkeypatch):
    real_connect = planning_routes.connect

    def busy_on_write(db_path, *, read_only=False):
        if not read_only:
            raise duckdb.ConnectionException("writer busy")
        return real_connect(db_path, read_only=read_only)

    monkeypatch.setattr(planning_routes, "connect", busy_on_write)

    r = app_with_db.get("/api/clients/c_test/plan")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sessions"]
    assert body["verdict"] in {"DELOAD", "CONSERVATIVE", "STANDARD"}


def test_weekly_delta_summarizes_plan_vs_reality(app_with_db):
    today = date.today()
    week_of = today - timedelta(days=today.weekday())
    previous_week = week_of - timedelta(days=7)

    with connect(recommendation_routes.DEFAULT_DB_PATH, read_only=False) as con:
        ensure_client(con, DEFAULT_TRAINER_ID, "c_delta", name="Delta Client")
        insert_metrics(
            con,
            DEFAULT_TRAINER_ID,
            pd.DataFrame([
                {
                    "id": "m_delta_recent",
                    "client_id": "c_delta",
                    "date": today,
                    "source": "garmin",
                    "kind": MetricKind.HRV_RMSSD.value,
                    "value": 55.0,
                    "unit": "ms",
                }
            ]),
        )
        insert_sessions(
            con,
            DEFAULT_TRAINER_ID,
            pd.DataFrame([
                {
                    "id": "s_delta_done",
                    "client_id": "c_delta",
                    "date": week_of,
                    "type": "strength",
                    "duration_min": 60,
                    "rpe": 5,
                    "notes": "",
                },
                {
                    "id": "s_delta_previous",
                    "client_id": "c_delta",
                    "date": previous_week,
                    "type": "strength",
                    "duration_min": 30,
                    "rpe": 5,
                    "notes": "",
                },
            ]),
        )
        insert_plan(
            con,
            DEFAULT_TRAINER_ID,
            [
                PlannedSession(
                    id="p_delta_1",
                    client_id="c_delta",
                    week_of=week_of,
                    slot=1,
                    type=SessionType.STRENGTH,
                    title="Strength",
                    description="Do the work.",
                    target_duration_min=40,
                    target_load_au=200,
                    target_rpe=5,
                    contraindications=[],
                    source=PlanSource.ENGINE,
                    generated_at=datetime.now(),
                    executed_session_id="s_delta_done",
                ),
                PlannedSession(
                    id="p_delta_2",
                    client_id="c_delta",
                    week_of=week_of,
                    slot=2,
                    type=SessionType.CARDIO,
                    title="Z2",
                    description="Easy aerobic.",
                    target_duration_min=50,
                    target_load_au=300,
                    target_rpe=6,
                    contraindications=[],
                    source=PlanSource.ENGINE,
                    generated_at=datetime.now(),
                    executed_session_id=None,
                ),
            ],
        )

    r = app_with_db.get("/api/clients/c_delta/weekly-delta")

    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "off_track"
    assert data["planned_sessions"] == 2
    assert data["completed_sessions"] == 1
    assert data["completion_rate"] == 0.5
    assert data["target_load_au"] == 500
    assert data["completed_target_load_au"] == 200
    assert data["actual_load_au"] == 300
    assert data["matched_load_delta_pct"] == 50.0
    assert data["current_week_load_au"] == 300
    assert data["previous_week_load_au"] == 150
    assert data["week_load_change_pct"] == 100.0
    assert "1 of 2 planned sessions completed" in data["bullets"][0]
    assert any("50% above target" in bullet for bullet in data["bullets"])


def test_weekly_delta_does_not_flag_uncompleted_plan_early_week(app_with_db):
    early_week = date(2026, 5, 26)  # Tuesday
    week_of = early_week - timedelta(days=early_week.weekday())

    with connect(recommendation_routes.DEFAULT_DB_PATH, read_only=False) as con:
        ensure_client(con, DEFAULT_TRAINER_ID, "c_early_plan", name="Early Plan")
        insert_plan(
            con,
            DEFAULT_TRAINER_ID,
            [
                PlannedSession(
                    id="p_early_1",
                    client_id="c_early_plan",
                    week_of=week_of,
                    slot=1,
                    type=SessionType.STRENGTH,
                    title="Strength",
                    description="Planned for later this week.",
                    target_duration_min=60,
                    target_load_au=300,
                    target_rpe=5,
                    contraindications=[],
                    source=PlanSource.ENGINE,
                    generated_at=datetime.now(),
                    executed_session_id=None,
                )
            ],
        )

        delta = build_weekly_delta(con, DEFAULT_TRAINER_ID, "c_early_plan", today=early_week)

    assert delta.completed_sessions == 0
    assert delta.completion_rate == 0.0
    assert delta.status == "on_track"


def test_weekly_delta_matches_sessions_without_visiting_plan_first(app_with_db):
    today = date.today()
    week_of = today - timedelta(days=today.weekday())

    with connect(recommendation_routes.DEFAULT_DB_PATH, read_only=False) as con:
        ensure_client(con, DEFAULT_TRAINER_ID, "c_match_delta", name="Match Delta")
        insert_sessions(
            con,
            DEFAULT_TRAINER_ID,
            pd.DataFrame([
                {
                    "id": "s_match_done",
                    "client_id": "c_match_delta",
                    "date": week_of + timedelta(days=1),
                    "type": "strength",
                    "duration_min": 60,
                    "rpe": 8,
                    "notes": "",
                }
            ]),
        )
        insert_plan(
            con,
            DEFAULT_TRAINER_ID,
            [
                PlannedSession(
                    id="p_match_1",
                    client_id="c_match_delta",
                    week_of=week_of,
                    slot=1,
                    type=SessionType.STRENGTH,
                    title="Strength",
                    description="Do the work.",
                    target_duration_min=60,
                    target_load_au=300,
                    target_rpe=5,
                    contraindications=[],
                    source=PlanSource.ENGINE,
                    generated_at=datetime.now(),
                    executed_session_id=None,
                )
            ],
        )

    r = app_with_db.get("/api/clients/c_match_delta/weekly-delta")

    assert r.status_code == 200, r.text
    data = r.json()
    assert data["completed_sessions"] == 1
    assert data["actual_load_au"] == 480
    assert data["matched_load_delta_pct"] == 60.0


def test_weekly_delta_404s_for_unknown_client(app_with_db):
    r = app_with_db.get("/api/clients/c_missing/weekly-delta")
    assert r.status_code == 404


def test_action_queue_surfaces_plan_reality_drift(app_with_db):
    today = date.today()
    week_of = today - timedelta(days=today.weekday())
    previous_week = week_of - timedelta(days=7)

    with connect(recommendation_routes.DEFAULT_DB_PATH, read_only=False) as con:
        ensure_client(con, DEFAULT_TRAINER_ID, "c_delta", name="Delta Client")
        insert_metrics(
            con,
            DEFAULT_TRAINER_ID,
            pd.DataFrame([
                {
                    "id": "m_delta_recent_queue",
                    "client_id": "c_delta",
                    "date": today,
                    "source": "garmin",
                    "kind": MetricKind.HRV_RMSSD.value,
                    "value": 55.0,
                    "unit": "ms",
                }
            ]),
        )
        insert_sessions(
            con,
            DEFAULT_TRAINER_ID,
            pd.DataFrame([
                {
                    "id": "s_delta_done",
                    "client_id": "c_delta",
                    "date": week_of,
                    "type": "strength",
                    "duration_min": 60,
                    "rpe": 5,
                    "notes": "",
                },
                {
                    "id": "s_delta_previous",
                    "client_id": "c_delta",
                    "date": previous_week,
                    "type": "strength",
                    "duration_min": 30,
                    "rpe": 5,
                    "notes": "",
                },
            ]),
        )
        insert_plan(
            con,
            DEFAULT_TRAINER_ID,
            [
                PlannedSession(
                    id="p_delta_1",
                    client_id="c_delta",
                    week_of=week_of,
                    slot=1,
                    type=SessionType.STRENGTH,
                    title="Strength",
                    description="Do the work.",
                    target_duration_min=40,
                    target_load_au=200,
                    target_rpe=5,
                    contraindications=[],
                    source=PlanSource.ENGINE,
                    generated_at=datetime.now(),
                    executed_session_id="s_delta_done",
                )
            ],
        )

    r = app_with_db.get("/api/action-queue")

    assert r.status_code == 200, r.text
    items = r.json()
    drift = next(item for item in items if item["kind"] == "review_weekly_delta")
    assert drift["client_id"] == "c_delta"
    assert drift["priority"] == "high"
    assert "plan drift" in drift["title"].lower()
    assert "50% above target" in drift["detail"]


def test_refresh_recommendation_rebuilds_untouched_engine_plan(app_with_db, monkeypatch):
    today = date.today()
    week_of = today - timedelta(days=today.weekday())

    with connect(recommendation_routes.DEFAULT_DB_PATH, read_only=False) as con:
        ensure_client(con, DEFAULT_TRAINER_ID, "c_refresh_plan", name="Refresh Plan")
        insert_recommendation(
            con,
            DEFAULT_TRAINER_ID,
            Recommendation(
                id="rec_refresh_plan_old",
                client_id="c_refresh_plan",
                generated_at=datetime.now(),
                week_of=week_of,
                recommendation="Standard progression per ACSM 11e: increase load 5-10%.",
                rationale="Old weekly snapshot.",
                source_metric_ids=[],
                confidence=0.78,
            ),
        )
        insert_plan(
            con,
            DEFAULT_TRAINER_ID,
            [
                PlannedSession(
                    id="p_refresh_old_1",
                    client_id="c_refresh_plan",
                    week_of=week_of,
                    slot=1,
                    type=SessionType.STRENGTH,
                    title="Old standard heavy strength",
                    description="This was generated from the old standard verdict.",
                    target_duration_min=60,
                    target_load_au=500,
                    target_rpe=8,
                    contraindications=[],
                    source=PlanSource.ENGINE,
                    generated_at=datetime.now(),
                    executed_session_id=None,
                )
            ],
        )

    def deload_recommendation(client_id, metrics, sessions, today=None, thresholds=None):
        today = today or date.today()
        return Recommendation(
            id="rec_refresh_plan_new",
            client_id=client_id,
            generated_at=datetime.now(),
            week_of=today - timedelta(days=today.weekday()),
            recommendation="Deload week: reduce training load by 40%.",
            rationale="Flags: hrv_below_baseline.",
            source_metric_ids=[],
            confidence=0.9,
        )

    monkeypatch.setattr(recommendation_routes, "generate_recommendation", deload_recommendation)

    refreshed = app_with_db.post("/api/clients/c_refresh_plan/recommendation/refresh")
    assert refreshed.status_code == 200, refreshed.text

    plan = app_with_db.get("/api/clients/c_refresh_plan/plan")

    assert plan.status_code == 200, plan.text
    data = plan.json()
    assert data["verdict"] == "DELOAD"
    assert "Old standard heavy strength" not in {slot["title"] for slot in data["sessions"]}
    assert any(slot["title"] == "Mobility + technique" for slot in data["sessions"])


def test_refresh_recommendation_preserves_trainer_edited_plan(app_with_db, monkeypatch):
    today = date.today()
    week_of = today - timedelta(days=today.weekday())

    with connect(recommendation_routes.DEFAULT_DB_PATH, read_only=False) as con:
        ensure_client(con, DEFAULT_TRAINER_ID, "c_trainer_plan", name="Trainer Plan")
        insert_recommendation(
            con,
            DEFAULT_TRAINER_ID,
            Recommendation(
                id="rec_trainer_plan_old",
                client_id="c_trainer_plan",
                generated_at=datetime.now(),
                week_of=week_of,
                recommendation="Standard progression per ACSM 11e: increase load 5-10%.",
                rationale="Old weekly snapshot.",
                source_metric_ids=[],
                confidence=0.78,
            ),
        )
        insert_plan(
            con,
            DEFAULT_TRAINER_ID,
            [
                PlannedSession(
                    id="p_trainer_plan_1",
                    client_id="c_trainer_plan",
                    week_of=week_of,
                    slot=1,
                    type=SessionType.STRENGTH,
                    title="Trainer custom strength adjustment",
                    description="The trainer already edited this plan for real-life constraints.",
                    target_duration_min=45,
                    target_load_au=180,
                    target_rpe=4,
                    contraindications=[],
                    source=PlanSource.TRAINER,
                    generated_at=datetime.now(),
                    executed_session_id=None,
                )
            ],
        )

    def deload_recommendation(client_id, metrics, sessions, today=None, thresholds=None):
        today = today or date.today()
        return Recommendation(
            id="rec_trainer_plan_new",
            client_id=client_id,
            generated_at=datetime.now(),
            week_of=today - timedelta(days=today.weekday()),
            recommendation="Deload week: reduce training load by 40%.",
            rationale="Flags: hrv_below_baseline.",
            source_metric_ids=[],
            confidence=0.9,
        )

    monkeypatch.setattr(recommendation_routes, "generate_recommendation", deload_recommendation)

    refreshed = app_with_db.post("/api/clients/c_trainer_plan/recommendation/refresh")
    assert refreshed.status_code == 200, refreshed.text

    plan = app_with_db.get("/api/clients/c_trainer_plan/plan")

    assert plan.status_code == 200, plan.text
    data = plan.json()
    assert data["verdict"] == "DELOAD"
    assert data["sessions"] == [
        {
            "id": "p_trainer_plan_1",
            "client_id": "c_trainer_plan",
            "week_of": str(week_of),
            "slot": 1,
            "type": "strength",
            "title": "Trainer custom strength adjustment",
            "description": "The trainer already edited this plan for real-life constraints.",
            "target_duration_min": 45,
            "target_load_au": 180,
            "target_rpe": 4.0,
            "contraindications": [],
            "source": "trainer",
            "generated_at": data["sessions"][0]["generated_at"],
            "executed_session_id": None,
        }
    ]


def test_override_roundtrip(app_with_db):
    payload = {
        "week_of": str(date.today()),
        "system_recommendation": "Standard progression per ACSM 11e: increase load 5-10%.",
        "system_confidence": 0.78,
        "trainer_action": "accept",
        "applied_load_change_pct": None,
        "trainer_note": "looks fine",
    }
    post = app_with_db.post("/api/clients/c_test/overrides", json=payload)
    assert post.status_code == 200, post.text
    ov = post.json()
    assert ov["trainer_action"] == "accept"

    get = app_with_db.get("/api/clients/c_test/overrides")
    assert get.status_code == 200
    rows = get.json()
    assert any(r["id"] == ov["id"] for r in rows)


def test_calibration_with_one_override(app_with_db):
    # Seed an override first.
    payload = {
        "week_of": str(date.today()),
        "system_recommendation": "Deload week: reduce training load by 20%.",
        "system_confidence": 0.85,
        "trainer_action": "reject",
        "applied_load_change_pct": None,
        "trainer_note": "client felt great, kept training",
    }
    app_with_db.post("/api/clients/c_test/overrides", json=payload)

    r = app_with_db.get("/api/calibration")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 1
    assert data["rejects"] >= 1
    assert "Deload" in data["matrix"]
    # Upgrade fields all present even with one override.
    assert "by_week" in data and len(data["by_week"]) >= 1
    assert "by_client" in data and len(data["by_client"]) >= 1
    assert "suggestions" in data  # may be empty when sample size is small


def test_calibration_suggests_threshold_tune_after_repeat_deload_pushback(app_with_db):
    """Seed 4 deload calls that the trainer rejected. The suggestions
    engine should pick up the pattern and recommend raising the HRV
    severity thresholds."""
    base_week = date.today() - timedelta(weeks=4)
    for i in range(4):
        app_with_db.post("/api/clients/c_test/overrides", json={
            "week_of": str(base_week + timedelta(weeks=i)),
            "system_recommendation": "Deload week: reduce training load by 20%.",
            "system_confidence": 0.85,
            "trainer_action": "reject",
            "applied_load_change_pct": None,
            "trainer_note": f"week {i} reject",
        })

    data = app_with_db.get("/api/calibration").json()
    kinds = {s["kind"] for s in data["suggestions"]}
    assert "threshold_tune" in kinds
    msg = " ".join(s["message"] for s in data["suggestions"] if s["kind"] == "threshold_tune")
    assert "deload" in msg.lower() or "hrv" in msg.lower()


def test_calibration_by_client_includes_names(app_with_db):
    """Per-client rows surface the client's display name (from the
    clients table) so the frontend doesn't have to do a second lookup."""
    app_with_db.post("/api/clients/c_test/overrides", json={
        "week_of": str(date.today()),
        "system_recommendation": "Standard progression per ACSM 11e: increase load 5-10%.",
        "system_confidence": 0.78,
        "trainer_action": "accept",
        "applied_load_change_pct": None,
        "trainer_note": None,
    })

    by_client = app_with_db.get("/api/calibration").json()["by_client"]
    me = next(c for c in by_client if c["client_id"] == "c_test")
    assert me["name"] == "Test Client"
    assert me["total"] >= 1
    assert 0.0 <= me["accept_rate"] <= 1.0


def test_pdf_endpoint_returns_pdf_bytes(app_with_db):
    r = app_with_db.post(
        "/api/clients/c_test/pdf",
        json={"coach_message": "Great work this week."},
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    assert "attachment" in r.headers.get("content-disposition", "")


def test_pdf_endpoint_rejects_oversized_coach_message(app_with_db):
    r = app_with_db.post(
        "/api/clients/c_test/pdf",
        json={"coach_message": "x" * 501},
    )
    assert r.status_code == 422


def test_pdf_endpoint_uses_stored_weekly_recommendation(app_with_db, monkeypatch):
    """PDF export should render the same weekly recommendation the
    dashboard/share surfaces use, not recompute a route-local verdict."""
    week_of = date.today() - timedelta(days=date.today().weekday())
    stored = Recommendation(
        id="rec_pdf_sentinel",
        client_id="c_test",
        generated_at=datetime.now(),
        week_of=week_of,
        recommendation="Sentinel stored verdict for PDF export.",
        rationale="Stored rationale should travel with the export.",
        source_metric_ids=["m-hrv-1"],
        confidence=0.42,
    )
    with connect(recommendation_routes.DEFAULT_DB_PATH, read_only=False) as con:
        insert_recommendation(con, DEFAULT_TRAINER_ID, stored)

    captured: dict[str, Recommendation] = {}

    def fake_build_weekly_pdf(*, client_name, client_goal, rec, metrics, today=None, coach_message=None):
        captured["rec"] = rec
        return b"%PDF-1.4\n%%EOF"

    monkeypatch.setattr(pdf_routes, "build_weekly_pdf", fake_build_weekly_pdf)

    r = app_with_db.post("/api/clients/c_test/pdf", json={"coach_message": None})

    assert r.status_code == 200, r.text
    assert captured["rec"].id == "rec_pdf_sentinel"
    assert captured["rec"].recommendation == "Sentinel stored verdict for PDF export."
    assert captured["rec"].confidence == 0.42


def test_post_client_creates_row(app_with_db):
    payload = {
        "name": "New Client",
        "sex": "F",
        "age": 31,
        "height_cm": 168.0,
        "weight_kg": 62.0,
        "goal": "Half marathon Q3",
        "injury_history": None,
    }
    r = app_with_db.post("/api/clients", json=payload)
    assert r.status_code == 200, r.text
    new_id = r.json()["id"]
    assert new_id.startswith("c_")

    # Confirm it actually landed in the roster.
    listed = app_with_db.get("/api/clients").json()
    assert any(c["id"] == new_id for c in listed)

    detail = app_with_db.get(f"/api/clients/{new_id}").json()
    assert detail["name"] == "New Client"
    assert detail["sex"] == "F"
    assert detail["goal"] == "Half marathon Q3"


def test_post_client_validates_ranges(app_with_db):
    bad = {
        "name": "Bad", "sex": "F", "age": 5,  # below range
        "height_cm": 165.0, "weight_kg": 60.0, "goal": "x",
    }
    assert app_with_db.post("/api/clients", json=bad).status_code == 422


def test_patch_client_partial_update(app_with_db):
    # The fixture seeds c_test as "Test Client". Rename + change goal,
    # leave the other fields untouched and confirm they survive.
    r = app_with_db.patch(
        "/api/clients/c_test", json={"name": "Renamed Client", "goal": "Strength + GPP"}
    )
    assert r.status_code == 200, r.text
    assert set(r.json()["updated"]) == {"name", "goal"}

    detail = app_with_db.get("/api/clients/c_test").json()
    assert detail["name"] == "Renamed Client"
    assert detail["goal"] == "Strength + GPP"
    # Age, height, weight from the fixture's ensure_client call must
    # still be there.
    assert detail["age"] == 30


def test_patch_client_404_for_unknown(app_with_db):
    r = app_with_db.patch("/api/clients/c_missing", json={"name": "Nope"})
    assert r.status_code == 404


def test_patch_client_noop_returns_ok(app_with_db):
    r = app_with_db.patch("/api/clients/c_test", json={})
    assert r.status_code == 200
    assert r.json()["updated"] == []


def test_thresholds_get_returns_defaults_and_overrides(app_with_db):
    r = app_with_db.get("/api/clients/c_test/thresholds")
    assert r.status_code == 200
    data = r.json()
    assert "defaults" in data and "overrides" in data
    assert data["defaults"]["hrv_mild_sd"] == 0.5
    assert data["overrides"] == {}


def test_thresholds_patch_upsert_and_revert(app_with_db):
    # Upsert two overrides.
    r = app_with_db.patch(
        "/api/clients/c_test/thresholds",
        json={"overrides": {"hrv_mild_sd": 0.7, "sleep_floor_hours": 6.5}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["overrides"] == {"hrv_mild_sd": 0.7, "sleep_floor_hours": 6.5}

    # Update one + revert the other to default in the same call.
    r = app_with_db.patch(
        "/api/clients/c_test/thresholds",
        json={"overrides": {"hrv_mild_sd": 0.6, "sleep_floor_hours": None}},
    )
    assert r.json()["overrides"] == {"hrv_mild_sd": 0.6}


def test_thresholds_patch_rejects_unknown_keys(app_with_db):
    r = app_with_db.patch(
        "/api/clients/c_test/thresholds",
        json={"overrides": {"bogus_threshold": 1.0}},
    )
    assert r.status_code == 400
    assert "Unknown threshold" in r.json()["detail"]


def test_thresholds_patch_rejects_out_of_range_value(app_with_db):
    r = app_with_db.patch(
        "/api/clients/c_test/thresholds",
        json={"overrides": {"hrv_severe_sd": -2.0}},
    )
    assert r.status_code == 400
    assert "out of range" in r.json()["detail"]


def test_thresholds_patch_rejects_misordered_ladder(app_with_db):
    # A sparse patch is validated against the (untouched) moderate/severe
    # defaults — pushing mild above moderate is rejected.
    r = app_with_db.patch(
        "/api/clients/c_test/thresholds",
        json={"overrides": {"hrv_mild_sd": 2.0}},
    )
    assert r.status_code == 400
    assert "strictly less than" in r.json()["detail"]


def test_metrics_days_out_of_bounds_rejected(app_with_db):
    assert app_with_db.get("/api/clients/c_test/metrics?days=0").status_code == 422
    assert app_with_db.get("/api/clients/c_test/metrics?days=91").status_code == 422
    # In-bounds still works.
    assert app_with_db.get("/api/clients/c_test/metrics?days=35").status_code == 200


def test_recommendation_history_limit_out_of_bounds_rejected(app_with_db):
    assert app_with_db.get("/api/clients/c_test/recommendations?limit=0").status_code == 422
    assert app_with_db.get("/api/clients/c_test/recommendations?limit=101").status_code == 422
    assert app_with_db.get("/api/clients/c_test/recommendations?limit=12").status_code == 200


def test_upload_apple_health_xml(app_with_db, tmp_path: Path):
    xml = """<?xml version="1.0"?>
<HealthData>
<Record type="HKQuantityTypeIdentifierRestingHeartRate" value="55" startDate="2026-05-22 07:00:00 -0700" endDate="2026-05-22 07:00:01 -0700" unit="count/min"/>
</HealthData>"""
    files = {"file": ("export.xml", xml.encode(), "application/xml")}
    r = app_with_db.post("/api/clients/c_test/upload", files=files)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["inserted"] == 1
    assert "resting_hr" in data["kinds"]


def test_upload_rejects_cross_trainer_client_id(app_with_db):
    with connect(clients_routes.DEFAULT_DB_PATH, read_only=False) as con:
        insert_trainer(con, "t_other", "other@example.com", "Other")
        ensure_client(con, "t_other", "c_other", name="Other Client")

    xml = """<?xml version="1.0"?>
<HealthData>
<Record type="HKQuantityTypeIdentifierRestingHeartRate" value="55" startDate="2026-05-22 07:00:00 -0700" endDate="2026-05-22 07:00:01 -0700" unit="count/min"/>
</HealthData>"""
    files = {"file": ("export.xml", xml.encode(), "application/xml")}
    r = app_with_db.post("/api/clients/c_other/upload", files=files)
    assert r.status_code == 404


def test_upload_checks_client_ownership_before_parsing_file(app_with_db):
    with connect(clients_routes.DEFAULT_DB_PATH, read_only=False) as con:
        insert_trainer(con, "t_other", "other2@example.com", "Other")
        ensure_client(con, "t_other", "c_other", name="Other Client")

    files = {"file": ("notes.txt", b"not a wearable export", "text/plain")}
    r = app_with_db.post("/api/clients/c_other/upload", files=files)
    assert r.status_code == 404


def test_upload_rejects_files_over_size_limit(app_with_db, monkeypatch):
    monkeypatch.setattr(metrics_routes, "MAX_UPLOAD_BYTES", 8)
    files = {"file": ("export.xml", b"x" * 9, "application/xml")}
    r = app_with_db.post("/api/clients/c_test/upload", files=files)
    assert r.status_code == 413


def test_override_rejects_cross_trainer_client_id(app_with_db):
    with connect(clients_routes.DEFAULT_DB_PATH, read_only=False) as con:
        insert_trainer(con, "t_other", "other@example.com", "Other")
        ensure_client(con, "t_other", "c_other", name="Other Client")

    r = app_with_db.post("/api/clients/c_other/overrides", json={
        "week_of": str(date.today()),
        "system_recommendation": "Standard progression per ACSM 11e: increase load 5-10%.",
        "system_confidence": 0.78,
        "trainer_action": "accept",
        "applied_load_change_pct": None,
        "trainer_note": None,
    })
    assert r.status_code == 404
