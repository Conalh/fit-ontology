"""Per-request DuckDB connection + current-trainer dependencies.

Every read endpoint takes a fresh read-only connection via this
dependency and closes it on response. We don't pool — DuckDB is
single-writer and the cached-singleton dance the Streamlit dashboard
uses doesn't translate to multi-process ASGI. The overhead is
~milliseconds, which is fine for this scale.

``current_trainer_id`` is the single seam that resolves the calling
trainer's id. It reads the signed session cookie set by
/api/auth/login first; when no cookie is present, three modes apply
in order of precedence:

  - FIT_ONTOLOGY_DEMO_MODE=1   → return DEMO_TRAINER_ID. Overrides
                                  REQUIRE_AUTH on purpose: a hosted
                                  portfolio deploy needs to show
                                  read-only content to unauthenticated
                                  visitors even when real-trainer auth
                                  is gated.
  - FIT_ONTOLOGY_REQUIRE_AUTH=1 → 401. Production multi-tenant
                                  posture.
  - neither                     → return DEFAULT_TRAINER_ID. Dev /
                                  Cloudflare-Access-only deployment;
                                  the perimeter is the auth, the app's
                                  own login is opt-in.

``forbid_demo_trainer`` is a small companion dependency that
mutating routes use to reject the demo trainer with HTTP 403. It
runs AFTER ``current_trainer_id`` so the chain is: resolve trainer
→ check it's not the demo trainer → proceed.
"""
from __future__ import annotations

import os
from collections.abc import Iterator

import duckdb
from fastapi import Depends, HTTPException, Request

from ..auth import COOKIE_NAME, decode_session
from ..db import DEFAULT_DB_PATH, DEFAULT_TRAINER_ID, connect
from ..demo import DEMO_TRAINER_ID, is_demo_enabled, is_demo_trainer


def read_only_conn() -> Iterator[duckdb.DuckDBPyConnection]:
    """Per-request read-only connection. Closed in the dependency's
    teardown so we don't leak handles across requests."""
    con = connect(DEFAULT_DB_PATH, read_only=True)
    try:
        yield con
    finally:
        con.close()


def _require_auth() -> bool:
    """Read the flag at call time rather than at module import so a
    test or a hot-reloaded config picks up changes without restart."""
    return os.environ.get("FIT_ONTOLOGY_REQUIRE_AUTH", "").strip() in {"1", "true", "yes"}


def current_trainer_id(request: Request) -> str:
    """The trainer the current request acts as.

    Order of resolution:
      1. Signed ``fo_session`` cookie → decoded trainer_id (any
         logged-in trainer wins regardless of demo mode).
      2. No cookie + FIT_ONTOLOGY_DEMO_MODE=1 → DEMO_TRAINER_ID.
         Demo intentionally precedes REQUIRE_AUTH so a public
         visitor sees the demo dashboard even on a production
         deploy where REQUIRE_AUTH is also on.
      3. No cookie + FIT_ONTOLOGY_REQUIRE_AUTH=1 → 401.
      4. No cookie + neither flag → DEFAULT_TRAINER_ID
         (Cloudflare-Access-only deployment).

    A *present-but-invalid* cookie (forged, tampered, or expired)
    falls through to step 2/3/4 — we can't tell legitimate "logged
    out" from "cookie was rejected" without a state table, and the
    security impact is identical: the bearer cannot prove an
    identity.
    """
    token = request.cookies.get(COOKIE_NAME, "")
    decoded = decode_session(token)
    if decoded:
        return decoded
    if is_demo_enabled():
        return DEMO_TRAINER_ID
    if _require_auth():
        raise HTTPException(status_code=401, detail="Not authenticated")
    return DEFAULT_TRAINER_ID


def _trust_client_ip_header() -> bool:
    """Whether to believe the client-supplied ``Fly-Client-IP`` header.

    ``Fly-Client-IP`` is only authoritative when the request actually
    transited Fly's edge proxy — the proxy sets it and a direct client
    cannot. On a self-hosted deploy (behind nginx/caddy, or nothing) the
    header is just an attacker-controlled request field: trusting it
    unconditionally lets a caller forge any source IP and so rotate the
    rate-limit identity at will, bypassing INTAKE_SUBMIT_LIMIT (the only
    public write surface) and the per-IP login axis. So we trust it only
    when we can tell we're behind Fly (the FLY_* env vars Fly injects), or
    when an operator behind a different trusted proxy opts in explicitly.

    Read at call time, not import, so a test can monkeypatch the env and
    so a hot-reloaded config takes effect without a restart — same
    posture as the auth cookie flags.
    """
    if os.environ.get("FIT_ONTOLOGY_TRUST_CLIENT_IP_HEADER", "").strip() in {"1", "true", "yes"}:
        return True
    return bool(os.environ.get("FLY_APP_NAME") or os.environ.get("FLY_MACHINE_ID"))


def real_client_ip(request: Request) -> str | None:
    """Best-effort real client IP, accounting for the reverse proxy.

    On Fly the app is only reachable through the edge proxy, so
    ``request.client.host`` is the proxy's private 6PN address —
    identical for every external visitor. That breaks the per-IP
    rate-limit identity (intake submit, the login IP axis) and makes
    every ``audit_log.ip`` useless. Fly sets ``Fly-Client-IP`` to the
    real client address authoritatively, so prefer it WHEN we trust the
    header (see ``_trust_client_ip_header`` — gated so an untrusted
    deploy can't be fed a forged header). Fall back to the peer address —
    which uvicorn rewrites from ``X-Forwarded-For`` when launched with
    ``--proxy-headers`` (see Dockerfile) — for non-Fly proxies and local
    dev.
    """
    if _trust_client_ip_header():
        fly = request.headers.get("fly-client-ip")
        if fly:
            return fly.strip()
    return request.client.host if request.client else None


def forbid_demo_trainer(trainer_id: str = Depends(current_trainer_id)) -> str:
    """Mutating-route guard: 403 if the calling trainer is the demo
    trainer. Composed with ``current_trainer_id`` so a route only
    needs ``trainer_id = Depends(forbid_demo_trainer)`` to get both
    the resolved id and the demo-rejection — no double Depends.

    Returns the trainer_id on success so the route signature is the
    same shape as Depends(current_trainer_id).
    """
    if is_demo_trainer(trainer_id):
        raise HTTPException(
            status_code=403,
            detail="Demo mode is read-only. Run FitOntology locally to save changes.",
        )
    return trainer_id
