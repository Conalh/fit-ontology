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

# Load .env BEFORE importing any module that reads the environment at
# import time — ``db.DEFAULT_DB_PATH``, ``db.DEFAULT_TRAINER_*``, the
# auth cookie flags, etc. all resolve env vars when their module is
# first imported. Importing them first and calling load_env() afterward
# silently ignored local .env overrides (the cookie-Secure footgun the
# reviewer flagged, and the same latent bug for FIT_ONTOLOGY_DB). The
# imports below therefore sit after this call on purpose; E402 is
# suppressed for them.
load_env()

from .db import DEFAULT_DB_PATH, connect  # noqa: E402
from .routes import (  # noqa: E402
    actions,
    ask,
    auth,
    calibration,
    clients,
    coach,
    delta,
    intake,
    metrics,
    overrides,
    pdf,
    planning,
    recommendation,
    roster,
    share,
    thresholds,
)
from .routes.deps import read_only_conn  # noqa: E402

# Re-export the connection dependency so existing test code that does
# ``api_mod.app.dependency_overrides[api_mod._read_only_conn] = ...``
# keeps working without modification.
_read_only_conn = read_only_conn


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


def _is_public_bind_host(host: str) -> bool:
    normalized = host.strip().lower()
    if not normalized:
        return False
    return normalized not in {"127.0.0.1", "localhost", "::1"}


def _is_production_like_runtime() -> bool:
    """Return True when insecure dev fallbacks should be refused.

    The ASGI app cannot see Uvicorn's bind host unless the launcher sets
    it, so ``serve.py`` stamps FIT_ONTOLOGY_BIND_HOST before boot. Docker
    images set FIT_ONTOLOGY_PRODUCTION=1 directly because they launch
    Uvicorn without the console wrapper.
    """
    return (
        _truthy_env("FIT_ONTOLOGY_PRODUCTION")
        or bool(os.environ.get("FLY_APP_NAME") or os.environ.get("FLY_MACHINE_ID"))
        or _is_public_bind_host(os.environ.get("FIT_ONTOLOGY_BIND_HOST", ""))
    )


def _validate_startup_config() -> None:
    """Fail closed before serving an internet-facing process.

    Local development keeps the no-auth default trainer fallback. Any
    production-like runtime must either require app auth, run explicit
    read-only demo mode, or declare that an external perimeter auth layer
    is responsible for access control.
    """
    if not _is_production_like_runtime():
        return

    has_app_auth = _truthy_env("FIT_ONTOLOGY_REQUIRE_AUTH")
    has_demo = _truthy_env("FIT_ONTOLOGY_DEMO_MODE")
    has_perimeter_auth = _truthy_env("FIT_ONTOLOGY_PERIMETER_AUTH")
    if not (has_app_auth or has_demo or has_perimeter_auth):
        raise RuntimeError(
            "Refusing to start public FitOntology runtime without "
            "FIT_ONTOLOGY_REQUIRE_AUTH=1, FIT_ONTOLOGY_DEMO_MODE=1, or "
            "FIT_ONTOLOGY_PERIMETER_AUTH=1."
        )

    if not os.environ.get("FIT_ONTOLOGY_SESSION_SECRET", "").strip():
        raise RuntimeError(
            "Refusing to start public FitOntology runtime without "
            "FIT_ONTOLOGY_SESSION_SECRET."
        )


def _init_sentry() -> None:
    """Initialise Sentry if FIT_ONTOLOGY_SENTRY_DSN is set.

    No-op when the env var is empty (the dev + portfolio-demo default)
    so the sentry-sdk dependency stays optional and the SDK doesn't
    silently send error telemetry from a developer's laptop. Same
    posture as the demo-mode and require-auth flags: every prod-only
    behaviour is opt-in via env var.

    sentry-sdk is imported lazily so a build without the dep can still
    boot — the only cost is a no-op call to this function. The
    FastAPI integration auto-captures uncaught exceptions in route
    handlers + middleware; logging integration ships every WARNING+
    log line as a breadcrumb so the operator gets context on the
    state leading up to a crash.
    """
    dsn = os.environ.get("FIT_ONTOLOGY_SENTRY_DSN", "").strip()
    if not dsn:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
    except ImportError:
        import sys
        print(
            "[fit_ontology.api] WARNING: FIT_ONTOLOGY_SENTRY_DSN is set but "
            "sentry-sdk is not installed. Install with `pip install -e .[monitoring]` "
            "to enable error reporting.",
            file=sys.stderr,
        )
        return
    # ``environment`` is what the Sentry UI uses to filter dev vs prod;
    # the same DSN can carry both. Default to "production" since this
    # function only runs when the DSN is configured at all, which
    # rarely happens locally.
    environment = os.environ.get("FIT_ONTOLOGY_SENTRY_ENV", "production")
    # ``release`` carries the app version so Sentry can correlate
    # errors against deploys. Matches the FastAPI version string below.
    release = os.environ.get("FIT_ONTOLOGY_RELEASE", "fit-ontology@0.5.1")
    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,
        # Performance + profiling sampling at 0.1 = capture 10% of
        # request traces. A free-tier-budget-friendly default for a
        # portfolio app; raise if events get sparse.
        traces_sample_rate=0.1,
        profiles_sample_rate=0.1,
        integrations=[
            FastApiIntegration(transaction_style="endpoint"),
            LoggingIntegration(level=None, event_level=None),
        ],
        # Don't send PII automatically (route params, request bodies,
        # user-Agent etc.). Trainer + client emails are PII; an
        # uncaught exception in an auth route would otherwise surface
        # the attempted email in the Sentry event.
        send_default_pii=False,
    )


_init_sentry()


def _bootstrap_db() -> None:
    """Open one write-mode connection so the schema DDL + migrations +
    demo-data seed all land before any request arrives.

    Why this matters: the first request after a cold boot is often
    ``GET /api/auth/me`` from the SPA's AuthGuard, which goes through
    a read-only connection. Read-only opens skip migrations + seed
    (DuckDB can't run DDL there anyway). Without this hook, a fresh
    deploy with ``FIT_ONTOLOGY_DEMO_MODE=1`` would have no demo
    trainer in the DB when /me runs, /me would 401, and the guard
    would bounce the visitor to /login — defeating the whole point
    of the public demo. The same gap applies to a non-demo deploy: a
    fresh DB needs its trainers table created + default trainer seeded
    before the first read-only query needs it.

    Failure posture: fail CLOSED in a production-like runtime. Serving
    traffic against a DB whose schema/migration/seed didn't complete
    means cross-tenant scoping columns, the audit table, or the default
    trainer might be missing — better to refuse the boot than to answer
    requests from a half-initialised database. Local dev keeps the
    log-and-continue behaviour so a transient lock during the inner loop
    doesn't block startup; the first real write surfaces the error with
    full context anyway.
    """
    try:
        with connect(DEFAULT_DB_PATH, read_only=False):
            pass
    except Exception as exc:
        if _is_production_like_runtime():
            raise RuntimeError(
                "Refusing to start: DB bootstrap (schema/migration/seed) "
                f"failed in a production-like runtime: {exc!r}"
            ) from exc
        import sys
        print(
            f"[fit_ontology.api] WARNING: startup DB bootstrap failed: {exc!r}",
            file=sys.stderr,
        )


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Validate startup config, bootstrap the DB, then serve. Yields
    immediately after the bootstrap; no teardown work."""
    _validate_startup_config()
    _bootstrap_db()
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
app.include_router(actions.router)
app.include_router(share.router)
app.include_router(intake.router)
app.include_router(clients.router)
app.include_router(delta.router)
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
