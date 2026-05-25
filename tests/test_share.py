"""Phase 3a share-token surface.

Eight contracts pinned:
  1. Helper roundtrip — create_share_token + share_lookup return the
     same token + trainer_id + client_id + message.
  2. Expired tokens are flagged ``expired=True`` rather than returning
     None (so the route can emit 410 vs 404).
  3. Unknown tokens return None.
  4. Cross-trainer mint is rejected — trainer A cannot mint a share
     for trainer B's client even with a known client_id.
  5. revoke_share_token works only for the owning trainer.
  6. POST /api/clients/{id}/share is trainer-scoped — a session cookie
     for trainer A can't mint a share for trainer B's client_id.
  7. GET /api/share/{token} is public — works with NO session cookie.
  8. The public payload omits intake PII (sex, age, weight, injury).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import fit_ontology.api as api_mod
from fit_ontology.db import (
    DEFAULT_TRAINER_ID,
    connect,
    create_share_token,
    ensure_client,
    insert_metrics,
    insert_sessions,
    insert_trainer,
    revoke_share_token,
    set_trainer_password,
    share_lookup,
)
from fit_ontology.ontology import MetricKind
from fit_ontology.routes import (
    auth as auth_routes,
    clients as clients_routes,
    metrics as metrics_routes,
    overrides as overrides_routes,
    recommendation as recommendation_routes,
    share as share_routes,
    thresholds as thresholds_routes,
)


# ─── Helper-level tests ───────────────────────────────────────────────


def _seed_with_client(db_path: Path) -> tuple[str, str]:
    """Standard fixture: default trainer + one client + a week of metrics
    so the public share view has something to render. Returns
    (trainer_id, client_id)."""
    with connect(db_path, read_only=False) as con:
        ensure_client(con, DEFAULT_TRAINER_ID, "c_test", name="Test Client")
        today = date.today()
        rows = []
        for offset in range(14, 0, -1):
            d = today - timedelta(days=offset)
            rows.append({
                "id": f"m-hrv-{offset}", "client_id": "c_test", "date": d,
                "source": "garmin", "kind": MetricKind.HRV_RMSSD.value,
                "value": 55.0, "unit": "ms",
            })
        insert_metrics(con, DEFAULT_TRAINER_ID, pd.DataFrame(rows))
        sess = pd.DataFrame([
            {"id": f"s-{i}", "client_id": "c_test", "date": today - timedelta(days=i*2),
             "type": "strength", "duration_min": 45, "rpe": 6, "notes": ""}
            for i in range(3)
        ])
        insert_sessions(con, DEFAULT_TRAINER_ID, sess)
    return DEFAULT_TRAINER_ID, "c_test"


def test_create_then_lookup_roundtrip(tmp_path: Path):
    db_path = tmp_path / "share.duckdb"
    trainer_id, client_id = _seed_with_client(db_path)

    with connect(db_path, read_only=False) as con:
        token, expires_at = create_share_token(con, trainer_id, client_id, "be in bed by 10pm")
        assert isinstance(token, str) and len(token) >= 32
        assert expires_at > datetime.utcnow()

    with connect(db_path, read_only=True) as con:
        record = share_lookup(con, token)

    assert record is not None
    assert record["trainer_id"] == trainer_id
    assert record["client_id"] == client_id
    assert record["trainer_message"] == "be in bed by 10pm"
    assert record["expired"] is False


def test_expired_token_is_flagged_not_hidden(tmp_path: Path):
    """Expired tokens still return a record — the route uses the
    ``expired`` flag to choose 410 (Gone) over 404. If share_lookup
    just returned None we'd lose that distinction."""
    db_path = tmp_path / "share.duckdb"
    trainer_id, client_id = _seed_with_client(db_path)

    with connect(db_path, read_only=False) as con:
        token, _ = create_share_token(con, trainer_id, client_id, None)
        # Hand-roll a past expiry to simulate token aging.
        con.execute(
            "UPDATE client_share_tokens SET expires_at = ? WHERE token = ?",
            [datetime.utcnow() - timedelta(days=1), token],
        )

    with connect(db_path, read_only=True) as con:
        record = share_lookup(con, token)

    assert record is not None
    assert record["expired"] is True


def test_unknown_token_returns_none(tmp_path: Path):
    db_path = tmp_path / "share.duckdb"
    _seed_with_client(db_path)
    with connect(db_path, read_only=True) as con:
        assert share_lookup(con, "not-a-real-token") is None


def test_cross_trainer_mint_is_rejected(tmp_path: Path):
    db_path = tmp_path / "share.duckdb"
    # Two trainers, one client each. Trainer B tries to mint a share
    # for trainer A's client — the helper must say no, otherwise a
    # leaked client_id lets a different trainer publish someone else's
    # weekly report.
    with connect(db_path, read_only=False) as con:
        insert_trainer(con, "t_a", "a@example.com", "A")
        insert_trainer(con, "t_b", "b@example.com", "B")
        ensure_client(con, "t_a", "c_a", name="A's client")
        with pytest.raises(ValueError):
            create_share_token(con, "t_b", "c_a", None)


def test_revoke_only_for_owning_trainer(tmp_path: Path):
    db_path = tmp_path / "share.duckdb"
    with connect(db_path, read_only=False) as con:
        insert_trainer(con, "t_a", "a@example.com", "A")
        insert_trainer(con, "t_b", "b@example.com", "B")
        ensure_client(con, "t_a", "c_a", name="A's client")
        token, _ = create_share_token(con, "t_a", "c_a", None)
        # Trainer B can't kill A's link.
        assert revoke_share_token(con, "t_b", token) is False
        # But trainer A can.
        assert revoke_share_token(con, "t_a", token) is True
        # And it's actually gone.
        assert share_lookup(con, token) is None


# ─── HTTP surface tests ───────────────────────────────────────────────


@pytest.fixture()
def share_app(tmp_path: Path, monkeypatch):
    """API wired to a temp DB with one trainer + one client + metrics.
    Session secret pinned so the test trainer's cookie is reproducible."""
    monkeypatch.setenv("FIT_ONTOLOGY_SESSION_SECRET", "test-secret-do-not-use-in-prod")
    monkeypatch.delenv("FIT_ONTOLOGY_REQUIRE_AUTH", raising=False)

    db_path = tmp_path / "share.duckdb"
    with connect(db_path, read_only=False) as con:
        insert_trainer(con, "t_test", "conal@example.com", "Conal Test")
        set_trainer_password(con, "t_test", "letmein")
        ensure_client(con, "t_test", "c_owned", name="Test Client")
        today = date.today()
        rows = []
        for offset in range(14, 0, -1):
            d = today - timedelta(days=offset)
            rows.append({
                "id": f"m-{offset}", "client_id": "c_owned", "date": d,
                "source": "garmin", "kind": MetricKind.HRV_RMSSD.value,
                "value": 55.0, "unit": "ms",
            })
        insert_metrics(con, "t_test", pd.DataFrame(rows))
        sess = pd.DataFrame([
            {"id": f"s-{i}", "client_id": "c_owned", "date": today - timedelta(days=i*2),
             "type": "strength", "duration_min": 45, "rpe": 6, "notes": ""}
            for i in range(3)
        ])
        insert_sessions(con, "t_test", sess)

    for mod in (
        clients_routes, metrics_routes, overrides_routes, recommendation_routes,
        thresholds_routes, auth_routes, share_routes,
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
        yield TestClient(api_mod.app)
    finally:
        api_mod.app.dependency_overrides.pop(api_mod._read_only_conn, None)


def _login(client: TestClient) -> None:
    r = client.post("/api/auth/login", json={"email": "conal@example.com", "password": "letmein"})
    assert r.status_code == 200, r.text


def test_post_share_requires_owning_trainer(share_app):
    """Without a session cookie, POST /share falls back to the default
    trainer (per current_trainer_id's dev-mode fallback) — which is
    NOT t_test. The default trainer doesn't own c_owned, so 404."""
    r = share_app.post("/api/clients/c_owned/share", json={"trainer_message": None})
    assert r.status_code == 404


def test_post_share_works_for_owning_trainer(share_app):
    _login(share_app)
    r = share_app.post(
        "/api/clients/c_owned/share",
        json={"trainer_message": "stay consistent with sleep this week"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert "token" in data and len(data["token"]) >= 32
    assert "expires_at" in data


def test_get_share_is_public(share_app):
    """GET /api/share/{token} works WITHOUT a session cookie — that's
    the whole point of the share view (client opens it on their phone
    with no account)."""
    _login(share_app)
    create = share_app.post(
        "/api/clients/c_owned/share",
        json={"trainer_message": "looking strong"},
    )
    token = create.json()["token"]
    # Drop the session cookie before the public read.
    share_app.cookies.clear()

    r = share_app.get(f"/api/share/{token}")
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["client_first_name"] == "Test"  # "Test Client" → first word
    assert payload["trainer_message"] == "looking strong"
    assert "recommendation" in payload and payload["recommendation"]


def test_get_share_omits_pii(share_app):
    """Defense in depth: the public payload must not carry intake
    fields a client doesn't need from a weekly share. If a future
    refactor expands the schema, this test fails loud."""
    _login(share_app)
    token = share_app.post(
        "/api/clients/c_owned/share", json={"trainer_message": None},
    ).json()["token"]
    share_app.cookies.clear()

    payload = share_app.get(f"/api/share/{token}").json()
    forbidden = {"sex", "age", "height_cm", "weight_kg", "injury_history", "email"}
    leaked = forbidden & set(payload.keys())
    assert not leaked, f"share payload leaked PII fields: {leaked}"


def test_get_share_returns_404_for_unknown_token(share_app):
    r = share_app.get("/api/share/this-token-does-not-exist")
    assert r.status_code == 404


def test_get_share_returns_410_for_expired_token(share_app, tmp_path: Path, monkeypatch):
    """Mint a real token, then fast-forward its expires_at into the
    past via raw SQL — the GET should distinguish "expired" from
    "missing" by returning 410 rather than 404."""
    _login(share_app)
    token = share_app.post(
        "/api/clients/c_owned/share", json={"trainer_message": None},
    ).json()["token"]
    share_app.cookies.clear()

    # Find the DB the routes are pointing at and age the token.
    db_path = clients_routes.DEFAULT_DB_PATH
    with connect(db_path, read_only=False) as con:
        con.execute(
            "UPDATE client_share_tokens SET expires_at = ? WHERE token = ?",
            [datetime.utcnow() - timedelta(days=1), token],
        )

    r = share_app.get(f"/api/share/{token}")
    assert r.status_code == 410
