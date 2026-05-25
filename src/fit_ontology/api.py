"""FastAPI surface over the fit_ontology modules.

Pragmatic, not RESTful-purist. Route handlers live in ``fit_ontology.routes.*``
and are mounted here; this file is the app factory + cross-cutting concerns
(CORS, the bundled static frontend mount).

Connection lifecycle: every request opens a fresh DuckDB connection
(read-only for reads, write for writes) and closes it on response. We
don't pool — DuckDB is single-writer and the cached-singleton dance
the Streamlit dashboard uses doesn't translate to multi-process ASGI.
The overhead is ~milliseconds, which is fine for this scale.

CORS: open to localhost:3000 in dev so `next dev` can hit the API
running on the FastAPI port. In bundled mode (Next.js static export
served from this same FastAPI process) CORS isn't engaged at all.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from .config import load_env
from .db import DEFAULT_DB_PATH, connect
from .routes import (
    ask,
    auth,
    calibration,
    clients,
    coach,
    metrics,
    overrides,
    pdf,
    planning,
    recommendation,
    roster,
    share,
    thresholds,
)
from .routes.deps import read_only_conn

# Re-export the connection dependency so existing test code that does
# ``api_mod.app.dependency_overrides[api_mod._read_only_conn] = ...``
# keeps working without modification.
_read_only_conn = read_only_conn

load_env()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Open one write-mode connection at startup so the schema DDL +
    migrations + demo-data seed all land before any request arrives.

    Why this matters: the first request after a cold boot is often
    ``GET /api/auth/me`` from the SPA's AuthGuard, which goes through
    a read-only connection. Read-only opens skip migrations + seed
    (DuckDB can't run DDL there anyway). Without this hook, a fresh
    deploy with ``FIT_ONTOLOGY_DEMO_MODE=1`` would have no demo
    trainer in the DB when /me runs, /me would 401, and the guard
    would bounce the visitor to /login — defeating the whole point
    of the public demo.

    The hook also covers the same gap for a non-demo deploy: a fresh
    DB will have its trainers table created + the default trainer
    seeded before the first read-only query needs it.

    Yields immediately after the bootstrap; no teardown work.
    """
    try:
        with connect(DEFAULT_DB_PATH, read_only=False):
            pass
    except Exception as exc:
        # Don't refuse to start over a bootstrap failure — log and
        # let the app come up. The first real write request will
        # surface the actual error with full context.
        import sys
        print(
            f"[fit_ontology.api] WARNING: startup DB bootstrap failed: {exc!r}",
            file=sys.stderr,
        )
    yield


app = FastAPI(title="FitOntology API", version="0.5.1", lifespan=_lifespan)
# NOTE: bumped in lockstep with pyproject.toml; the version string also
# appears in the OpenAPI doc so SDK consumers can pin against it.

app.add_middleware(
    CORSMiddleware,
    # `next dev` runs on 3000 by default. The bundled deploy serves the
    # static export from this same FastAPI process, so the same-origin
    # rule already covers it — we only need CORS for the dev loop.
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Security headers (Phase 5a + 5b) ────────────────────────────────
#
# Phase 5a baselines (every response):
#   X-Frame-Options: DENY                — clickjacking (legacy; CSP
#                                          frame-ancestors supersedes
#                                          this, kept for old browsers)
#   X-Content-Type-Options: nosniff      — MIME sniffing
#   Referrer-Policy: strict-origin-when-cross-origin
#                                        — privacy on outbound links
#   Strict-Transport-Security            — gated on
#                                          FIT_ONTOLOGY_SESSION_SECURE
#                                          (HSTS on http://localhost
#                                          would brick dev until the
#                                          user manually clears HSTS
#                                          state via chrome://net-internals)
#
# Phase 5b CSP (HTML responses only — applies to navigation contexts):
#
#   default-src 'self'        Block any external resource by default.
#                             Every other directive narrows from here.
#   script-src 'self' 'unsafe-inline'
#                             'unsafe-inline' is required because the
#                             Next.js static export injects bootstrap
#                             scripts inline (self.__next_f.push) and
#                             we have no per-request server render to
#                             attach a nonce to them. The XSS surface
#                             this leaves open is bounded by: React
#                             escapes by default, no
#                             dangerouslySetInnerHTML anywhere in the
#                             codebase, no template injection paths.
#                             If a future feature needs nonces (third-
#                             party widgets, embed scripts), we'll
#                             ship the HTML-rewriting middleware then.
#   style-src 'self' 'unsafe-inline'
#                             Every component uses inline style={{}}
#                             attrs that CSP can't hash. Unavoidable
#                             without rewriting the front-end to use
#                             only class-based styling.
#   img-src 'self' data:      data: for inline SVG icons.
#   font-src 'self' data:     next/font emits inline font data: URLs.
#   connect-src 'self'        Same-origin fetches only. The dev cross-
#                             origin loop (Next :3000 → API :8000) is
#                             served by Next dev server which sets no
#                             CSP of its own.
#   frame-ancestors 'none'    Modern clickjacking defense — supersedes
#                             X-Frame-Options, applies even when the
#                             page is iframed from a same-origin parent.
#   base-uri 'self'           Blocks <base href="evil"> redirects.
#   form-action 'self'        Blocks credential-stealing <form
#                             action="evil"> posts.
#   object-src 'none'         No Flash / Java / similar plugin surface.
#
# Optional strict report-only mode (FIT_ONTOLOGY_CSP_STRICT_REPORT=1):
# emits a second header Content-Security-Policy-Report-Only with
# script-src 'self' (no 'unsafe-inline'). Browsers report violations
# in DevTools without enforcing — gives telemetry on what would break
# if we tightened later. No report-uri yet; a future hardening pass
# can add a /api/csp-report endpoint to ingest violations server-side.

_CSP_ENFORCING = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self' data:",
    "connect-src 'self'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
])

_CSP_STRICT_REPORT_ONLY = "; ".join([
    "default-src 'self'",
    "script-src 'self'",  # strict — no 'unsafe-inline'
    "style-src 'self' 'unsafe-inline'",  # inline style attrs unavoidable
    "img-src 'self' data:",
    "font-src 'self' data:",
    "connect-src 'self'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
])


def _is_html_response(response) -> bool:
    """CSP only affects HTML page contexts. Skip it on JSON / static
    asset responses where it's noise — the browser would ignore it
    anyway, but the bytes-on-the-wire add up across hot endpoints."""
    ctype = response.headers.get("content-type", "").lower()
    return "html" in ctype


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        # Lazy env reads so tests that monkeypatch the flags mid-run
        # pick them up without reloading the module.
        env = os.environ
        if env.get("FIT_ONTOLOGY_SESSION_SECURE", "").strip() in {"1", "true", "yes"}:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=63072000; includeSubDomains",
            )
        if _is_html_response(response):
            response.headers.setdefault("Content-Security-Policy", _CSP_ENFORCING)
            if env.get("FIT_ONTOLOGY_CSP_STRICT_REPORT", "").strip() in {"1", "true", "yes"}:
                response.headers.setdefault(
                    "Content-Security-Policy-Report-Only",
                    _CSP_STRICT_REPORT_ONLY,
                )
        return response


app.add_middleware(SecurityHeadersMiddleware)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


# Order doesn't matter for routing — FastAPI matches paths from the
# union of all routers' route tables. Grouped roughly by ontology
# surface (clients → metrics → rec → overrides → calibration → tuning
# → exports → assistant → roster).
app.include_router(auth.router)
app.include_router(share.router)
app.include_router(clients.router)
app.include_router(metrics.router)
app.include_router(recommendation.router)
app.include_router(overrides.router)
app.include_router(calibration.router)
app.include_router(thresholds.router)
app.include_router(planning.router)
app.include_router(pdf.router)
app.include_router(ask.router)
app.include_router(coach.router)
app.include_router(roster.router)


# ─── Static frontend mount ───────────────────────────────────────────
#
# When the Next.js export exists at ``web/out/``, serve it at ``/``
# under this same FastAPI process. Local-first deployment, one URL,
# no CORS round-trip. In dev (no static export) the Next.js dev server
# runs on its own port and hits ``/api`` here via CORS.
#
# Path resolution: in an editable install (local dev), ``__file__``
# is at ``<repo>/src/fit_ontology/api.py`` and ``parents[2]`` lands at
# the repo root — ``web/out`` is right there. In a non-editable
# install (the Docker image, which does ``pip install .``), ``__file__``
# lives in ``site-packages`` and ``parents[2]`` no longer points
# anywhere useful. The Dockerfile sets ``FIT_ONTOLOGY_STATIC_ROOT=
# /app/web/out`` to override the calculation; the fallback below is
# what the local dev loop uses.

_STATIC_ROOT = Path(
    os.environ.get(
        "FIT_ONTOLOGY_STATIC_ROOT",
        str(Path(__file__).resolve().parents[2] / "web" / "out"),
    )
)
if _STATIC_ROOT.exists():
    app.mount("/", StaticFiles(directory=str(_STATIC_ROOT), html=True), name="web")
