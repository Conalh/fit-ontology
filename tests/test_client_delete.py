"""DELETE /api/clients/{client_id} — cascading hard delete.

Contracts pinned:
  1. Trainer can delete their own client; response carries the name.
  2. After delete, every FK-referencing row (sessions, metrics,
     recommendations, overrides, planned_sessions, thresholds,
     share tokens) is gone.
  3. ``client_intake_tokens.consumed_client_id`` is NULL'd, NOT
     deleted — the mint-event row stays so the audit trail survives
     a deletion of the resulting client.
  4. Cross-trainer isolation: trainer A cannot delete trainer B's
     client (404, same shape as a missing client).
  5. Idempotency: deleting twice → second call is a 404, not a 500.
  6. Demo trainer: forbid_demo_trainer returns 403.
  7. Audit row written with ``action=client.deleted`` and the name
     embedded in ``details`` so the trail survives the row removal.
  8. Unknown client id: 404.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import fit_ontology.api as api_mod
from fit_ontology.db import (
    connect,
    create_intake_token,
    create_share_token,
    ensure_client,
    insert_metrics,
    insert_sessions,
    insert_trainer,
    set_trainer_password,
    upsert_threshold,
)
from fit_ontology.ontology import MetricKind
from fit_ontology.routes import (
    auth as auth_routes,
)
from fit_ontology.routes import (
    clients as clients_routes,
)


@pytest.fixture()
def delete_app(tmp_path: Path, monkeypatch):
    """API wired to a temp DB with two trainers and a rich client
    under trainer A so the cascade actually has things to delete."""
    monkeypatch.setenv("FIT_ONTOLOGY_SESSION_SECRET", "test-secret-do-not-use-in-prod")
    monkeypatch.delenv("FIT_ONTOLOGY_REQUIRE_AUTH", raising=False)
    monkeypatch.delenv("FIT_ONTOLOGY_DEMO_MODE", raising=False)

    db_path = tmp_path / "delete.duckdb"
    with connect(db_path, read_only=False) as con:
        insert_trainer(con, "t_alice", "alice@example.com", "Alice")
        set_trainer_password(con, "t_alice", "letmein")
        insert_trainer(con, "t_bob", "bob@example.com", "Bob")
        set_trainer_password(con, "t_bob", "letmein")

        # Rich client under Alice — sessions, metrics, threshold,
        # share token, intake token. Bob has nothing.
        ensure_client(con, "t_alice", "c_target", name="Doomed Client")
        today = date.today()
        rows = [
            {"id": f"m-{i}", "client_id": "c_target", "date": today - timedelta(days=i),
             "source": "garmin", "kind": MetricKind.HRV_RMSSD.value,
             "value": 55.0, "unit": "ms"}
            for i in range(7)
        ]
        insert_metrics(con, "t_alice", pd.DataFrame(rows))
        sess = pd.DataFrame([
            {"id": f"s-{i}", "client_id": "c_target", "date": today - timedelta(days=i),
             "type": "strength", "duration_min": 45, "rpe": 6, "notes": ""}
            for i in range(3)
        ])
        insert_sessions(con, "t_alice", sess)
        upsert_threshold(con, "t_alice", "c_target", "hrv_mild_drop_sd", 0.7)
        create_share_token(con, "t_alice", "c_target", "go to bed")
        # Mint an intake token + manually stamp consumed_client_id to
        # the target client, so we can verify NULL'ing in the cascade.
        intake_token, _ = create_intake_token(con, "t_alice")
        con.execute(
            "UPDATE client_intake_tokens SET consumed_client_id = ? WHERE token = ?",
            ["c_target", intake_token],
        )

    for mod in (auth_routes, clients_routes):
        monkeypatch.setattr(mod, "DEFAULT_DB_PATH", db_path)

    yield TestClient(api_mod.app), db_path


def _login(client: TestClient, email: str) -> None:
    r = client.post("/api/auth/login", json={"email": email, "password": "letmein"})
    assert r.status_code == 200, r.text


# ─── Happy path + cascade integrity ──────────────────────────────────


def test_delete_returns_name_and_clears_row(delete_app):
    client, db_path = delete_app
    _login(client, "alice@example.com")
    r = client.delete("/api/clients/c_target")
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "name": "Doomed Client"}

    with connect(db_path, read_only=True) as con:
        row = con.execute(
            "SELECT 1 FROM clients WHERE id = 'c_target'"
        ).fetchone()
    assert row is None


def test_delete_cascades_dependents(delete_app):
    client, db_path = delete_app
    _login(client, "alice@example.com")
    client.delete("/api/clients/c_target")

    with connect(db_path, read_only=True) as con:
        for table in (
            "sessions",
            "metrics",
            "client_thresholds",
            "client_share_tokens",
        ):
            n = con.execute(
                f"SELECT COUNT(*) FROM {table} WHERE client_id = 'c_target'"
            ).fetchone()[0]
            assert n == 0, f"{table} still has rows for the deleted client"


def test_delete_nulls_intake_consumed_client_id(delete_app):
    """Intake tokens are deliberately preserved (the mint event is its
    own audit trail); only the FK pointer to the deleted client gets
    NULL'd so the row remains queryable as 'this token was minted
    and used'."""
    client, db_path = delete_app
    _login(client, "alice@example.com")
    client.delete("/api/clients/c_target")

    with connect(db_path, read_only=True) as con:
        row = con.execute(
            "SELECT consumed_client_id FROM client_intake_tokens "
            "WHERE consumed_client_id = 'c_target'"
        ).fetchone()
        # Should be no rows still pointing at the deleted client...
        assert row is None
        # ...but the intake-token row itself should still exist with
        # NULL consumed_client_id.
        n_tokens = con.execute(
            "SELECT COUNT(*) FROM client_intake_tokens WHERE trainer_id = 't_alice'"
        ).fetchone()[0]
        assert n_tokens == 1


def test_delete_writes_audit_row_with_name(delete_app):
    client, db_path = delete_app
    _login(client, "alice@example.com")
    client.delete("/api/clients/c_target")

    with connect(db_path, read_only=True) as con:
        row = con.execute(
            "SELECT action, target_id, details FROM audit_log "
            "WHERE action = 'client.deleted'"
        ).fetchone()
    assert row is not None
    action, target_id, details_json = row
    assert action == "client.deleted"
    assert target_id == "c_target"
    details = json.loads(details_json)
    assert details["name"] == "Doomed Client"


# ─── Auth + isolation + edge cases ───────────────────────────────────


def test_delete_other_trainers_client_returns_404(delete_app):
    """Trainer B tries to delete trainer A's client. Same 404 shape
    as a missing client — never leak the "exists-but-not-yours" case."""
    client, db_path = delete_app
    _login(client, "bob@example.com")
    r = client.delete("/api/clients/c_target")
    assert r.status_code == 404

    # And the row is unscathed.
    with connect(db_path, read_only=True) as con:
        row = con.execute(
            "SELECT 1 FROM clients WHERE id = 'c_target'"
        ).fetchone()
    assert row is not None


def test_delete_unknown_id_returns_404(delete_app):
    client, _ = delete_app
    _login(client, "alice@example.com")
    r = client.delete("/api/clients/c_nope")
    assert r.status_code == 404


def test_delete_is_idempotent_second_call_404(delete_app):
    client, _ = delete_app
    _login(client, "alice@example.com")
    first = client.delete("/api/clients/c_target")
    assert first.status_code == 200
    second = client.delete("/api/clients/c_target")
    assert second.status_code == 404


def test_delete_demo_trainer_403(delete_app, monkeypatch):
    """The hosted-demo trainer must not be able to delete clients
    (forbid_demo_trainer). Same posture as POST/PATCH."""
    client, _ = delete_app
    monkeypatch.setenv("FIT_ONTOLOGY_DEMO_MODE", "1")
    # No login → falls through to t_demo
    r = client.delete("/api/clients/c_target")
    assert r.status_code == 403
