"""Phase 4 demo mode.

Pins the contracts that make a hosted portfolio deploy actually
usable:

  1. Seed on first boot — when DEMO_MODE=1 and the DB has no demo
     data, connect() loads the synthetic dataset under the demo
     trainer. Idempotent: a second connect doesn't re-load.
  2. /me without cookie + DEMO_MODE on → returns the demo trainer
     (even when REQUIRE_AUTH=1, which is the production posture).
  3. /me without cookie + DEMO_MODE off + REQUIRE_AUTH=1 → 401.
  4. forbid_demo_trainer dependency raises 403 with a friendly
     message when the calling trainer is the demo trainer.
  5. Mutating routes all return 403 for an unauthenticated visitor
     in demo mode: clients POST, clients PATCH, override POST,
     plan PATCH, share POST, coach draft POST, thresholds PATCH,
     metrics upload POST.
  6. Lazy-persist GET routes serve data but skip the persistence
     branch when the calling trainer is the demo trainer (no row
     lands in recommendations/planned_sessions).
  7. The demo trainer's data is properly trainer-scoped — it does
     not leak into the default trainer's queries.
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
    connect,
    list_clients,
)
from fit_ontology.demo import (
    DEMO_TRAINER_EMAIL,
    DEMO_TRAINER_ID,
    is_demo_enabled,
    seed_demo_data_if_needed,
)
from fit_ontology.rate_limit import reset as rate_limit_reset
from fit_ontology.routes import (
    auth as auth_routes,
)
from fit_ontology.routes import (
    clients as clients_routes,
)
from fit_ontology.routes import (
    coach as coach_routes,
)
from fit_ontology.routes import (
    metrics as metrics_routes,
)
from fit_ontology.routes import (
    overrides as overrides_routes,
)
from fit_ontology.routes import (
    planning as planning_routes,
)
from fit_ontology.routes import (
    recommendation as recommendation_routes,
)
from fit_ontology.routes import (
    share as share_routes,
)
from fit_ontology.routes import (
    thresholds as thresholds_routes,
)

# ─── Module-level helper contract tests ───────────────────────────────


def test_is_demo_enabled_reads_env_at_call_time(monkeypatch):
    monkeypatch.delenv("FIT_ONTOLOGY_DEMO_MODE", raising=False)
    assert is_demo_enabled() is False
    monkeypatch.setenv("FIT_ONTOLOGY_DEMO_MODE", "1")
    assert is_demo_enabled() is True
    monkeypatch.setenv("FIT_ONTOLOGY_DEMO_MODE", "0")
    assert is_demo_enabled() is False


def test_seed_demo_data_is_idempotent(tmp_path: Path, monkeypatch):
    """First call seeds the synthetic clients; second call is a no-op.
    Both end up with the same row count — the idempotence is what
    makes seeding-on-every-connect safe."""
    monkeypatch.setenv("FIT_ONTOLOGY_DEMO_MODE", "1")
    db_path = tmp_path / "demo_seed.duckdb"

    with connect(db_path, read_only=False) as con:
        seed_demo_data_if_needed(con)
        first_clients = list_clients(con, DEMO_TRAINER_ID)
        seed_demo_data_if_needed(con)
        second_clients = list_clients(con, DEMO_TRAINER_ID)

    assert not first_clients.empty, "first seed must produce demo clients"
    assert len(second_clients) == len(first_clients), (
        "second seed must be a no-op (idempotent)"
    )


def test_seed_demo_data_isolates_from_default_trainer(tmp_path: Path, monkeypatch):
    """The default trainer must NOT see demo data in their list_clients
    query — trainer scoping has to hold even for seeded content."""
    monkeypatch.setenv("FIT_ONTOLOGY_DEMO_MODE", "1")
    db_path = tmp_path / "demo_iso.duckdb"

    with connect(db_path, read_only=False) as con:
        seed_demo_data_if_needed(con)
        demo = list_clients(con, DEMO_TRAINER_ID)
        default = list_clients(con, DEFAULT_TRAINER_ID)

    assert not demo.empty
    assert default.empty, (
        "default trainer must not see demo clients via list_clients"
    )


def test_connect_auto_seeds_when_demo_mode_on(tmp_path: Path, monkeypatch):
    """The whole point of demo mode: a fresh deploy with DEMO_MODE=1
    boots into a working demo on the very first connect(), no manual
    seed step required."""
    monkeypatch.setenv("FIT_ONTOLOGY_DEMO_MODE", "1")
    db_path = tmp_path / "auto_seed.duckdb"

    # connect() itself should trigger the seed.
    with connect(db_path, read_only=False) as con:
        clients = list_clients(con, DEMO_TRAINER_ID)
    assert not clients.empty


def test_connect_skips_seed_when_demo_mode_off(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("FIT_ONTOLOGY_DEMO_MODE", raising=False)
    db_path = tmp_path / "no_seed.duckdb"

    with connect(db_path, read_only=False) as con:
        clients = list_clients(con, DEMO_TRAINER_ID)
    assert clients.empty, (
        "DEMO_MODE off must not load demo data even on first connect"
    )


# ─── HTTP-level tests ─────────────────────────────────────────────────


@pytest.fixture()
def demo_app(tmp_path: Path, monkeypatch):
    """API wired to a temp DB with DEMO_MODE=1 + REQUIRE_AUTH=1 (the
    production posture for a hosted portfolio deploy). Session secret
    pinned so cookies are reproducible. Rate-limit buckets reset
    between tests."""
    monkeypatch.setenv("FIT_ONTOLOGY_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("FIT_ONTOLOGY_DEMO_MODE", "1")
    monkeypatch.setenv("FIT_ONTOLOGY_REQUIRE_AUTH", "1")
    rate_limit_reset()

    db_path = tmp_path / "demo.duckdb"
    # Initial connect runs the auto-seed.
    with connect(db_path, read_only=False):
        pass

    for mod in (
        clients_routes,
        metrics_routes,
        overrides_routes,
        recommendation_routes,
        thresholds_routes,
        auth_routes,
        share_routes,
        planning_routes,
        coach_routes,
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
        yield TestClient(api_mod.app), db_path
    finally:
        api_mod.app.dependency_overrides.pop(api_mod._read_only_conn, None)
        rate_limit_reset()


def test_me_returns_demo_trainer_without_cookie(demo_app):
    """The headline contract: a public visitor hits /me with no
    cookie and gets the demo trainer back — not a 401 — even though
    REQUIRE_AUTH is on. That's how the SPA's auth guard ends up
    rendering the demo dashboard for the public."""
    client, _db = demo_app
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["id"] == DEMO_TRAINER_ID
    assert r.json()["email"] == DEMO_TRAINER_EMAIL


def test_demo_visitor_can_list_clients(demo_app):
    """A read-only roster fetch should succeed and return the seeded
    demo clients."""
    client, _db = demo_app
    r = client.get("/api/clients")
    assert r.status_code == 200
    ids = [c["id"] for c in r.json()]
    # The synthetic dataset has three clients: c_alice, c_ben, c_carla.
    assert set(ids) >= {"c_alice", "c_ben", "c_carla"}


def test_demo_visitor_cannot_create_client(demo_app):
    client, _db = demo_app
    r = client.post("/api/clients", json={
        "name": "New", "sex": "F", "age": 30,
        "height_cm": 168.0, "weight_kg": 60.0, "goal": "g",
    })
    assert r.status_code == 403
    assert "Demo mode" in r.json()["detail"]


def test_demo_visitor_cannot_patch_client(demo_app):
    client, _db = demo_app
    r = client.patch("/api/clients/c_alice", json={"name": "Hijack"})
    assert r.status_code == 403


def test_demo_visitor_cannot_save_override(demo_app):
    client, _db = demo_app
    r = client.post("/api/clients/c_alice/overrides", json={
        "week_of": str(date.today()),
        "system_recommendation": "x",
        "system_confidence": 0.5,
        "trainer_action": "accept",
        "applied_load_change_pct": None,
        "trainer_note": None,
    })
    assert r.status_code == 403


def test_demo_visitor_cannot_mint_share(demo_app):
    client, _db = demo_app
    r = client.post("/api/clients/c_alice/share", json={"trainer_message": None})
    assert r.status_code == 403


def test_demo_visitor_cannot_patch_thresholds(demo_app):
    client, _db = demo_app
    r = client.patch("/api/clients/c_alice/thresholds",
                     json={"overrides": {"hrv_severe_sd": -2.0}})
    assert r.status_code == 403


def test_demo_visitor_cannot_upload(demo_app):
    client, _db = demo_app
    files = {"file": ("metrics.csv", b"id,date\n", "text/csv")}
    r = client.post("/api/clients/c_alice/upload", files=files)
    assert r.status_code == 403


def test_demo_visitor_cannot_patch_plan_slot(demo_app):
    client, _db = demo_app
    r = client.patch("/api/clients/c_alice/plan/1", json={"title": "Hijack"})
    assert r.status_code == 403


def test_recommendation_get_skips_persist_for_demo(demo_app):
    """Demo lazy-persist gate. /recommendation returns a verdict but
    must NOT write a recommendations row — otherwise every demo
    visitor pollutes the writer lock and the audit log."""
    client, db_path = demo_app

    # Count rows before.
    with connect(db_path, read_only=True) as con:
        before = con.execute(
            "SELECT COUNT(*) FROM recommendations WHERE trainer_id = ?",
            [DEMO_TRAINER_ID],
        ).fetchone()[0]

    r = client.get("/api/clients/c_alice/recommendation")
    assert r.status_code == 200
    assert r.json()["recommendation"]  # got a verdict

    with connect(db_path, read_only=True) as con:
        after = con.execute(
            "SELECT COUNT(*) FROM recommendations WHERE trainer_id = ?",
            [DEMO_TRAINER_ID],
        ).fetchone()[0]
    assert after == before, "demo /recommendation must not persist"


def test_plan_get_skips_persist_for_demo(demo_app):
    """Same shape for plan: visitor gets a plan rendered, but no
    planned_sessions row gets written for the demo trainer."""
    client, db_path = demo_app

    with connect(db_path, read_only=True) as con:
        before = con.execute(
            "SELECT COUNT(*) FROM planned_sessions WHERE trainer_id = ?",
            [DEMO_TRAINER_ID],
        ).fetchone()[0]

    r = client.get("/api/clients/c_alice/plan")
    assert r.status_code == 200
    body = r.json()
    assert body["sessions"], "plan must contain at least one slot"

    with connect(db_path, read_only=True) as con:
        after = con.execute(
            "SELECT COUNT(*) FROM planned_sessions WHERE trainer_id = ?",
            [DEMO_TRAINER_ID],
        ).fetchone()[0]
    assert after == before, "demo /plan must not persist"


def test_coach_draft_blocked_for_demo(demo_app, monkeypatch):
    """Coach Assistant burns Anthropic quota — demo visitors shouldn't
    be able to drain the API budget."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    client, _db = demo_app
    r = client.post("/api/clients/c_alice/coach-message/draft")
    assert r.status_code == 403


def test_demo_mode_off_means_normal_auth_behavior(tmp_path: Path, monkeypatch):
    """Sanity: with DEMO_MODE off and REQUIRE_AUTH on, /me 401s for
    an unauthenticated visitor. The demo behavior is opt-in."""
    monkeypatch.setenv("FIT_ONTOLOGY_SESSION_SECRET", "test-secret")
    monkeypatch.delenv("FIT_ONTOLOGY_DEMO_MODE", raising=False)
    monkeypatch.setenv("FIT_ONTOLOGY_REQUIRE_AUTH", "1")
    rate_limit_reset()

    db_path = tmp_path / "no_demo.duckdb"
    with connect(db_path, read_only=False):
        pass

    monkeypatch.setattr(auth_routes, "DEFAULT_DB_PATH", db_path)

    def _ro():
        c = connect(db_path, read_only=True)
        try:
            yield c
        finally:
            c.close()

    api_mod.app.dependency_overrides[api_mod._read_only_conn] = _ro
    try:
        client = TestClient(api_mod.app)
        r = client.get("/api/auth/me")
        assert r.status_code == 401
    finally:
        api_mod.app.dependency_overrides.pop(api_mod._read_only_conn, None)
