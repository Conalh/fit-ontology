"""Phase 5a — audit log + rate limiting + security headers.

Three concerns, one test file because each one is small and they
share the same TestClient fixture.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import fit_ontology.api as api_mod
from fit_ontology.db import (
    DEFAULT_TRAINER_ID,
    audit_log_for_trainer,
    connect,
    ensure_client,
    insert_metrics,
    insert_sessions,
    insert_trainer,
    set_trainer_password,
)
from fit_ontology.ontology import MetricKind
from fit_ontology.rate_limit import reset as rate_limit_reset
from fit_ontology.routes import (
    auth as auth_routes,
    clients as clients_routes,
    metrics as metrics_routes,
    overrides as overrides_routes,
    planning as planning_routes,
    recommendation as recommendation_routes,
    share as share_routes,
    thresholds as thresholds_routes,
)


@pytest.fixture()
def app(tmp_path: Path, monkeypatch):
    """Temp DB + one logged-in trainer + one client + a week of metrics.
    Pinned session secret so cookies are reproducible; rate-limit
    buckets reset between tests so /ask + /share don't leak state."""
    monkeypatch.setenv("FIT_ONTOLOGY_SESSION_SECRET", "test-secret")
    monkeypatch.delenv("FIT_ONTOLOGY_REQUIRE_AUTH", raising=False)
    monkeypatch.delenv("FIT_ONTOLOGY_SESSION_SECURE", raising=False)
    rate_limit_reset()

    db_path = tmp_path / "sec.duckdb"
    with connect(db_path, read_only=False) as con:
        insert_trainer(con, "t_test", "conal@example.com", "Conal Test")
        set_trainer_password(con, "t_test", "letmein")
        ensure_client(con, "t_test", "c_owned", name="Test Client")
        today = date.today()
        rows = []
        for off in range(14, 0, -1):
            d = today - timedelta(days=off)
            rows.append({
                "id": f"m-{off}", "client_id": "c_owned", "date": d,
                "source": "garmin", "kind": MetricKind.HRV_RMSSD.value,
                "value": 55.0, "unit": "ms",
            })
        insert_metrics(con, "t_test", pd.DataFrame(rows))
        # Sessions too, so plan generation has something to anchor on.
        sess = pd.DataFrame([
            {"id": f"s-{i}", "client_id": "c_owned",
             "date": today - timedelta(days=i*2),
             "type": "strength", "duration_min": 45, "rpe": 6, "notes": ""}
            for i in range(3)
        ])
        insert_sessions(con, "t_test", sess)

    for mod in (
        clients_routes, metrics_routes, overrides_routes,
        recommendation_routes, thresholds_routes,
        auth_routes, share_routes, planning_routes,
    ):
        monkeypatch.setattr(mod, "DEFAULT_DB_PATH", db_path)

    def _ro():
        c = connect(db_path, read_only=True)
        try:
            yield c
        finally:
            c.close()

    api_mod.app.dependency_overrides[api_mod._read_only_conn] = _ro
    try:
        client = TestClient(api_mod.app)
        client.post("/api/auth/login", json={"email": "conal@example.com", "password": "letmein"})
        yield client, db_path
    finally:
        api_mod.app.dependency_overrides.pop(api_mod._read_only_conn, None)
        rate_limit_reset()


# ─── Audit log ────────────────────────────────────────────────────────


def test_login_writes_audit_row(app):
    client, db_path = app
    # The fixture itself performed a login — find it in the log.
    with connect(db_path, read_only=True) as con:
        rows = audit_log_for_trainer(con, "t_test")
    assert any(r["action"] == "auth.login" for r in rows)


def test_logout_writes_audit_row(app):
    client, db_path = app
    r = client.post("/api/auth/logout")
    assert r.status_code == 200
    with connect(db_path, read_only=True) as con:
        rows = audit_log_for_trainer(con, "t_test")
    assert any(r["action"] == "auth.logout" for r in rows)


def test_client_create_writes_audit_row(app):
    client, db_path = app
    r = client.post("/api/clients", json={
        "name": "New Person", "sex": "F", "age": 30,
        "height_cm": 168.0, "weight_kg": 60.0, "goal": "general fitness",
    })
    assert r.status_code == 200, r.text
    new_id = r.json()["id"]

    with connect(db_path, read_only=True) as con:
        rows = audit_log_for_trainer(con, "t_test")
    created = [r for r in rows if r["action"] == "client.created"]
    assert len(created) == 1
    assert created[0]["target_id"] == new_id
    assert created[0]["details"]["name"] == "New Person"


def test_override_save_writes_audit_row(app):
    client, db_path = app
    r = client.post("/api/clients/c_owned/overrides", json={
        "week_of": str(date.today()),
        "system_recommendation": "Standard progression",
        "system_confidence": 0.8,
        "trainer_action": "accept",
        "applied_load_change_pct": None,
        "trainer_note": None,
    })
    assert r.status_code == 200, r.text

    with connect(db_path, read_only=True) as con:
        rows = audit_log_for_trainer(con, "t_test")
    saved = [r for r in rows if r["action"] == "override.saved"]
    assert len(saved) == 1
    assert saved[0]["target_id"] == "c_owned"
    assert saved[0]["details"]["trainer_action"] == "accept"


def test_plan_edit_writes_audit_row(app):
    client, db_path = app
    # Generate the plan first so a slot exists to PATCH.
    client.get("/api/clients/c_owned/plan")

    r = client.patch("/api/clients/c_owned/plan/1", json={"title": "Edited title"})
    assert r.status_code == 200, r.text

    with connect(db_path, read_only=True) as con:
        rows = audit_log_for_trainer(con, "t_test")
    edits = [r for r in rows if r["action"] == "plan.edited"]
    assert len(edits) == 1
    assert edits[0]["target_id"] == "c_owned"
    assert edits[0]["details"]["slot"] == 1
    assert "title" in edits[0]["details"]["fields"]


def test_share_mint_writes_audit_row(app):
    client, db_path = app
    r = client.post("/api/clients/c_owned/share", json={"trainer_message": None})
    assert r.status_code == 200, r.text

    with connect(db_path, read_only=True) as con:
        rows = audit_log_for_trainer(con, "t_test")
    minted = [r for r in rows if r["action"] == "share.minted"]
    assert len(minted) == 1
    assert minted[0]["target_id"] == "c_owned"


def test_audit_log_is_trainer_scoped(tmp_path: Path):
    """audit_log_for_trainer must not leak across trainers — same gate
    as every other Phase 2a scoped helper."""
    db_path = tmp_path / "iso.duckdb"
    with connect(db_path, read_only=False) as con:
        insert_trainer(con, "t_a", "a@example.com", "A")
        insert_trainer(con, "t_b", "b@example.com", "B")
        from fit_ontology.db import record_audit
        record_audit(con, "t_a", "client.created", target_id="ca")
        record_audit(con, "t_b", "client.created", target_id="cb")

    with connect(db_path, read_only=True) as con:
        a_rows = audit_log_for_trainer(con, "t_a")
        b_rows = audit_log_for_trainer(con, "t_b")
    assert [r["target_id"] for r in a_rows] == ["ca"]
    assert [r["target_id"] for r in b_rows] == ["cb"]


# ─── Rate limiting ────────────────────────────────────────────────────


def test_share_mint_rate_limited(app, monkeypatch):
    """SHARE_MINT_LIMIT is 20/hour. Patch it down to 3 for the test so
    we don't have to fire 21 real share-creates."""
    from fit_ontology import rate_limit as rl_mod
    monkeypatch.setattr(rl_mod.SHARE_MINT_LIMIT, "max_attempts", 3)
    client, _ = app
    # 3 hits OK
    for _ in range(3):
        r = client.post("/api/clients/c_owned/share", json={"trainer_message": None})
        assert r.status_code == 200, r.text
    # 4th hit blocked
    r = client.post("/api/clients/c_owned/share", json={"trainer_message": None})
    assert r.status_code == 429


def test_login_rate_limit_blocks_after_threshold(tmp_path: Path, monkeypatch):
    """LOGIN_LIMIT is 10/minute. Patch to 2 to keep the test fast."""
    from fit_ontology import rate_limit as rl_mod
    monkeypatch.setattr(rl_mod.LOGIN_LIMIT, "max_attempts", 2)
    rl_mod.reset()

    # Point auth_routes at a fresh DB so login's verify path doesn't
    # hit whatever stale file lives at the default path. The rate
    # limiter runs before the DB lookup, so we don't even need to
    # seed a trainer — wrong-credential 401 still counts toward the
    # bucket and the test only cares about the 429 cutover.
    db_path = tmp_path / "ratelimit.duckdb"
    with connect(db_path, read_only=False):
        pass
    monkeypatch.setattr(auth_routes, "DEFAULT_DB_PATH", db_path)

    c = TestClient(api_mod.app)
    for _ in range(2):
        c.post("/api/auth/login", json={"email": "x@example.com", "password": "wrong"})
    r = c.post("/api/auth/login", json={"email": "x@example.com", "password": "wrong"})
    assert r.status_code == 429
    rl_mod.reset()


# ─── Security headers ─────────────────────────────────────────────────


def test_baseline_security_headers_present(app):
    client, _ = app
    r = client.get("/api/health")
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


def test_hsts_absent_without_secure_flag(app):
    client, _ = app
    r = client.get("/api/health")
    assert "Strict-Transport-Security" not in r.headers


def test_hsts_present_when_secure_flag_set(app, monkeypatch):
    monkeypatch.setenv("FIT_ONTOLOGY_SESSION_SECURE", "1")
    client, _ = app
    r = client.get("/api/health")
    assert r.headers.get("Strict-Transport-Security", "").startswith("max-age=")
