"""Phase 3b public intake surface (M3 milestone).

Helper-level invariants are in test_intake_tokens.py; the mint
endpoint is in test_intake_mint.py. This file covers the two
unauthenticated endpoints:

  GET  /api/intake/{token}   form-page preflight
  POST /api/intake/{token}   form submission

Contracts pinned:
  1. GET returns trainer_name + trainer_message + expiry +
     consumed=False for a fresh token. Trainer_id is NOT in the
     payload — it's an internal id, never leaked.
  2. GET 404 on unknown token, 410 on expired, 410 if the trainer
     was deleted after mint (token points at a roster that no
     longer exists).
  3. GET on a consumed token returns 200 with consumed=True so the
     page can render a personalized "you already submitted to
     {trainer}" state — more useful UX than a generic 410.
  4. POST happy path: token resolves, client row is inserted scoped
     to the token's trainer_id, and POST returns {ok, id}.
  5. POST atomically consumes the token: a second POST with the
     same token returns 410, and only ONE client row was created
     in total (no stranded row from a race-lost insert).
  6. POST cross-trainer isolation: the new client appears only in
     the minting trainer's roster, never in another trainer's.
  7. POST writes an ``intake.submitted`` audit row scoped to the
     resolved trainer, with the new client_id as the target.
  8. POST 404/410 on unknown/expired/consumed before any insert.
  9. POST rate-limits per IP (INTAKE_SUBMIT_LIMIT = 10/hour).
 10. POST validation: ClientCreate field violations return 422
     before the token is consumed (a malformed submission shouldn't
     burn the token).
"""
from __future__ import annotations

from datetime import datetime, timedelta
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

GOOD_PAYLOAD = {
    "name": "Ada Chen",
    "sex": "F",
    "age": 34,
    "height_cm": 168.0,
    "weight_kg": 62.5,
    "goal": "First half marathon, sub-2:00",
    "injury_history": "Mild left hip stiffness on long runs",
}


@pytest.fixture()
def intake_app(tmp_path: Path, monkeypatch):
    """API wired to a temp DB with two trainers so cross-trainer
    isolation tests have somewhere to verify against."""
    monkeypatch.setenv("FIT_ONTOLOGY_SESSION_SECRET", "test-secret-do-not-use-in-prod")
    monkeypatch.delenv("FIT_ONTOLOGY_REQUIRE_AUTH", raising=False)
    monkeypatch.delenv("FIT_ONTOLOGY_DEMO_MODE", raising=False)
    rate_limit_mod.reset()

    db_path = tmp_path / "intake.duckdb"
    with connect(db_path, read_only=False) as con:
        insert_trainer(con, "t_alice", "alice@example.com", "Alice Trainer")
        set_trainer_password(con, "t_alice", "letmein")
        insert_trainer(con, "t_bob", "bob@example.com", "Bob Trainer")
        set_trainer_password(con, "t_bob", "letmein")

    for mod in (auth_routes, clients_routes, intake_routes):
        monkeypatch.setattr(mod, "DEFAULT_DB_PATH", db_path)

    # The GET endpoint uses the read_only_conn dependency, which
    # opens DEFAULT_DB_PATH via the deps module's own reference —
    # override to point at the test DB.
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


def _login_as(client: TestClient, email: str) -> None:
    r = client.post("/api/auth/login", json={"email": email, "password": "letmein"})
    assert r.status_code == 200, r.text


def _mint_as(client: TestClient, email: str, message: str | None = None) -> str:
    _login_as(client, email)
    r = client.post(
        "/api/clients/intake/mint",
        json={"trainer_message": message} if message else {},
    )
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    client.cookies.clear()  # drop session so subsequent calls are anonymous
    return token


# ─── GET preflight ───────────────────────────────────────────────────


def test_get_returns_trainer_name_and_message(intake_app):
    token = _mint_as(intake_app, "alice@example.com", "Fill this in before Tuesday")
    r = intake_app.get(f"/api/intake/{token}")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["trainer_name"] == "Alice Trainer"
    assert data["trainer_message"] == "Fill this in before Tuesday"
    assert data["consumed"] is False
    # No internal id leaked.
    assert "trainer_id" not in data


def test_get_404_for_unknown_token(intake_app):
    r = intake_app.get("/api/intake/not-a-real-token")
    assert r.status_code == 404


def test_get_410_for_expired_token(intake_app):
    token = _mint_as(intake_app, "alice@example.com")
    db_path = intake_routes.DEFAULT_DB_PATH
    with connect(db_path, read_only=False) as con:
        con.execute(
            "UPDATE client_intake_tokens SET expires_at = ? WHERE token = ?",
            [datetime.utcnow() - timedelta(days=1), hash_token(token)],
        )
    r = intake_app.get(f"/api/intake/{token}")
    assert r.status_code == 410


def test_get_410_if_trainer_deleted_after_mint(intake_app):
    """Edge case: the trainer row is removed (manual cleanup) after
    a token was minted. The token is technically still valid but
    points at a roster that no longer exists. Treat as expired —
    same posture as share.py's "client deleted after mint" path."""
    token = _mint_as(intake_app, "alice@example.com")
    db_path = intake_routes.DEFAULT_DB_PATH
    with connect(db_path, read_only=False) as con:
        con.execute("DELETE FROM trainers WHERE id = ?", ["t_alice"])
    r = intake_app.get(f"/api/intake/{token}")
    assert r.status_code == 410


def test_get_consumed_token_returns_200_with_flag(intake_app):
    """After submission, the GET still works but carries
    consumed=True so the page can render a personalized 'you
    already submitted to {trainer}' state."""
    token = _mint_as(intake_app, "alice@example.com", "Welcome!")
    r = intake_app.post(f"/api/intake/{token}", json=GOOD_PAYLOAD)
    assert r.status_code == 200, r.text

    r = intake_app.get(f"/api/intake/{token}")
    assert r.status_code == 200
    data = r.json()
    assert data["consumed"] is True
    assert data["trainer_name"] == "Alice Trainer"
    assert data["trainer_message"] == "Welcome!"


# ─── POST submission ─────────────────────────────────────────────────


def test_submit_happy_path_creates_client(intake_app):
    token = _mint_as(intake_app, "alice@example.com")
    r = intake_app.post(f"/api/intake/{token}", json=GOOD_PAYLOAD)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["id"].startswith("c_")

    # And the row is scoped to Alice (the minting trainer).
    db_path = intake_routes.DEFAULT_DB_PATH
    with connect(db_path, read_only=True) as con:
        row = con.execute(
            "SELECT trainer_id, name, sex, age FROM clients WHERE id = ?",
            [data["id"]],
        ).fetchone()
    assert row == ("t_alice", "Ada Chen", "F", 34)


def test_submit_is_one_shot(intake_app):
    """The atomic-consume guarantee at the HTTP level: a second POST
    with the same token returns 410, and exactly ONE client row was
    created (no stranded insert from a race-lost claim)."""
    token = _mint_as(intake_app, "alice@example.com")
    first = intake_app.post(f"/api/intake/{token}", json=GOOD_PAYLOAD)
    assert first.status_code == 200, first.text

    second = intake_app.post(
        f"/api/intake/{token}",
        json={**GOOD_PAYLOAD, "name": "Imposter"},
    )
    assert second.status_code == 410

    db_path = intake_routes.DEFAULT_DB_PATH
    with connect(db_path, read_only=True) as con:
        count = con.execute(
            "SELECT COUNT(*) FROM clients WHERE trainer_id = ?", ["t_alice"]
        ).fetchone()
        imposters = con.execute(
            "SELECT COUNT(*) FROM clients WHERE name = ?", ["Imposter"]
        ).fetchone()
    assert count[0] == 1
    assert imposters[0] == 0


def test_submit_is_scoped_to_minting_trainer(intake_app):
    """Cross-trainer isolation: Alice mints, the client submits, the
    new row appears in Alice's roster — NOT Bob's."""
    token = _mint_as(intake_app, "alice@example.com")
    r = intake_app.post(f"/api/intake/{token}", json=GOOD_PAYLOAD)
    assert r.status_code == 200

    db_path = intake_routes.DEFAULT_DB_PATH
    with connect(db_path, read_only=True) as con:
        alice = con.execute(
            "SELECT COUNT(*) FROM clients WHERE trainer_id = ?", ["t_alice"]
        ).fetchone()
        bob = con.execute(
            "SELECT COUNT(*) FROM clients WHERE trainer_id = ?", ["t_bob"]
        ).fetchone()
    assert alice[0] == 1
    assert bob[0] == 0


def test_submit_writes_audit_row(intake_app):
    token = _mint_as(intake_app, "alice@example.com")
    r = intake_app.post(f"/api/intake/{token}", json=GOOD_PAYLOAD)
    client_id = r.json()["id"]

    db_path = intake_routes.DEFAULT_DB_PATH
    with connect(db_path, read_only=True) as con:
        row = con.execute(
            """
            SELECT action, trainer_id, target_id
            FROM audit_log
            WHERE action = ? AND target_id = ?
            """,
            ["intake.submitted", client_id],
        ).fetchone()
    assert row == ("intake.submitted", "t_alice", client_id)


def test_submit_404_for_unknown_token(intake_app):
    r = intake_app.post("/api/intake/no-such-token", json=GOOD_PAYLOAD)
    assert r.status_code == 404


def test_submit_410_for_expired_token(intake_app):
    token = _mint_as(intake_app, "alice@example.com")
    db_path = intake_routes.DEFAULT_DB_PATH
    with connect(db_path, read_only=False) as con:
        con.execute(
            "UPDATE client_intake_tokens SET expires_at = ? WHERE token = ?",
            [datetime.utcnow() - timedelta(days=1), hash_token(token)],
        )
    r = intake_app.post(f"/api/intake/{token}", json=GOOD_PAYLOAD)
    assert r.status_code == 410


def test_validation_error_doesnt_burn_token(intake_app):
    """A malformed submission (e.g. age out of range) returns 422
    BEFORE the token is consumed — the prospective client should be
    able to fix the form and resubmit, not be locked out by their
    own typo."""
    token = _mint_as(intake_app, "alice@example.com")
    bad = {**GOOD_PAYLOAD, "age": 5}  # ClientCreate requires age >= 10
    r = intake_app.post(f"/api/intake/{token}", json=bad)
    assert r.status_code == 422

    # Token still works for a corrected submission.
    r = intake_app.post(f"/api/intake/{token}", json=GOOD_PAYLOAD)
    assert r.status_code == 200, r.text


def test_submit_rate_limit_per_ip(intake_app):
    """INTAKE_SUBMIT_LIMIT is 10/hour per IP. The 11th call returns
    429 regardless of whether previous calls used valid tokens (a
    malformed-token flood is exactly what we're defending against
    here — they all bounce 404, but each one counts against the
    bucket so the 11th hit is rate-limited)."""
    # 10 cheap 404s against unknown tokens — all count against the
    # per-IP bucket.
    for i in range(10):
        r = intake_app.post(f"/api/intake/probe-{i}", json=GOOD_PAYLOAD)
        # 404 expected on unknown tokens; the assertion below cares
        # about the bucket, not the status here.
        assert r.status_code in (404, 410), f"unexpected status on call {i}: {r.status_code}"
    r = intake_app.post("/api/intake/probe-final", json=GOOD_PAYLOAD)
    assert r.status_code == 429
