"""Phase 3b intake mint endpoint (M2 milestone).

Helper-level invariants are pinned in test_intake_tokens.py — this file
covers the HTTP surface that wraps them:

  POST /api/clients/intake/mint  (trainer-scoped, rate-limited, audited)

Public lookup + submit endpoints land in M3 and get their own file.

Contracts pinned here:
  1. Authed mint returns {token, expires_at} with a 32+ char token and
     an expiry in the future.
  2. trainer_message round-trips: passing it produces a row carrying
     the same string; omitting it produces NULL.
  3. Each successful mint writes an ``intake.minted`` audit row scoped
     to the calling trainer.
  4. Anonymous mint under REQUIRE_AUTH=1 (production posture) gets
     401 from current_trainer_id before the route body runs. In dev
     mode the default-trainer fallback kicks in; the env-var gate is
     what enforces "no cookie → no write" on hosted deploys.
  5. Demo trainer is refused (403) via forbid_demo_trainer — a hosted-
     demo visitor can't mint links that would create real clients
     under t_demo.
  6. Rate limit trips at the 21st call within the hour (matches
     INTAKE_MINT_LIMIT = 20/hour). Reset between tests so the bucket
     state doesn't bleed.
  7. trainer_message > 500 chars is rejected by Pydantic before the
     route body runs (422).
  8. Refactor regression: the existing POST /api/clients still creates
     a client and writes its audit row — proves insert_client_from_-
     payload didn't change the externally-observable behavior.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import fit_ontology.api as api_mod
import fit_ontology.rate_limit as rate_limit_mod
from fit_ontology.db import (
    connect,
    hash_token,
    insert_trainer,
    set_trainer_password,
)
from fit_ontology.routes import (
    auth as auth_routes,
)
from fit_ontology.routes import (
    clients as clients_routes,
)
from fit_ontology.routes import (
    intake as intake_routes,
)


@pytest.fixture()
def intake_app(tmp_path: Path, monkeypatch):
    """API wired to a temp DB with one trainer. No client rows needed —
    mint doesn't touch the clients table. The rate-limit module's
    in-process buckets are reset between tests so a prior test's 19
    mints don't sabotage a fresh 20-mint sequence."""
    monkeypatch.setenv("FIT_ONTOLOGY_SESSION_SECRET", "test-secret-do-not-use-in-prod")
    monkeypatch.delenv("FIT_ONTOLOGY_REQUIRE_AUTH", raising=False)
    monkeypatch.delenv("FIT_ONTOLOGY_DEMO_MODE", raising=False)
    rate_limit_mod.reset()

    db_path = tmp_path / "intake.duckdb"
    with connect(db_path, read_only=False) as con:
        insert_trainer(con, "t_test", "conal@example.com", "Conal Test")
        set_trainer_password(con, "t_test", "letmein")

    for mod in (auth_routes, clients_routes, intake_routes):
        monkeypatch.setattr(mod, "DEFAULT_DB_PATH", db_path)

    yield TestClient(api_mod.app)


def _login(client: TestClient) -> None:
    r = client.post(
        "/api/auth/login", json={"email": "conal@example.com", "password": "letmein"}
    )
    assert r.status_code == 200, r.text


# ─── Happy path + audit ──────────────────────────────────────────────


def test_authed_mint_returns_token_and_expiry(intake_app):
    _login(intake_app)
    r = intake_app.post(
        "/api/clients/intake/mint", json={"trainer_message": "welcome aboard"}
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert isinstance(data["token"], str) and len(data["token"]) >= 32
    expires_at = datetime.fromisoformat(data["expires_at"])
    assert expires_at > datetime.now(UTC).replace(tzinfo=None)


def test_trainer_message_roundtrips(intake_app):
    _login(intake_app)
    msg = "fill this in before our Tuesday call"
    token = intake_app.post(
        "/api/clients/intake/mint", json={"trainer_message": msg}
    ).json()["token"]

    db_path = intake_routes.DEFAULT_DB_PATH
    with connect(db_path, read_only=True) as con:
        row = con.execute(
            "SELECT trainer_message FROM client_intake_tokens WHERE token = ?",
            [hash_token(token)],
        ).fetchone()
    assert row is not None
    assert row[0] == msg


def test_trainer_message_optional_stores_null(intake_app):
    _login(intake_app)
    token = intake_app.post(
        "/api/clients/intake/mint", json={}
    ).json()["token"]

    db_path = intake_routes.DEFAULT_DB_PATH
    with connect(db_path, read_only=True) as con:
        row = con.execute(
            "SELECT trainer_message FROM client_intake_tokens WHERE token = ?",
            [hash_token(token)],
        ).fetchone()
    assert row is not None
    assert row[0] is None


def test_mint_writes_audit_row(intake_app):
    """Each successful mint writes an ``intake.minted`` row scoped to
    the calling trainer. Lets the trainer reconcile "I sent N links"
    against the audit log later."""
    _login(intake_app)
    intake_app.post("/api/clients/intake/mint", json={})

    db_path = intake_routes.DEFAULT_DB_PATH
    with connect(db_path, read_only=True) as con:
        row = con.execute(
            "SELECT action, trainer_id FROM audit_log WHERE action = ? ORDER BY created_at DESC LIMIT 1",
            ["intake.minted"],
        ).fetchone()
    assert row is not None
    assert row[0] == "intake.minted"
    assert row[1] == "t_test"


# ─── Auth posture ────────────────────────────────────────────────────


def test_anonymous_mint_requires_auth_in_prod_mode(intake_app, monkeypatch):
    """With REQUIRE_AUTH=1 (production posture), an anonymous mint
    request gets 401 from current_trainer_id before the route runs.
    In dev mode current_trainer_id falls back to DEFAULT_TRAINER_ID
    so any anonymous caller can mint AS the default trainer — that's
    fine for solo-dev but unacceptable for the hosted multi-trainer
    deploy, hence the env-var gate."""
    monkeypatch.setenv("FIT_ONTOLOGY_REQUIRE_AUTH", "1")
    r = intake_app.post("/api/clients/intake/mint", json={})
    assert r.status_code == 401


def test_demo_trainer_is_forbidden(intake_app, monkeypatch, tmp_path: Path):
    """forbid_demo_trainer must block a t_demo visitor from minting —
    otherwise the public demo could spam client rows under the demo
    trainer's roster."""
    monkeypatch.setenv("FIT_ONTOLOGY_DEMO_MODE", "1")
    # The fixture's DB exists already; demo seeding will set up t_demo
    # on the next write-mode connect. Force it now by reaching for a
    # connect call.
    db_path = intake_routes.DEFAULT_DB_PATH
    with connect(db_path, read_only=False):
        pass  # demo seed runs in connect()

    r = intake_app.post("/api/clients/intake/mint", json={})
    assert r.status_code == 403


# ─── Validation + rate limit ─────────────────────────────────────────


def test_trainer_message_over_500_chars_is_rejected(intake_app):
    _login(intake_app)
    r = intake_app.post(
        "/api/clients/intake/mint", json={"trainer_message": "x" * 501}
    )
    assert r.status_code == 422  # Pydantic Field max_length


def test_rate_limit_trips_at_21st_call(intake_app):
    """INTAKE_MINT_LIMIT is 20/hour per trainer. The 21st call inside
    the window returns 429."""
    _login(intake_app)
    for i in range(20):
        r = intake_app.post("/api/clients/intake/mint", json={})
        assert r.status_code == 200, f"call {i + 1} should succeed, got {r.status_code}"
    r = intake_app.post("/api/clients/intake/mint", json={})
    assert r.status_code == 429


# ─── Refactor regression ─────────────────────────────────────────────


def test_existing_client_post_still_works(intake_app):
    """insert_client_from_payload was extracted from this route. Pin
    the externally-observable behavior so a future tweak to the
    helper can't silently regress the authed UI's create flow."""
    _login(intake_app)
    r = intake_app.post(
        "/api/clients",
        json={
            "name": "Ben Okafor",
            "sex": "M",
            "age": 32,
            "height_cm": 180.0,
            "weight_kg": 78.0,
            "goal": "Sub-3:15 Chicago, Oct 11",
            "injury_history": None,
        },
    )
    assert r.status_code == 200, r.text
    client_id = r.json()["id"]
    assert client_id.startswith("c_")

    # And the row + audit landed.
    db_path = clients_routes.DEFAULT_DB_PATH
    with connect(db_path, read_only=True) as con:
        client_row = con.execute(
            "SELECT name, sex, trainer_id FROM clients WHERE id = ?",
            [client_id],
        ).fetchone()
        audit_row = con.execute(
            "SELECT action FROM audit_log WHERE target_id = ? AND action = ?",
            [client_id, "client.created"],
        ).fetchone()
    assert client_row == ("Ben Okafor", "M", "t_test")
    assert audit_row == ("client.created",)
