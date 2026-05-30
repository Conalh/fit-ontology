"""Phase 5a — audit log + rate limiting + security headers.

Three concerns, one test file because each one is small and they
share the same TestClient fixture.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient
from starlette.requests import Request

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
    ask as ask_routes,
)
from fit_ontology.routes import (
    auth as auth_routes,
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


# CSP only attaches to HTML responses (see _is_html_response in api.py).
# In a dev environment with ``web/out/`` present the static mount catches
# ``GET /`` and returns index.html — HTML, CSP fires. On CI runners that
# haven't built the Next.js export, the same request falls through to
# FastAPI's default 404 handler which returns JSON — CSP correctly
# skips it, and the CSP assertion in test_csp_present_on_html_responses
# fails because there's no HTML response to attach to. Registering this
# probe route once at module load time gives the CSP tests a
# deterministic HTML target regardless of whether ``web/out/`` is
# bundled in the test environment. ``include_in_schema=False`` keeps it
# out of the OpenAPI doc; the path is namespaced so it can't collide
# with a real route.
def _csp_html_probe() -> HTMLResponse:
    return HTMLResponse("<!doctype html><html><body>csp probe</body></html>")


api_mod.app.add_api_route(
    "/_test_csp_html_probe",
    _csp_html_probe,
    include_in_schema=False,
    methods=["GET"],
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
        auth_routes, share_routes, planning_routes, ask_routes,
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


def test_lazy_persist_routes_404_for_cross_trainer_client(app):
    client, db_path = app
    with connect(db_path, read_only=False) as con:
        insert_trainer(con, "t_other", "other@example.com", "Other")
        ensure_client(con, "t_other", "c_other", name="Other Client")

    assert client.get("/api/clients/c_other/recommendation").status_code == 404
    assert client.get("/api/clients/c_other/plan").status_code == 404
    assert client.get("/api/clients/c_other/thresholds").status_code == 404
    r = client.patch(
        "/api/clients/c_other/thresholds",
        json={"overrides": {"hrv_severe_sd": -2.0}},
    )
    assert r.status_code == 404


def test_plan_patch_rejects_cross_trainer_client_even_if_stale_row_exists(app):
    client, db_path = app
    today = date.today()
    week_of = today - timedelta(days=today.weekday())
    with connect(db_path, read_only=False) as con:
        insert_trainer(con, "t_other", "other2@example.com", "Other")
        ensure_client(con, "t_other", "c_other", name="Other Client")
        con.execute(
            """
            INSERT INTO planned_sessions
              (id, client_id, week_of, slot, type, title, description,
               target_duration_min, target_load_au, target_rpe,
               contraindications, source, generated_at, executed_session_id, trainer_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?)
            """,
            [
                "ps_stale_cross",
                "c_other",
                week_of,
                1,
                "strength",
                "Stale row",
                "Should not be editable",
                45,
                None,
                6.0,
                "[]",
                "trainer",
                None,
                "t_test",
            ],
        )

    r = client.patch("/api/clients/c_other/plan/1", json={"title": "Edited title"})
    assert r.status_code == 404


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


def test_plan_generation_uses_latest_trainer_override_verdict(app):
    """If the trainer overrides this week's call before opening the plan,
    the first generated plan should follow the trainer's exact call."""
    client, _ = app
    today = date.today()
    week_of = today - timedelta(days=today.weekday())

    r = client.post("/api/clients/c_owned/overrides", json={
        "week_of": week_of.isoformat(),
        "system_recommendation": "Deload week: reduce training load by 20%.",
        "system_confidence": 0.9,
        "trainer_action": "reject",
        "trainer_recommendation": "Standard progression per ACSM 11e: increase load 5-10%.",
        "applied_load_change_pct": None,
        "trainer_note": "in-person assessment looked stronger than the wearables",
    })
    assert r.status_code == 200, r.text
    assert r.json()["trainer_recommendation"].startswith("Standard")

    plan = client.get("/api/clients/c_owned/plan")
    assert plan.status_code == 200, plan.text
    body = plan.json()
    assert body["verdict"] == "STANDARD"
    assert len(body["sessions"]) == 4


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


def test_ask_rejects_oversized_question_before_llm(app, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    client, _ = app
    r = client.post("/api/ask", json={"question": "x" * 2001})
    assert r.status_code == 422


def test_ask_rejects_unapproved_model_before_llm(app, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    client, _ = app
    r = client.post(
        "/api/ask",
        json={"question": "summarize this", "model": "claude-opus-expensive"},
    )
    assert r.status_code == 422


def test_ask_unknown_session_returns_404(app, monkeypatch):
    """History is server-side now: a session_id that isn't this trainer's
    (unknown or another trainer's) is a 404, resolved before the LLM is
    ever called."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    client, _ = app
    r = client.post(
        "/api/ask",
        json={"question": "continue please", "session_id": "ask_does_not_exist"},
    )
    assert r.status_code == 404


def _fresh_login_db(tmp_path: Path, monkeypatch, name: str) -> None:
    """Point auth_routes at a fresh DB so login's verify path doesn't hit
    whatever stale file lives at the default path. The rate limiter runs
    before the DB lookup, so we don't even need to seed a trainer —
    wrong-credential 401 still counts toward the bucket and these tests
    only care about the 429 cutover."""
    db_path = tmp_path / name
    with connect(db_path, read_only=False):
        pass
    monkeypatch.setattr(auth_routes, "DEFAULT_DB_PATH", db_path)


def test_login_rate_limit_blocks_after_threshold(tmp_path: Path, monkeypatch):
    """The per-email axis is 10/minute. Patch to 2 to keep the test fast.
    Same IP + same email is the baseline case the limiter must catch."""
    from fit_ontology import rate_limit as rl_mod
    monkeypatch.setattr(rl_mod.LOGIN_EMAIL_LIMIT, "max_attempts", 2)
    rl_mod.reset()
    _fresh_login_db(tmp_path, monkeypatch, "ratelimit.duckdb")

    c = TestClient(api_mod.app)
    for _ in range(2):
        c.post("/api/auth/login", json={"email": "x@example.com", "password": "wrong"})
    r = c.post("/api/auth/login", json={"email": "x@example.com", "password": "wrong"})
    assert r.status_code == 429
    rl_mod.reset()


def test_login_email_limit_survives_ip_rotation(tmp_path: Path, monkeypatch):
    """REGRESSION: the per-email cap must hold even when the attacker
    rotates source IPs. The old combined ``ip|email`` key gave a fresh
    bucket per IP, so an IP-rotating brute-forcer never tripped a
    per-account cap. With the trust flag on, distinct Fly-Client-IP
    values register as distinct source IPs."""
    from fit_ontology import rate_limit as rl_mod
    monkeypatch.setattr(rl_mod.LOGIN_EMAIL_LIMIT, "max_attempts", 2)
    monkeypatch.setattr(rl_mod.LOGIN_IP_LIMIT, "max_attempts", 10_000)  # not the axis under test
    rl_mod.reset()
    monkeypatch.setenv("FIT_ONTOLOGY_TRUST_CLIENT_IP_HEADER", "1")
    _fresh_login_db(tmp_path, monkeypatch, "ratelimit_email.duckdb")

    c = TestClient(api_mod.app)
    for i in range(2):
        c.post(
            "/api/auth/login",
            json={"email": "victim@example.com", "password": "wrong"},
            headers={"Fly-Client-IP": f"203.0.113.{i}"},
        )
    r = c.post(
        "/api/auth/login",
        json={"email": "victim@example.com", "password": "wrong"},
        headers={"Fly-Client-IP": "203.0.113.99"},  # brand-new IP
    )
    assert r.status_code == 429
    rl_mod.reset()


def test_login_ip_limit_survives_email_rotation(tmp_path: Path, monkeypatch):
    """The per-IP cap must hold even when the attacker rotates the email
    (credential-stuffing many accounts from one source)."""
    from fit_ontology import rate_limit as rl_mod
    monkeypatch.setattr(rl_mod.LOGIN_IP_LIMIT, "max_attempts", 2)
    monkeypatch.setattr(rl_mod.LOGIN_EMAIL_LIMIT, "max_attempts", 10_000)  # not the axis under test
    rl_mod.reset()
    monkeypatch.setenv("FIT_ONTOLOGY_TRUST_CLIENT_IP_HEADER", "1")
    _fresh_login_db(tmp_path, monkeypatch, "ratelimit_ip.duckdb")

    c = TestClient(api_mod.app)
    for i in range(2):
        c.post(
            "/api/auth/login",
            json={"email": f"user{i}@example.com", "password": "wrong"},
            headers={"Fly-Client-IP": "198.51.100.7"},
        )
    r = c.post(
        "/api/auth/login",
        json={"email": "user99@example.com", "password": "wrong"},  # brand-new email
        headers={"Fly-Client-IP": "198.51.100.7"},
    )
    assert r.status_code == 429
    rl_mod.reset()


# ─── real_client_ip header trust gating (audit fix #2) ────────────────


def _fake_request(headers: dict[str, str], client_host: str | None) -> Request:
    """Build a minimal ASGI Request with the given headers + peer host."""
    scope = {
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": (client_host, 54321) if client_host else None,
    }
    return Request(scope)


def test_real_client_ip_ignores_forged_header_when_untrusted(monkeypatch):
    """On a self-hosted (non-Fly, no opt-in) deploy, Fly-Client-IP is just
    an attacker-controlled request field — we must NOT believe it, or the
    rate-limit identity can be freely rotated. Falls back to the peer."""
    from fit_ontology.routes.deps import real_client_ip

    for key in ("FIT_ONTOLOGY_TRUST_CLIENT_IP_HEADER", "FLY_APP_NAME", "FLY_MACHINE_ID"):
        monkeypatch.delenv(key, raising=False)
    req = _fake_request({"Fly-Client-IP": "1.2.3.4"}, client_host="10.0.0.9")
    assert real_client_ip(req) == "10.0.0.9"


def test_real_client_ip_trusts_header_on_fly(monkeypatch):
    """Behind Fly's edge (FLY_* injected) the header is authoritative."""
    from fit_ontology.routes.deps import real_client_ip

    monkeypatch.delenv("FIT_ONTOLOGY_TRUST_CLIENT_IP_HEADER", raising=False)
    monkeypatch.setenv("FLY_APP_NAME", "fit-ontology")
    req = _fake_request({"Fly-Client-IP": "1.2.3.4"}, client_host="fdaa::3")
    assert real_client_ip(req) == "1.2.3.4"


def test_real_client_ip_trusts_header_with_explicit_optin(monkeypatch):
    """An operator behind a different trusted proxy can opt in explicitly."""
    from fit_ontology.routes.deps import real_client_ip

    monkeypatch.delenv("FLY_APP_NAME", raising=False)
    monkeypatch.delenv("FLY_MACHINE_ID", raising=False)
    monkeypatch.setenv("FIT_ONTOLOGY_TRUST_CLIENT_IP_HEADER", "1")
    req = _fake_request({"Fly-Client-IP": "1.2.3.4"}, client_host="10.0.0.9")
    assert real_client_ip(req) == "1.2.3.4"


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


# ─── CSP (Phase 5b) ───────────────────────────────────────────────────


def _csp_response(client: TestClient):
    """Force an HTML response so the CSP middleware actually attaches
    the header — /api/health returns JSON and skips CSP by design.
    Hits the test-only HTML probe route registered at module load so
    we're independent of whether ``web/out/`` is bundled (see the
    module-level comment for why this matters on CI)."""
    return client.get("/_test_csp_html_probe")


def test_csp_present_on_html_responses(app):
    """CSP should land on the HTML fall-through (when there's no static
    export mounted, FastAPI returns 404 with text/html — still has the
    header)."""
    client, _ = app
    # Direct route returns JSON — no CSP.
    json_r = client.get("/api/health")
    assert "Content-Security-Policy" not in json_r.headers, (
        "CSP must skip JSON responses — adds bytes, browsers ignore it"
    )

    # Hit a route that returns HTML (any 404 with default error handler
    # serves text/html in Starlette).
    html_r = _csp_response(client)
    csp = html_r.headers.get("Content-Security-Policy", "")
    assert csp, "CSP must be set on HTML responses"
    # Spot-check the directives that actually matter.
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp
    assert "base-uri 'self'" in csp
    assert "form-action 'self'" in csp


def test_csp_never_contains_unsafe_eval(app):
    """Regression guard against a future dep / refactor that introduces
    eval()-style script execution. unsafe-eval is the single CSP
    keyword whose absence we want to assert independently of policy
    iteration."""
    client, _ = app
    html_r = _csp_response(client)
    csp = html_r.headers.get("Content-Security-Policy", "")
    report = html_r.headers.get("Content-Security-Policy-Report-Only", "")
    assert "'unsafe-eval'" not in csp
    assert "'unsafe-eval'" not in report


def test_csp_strict_report_only_off_by_default(app):
    client, _ = app
    html_r = _csp_response(client)
    assert "Content-Security-Policy-Report-Only" not in html_r.headers


def test_csp_strict_report_only_on_when_flag_set(app, monkeypatch):
    monkeypatch.setenv("FIT_ONTOLOGY_CSP_STRICT_REPORT", "1")
    client, _ = app
    html_r = _csp_response(client)
    report = html_r.headers.get("Content-Security-Policy-Report-Only", "")
    assert report, "report-only header must appear when the flag is set"
    # The strict variant has no 'unsafe-inline' on script-src.
    # Pulled apart so the assertion error is readable if it fires.
    script_directives = [
        d.strip() for d in report.split(";") if d.strip().startswith("script-src")
    ]
    assert script_directives, "report-only must include script-src"
    assert "'unsafe-inline'" not in script_directives[0], (
        "report-only's whole purpose is to surface what would break "
        "under strict script-src — 'unsafe-inline' here defeats it"
    )
