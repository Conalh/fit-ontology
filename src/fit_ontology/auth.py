"""Session-cookie auth (roadmap Phase 2b-α).

The login surface is intentionally narrow: a signed cookie carries the
trainer_id, FastAPI decodes it on every request via the
``current_trainer_id`` dependency in routes/deps.py, and the routes
themselves stay shaped exactly as Phase 2a left them.

Why itsdangerous rather than a JWT library: the only claim we need is
``trainer_id`` and a server-side max-age. itsdangerous's URLSafeTimed-
Serializer signs and timestamps in one line each. A full JWT (header,
claims, alg negotiation, JWK rotation) brings surface area we don't
need until Phase 4's cross-service auth.

Why a signed cookie rather than server-stored sessions: DuckDB is
single-writer, and a sessions table would mean every authenticated
request takes the write lock just to extend the session row. The
cookie carries the only state we care about (trainer_id) and the TTL
is enforced by the signature's embedded timestamp.

Security posture for Phase 2b-α:
  - HttpOnly so client-side JS can't read the cookie
  - SameSite=Lax so a third-party site can't trick the browser into
    submitting an authenticated request
  - Secure flag toggled by env var so dev (http://localhost) works
    while production (https://app.mobility.rest) requires HTTPS
  - 14-day max age, refreshed on every login (no sliding window —
    that's Phase 2b-β with the UI for "log out everywhere")
"""
from __future__ import annotations

import os
import secrets

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

COOKIE_NAME = "fo_session"

# 14 days. Long enough that a returning trainer doesn't have to log
# back in every workday; short enough that a stolen cookie expires on
# its own without admin intervention.
SESSION_MAX_AGE_SECONDS = 14 * 24 * 60 * 60

def _cookie_secure() -> bool:
    """Whether the session cookie should be sent only over HTTPS.

    Read lazily on every cookie write rather than captured in a
    module-level constant at import time. The constant version was a
    footgun: ``api.py`` imports the route modules (which import this
    module) *before* it calls ``load_env()``, so a ``.env`` value for
    ``FIT_ONTOLOGY_SESSION_SECURE`` landed too late to be seen — the
    cookie would silently ship without the Secure flag in a local
    HTTPS-fronted deploy. Resolving at call time also matches the
    SecurityHeadersMiddleware, which already reads the same flag lazily
    for HSTS, and lets a test monkeypatch the env var mid-run.

    Dev environments (next dev on localhost) need this off; production
    should always set ``FIT_ONTOLOGY_SESSION_SECURE=1`` explicitly.
    """
    return os.environ.get("FIT_ONTOLOGY_SESSION_SECURE", "").strip() in {"1", "true", "yes"}


def _session_secret() -> str:
    """The secret used to sign the session cookie.

    Resolution order:
      1. ``FIT_ONTOLOGY_SESSION_SECRET`` env var — required in any
         deployment where two restarts must produce compatible cookies
         (which is every deployment except a one-shot test run).
      2. A randomly-generated string per process, with a stderr warning.
         This keeps the dev loop working without forcing every
         contributor to set an env var, but every restart invalidates
         every existing session — which is exactly what you want in dev
         and exactly what you don't want in production.

    We resolve lazily (rather than at import) so a test can set the env
    var via monkeypatch.setenv() before any session work happens.
    """
    secret = os.environ.get("FIT_ONTOLOGY_SESSION_SECRET", "").strip()
    if secret:
        return secret
    cached = getattr(_session_secret, "_cached", None)
    if cached:
        return cached
    # Dev fallback. ``secrets.token_urlsafe`` is cryptographically
    # strong; the warning is only because restarting the process
    # invalidates every active session.
    import sys
    fallback = secrets.token_urlsafe(32)
    print(
        "[fit_ontology.auth] WARNING: FIT_ONTOLOGY_SESSION_SECRET not set; "
        "generated a per-process secret. Existing sessions will be invalidated "
        "on restart. Set this env var in any non-dev deployment.",
        file=sys.stderr,
    )
    # Cache on the function so subsequent calls in the same process
    # return the same value without re-warning.
    _session_secret._cached = fallback  # type: ignore[attr-defined]
    return fallback


def _serializer() -> URLSafeTimedSerializer:
    """Build a fresh serializer each call so a monkey-patched secret
    (in tests) takes effect immediately."""
    return URLSafeTimedSerializer(_session_secret(), salt="fit_ontology.session.v1")


def encode_session(trainer_id: str) -> str:
    """Serialize and sign a trainer_id into a session cookie value."""
    return _serializer().dumps(trainer_id)


def decode_session(token: str) -> str | None:
    """Verify a session cookie and return its trainer_id, or None if
    the cookie is missing, tampered, or older than ``SESSION_MAX_AGE_SECONDS``.

    No exception leaks out — the calling dependency treats every failure
    mode identically (no authenticated trainer)."""
    if not token:
        return None
    try:
        return _serializer().loads(token, max_age=SESSION_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None


def cookie_kwargs() -> dict:
    """Common kwargs for FastAPI's Response.set_cookie. Centralized so
    every cookie write uses the same security flags."""
    return {
        "key": COOKIE_NAME,
        "httponly": True,
        "secure": _cookie_secure(),
        "samesite": "lax",
        "max_age": SESSION_MAX_AGE_SECONDS,
        "path": "/",
    }
