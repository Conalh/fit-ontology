"""Phase 2b-α auth surface.

Pins six contracts:
  1. Login with valid email+password sets a signed cookie and returns
     the trainer profile.
  2. Login with a wrong password returns 401 and does NOT set a cookie.
  3. /me returns the trainer when the cookie is valid; 401 when absent.
  4. Logout clears the cookie; subsequent /me is 401.
  5. With FIT_ONTOLOGY_REQUIRE_AUTH unset, scoped routes (e.g. /api/clients)
     fall back to the default trainer when there is no cookie — preserving
     the Cloudflare-Access-only single-trainer deployment.
  6. With FIT_ONTOLOGY_REQUIRE_AUTH=1, those same routes return 401 when
     there is no cookie.

Forged-cookie behavior is covered by the auth module's own unit test —
itsdangerous's bad-signature path is well-trodden; we don't need to
duplicate it via the HTTP layer.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import fit_ontology.api as api_mod
from fit_ontology.auth import (
    COOKIE_NAME,
    cookie_kwargs,
    decode_session,
    encode_session,
)
from fit_ontology.db import (
    DEFAULT_TRAINER_ID,
    connect,
    ensure_client,
    insert_trainer,
    set_trainer_password,
)
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
    recommendation as recommendation_routes,
)
from fit_ontology.routes import (
    thresholds as thresholds_routes,
)

# ─── Fixture ──────────────────────────────────────────────────────────


@pytest.fixture()
def auth_app(tmp_path: Path, monkeypatch):
    """API wired to a temp DuckDB with one trainer ("conal@example.com",
    password "letmein") seeded. The default trainer also exists via the
    migration, but with no password set so login against it would fail —
    the test trainer is the one we authenticate as.

    The fixture pins FIT_ONTOLOGY_SESSION_SECRET so cookies issued in
    one test are decodable from another, and so the dev-mode warning
    doesn't spam the test output.
    """
    monkeypatch.setenv("FIT_ONTOLOGY_SESSION_SECRET", "test-secret-do-not-use-in-prod")
    monkeypatch.delenv("FIT_ONTOLOGY_REQUIRE_AUTH", raising=False)

    db_path = tmp_path / "auth.duckdb"
    with connect(db_path, read_only=False) as con:
        insert_trainer(con, "t_test", "conal@example.com", "Conal Test")
        set_trainer_password(con, "t_test", "letmein")
        # Seed a client under the test trainer so the "/api/clients
        # scoped to current_trainer_id" assertions have something to
        # see when a cookie is presented.
        ensure_client(con, "t_test", "c_owned_by_test", name="Test Client")
        # And a client under the DEFAULT trainer so the fallback-mode
        # assertion has something distinct to see.
        ensure_client(con, DEFAULT_TRAINER_ID, "c_owned_by_default", name="Default Client")

    # Point every route module that opens its own write conn at the
    # temp DB, and shadow the read-only dependency.
    for mod in (clients_routes, metrics_routes, overrides_routes, recommendation_routes, thresholds_routes):
        monkeypatch.setattr(mod, "DEFAULT_DB_PATH", db_path)
    # auth router also opens its own write connection for the login
    # path's read of the trainer row.
    import fit_ontology.routes.auth as auth_routes
    monkeypatch.setattr(auth_routes, "DEFAULT_DB_PATH", db_path)

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


# ─── Auth surface tests ───────────────────────────────────────────────


def test_login_sets_cookie_and_returns_profile(auth_app):
    r = auth_app.post("/api/auth/login", json={"email": "conal@example.com", "password": "letmein"})
    assert r.status_code == 200, r.text
    profile = r.json()
    assert profile == {"id": "t_test", "email": "conal@example.com", "name": "Conal Test"}

    # Cookie present and decodes back to the same trainer_id.
    cookie = r.cookies.get(COOKIE_NAME)
    assert cookie, "login response must set the session cookie"
    assert decode_session(cookie) == "t_test"


def test_login_wrong_password_returns_401_no_cookie(auth_app):
    r = auth_app.post("/api/auth/login", json={"email": "conal@example.com", "password": "wrong"})
    assert r.status_code == 401
    assert COOKIE_NAME not in r.cookies, "failed login must NOT set a cookie"


def test_login_unknown_email_returns_401(auth_app):
    """Same 401 for "no such email" as for "wrong password" — the API
    must not leak whether an email is registered."""
    r = auth_app.post("/api/auth/login", json={"email": "ghost@example.com", "password": "letmein"})
    assert r.status_code == 401


def test_me_returns_trainer_when_cookie_valid(auth_app):
    auth_app.post("/api/auth/login", json={"email": "conal@example.com", "password": "letmein"})
    r = auth_app.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["id"] == "t_test"


def test_me_returns_default_trainer_without_cookie_when_auth_not_required(auth_app):
    """/me drives the SPA auth guard. In dev / single-trainer mode it
    should return the default trainer so a synthetic-data run does not
    strand the user on /login with no password-backed account."""
    r = auth_app.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["id"] == DEFAULT_TRAINER_ID


def test_me_returns_401_without_cookie_when_auth_required(auth_app, monkeypatch):
    monkeypatch.setenv("FIT_ONTOLOGY_REQUIRE_AUTH", "1")
    r = auth_app.get("/api/auth/me")
    assert r.status_code == 401


def test_logout_clears_cookie(auth_app, monkeypatch):
    monkeypatch.setenv("FIT_ONTOLOGY_REQUIRE_AUTH", "1")
    auth_app.post("/api/auth/login", json={"email": "conal@example.com", "password": "letmein"})
    # Sanity: /me sees the trainer
    assert auth_app.get("/api/auth/me").status_code == 200

    logout = auth_app.post("/api/auth/logout")
    assert logout.status_code == 200

    # Cookie cleared client-side — TestClient drops it
    assert auth_app.get("/api/auth/me").status_code == 401


# ─── Cookie-driven scoping on existing routes ─────────────────────────


def test_scoped_route_falls_back_to_default_trainer_when_no_cookie(auth_app, monkeypatch):
    """The Phase 2b-α dev-mode safety net: /api/clients without a
    cookie still returns the DEFAULT trainer's roster so the Cloudflare-
    Access-only dashboard keeps rendering until the login UI lands."""
    monkeypatch.delenv("FIT_ONTOLOGY_REQUIRE_AUTH", raising=False)
    r = auth_app.get("/api/clients")
    assert r.status_code == 200
    ids = [c["id"] for c in r.json()]
    assert "c_owned_by_default" in ids
    assert "c_owned_by_test" not in ids


def test_scoped_route_returns_test_trainer_data_when_cookie_present(auth_app):
    auth_app.post("/api/auth/login", json={"email": "conal@example.com", "password": "letmein"})
    r = auth_app.get("/api/clients")
    assert r.status_code == 200
    ids = [c["id"] for c in r.json()]
    assert "c_owned_by_test" in ids
    assert "c_owned_by_default" not in ids


def test_require_auth_returns_401_when_no_cookie(auth_app, monkeypatch):
    """Production posture: with FIT_ONTOLOGY_REQUIRE_AUTH=1 the scoped
    routes must return 401 rather than falling back to the default."""
    monkeypatch.setenv("FIT_ONTOLOGY_REQUIRE_AUTH", "1")
    r = auth_app.get("/api/clients")
    assert r.status_code == 401


def test_require_auth_still_lets_cookie_through(auth_app, monkeypatch):
    """Sanity: enabling REQUIRE_AUTH doesn't break authenticated requests."""
    monkeypatch.setenv("FIT_ONTOLOGY_REQUIRE_AUTH", "1")
    auth_app.post("/api/auth/login", json={"email": "conal@example.com", "password": "letmein"})
    r = auth_app.get("/api/clients")
    assert r.status_code == 200


# ─── Session module unit tests ────────────────────────────────────────


def test_session_roundtrip_with_known_secret(monkeypatch):
    monkeypatch.setenv("FIT_ONTOLOGY_SESSION_SECRET", "unit-test-secret")
    token = encode_session("t_x")
    assert decode_session(token) == "t_x"


def test_session_roundtrip_with_generated_dev_secret(monkeypatch):
    """The no-env dev fallback should be stable for the process. A
    token signed on login must decode on the next request."""
    import fit_ontology.auth as auth_mod

    monkeypatch.delenv("FIT_ONTOLOGY_SESSION_SECRET", raising=False)
    if hasattr(auth_mod._session_secret, "_cached"):
        delattr(auth_mod._session_secret, "_cached")

    token = encode_session("t_x")
    assert decode_session(token) == "t_x"


def test_session_rejects_tampered_cookie(monkeypatch):
    monkeypatch.setenv("FIT_ONTOLOGY_SESSION_SECRET", "unit-test-secret")
    token = encode_session("t_x")
    # Flip a character — signature must no longer match.
    tampered = token[:-2] + ("A" if token[-2] != "A" else "B") + token[-1]
    assert decode_session(tampered) is None


def test_session_rejects_cookie_signed_with_different_secret(monkeypatch):
    monkeypatch.setenv("FIT_ONTOLOGY_SESSION_SECRET", "old-secret")
    token = encode_session("t_x")
    monkeypatch.setenv("FIT_ONTOLOGY_SESSION_SECRET", "rotated-secret")
    assert decode_session(token) is None


# ─── Cookie Secure flag (dynamic env read) ───────────────────────────
#
# The Secure flag is resolved inside cookie_kwargs() on every cookie
# write rather than captured at import time. The constant version was
# read before api.py's load_env() ran, so a .env value for
# FIT_ONTOLOGY_SESSION_SECURE landed too late to take effect. These
# pin the dynamic behavior so a regression to a module-level constant
# fails loudly.


def test_cookie_secure_off_without_flag(monkeypatch):
    monkeypatch.delenv("FIT_ONTOLOGY_SESSION_SECURE", raising=False)
    assert cookie_kwargs()["secure"] is False


def test_cookie_secure_on_when_flag_set_after_import(monkeypatch):
    """Setting the env var at runtime (as load_env would, after the auth
    module is already imported) must still flip the Secure flag."""
    monkeypatch.setenv("FIT_ONTOLOGY_SESSION_SECURE", "1")
    assert cookie_kwargs()["secure"] is True


# ─── Startup posture ────────────────────────────────────────────────────────

def _clear_startup_env(monkeypatch):
    for key in (
        "FIT_ONTOLOGY_PRODUCTION",
        "FIT_ONTOLOGY_BIND_HOST",
        "FIT_ONTOLOGY_REQUIRE_AUTH",
        "FIT_ONTOLOGY_DEMO_MODE",
        "FIT_ONTOLOGY_PERIMETER_AUTH",
        "FIT_ONTOLOGY_SESSION_SECRET",
        "FLY_APP_NAME",
        "FLY_MACHINE_ID",
    ):
        monkeypatch.delenv(key, raising=False)


def test_startup_config_allows_local_dev_without_auth(monkeypatch):
    _clear_startup_env(monkeypatch)

    api_mod._validate_startup_config()


def test_startup_config_rejects_public_bind_without_auth_or_demo(monkeypatch):
    _clear_startup_env(monkeypatch)
    monkeypatch.setenv("FIT_ONTOLOGY_BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("FIT_ONTOLOGY_SESSION_SECRET", "test-secret")

    with pytest.raises(RuntimeError, match="FIT_ONTOLOGY_REQUIRE_AUTH"):
        api_mod._validate_startup_config()


def test_startup_config_rejects_production_without_session_secret(monkeypatch):
    _clear_startup_env(monkeypatch)
    monkeypatch.setenv("FIT_ONTOLOGY_PRODUCTION", "1")
    monkeypatch.setenv("FIT_ONTOLOGY_REQUIRE_AUTH", "1")

    with pytest.raises(RuntimeError, match="FIT_ONTOLOGY_SESSION_SECRET"):
        api_mod._validate_startup_config()


def test_startup_config_allows_public_demo_with_session_secret(monkeypatch):
    _clear_startup_env(monkeypatch)
    monkeypatch.setenv("FIT_ONTOLOGY_PRODUCTION", "1")
    monkeypatch.setenv("FIT_ONTOLOGY_DEMO_MODE", "1")
    monkeypatch.setenv("FIT_ONTOLOGY_SESSION_SECRET", "test-secret")

    api_mod._validate_startup_config()


def test_startup_config_allows_public_perimeter_auth_with_session_secret(monkeypatch):
    _clear_startup_env(monkeypatch)
    monkeypatch.setenv("FIT_ONTOLOGY_PRODUCTION", "1")
    monkeypatch.setenv("FIT_ONTOLOGY_PERIMETER_AUTH", "1")
    monkeypatch.setenv("FIT_ONTOLOGY_SESSION_SECRET", "test-secret")

    api_mod._validate_startup_config()


# ─── DB bootstrap failure posture ────────────────────────────────────


def test_bootstrap_fails_closed_in_production(monkeypatch):
    """A production-like runtime must refuse to start if the schema /
    migration / seed bootstrap fails, rather than serve traffic against a
    half-initialised DB."""
    _clear_startup_env(monkeypatch)
    monkeypatch.setenv("FIT_ONTOLOGY_PRODUCTION", "1")

    def _boom(*args, **kwargs):
        raise RuntimeError("schema DDL exploded")

    monkeypatch.setattr(api_mod, "connect", _boom)
    with pytest.raises(RuntimeError, match="Refusing to start"):
        api_mod._bootstrap_db()


def test_bootstrap_logs_and_continues_in_dev(monkeypatch):
    """Local dev keeps the log-and-continue behaviour so a transient lock
    doesn't block the inner loop."""
    _clear_startup_env(monkeypatch)

    def _boom(*args, **kwargs):
        raise RuntimeError("transient lock")

    monkeypatch.setattr(api_mod, "connect", _boom)
    # No raise — returns normally after logging.
    api_mod._bootstrap_db()
