"""Login / logout / me — Phase 2b-α auth surface.

Three endpoints, deliberately small:
  - POST /api/auth/login    {email, password} → 200 + cookie / 401
  - POST /api/auth/logout   → 200, clears cookie
  - GET  /api/auth/me       → 200 {id, email, name} / 401

Rate limiting uses the shared rate_limit module (Phase 5a) — login
keeps its (IP, email) pair-keyed bucket, which is now declared
centrally alongside the limits on /ask and /share-mint.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..auth import COOKIE_NAME, cookie_kwargs, decode_session, encode_session
from ..db import (
    DEFAULT_DB_PATH,
    DEFAULT_TRAINER_ID,
    connect,
    get_trainer,
    record_audit,
    verify_trainer_login,
)
from ..rate_limit import LOGIN_LIMIT, enforce
from .deps import read_only_conn
from .schemas import AuthMeResponse, LoginRequest

router = APIRouter()


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
    # Rate limit keyed on (ip, email) — see rate_limit.LOGIN_LIMIT
    # docstring for the both-axes rationale.
    enforce(LOGIN_LIMIT, f"{client_ip}|{payload.email.lower()}")

    # Verify under a read-only connection — keeps login uncoupled
    # from whichever process happens to hold the writer lock (sync
    # scripts, the assistant, the dashboard saving an override).
    # A login that can't succeed because the DB is being written to
    # is a worse failure mode than missing one audit row.
    with connect(DEFAULT_DB_PATH, read_only=True) as con:
        trainer_id = verify_trainer_login(con, payload.email, payload.password)
        if trainer_id is None:
            # Uniform 401 — the helper already paid the dummy-hash cost
            # so timing is roughly the same whether the email is known
            # or not. We deliberately do NOT audit-log failed logins
            # here: the rate limiter handles attempt-tracking, and a
            # flood of failures would just pollute a trainer's audit
            # history without adding signal a real intrusion response
            # wouldn't already have from access logs.
            raise HTTPException(status_code=401, detail="Invalid credentials")
        row = get_trainer(con, trainer_id)

    # Best-effort audit write — see write-paths comment in db.py.
    # If this fails, the user still gets their cookie and the login
    # is honored; only the audit row is missing.
    try:
        with connect(DEFAULT_DB_PATH, read_only=False) as wcon:
            record_audit(wcon, trainer_id, "auth.login", ip=client_ip)
    except Exception:
        pass

    # Issue the cookie + return the profile. The cookie's max-age is
    # set inside cookie_kwargs(); set_cookie also sends a Set-Cookie
    # header that the browser overwrites the prior session with.
    response.set_cookie(value=encode_session(trainer_id), **cookie_kwargs())
    return AuthMeResponse(id=row[0], email=row[1], name=row[2])


@router.post("/api/auth/logout")
def post_logout(request: Request, response: Response) -> dict:
    """Clear the session cookie. Idempotent — a logout request with no
    cookie still returns 200 so a stale tab doesn't show an error
    bubble for trying to log out of a session that's already gone."""
    # Audit only the case where there was actually a session to log
    # out of. A logout-with-no-cookie is a noop from the audit POV.
    token = request.cookies.get(COOKIE_NAME, "")
    trainer_id = decode_session(token) if token else None
    if trainer_id:
        client_ip = request.client.host if request.client else None
        try:
            with connect(DEFAULT_DB_PATH, read_only=False) as con:
                record_audit(con, trainer_id, "auth.logout", ip=client_ip)
        except Exception:
            # Don't fail the logout just because the audit write
            # contended — the user is leaving, not their problem.
            pass

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

    Resolution mirrors ``current_trainer_id``:
      - valid cookie → that trainer
      - no cookie + FIT_ONTOLOGY_DEMO_MODE=1 → demo trainer
      - no cookie + FIT_ONTOLOGY_REQUIRE_AUTH=1 → 401
      - no cookie + neither → default trainer (dev / Cloudflare
        Access posture)

    Demo precedes REQUIRE_AUTH so an unauthenticated visitor to the
    hosted portfolio deploy gets the demo trainer's profile instead
    of being asked to log in.
    """
    from ..demo import DEMO_TRAINER_ID, is_demo_enabled

    token = request.cookies.get(COOKIE_NAME, "")
    trainer_id = decode_session(token)
    if not trainer_id:
        if is_demo_enabled():
            trainer_id = DEMO_TRAINER_ID
        elif os.environ.get("FIT_ONTOLOGY_REQUIRE_AUTH", "").strip() in {"1", "true", "yes"}:
            raise HTTPException(status_code=401, detail="Not authenticated")
        else:
            trainer_id = DEFAULT_TRAINER_ID
    row = get_trainer(con, trainer_id)
    if not row:
        # Cookie signed a trainer that no longer exists (deleted account).
        raise HTTPException(status_code=401, detail="Trainer not found")
    return AuthMeResponse(id=row[0], email=row[1], name=row[2])
