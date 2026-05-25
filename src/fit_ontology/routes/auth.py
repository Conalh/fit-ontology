"""Login / logout / me — Phase 2b-α auth surface.

Three endpoints, deliberately small:
  - POST /api/auth/login    {email, password} → 200 + cookie / 401
  - POST /api/auth/logout   → 200, clears cookie
  - GET  /api/auth/me       → 200 {id, email, name} / 401

Rate limiting: a coarse in-process per-IP counter for /login is enough
for Phase 2b-α — the real story (slowapi + Redis when multi-process)
lands in Phase 5's security pass. The simple counter blocks the
"script someone runs against the API for an hour" failure mode without
adding infrastructure.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..auth import COOKIE_NAME, cookie_kwargs, decode_session, encode_session
from ..db import DEFAULT_DB_PATH, connect, get_trainer, verify_trainer_login
from .deps import read_only_conn
from .schemas import AuthMeResponse, LoginRequest

router = APIRouter()


# ─── /login rate limit (in-process) ───────────────────────────────────
#
# Window = 60s, max 10 attempts per (IP, email) pair. Both axes
# because IP-only lets one shared NAT lock out a whole office, and
# email-only lets an attacker burn through credential stuffing one
# email at a time from any IP. The pair caps both. Single-process
# only — when the deploy goes to multiple workers (Phase 4), swap to
# slowapi backed by Redis.

_LOGIN_WINDOW_SECONDS = 60
_LOGIN_MAX_ATTEMPTS = 10
_login_attempts: dict[tuple[str, str], deque] = defaultdict(deque)


def _rate_limit_login(ip: str, email: str) -> None:
    """Raise 429 if (ip, email) has too many attempts in the window.
    Records this attempt on success."""
    key = (ip, email.lower())
    now = time.monotonic()
    bucket = _login_attempts[key]
    # Evict expired entries from the front.
    while bucket and bucket[0] < now - _LOGIN_WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= _LOGIN_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Try again in a minute.",
        )
    bucket.append(now)


@router.post("/api/auth/login", response_model=AuthMeResponse)
def post_login(
    payload: LoginRequest,
    request: Request,
    response: Response,
) -> AuthMeResponse:
    """Verify email + password, set the signed session cookie, return
    the trainer profile so the front-end can populate its sidebar
    without an extra /me round-trip."""
    client_ip = request.client.host if request.client else "unknown"
    _rate_limit_login(client_ip, payload.email)

    with connect(DEFAULT_DB_PATH, read_only=True) as con:
        trainer_id = verify_trainer_login(con, payload.email, payload.password)
        if trainer_id is None:
            # Uniform 401 — the helper already paid the dummy-hash cost
            # so timing is roughly the same whether the email is known
            # or not.
            raise HTTPException(status_code=401, detail="Invalid credentials")
        row = get_trainer(con, trainer_id)

    # Issue the cookie + return the profile. The cookie's max-age is
    # set inside cookie_kwargs(); set_cookie also sends a Set-Cookie
    # header that the browser overwrites the prior session with.
    response.set_cookie(value=encode_session(trainer_id), **cookie_kwargs())
    return AuthMeResponse(id=row[0], email=row[1], name=row[2])


@router.post("/api/auth/logout")
def post_logout(response: Response) -> dict:
    """Clear the session cookie. Idempotent — a logout request with no
    cookie still returns 200 so a stale tab doesn't show an error
    bubble for trying to log out of a session that's already gone."""
    # delete_cookie writes Set-Cookie with Max-Age=0 + an empty value.
    # Same path / samesite as the issue path or the browser won't match
    # the cookie to clear.
    response.delete_cookie(key=COOKIE_NAME, path="/", samesite="lax")
    return {"ok": True}


@router.get("/api/auth/me", response_model=AuthMeResponse)
def get_me(
    request: Request,
    con=Depends(read_only_conn),
) -> AuthMeResponse:
    """Returns the trainer associated with the request's session cookie.

    Intentionally does NOT honor FIT_ONTOLOGY_REQUIRE_AUTH's
    fallback-to-default — /me is the endpoint the front-end calls to
    decide "show the login form or the dashboard?" and it must answer
    that honestly regardless of dev-mode shortcuts elsewhere.
    """
    token = request.cookies.get(COOKIE_NAME, "")
    trainer_id = decode_session(token)
    if not trainer_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    row = get_trainer(con, trainer_id)
    if not row:
        # Cookie signed a trainer that no longer exists (deleted account).
        raise HTTPException(status_code=401, detail="Trainer not found")
    return AuthMeResponse(id=row[0], email=row[1], name=row[2])
