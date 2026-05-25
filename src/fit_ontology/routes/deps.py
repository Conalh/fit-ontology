"""Per-request DuckDB connection + current-trainer dependencies.

Every read endpoint takes a fresh read-only connection via this
dependency and closes it on response. We don't pool — DuckDB is
single-writer and the cached-singleton dance the Streamlit dashboard
uses doesn't translate to multi-process ASGI. The overhead is
~milliseconds, which is fine for this scale.

``current_trainer_id`` is the single seam that resolves the calling
trainer's id. In Phase 2b-α it reads the signed session cookie set
by /api/auth/login. When no cookie is present the behavior is
controlled by FIT_ONTOLOGY_REQUIRE_AUTH:

  - unset / "0" (default): fall back to ``DEFAULT_TRAINER_ID``. This
    preserves the single-trainer dashboard that ships behind
    Cloudflare Access — the perimeter is the auth, the app's own
    login is opt-in. Removes once Phase 2b-β ships the login UI.
  - "1": raise 401. The production multi-tenant posture.
"""
from __future__ import annotations

import os
from collections.abc import Iterator

import duckdb
from fastapi import HTTPException, Request

from ..auth import COOKIE_NAME, decode_session
from ..db import DEFAULT_DB_PATH, DEFAULT_TRAINER_ID, connect


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
      1. Signed ``fo_session`` cookie → decoded trainer_id
      2. No cookie + FIT_ONTOLOGY_REQUIRE_AUTH=1 → 401
      3. No cookie + auth not required → DEFAULT_TRAINER_ID (Phase
         2b-α back-compat for the Cloudflare-Access-only deployment)

    A *present-but-invalid* cookie (forged, tampered, or expired) also
    falls through to step 2/3 — we can't tell legitimate "logged out"
    from "cookie was rejected" without a state table, and the security
    impact is the same: the bearer cannot prove an identity.
    """
    token = request.cookies.get(COOKIE_NAME, "")
    decoded = decode_session(token)
    if decoded:
        return decoded
    if _require_auth():
        raise HTTPException(status_code=401, detail="Not authenticated")
    return DEFAULT_TRAINER_ID
